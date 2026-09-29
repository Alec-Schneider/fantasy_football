"""Assemble already-computed analytics into LLM-prompt-ready context bundles.

This module is pure aggregation and formatting: it computes **no** new
metrics of its own. Every number in :class:`MatchupContext` and
:class:`LeagueWeekContext` is either read verbatim off a DataFrame already
produced by ``analytics/`` or ``players/`` (season matchups, player
contributions, lineup efficiency, all-play standings, head-to-head records,
standings, power rankings, weekly scoring ranks, schedule luck), or is a
small, explicitly-documented derivation over those existing frames (e.g. a
head-to-head win/loss streak, computed by walking two rosters' own prior
``season_matchup_df`` rows -- see :func:`_compute_streak`). It performs no
network access and is fully testable against hand-built DataFrames, per
AGENTS.md's "analytics functions must be deterministic and testable without
live HTTP" rule.

Two builders, per FFA-090/FFA-091
----------------------------------

- :func:`build_matchup_context` -- one :class:`MatchupContext` per non-bye
  pairing in a given week: final score, margin, projected score (if the
  caller supplies one -- this repository has no wired projection vendor
  yet, see ``players/projections.py``), each side's top contributors
  (``players/matchup_contribution.py``), bench points left on the table
  (``players/lineup_efficiency.py``), that week's all-play record for each
  side (``analytics/all_play.py``), the two managers' head-to-head record
  entering the week (``analytics/head_to_head.py``), and a simple,
  documented head-to-head streak/revenge-game read.
- :func:`build_league_week_context` -- one :class:`LeagueWeekContext` per
  week: standings and their movement since last week
  (``analytics/standings.py``), power-ranking deltas
  (``analytics/power_rankings.py``), the week's scoring leaderboard
  (``analytics/weekly_scores.py``), and schedule-luck outliers
  (``analytics/schedule_luck.py``).

Both return plain, frozen, JSON-serializable dataclasses (nested dataclasses
and ``list``/``None`` only -- no DataFrames, no numpy scalars) so a caller
can inspect them directly, ``json.dumps(dataclasses.asdict(context))`` them,
or hand them to a future ``prompts.py`` (FFA-092, out of this ticket's
scope).

Milestones (clinched playoff spot / mathematically eliminated) are
deliberately **not** included in :class:`LeagueWeekContext`. This repo's
only playoff-boundary logic --
:func:`~fantasy_analyzer.matchups.playoffs.build_final_placements` -- only
resolves a placement once a playoff bracket match has actually been played
(see that function's "Undetermined placements" section); it cannot say
whether a team currently in Week 8 of the regular season has clinched or
been eliminated, because that requires simulating every remaining
combination of outcomes against the number of playoff spots, which no
module in this repository computes. Rather than invent that logic here,
this field is omitted; see this ticket's final report for the gap.

Bye weeks
---------

A bye row in ``season_matchup_df`` (``roster_2_id`` is ``None``, per
:mod:`~fantasy_analyzer.matchups.pairing`) is not a pairing between two
managers, so :func:`build_matchup_context` excludes it entirely -- the same
exclusion :mod:`~fantasy_analyzer.analytics.head_to_head` and
:mod:`~fantasy_analyzer.players.matchup_contribution` already document for
the same structural reason. A bye roster's score still counts toward that
week's league-wide scoring leaderboard in :func:`build_league_week_context`
(``build_weekly_scoring_ranks`` already includes it), but never toward
"biggest blowout" / "closest game", which require two sides.

First-ever meeting / missing history
-------------------------------------

If two rosters have no prior meeting before the given week (in whatever
``season_matchup_df`` slice the caller passes -- typically the current
season, but a multi-season frame works identically), :class:`HeadToHead`
reports ``meetings=0`` and all counts ``0``, ``last_meeting_*`` fields are
``None``, and :class:`Streak` reports ``holder_roster_id=None``,
``length=0``, ``snapped_this_week=False``, ``is_revenge_game=False`` --
there is no streak or revenge game to report without a prior meeting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from fantasy_analyzer.analytics.all_play import build_all_play_standings
from fantasy_analyzer.analytics.head_to_head import build_head_to_head_records
from fantasy_analyzer.analytics.league_analytics import LeagueAnalytics
from fantasy_analyzer.analytics.power_rankings import build_power_rankings
from fantasy_analyzer.analytics.schedule_luck import build_schedule_luck
from fantasy_analyzer.analytics.weekly_scores import build_weekly_scoring_ranks
from fantasy_analyzer.league.snapshot import LeagueSnapshot
from fantasy_analyzer.players.lineup_efficiency import build_lineup_efficiency_metrics
from fantasy_analyzer.players.matchup_contribution import (
    build_matchup_player_contributions,
)

#: Minimum number of consecutive same-outcome meetings (from the meeting
#: side's own perspective: all wins, or all losses) required for
#: :func:`_compute_streak` to report an active streak. A single win or loss
#: is just "the last result", not a streak worth calling out.
STREAK_MIN_LENGTH = 2

#: Default number of each side's highest-``fantasy_points`` starters
#: included as ``top_contributors`` in a :class:`TeamWeekSummary`.
DEFAULT_TOP_N_CONTRIBUTORS = 3


# ---------------------------------------------------------------------------
# Small conversion helpers -- keep every field a native Python type so the
# dataclasses below are trivially JSON-serializable, never a numpy scalar.
# ---------------------------------------------------------------------------


def _int_or_none(value: object) -> Optional[int]:
    return None if value is None or pd.isna(value) else int(value)


def _float_or_none(value: object) -> Optional[float]:
    return None if value is None or pd.isna(value) else float(value)


def _str_or_none(value: object) -> Optional[str]:
    return None if value is None or pd.isna(value) else str(value)


def _bool_or_default(value: object, default: bool = False) -> bool:
    return default if value is None or pd.isna(value) else bool(value)


def _owner_lookup(teams_df: pd.DataFrame) -> dict[int, Optional[str]]:
    """Map ``roster_id -> display_name``, or ``{}`` for an empty frame."""
    if teams_df.empty:
        return {}
    return {
        int(roster_id): (display_name if pd.notna(display_name) else None)
        for roster_id, display_name in zip(
            teams_df["roster_id"], teams_df["display_name"]
        )
    }


# ---------------------------------------------------------------------------
# FFA-090 -- weekly matchup context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerContribution:
    """One started player's contribution to their roster's score that week.

    Sourced verbatim from
    :func:`~fantasy_analyzer.players.matchup_contribution.build_matchup_player_contributions`.
    """

    sleeper_player_id: Optional[str]
    player_name: Optional[str]
    position: Optional[str]
    fantasy_points: float
    share_of_team_points: Optional[float]
    contribution_rank: int


@dataclass(frozen=True)
class BenchScorer:
    """The highest-scoring benched player on a roster that week.

    Selected as the ``bench == True`` row in ``player_week_df`` for that
    ``(season, week, roster_id)`` with the greatest ``fantasy_points``,
    ties broken by ascending ``player_name`` for determinism. ``None`` if
    the roster had no benched player with a recorded score that week (an
    empty bench, or no ``player_week_df`` rows for that roster-week).
    """

    sleeper_player_id: Optional[str]
    player_name: Optional[str]
    position: Optional[str]
    fantasy_points: float


@dataclass(frozen=True)
class AllPlayWeekRecord:
    """A roster's single-week all-play record (FFA-051, scoped to one week).

    Answers "was this a top-half score that ran into a buzzsaw, or a
    bottom-half win": how the roster's own score that week compared with
    every other roster's score that same week, independent of who it
    actually played. ``None`` if the roster has no scored row that week.
    """

    wins: Optional[int]
    losses: Optional[int]
    ties: Optional[int]
    win_pct: Optional[float]
    rank: Optional[int]


@dataclass(frozen=True)
class TeamWeekSummary:
    """One side of a matchup: its score and the context around it."""

    roster_id: int
    owner: Optional[str]
    points: Optional[float]
    projected_points: Optional[float]
    top_contributors: list[PlayerContribution] = field(default_factory=list)
    points_left_on_bench: Optional[float] = None
    top_bench_scorer: Optional[BenchScorer] = None
    all_play: Optional[AllPlayWeekRecord] = None


@dataclass(frozen=True)
class HeadToHead:
    """The two managers' head-to-head record entering this week's matchup.

    Built by calling
    :func:`~fantasy_analyzer.analytics.head_to_head.build_head_to_head_records`
    on the subset of ``season_matchup_df`` rows strictly *before* the given
    week -- i.e. this is history *entering* the matchup, not including it.
    ``roster_1_id``/``roster_2_id`` match the ``MatchupContext`` they are
    attached to; ``wins``/``losses``/``ties`` are from ``roster_1_id``'s
    perspective.
    """

    meetings: int
    roster_1_wins: int
    roster_1_losses: int
    ties: int
    last_meeting_season: Optional[str]
    last_meeting_week: Optional[int]
    last_meeting_winner_roster_id: Optional[int]


@dataclass(frozen=True)
class Streak:
    """A simple, documented head-to-head streak/revenge-game read.

    ``holder_roster_id``/``length`` describe the active streak *entering*
    this week: the longest run of consecutive same-outcome results (all
    wins, or all losses, from the streak holder's perspective) in the two
    rosters' most recent prior meetings, read backward from the meeting
    immediately before this week and stopping at the first tie or change of
    outcome. Reported only if that run is at least
    :data:`STREAK_MIN_LENGTH` long; otherwise ``holder_roster_id=None`` and
    ``length=0``.

    ``snapped_this_week`` is ``True`` iff there was an active streak
    entering the week (``length >= STREAK_MIN_LENGTH``) and this week's
    decided result did not extend it (the streak holder did not win this
    week, for a win streak, or did not lose, for a loss streak).

    ``is_revenge_game`` is ``True`` iff there was at least one prior
    meeting and this week's winner lost the single most recent prior
    meeting between these two rosters (i.e. this week's winner "avenged"
    that loss). Both flags are ``False`` when this week's matchup itself is
    undecided (missing points) or there is no prior meeting.
    """

    holder_roster_id: Optional[int]
    length: int
    snapped_this_week: bool
    is_revenge_game: bool


@dataclass(frozen=True)
class MatchupContext:
    """Everything :func:`build_matchup_context` assembles for one pairing."""

    season: Optional[str]
    week: int
    is_playoff: bool
    matchup_id: Optional[int]
    team_1: TeamWeekSummary
    team_2: TeamWeekSummary
    margin: Optional[float]
    winner_roster_id: Optional[int]
    loser_roster_id: Optional[int]
    is_tie: bool
    head_to_head: HeadToHead
    streak: Streak


def _weekly_contribution_rows(
    contributions_df: pd.DataFrame, week: int, roster_id: int
) -> pd.DataFrame:
    if contributions_df.empty:
        return contributions_df
    mask = (contributions_df["week"] == week) & (
        contributions_df["roster_id"] == roster_id
    )
    return contributions_df.loc[mask].sort_values("contribution_rank")


def _top_contributors(
    contributions_df: pd.DataFrame, week: int, roster_id: int, top_n: int
) -> list[PlayerContribution]:
    rows = _weekly_contribution_rows(contributions_df, week, roster_id)
    contributors: list[PlayerContribution] = []
    for row in rows.head(top_n).itertuples(index=False):
        contributors.append(
            PlayerContribution(
                sleeper_player_id=_str_or_none(row.sleeper_player_id),
                player_name=_str_or_none(row.player_name),
                position=_str_or_none(row.position),
                fantasy_points=float(row.fantasy_points),
                share_of_team_points=_float_or_none(row.share_of_team_points),
                contribution_rank=int(row.contribution_rank),
            )
        )
    return contributors


def _bench_points_left(
    lineup_efficiency_df: pd.DataFrame, week: int, roster_id: int
) -> Optional[float]:
    if lineup_efficiency_df.empty:
        return None
    mask = (lineup_efficiency_df["week"] == week) & (
        lineup_efficiency_df["roster_id"] == roster_id
    )
    rows = lineup_efficiency_df.loc[mask]
    if rows.empty:
        return None
    return _float_or_none(rows.iloc[0]["points_left_on_bench"])


def _top_bench_scorer(
    player_week_df: pd.DataFrame, week: int, roster_id: int
) -> Optional[BenchScorer]:
    if player_week_df.empty:
        return None
    mask = (
        (player_week_df["week"] == week)
        & (player_week_df["roster_id"] == roster_id)
        & (player_week_df["bench"] == True)  # noqa: E712
        & player_week_df["fantasy_points"].notna()
    )
    rows = player_week_df.loc[mask]
    if rows.empty:
        return None
    rows = rows.sort_values(
        by=["fantasy_points", "player_name"], ascending=[False, True]
    )
    top = rows.iloc[0]
    return BenchScorer(
        sleeper_player_id=_str_or_none(top["sleeper_player_id"]),
        player_name=_str_or_none(top["player_name"]),
        position=_str_or_none(top["position"]),
        fantasy_points=float(top["fantasy_points"]),
    )


def _all_play_week_record(
    all_play_week_df: pd.DataFrame, roster_id: int
) -> Optional[AllPlayWeekRecord]:
    if all_play_week_df.empty:
        return None
    rows = all_play_week_df.loc[all_play_week_df["roster_id"] == roster_id]
    if rows.empty:
        return None
    row = rows.iloc[0]
    return AllPlayWeekRecord(
        wins=_int_or_none(row["all_play_wins"]),
        losses=_int_or_none(row["all_play_losses"]),
        ties=_int_or_none(row["all_play_ties"]),
        win_pct=_float_or_none(row["all_play_win_pct"]),
        rank=_int_or_none(row["all_play_rank"]),
    )


def _team_week_summary(
    *,
    roster_id: int,
    points: object,
    owner_lookup: dict[int, Optional[str]],
    contributions_df: pd.DataFrame,
    lineup_efficiency_df: pd.DataFrame,
    player_week_df: pd.DataFrame,
    all_play_week_df: pd.DataFrame,
    week: int,
    top_n_contributors: int,
    projected_points: Optional[dict[int, float]],
) -> TeamWeekSummary:
    return TeamWeekSummary(
        roster_id=roster_id,
        owner=owner_lookup.get(roster_id),
        points=_float_or_none(points),
        projected_points=(_float_or_none((projected_points or {}).get(roster_id))),
        top_contributors=_top_contributors(
            contributions_df, week, roster_id, top_n_contributors
        ),
        points_left_on_bench=_bench_points_left(lineup_efficiency_df, week, roster_id),
        top_bench_scorer=_top_bench_scorer(player_week_df, week, roster_id),
        all_play=_all_play_week_record(all_play_week_df, roster_id),
    )


def _prior_meetings(
    season_matchup_df: pd.DataFrame, roster_1_id: int, roster_2_id: int, week: int
) -> pd.DataFrame:
    """Non-bye rows where these two rosters met, strictly before ``week``."""
    if season_matchup_df.empty:
        return season_matchup_df
    ids = {roster_1_id, roster_2_id}
    mask = (
        (season_matchup_df["week"] < week)
        & season_matchup_df["roster_2_id"].notna()
        & season_matchup_df.apply(
            lambda row: {row["roster_1_id"], row["roster_2_id"]} == ids, axis=1
        )
    )
    return season_matchup_df.loc[mask].sort_values("week")


def _head_to_head_snapshot(
    prior_df: pd.DataFrame, teams_df: pd.DataFrame, roster_1_id: int, roster_2_id: int
) -> HeadToHead:
    if prior_df.empty:
        return HeadToHead(
            meetings=0,
            roster_1_wins=0,
            roster_1_losses=0,
            ties=0,
            last_meeting_season=None,
            last_meeting_week=None,
            last_meeting_winner_roster_id=None,
        )

    records_df = build_head_to_head_records(prior_df, teams_df)
    row_matches = records_df.loc[
        (records_df["roster_id"] == roster_1_id)
        & (records_df["opponent_roster_id"] == roster_2_id)
    ]

    if row_matches.empty:
        meetings, wins, losses, ties = 0, 0, 0, 0
    else:
        row = row_matches.iloc[0]
        meetings = int(row["meetings"])
        wins = int(row["wins"])
        losses = int(row["losses"])
        ties = int(row["ties"])

    last_row = prior_df.iloc[-1]
    last_winner = _int_or_none(last_row["winner"])
    return HeadToHead(
        meetings=meetings,
        roster_1_wins=wins,
        roster_1_losses=losses,
        ties=ties,
        last_meeting_season=_str_or_none(last_row["season"]),
        last_meeting_week=_int_or_none(last_row["week"]),
        last_meeting_winner_roster_id=last_winner,
    )


def _compute_streak(
    prior_df: pd.DataFrame,
    roster_1_id: int,
    roster_2_id: int,
    this_week_winner_roster_id: Optional[int],
) -> Streak:
    """Derive the active streak entering the week, and revenge/snap flags.

    See :class:`Streak` for the exact definitions. ``prior_df`` must already
    be sorted ascending by ``week`` (as :func:`_prior_meetings` returns it).
    """
    if prior_df.empty:
        return Streak(
            holder_roster_id=None,
            length=0,
            snapped_this_week=False,
            is_revenge_game=False,
        )

    # Walk backward from the most recent prior meeting, from roster_1_id's
    # perspective: "win" if roster_1_id won that meeting, "loss" if
    # roster_1_id lost, "tie" (which breaks any streak) otherwise.
    outcomes: list[str] = []
    for row in prior_df.itertuples(index=False):
        winner = _int_or_none(row.winner)
        if winner == roster_1_id:
            outcomes.append("win")
        elif winner == roster_2_id:
            outcomes.append("loss")
        else:
            outcomes.append("tie")

    last_outcome = outcomes[-1]
    length = 0
    holder_roster_id: Optional[int] = None
    if last_outcome in ("win", "loss"):
        length = 1
        for outcome in reversed(outcomes[:-1]):
            if outcome == last_outcome:
                length += 1
            else:
                break
        if length >= STREAK_MIN_LENGTH:
            holder_roster_id = roster_1_id if last_outcome == "win" else roster_2_id
        else:
            length = 0

    snapped_this_week = False
    if (
        holder_roster_id is not None
        and this_week_winner_roster_id is not None
        and this_week_winner_roster_id != holder_roster_id
    ):
        snapped_this_week = True

    last_meeting_loser = (
        roster_2_id
        if outcomes[-1] == "win"
        else roster_1_id
        if outcomes[-1] == "loss"
        else None
    )
    is_revenge_game = (
        this_week_winner_roster_id is not None
        and last_meeting_loser is not None
        and this_week_winner_roster_id == last_meeting_loser
    )

    return Streak(
        holder_roster_id=holder_roster_id,
        length=length,
        snapped_this_week=snapped_this_week,
        is_revenge_game=is_revenge_game,
    )


def build_matchup_context(
    snapshot: LeagueSnapshot,
    season_matchup_df: pd.DataFrame,
    player_week_df: pd.DataFrame,
    week: int,
    *,
    top_n_contributors: int = DEFAULT_TOP_N_CONTRIBUTORS,
    projected_points: Optional[dict[int, float]] = None,
) -> list[MatchupContext]:
    """Build one :class:`MatchupContext` per non-bye pairing in ``week``.

    Pure aggregation over already-built inputs -- see the module docstring
    for exactly which existing ``analytics``/``players`` builder backs each
    field, and for the bye-week and first-meeting behavior.

    Args:
        snapshot: The league's normalized snapshot; only ``teams_df`` (for
            owner labels) is read.
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame
            (:func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`),
            covering at least every week up to and including ``week`` --
            head-to-head history and streak detection read the weeks
            strictly before ``week``, so a frame containing only ``week``
            itself yields ``meetings=0`` history for every pairing even if
            the two rosters have met before.
        player_week_df: A
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            DataFrame
            (:func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`)
            covering at least ``week``, with a ``fantasy_points`` column.
        week: The week to build matchup contexts for.
        top_n_contributors: How many of each side's highest-scoring
            starters to include as ``top_contributors``. Defaults to
            :data:`DEFAULT_TOP_N_CONTRIBUTORS`.
        projected_points: Optional ``{roster_id: projected_points}`` for
            this week, if the caller has one from a projection provider.
            This repository has no projection vendor wired in yet (see
            ``players/projections.py``), so this defaults to ``None`` and
            every ``projected_points`` field is then ``None``.

    Returns:
        One :class:`MatchupContext` per non-bye pairing in ``week``, sorted
        by ascending ``matchup_id`` then ``roster_1_id``. Empty if
        ``season_matchup_df`` is empty or has no non-bye row for ``week``.
    """
    if season_matchup_df.empty:
        return []

    week_rows = season_matchup_df.loc[
        (season_matchup_df["week"] == week) & season_matchup_df["roster_2_id"].notna()
    ].sort_values(by=["matchup_id", "roster_1_id"])
    if week_rows.empty:
        return []

    teams_df = snapshot.teams_df
    owner_lookup = _owner_lookup(teams_df)

    contributions_df = (
        build_matchup_player_contributions(season_matchup_df, player_week_df)
        if not player_week_df.empty
        else player_week_df
    )
    lineup_efficiency_df = (
        build_lineup_efficiency_metrics(player_week_df, snapshot.roster_positions)
        if not player_week_df.empty
        else player_week_df
    )

    this_week_df = season_matchup_df.loc[season_matchup_df["week"] == week]
    weekly_ranks_df = build_weekly_scoring_ranks(this_week_df, teams_df)
    all_play_week_df = build_all_play_standings(weekly_ranks_df)

    contexts: list[MatchupContext] = []
    for row in week_rows.itertuples(index=False):
        roster_1_id = int(row.roster_1_id)
        roster_2_id = int(row.roster_2_id)

        team_1 = _team_week_summary(
            roster_id=roster_1_id,
            points=row.points_1,
            owner_lookup=owner_lookup,
            contributions_df=contributions_df,
            lineup_efficiency_df=lineup_efficiency_df,
            player_week_df=player_week_df,
            all_play_week_df=all_play_week_df,
            week=week,
            top_n_contributors=top_n_contributors,
            projected_points=projected_points,
        )
        team_2 = _team_week_summary(
            roster_id=roster_2_id,
            points=row.points_2,
            owner_lookup=owner_lookup,
            contributions_df=contributions_df,
            lineup_efficiency_df=lineup_efficiency_df,
            player_week_df=player_week_df,
            all_play_week_df=all_play_week_df,
            week=week,
            top_n_contributors=top_n_contributors,
            projected_points=projected_points,
        )

        winner_roster_id = _int_or_none(row.winner)
        prior_df = _prior_meetings(season_matchup_df, roster_1_id, roster_2_id, week)
        head_to_head = _head_to_head_snapshot(
            prior_df, teams_df, roster_1_id, roster_2_id
        )
        streak = _compute_streak(prior_df, roster_1_id, roster_2_id, winner_roster_id)

        contexts.append(
            MatchupContext(
                season=_str_or_none(row.season),
                week=week,
                is_playoff=_bool_or_default(row.is_playoff),
                matchup_id=_int_or_none(row.matchup_id),
                team_1=team_1,
                team_2=team_2,
                margin=_float_or_none(row.margin),
                winner_roster_id=winner_roster_id,
                loser_roster_id=_int_or_none(row.loser),
                is_tie=_bool_or_default(row.is_tie),
                head_to_head=head_to_head,
                streak=streak,
            )
        )

    return contexts


# ---------------------------------------------------------------------------
# FFA-091 -- league-wide weekly recap context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StandingsMovement:
    """One roster's standings row, plus movement since ``previous_standings_df``.

    ``rank``/``wins``/``losses``/``ties``/``win_pct``/``points_for``/
    ``points_against``/``point_diff`` are read verbatim off ``standings_df``
    (:func:`~fantasy_analyzer.analytics.standings.build_standings`).
    ``previous_rank``/``rank_change`` are ``None`` unless the caller passed
    ``previous_standings_df``; when both ranks are known, ``rank_change =
    previous_rank - rank`` (positive means the roster moved *up* -- to a
    numerically lower, better rank).
    """

    roster_id: int
    owner: Optional[str]
    rank: int
    wins: float
    losses: float
    ties: float
    win_pct: float
    points_for: float
    points_against: float
    point_diff: float
    previous_rank: Optional[int]
    rank_change: Optional[int]


@dataclass(frozen=True)
class PowerRankingDelta:
    """One roster's power ranking as of ``week``, and its change from ``week - 1``.

    Both power-ranking snapshots are built by
    :func:`~fantasy_analyzer.analytics.power_rankings.build_power_rankings`
    over ``season_matchup_df`` filtered to ``week <= N`` -- see that
    function's own docstring for why filtering by week this way is the
    documented way to get an "as of week N" power ranking. ``previous_*``
    fields are ``None`` for ``week == 1`` (no prior week exists) or if the
    roster has no decided game through ``week - 1``.
    """

    roster_id: int
    owner: Optional[str]
    power_rank: int
    power_score: float
    previous_power_rank: Optional[int]
    power_score_delta: Optional[float]


@dataclass(frozen=True)
class ScoringLeaderboardEntry:
    """A single roster's score, for the weekly high/low leaderboard."""

    roster_id: int
    owner: Optional[str]
    points: float


