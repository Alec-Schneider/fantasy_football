"""A fitted, real-points-scale draft value curve (FFA-085).

This module answers a question ``draft_grade.py``/``draft_board.py``
explicitly flag as out of scope for themselves: *in real fantasy points,
not a rank-derived proxy score, how much value does a draft slot typically
return, and how much is a given player projected to be worth?*
``draft_board.py``'s own module docstring says it plainly: "This codebase
has no fitted points-by-pick curve to calibrate against ... so ``-ln`` is
used as a principled, parameter-free stand-in for that curve." This module
builds that fitted curve, from real history, and puts it to work.

The data: one already-completed draft's worth of ground truth
--------------------------------------------------------------------------

For a league that has already played a season, the codebase already has
both halves of the relationship this module needs, from two existing,
independently-built sources:

- **What a pick actually cost**: a season's normalized draft picks
  (:func:`~fantasy_analyzer.league.draft.build_normalized_draft_picks`,
  FFA-077) -- one row per pick, with ``pick_no`` and ``sleeper_player_id``.
- **What that pick actually returned**: the same season's league-wide
  composite player ranking
  (:func:`~fantasy_analyzer.players.player_rankings.build_league_player_rankings`,
  FFA-073) -- one row per player, with ``points_above_replacement`` (FFA-068's
  season-total value-over-replacement, in real fantasy points).

Joining the two on ``sleeper_player_id`` gives, for every non-keeper pick
in a completed draft, an ``(pick_no, points_above_replacement)`` pair: a
real, realized data point on "value returned by this exact draft slot."
:func:`fit_points_value_curve` fits a smooth curve through that scatter;
:func:`score_points_value` then evaluates the fitted curve against a
*different* season's draft (typically the upcoming one, scored against its
own board's ``draft_rank``) to produce a real-points-scale companion to
``draft_grade.py``'s ``pick_value``.

Curve shape and fit -- ``points_above_replacement = a + b * ln(pick_no)``
--------------------------------------------------------------------------

The same log-of-rank shape ``draft_board.py`` already assumes ("value
falls off steeply at the top and flattens at the bottom") is fit here with
real coefficients instead of used as an unparameterized stand-in: ordinary
least squares of ``points_above_replacement`` on ``ln(pick_no)``, one
predictor, closed-form (no external regression library needed)::

    x_i = ln(pick_no_i),  y_i = points_above_replacement_i
    b = sum((x_i - x_bar) * (y_i - y_bar)) / sum((x_i - x_bar) ** 2)
    a = y_bar - b * x_bar

:class:`PointsValueCurve` carries ``intercept`` (``a``), ``slope`` (``b``),
``n_picks`` (how many ``(pick_no, points_above_replacement)`` pairs the fit
used), and ``r_squared`` (``1 - SS_res / SS_tot``) so a caller can see, and
report, how much of the scatter the fit actually explains -- this is a
single-season, single-league sample (roughly 150-190 non-keeper picks for
the leagues this codebase covers), individual player outcomes are noisy
(injuries, breakouts, busts), and an ``r_squared`` in the 0.3-0.4 range on
real data is expected and still meaningfully better than no curve at all,
not a sign of a broken fit. Report ``r_squared`` alongside any number this
curve produces; do not present the curve as more precise than it is.

:meth:`PointsValueCurve.value_at` evaluates ``a + b * ln(x)`` for any
``x >= 1`` (a pick number or a board rank -- both live on the same "1st,
2nd, 3rd best" ordinal scale, so the same fitted function applies to
either), clamping ``x`` up to ``1.0`` first (``ln`` is undefined at and
below 0, and a "0th pick" is not a meaningful input).

Two things this curve is used for, both scored by :func:`score_points_value`
--------------------------------------------------------------------------

Given a *different* draft's picks (``scored_picks_df``, FFA-078's own
output) and that draft's board (``board_df``, ``draft_board.py``'s
output, read here for ``draft_rank``):

    ``projected_points_value = curve.value_at(draft_rank of the player taken)``

"Given where this year's board ranks this player, how many points above
replacement does history say a player at that rank is worth?" -- a
genuine, real-points-scale projection, standing in for the season
projection this codebase does not otherwise have (see
``draft_board.py``'s own "no season-long point projection is in scope"
note).

    ``expected_points_value_at_pick = curve.value_at(pick_no actually used)``

"What does history say a pick at this exact slot typically returns?" --
independent of which player was actually taken.

    ``pick_value_points = projected_points_value - expected_points_value_at_pick``

Same sign convention as ``draft_grade.py``'s ``pick_value``: positive
means the player's projected real-points value exceeds what the slot
typically returns (a steal); negative means the reverse (a reach). This is
a genuine points-scale sibling to ``pick_value`` (which measures the same
question on the current board's own, market-relative ``draft_score``
scale) -- the two will usually agree in sign and can be read side by side,
but need not always agree, since they answer subtly different questions
(“more value than the market expects this year” vs. “more real points
than history says this slot returns”).

Worked toy example (hand-checked in tests) -- a perfect-fit curve
--------------------------------------------------------------------------

Four historical picks, deliberately exact multiples of 2 so their natural
logs fall on an evenly-spaced grid (``ln(2), ln(4)=2ln(2), ln(8)=3ln(2)``),
paired with ``points_above_replacement`` values chosen to be *exactly*
linear in that grid -- a perfect fit (``r_squared = 1.0``), for maximum
hand-checkability::

    pick_no=1 -> points_above_replacement=30   (ln(1)=0)
    pick_no=2 -> points_above_replacement=20   (ln(2))
    pick_no=4 -> points_above_replacement=10   (ln(4) = 2 ln(2))
    pick_no=8 -> points_above_replacement=0    (ln(8) = 3 ln(2))

    b = -10 / ln(2) ~= -14.4270,  a = 30.0

    curve.value_at(1) = 30 + b*ln(1)  = 30.0
    curve.value_at(2) = 30 + b*ln(2)  = 30 - 10       = 20.0
    curve.value_at(4) = 30 + b*ln(4)  = 30 - 20        = 10.0
    curve.value_at(8) = 30 + b*ln(8)  = 30 - 30        =  0.0
    curve.value_at(16)= 30 + b*ln(16) = 30 - 40        = -10.0   (extrapolated)

Keeper handling
--------------------------------------------------------------------------

Both halves of this module drop keeper picks, for the identical reason
``draft_grade.py`` excludes them from grading: a keeper's draft slot is
not a real market-clearing price, so counting it would teach the curve a
false relationship between slot and value (and, symmetrically, scoring a
keeper pick against the curve would grade a decision that was not really
made this year). :func:`fit_points_value_curve` drops any row where
``is_keeper is True`` from the fitting sample entirely, before computing
``x_bar``/``y_bar``. :func:`score_points_value` forces
``pick_value_points = NaN`` for any pick with ``excluded_reason ==
"keeper"`` (the same flag ``draft_grade.py`` already sets), the same
"still visible, not dropped, but excluded from being graded" convention
``pick_value``/``vor`` use there -- ``projected_points_value`` is left
populated for a keeper (it describes the player, not the transaction).

K and DEF are excluded from the fitting sample
--------------------------------------------------------------------------

:data:`DEFAULT_POINTS_CURVE_EXCLUDED_POSITIONS` is ``frozenset({"K",
"DEF"})``, the identical stance ``draft_board.py`` takes on its own
retrospective component and for the identical reason: the FFA-073
composite ranking this module reads realized value from is built on a
scoring engine that cannot map every Sleeper team-defense rule at all, and
maps kicker rules incompletely, so a K/DEF ``points_above_replacement`` is
not on the same footing as a QB/RB/WR/TE's and would distort the fit if
included. DEF rows do not appear in the retrospective frame in practice
anyway (the join simply misses them); the explicit K filter is the one
that actually removes rows. Pass
``excluded_positions=frozenset()`` to disable this.

Missing values / edge cases
--------------------------------------------------------------------------

- **Fewer than two usable (non-keeper, non-excluded-position, joined,
  non-``NaN``) picks**: :func:`fit_points_value_curve` returns ``None`` --
  an OLS fit needs at least two points, and this module never fabricates
  one. Callers must handle a ``None`` curve (:func:`score_points_value`
  treats it exactly like an empty curve: every new column ``NaN``).
- **Zero variance in ``ln(pick_no)``** (every usable pick shares the same
  ``pick_no`` -- unreachable in a real draft, only reachable from a
  degenerate hand-built frame): the OLS denominator is 0; returns ``None``
  for the identical "cannot support this claim" reason
  ``draft_report.py``'s z-score helper documents for zero-variance
  populations.
- **A pick with no board match, or a ``draft_rank`` of ``NaN``**:
  ``projected_points_value = NaN`` (there is no rank to evaluate the curve
  at), hence ``pick_value_points = NaN`` too.
  ``expected_points_value_at_pick`` is unaffected -- like
  ``draft_grade.py``'s ``expected_value_at_pick``, it depends only on
  ``pick_no`` and the curve, not on which player was taken.
- **``pick_no`` missing on the pick itself**: both
  ``expected_points_value_at_pick`` and (transitively) ``pick_value_points``
  are ``NaN``.
- **``curve is None``**: every one of the three new columns is ``NaN`` for
  every pick.

Regular season vs. playoffs
--------------------------------------------------------------------------

:func:`fit_points_value_curve` inherits whatever phase scope
``prior_df``'s ``points_above_replacement`` was built over (the identical
"this module makes no independent phase distinction" stance
``draft_board.py`` documents for its own retrospective component) --
regular-season-only is the convention this codebase's existing 2025
retrospective files use and is "arguably the more defensible ... signal"
per that module's own note, since a playoff-only sample is a handful of
weeks from a subset of teams. :func:`score_points_value` never looks at
weekly data at all -- like FFA-078/FFA-079, it is a draft-time computation
with no regular-season/playoff distinction of its own.

Column dtypes
--------------------------------------------------------------------------

:class:`PointsValueCurve` fields are all ``float`` (``n_picks`` is
``int``). :func:`score_points_value` returns every column of
``scored_picks_df`` unchanged plus three new ``float64`` columns
(``projected_points_value``, ``expected_points_value_at_pick``,
``pick_value_points``), so an undefined value is ``NaN``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

from fantasy_analyzer.players.draft_grade import SCORED_DRAFT_PICK_COLUMNS

#: Positions dropped from the curve-fitting sample -- see the module
#: docstring's "K and DEF are excluded" section.
DEFAULT_POINTS_CURVE_EXCLUDED_POSITIONS = frozenset({"K", "DEF"})

#: Column order for the DataFrame returned by :func:`score_points_value`.
POINTS_VALUE_PICK_COLUMNS = SCORED_DRAFT_PICK_COLUMNS + [
    "projected_points_value",
    "expected_points_value_at_pick",
    "pick_value_points",
]

_NEW_FLOAT_COLUMNS = [
    "projected_points_value",
    "expected_points_value_at_pick",
    "pick_value_points",
]


def _is_missing(value: Any) -> bool:
    """True for ``None``, ``NaN``/``NA``, and the empty string.

    Duplicated from the identical helper in ``draft_grade.py`` and
    ``draft_board.py`` rather than imported -- this codebase does not
    import private names across modules.
    """
    if isinstance(value, str):
        return value == ""
    return pd.isna(value)


def _optional_float(value: Any) -> Optional[float]:
    """``float(value)`` unless ``value`` is missing, in which case ``None``."""
    return None if _is_missing(value) else float(value)


@dataclass(frozen=True)
class PointsValueCurve:
    """A fitted ``points_above_replacement = intercept + slope * ln(x)`` curve.

    See the module docstring's "Curve shape and fit" section. Constructed
    only by :func:`fit_points_value_curve` -- never build one by hand
    outside a test, since ``r_squared``/``n_picks`` are meant to travel
    with the fit that produced them.

    Attributes:
        intercept: ``a`` in ``a + b * ln(x)``.
        slope: ``b`` in ``a + b * ln(x)``. Negative for a real draft (value
            declines as pick number/rank increases).
        n_picks: How many ``(pick_no, points_above_replacement)`` pairs the
            fit used, after dropping keepers, excluded positions, and
            unjoined/missing rows. Always ``>= 2`` (see
            :func:`fit_points_value_curve`'s missing-value handling for
            when a curve cannot be built at all).
        r_squared: ``1 - SS_res / SS_tot`` of the fit against its own
            training sample. ``1.0`` for a perfect fit; can be small (even
            close to ``0``) for a genuinely noisy single-season sample --
            always report it alongside any value this curve produces.
    """

    intercept: float
    slope: float
    n_picks: int
    r_squared: float

    def value_at(self, x: float) -> float:
        """``intercept + slope * ln(max(x, 1.0))``.

        ``x`` is a pick number or a board rank -- both are 1-indexed
        ordinal positions on the same scale this curve was fit against.
        Clamped up to ``1.0`` first: ``ln`` is undefined at ``0`` and
        negative for ``0 < x < 1``, and neither is a meaningful pick
        number or rank.
        """
        return self.intercept + self.slope * math.log(max(x, 1.0))


def fit_points_value_curve(
    picks_df: pd.DataFrame,
    prior_df: pd.DataFrame,
    *,
    excluded_positions: frozenset[str] = DEFAULT_POINTS_CURVE_EXCLUDED_POSITIONS,
) -> Optional[PointsValueCurve]:
    """Fit a real-points draft value curve from one completed season's draft.

    Joins ``picks_df`` to ``prior_df`` on ``sleeper_player_id``, drops
    keeper picks and any pick at a position in ``excluded_positions``, and
    fits ``points_above_replacement = intercept + slope * ln(pick_no)`` by
    ordinary least squares. See the module docstring for the full formula,
    the worked toy example, and every missing-value case.

    Args:
        picks_df: A :data:`~fantasy_analyzer.league.draft.
            NORMALIZED_DRAFT_PICK_COLUMNS`-shaped frame for one **already-
            completed** season's draft -- read for ``pick_no``,
            ``sleeper_player_id``, ``is_keeper``, and ``position``.
        prior_df: A :data:`~fantasy_analyzer.players.player_rankings.
            LEAGUE_PLAYER_RANKING_COLUMNS`-shaped frame for the **same**
            season -- read for ``sleeper_player_id`` and
            ``points_above_replacement``.
        excluded_positions: Positions dropped from the fitting sample. See
            :data:`DEFAULT_POINTS_CURVE_EXCLUDED_POSITIONS`.

    Returns:
        A :class:`PointsValueCurve`, or ``None`` if fewer than two usable
        ``(pick_no, points_above_replacement)`` pairs are available, or if
        every usable pick shares the same ``pick_no`` (zero variance).
    """
    if picks_df is None or picks_df.empty or prior_df is None or prior_df.empty:
        return None

    prior_lookup: dict[str, Optional[float]] = {}
    for row in prior_df.itertuples(index=False):
        player_id = getattr(row, "sleeper_player_id", None)
        if _is_missing(player_id):
            continue
        prior_lookup[str(player_id)] = _optional_float(
            getattr(row, "points_above_replacement", None)
        )

    points: list[tuple[float, float]] = []
    for pick in picks_df.itertuples(index=False):
        if getattr(pick, "is_keeper", None) is True:
            continue
        position = getattr(pick, "position", None)
        if not _is_missing(position) and str(position) in excluded_positions:
            continue
        player_id = getattr(pick, "sleeper_player_id", None)
        if _is_missing(player_id):
            continue
        pick_no = _optional_float(getattr(pick, "pick_no", None))
        if pick_no is None or pick_no <= 0:
            continue
        y = prior_lookup.get(str(player_id))
        if y is None:
            continue
        points.append((math.log(pick_no), y))

    if len(points) < 2:
        return None

    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    x_bar = math.fsum(xs) / len(xs)
    y_bar = math.fsum(ys) / len(ys)

    ss_xx = math.fsum((x - x_bar) ** 2 for x in xs)
    if ss_xx == 0:
        return None

    ss_xy = math.fsum((x - x_bar) * (y - y_bar) for x, y in points)
    slope = ss_xy / ss_xx
    intercept = y_bar - slope * x_bar

    ss_tot = math.fsum((y - y_bar) ** 2 for y in ys)
    if ss_tot == 0:
        r_squared = 1.0
    else:
        ss_res = math.fsum((y - (intercept + slope * x)) ** 2 for x, y in points)
        r_squared = 1.0 - ss_res / ss_tot

    return PointsValueCurve(
        intercept=intercept, slope=slope, n_picks=len(points), r_squared=r_squared
    )


def _empty_result(scored_picks_df: pd.DataFrame) -> pd.DataFrame:
    """A copy of ``scored_picks_df`` (zero rows) with the new columns added."""
    result = scored_picks_df.copy()
    for column in SCORED_DRAFT_PICK_COLUMNS:
        if column not in result.columns:
            result[column] = pd.Series(dtype=object)
    for column in _NEW_FLOAT_COLUMNS:
        result[column] = pd.Series(dtype="float64")
    return result[POINTS_VALUE_PICK_COLUMNS]


def score_points_value(
    scored_picks_df: pd.DataFrame,
    board_df: pd.DataFrame,
    curve: Optional[PointsValueCurve],
) -> pd.DataFrame:
    """Evaluate a fitted :class:`PointsValueCurve` against one draft's picks.

    Args:
        scored_picks_df: :func:`~fantasy_analyzer.players.draft_grade.
            score_draft_picks`'s own output (FFA-078,
            :data:`~fantasy_analyzer.players.draft_grade.
            SCORED_DRAFT_PICK_COLUMNS`-shaped) -- read for ``pick_no``,
            ``sleeper_player_id``, and ``excluded_reason``.
        board_df: The same :data:`~fantasy_analyzer.players.draft_board.
            DRAFT_BOARD_COLUMNS`-shaped frame ``scored_picks_df`` was
            scored against -- read here for ``draft_rank`` (not carried
            through by ``score_draft_picks``, so re-read directly).
        curve: A :class:`PointsValueCurve`, typically fit by
            :func:`fit_points_value_curve` against a **prior** completed
            season -- ``None`` if no curve could be fit (every new column
            is ``NaN`` in that case).

    Returns:
        A DataFrame with columns :data:`POINTS_VALUE_PICK_COLUMNS`, one row
        per row of ``scored_picks_df``, in the same order.
    """
    if scored_picks_df.empty:
        return _empty_result(scored_picks_df)

    draft_rank_lookup: dict[str, Optional[float]] = {}
    if board_df is not None and not board_df.empty:
        for row in board_df.itertuples(index=False):
            player_id = getattr(row, "sleeper_player_id", None)
            if _is_missing(player_id):
                continue
            draft_rank_lookup[str(player_id)] = _optional_float(
                getattr(row, "draft_rank", None)
            )

    rows: list[dict[str, Any]] = []
    for pick in scored_picks_df.itertuples(index=False):
        pick_dict = {
            column: getattr(pick, column) for column in SCORED_DRAFT_PICK_COLUMNS
        }

        pick_no = _optional_float(pick_dict.get("pick_no"))
        expected_points_value_at_pick = (
            None if curve is None or pick_no is None else curve.value_at(pick_no)
        )

        player_id = pick_dict.get("sleeper_player_id")
        draft_rank = (
            None if _is_missing(player_id) else draft_rank_lookup.get(str(player_id))
        )
        projected_points_value = (
            None if curve is None or draft_rank is None else curve.value_at(draft_rank)
        )

        pick_value_points = (
            None
            if projected_points_value is None or expected_points_value_at_pick is None
            else projected_points_value - expected_points_value_at_pick
        )
        if pick_dict.get("excluded_reason") == "keeper":
            pick_value_points = None

        pick_dict.update(
            {
                "projected_points_value": projected_points_value,
                "expected_points_value_at_pick": expected_points_value_at_pick,
                "pick_value_points": pick_value_points,
            }
        )
        rows.append(pick_dict)

    result = pd.DataFrame(rows, columns=POINTS_VALUE_PICK_COLUMNS)
    for column in _NEW_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    # pandas' DataFrame-from-records constructor infers a mixed
    # string/None column (e.g. "keeper" and None side by side) as a
    # string dtype that silently normalizes None to NaN -- unlike a
    # mixed bool/None column, which is left as object dtype with None
    # intact. ``excluded_reason`` is exactly the former shape (a real
    # string on a minority of rows, None elsewhere), so without this
    # explicit re-normalization every ``is None`` check downstream (this
    # module's own keeper handling included) would silently break. Same
    # convention ``draft_grade.py`` already uses for its own new object
    # columns, applied here to the two pass-through columns this module's
    # own logic depends on staying real ``None``.
    for column in ("expected_pick_source", "excluded_reason"):
        result[column] = pd.Series(
            [
                None if _is_missing(value) else value
                for value in result[column].tolist()
            ],
            dtype=object,
        )
    return result[POINTS_VALUE_PICK_COLUMNS]
