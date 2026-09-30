"""Opportunity-first rest-of-season projection (FFA-111).

:mod:`fantasy_analyzer.players.ros_projection` shrinks a player's points
per game toward his prior. That prices him on points, so it inherits the
touchdown trap its own docstring names: a player whose season to date is
touchdown-driven is valued on the least repeatable thing he did. This
module rebuilds the projection from what *is* repeatable -- how often he is
given the ball -- and reintroduces efficiency and touchdowns only after
regressing each one by an amount fitted to how noisy it is.

It answers the same question, on the same rows, as the harness in
:mod:`fantasy_analyzer.players.ros_backtest`: at cutoff week ``w``, what
will each player average per game over weeks ``w+1..17``?

The model
--------------------------------------------------------------------------

Per player, per position (QB, RB, WR, TE -- :data:`MODELED_POSITIONS`):

1. **Volume per game** for each of :data:`VOLUME_STATS` (pass attempts,
   carries, targets), a precision-weighted average of up to four sources::

       observed = (1 - rho) * season_mean + rho * last2_mean
       volume   = (g * observed + d * g_prev * prior_mean
                   + n_s * slope * snap_share_last2 + n0 * baseline)
                  / (g + d * g_prev + n_s + n0)

   ``g`` is games to date, ``g_prev`` prior-season games. ``d`` discounts
   a prior-season game against a current one, ``rho`` is the weight of the
   last two games (role changes show up in usage before points), ``n0`` is
   pseudo-games at the positional ``baseline`` -- the no-prior role
   baseline for a player with fewer than
   :data:`NO_PRIOR_GAMES_THRESHOLD` prior games (rookies and call-ups, a
   lower-volume population). The snap term (``n_s`` pseudo-games at
   ``slope * snap_share_last2``, ``slope`` fitted through the origin) is
   used only when a snap-count frame is supplied; a player without a snap
   row simply has no snap term.

2. **Efficiency and touchdowns per opportunity** for each of
   :data:`RATE_DEFINITIONS` (catch rate, yards per target, yards per carry,
   yards per attempt, completion, interception, TD rates, fumbles per
   opportunity, two-point conversions)::

       rate = (x + d * x_prev + k * mean) / (n + d * n_prev + k)

   pooled numerator ``x`` over denominator ``n`` (this season, plus the
   prior season at weight ``d``), plus ``k`` pseudo-opportunities at the
   positional mean. ``k`` is fitted per rate and position, so the data
   decide how hard each rate regresses. As expected, touchdown rates are
   regressed hardest: in the persisted 2015-2025 fit, WR and TE TD rate
   ``k = 300`` targets, RB rush TD rate ``k = 300`` carries, QB pass TD
   rate ``k = 500`` attempts, against ``k = 50`` for WR catch rate.

3. **Score** the projected per-game stat line (volume times rate) through
   :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points` with
   the league's own settings. Scoring is linear, so the points of the
   expected line are the expected points; half-PPR and PPR differ exactly
   as the league scores them. nflverse's ``fantasy_points`` columns are
   never used.

4. **Blend** with the EB points projection:
   ``projected = a * usage + (1 - a) * eb``, ``a`` fitted per position
   (0.65-0.80 on usage in the persisted fit).

5. **Absent prior (FFA-104).** A player with no games to date and fewer
   than four prior-season games has nothing observed. He gets the fitted
   *absent-prior stat line*: the mean per-game line of players who were in
   exactly that state at a cutoff and then played at least four games.
   Scoring the mean line gives the cohort's mean points in any league.

Toy example (hand-checkable; ``tests/players/test_usage_projection.py``)
--------------------------------------------------------------------------

WR ``w1`` at cutoff week 3. Targets 10, 6, 2 (18 total), receptions 12,
yards 150, one TD; last season four games of 5 targets. Hand-set
constants: targets ``n0=1, d=0.5, rho=0.5, baseline=8``; catch rate
``k=12, mean=0.5``; yards/target ``k=12, mean=7.5``; TD rate ``k=182,
mean=0.04``; ``d=0`` for the rates.

- Targets: observed ``0.5*6 + 0.5*4 = 5``; ``(3*5 + 0.5*4*5 + 1*8) /
  (3 + 2 + 1) = 33/6 = 5.5``.
- Catch rate ``(12 + 12*0.5)/(18 + 12) = 0.6``; yards/target
  ``(150 + 90)/30 = 8.0``; TD rate ``(1 + 7.28)/200 = 0.0414`` (observed
  0.056, pulled most of the way to 0.04).
- Line: 5.5 targets, 3.3 catches, 44 yards, 0.2277 TD. Half-PPR
  ``1.65 + 4.4 + 1.3662 = 7.4162``; full PPR ``9.0662``.
- Blended with an EB projection of 10.0 at ``a = 0.75``: ``8.06215``.

Fitting, and why it cannot leak
--------------------------------------------------------------------------

:func:`fit_usage_components` fits each volume and rate constant against
its own realized rest-of-season value by grid search (weighted squared
error: volume per game weighted by remaining games, rates weighted by
remaining opportunities). The fit is in stat space, so it does not depend
on scoring. Only the blend weight is fitted in points
(:func:`fit_blend_weights`, minimum MAE, ties to the smaller weight, i.e.
the incumbent EB). Every feature is built from weeks ``1..w`` and the
previous season; targets come from weeks ``w+1..17``.
:func:`run_usage_backtest` refits everything on seasons strictly before
the one it scores (rolling origin). The blend weight is fitted on training
seasons using component constants fitted on those same training seasons
-- in-sample for a handful of shrinkage constants over ~20,000 rows, and
never touching the scored season.

Measured (rolling origin, scored 2019-2025, cutoffs 2/3/4/6/8/10)
--------------------------------------------------------------------------

Half-PPR (NWC's real settings), mean over the 42 season-by-cutoff cells:

==========  =======================  =======================
Population  EB MAE / Spearman        Blend MAE / Spearman
==========  =======================  =======================
All         2.449 / 0.797            2.288 / 0.824
Waiver      2.096 / 0.573            1.987 / 0.650
==========  =======================  =======================

The blend beats EB on MAE in 42/42 cells overall and 38/42 in the waiver
population, and on Spearman in 42/42 both ways. Per-position, cutoff-3 and
full-PPR tables, plus what did not help, are in
``docs/valuation-model.md``. Summary of what was **tested and not
adopted**: ffopportunity expected rates as shrinkage targets (no gain:
won 17-20 of 42 cells), and shrunk league-scored xFP as a third stacked
component (no gain: +0.002/-0.002 MAE). Top-5 hit rate does not improve
reliably; do not read the top of the board to more precision than it has.

Missing values, ties, regular season
--------------------------------------------------------------------------

- A scored frame without :data:`REQUIRED_STAT_COLUMNS` yields empty
  features and ``NaN`` usage projections; callers fall back to EB.
- No snap frame: :meth:`UsageModelParameters.for_snap_data` selects the
  separately fitted no-snap parameter set (measured separately: still
  beats EB on MAE at every position).
- ``NaN`` never becomes zero: a stat line that is all ``NaN`` scores
  ``NaN`` (:func:`score_stat_line`).
- Ties: players with identical inputs get identical projections (every
  absent-prior player at a position shares one value). Ranking ties are
  resolved downstream by standard competition ranking.
- Regular season only: targets stop at week 17
  (:data:`~fantasy_analyzer.players.ros_backtest.DEFAULT_SEASON_END_WEEK`);
  the prior season is its regular-season rows.

Known limits
--------------------------------------------------------------------------

- Step-function bonuses (``bonus_rec_yd_200`` and similar) and
  special-teams or fumble-return TDs are not projected: a per-game
  *expected* line never crosses a 200-yard threshold. Realized scoring in
  a league that uses them is slightly higher than the usage projection.
- nflverse has no row for a week in which a player recorded no stat, so
  "games" undercount snap-only weeks. The target is measured the same way,
  so the backtest is consistent, but a pure blocker's rate is per stat row.
- No availability model: this is a per-game rate, exactly like the EB
  projection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from fantasy_analyzer.players.ros_backtest import (
    DEFAULT_SEASON_END_WEEK,
    build_ros_evaluation_set,
)
from fantasy_analyzer.players.scoring import calculate_fantasy_points

# --------------------------------------------------------------------------
# Definitions
# --------------------------------------------------------------------------

#: Positions the usage model projects. Every other position (K, DEF, IDP)
#: has no volume/efficiency decomposition here and keeps the points-space
#: empirical-Bayes projection.
MODELED_POSITIONS = ("QB", "RB", "WR", "TE")

#: The three opportunity counts every projection is built from.
VOLUME_STATS = ("attempts", "carries", "targets")

#: Derived stat: fumbles lost of every kind, scored by ``fum_lost``.
#: :mod:`fantasy_analyzer.players.scoring` prefers nflverse's
#: ``fumbles_lost_total`` (which also counts return fumbles) and falls back
#: to the sum of the three columns below; ``fumbles_lost`` here follows the
#: same rule row by row, so the projected rate and the realized scoring
#: count the same fumbles.
FUMBLE_COLUMNS = ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost")

#: The total the scoring engine prefers for ``fum_lost`` when present.
FUMBLE_TOTAL_COLUMN = "fumbles_lost_total"

#: Per-opportunity rate -> ``(numerator stat, denominator volume stats)``.
#: The numerator names are nflverse stat columns (``fumbles_lost`` is the
#: derived sum of :data:`FUMBLE_COLUMNS`); a rate's denominator is the sum of
#: its volume stats. Every scored offensive category a Sleeper league can
#: weight is one of these numerators or one of :data:`VOLUME_STATS`.
RATE_DEFINITIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "completion_rate": ("completions", ("attempts",)),
    "pass_yards_per_attempt": ("passing_yards", ("attempts",)),
    "pass_td_rate": ("passing_tds", ("attempts",)),
    "interception_rate": ("passing_interceptions", ("attempts",)),
    "sack_rate": ("sacks_suffered", ("attempts",)),
    "pass_2pt_rate": ("passing_2pt_conversions", ("attempts",)),
    "rush_yards_per_carry": ("rushing_yards", ("carries",)),
    "rush_td_rate": ("rushing_tds", ("carries",)),
    "rush_2pt_rate": ("rushing_2pt_conversions", ("carries",)),
    "catch_rate": ("receptions", ("targets",)),
    "receiving_yards_per_target": ("receiving_yards", ("targets",)),
    "receiving_td_rate": ("receiving_tds", ("targets",)),
    "rec_2pt_rate": ("receiving_2pt_conversions", ("targets",)),
    "fumble_lost_rate": ("fumbles_lost", ("attempts", "carries", "targets")),
}

#: Rates whose numerator is a touchdown. Reported separately because they
#: are the least stable inputs and the fit regresses them hardest.
TOUCHDOWN_RATES = ("pass_td_rate", "rush_td_rate", "receiving_td_rate")

#: Every per-player counting stat the feature builder sums.
BASE_STATS = VOLUME_STATS + tuple(
    dict.fromkeys(numerator for numerator, _ in RATE_DEFINITIONS.values())
)

#: Raw nflverse columns a scored player-week frame must carry for the usage
#: model to run. Without them every usage projection is ``NaN`` and callers
#: fall back to the points-space projection.
REQUIRED_STAT_COLUMNS = (
    tuple(column for column in BASE_STATS if column != "fumbles_lost") + FUMBLE_COLUMNS
)

#: How many most-recent games feed the recency term of the volume estimate.
DEFAULT_RECENCY_GAMES = 2

#: Default location of the persisted parameter set.
DEFAULT_USAGE_PARAMETERS_PATH = Path(".cache/nflverse/usage_model_parameters.json")

#: Grids searched by :func:`fit_usage_model`. See the module docstring.
DEFAULT_VOLUME_N0_GRID = (0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)
DEFAULT_PRIOR_WEIGHT_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0)
DEFAULT_RECENCY_GRID = (0.0, 0.2, 0.4, 0.6, 0.8)
DEFAULT_RATE_K_GRID = (
    0.0,
    2.0,
    5.0,
    10.0,
    20.0,
    35.0,
    50.0,
    75.0,
    100.0,
    150.0,
    200.0,
    300.0,
    500.0,
    750.0,
    1000.0,
    1500.0,
    2500.0,
    5000.0,
    10000.0,
)
DEFAULT_RATE_PRIOR_WEIGHT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
DEFAULT_BLEND_GRID = tuple(round(step * 0.05, 2) for step in range(21))


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class VolumeParameters:
    """Shrinkage constants for one volume stat at one position.

    Attributes:
        n0: Pseudo-games of the baseline. The number of current-season games
            at which the season-to-date rate and the baseline weigh equally
            (with no prior season).
        prior_weight: Weight of one prior-season game relative to one
            current-season game.
        recency_weight: Share of the observed rate taken from the last
            :data:`DEFAULT_RECENCY_GAMES` games rather than the season mean.
        baseline: Per-game volume the estimate shrinks toward for a player
            with a prior season.
        no_prior_baseline: The same for a player with no prior season (a
            rookie or a returning player): the role baseline of the
            population the waiver wire is actually full of.
        snap_n0: Pseudo-games given to the snap-implied volume
            ``snap_slope * snap_share_last2``. ``0`` switches the term off
            (and it is off for any player with no snap data).
        snap_slope: Per-game volume per unit of offensive snap share,
            fitted through the origin.
    """

    n0: float
    prior_weight: float
    recency_weight: float
    baseline: float
    no_prior_baseline: float
    snap_n0: float = 0.0
    snap_slope: float = 0.0


@dataclass(frozen=True)
class RateParameters:
    """Shrinkage constants for one per-opportunity rate at one position.

    Attributes:
        k: Pseudo-opportunities of the positional mean. Large ``k`` means the
            rate is mostly noise and is regressed hard.
        prior_weight: Weight of one prior-season opportunity relative to one
            current-season opportunity.
        mean: The positional mean rate (opportunity-weighted).
        expected_k: When set, the shrinkage target is the player's own
            *expected* rate (ffopportunity expected numerator over charted
            opportunities, itself shrunk toward ``mean`` with
            ``expected_k`` pseudo-opportunities) instead of ``mean``.
            ``None`` switches it off.
    """

    k: float
    prior_weight: float
    mean: float
    expected_k: Optional[float] = None


@dataclass(frozen=True)
class UsageModelParameters:
    """A fitted usage-model parameter set.

    Attributes:
        volume: Position -> volume stat -> :class:`VolumeParameters`.
        rates: Position -> rate name -> :class:`RateParameters`.
        blend_weight: Position -> weight on the usage projection in the
            final blend (``1`` = usage only, ``0`` = the empirical-Bayes
            points projection only). A position absent here is not blended:
            its final projection is the EB one.
        absent_prior_stat_line: Position -> per-game stat line assigned to a
            player with no games to date and no trusted prior (FFA-104).
        fit_seasons: The seasons every constant was fitted on, sorted.
        fit_metrics: Free-form diagnostics recorded at fit time.
        no_snap_fallback: A second parameter set fitted *without* the snap
            term, used when no usage frame is available. Snap-term constants
            are fitted jointly with the other volume constants, so simply
            dropping the term from a snap-fitted set would apply constants
            to a model they were not fitted for.
    """

    volume: Mapping[str, Mapping[str, VolumeParameters]]
    rates: Mapping[str, Mapping[str, RateParameters]]
    blend_weight: Mapping[str, float] = field(default_factory=dict)
    absent_prior_stat_line: Mapping[str, Mapping[str, float]] = field(
        default_factory=dict
    )
    fit_seasons: tuple[int, ...] = ()
    fit_metrics: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    no_snap_fallback: Optional["UsageModelParameters"] = None

    def positions(self) -> tuple[str, ...]:
        """Positions with both volume and rate parameters, sorted."""
        return tuple(sorted(set(self.volume) & set(self.rates)))

    def uses_snaps(self) -> bool:
        """Whether any volume constant carries a snap term."""
        return any(
            values.snap_n0 > 0
            for by_stat in self.volume.values()
            for values in by_stat.values()
        )

    def for_snap_data(self, has_snap_data: bool) -> "UsageModelParameters":
        """The parameter set to use given whether snap data is available.

        With snap data: this set. Without: :attr:`no_snap_fallback` when
        there is one, else this set (whose snap term then contributes
        nothing -- see :func:`shrink_volume`).
        """
        if has_snap_data or self.no_snap_fallback is None:
            return self
        return self.no_snap_fallback


def _parameters_to_payload(parameters: UsageModelParameters) -> dict:
    payload = {
        "volume": {
            str(position): {
                str(stat): {
                    "n0": float(values.n0),
                    "prior_weight": float(values.prior_weight),
                    "recency_weight": float(values.recency_weight),
                    "baseline": float(values.baseline),
                    "no_prior_baseline": float(values.no_prior_baseline),
                    "snap_n0": float(values.snap_n0),
                    "snap_slope": float(values.snap_slope),
                }
                for stat, values in by_stat.items()
            }
            for position, by_stat in parameters.volume.items()
        },
        "rates": {
            str(position): {
                str(rate): {
                    "k": float(values.k),
                    "prior_weight": float(values.prior_weight),
                    "mean": float(values.mean),
                    "expected_k": (
                        None if values.expected_k is None else float(values.expected_k)
                    ),
                }
                for rate, values in by_rate.items()
            }
            for position, by_rate in parameters.rates.items()
        },
        "blend_weight": {
            str(position): float(value)
            for position, value in parameters.blend_weight.items()
        },
        "absent_prior_stat_line": {
            str(position): {str(stat): float(value) for stat, value in line.items()}
            for position, line in parameters.absent_prior_stat_line.items()
        },
        "fit_seasons": [int(season) for season in parameters.fit_seasons],
        "fit_metrics": {
            str(key): {str(name): float(value) for name, value in values.items()}
            for key, values in parameters.fit_metrics.items()
        },
    }
    if parameters.no_snap_fallback is not None:
        payload["no_snap_fallback"] = _parameters_to_payload(
            parameters.no_snap_fallback
        )
    return payload


def _parameters_from_payload(payload: Mapping) -> UsageModelParameters:
    volume = {
        str(position): {
            str(stat): VolumeParameters(
                n0=float(values["n0"]),
                prior_weight=float(values["prior_weight"]),
                recency_weight=float(values["recency_weight"]),
                baseline=float(values["baseline"]),
                no_prior_baseline=float(values["no_prior_baseline"]),
                snap_n0=float(values.get("snap_n0", 0.0)),
                snap_slope=float(values.get("snap_slope", 0.0)),
            )
            for stat, values in by_stat.items()
        }
        for position, by_stat in payload["volume"].items()
    }
    rates = {
        str(position): {
            str(rate): RateParameters(
                k=float(values["k"]),
                prior_weight=float(values["prior_weight"]),
                mean=float(values["mean"]),
                expected_k=(
                    None
                    if values.get("expected_k") is None
                    else float(values["expected_k"])
                ),
            )
            for rate, values in by_rate.items()
        }
        for position, by_rate in payload["rates"].items()
    }
    fallback = payload.get("no_snap_fallback")
    return UsageModelParameters(
        volume=volume,
        rates=rates,
        blend_weight={
            str(position): float(value)
            for position, value in payload.get("blend_weight", {}).items()
        },
        absent_prior_stat_line={
            str(position): {str(stat): float(value) for stat, value in line.items()}
            for position, line in payload.get("absent_prior_stat_line", {}).items()
        },
        fit_seasons=tuple(int(season) for season in payload.get("fit_seasons", ())),
        fit_metrics={
            str(key): {str(name): float(value) for name, value in values.items()}
            for key, values in payload.get("fit_metrics", {}).items()
        },
        no_snap_fallback=(
            _parameters_from_payload(fallback) if fallback is not None else None
        ),
    )


def save_usage_model_parameters(
    parameters: UsageModelParameters,
    path: Union[str, Path] = DEFAULT_USAGE_PARAMETERS_PATH,
) -> Path:
    """Persist a fitted usage-model parameter set as JSON.

    Built-in types only (numpy scalars are coerced), mirroring
    :func:`~fantasy_analyzer.players.ros_projection.save_shrinkage_parameters`.

    Args:
        parameters: The fitted constants to write, including any
            :attr:`~UsageModelParameters.no_snap_fallback`.
        path: Destination file. Parent directories are created.

    Returns:
        The path written.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(_parameters_to_payload(parameters), indent=2, sort_keys=True) + "\n"
    )
    return destination