@dataclass(frozen=True)
class MatchupExtreme:
    """One matchup, called out as the week's biggest blowout or closest game."""

    roster_1_id: int
    roster_2_id: int
    owner_1: Optional[str]
    owner_2: Optional[str]
    points_1: float
    points_2: float
    margin: float


@dataclass(frozen=True)
class WeeklyScoringLeaderboard:
    """The week's scoring extremes.

    ``highest_score``/``lowest_score`` come from
    :func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
    restricted to ``week`` (byes included, since a bye still has a real
    score). ``biggest_blowout``/``closest_game`` come from
    ``season_matchup_df``'s own ``margin`` column, restricted to ``week``'s
    non-bye rows -- ``None`` if the week has no decided non-bye matchup.
    Ties are broken by ascending ``roster_id`` (leaderboard) or ascending
    ``matchup_id`` (blowout/closest), matching this codebase's existing
    tie-break convention (e.g. ``weekly_scores.py``'s own ranking).
    """

    highest_score: Optional[ScoringLeaderboardEntry]
    lowest_score: Optional[ScoringLeaderboardEntry]
    biggest_blowout: Optional[MatchupExtreme]
    closest_game: Optional[MatchupExtreme]


@dataclass(frozen=True)
class ScheduleLuckOutlier:
    """One roster's schedule-luck reading, for the luckiest/unluckiest callout."""

    roster_id: int
    owner: Optional[str]
    schedule_luck: float
    win_pct: float
    all_play_win_pct: float


