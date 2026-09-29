"""Waiver-wire value ranking: rank free agents by ROS points above replacement
(FFA-092).

This module is the bridge between three already-shipped pieces this ticket
must not re-derive:

- :mod:`fantasy_analyzer.players.free_agents` (FFA-091) supplies the
  league's current-state free-agent *pool* -- who is available, and whether
  he has an nflverse (``gsis_id``) crosswalk match at all.
- :mod:`fantasy_analyzer.players.ros_projection` (FFA-090) supplies the
  shrinkage estimator (``projected_ppg = w * observed + (1 - w) * prior``,
  ``w = games / (games + n0)``) that turns season-to-date production into a
  rest-of-season points-per-game projection. This module calls
  :func:`~fantasy_analyzer.players.ros_projection.project_ppg` directly; it
  does not reimplement the blend.
- :mod:`fantasy_analyzer.players.player_value` (FFA-068) supplies the
  replacement-level / VORP machinery. This module builds a
  ``performance_df``-shaped frame out of *projected* (not realized)
  production and feeds it to
  :func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`
  unchanged -- no replacement level or VORP arithmetic is reimplemented here
  either.

What this module adds is the missing middle step:
:mod:`fantasy_analyzer.players.ros_backtest` (FFA-089) computes the
season-to-date features (games/points/ppg-to-date, last-3 ppg, prior-season
ppg) with its own private helpers, but only for players who *also* have a
realized rest-of-season outcome to score against -- a backtest requirement
that is impossible for a real, in-progress season's free agents, who by
definition have no future yet. :func:`build_free_agent_ros_projections`
re-derives the small "season-to-date summary" computation directly against
raw scored player-weeks (not by importing FFA-089's private helpers), for a
player population FFA-089 cannot serve: unscored, currently-available,
possibly zero-games-played free agents.

Why the ranking is VORP, not raw projected points per game
--------------------------------------------------------------------------

Ranking free agents by raw ``projected_ppg`` would let a mediocre RB (say,
8 ppg in a deep, low-replacement position) outrank a legitimately startable
TE (say, 7 ppg, but 3 ppg above a thin TE replacement level) whenever the
RB's raw rate happens to be higher -- exactly the FFA-068 VORP argument,
applied here to a projection instead of a realized total. The fix is
identical: subtract the position's replacement level before comparing
across positions. See :mod:`fantasy_analyzer.players.player_value`'s module
docstring for the full replacement-level methodology (starter-slot
counting, the clamp when a league under-rosters a position, etc.) --
unchanged here.

Whom the replacement level is measured over (FFA-095)
--------------------------------------------------------------------------

The VORP argument above only works if "replacement level" means *the
league's* last startable player at the position. Originally this module
passed only ``free_agent_pool`` to FFA-068, which silently redefined it as
the last startable player **among free agents** -- a very different, and
much worse, number.

Measured on the 2026 week-1 board for a 12-team league, the difference is
not subtle:

===========  =========================  =========================
Position     Replacement ppg, wire      Replacement ppg, league
===========  =========================  =========================
QB           11.3                       17.5
RB            1.9                        8.5
TE            5.4                        6.7
===========  =========================  =========================

The RB row is the clearest failure: ranked over free agents alone, the
"last startable RB" was the 36th-best *unrostered* RB at 1.92 ppg, because
the pool is the entire unrostered catalog and its tail is full of players
who will never take a snap. Every free-agent RB was then scored against
that floor, which inflated positional VORP across the board and -- worse
-- made the *cross-position* ordering an artifact of which position had the
longer junk tail. On a one-QB league the resulting board was topped by
quarterbacks and kickers.

Pass ``replacement_population`` (the league-wide pool,
``build_free_agent_pool([], ...)``) to fix this. The rostered players are
used to set the bar and are then dropped from the output; only free agents
are ever returned. The default remains the original behavior so existing
callers are unaffected, but a real waiver board should always supply it.

Note the deliberate knock-on effect: with a league-wide population, the
positional-mean fallback prior for a zero-game player (see "Why the
fallback pool is free agents, not the whole league" below) also becomes
league-wide. That is the consistent choice once the ranking's frame of
reference is the league rather than the wire -- the section below describes
the ``replacement_population=None`` case.

The pipeline, end to end
--------------------------------------------------------------------------

1. :func:`build_free_agent_ros_projections` -- for every free agent in
   ``free_agent_pool``, compute season-to-date features from
   ``scored_weeks`` (games/points/ppg to date, last-3 ppg, prior-season
   ppg), blend them into ``projected_ppg`` via
   :func:`~fantasy_analyzer.players.ros_projection.project_ppg`, and turn
   that rate into a rest-of-season point total using **remaining regular
   season weeks** (see "Regular season vs. playoffs" below). Also reports
   the exact blend weight ``w`` and a games-to-date confidence tier for
   every player -- the "the ranking must explain itself" requirement.
2. :func:`build_waiver_wire_rankings` -- reshapes step 1's output into a
   ``performance_df``-shaped frame (``games_played`` = projected remaining
   games, ``points_per_game`` = ``projected_ppg``, ``total_points`` =
   ``projected_ppg * remaining_games``), feeds it to FFA-068's
   :func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`
   unmodified, and merges the resulting replacement/VORP columns back onto
   the explanatory columns from step 1. The result is ranked by descending
   ``points_above_replacement`` (FFA-068's ``value_rank``, renamed
   ``waiver_rank`` here for clarity, since "the league" this rank is
   computed over is the free-agent pool passed in, not the whole rostered
   league).

Toy example (hand-checkable)
--------------------------------------------------------------------------

One free agent, ``"99"`` (WR), ``n0(WR) = 3.0``, cutoff week 4,
``season_end_week = 17``:

- Weeks 1-4 scored: 8, 12, 10, 6 fantasy points (via ``gsis_id`` "WR99").
  ``games_to_date = 4``, ``points_to_date = 36``, ``ppg_to_date = 9.0``.
- No ``prior_season_weeks`` supplied, and he is the only WR in the pool, so
  the position-mean fallback (see :func:`project_ppg`'s docstring) is his
  own ``ppg_to_date``, ``9.0`` -- ``prior_resolved_ppg = 9.0``.
- ``w = 4 / (4 + 3) = 0.5714...``.
- ``projected_ppg = 0.5714... * 9.0 + 0.4286... * 9.0 = 9.0`` (degenerate
  here because prior equals observed with only one WR in the pool; see the
  module's tests for a case with a second WR where the fallback differs
  from the player's own rate).
- ``remaining_games = 17 - 4 = 13``; ``projected_ros_points = 9.0 * 13 =
  117.0``.
- ``confidence_tier``: ``games_to_date = 4`` falls in
  :data:`CONFIDENCE_TIER_MEDIUM_MAX_GAMES`'s range (3-7 games) -> ``"medium"``.

Regular season vs. playoffs
--------------------------------------------------------------------------

``remaining_games`` counts **remaining regular-season weeks only**:
``max(season_end_week - cutoff_week, 0)``, where ``season_end_week``
defaults to
:data:`~fantasy_analyzer.players.ros_backtest.DEFAULT_SEASON_END_WEEK` (17)
-- the same boundary ``ros_backtest.py`` uses to exclude a fantasy
league's playoff weeks and the injury-prone, matchup-driven NFL week 18
from its own rest-of-season target. A caller with a league that ends its
*fantasy* regular season earlier passes a smaller ``season_end_week``.

This is a **schedule-only** count, not an availability model: it does not
subtract bye weeks or account for a player's own injury risk, matching
:mod:`fantasy_analyzer.players.ros_projection`'s explicit "no availability
model" scope note. A free agent who has a bye in one of his remaining weeks
will, on average, play one fewer game than ``remaining_games`` implies, so
``projected_ros_points`` is a mild overstatement for such players. This is a
documented limitation, not a silent one.

Handling a zero-games-to-date free agent (rookie / inactive-to-date)
--------------------------------------------------------------------------

A free agent with a crosswalk match but no scored weeks yet this season
still gets a projection: ``games_to_date = 0`` forces ``w = 0`` exactly
(``0 / (0 + n0) = 0``), so ``projected_ppg`` collapses to the resolved prior
-- his own ``prior_season_ppg`` if he has one, else the **mean
``ppg_to_date`` among fellow free agents at his position who have played at
least one game this season** (computed once per position, from the
population that actually has games-to-date; see "Why the fallback pool is
free agents, not the whole league" below). This mirrors
:func:`~fantasy_analyzer.players.ros_projection.project_ppg`'s own
fallback rule, applied by hand here rather than by calling that function on
a mixed population -- see the implementation note below for why.

Implementation note: ``project_ppg`` cannot be called directly on a mixed
population that includes zero-game rows. Its fallback,
``groupby("position")["ppg_to_date"].mean()``, is computed over *whatever
frame it is given*; a zero-game row would need a placeholder
``ppg_to_date`` to avoid ``0.0 * NaN`` producing ``NaN`` in the weighted
sum (``weight`` is exactly ``0.0`` for a zero-game row, but ``0.0 * NaN``
is ``NaN``, not ``0.0``), and any placeholder value fed into that same
frame would corrupt the very positional mean the zero-game rows are trying
to read. This module therefore projects the two populations separately:
``project_ppg`` is called, unmodified, on the sub-frame of free agents who
have at least one game this season (exactly the population
:func:`~fantasy_analyzer.players.ros_backtest.build_ros_evaluation_set`
would itself have kept, since it requires ``games_to_date >= 1``), which
also produces the position-mean fallback this module reuses by hand for the
zero-game rows.

Why the fallback pool is free agents, not the whole league
--------------------------------------------------------------------------

The positional mean used as a rookie's fallback prior is computed **only
over free agents who have played this season**, not over the full rostered
league. This is a deliberate, documented choice: it is the correct read of
"what does an average member of the population this ranking scores look
like," and it is the same choice ``ros_backtest.py``'s own fallback makes
implicitly -- its "evaluated players" pool is whatever frame the caller
built, never a separate broader reference population. A rookie free agent
being compared against an above-average full-league prior would be
inconsistent with the fact that he is, by construction, currently
unrostered.

A free agent with **no crosswalk match at all**
--------------------------------------------------------------------------

Per FFA-091's "don't drop, null" convention, continued here: a free agent
with ``has_crosswalk = False`` gets a real row in the output with every
projection-derived column set to ``NaN``/``None`` (``games_to_date``,
``ppg_to_date``, ``last3_ppg``, ``prior_season_ppg``, ``prior_resolved_ppg``,
``blend_weight``, ``confidence_tier``, ``projected_ppg``,
``projected_ros_points``, and downstream every VORP column) -- genuinely no
projection is possible without an nflverse identity to look up scored
weeks against. ``remaining_games`` is still populated (it is a pure
schedule fact, independent of the player), and the pool-identity columns
from :data:`~fantasy_analyzer.players.free_agents.FREE_AGENT_POOL_COLUMNS`
are always carried through.

Sample-size confidence tiers
--------------------------------------------------------------------------

A simple, explicit bucketing of ``games_to_date`` -- not a statistical
confidence interval, a coarse display aid:

- **low**: ``games_to_date <= 2`` (:data:`CONFIDENCE_TIER_LOW_MAX_GAMES`).
  At most two games; with the shrinkage grid's ``n0`` values typically in
  the 1-12 range (see
  :data:`~fantasy_analyzer.players.ros_projection.DEFAULT_N0_GRID`), a
  player this early is at or below half-weight on his own observed rate for
  every position tested.
- **medium**: ``3 <= games_to_date <= 7``
  (:data:`CONFIDENCE_TIER_MEDIUM_MAX_GAMES`). Roughly a quarter to
  under-half of a 17-week season.
- **high**: ``games_to_date >= 8``. At least a half-season of evidence.

A free agent with no crosswalk match, or (defensively) any row with an
undefined ``games_to_date``, gets ``confidence_tier = None`` rather than a
tier -- there is no games-to-date value to bucket.

Column dtypes
--------------------------------------------------------------------------

``games_to_date``, ``ppg_to_date``, ``last3_ppg``, ``prior_season_ppg``,
``prior_resolved_ppg``, ``blend_weight``, ``projected_ppg``,
``remaining_games``, ``projected_ros_points``, ``replacement_ppg``,
``ppg_above_replacement``, ``points_above_replacement``, ``waiver_rank``
and ``player_owned_avg`` are ``float64``, with undefined values as
``NaN``. ``confidence_tier`` is ``object``, with an undefined value as
``None`` explicitly (never ``NaN``) -- built via a plain Python list
rather than ``Series.map``, since pandas can otherwise silently coerce a
returned ``None`` into ``NaN`` in a column that is mostly strings,
depending on the pandas string-dtype configuration in effect. Test it with
``is None``.

Ties, missing values, empty input
--------------------------------------------------------------------------

- **Empty ``free_agent_pool``**: both builders return an empty, correctly
  shaped, correctly typed frame.
- **Ties in ``waiver_rank``**: inherited verbatim from FFA-068's
  ``value_rank`` -- standard competition ("1224") ranking on
  ``points_above_replacement`` rounded to six decimal places; tied players
  share a rank.
- **A free agent player_value.py drops** (an unreachable case in practice,
  since every row this module hands it has non-missing
  ``season``/``sleeper_player_id``/``position``/``games_played``/
  ``points_per_game``/``total_points`` by construction -- rows with a
  ``NaN`` projection are filtered out of the value-metrics input entirely,
  see :func:`build_waiver_wire_rankings`): such a player is left with
  ``NaN`` in every VORP column and ``waiver_rank = NaN`` after the merge,
  which is exactly the "no projection possible" outcome, not an error.

Regular season vs. playoffs, restated for the ranking step
--------------------------------------------------------------------------

:func:`build_waiver_wire_rankings` inherits FFA-068's phase-agnostic
contract: it has no ``is_playoff`` concept of its own, and the only
playoff-boundary decision in this pipeline is ``season_end_week``'s effect
on ``remaining_games`` in step 1, described above.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from fantasy_analyzer.players.player_value import (
    build_player_value_metrics,
)
from fantasy_analyzer.players.ros_backtest import DEFAULT_SEASON_END_WEEK
from fantasy_analyzer.players.ros_projection import ShrinkageParameters, project_ppg

#: Season-to-date opportunity summary columns (FFA-098), appended to
#: :data:`FREE_AGENT_PROJECTION_COLUMNS`.
#:
#: Every one is a **per-game** figure over the player's observed weeks
#: (weeks ``1..cutoff_week`` in which he has a scored row), so they sit on
#: the same footing as ``ppg_to_date`` and are directly comparable between a
#: player with one game and a player with eight. The four share/ratio
#: columns are already per-game rates in the source, so their summary is the
#: mean across observed weeks; the volume and EPA columns are totals in the
#: source, so theirs is the total divided by ``games_to_date``.
#:
#: These columns are **descriptive, not inputs to the projection**.
#: ``projected_ppg`` is computed in points space exactly as before; these
#: sit beside it so a reader can see whether the points came from usage or
#: from a touchdown. See
#: :data:`~fantasy_analyzer.players.ros_backtest.CARRIED_OPPORTUNITY_COLUMNS`
#: for why that distinction decides waiver claims.
OPPORTUNITY_SUMMARY_COLUMNS = [
    "targets_per_game",
    "carries_per_game",
    "target_share",
    "air_yards_share",
    "wopr",
    "racr",
    "air_yards_per_game",
    "receiving_epa_per_game",
    "rushing_epa_per_game",
    "passing_epa_per_game",
]

#: Source column -> summary column for the opportunity figures that are
#: already per-game rates (mean across observed weeks).
_OPPORTUNITY_RATE_COLUMNS = {
    "target_share": "target_share",
    "air_yards_share": "air_yards_share",
    "wopr": "wopr",
    "racr": "racr",
}

#: Source column -> summary column for the opportunity figures that are
#: per-week totals (summed, then divided by ``games_to_date``).
_OPPORTUNITY_VOLUME_COLUMNS = {
    "targets": "targets_per_game",
    "carries": "carries_per_game",
    "receiving_air_yards": "air_yards_per_game",
    "receiving_epa": "receiving_epa_per_game",
    "rushing_epa": "rushing_epa_per_game",
    "passing_epa": "passing_epa_per_game",
}

#: Default minimum prior-season games required before a player's own
#: ``prior_season_ppg`` is trusted as his prior (FFA-096).
#:
#: Without this guard the shrinkage blend treats a one-game prior exactly
#: like a seventeen-game one. That is not a hypothetical: running the 2026
#: week-1 board, Phil Mafah carried a 9.90 ppg "prior" earned entirely in a
#: single week-18 2025 appearance, and with ``games_to_date = 0`` the blend
#: weight ``w`` is exactly zero -- so that one game *became* his whole
#: projection and floated him up the board above genuinely productive
#: players. Four games is the smallest sample at which a per-game rate is
#: worth more than the positional mean it falls back to.
#:
#: A player below the threshold is **not dropped**: his ``prior_season_ppg``
#: is still reported (so the board can show the thin sample), but the
#: *resolved* prior falls back to the positional mean, exactly as it does
#: for a player with no prior season at all.
DEFAULT_MIN_PRIOR_GAMES = 4

#: Column order for the DataFrame returned by
#: :func:`build_free_agent_ros_projections`.
FREE_AGENT_PROJECTION_COLUMNS = [
    "player_id",
    "full_name",
    "position",
    "team",
    "status",
    "gsis_id",
    "has_crosswalk",
    "games_to_date",
    "ppg_to_date",
    "last3_ppg",
    "prior_season_ppg",
    "prior_season_games",
    "prior_resolved_ppg",
    "blend_weight",
    "confidence_tier",
    "projected_ppg",
    "remaining_games",
    "projected_ros_points",
] + OPPORTUNITY_SUMMARY_COLUMNS

#: Column order for the DataFrame returned by :func:`build_waiver_wire_rankings`.
WAIVER_WIRE_RANKING_COLUMNS = FREE_AGENT_PROJECTION_COLUMNS + [
    "replacement_ppg",
    "ppg_above_replacement",
    "points_above_replacement",
    "waiver_rank",
    "player_owned_avg",
]

#: ``games_to_date`` at or below this is the ``"low"`` confidence tier. See
#: the module docstring's "Sample-size confidence tiers" section.
CONFIDENCE_TIER_LOW_MAX_GAMES = 2

#: ``games_to_date`` at or below this (and above
#: :data:`CONFIDENCE_TIER_LOW_MAX_GAMES`) is the ``"medium"`` tier; above it
#: is ``"high"``.
CONFIDENCE_TIER_MEDIUM_MAX_GAMES = 7

_FLOAT_PROJECTION_COLUMNS = [
    "games_to_date",
    "ppg_to_date",
    "last3_ppg",
    "prior_season_ppg",
    "prior_season_games",
    "prior_resolved_ppg",
    "blend_weight",
    "projected_ppg",
    "remaining_games",
    "projected_ros_points",
] + OPPORTUNITY_SUMMARY_COLUMNS

_FLOAT_RANKING_COLUMNS = _FLOAT_PROJECTION_COLUMNS + [
    "replacement_ppg",
    "ppg_above_replacement",
    "points_above_replacement",
    "player_owned_avg",
]


def confidence_tier(games_to_date: Optional[float]) -> Optional[str]:
    """Bucket ``games_to_date`` into ``"low"``/``"medium"``/``"high"``.

    See the module docstring's "Sample-size confidence tiers" section for
    the thresholds and their rationale.

    Args:
        games_to_date: Weeks played at or before the cutoff, or ``None``/
            ``NaN`` for a player with no observable games-to-date value
            (e.g. no crosswalk match at all).

    Returns:
        ``"low"`` (``<= 2`` games), ``"medium"`` (``3``-``7``), ``"high"``
        (``>= 8``), or ``None`` when ``games_to_date`` is undefined.
    """
    if games_to_date is None or pd.isna(games_to_date):
        return None
    if games_to_date <= CONFIDENCE_TIER_LOW_MAX_GAMES:
        return "low"
    if games_to_date <= CONFIDENCE_TIER_MEDIUM_MAX_GAMES:
        return "medium"
    return "high"


def _empty_projection_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype="float64" if column in _FLOAT_PROJECTION_COLUMNS else object
            )
            for column in FREE_AGENT_PROJECTION_COLUMNS
        }
    )


def _empty_ranking_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype="float64" if column in _FLOAT_RANKING_COLUMNS else object
            )
            for column in WAIVER_WIRE_RANKING_COLUMNS
        }
    )


def _to_date_summary(weeks: pd.DataFrame) -> pd.DataFrame:
    """Games/points to date per ``player_id`` (nflverse/``gsis_id`` keyed).

    Re-derived here rather than imported from
    ``ros_backtest._per_player_summary``: that helper is private, and this
    module's row universe (free agents, including zero-game ones) differs
    from that module's (players with a realized future outcome). See the
    module docstring's "What this module adds" section.
    """
    if weeks.empty:
        return pd.DataFrame(columns=["games_to_date", "points_to_date"])
    grouped = weeks.groupby("player_id", sort=False)["fantasy_points"]
    return pd.DataFrame(
        {"games_to_date": grouped.size(), "points_to_date": grouped.sum()}
    )


def _opportunity_summary(weeks: pd.DataFrame) -> pd.DataFrame:
    """Per-game opportunity figures per ``player_id`` (FFA-098).

    See :data:`OPPORTUNITY_SUMMARY_COLUMNS` for the per-column definitions
    and why rate columns are averaged while volume columns are divided by
    games played.

    A source column absent from ``weeks`` (an older cache, or a provider
    that does not carry it) yields an all-``NaN`` summary column rather
    than a missing one, so the output schema is stable regardless of what
    the provider supplied.

    Args:
        weeks: Scored player-weeks restricted to the observed window, as
            filtered inside :func:`build_free_agent_ros_projections`.

    Returns:
        A DataFrame indexed by ``player_id`` with
        :data:`OPPORTUNITY_SUMMARY_COLUMNS`. Empty (same columns, no rows)
        if ``weeks`` is empty.
    """
    if weeks.empty:
        return pd.DataFrame(
            {
                column: pd.Series(dtype="float64")
                for column in OPPORTUNITY_SUMMARY_COLUMNS
            }
        )

    grouped = weeks.groupby("player_id", sort=False)
    summary = pd.DataFrame(index=grouped.size().index)
    games = grouped.size()

    for source, target in _OPPORTUNITY_RATE_COLUMNS.items():
        if source in weeks.columns:
            # mean() skips NaN weeks, which is what we want: a week the
            # source could not compute a share for should not drag the
            # average toward zero.
            summary[target] = grouped[source].mean()
        else:
            summary[target] = float("nan")

    for source, target in _OPPORTUNITY_VOLUME_COLUMNS.items():
        if source in weeks.columns:
            # Divided by *games played*, not by the number of weeks with a
            # non-null value: a week a receiver played and drew zero
            # targets is a real zero and must pull the per-game rate down.
            summary[target] = grouped[source].sum(min_count=1) / games
        else:
            summary[target] = float("nan")

    summary.index.name = "player_id"
    return summary[OPPORTUNITY_SUMMARY_COLUMNS].astype("float64")


def _last3_ppg(weeks: pd.DataFrame) -> pd.Series:
    """Mean points over each player's last (at most) three weeks played."""
    if weeks.empty:
        return pd.Series(dtype="float64")
    ordered = weeks.sort_values(["player_id", "week"], kind="stable")
    tail = ordered.groupby("player_id", sort=False).tail(3)
    return tail.groupby("player_id", sort=False)["fantasy_points"].mean()