def load_usage_model_parameters(
    path: Union[str, Path] = DEFAULT_USAGE_PARAMETERS_PATH,
) -> Optional[UsageModelParameters]:
    """Load a persisted usage-model parameter set, or ``None`` if unusable.

    Mirrors
    :func:`~fantasy_analyzer.players.ros_projection.load_shrinkage_parameters`:
    a missing file and a corrupt file both return ``None``, so a caller's
    fallback (the points-space projection alone) is the same in either case.

    Args:
        path: The file :func:`save_usage_model_parameters` wrote.

    Returns:
        The stored :class:`UsageModelParameters`, or ``None``.
    """
    source = Path(path)
    if not source.exists():
        return None
    try:
        return _parameters_from_payload(json.loads(source.read_text()))
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return None


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------


def has_usage_stat_columns(scored_weeks: pd.DataFrame) -> bool:
    """Whether ``scored_weeks`` carries every raw stat the usage model needs."""
    return all(column in scored_weeks.columns for column in REQUIRED_STAT_COLUMNS)


def _with_base_stats(weeks: pd.DataFrame) -> pd.DataFrame:
    """Return ``weeks`` with the derived ``fumbles_lost`` column added."""
    frame = weeks.copy()
    component_sum = sum(
        frame[column].fillna(0).astype(float) for column in FUMBLE_COLUMNS
    )
    if FUMBLE_TOTAL_COLUMN in frame.columns:
        total = pd.to_numeric(frame[FUMBLE_TOTAL_COLUMN], errors="coerce")
        frame["fumbles_lost"] = total.where(total.notna(), component_sum)
    else:
        frame["fumbles_lost"] = component_sum
    for stat in BASE_STATS:
        frame[stat] = frame[stat].fillna(0).astype(float)
    return frame