@dataclass(frozen=True)
class ScheduleLuckOutliers:
    """The luckiest and unluckiest rosters through ``week``.

    Built from
    :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
    over ``season_matchup_df`` filtered to ``week <= N`` (the same
    "as of week N" filtering convention as :class:`PowerRankingDelta`).
    ``None`` for either field if no roster has a decided game through
    ``week``.
    """

    luckiest: Optional[ScheduleLuckOutlier]
    unluckiest: Optional[ScheduleLuckOutlier]


@dataclass(frozen=True)
class LeagueWeekContext:
    """Everything :func:`build_league_week_context` assembles for one week."""

    season: Optional[str]
    week: int
    standings: list[StandingsMovement] = field(default_factory=list)
    power_ranking_deltas: list[PowerRankingDelta] = field(default_factory=list)
    weekly_leaderboard: Optional[WeeklyScoringLeaderboard] = None
    schedule_luck_outliers: Optional[ScheduleLuckOutliers] = None


def _standings_movement(
    standings_df: pd.DataFrame, previous_standings_df: Optional[pd.DataFrame]
) -> list[StandingsMovement]:
    if standings_df.empty:
        return []

    previous_rank_by_roster: dict[int, int] = {}
    if previous_standings_df is not None and not previous_standings_df.empty:
        previous_rank_by_roster = {
            int(roster_id): int(rank)
            for roster_id, rank in zip(
                previous_standings_df["roster_id"], previous_standings_df["rank"]
            )
        }

    movements: list[StandingsMovement] = []
    for row in standings_df.sort_values(by=["rank", "roster_id"]).itertuples(
        index=False
    ):
        roster_id = int(row.roster_id)
        rank = int(row.rank)
        previous_rank = previous_rank_by_roster.get(roster_id)
        rank_change = previous_rank - rank if previous_rank is not None else None
        movements.append(
            StandingsMovement(
                roster_id=roster_id,
                owner=_str_or_none(row.display_name),
                rank=rank,
                wins=float(row.wins),
                losses=float(row.losses),
                ties=float(row.ties),
                win_pct=float(row.win_pct),
                points_for=float(row.points_for),
                points_against=float(row.points_against),
                point_diff=float(row.point_diff),
                previous_rank=previous_rank,
                rank_change=rank_change,
            )
        )
    return movements


