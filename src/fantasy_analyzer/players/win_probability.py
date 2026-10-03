"""Win probability for a weekly matchup (FFA-114).

Each team's final score is modelled as a normal variable. The mean ``mu`` is
the team's expected points (actual points for games already played, the
projection for games still to come -- computed upstream by FFA-113). The
variance is the sum, over the starters whose games are still *pending*, of a
fitted single-week per-player variance::

    sd^2 = sum_i  s(position_i, projection_i)^2           (pending starters)

    P(me) = Phi( (mu_me - mu_opp) / (lambda * sqrt(sd_me^2 + sd_opp^2)) )

``s`` takes one of two forms, chosen by held-out Gaussian likelihood in
``scripts/fit_win_probability.py``:

``"constant"``
    ``s = a_position``.
``"sqrt"``
    ``s = c_position * sqrt(max(projection, MIN_SQRT_PROJECTION))`` -- a
    Poisson-like variance proportional to the projection.

``lambda`` (:attr:`WinProbabilityParameters.margin_sd_multiplier`) is one
fitted inflation factor on the margin's standard deviation. It absorbs what
the independence sum ignores: within-team correlation (a shootout lifts a
QB and his receivers together) and surprise inactives.

Edge rules
--------------------------------------------------------------------------

* **Ties.** A normal variable has no point mass, so ``P(tie) = 0`` and
  ``P(me) + P(opponent) = 1`` exactly. A real exact tie in the *fitting*
  data is dropped, not scored.
* **No variance left.** If both teams' standard deviations are 0 (every
  starter's game is final) the formula is undefined; the answer is the sign
  of the margin: ``1.0`` / ``0.0``, and ``0.5`` for an exact tie.
* **Missing projection.** A NaN or non-finite projection is read as ``0``;
  a negative one is clipped to ``0``. Under the sqrt form the projection is
  then floored at :data:`MIN_SQRT_PROJECTION` so a zero projection does not
  give a zero SD. Under the constant form the projection is not used.
* **Unknown position.** :attr:`~WinProbabilityParameters.default_coefficient`.
  ``DST`` / ``D/ST`` are read as ``DEF``
  (:data:`~fantasy_analyzer.players.roster_fit.POSITION_ALIASES`).
* **Regular season vs playoff.** The model is agnostic: it is fitted on
  regular-season weeks only and applied unchanged to playoff weeks by the
  caller, if at all. Nothing here knows about the calendar.

Everything in this module is pure: no network, no file access except the
explicit save/load pair.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

from fantasy_analyzer.players.roster_fit import POSITION_ALIASES

#: Where ``scripts/fit_win_probability.py`` writes the fitted parameters.
DEFAULT_WIN_PROBABILITY_PARAMETERS_PATH = Path(
    ".cache/nflverse/win_probability_parameters.json"
)

FORM_CONSTANT = "constant"
FORM_SQRT = "sqrt"
SD_FORMS = (FORM_CONSTANT, FORM_SQRT)

#: Floor (fantasy points) on the projection inside the sqrt form.
MIN_SQRT_PROJECTION = 1.0


@dataclass(frozen=True)
class WinProbabilityParameters:
    """Fitted constants of the win-probability model.

    Attributes:
        form: ``"constant"`` or ``"sqrt"`` (see the module docstring).
        coefficients: Position -> ``a_pos`` (constant) or ``c_pos`` (sqrt).
        default_coefficient: Used for a position with no coefficient.
        margin_sd_multiplier: ``lambda``, the margin-SD inflation factor.
        calibrated: ``False`` when the team-level calibration of ``lambda``
            could not be run (``lambda`` is then a placeholder 1.0). A
            consumer must not show a probability from an uncalibrated set.
        metadata: Provenance -- fitted seasons, sample sizes, metrics.
            Built-in JSON types only.
    """

    form: str
    coefficients: dict[str, float]
    default_coefficient: float
    margin_sd_multiplier: float
    calibrated: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.form not in SD_FORMS:
            raise ValueError(f"form must be one of {SD_FORMS}; got {self.form!r}.")
        if not (
            math.isfinite(self.margin_sd_multiplier) and self.margin_sd_multiplier > 0
        ):
            raise ValueError(
                "margin_sd_multiplier must be finite and > 0; "
                f"got {self.margin_sd_multiplier!r}."
            )
        values = [self.default_coefficient, *self.coefficients.values()]
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise ValueError("coefficients must be finite and >= 0.")


def save_win_probability_parameters(
    parameters: WinProbabilityParameters,
    path: Union[str, Path] = DEFAULT_WIN_PROBABILITY_PARAMETERS_PATH,
) -> Path:
    """Persist a fitted parameter set as JSON and return the path written.

    Mirrors ``save_usage_model_parameters``: built-in types only, sorted
    keys, parent directories created.
    """
    payload = {
        "form": parameters.form,
        "coefficients": {
            str(key): float(value) for key, value in parameters.coefficients.items()
        },
        "default_coefficient": float(parameters.default_coefficient),
        "margin_sd_multiplier": float(parameters.margin_sd_multiplier),
        "calibrated": bool(parameters.calibrated),
        "metadata": parameters.metadata,
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n"
    )
    return destination


def _json_default(value: object) -> object:
    """Coerce numpy scalars/arrays that leak into ``metadata``."""
    if hasattr(value, "tolist"):
        return value.tolist()  # type: ignore[attr-defined]
    raise TypeError(f"Not JSON serialisable: {type(value).__name__}")


def load_win_probability_parameters(
    path: Union[str, Path] = DEFAULT_WIN_PROBABILITY_PARAMETERS_PATH,
) -> Optional[WinProbabilityParameters]:
    """Load a persisted parameter set, or ``None`` if missing or unusable.

    A missing file and a corrupt one both return ``None`` -- the dashboard's
    fallback (show the projected margin only) is the same for either.
    """
    source = Path(path)
    if not source.exists():
        return None
    try:
        payload = json.loads(source.read_text())
        return WinProbabilityParameters(
            form=str(payload["form"]),
            coefficients={
                str(key): float(value) for key, value in payload["coefficients"].items()
            },
            default_coefficient=float(payload["default_coefficient"]),
            margin_sd_multiplier=float(payload["margin_sd_multiplier"]),
            calibrated=bool(payload["calibrated"]),
            metadata=dict(payload.get("metadata", {})),
        )
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return None


def _clean_projection(projection: object) -> float:
    """A projection as a non-negative finite float (NaN/None -> 0, negative -> 0)."""
    try:
        value = float(projection)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(value, 0.0)


def _coefficient(position: object, parameters: WinProbabilityParameters) -> float:
    """The position's coefficient, resolving aliases; default when unknown."""
    if position is None or (isinstance(position, float) and math.isnan(position)):
        return parameters.default_coefficient
    label = POSITION_ALIASES.get(str(position), str(position))
    return parameters.coefficients.get(label, parameters.default_coefficient)