def _majority(values: pd.Series) -> Optional[str]:
    non_null = values.dropna()
    if non_null.empty:
        return None
    counts = non_null.value_counts()
    top = counts.max()
    for value in non_null:
        if counts[value] == top:
            return value
    return None


def build_usage_features(
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    *,
    prior_season_weeks: Optional[pd.DataFrame] = None,
    recency_games: int = DEFAULT_RECENCY_GAMES,
) -> pd.DataFrame:
    """Season-to-date, recent and prior-season opportunity sums per player.

    Every column is computed from weeks ``1..cutoff_week`` of ``season`` and
    from the whole regular season ``season - 1`` -- nothing after the
    cutoff, so the frame cannot leak.

    Args:
        scored_weeks: Scored player-weeks carrying
            :data:`REQUIRED_STAT_COLUMNS`
            (:func:`~fantasy_analyzer.players.ros_backtest.build_scored_player_weeks`).
        season: The season being projected.
        cutoff_week: Last week whose results are knowable.
        prior_season_weeks: Frame to read ``season - 1`` from. Defaults to
            ``scored_weeks``.
        recency_games: Games in the recency window.

    Returns:
        A DataFrame indexed by ``player_id`` with ``position``,
        ``games_to_date``, ``prior_games``, ``{stat}_to_date`` and
        ``{stat}_prior`` for every :data:`BASE_STATS` entry, and
        ``{volume}_recent`` (per-game mean over the last ``recency_games``
        games) for every :data:`VOLUME_STATS` entry. One row per player with
        a row in either window. Empty if the stat columns are absent.

    Raises:
        ValueError: If ``cutoff_week < 1`` or ``recency_games < 1``.
    """
    if cutoff_week < 1:
        raise ValueError(f"cutoff_week must be >= 1; got {cutoff_week}.")
    if recency_games < 1:
        raise ValueError(f"recency_games must be >= 1; got {recency_games}.")
    if prior_season_weeks is None:
        prior_season_weeks = scored_weeks

    columns = (
        ["position", "games_to_date", "prior_games"]
        + [f"{stat}_to_date" for stat in BASE_STATS]
        + [f"{stat}_prior" for stat in BASE_STATS]
        + [f"{stat}_recent" for stat in VOLUME_STATS]
    )
    if not has_usage_stat_columns(scored_weeks):
        return pd.DataFrame(columns=columns).rename_axis("player_id")

    current = scored_weeks[
        (scored_weeks["season"] == season)
        & (scored_weeks["week"] >= 1)
        & (scored_weeks["week"] <= cutoff_week)
    ]
    current = _with_base_stats(current)

    prior = pd.DataFrame(columns=scored_weeks.columns)
    if (
        prior_season_weeks is not None
        and not prior_season_weeks.empty
        and has_usage_stat_columns(prior_season_weeks)
    ):
        prior = prior_season_weeks[prior_season_weeks["season"] == season - 1]
    prior = _with_base_stats(prior) if not prior.empty else prior

    current_grouped = current.groupby("player_id", sort=False)
    to_date = current_grouped[list(BASE_STATS)].sum().add_suffix("_to_date")
    to_date["games_to_date"] = current_grouped.size()
    to_date["position_current"] = current_grouped["position"].agg(_majority)

    ordered = current.sort_values(["player_id", "week"], kind="stable")
    recent = (
        ordered.groupby("player_id", sort=False)
        .tail(recency_games)
        .groupby("player_id", sort=False)[list(VOLUME_STATS)]
        .mean()
        .add_suffix("_recent")
    )

    if not prior.empty:
        prior_grouped = prior.groupby("player_id", sort=False)
        prior_summary = prior_grouped[list(BASE_STATS)].sum().add_suffix("_prior")
        prior_summary["prior_games"] = prior_grouped.size()
        prior_summary["position_prior"] = prior_grouped["position"].agg(_majority)
    else:
        prior_summary = pd.DataFrame(
            columns=[f"{stat}_prior" for stat in BASE_STATS]
            + ["prior_games", "position_prior"]
        )

    features = to_date.join(recent, how="left").join(prior_summary, how="outer")
    features["position"] = features["position_current"].where(
        features["position_current"].notna(), features["position_prior"]
    )
    features["games_to_date"] = features["games_to_date"].fillna(0).astype(float)
    features["prior_games"] = features["prior_games"].fillna(0).astype(float)
    for stat in BASE_STATS:
        features[f"{stat}_to_date"] = (
            features[f"{stat}_to_date"].fillna(0).astype(float)
        )
        features[f"{stat}_prior"] = features[f"{stat}_prior"].fillna(0).astype(float)
    for stat in VOLUME_STATS:
        features[f"{stat}_recent"] = features[f"{stat}_recent"].astype(float)
    features.index.name = "player_id"
    return features[columns]


def build_usage_targets(
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    *,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
) -> pd.DataFrame:
    """Realized rest-of-season stat sums per player -- fitting/backtest only.

    Reads weeks ``cutoff_week + 1..season_end_week`` (regular season only),
    i.e. exactly the window of the harness's ``ros_ppg`` target.

    Returns:
        A DataFrame indexed by ``player_id`` with ``ros_games`` and
        ``{stat}_ros`` for every :data:`BASE_STATS` entry.
    """
    future = scored_weeks[
        (scored_weeks["season"] == season)
        & (scored_weeks["week"] > cutoff_week)
        & (scored_weeks["week"] <= season_end_week)
    ]
    if future.empty or not has_usage_stat_columns(future):
        return pd.DataFrame(
            columns=["ros_games"] + [f"{stat}_ros" for stat in BASE_STATS]
        ).rename_axis("player_id")
    future = _with_base_stats(future)
    grouped = future.groupby("player_id", sort=False)
    targets = grouped[list(BASE_STATS)].sum().add_suffix("_ros")
    targets["ros_games"] = grouped.size().astype(float)
    targets.index.name = "player_id"
    return targets


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

#: Prior-season games below which a player is treated as having no prior:
#: his volume shrinks toward the no-prior role baseline, and with zero games
#: to date he gets the absent-prior stat line (FFA-104). Matches
#: :data:`~fantasy_analyzer.players.waiver_rankings.DEFAULT_MIN_PRIOR_GAMES`.
NO_PRIOR_GAMES_THRESHOLD = 4

#: Columns of the per-game stat line :func:`project_usage` builds. Named as
#: nflverse stat columns so the line scores directly through
#: :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`.
STAT_LINE_COLUMNS = (
    "attempts",
    "completions",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "passing_2pt_conversions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "rushing_2pt_conversions",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_2pt_conversions",
    "sack_fumbles_lost",
    "rushing_fumbles_lost",
    "receiving_fumbles_lost",
)

#: Rate -> the stat-line column it produces.
_RATE_OUTPUT = {
    rate: ("rushing_fumbles_lost" if numerator == "fumbles_lost" else numerator)
    for rate, (numerator, _) in RATE_DEFINITIONS.items()
}