def _power_ranking_deltas(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame, week: int
) -> list[PowerRankingDelta]:
    through_week_df = season_matchup_df.loc[season_matchup_df["week"] <= week]
    if through_week_df.empty:
        return []
    current_df = build_power_rankings(through_week_df, teams_df)
    if current_df.empty:
        return []

    previous_by_roster: dict[int, tuple[int, float]] = {}
    if week > 1:
        prior_df = season_matchup_df.loc[season_matchup_df["week"] <= week - 1]
        if not prior_df.empty:
            previous_rankings_df = build_power_rankings(prior_df, teams_df)
            previous_by_roster = {
                int(row.roster_id): (int(row.power_rank), float(row.power_score))
                for row in previous_rankings_df.itertuples(index=False)
            }

    deltas: list[PowerRankingDelta] = []
    for row in current_df.sort_values(by=["power_rank", "roster_id"]).itertuples(
        index=False
    ):
        roster_id = int(row.roster_id)
        previous = previous_by_roster.get(roster_id)
        deltas.append(
            PowerRankingDelta(
                roster_id=roster_id,
                owner=_str_or_none(row.owner),
                power_rank=int(row.power_rank),
                power_score=float(row.power_score),
                previous_power_rank=previous[0] if previous else None,
                power_score_delta=(
                    float(row.power_score) - previous[1] if previous else None
                ),
            )
        )
    return deltas