def build_free_agent_ros_projections(
    free_agent_pool: pd.DataFrame,
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    parameters: ShrinkageParameters,
    *,
    prior_season_weeks: Optional[pd.DataFrame] = None,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
    min_prior_games: int = DEFAULT_MIN_PRIOR_GAMES,
) -> pd.DataFrame:
    """Project rest-of-season points per game for every free agent.

    See the module docstring for the full methodology: the two-population
    split (players with >= 1 game to date vs. zero-game rookies vs. no
    crosswalk at all), the shrinkage blend
    (:func:`~fantasy_analyzer.players.ros_projection.project_ppg`), the
    schedule-only ``remaining_games`` definition, and the confidence-tier
    bucketing.

    Args:
        free_agent_pool:
            :data:`~fantasy_analyzer.players.free_agents.FREE_AGENT_POOL_COLUMNS`-shaped,
            as returned by
            :func:`~fantasy_analyzer.players.free_agents.build_free_agent_pool`.
        scored_weeks: League-scored player-weeks for ``season`` (and,
            ideally, ``season - 1`` if ``prior_season_weeks`` is not passed
            separately), as returned by
            :func:`~fantasy_analyzer.players.ros_backtest.build_scored_player_weeks`
            with ``player_id_column="player_id"`` (nflverse ``gsis_id``,
            the crosswalk's target side -- **not**
            ``"sleeper_player_id"``, since this module joins on
            ``gsis_id``).
        season: The season to project.
        cutoff_week: The last week whose results are knowable. Features are
            built from weeks ``1..cutoff_week``.
        parameters: Fitted shrinkage constants
            (:func:`~fantasy_analyzer.players.ros_projection.fit_shrinkage`).
        prior_season_weeks: Scored player-weeks for ``season - 1``, used
            only for ``prior_season_ppg``. Defaults to ``scored_weeks``
            itself (which may already span multiple seasons); pass an
            explicit frame to be precise about what "prior" means, or
            ``None``... note ``None`` here still falls back to
            ``scored_weeks`` -- pass an empty DataFrame to force every
            player's ``prior_season_ppg`` to be undefined.
        season_end_week: Last regular-season week counted toward
            ``remaining_games``. See the module docstring's "Regular
            season vs. playoffs" section.
        min_prior_games: Minimum prior-season games before a player's own
            ``prior_season_ppg`` is used as his prior. Below this, the
            prior falls back to the positional mean, as it does for a
            player with no prior season at all. Defaults to
            :data:`DEFAULT_MIN_PRIOR_GAMES`; pass ``0`` to disable the
            guard and trust every prior regardless of sample size.

    Returns:
        A DataFrame with :data:`FREE_AGENT_PROJECTION_COLUMNS`, one row per
        free agent in ``free_agent_pool``, in the same order. Empty (same
        columns) if ``free_agent_pool`` is empty.

    Raises:
        ValueError: If ``cutoff_week < 1`` or ``min_prior_games < 0``.
    """
    if cutoff_week < 1:
        raise ValueError(f"cutoff_week must be >= 1; got {cutoff_week}.")
    if min_prior_games < 0:
        raise ValueError(f"min_prior_games must be >= 0; got {min_prior_games}.")
    if free_agent_pool.empty:
        return _empty_projection_frame()

    if prior_season_weeks is None:
        prior_season_weeks = scored_weeks

    this_season = scored_weeks[scored_weeks["season"] == season]
    observed = this_season[
        (this_season["week"] >= 1) & (this_season["week"] <= cutoff_week)
    ]

    to_date = _to_date_summary(observed)
    last3 = _last3_ppg(observed)
    opportunity = _opportunity_summary(observed)

    prior_ppg = pd.Series(dtype="float64")
    prior_games = pd.Series(dtype="float64")
    if prior_season_weeks is not None and not prior_season_weeks.empty:
        prior = prior_season_weeks[prior_season_weeks["season"] == season - 1]
        if not prior.empty:
            prior_summary = _to_date_summary(prior)
            prior_games = prior_summary["games_to_date"].astype("float64")
            prior_ppg = prior_summary["points_to_date"] / prior_summary["games_to_date"]

    remaining_games = float(max(season_end_week - cutoff_week, 0))

    rows: list[dict] = []
    for pool_row in free_agent_pool.itertuples(index=False):
        gsis_id = pool_row.gsis_id
        has_crosswalk = bool(pool_row.has_crosswalk)

        row = {
            "player_id": pool_row.player_id,
            "full_name": pool_row.full_name,
            "position": pool_row.position,
            "team": pool_row.team,
            "status": pool_row.status,
            "gsis_id": gsis_id,
            "has_crosswalk": has_crosswalk,
            "games_to_date": None,
            "ppg_to_date": None,
            "last3_ppg": None,
            "prior_season_ppg": None,
            "prior_season_games": None,
            "prior_resolved_ppg": None,
            "blend_weight": None,
            "confidence_tier": None,
            "projected_ppg": None,
            "remaining_games": remaining_games,
            "projected_ros_points": None,
        }

        if not has_crosswalk:
            # No crosswalk at all -> genuinely no projection possible.
            rows.append(row)
            continue

        in_to_date = gsis_id in to_date.index
        games_to_date = (
            float(to_date.loc[gsis_id, "games_to_date"]) if in_to_date else 0.0
        )
        points_to_date = (
            float(to_date.loc[gsis_id, "points_to_date"]) if in_to_date else 0.0
        )
        row["games_to_date"] = games_to_date
        row["ppg_to_date"] = (
            points_to_date / games_to_date if games_to_date > 0 else None
        )
        row["last3_ppg"] = float(last3.loc[gsis_id]) if gsis_id in last3.index else None
        row["prior_season_ppg"] = (
            float(prior_ppg.loc[gsis_id])
            if not prior_ppg.empty and gsis_id in prior_ppg.index
            else None
        )
        row["prior_season_games"] = (
            float(prior_games.loc[gsis_id])
            if not prior_games.empty and gsis_id in prior_games.index
            else None
        )
        rows.append(row)

    frame = pd.DataFrame(rows, columns=FREE_AGENT_PROJECTION_COLUMNS)
    frame["games_to_date"] = pd.to_numeric(frame["games_to_date"], errors="coerce")
    frame["ppg_to_date"] = pd.to_numeric(frame["ppg_to_date"], errors="coerce")
    frame["prior_season_ppg"] = pd.to_numeric(
        frame["prior_season_ppg"], errors="coerce"
    )
    frame["prior_season_games"] = pd.to_numeric(
        frame["prior_season_games"], errors="coerce"
    )

    # FFA-096: a prior built on too few games is not a prior. It is still
    # *reported* (``prior_season_ppg`` keeps the raw value, and
    # ``prior_season_games`` shows how thin it is), but it does not feed
    # the blend -- ``trusted_prior`` is what both populations below resolve
    # against, so an under-sampled player falls back to the positional mean
    # exactly like a player with no prior season at all. See
    # :data:`DEFAULT_MIN_PRIOR_GAMES` for the failure this prevents.
    trusted_prior = frame["prior_season_ppg"].where(
        frame["prior_season_games"].fillna(0) >= min_prior_games
    )

    # Population A: has a crosswalk and >= 1 game to date. project_ppg is
    # called on exactly this sub-frame, unmodified -- see the module
    # docstring's implementation note on why a mixed population cannot be
    # fed to it directly.
    observed_mask = frame["has_crosswalk"] & (frame["games_to_date"].fillna(0) > 0)
    observed_frame = frame.loc[observed_mask].copy()

    positional_mean: dict[str, float] = {}
    if not observed_frame.empty:
        observed_frame["ppg_to_date"] = observed_frame["ppg_to_date"].astype(float)
        observed_frame["games_to_date"] = observed_frame["games_to_date"].astype(float)
        # project_ppg reads ``prior_season_ppg`` directly, so the guard is
        # applied by substituting the trusted series into the sub-frame it
        # sees -- ``frame``'s own reported column is left untouched.
        observed_frame["prior_season_ppg"] = trusted_prior.loc[
            observed_frame.index
        ].astype("float64")
        projected = project_ppg(observed_frame, parameters)
        frame.loc[observed_frame.index, "projected_ppg"] = projected.to_numpy()

        n0 = observed_frame["position"].map(parameters.n0_for).astype(float)
        weight = observed_frame["games_to_date"] / (
            observed_frame["games_to_date"] + n0
        )
        frame.loc[observed_frame.index, "blend_weight"] = weight.to_numpy()

        prior = observed_frame["prior_season_ppg"]
        resolved = prior.where(
            prior.notna(),
            observed_frame.groupby("position")["ppg_to_date"].transform("mean"),
        )
        frame.loc[observed_frame.index, "prior_resolved_ppg"] = resolved.to_numpy()

        positional_mean = (
            observed_frame.groupby("position")["ppg_to_date"].mean().to_dict()
        )

    # Population B: has a crosswalk but zero games to date (rookie /
    # inactive-to-date). w = 0 exactly, so projected_ppg = resolved prior.
    zero_games_mask = (
        frame["has_crosswalk"]
        & (frame["games_to_date"].fillna(0) == 0)
        & frame["games_to_date"].notna()
    )
    for index in frame.loc[zero_games_mask].index:
        position = frame.at[index, "position"]
        prior_season_ppg = trusted_prior.at[index]
        if prior_season_ppg is not None and not pd.isna(prior_season_ppg):
            resolved = float(prior_season_ppg)
        else:
            resolved = positional_mean.get(position)
        frame.at[index, "prior_resolved_ppg"] = resolved
        frame.at[index, "blend_weight"] = 0.0
        frame.at[index, "projected_ppg"] = resolved

    frame["projected_ros_points"] = frame["projected_ppg"] * frame["remaining_games"]
    # Built via an explicit list rather than Series.map: pandas can silently
    # coerce a returned ``None`` to ``NaN`` in an otherwise-string column
    # (dtype-dependent), and this label column must reliably carry ``None``
    # -- see the module docstring's dtype convention.
    frame["confidence_tier"] = pd.Series(
        [confidence_tier(value) for value in frame["games_to_date"].tolist()],
        dtype=object,
    )

    # FFA-098: attach the season-to-date usage picture. Joined on gsis_id
    # (the key ``observed`` is grouped by); a player with no crosswalk
    # match, or one who has not played, simply has no row in the summary
    # and gets NaN across the board -- the same "null, don't drop"
    # convention every other projection column here follows.
    for column in OPPORTUNITY_SUMMARY_COLUMNS:
        frame[column] = frame["gsis_id"].map(
            opportunity[column] if column in opportunity.columns else {}
        )

    for column in _FLOAT_PROJECTION_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")

    return frame[FREE_AGENT_PROJECTION_COLUMNS]