def shrink_volume(
    games: np.ndarray,
    observed_per_game: np.ndarray,
    recent_per_game: np.ndarray,
    prior_games: np.ndarray,
    prior_per_game: np.ndarray,
    baseline: np.ndarray,
    parameters: VolumeParameters,
    snap_share: Optional[np.ndarray] = None,
) -> np.ndarray:
    """The multi-source volume estimate (see the module docstring).

    ``(g * observed + d * g_prev * prior + n_s * slope * snap + n0 * baseline)
    / (g + d * g_prev + n_s + n0)`` where ``observed = (1 - rho) *
    season_mean + rho * recent_mean`` and ``snap`` is the recent offensive
    snap share. A zero-game player's observed term carries zero weight, a
    missing recent mean falls back to the season mean, and a missing snap
    share drops the snap term, so ``NaN`` never propagates.
    """
    rho = parameters.recency_weight
    recent = np.where(np.isnan(recent_per_game), observed_per_game, recent_per_game)
    observed = (1 - rho) * observed_per_game + rho * recent
    observed = np.where(games > 0, observed, 0.0)
    prior = np.where(prior_games > 0, prior_per_game, 0.0)
    prior_weight = parameters.prior_weight * prior_games
    numerator = games * observed + prior_weight * prior + parameters.n0 * baseline
    denominator = games + prior_weight + parameters.n0
    if snap_share is not None and parameters.snap_n0 > 0:
        has_snaps = ~np.isnan(snap_share)
        snap_weight = np.where(has_snaps, parameters.snap_n0, 0.0)
        snap_volume = parameters.snap_slope * np.where(has_snaps, snap_share, 0.0)
        numerator = numerator + snap_weight * snap_volume
        denominator = denominator + snap_weight
    return numerator / denominator


def shrink_rate(
    numerator_to_date: np.ndarray,
    denominator_to_date: np.ndarray,
    numerator_prior: np.ndarray,
    denominator_prior: np.ndarray,
    parameters: RateParameters,
    expected: Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = None,
) -> np.ndarray:
    """The per-opportunity rate estimate (see the module docstring).

    ``(x + d * x_prev + k * m) / (n + d * n_prev + k)``: pooled counts from
    this season and a discounted prior season, plus ``k`` pseudo-
    opportunities at the target ``m``. ``m`` is the positional mean, or --
    when ``expected`` (expected numerator/charted denominator, to date and
    prior) is given and ``parameters.expected_k`` is set -- the player's own
    expected rate ``(e + d * e_prev + k_e * mean) / (n_e + d * n_e_prev +
    k_e)``. With no opportunities at all the estimate is the target.
    """
    d = parameters.prior_weight
    target = np.full(np.shape(numerator_to_date), parameters.mean, dtype=float)
    if expected is not None and parameters.expected_k is not None:
        e, n_e, e_prev, n_e_prev = (
            np.nan_to_num(np.asarray(a, dtype=float)) for a in expected
        )
        expected_numerator = e + d * e_prev + parameters.expected_k * parameters.mean
        expected_denominator = n_e + d * n_e_prev + parameters.expected_k
        with np.errstate(divide="ignore", invalid="ignore"):
            player_expected = expected_numerator / expected_denominator
        target = np.where(expected_denominator > 0, player_expected, parameters.mean)
    numerator = numerator_to_date + d * numerator_prior + parameters.k * target
    denominator = denominator_to_date + d * denominator_prior + parameters.k
    with np.errstate(divide="ignore", invalid="ignore"):
        rate = numerator / denominator
    return np.where(denominator > 0, rate, target)


def _denominator(
    frame: pd.DataFrame, volumes: tuple[str, ...], suffix: str
) -> np.ndarray:
    return sum(frame[f"{volume}{suffix}"].to_numpy(dtype=float) for volume in volumes)


def _snap_share_array(frame: pd.DataFrame) -> Optional[np.ndarray]:
    """Recent snap share, or ``None`` when the frame carries no snap data."""
    if "snap_share_last2" not in frame.columns:
        return None
    return frame["snap_share_last2"].to_numpy(dtype=float)