def _weekly_leaderboard(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame, week: int
) -> WeeklyScoringLeaderboard:
    this_week_df = season_matchup_df.loc[season_matchup_df["week"] == week]
    weekly_ranks_df = build_weekly_scoring_ranks(this_week_df, teams_df)

    highest_score: Optional[ScoringLeaderboardEntry] = None
    lowest_score: Optional[ScoringLeaderboardEntry] = None
    if not weekly_ranks_df.empty:
        ordered = weekly_ranks_df.sort_values(
            by=["points", "roster_id"], ascending=[False, True]
        )
        top = ordered.iloc[0]
        bottom = ordered.iloc[-1]
        highest_score = ScoringLeaderboardEntry(
            roster_id=int(top["roster_id"]),
            owner=_str_or_none(top["owner"]),
            points=float(top["points"]),
        )
        lowest_score = ScoringLeaderboardEntry(
            roster_id=int(bottom["roster_id"]),
            owner=_str_or_none(bottom["owner"]),
            points=float(bottom["points"]),
        )

    non_bye_df = this_week_df.loc[
        this_week_df["roster_2_id"].notna() & this_week_df["margin"].notna()
    ]
    owner_lookup = _owner_lookup(teams_df)

    biggest_blowout: Optional[MatchupExtreme] = None
    closest_game: Optional[MatchupExtreme] = None
    if not non_bye_df.empty:
        ordered = non_bye_df.sort_values(
            by=["margin", "matchup_id"], ascending=[False, True]
        )
        blowout_row = ordered.iloc[0]
        closest_row = ordered.iloc[-1]
        biggest_blowout = _matchup_extreme(blowout_row, owner_lookup)
        closest_game = _matchup_extreme(closest_row, owner_lookup)

    return WeeklyScoringLeaderboard(
        highest_score=highest_score,
        lowest_score=lowest_score,
        biggest_blowout=biggest_blowout,
        closest_game=closest_game,
    )