def build_waiver_wire_rankings(
    free_agent_pool: pd.DataFrame,
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    roster_positions: list[str],
    num_teams: Optional[int],
    parameters: ShrinkageParameters,
    *,
    prior_season_weeks: Optional[pd.DataFrame] = None,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
    min_prior_games: int = DEFAULT_MIN_PRIOR_GAMES,
    replacement_population: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Rank a league's free agents by rest-of-season points above replacement.

    Builds :func:`build_free_agent_ros_projections`, reshapes the projected
    ``(games_played, points_per_game, total_points)`` triple into a
    ``performance_df``-shaped frame, and feeds it unmodified to
    :func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`
    for the replacement-level / VORP computation. See the module docstring
    for why this ranks on VORP rather than raw ``projected_ppg``.

    Args:
        free_agent_pool: As for :func:`build_free_agent_ros_projections`.
        scored_weeks: As for :func:`build_free_agent_ros_projections`.
        season: The season to project and rank.
        cutoff_week: As for :func:`build_free_agent_ros_projections`.
        roster_positions: The league's ordered roster-slot list, passed
            through to FFA-068 for the starter-cutoff replacement baseline.
        num_teams: The league's team count, passed through to FFA-068.
        parameters: Fitted shrinkage constants.
        prior_season_weeks: As for :func:`build_free_agent_ros_projections`.
        season_end_week: As for :func:`build_free_agent_ros_projections`.
        min_prior_games: As for :func:`build_free_agent_ros_projections`.
        replacement_population: An optional second pool-shaped frame (same
            schema as ``free_agent_pool``) naming the players the
            replacement level should be measured over -- normally the
            whole league, rostered players included, as returned by
            :func:`~fantasy_analyzer.players.free_agents.build_free_agent_pool`
            with an empty ``raw_rosters``. Defaults to ``None``, which
            preserves the original behavior of measuring replacement level
            over ``free_agent_pool`` alone. **Supplying it is strongly
            recommended for a real waiver board** -- see the module
            docstring's "Whom the replacement level is measured over"
            section for the measured distortion it removes. Only
            ``free_agent_pool``'s players are ever returned.

    Returns:
        A DataFrame with :data:`WAIVER_WIRE_RANKING_COLUMNS`, one row per
        free agent, sorted by ascending ``waiver_rank`` (players with no
        projection -- no crosswalk match -- sort last, in
        ``free_agent_pool`` order). Empty (same columns) if
        ``free_agent_pool`` is empty.
    """
    if free_agent_pool.empty:
        return _empty_ranking_frame()

    free_agent_ids = free_agent_pool["player_id"]

    # The population the projection and the replacement level are computed
    # over. Adding the rostered league here changes three things at once,
    # all of them in the same direction: the starter cutoff finally lands
    # on the league's real last startable player at each position, the
    # positional-mean fallback prior for a zero-game player becomes the
    # league's mean rather than the wire's, and cross-position VORP
    # comparisons stop being an artifact of which position happens to have
    # the longer tail of unrostered junk.
    if replacement_population is None or replacement_population.empty:
        population = free_agent_pool
    else:
        population = pd.concat(
            [free_agent_pool, replacement_population], ignore_index=True
        ).drop_duplicates(subset="player_id", keep="first")

    projections = build_free_agent_ros_projections(
        population,
        scored_weeks,
        season,
        cutoff_week,
        parameters,
        prior_season_weeks=prior_season_weeks,
        season_end_week=season_end_week,
        min_prior_games=min_prior_games,
    )

    # Only players with a real projection can enter the VORP computation --
    # a NaN points_per_game/total_points row is dropped by player_value.py's
    # own "missing value -> skip" rule (see that module's docstring), which
    # is exactly the "null, not dropped from the final output" behavior
    # this ticket requires: such a player simply never gets a value_df row,
    # and the left-merge below leaves his VORP columns NaN.
    performance_df = pd.DataFrame(
        {
            "season": season,
            "sleeper_player_id": projections["player_id"],
            "player_name": projections["full_name"],
            "position": projections["position"],
            "nfl_team": projections["team"],
            "games_played": projections["remaining_games"],
            "points_per_game": projections["projected_ppg"],
            "total_points": projections["projected_ros_points"],
        }
    )
    valid = (
        performance_df["points_per_game"].notna()
        & performance_df["total_points"].notna()
    )
    value_df = build_player_value_metrics(
        performance_df.loc[valid], roster_positions, num_teams
    )

    if not value_df.empty:
        value_lookup = value_df.set_index("sleeper_player_id")[
            [
                "replacement_ppg",
                "ppg_above_replacement",
                "points_above_replacement",
                "value_rank",
            ]
        ]
    else:
        value_lookup = pd.DataFrame(
            columns=[
                "replacement_ppg",
                "ppg_above_replacement",
                "points_above_replacement",
                "value_rank",
            ]
        )

    result = projections.merge(
        value_lookup,
        left_on="player_id",
        right_index=True,
        how="left",
    )
    result = result.rename(columns={"value_rank": "waiver_rank"})

    # Drop the rostered players back out: they were only ever here to set
    # the replacement bar. Their VORP columns stay on the free agents who
    # remain, so ``ppg_above_replacement`` now means "above the league's
    # last startable player at this position", which is the number a
    # manager deciding on a claim actually needs.
    result = result[result["player_id"].isin(free_agent_ids)].reset_index(drop=True)

    # ``waiver_rank`` is a rank *among the claimable players*, so it is
    # re-derived over the filtered rows rather than inherited from
    # player_value.py's league-wide ``value_rank`` (which, with a
    # replacement_population supplied, would count rostered players and
    # leave gaps). The rule is copied exactly from
    # ``player_value._assign_value_ranks``: standard competition ("1224")
    # ranking on descending points_above_replacement, ties judged at six
    # decimal places so float noise cannot split an equal VORP. With no
    # replacement_population this reproduces the inherited rank exactly.
    result["waiver_rank"] = (
        result["points_above_replacement"]
        .round(6)
        .rank(method="min", ascending=False)
        .astype("float64")
    )

    if "player_owned_avg" in free_agent_pool.columns:
        result = result.merge(
            free_agent_pool[["player_id", "player_owned_avg"]],
            on="player_id",
            how="left",
        )
    else:
        result["player_owned_avg"] = pd.Series(dtype="float64")

    for column in _FLOAT_RANKING_COLUMNS:
        result[column] = result[column].astype("float64")

    result = result.sort_values(
        by=["waiver_rank"],
        key=lambda column: column.fillna(float("inf")),
        kind="stable",
    ).reset_index(drop=True)

    return result[WAIVER_WIRE_RANKING_COLUMNS]


def build_projection_performance_frame(
    waiver_rankings: pd.DataFrame, season: int
) -> pd.DataFrame:
    """Adapt :func:`build_waiver_wire_rankings` output for ``mode="projected"``.

    :func:`~fantasy_analyzer.players.player_rankings.build_league_player_rankings`'s
    ``projections_df`` parameter expects a ``performance_df``-shaped frame
    (``season``, ``sleeper_player_id``, ``position``, ``games_played``,
    ``points_per_game``, ``total_points``, plus the optional label columns
    ``player_name``/``nfl_team``). This is a thin, lossless rename/select
    over this module's own output so a caller does not have to remember the
    column mapping by hand.

    Args:
        waiver_rankings: As returned by :func:`build_waiver_wire_rankings`.
        season: The season label to stamp on every row (this module's
            output does not carry one -- it is a single-cutoff snapshot,
            not a season history).

    Returns:
        A DataFrame with the columns
        ``build_league_player_rankings(mode="projected")`` requires. Rows
        with no projection (``points_per_game`` is ``NaN``) are included,
        not dropped -- ``build_league_player_rankings`` handles a missing
        required value the same way FFA-068 does (the row contributes no
        value/VORP and is not itself an error). Empty if
        ``waiver_rankings`` is empty.
    """
    if waiver_rankings.empty:
        return pd.DataFrame(
            columns=[
                "season",
                "sleeper_player_id",
                "player_name",
                "position",
                "nfl_team",
                "games_played",
                "points_per_game",
                "total_points",
            ]
        )

    return pd.DataFrame(
        {
            "season": season,
            "sleeper_player_id": waiver_rankings["player_id"],
            "player_name": waiver_rankings["full_name"],
            "position": waiver_rankings["position"],
            "nfl_team": waiver_rankings["team"],
            "games_played": waiver_rankings["remaining_games"],
            "points_per_game": waiver_rankings["projected_ppg"],
            "total_points": waiver_rankings["projected_ros_points"],
        }
    )