def _expected_arrays(
    frame: pd.DataFrame, rate: str
) -> Optional[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """Expected numerator/denominator arrays for ``rate``, if the frame has them."""
    if rate not in EXPECTED_RATE_SOURCES:
        return None
    numerator, denominators = EXPECTED_RATE_SOURCES[rate]
    needed = [f"exp_{numerator}_to_date", f"exp_{numerator}_prior"] + [
        f"exp_{volume}_{suffix}"
        for volume in denominators
        for suffix in ("to_date", "prior")
    ]
    if not all(column in frame.columns for column in needed):
        return None

    def _sum(suffix: str) -> np.ndarray:
        return sum(
            np.nan_to_num(frame[f"exp_{volume}_{suffix}"].to_numpy(dtype=float))
            for volume in denominators
        )

    return (
        np.nan_to_num(frame[f"exp_{numerator}_to_date"].to_numpy(dtype=float)),
        _sum("to_date"),
        np.nan_to_num(frame[f"exp_{numerator}_prior"].to_numpy(dtype=float)),
        _sum("prior"),
    )


def project_usage(
    features: pd.DataFrame,
    parameters: UsageModelParameters,
    scoring_settings: Mapping[str, float],
) -> pd.DataFrame:
    """Project per-game volume, rates, a stat line and points for each player.

    Args:
        features: As returned by :func:`build_usage_features`.
        parameters: A fitted :class:`UsageModelParameters`.
        scoring_settings: The league's Sleeper scoring settings. The stat
            line is scored through
            :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`,
            so half-PPR and PPR (and any other linear setting) differ
            exactly as the league scores them.

    Returns:
        A DataFrame indexed like ``features`` with
        ``projected_{attempts,carries,targets}_per_game``, one column per
        :data:`RATE_DEFINITIONS` rate, the :data:`STAT_LINE_COLUMNS` stat
        line (per game), ``usage_projected_ppg`` and ``usage_absent_prior``
        (``True`` where the absent-prior line was used). Rows at a position
        the parameters do not cover carry ``NaN`` throughout.
    """
    index = features.index
    output = pd.DataFrame(index=index)
    for volume in VOLUME_STATS:
        output[f"projected_{volume}_per_game"] = np.nan
    for rate in RATE_DEFINITIONS:
        output[rate] = np.nan
    for column in STAT_LINE_COLUMNS:
        output[column] = np.nan
    output["usage_absent_prior"] = False

    if features.empty:
        output["usage_projected_ppg"] = pd.Series(dtype="float64")
        return output

    games = features["games_to_date"].to_numpy(dtype=float)
    prior_games = features["prior_games"].to_numpy(dtype=float)

    for position in parameters.positions():
        mask = (features["position"] == position).to_numpy()
        if not mask.any():
            continue
        subset = features.loc[mask]
        g = games[mask]
        gp = prior_games[mask]
        no_prior = gp < NO_PRIOR_GAMES_THRESHOLD

        volumes: dict[str, np.ndarray] = {}
        for volume in VOLUME_STATS:
            values = parameters.volume[position][volume]
            with np.errstate(divide="ignore", invalid="ignore"):
                observed = np.where(
                    g > 0, subset[f"{volume}_to_date"].to_numpy(dtype=float) / g, 0.0
                )
                prior = np.where(
                    gp > 0, subset[f"{volume}_prior"].to_numpy(dtype=float) / gp, 0.0
                )
            baseline = np.where(no_prior, values.no_prior_baseline, values.baseline)
            volumes[volume] = shrink_volume(
                g,
                observed,
                subset[f"{volume}_recent"].to_numpy(dtype=float),
                gp,
                prior,
                baseline,
                values,
                snap_share=_snap_share_array(subset),
            )
            output.loc[mask, f"projected_{volume}_per_game"] = volumes[volume]
            output.loc[mask, volume] = volumes[volume]

        for rate, (numerator, denominators) in RATE_DEFINITIONS.items():
            values = parameters.rates[position][rate]
            estimate = shrink_rate(
                subset[f"{numerator}_to_date"].to_numpy(dtype=float),
                _denominator(subset, denominators, "_to_date"),
                subset[f"{numerator}_prior"].to_numpy(dtype=float),
                _denominator(subset, denominators, "_prior"),
                values,
                expected=_expected_arrays(subset, rate),
            )
            output.loc[mask, rate] = estimate
            per_game_volume = sum(volumes[volume] for volume in denominators)
            output.loc[mask, _RATE_OUTPUT[rate]] = estimate * per_game_volume

        output.loc[mask, "sack_fumbles_lost"] = 0.0
        output.loc[mask, "receiving_fumbles_lost"] = 0.0

        # FFA-104: no games to date and no trusted prior. Nothing about the
        # player is observed, so he gets the fitted absent-prior line.
        line = parameters.absent_prior_stat_line.get(position)
        absent = mask & (games == 0) & (prior_games < NO_PRIOR_GAMES_THRESHOLD)
        if line and absent.any():
            for column in STAT_LINE_COLUMNS:
                output.loc[absent, column] = float(line.get(column, 0.0))
            output.loc[absent, "projected_attempts_per_game"] = float(
                line.get("attempts", 0.0)
            )
            output.loc[absent, "projected_carries_per_game"] = float(
                line.get("carries", 0.0)
            )
            output.loc[absent, "projected_targets_per_game"] = float(
                line.get("targets", 0.0)
            )
            output.loc[absent, "usage_absent_prior"] = True

    output["usage_projected_ppg"] = score_stat_line(
        output[list(STAT_LINE_COLUMNS)], scoring_settings
    )
    return output


def score_stat_line(
    stat_line: pd.DataFrame, scoring_settings: Mapping[str, float]
) -> pd.Series:
    """Score a per-game stat line through the league's settings.

    A row whose stat line is entirely ``NaN`` (no projection) scores
    ``NaN``, not zero -- the scoring engine itself treats ``NaN`` stats as
    zero, which would silently turn "no projection" into "projected zero".
    """
    if stat_line.empty:
        return pd.Series(dtype="float64", index=stat_line.index)
    points = calculate_fantasy_points(stat_line, scoring_settings).points_df[
        "fantasy_points"
    ]
    return points.where(stat_line.notna().any(axis=1)).astype("float64")


def blend_projections(
    positions: pd.Series,
    eb_projected_ppg: pd.Series,
    usage_projected_ppg: pd.Series,
    parameters: UsageModelParameters,
) -> tuple[pd.Series, pd.Series]:
    """Combine the EB and usage projections into the final one.

    ``final = a * usage + (1 - a) * eb`` with ``a =
    parameters.blend_weight[position]``. Where ``a`` is undefined for the
    position, or the usage projection is ``NaN``, the EB projection is
    used unchanged.

    Returns:
        ``(projected_ppg, projection_model)``. ``projection_model`` is
        ``"usage"`` (``a == 1``), ``"blend"`` (``0 < a < 1``), ``"eb"`` (EB
        used, for any reason) or ``None`` when neither projection exists.
    """
    weight = positions.map(lambda position: parameters.blend_weight.get(position))
    weight = pd.to_numeric(weight, errors="coerce")
    usable = weight.notna() & usage_projected_ppg.notna() & eb_projected_ppg.notna()
    usage_only = weight.notna() & usage_projected_ppg.notna() & eb_projected_ppg.isna()

    final = eb_projected_ppg.astype("float64").copy()
    final[usable] = (
        weight[usable] * usage_projected_ppg[usable]
        + (1 - weight[usable]) * eb_projected_ppg[usable]
    )
    final[usage_only] = usage_projected_ppg[usage_only]

    labels: list[Optional[str]] = []
    for is_usable, is_usage_only, value, eb in zip(
        usable, usage_only, weight, eb_projected_ppg
    ):
        if is_usable:
            if value >= 1.0:
                labels.append("usage")
            elif value <= 0.0:
                labels.append("eb")
            else:
                labels.append("blend")
        elif is_usage_only:
            labels.append("usage")
        elif pd.notna(eb):
            labels.append("eb")
        else:
            labels.append(None)
    return final, pd.Series(labels, index=positions.index, dtype=object)


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------


def build_usage_panel(
    scored_weeks: pd.DataFrame,
    seasons: Iterable[int],
    cutoff_weeks: Iterable[int],
    *,
    recency_games: int = DEFAULT_RECENCY_GAMES,
    **evaluation_kwargs,
) -> pd.DataFrame:
    """Stack harness evaluation rows with usage features and ROS targets.

    One row per ``(season, cutoff_week, player)`` in exactly the population
    :func:`~fantasy_analyzer.players.ros_backtest.build_ros_evaluation_set`
    scores (at least one game to date, enough remaining games), so the usage
    model is fitted and measured on the same rows as every baseline.

    Args:
        scored_weeks: Scored player-weeks carrying :data:`REQUIRED_STAT_COLUMNS`,
            spanning every season and its predecessor.
        seasons: Seasons to include.
        cutoff_weeks: Cutoff weeks within each season.
        recency_games: Passed to :func:`build_usage_features`.
        **evaluation_kwargs: Forwarded to ``build_ros_evaluation_set``.

    Returns:
        The evaluation columns plus every :func:`build_usage_features` and
        :func:`build_usage_targets` column. Empty if nothing is evaluable.
    """
    season_end_week = evaluation_kwargs.get("season_end_week", DEFAULT_SEASON_END_WEEK)
    cells = []
    for season in seasons:
        for cutoff_week in cutoff_weeks:
            evaluation = build_ros_evaluation_set(
                scored_weeks,
                season,
                cutoff_week,
                prior_season_weeks=scored_weeks,
                **evaluation_kwargs,
            ).evaluation_df
            if evaluation.empty:
                continue
            # ``position`` and ``games_to_date`` come from the evaluation
            # frame (identical by construction: same rows, same window).
            features = build_usage_features(
                scored_weeks, season, cutoff_week, recency_games=recency_games
            ).drop(columns=["position", "games_to_date"])
            targets = build_usage_targets(
                scored_weeks, season, cutoff_week, season_end_week=season_end_week
            )
            cell = evaluation.join(features, on="player_id").join(
                targets, on="player_id"
            )
            cells.append(cell)
    if not cells:
        return pd.DataFrame()
    return pd.concat(cells, ignore_index=True)


def build_absent_prior_cohort(
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    *,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
    min_remaining_games: int = 4,
    no_prior_games_threshold: int = NO_PRIOR_GAMES_THRESHOLD,
) -> pd.DataFrame:
    """Players with no games to date and no trusted prior who later played.

    The population FFA-104 is about, reconstructed historically: no row in
    weeks ``1..cutoff_week`` of ``season``, fewer than
    ``no_prior_games_threshold`` rows in ``season - 1``, and at least
    ``min_remaining_games`` rows in ``cutoff_week + 1..season_end_week``.

    Conditioning on *later playing* is unavoidable -- nflverse has no row
    for a player who never takes the field, so the cohort's scoring is an
    upper bound on what such a player is worth in expectation.

    Returns:
        One row per player: ``season``, ``cutoff_week``, ``player_id``,
        ``position``, ``prior_games``, ``ros_games``, ``ros_ppg`` (points
        per game in the harness's target window) and ``{stat}_ros`` sums.
        Empty if nobody qualifies or the stat columns are absent.
    """
    this_season = scored_weeks[scored_weeks["season"] == season]
    observed_ids = set(
        this_season.loc[
            (this_season["week"] >= 1) & (this_season["week"] <= cutoff_week),
            "player_id",
        ]
    )
    future = this_season[
        (this_season["week"] > cutoff_week) & (this_season["week"] <= season_end_week)
    ]
    future = future[~future["player_id"].isin(observed_ids)]
    if future.empty or not has_usage_stat_columns(future):
        return pd.DataFrame()

    prior_counts = (
        scored_weeks[scored_weeks["season"] == season - 1].groupby("player_id").size()
    )
    future = _with_base_stats(future)
    grouped = future.groupby("player_id", sort=True)
    cohort = grouped[list(BASE_STATS)].sum().add_suffix("_ros")
    cohort["ros_games"] = grouped.size().astype(float)
    cohort["ros_points"] = grouped["fantasy_points"].sum()
    cohort["position"] = grouped["position"].agg(_majority)
    cohort["prior_games"] = cohort.index.map(prior_counts).fillna(0).astype(float)
    cohort = cohort[
        (cohort["ros_games"] >= min_remaining_games)
        & (cohort["prior_games"] < no_prior_games_threshold)
    ]
    cohort = cohort.reset_index()
    cohort["season"] = season
    cohort["cutoff_week"] = cutoff_week
    cohort["ros_ppg"] = cohort["ros_points"] / cohort["ros_games"]
    return cohort


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    total = weights.sum()
    return float((values * weights).sum() / total) if total > 0 else 0.0


def _fit_volume(
    rows: pd.DataFrame,
    volume: str,
    *,
    n0_grid: Sequence[float],
    prior_weight_grid: Sequence[float],
    recency_grid: Sequence[float],
    snap_n0_grid: Sequence[float] = (),
) -> tuple[VolumeParameters, float]:
    """Grid-search one position's volume constants; minimize weighted MSE.

    Two stages. First ``(n0, prior_weight, recency_weight)`` on the full
    grid with no snap term. Then, if ``snap_n0_grid`` is non-empty and the
    rows carry ``snap_share_last2``, ``snap_n0`` jointly with ``n0`` and
    ``prior_weight`` (recency held at its stage-one value), with
    ``snap_slope`` fitted through the origin by weighted least squares. A
    ``snap_n0`` of ``0`` is always a candidate, so the snap term is adopted
    only when it lowers the training loss.
    """
    g = rows["games_to_date"].to_numpy(dtype=float)
    gp = rows["prior_games"].to_numpy(dtype=float)
    ros_games = rows["ros_games"].to_numpy(dtype=float)
    target = rows[f"{volume}_ros"].to_numpy(dtype=float) / ros_games
    with np.errstate(divide="ignore", invalid="ignore"):
        observed = np.where(
            g > 0, rows[f"{volume}_to_date"].to_numpy(dtype=float) / g, 0.0
        )
        prior = np.where(
            gp > 0, rows[f"{volume}_prior"].to_numpy(dtype=float) / gp, 0.0
        )
    recent = rows[f"{volume}_recent"].to_numpy(dtype=float)
    no_prior = gp < NO_PRIOR_GAMES_THRESHOLD

    baseline = _weighted_mean(target[~no_prior], ros_games[~no_prior])
    no_prior_baseline = _weighted_mean(target[no_prior], ros_games[no_prior])
    base = np.where(no_prior, no_prior_baseline, baseline)

    best, best_loss = None, np.inf
    for rho in recency_grid:
        for d in prior_weight_grid:
            for n0 in n0_grid:
                values = VolumeParameters(n0, d, rho, baseline, no_prior_baseline)
                predicted = shrink_volume(g, observed, recent, gp, prior, base, values)
                loss = float(
                    np.sum(ros_games * (predicted - target) ** 2) / ros_games.sum()
                )
                if loss < best_loss - 1e-12:
                    best, best_loss = values, loss

    snap = _snap_share_array(rows)
    if not len(snap_n0_grid) or snap is None or np.all(np.isnan(snap)):
        return best, best_loss
    has = ~np.isnan(snap)
    weights = ros_games[has]
    denominator = float(np.sum(weights * snap[has] ** 2))
    slope = (
        float(np.sum(weights * snap[has] * target[has]) / denominator)
        if denominator > 0
        else 0.0
    )
    for snap_n0 in snap_n0_grid:
        for d in prior_weight_grid:
            for n0 in n0_grid:
                values = VolumeParameters(
                    n0,
                    d,
                    best.recency_weight,
                    baseline,
                    no_prior_baseline,
                    float(snap_n0),
                    slope,
                )
                predicted = shrink_volume(
                    g, observed, recent, gp, prior, base, values, snap_share=snap
                )
                loss = float(
                    np.sum(ros_games * (predicted - target) ** 2) / ros_games.sum()
                )
                if loss < best_loss - 1e-12:
                    best, best_loss = values, loss
    return best, best_loss


def _fit_rate(
    rows: pd.DataFrame,
    rate: str,
    *,
    k_grid: Sequence[float],
    prior_weight_grid: Sequence[float],
    expected_k_grid: Sequence[Optional[float]] = (None,),
) -> tuple[RateParameters, float]:
    """Grid-search one position's rate constants; minimize opportunity-weighted MSE.

    ``expected_k_grid`` candidates other than ``None`` are only tried when
    the rows carry the rate's expected columns; ``None`` (positional-mean
    target) is always a candidate, so the expected-rate target is adopted
    only when it lowers the training loss.
    """
    numerator, denominators = RATE_DEFINITIONS[rate]
    x = rows[f"{numerator}_to_date"].to_numpy(dtype=float)
    n = _denominator(rows, denominators, "_to_date")
    x_prev = rows[f"{numerator}_prior"].to_numpy(dtype=float)
    n_prev = _denominator(rows, denominators, "_prior")
    x_ros = rows[f"{numerator}_ros"].to_numpy(dtype=float)
    n_ros = _denominator(rows, denominators, "_ros")

    scored = n_ros > 0
    mean = float(x_ros[scored].sum() / n_ros[scored].sum()) if scored.any() else 0.0
    if not scored.any():
        return RateParameters(k=float(max(k_grid)), prior_weight=0.0, mean=mean), 0.0

    x, n, x_prev, n_prev = x[scored], n[scored], x_prev[scored], n_prev[scored]
    x_ros, n_ros = x_ros[scored], n_ros[scored]
    realized = x_ros / n_ros
    expected = _expected_arrays(rows, rate)
    if expected is not None:
        expected = tuple(array[scored] for array in expected)
    candidates = [None] + [value for value in expected_k_grid if value is not None]
    if expected is None:
        candidates = [None]

    best, best_loss = None, np.inf
    for expected_k in candidates:
        for d in prior_weight_grid:
            for k in k_grid:
                values = RateParameters(
                    k=float(k),
                    prior_weight=float(d),
                    mean=mean,
                    expected_k=None if expected_k is None else float(expected_k),
                )
                predicted = shrink_rate(
                    x,
                    n,
                    x_prev,
                    n_prev,
                    values,
                    expected=expected if expected_k is not None else None,
                )
                loss = float(np.sum(n_ros * (predicted - realized) ** 2) / n_ros.sum())
                if loss < best_loss - 1e-15:
                    best, best_loss = values, loss
    return best, best_loss


def fit_usage_components(
    panel: pd.DataFrame,
    fit_seasons: Sequence[int],
    *,
    positions: Sequence[str] = MODELED_POSITIONS,
    n0_grid: Sequence[float] = DEFAULT_VOLUME_N0_GRID,
    prior_weight_grid: Sequence[float] = DEFAULT_PRIOR_WEIGHT_GRID,
    recency_grid: Sequence[float] = DEFAULT_RECENCY_GRID,
    k_grid: Sequence[float] = DEFAULT_RATE_K_GRID,
    rate_prior_weight_grid: Sequence[float] = DEFAULT_RATE_PRIOR_WEIGHT_GRID,
    snap_n0_grid: Sequence[float] = (),
    expected_k_grid: Sequence[Optional[float]] = (None,),
    min_rows: int = 30,
) -> UsageModelParameters:
    """Fit every volume and rate constant on ``fit_seasons`` rows of ``panel``.

    Each component is fitted against its own realized rest-of-season value
    (volume per game, weighted by remaining games; rate per opportunity,
    weighted by remaining opportunities), in stat space -- so the constants
    are independent of any league's scoring settings.

    Args:
        panel: As returned by :func:`build_usage_panel`.
        fit_seasons: Seasons to fit on. **Must not include a season these
            parameters will be used to score.**
        positions: Positions to fit.
        n0_grid, prior_weight_grid, recency_grid: Volume grids.
        k_grid, rate_prior_weight_grid: Rate grids.
        snap_n0_grid: Snap-term grid (empty = no snap term). Needs
            ``snap_share_last2`` on the panel.
        expected_k_grid: Expected-rate target grid (``(None,)`` = off).
            Needs the ``exp_*`` columns on the panel.
        min_rows: Positions with fewer fit rows are left unfitted.

    Returns:
        A :class:`UsageModelParameters` with ``volume`` and ``rates``
        populated and no blend weights (see :func:`fit_blend_weights`).
    """
    rows = panel[panel["season"].isin(list(fit_seasons))] if not panel.empty else panel
    volume: dict[str, dict[str, VolumeParameters]] = {}
    rates: dict[str, dict[str, RateParameters]] = {}
    metrics: dict[str, dict[str, float]] = {}
    for position in positions:
        subset = rows[rows["position"] == position] if not rows.empty else rows
        if len(subset) < min_rows:
            continue
        volume[position] = {}
        rates[position] = {}
        position_metrics: dict[str, float] = {"rows": float(len(subset))}
        for stat in VOLUME_STATS:
            values, loss = _fit_volume(
                subset,
                stat,
                n0_grid=n0_grid,
                prior_weight_grid=prior_weight_grid,
                recency_grid=recency_grid,
                snap_n0_grid=snap_n0_grid,
            )
            volume[position][stat] = values
            position_metrics[f"{stat}_mse"] = loss
        for rate in RATE_DEFINITIONS:
            values, loss = _fit_rate(
                subset,
                rate,
                k_grid=k_grid,
                prior_weight_grid=rate_prior_weight_grid,
                expected_k_grid=expected_k_grid,
            )
            rates[position][rate] = values
            position_metrics[f"{rate}_mse"] = loss
        metrics[position] = position_metrics
    return UsageModelParameters(
        volume=volume,
        rates=rates,
        fit_seasons=tuple(sorted(int(season) for season in fit_seasons)),
        fit_metrics=metrics,
    )


def fit_absent_prior_stat_lines(
    cohort: pd.DataFrame, fit_seasons: Sequence[int]
) -> dict[str, dict[str, float]]:
    """Mean per-game stat line of the absent-prior cohort, per position.

    The mean over players of each player's per-game rest-of-season stat
    line. Because league scoring is linear in the stat line, scoring this
    mean line gives exactly the cohort's mean points per game under any
    scoring settings -- so one fitted line serves every league.

    Args:
        cohort: Stacked :func:`build_absent_prior_cohort` rows.
        fit_seasons: Seasons to fit on (must exclude any scored season).

    Returns:
        Position -> :data:`STAT_LINE_COLUMNS` -> per-game value.
    """
    if cohort.empty:
        return {}
    rows = cohort[cohort["season"].isin(list(fit_seasons))]
    lines: dict[str, dict[str, float]] = {}
    for position, subset in rows.groupby("position", sort=True):
        games = subset["ros_games"].to_numpy(dtype=float)
        line: dict[str, float] = {}
        for column in STAT_LINE_COLUMNS:
            if column in ("sack_fumbles_lost", "receiving_fumbles_lost"):
                line[column] = 0.0
                continue
            source = "fumbles_lost" if column == "rushing_fumbles_lost" else column
            line[column] = float(
                np.mean(subset[f"{source}_ros"].to_numpy(dtype=float) / games)
            )
        line["rows"] = float(len(subset))
        lines[str(position)] = line
    return lines


def fit_blend_weights(
    positions: pd.Series,
    eb_projected_ppg: pd.Series,
    usage_projected_ppg: pd.Series,
    actual_ppg: pd.Series,
    *,
    grid: Sequence[float] = DEFAULT_BLEND_GRID,
    min_rows: int = 30,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Fit ``a`` in ``a * usage + (1 - a) * eb`` per position by minimum MAE.

    Ties on the grid resolve to the smallest ``a`` -- the incumbent EB model
    keeps the weight unless the usage projection strictly improves on it.

    Returns:
        ``(blend_weight, metrics)``: position -> fitted ``a``, and position
        -> ``{"mae_eb", "mae_usage", "mae_blend", "rows"}`` at the fit.
    """
    weights: dict[str, float] = {}
    metrics: dict[str, dict[str, float]] = {}
    frame = pd.DataFrame(
        {
            "position": positions,
            "eb": eb_projected_ppg,
            "usage": usage_projected_ppg,
            "actual": actual_ppg,
        }
    ).dropna()
    for position, subset in frame.groupby("position", sort=True):
        if len(subset) < min_rows:
            continue
        eb = subset["eb"].to_numpy()
        usage = subset["usage"].to_numpy()
        actual = subset["actual"].to_numpy()
        best, best_mae = 0.0, np.inf
        for a in grid:
            mae = float(np.mean(np.abs(a * usage + (1 - a) * eb - actual)))
            if mae < best_mae - 1e-12:
                best, best_mae = float(a), mae
        weights[str(position)] = best
        metrics[str(position)] = {
            "mae_eb": float(np.mean(np.abs(eb - actual))),
            "mae_usage": float(np.mean(np.abs(usage - actual))),
            "mae_blend": best_mae,
            "rows": float(len(subset)),
        }
    return weights, metrics


# --------------------------------------------------------------------------
# Snap share and expected points (FFA-110 usage frame)
# --------------------------------------------------------------------------

#: ffopportunity expected-stat column -> the nflverse stat column it is the
#: expectation of. Scoring this "expected stat line" through the league's
#: settings gives a league-specific xFP; ffopportunity's own
#: ``ep_total_fantasy_points_exp`` is full PPR and is never used as points.
EXPECTED_STAT_SOURCES: dict[str, str] = {
    "attempts": "ep_pass_attempt",
    "completions": "ep_pass_completions_exp",
    "passing_yards": "ep_pass_yards_gained_exp",
    "passing_tds": "ep_pass_touchdown_exp",
    "passing_interceptions": "ep_pass_interception_exp",
    "passing_2pt_conversions": "ep_pass_two_point_conv_exp",
    "carries": "ep_rush_attempt",
    "rushing_yards": "ep_rush_yards_gained_exp",
    "rushing_tds": "ep_rush_touchdown_exp",
    "rushing_2pt_conversions": "ep_rush_two_point_conv_exp",
    "targets": "ep_rec_attempt",
    "receptions": "ep_receptions_exp",
    "receiving_yards": "ep_rec_yards_gained_exp",
    "receiving_tds": "ep_rec_touchdown_exp",
    "receiving_2pt_conversions": "ep_rec_two_point_conv_exp",
}

#: Rates whose shrinkage target can be the player's own *expected* rate
#: (expected numerator over charted opportunities) instead of the positional
#: mean. The expected rate prices where a player's opportunities came from
#: (depth of target, distance to the goal line), which his realized rate
#: over a few games cannot separate from luck.
EXPECTED_RATE_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "completion_rate": ("completions", ("attempts",)),
    "pass_yards_per_attempt": ("passing_yards", ("attempts",)),
    "pass_td_rate": ("passing_tds", ("attempts",)),
    "interception_rate": ("passing_interceptions", ("attempts",)),
    "rush_yards_per_carry": ("rushing_yards", ("carries",)),
    "rush_td_rate": ("rushing_tds", ("carries",)),
    "catch_rate": ("receptions", ("targets",)),
    "receiving_yards_per_target": ("receiving_yards", ("targets",)),
    "receiving_td_rate": ("receiving_tds", ("targets",)),
}

#: Columns :func:`build_opportunity_quality_features` returns.
OPPORTUNITY_QUALITY_COLUMNS = (
    [
        "snap_games_to_date",
        "snap_share",
        "snap_share_last2",
        "xfp_to_date",
        "xfp_share",
        "xfp_prior",
        "prior_snap_share",
    ]
    + [f"exp_{stat}_to_date" for stat in EXPECTED_STAT_SOURCES]
    + [f"exp_{stat}_prior" for stat in EXPECTED_STAT_SOURCES]
)


def expected_points(
    usage_weeks: pd.DataFrame, scoring_settings: Mapping[str, float]
) -> pd.Series:
    """League-scored expected fantasy points per usage row.

    Builds each row's expected stat line from :data:`EXPECTED_STAT_SOURCES`
    and scores it with
    :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`, so a
    half-PPR league gets half-PPR xFP. A row with no ffopportunity data
    (every ``ep_*`` column null -- a snap-only week) scores ``NaN``.

    Args:
        usage_weeks: Rows of ``players.usage.load_usage_player_weeks``.
        scoring_settings: The league's scoring settings.

    Returns:
        A float Series aligned to ``usage_weeks``.
    """
    present = [
        source for source in EXPECTED_STAT_SOURCES.values() if source in usage_weeks
    ]
    if usage_weeks.empty or not present:
        return pd.Series(np.nan, index=usage_weeks.index, dtype="float64")
    line = pd.DataFrame(
        {
            stat: usage_weeks[source].astype(float)
            if source in usage_weeks
            else pd.Series(0.0, index=usage_weeks.index)
            for stat, source in EXPECTED_STAT_SOURCES.items()
        }
    )
    has_data = usage_weeks[present].notna().any(axis=1)
    return score_stat_line(line.fillna(0.0), scoring_settings).where(has_data)


def build_opportunity_quality_features(
    usage_weeks: Optional[pd.DataFrame],
    season: int,
    cutoff_week: int,
    scoring_settings: Mapping[str, float],
    *,
    recency_games: int = DEFAULT_RECENCY_GAMES,
) -> pd.DataFrame:
    """Snap share and expected-points features per player at the cutoff.

    Reads weeks ``1..cutoff_week`` of ``season`` and the whole of
    ``season - 1`` from the usage frame, nothing later.

    Definitions (all over the player's usage rows in the window):

    - ``snap_share``: mean ``offense_snap_pct`` over weeks with a snap row;
      ``snap_share_last2``: the same over his last ``recency_games`` such
      weeks. A week with a snap row and zero offensive snaps counts as 0.
    - ``xfp_to_date``: sum of league-scored expected points
      (:func:`expected_points`); ``xfp_prior`` the same for ``season - 1``.
    - ``xfp_share``: ``sum(ep_rec_fantasy_points_exp + ep_rush_fantasy_points_exp)
      / sum(ep_total_fantasy_points_exp_team)`` -- the player's share of his
      team's rushing and receiving xFP (full PPR on both sides, so a ratio
      is scoring-neutral).
    - ``exp_{stat}_to_date`` / ``exp_{stat}_prior``: sums of each expected
      stat in :data:`EXPECTED_STAT_SOURCES`, the numerators and charted
      denominators of the expected rates.

    Args:
        usage_weeks: ``players.usage.load_usage_player_weeks`` output, keyed
            by ``gsis_id``. ``None`` or empty yields an empty frame.
        season: Season being projected.
        cutoff_week: Last knowable week.
        scoring_settings: League scoring settings, for the xFP columns.
        recency_games: Weeks in ``snap_share_last2``'s window.

    Returns:
        A DataFrame indexed by ``player_id`` (the GSIS id) with
        :data:`OPPORTUNITY_QUALITY_COLUMNS`. Missing sources stay ``NaN``.
    """
    empty = pd.DataFrame(columns=OPPORTUNITY_QUALITY_COLUMNS, dtype="float64")
    empty.index.name = "player_id"
    if usage_weeks is None or usage_weeks.empty:
        return empty

    window = usage_weeks[
        (usage_weeks["season"] == season)
        & (usage_weeks["week"] >= 1)
        & (usage_weeks["week"] <= cutoff_week)
    ]
    prior = usage_weeks[usage_weeks["season"] == season - 1]
    if window.empty and prior.empty:
        return empty

    def _summaries(frame: pd.DataFrame, suffix: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        frame = frame.assign(_xfp=expected_points(frame, scoring_settings))
        grouped = frame.groupby("gsis_id", sort=False)
        result = pd.DataFrame(index=grouped.size().index)
        result[f"xfp_{suffix}"] = grouped["_xfp"].sum(min_count=1)
        for stat, source in EXPECTED_STAT_SOURCES.items():
            if source in frame.columns:
                result[f"exp_{stat}_{suffix}"] = grouped[source].sum(min_count=1)
        if "offense_snap_pct" in frame.columns:
            result[f"_snap_share_{suffix}"] = grouped["offense_snap_pct"].mean()
        return result

    current = _summaries(window, "to_date")
    previous = _summaries(prior, "prior")

    features = current.join(previous, how="outer") if not current.empty else previous
    if "offense_snap_pct" in window.columns and not window.empty:
        snaps = window[window["offense_snap_pct"].notna()].sort_values(
            ["gsis_id", "week"], kind="stable"
        )
        grouped = snaps.groupby("gsis_id", sort=False)
        features["snap_games_to_date"] = grouped["offense_snaps"].agg(
            lambda values: float((values > 0).sum())
        )
        features["snap_share_last2"] = (
            grouped.tail(recency_games).groupby("gsis_id")["offense_snap_pct"].mean()
        )
    if "_snap_share_to_date" in features.columns:
        features["snap_share"] = features["_snap_share_to_date"]
    if "_snap_share_prior" in features.columns:
        features["prior_snap_share"] = features["_snap_share_prior"]
    share_columns = (
        "ep_rec_fantasy_points_exp",
        "ep_rush_fantasy_points_exp",
        "ep_total_fantasy_points_exp_team",
    )
    if not window.empty and all(column in window.columns for column in share_columns):
        grouped = window.groupby("gsis_id", sort=False)
        own = grouped["ep_rec_fantasy_points_exp"].sum(min_count=1).fillna(0) + grouped[
            "ep_rush_fantasy_points_exp"
        ].sum(min_count=1).fillna(0)
        team = grouped["ep_total_fantasy_points_exp_team"].sum(min_count=1)
        features["xfp_share"] = (own / team).where(team > 0)

    for column in OPPORTUNITY_QUALITY_COLUMNS:
        if column not in features.columns:
            features[column] = np.nan
    features.index.name = "player_id"
    return features[OPPORTUNITY_QUALITY_COLUMNS].astype("float64")


# --------------------------------------------------------------------------
# End-to-end fit and rolling-origin backtest
# --------------------------------------------------------------------------

#: Cutoff weeks the fit and the backtest pool over by default: the weeks a
#: waiver decision is actually made in, including week 3 (the live case on
#: 2026-09-29).
DEFAULT_FIT_CUTOFF_WEEKS = (2, 3, 4, 6, 8, 10)

#: Snap-term grid (pseudo-games) used by :func:`fit_usage_model`.
DEFAULT_SNAP_N0_GRID = (0.5, 1.0, 2.0, 3.0, 5.0, 8.0)

#: Name of the backtest's final-projection column (the blend).
BLENDED_PROJECTION_COLUMN = "blended_projected_ppg"

#: Name of the backtest's usage-only projection column.
USAGE_PROJECTION_COLUMN = "usage_projected_ppg"


def attach_opportunity_quality(
    panel: pd.DataFrame,
    usage_weeks: Optional[pd.DataFrame],
    scoring_settings: Mapping[str, float],
) -> pd.DataFrame:
    """Join :func:`build_opportunity_quality_features` onto every panel cell.

    Each ``(season, cutoff_week)`` cell gets the features computed at its
    own cutoff, so no cell sees a later week. ``usage_weeks=None`` returns
    ``panel`` unchanged (the no-snap model then applies).
    """
    if usage_weeks is None or usage_weeks.empty or panel.empty:
        return panel
    parts = []
    for (season, cutoff_week), cell in panel.groupby(
        ["season", "cutoff_week"], sort=False
    ):
        quality = build_opportunity_quality_features(
            usage_weeks, int(season), int(cutoff_week), scoring_settings
        )
        parts.append(cell.join(quality, on="player_id"))
    return pd.concat(parts).loc[panel.index]


def _eb_projection_by_cell(rows: pd.DataFrame, eb_parameters) -> pd.Series:
    """EB ``project_ppg`` evaluated cell by cell (its fallback is per cell)."""
    from fantasy_analyzer.players.ros_projection import project_ppg

    projected = pd.Series(np.nan, index=rows.index, dtype="float64")
    for _, cell in rows.groupby(["season", "cutoff_week"], sort=False):
        projected.loc[cell.index] = project_ppg(cell, eb_parameters).to_numpy()
    return projected


def fit_usage_model_on_panel(
    panel: pd.DataFrame,
    cohort: pd.DataFrame,
    fit_seasons: Sequence[int],
    scoring_settings: Mapping[str, float],
    eb_parameters,
    *,
    positions: Sequence[str] = MODELED_POSITIONS,
    snap_n0_grid: Sequence[float] = DEFAULT_SNAP_N0_GRID,
) -> UsageModelParameters:
    """Fit a complete parameter set (snap model + no-snap fallback) on a panel.

    Steps, all on ``fit_seasons`` rows only:

    1. Volume and rate constants twice -- once with the snap term (when the
       panel carries ``snap_share_last2``), once without.
    2. For each, the per-position blend weight against the EB projection
       (``eb_parameters``) under ``scoring_settings``.
    3. The absent-prior stat line from ``cohort`` (FFA-104).

    Args:
        panel: :func:`build_usage_panel` output, optionally with
            :func:`attach_opportunity_quality` applied.
        cohort: Stacked :func:`build_absent_prior_cohort` rows.
        fit_seasons: Seasons to fit on (must exclude every scored season).
        scoring_settings: Scoring used for the blend-weight fit. The volume
            and rate constants are scoring-independent.
        eb_parameters: The
            :class:`~fantasy_analyzer.players.ros_projection.ShrinkageParameters`
            the blend is fitted against.
        positions: Positions to fit.
        snap_n0_grid: Snap-term grid for the snap model.

    Returns:
        The snap-model :class:`UsageModelParameters` with its
        ``no_snap_fallback`` set, or the no-snap set alone when the panel
        has no snap data.
    """
    train = panel[panel["season"].isin(list(fit_seasons))]
    lines = fit_absent_prior_stat_lines(cohort, fit_seasons)
    eb_train = _eb_projection_by_cell(train, eb_parameters)
    no_snap_columns = [
        column for column in OPPORTUNITY_QUALITY_COLUMNS if column in train.columns
    ]

    def _complete(
        components: UsageModelParameters, rows: pd.DataFrame
    ) -> UsageModelParameters:
        usage = project_usage(rows, components, scoring_settings)["usage_projected_ppg"]
        weights, blend_metrics = fit_blend_weights(
            rows["position"], eb_train.loc[rows.index], usage, rows["ros_ppg"]
        )
        metrics = {
            **{key: dict(value) for key, value in components.fit_metrics.items()},
            **{f"blend_{key}": value for key, value in blend_metrics.items()},
        }
        return UsageModelParameters(
            volume=components.volume,
            rates=components.rates,
            blend_weight=weights,
            absent_prior_stat_line=lines,
            fit_seasons=components.fit_seasons,
            fit_metrics=metrics,
        )

    train_without = train.drop(columns=no_snap_columns)
    without = _complete(
        fit_usage_components(train_without, fit_seasons, positions=positions),
        train_without,
    )
    if (
        "snap_share_last2" not in train.columns
        or train["snap_share_last2"].isna().all()
    ):
        return without
    with_snaps = _complete(
        fit_usage_components(
            train, fit_seasons, positions=positions, snap_n0_grid=snap_n0_grid
        ),
        train,
    )
    return UsageModelParameters(
        volume=with_snaps.volume,
        rates=with_snaps.rates,
        blend_weight=with_snaps.blend_weight,
        absent_prior_stat_line=with_snaps.absent_prior_stat_line,
        fit_seasons=with_snaps.fit_seasons,
        fit_metrics=with_snaps.fit_metrics,
        no_snap_fallback=without,
    )


def fit_usage_model(
    scored_weeks: pd.DataFrame,
    fit_seasons: Sequence[int],
    scoring_settings: Mapping[str, float],
    *,
    usage_weeks: Optional[pd.DataFrame] = None,
    cutoff_weeks: Sequence[int] = DEFAULT_FIT_CUTOFF_WEEKS,
    eb_parameters=None,
    positions: Sequence[str] = MODELED_POSITIONS,
) -> UsageModelParameters:
    """Fit the usage model end to end from scored player-weeks.

    Builds the panel and the absent-prior cohort over ``fit_seasons``,
    fits the EB shrinkage on the same rows unless ``eb_parameters`` is
    given, and calls :func:`fit_usage_model_on_panel`.

    Args:
        scored_weeks: Scored player-weeks carrying :data:`REQUIRED_STAT_COLUMNS`
            for every fit season and its predecessor.
        fit_seasons: Seasons to fit on.
        scoring_settings: Scoring for the blend weights and xFP features.
        usage_weeks: Optional ``players.usage.load_usage_player_weeks``
            frame. ``None`` fits the no-snap model only.
        cutoff_weeks: Cutoffs to pool over.
        eb_parameters: EB constants to blend against; fitted if ``None``.
        positions: Positions to fit.

    Returns:
        A :class:`UsageModelParameters`.
    """
    from fantasy_analyzer.players.ros_projection import fit_shrinkage_on_rows

    skill = scored_weeks[scored_weeks["position"].isin(list(positions))]
    panel = build_usage_panel(skill, fit_seasons, cutoff_weeks)
    panel = attach_opportunity_quality(panel, usage_weeks, scoring_settings)
    cohorts = [
        build_absent_prior_cohort(skill, season, cutoff_week)
        for season in fit_seasons
        for cutoff_week in cutoff_weeks
    ]
    cohorts = [cohort for cohort in cohorts if not cohort.empty]
    cohort = pd.concat(cohorts, ignore_index=True) if cohorts else pd.DataFrame()
    if eb_parameters is None:
        eb_parameters = fit_shrinkage_on_rows(panel, fit_seasons, positions=positions)
    return fit_usage_model_on_panel(
        panel, cohort, fit_seasons, scoring_settings, eb_parameters, positions=positions
    )


def run_usage_backtest(
    panel: pd.DataFrame,
    cohort: pd.DataFrame,
    seasons: Sequence[int],
    scoring_settings: Mapping[str, float],
    *,
    min_fit_seasons: int = 3,
    waiver_population_only: bool = False,
    positions: Sequence[str] = MODELED_POSITIONS,
    by_position: bool = True,
) -> pd.DataFrame:
    """Rolling-origin backtest: EB vs usage vs blend, on the harness's rows.

    For each season in ``seasons``, every constant -- EB ``n0``, the usage
    volume/rate constants, the blend weights and the absent-prior line --
    is fitted on the panel's seasons strictly before it, then scored on
    that season alone with
    :func:`~fantasy_analyzer.players.ros_backtest.score_baselines`, next
    to the harness's own baselines.

    Args:
        panel: :func:`build_usage_panel` output spanning the scored seasons
            and every fit season, optionally with snap/xFP features.
        cohort: Stacked :func:`build_absent_prior_cohort` rows.
        seasons: Seasons to score.
        scoring_settings: The scoring ``panel``'s points were built with.
        min_fit_seasons: Seasons with fewer earlier panel seasons are skipped.
        waiver_population_only: Score only
            :func:`~fantasy_analyzer.players.ros_backtest.filter_to_waiver_population`.
        positions: Positions to fit and score.
        by_position: Passed to ``score_baselines``.

    Returns:
        :data:`~fantasy_analyzer.players.ros_backtest.ROS_METRIC_COLUMNS`
        rows for each baseline, ``projected_ppg`` (EB),
        :data:`USAGE_PROJECTION_COLUMN` and :data:`BLENDED_PROJECTION_COLUMN`.
    """
    from fantasy_analyzer.players.ros_backtest import (
        DEFAULT_BASELINES,
        ROS_METRIC_COLUMNS,
        RosEvaluationSet,
        filter_to_waiver_population,
        score_baselines,
    )
    from fantasy_analyzer.players.ros_projection import (
        PROJECTION_COLUMN,
        fit_shrinkage_on_rows,
    )

    panel = panel[panel["position"].isin(list(positions))]
    available = sorted(int(season) for season in panel["season"].unique())
    predictions = list(DEFAULT_BASELINES) + [
        PROJECTION_COLUMN,
        USAGE_PROJECTION_COLUMN,
        BLENDED_PROJECTION_COLUMN,
    ]
    results = []
    for season in sorted(seasons):
        fit_seasons = [candidate for candidate in available if candidate < season]
        if len(fit_seasons) < min_fit_seasons:
            continue
        eb_parameters = fit_shrinkage_on_rows(panel, fit_seasons, positions=positions)
        parameters = fit_usage_model_on_panel(
            panel,
            cohort,
            fit_seasons,
            scoring_settings,
            eb_parameters,
            positions=positions,
        )
        test = panel[panel["season"] == season].copy()
        if test.empty:
            continue
        has_snaps = "snap_share_last2" in test.columns
        chosen = parameters.for_snap_data(has_snaps)
        test[PROJECTION_COLUMN] = _eb_projection_by_cell(test, eb_parameters)
        test[USAGE_PROJECTION_COLUMN] = project_usage(test, chosen, scoring_settings)[
            "usage_projected_ppg"
        ]
        test[BLENDED_PROJECTION_COLUMN], _ = blend_projections(
            test["position"],
            test[PROJECTION_COLUMN],
            test[USAGE_PROJECTION_COLUMN],
            chosen,
        )
        for _, cell in test.groupby("cutoff_week", sort=True):
            evaluation_set = RosEvaluationSet(evaluation_df=cell.reset_index(drop=True))
            if waiver_population_only:
                evaluation_set = filter_to_waiver_population(evaluation_set)
            metrics = score_baselines(
                evaluation_set, predictions=predictions, by_position=by_position
            )
            if not metrics.empty:
                results.append(metrics)
    if not results:
        return pd.DataFrame(columns=ROS_METRIC_COLUMNS)
    return pd.concat(results, ignore_index=True)