def _matchup_extreme(
    row: "pd.Series", owner_lookup: dict[int, Optional[str]]
) -> MatchupExtreme:
    roster_1_id = int(row["roster_1_id"])
    roster_2_id = int(row["roster_2_id"])
    return MatchupExtreme(
        roster_1_id=roster_1_id,
        roster_2_id=roster_2_id,
        owner_1=owner_lookup.get(roster_1_id),
        owner_2=owner_lookup.get(roster_2_id),
        points_1=float(row["points_1"]),
        points_2=float(row["points_2"]),
        margin=float(row["margin"]),
    )


def _schedule_luck_outliers(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame, week: int
) -> ScheduleLuckOutliers:
    through_week_df = season_matchup_df.loc[season_matchup_df["week"] <= week]
    if through_week_df.empty:
        return ScheduleLuckOutliers(luckiest=None, unluckiest=None)

    luck_df = build_schedule_luck(through_week_df, teams_df)
    if luck_df.empty:
        return ScheduleLuckOutliers(luckiest=None, unluckiest=None)

    ordered = luck_df.sort_values(
        by=["schedule_luck", "roster_id"], ascending=[False, True]
    )
    luckiest_row = ordered.iloc[0]
    unluckiest_row = ordered.iloc[-1]
    return ScheduleLuckOutliers(
        luckiest=_schedule_luck_outlier(luckiest_row),
        unluckiest=_schedule_luck_outlier(unluckiest_row),
    )