def player_score_sd(
    position: str, projection: float, parameters: WinProbabilityParameters
) -> float:
    """Single-week score SD of one pending player.

    Args:
        position: Sleeper position; ``DST``/``D/ST`` count as ``DEF``. An
            unknown or missing position uses the default coefficient.
        projection: The player's expected points this week. NaN is read as
            0 and a negative value is clipped to 0 (see the module
            docstring); the constant form ignores it.
        parameters: The fitted set.

    Returns:
        ``a_pos`` (constant form) or
        ``c_pos * sqrt(max(projection, MIN_SQRT_PROJECTION))`` (sqrt form).
    """
    coefficient = _coefficient(position, parameters)
    if parameters.form == FORM_CONSTANT:
        return coefficient
    return coefficient * math.sqrt(
        max(_clean_projection(projection), MIN_SQRT_PROJECTION)
    )


def team_score_sd(
    lineup: pd.DataFrame,
    parameters: WinProbabilityParameters,
    *,
    position_column: str = "position",
    projection_column: str = "projection",
    pending_column: str = "pending",
) -> float:
    """SD of a team's final score: root-sum-square over its pending starters.

    Rows whose ``pending`` flag is false (or missing/NaN) contribute nothing:
    a game already played has no variance left. An empty lineup gives 0.0.
    The defaults match FFA-113's ``SlotRow`` columns.
    """
    if lineup.empty:
        return 0.0
    pending = lineup[pending_column].fillna(False).astype(bool)
    variance = 0.0
    for position, projection in zip(
        lineup.loc[pending, position_column], lineup.loc[pending, projection_column]
    ):
        variance += player_score_sd(position, projection, parameters) ** 2
    return math.sqrt(variance)


def _normal_cdf(value: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def win_probability(
    mean: float,
    sd: float,
    opponent_mean: float,
    opponent_sd: float,
    parameters: WinProbabilityParameters,
) -> float:
    """Probability that the first team outscores the second.

    ``Phi((mean - opponent_mean) / (lambda * sqrt(sd^2 + opponent_sd^2)))``.
    With no variance on either side the result is the sign of the margin
    (1.0 / 0.0, or 0.5 for an exact tie); ties have probability zero
    otherwise.

    Raises:
        ValueError: A mean is not finite or an SD is negative / not finite.
    """
    if not all(math.isfinite(value) for value in (mean, opponent_mean)):
        raise ValueError("means must be finite.")
    if not all(math.isfinite(value) and value >= 0 for value in (sd, opponent_sd)):
        raise ValueError("standard deviations must be finite and >= 0.")
    margin = mean - opponent_mean
    spread = parameters.margin_sd_multiplier * math.sqrt(sd**2 + opponent_sd**2)
    if spread == 0.0:
        if margin > 0:
            return 1.0
        if margin < 0:
            return 0.0
        return 0.5
    return _normal_cdf(margin / spread)