def _schedule_luck_outlier(row: "pd.Series") -> ScheduleLuckOutlier:
    return ScheduleLuckOutlier(
        roster_id=int(row["roster_id"]),
        owner=_str_or_none(row["owner"]),
        schedule_luck=float(row["schedule_luck"]),
        win_pct=float(row["win_pct"]),
        all_play_win_pct=float(row["all_play_win_pct"]),
    )


def build_league_week_context(
    snapshot: LeagueSnapshot,
    analytics: LeagueAnalytics,
    standings_df: pd.DataFrame,
    week: int,
    *,
    previous_standings_df: Optional[pd.DataFrame] = None,
) -> LeagueWeekContext:
    """Build the league-wide weekly recap context for ``week``.

    Pure aggregation over already-built inputs -- see the module docstring
    for exactly which existing ``analytics`` builder backs each field, why
    milestones are omitted, and the bye-week leaderboard behavior.

    Args:
        snapshot: The league's normalized snapshot; not read directly by
            this function (kept in the signature for symmetry with
            :func:`build_matchup_context` and for forward-compatibility with
            fields a future ticket might add), but ``analytics.teams_df``
            is what actually resolves owner labels here.
        analytics: A
            :class:`~fantasy_analyzer.analytics.league_analytics.LeagueAnalytics`
            built over the season's ``season_matchup_df``/``teams_df``.
            ``analytics.season_matchup_df`` should cover at least every week
            up to and including ``week`` -- power-ranking deltas and
            schedule-luck outliers are computed by filtering it to ``week
            <= N``, so a frame that stops before ``week`` under-counts both.
        standings_df: A ``STANDINGS_COLUMNS``-shaped DataFrame describing
            the standings *after* ``week``. Two builders produce that shape.
            :func:`~fantasy_analyzer.analytics.standings.build_standings_through_week`
            (FFA-102) derives it from the week-level matchup frame and so
            can reconstruct any past week, which is what backfilling a
            recap needs.
            :func:`~fantasy_analyzer.analytics.standings.build_standings`
            reads Sleeper's live, season-cumulative roster counters and has
            no per-week filter of its own, so it is only correct here when
            called promptly after ``week`` finalizes -- passing it while
            building a recap for an earlier week silently describes today.
        week: The week to build the recap context for.
        previous_standings_df: The same shape captured after the *previous*
            week, used only to compute ``rank_change``. Pass
            ``build_standings_through_week(..., week - 1)`` to derive it
            directly; with ``build_standings`` the only source is a cached
            copy from last week's run, since last week's table cannot be
            recovered from this week's cumulative snapshot.
            ``None`` (the default) leaves every ``previous_rank``/
            ``rank_change`` field ``None``. Prefer ``None`` for week 1:
            before any game every team is 0-0 and tied at rank 1, so a
            derived "previous" table reports every manager but one falling
            up to eleven places.

    Returns:
        A :class:`LeagueWeekContext` for ``week``.
    """
    season_matchup_df = analytics.season_matchup_df
    teams_df = analytics.teams_df

    season = (
        _str_or_none(season_matchup_df["season"].dropna().iloc[0])
        if not season_matchup_df.empty and season_matchup_df["season"].notna().any()
        else None
    )

    return LeagueWeekContext(
        season=season,
        week=week,
        standings=_standings_movement(standings_df, previous_standings_df),
        power_ranking_deltas=_power_ranking_deltas(season_matchup_df, teams_df, week),
        weekly_leaderboard=_weekly_leaderboard(season_matchup_df, teams_df, week),
        schedule_luck_outliers=_schedule_luck_outliers(
            season_matchup_df, teams_df, week
        ),
    )
