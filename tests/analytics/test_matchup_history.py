"""Tests for the MatchupHistory composition service (FFA-043, FFA-044).

``MatchupHistory`` is pure composition over ``build_head_to_head_records``
(FFA-040), ``build_head_to_head_matrix``/``format_head_to_head_matrix``
(FFA-041), and ``build_rivalry_records`` (FFA-042) -- it defines no new
metrics of its own. These tests therefore check two things: that its outputs
equal what calling those functions directly would produce (the composition is
wired to the right inputs), and that one small hand-built toy season resolves
to the hand-computed combined record + rivalry numbers, per AGENTS.md's
requirement for a hand-checkable example.

FFA-044's phase split (``regular_season_head_to_head_df``,
``playoff_head_to_head_df``, ``head_to_head_by_phase``) is tested the same
way: its outputs must equal calling ``build_head_to_head_records`` directly
against an ``is_playoff``-filtered slice of ``season_matchup_df`` (proving
the "pre-filter, then call the unmodified builder" composition), and one
hand-built toy season with known regular-season-only, playoff-only, and
both-phase meetings resolves to hand-computed numbers per phase.

Inputs are hand-built ``season_matchup_df``/``teams_df`` frames -- no HTTP
calls -- using the same helpers as ``test_head_to_head.py`` /
``test_rivalries.py`` so all three suites build identical input shapes.
"""

import math

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    HeadToHeadByPhase,
    HeadToHeadCell,
    HeadToHeadHistory,
    HeadToHeadPhaseRecord,
    MatchupHistory,
    RivalryGame,
    build_head_to_head_matrix,
    build_head_to_head_records,
    build_matchup_history,
    build_rivalry_records,
    format_head_to_head_matrix,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _matchup_row(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    winner: int | None,
    loser: int | None,
    is_tie: bool = False,
    is_playoff: bool = False,
    week: int = 1,
    matchup_id: int | None = 1,
    season: str = "2025",
    owner_1: str | None = None,
    owner_2: str | None = None,
) -> dict:
    margin = None
    point_differential = None
    if points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": owner_1,
        "owner_2": owner_2,
        "points_1": points_1,
        "points_2": points_2,
        "winner": winner,
        "loser": loser,
        "is_tie": is_tie,
        "margin": margin,
        "point_differential": point_differential,
    }


def _season_matchup_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


def _teams_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["roster_id", "owner_id", "display_name", "team_name"]
    return pd.DataFrame(rows, columns=columns)


def _team_row(roster_id: int, name: str) -> dict:
    return {
        "roster_id": roster_id,
        "owner_id": f"u{roster_id}",
        "display_name": name,
        "team_name": name,
    }


def _toy_rows() -> list[dict]:
    """Three rosters, four weeks; rosters 1 and 2 meet three times.

    Week 1: roster 1 (120.0) beats roster 2 (100.0) -- margin 20.0,
        combined 220.0.
    Week 2: roster 1 (90.0) ties roster 3 (90.0) -- margin 0.0,
        combined 180.0.
    Week 3: roster 2 (80.0) beats roster 1 (70.0) -- margin 10.0,
        combined 150.0. (A rematch with roster 1 as ``roster_2_id``, so both
        pairing directions are exercised.)
    Week 4: roster 1 (130.0) beats roster 2 (95.5) -- margin 34.5,
        combined 225.5.

    Hand-computed history for roster 1 vs roster 2 (three meetings):
        meetings = 3, scored_meetings = 3, wins = 2, losses = 1, ties = 0
        total_points          = 120.0 + 70.0 + 130.0 = 320.0
        total_opponent_points = 100.0 + 80.0 + 95.5  = 275.5
        avg_points            = 320.0 / 3 = 106.666...
        avg_opponent_points   = 275.5 / 3 =  91.833...
        avg_margin            = (20.0 + 10.0 + 34.5) / 3 = 64.5 / 3 = 21.5
        closest_game            = week 3 (margin 10.0)
        largest_win  (roster 1) = week 4 (margin 34.5)
        largest_loss (roster 1) = week 3 (margin 10.0)
        highest_scoring_matchup = week 4 (combined 225.5)

    Hand-computed history for roster 1 vs roster 3 (one meeting, a tie):
        meetings = 1, wins = 0, losses = 0, ties = 1
        avg_points = avg_opponent_points = 90.0
        avg_margin = 0.0, largest_win = largest_loss = None

    Rosters 2 and 3 never meet.
    """
    return [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=3,
            points_1=90.0,
            points_2=90.0,
            winner=None,
            loser=None,
            is_tie=True,
            week=2,
            matchup_id=2,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=1,
            points_1=80.0,
            points_2=70.0,
            winner=2,
            loser=1,
            week=3,
            matchup_id=3,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=130.0,
            points_2=95.5,
            winner=1,
            loser=2,
            week=4,
            matchup_id=4,
        ),
    ]


def _toy_teams_df() -> pd.DataFrame:
    return _teams_df([_team_row(1, "Alec"), _team_row(2, "Mike"), _team_row(3, "Joe")])


def _toy_history() -> MatchupHistory:
    return MatchupHistory(
        season_matchup_df=_season_matchup_df(_toy_rows()), teams_df=_toy_teams_df()
    )


def test_head_to_head_df_matches_build_head_to_head_records() -> None:
    history = _toy_history()

    expected = build_head_to_head_records(
        _season_matchup_df(_toy_rows()), _toy_teams_df()
    )
    pd.testing.assert_frame_equal(history.head_to_head_df, expected)


def test_rivalry_df_matches_build_rivalry_records() -> None:
    history = _toy_history()

    expected = build_rivalry_records(_season_matchup_df(_toy_rows()), _toy_teams_df())
    pd.testing.assert_frame_equal(history.rivalry_df, expected)


def test_head_to_head_matrix_matches_direct_call() -> None:
    """The matrix must be built from this service's own head-to-head records,
    not re-derived by some parallel path.
    """
    history = _toy_history()

    expected = build_head_to_head_matrix(
        build_head_to_head_records(_season_matchup_df(_toy_rows()), _toy_teams_df())
    )
    pd.testing.assert_frame_equal(history.head_to_head_matrix(), expected)


def test_formatted_head_to_head_matrix_matches_direct_call() -> None:
    history = _toy_history()

    expected = format_head_to_head_matrix(
        build_head_to_head_records(_season_matchup_df(_toy_rows()), _toy_teams_df())
    )
    pd.testing.assert_frame_equal(history.formatted_head_to_head_matrix(), expected)


def test_head_to_head_toy_example_hand_computed() -> None:
    """Roster 1 vs roster 2 matches the hand computation in ``_toy_rows``,
    combining FFA-040's record with FFA-042's rivalry extrema.
    """
    history = _toy_history()

    result = history.head_to_head(1, 2)

    assert isinstance(result, HeadToHeadHistory)
    assert result.roster_id == 1
    assert result.opponent_roster_id == 2
    assert result.owner == "Alec"
    assert result.opponent_owner == "Mike"

    assert result.meetings == 3
    assert result.wins == 2
    assert result.losses == 1
    assert result.ties == 0
    assert result.total_points == pytest.approx(320.0)
    assert result.total_opponent_points == pytest.approx(275.5)
    assert result.avg_points == pytest.approx(320.0 / 3)
    assert result.avg_opponent_points == pytest.approx(275.5 / 3)

    assert result.scored_meetings == 3
    assert result.avg_margin == pytest.approx(21.5)
    assert isinstance(result.closest_game, RivalryGame)
    assert result.closest_game.week == 3
    assert result.closest_game.margin == pytest.approx(10.0)
    assert result.largest_win.week == 4
    assert result.largest_win.margin == pytest.approx(34.5)
    assert result.largest_loss.week == 3
    assert result.largest_loss.margin == pytest.approx(10.0)
    assert result.highest_scoring_matchup.week == 4
    assert result.highest_scoring_matchup.combined_points == pytest.approx(225.5)


def test_head_to_head_is_directional() -> None:
    """``head_to_head(2, 1)`` is roster 2's perspective, the mirror of
    ``head_to_head(1, 2)`` -- wins/losses swapped, points swapped, and the
    same (unsigned) avg_margin.
    """
    history = _toy_history()

    a_vs_b = history.head_to_head(1, 2)
    b_vs_a = history.head_to_head(2, 1)

    assert b_vs_a.roster_id == 2
    assert b_vs_a.opponent_roster_id == 1
    assert b_vs_a.owner == "Mike"
    assert b_vs_a.wins == a_vs_b.losses == 1
    assert b_vs_a.losses == a_vs_b.wins == 2
    assert b_vs_a.total_points == pytest.approx(a_vs_b.total_opponent_points)
    assert b_vs_a.avg_margin == pytest.approx(a_vs_b.avg_margin)
    # A's largest win is B's largest loss, and vice versa.
    assert b_vs_a.largest_loss.week == a_vs_b.largest_win.week == 4
    assert b_vs_a.largest_win.week == a_vs_b.largest_loss.week == 3


def test_head_to_head_values_are_plain_python_scalars() -> None:
    """Fields are cast off the source rows, so callers get ``int``/``float``
    rather than leaking numpy scalar types out of the DataFrames.
    """
    result = _toy_history().head_to_head(1, 2)

    assert type(result.meetings) is int
    assert type(result.wins) is int
    assert type(result.scored_meetings) is int
    assert type(result.total_points) is float
    assert type(result.avg_margin) is float


def test_head_to_head_tie_only_pair_has_no_largest_win_or_loss() -> None:
    """Rosters 1 and 3 met once, a tie: the record shows the tie and the
    rivalry has a closest game but neither a largest win nor a largest loss.
    """
    result = _toy_history().head_to_head(1, 3)

    assert result.meetings == 1
    assert result.wins == 0
    assert result.losses == 0
    assert result.ties == 1
    assert result.avg_points == pytest.approx(90.0)
    assert result.avg_opponent_points == pytest.approx(90.0)
    assert result.avg_margin == pytest.approx(0.0)
    assert result.closest_game.week == 2
    assert result.largest_win is None
    assert result.largest_loss is None
    assert result.highest_scoring_matchup.combined_points == pytest.approx(180.0)


def test_head_to_head_pair_that_never_met_returns_none() -> None:
    """Rosters 2 and 3 both played in the toy season but never each other --
    a normal outcome, returned as ``None`` rather than raised.
    """
    history = _toy_history()

    assert history.head_to_head(2, 3) is None
    assert history.head_to_head(3, 2) is None


def test_head_to_head_unknown_roster_returns_none() -> None:
    """A roster id that never appears in the season is simply never-met."""
    history = _toy_history()

    assert history.head_to_head(1, 99) is None
    assert history.head_to_head(99, 1) is None


def test_head_to_head_same_roster_returns_none() -> None:
    """No roster plays itself, so the self-pair is never-met, not an error."""
    assert _toy_history().head_to_head(1, 1) is None


def test_head_to_head_unmapped_owner_is_none_rather_than_raising() -> None:
    """Roster 2 has no row in teams_df -- the labels come back ``None``."""
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(_toy_rows()),
        teams_df=_teams_df([_team_row(1, "Alec")]),
    )

    result = history.head_to_head(1, 2)
    assert result.owner == "Alec"
    assert result.opponent_owner is None

    mirror = history.head_to_head(2, 1)
    assert mirror.owner is None
    assert mirror.opponent_owner == "Alec"


def test_head_to_head_missing_points_meeting_counted_but_not_scored() -> None:
    """A meeting with missing points counts toward ``meetings`` but not
    ``scored_meetings``, and is excluded from the margin statistics -- the
    combined result surfaces both numbers so the discrepancy is visible.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=None,
            points_2=None,
            winner=None,
            loser=None,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=2,
            matchup_id=2,
        ),
    ]
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(rows), teams_df=_teams_df([])
    )

    result = history.head_to_head(1, 2)
    assert result.meetings == 2
    assert result.wins == 1
    assert result.scored_meetings == 1
    # avg_points divides by meetings (FFA-040), avg_margin by scored
    # meetings (FFA-042) -- both definitions are carried through unchanged.
    assert result.avg_points == pytest.approx(60.0)
    assert result.avg_margin == pytest.approx(20.0)
    assert result.closest_game.week == 2


def test_head_to_head_all_meetings_missing_points_gives_nan_avg_margin() -> None:
    """The pair met, so a result exists, but no margin statistic is defined."""
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=None,
            points_2=None,
            winner=None,
            loser=None,
        )
    ]
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(rows), teams_df=_teams_df([])
    )

    result = history.head_to_head(1, 2)
    assert result.meetings == 1
    assert result.scored_meetings == 0
    assert math.isnan(result.avg_margin)
    assert result.closest_game is None
    assert result.largest_win is None
    assert result.largest_loss is None
    assert result.highest_scoring_matchup is None


def test_head_to_head_combines_regular_season_and_playoff_meetings() -> None:
    """FFA-043 applies no phase filter of its own (FFA-044's job), so a
    playoff meeting is part of the same combined record and is eligible to be
    a reported extremum -- flagged via ``is_playoff`` on the game.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=150.0,
            points_2=90.0,
            winner=1,
            loser=2,
            week=16,
            matchup_id=1,
            is_playoff=True,
        ),
    ]
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(rows), teams_df=_teams_df([])
    )

    result = history.head_to_head(1, 2)
    assert result.meetings == 2
    assert result.wins == 2
    assert result.avg_margin == pytest.approx(40.0)
    assert result.largest_win.week == 16
    assert result.largest_win.is_playoff is True


def test_head_to_head_matrix_toy_example_hand_computed() -> None:
    """Cells match the toy season: 1 beats 2 twice and loses once, 1 ties 3,
    and 2 vs 3 never met.
    """
    matrix = _toy_history().head_to_head_matrix()

    assert list(matrix.index) == [1, 2, 3]
    assert list(matrix.columns) == [1, 2, 3]
    assert matrix.loc[1, 1] is None

    cell_1v2 = matrix.loc[1, 2]
    assert isinstance(cell_1v2, HeadToHeadCell)
    assert (cell_1v2.meetings, cell_1v2.wins, cell_1v2.losses) == (3, 2, 1)

    cell_1v3 = matrix.loc[1, 3]
    assert (cell_1v3.wins, cell_1v3.losses, cell_1v3.ties) == (0, 0, 1)

    cell_2v3 = matrix.loc[2, 3]
    assert cell_2v3.meetings == 0


def test_formatted_head_to_head_matrix_uses_owner_labels() -> None:
    formatted = _toy_history().formatted_head_to_head_matrix()

    assert list(formatted.index) == ["Alec", "Mike", "Joe"]
    assert formatted.loc["Alec", "Mike"] == "2-1"
    assert formatted.loc["Mike", "Alec"] == "1-2"
    # A single tie renders as "W-L-T"; a pair that never met renders blank.
    assert formatted.loc["Alec", "Joe"] == "0-0-1"
    assert formatted.loc["Mike", "Joe"] == ""


def test_empty_season_produces_empty_frames_and_no_lookups() -> None:
    """An empty season must not crash construction; every derived view is
    empty and every lookup is a clean ``None``.
    """
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df([]), teams_df=_teams_df([])
    )

    assert history.head_to_head_df.empty
    assert history.rivalry_df.empty
    assert history.head_to_head_matrix().empty
    assert history.formatted_head_to_head_matrix().empty
    assert history.head_to_head(1, 2) is None


def test_all_bye_season_produces_empty_frames_and_no_lookups() -> None:
    """A non-empty season with no real meetings behaves like an empty one."""
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=None,
            points_1=55.5,
            points_2=None,
            winner=None,
            loser=None,
            matchup_id=None,
        )
    ]
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(rows), teams_df=_teams_df([])
    )

    assert history.head_to_head_df.empty
    assert history.rivalry_df.empty
    assert history.head_to_head_matrix().empty
    assert history.head_to_head(1, 2) is None


def test_single_roster_season_of_byes_has_no_history() -> None:
    """Degenerate one-roster league: the roster only ever has byes, so it
    never appears in the matrix and has no self-history.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=None,
            points_1=100.0,
            points_2=None,
            winner=None,
            loser=None,
            week=week,
            matchup_id=None,
        )
        for week in (1, 2)
    ]
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(rows),
        teams_df=_teams_df([_team_row(1, "Alec")]),
    )

    assert history.head_to_head_df.empty
    assert history.head_to_head(1, 1) is None
    assert history.head_to_head_matrix().empty


def test_build_matchup_history_factory_matches_direct_construction() -> None:
    season_matchup_df = _season_matchup_df(_toy_rows())
    teams_df = _toy_teams_df()

    via_factory = build_matchup_history(season_matchup_df, teams_df)
    via_constructor = MatchupHistory(
        season_matchup_df=season_matchup_df, teams_df=teams_df
    )

    assert isinstance(via_factory, MatchupHistory)
    pd.testing.assert_frame_equal(
        via_factory.head_to_head_df, via_constructor.head_to_head_df
    )
    pd.testing.assert_frame_equal(via_factory.rivalry_df, via_constructor.rivalry_df)
    assert via_factory.head_to_head(1, 2) == via_constructor.head_to_head(1, 2)


# ---------------------------------------------------------------------------
# FFA-044: regular season vs. playoff head-to-head split
# ---------------------------------------------------------------------------


def _phase_toy_rows() -> list[dict]:
    """Three rosters; a mix of regular-season-only, playoff-only, and
    both-phase pairings, plus a missing-points playoff meeting and a
    playoff bye row.

    Regular season (weeks 1-3):
        Week 1 (matchup 1): roster 1 (130.0) beats roster 2 (100.0).
        Week 2 (matchup 2): roster 1 (90.0) ties roster 2 (90.0).
        Week 3 (matchup 3): roster 1 (80.0) beats roster 3 (60.0).

    Playoffs (weeks 4-8):
        Week 4 (matchup 1): roster 2 (150.0) beats roster 1 (140.0) -- a
            rematch with roster 1 as ``roster_2_id``, exercising both
            pairing directions.
        Week 5 (matchup 2): roster 1 (120.0) beats roster 2 (110.0).
        Week 6 (matchup 3): roster 2 (200.0) beats roster 3 (190.0) -- 2 vs 3
            meet only here, only in the playoffs.
        Week 7 (matchup 4): roster 1 vs roster 2, both scores missing --
            still a meeting, contributes to neither wins/losses/ties nor
            points.
        Week 8 (matchup ``None``): roster 1 on a bye -- no opponent, must
            not create or contribute to any pair in either phase.

    Hand-computed roster 1 vs roster 2, regular season only (weeks 1-2):
        meetings=2, wins=1, losses=0, ties=1
        total_points = 130.0 + 90.0 = 220.0 -> avg_points = 110.0
        total_opponent_points = 100.0 + 90.0 = 190.0 -> avg_opponent_points = 95.0

    Hand-computed roster 1 vs roster 2, playoffs only (weeks 4, 5, 7):
        meetings=3 (the missing-points week 7 meeting still counts),
        wins=1 (week 5), losses=1 (week 4), ties=0
        total_points = 140.0 + 120.0 = 260.0 (week 7 contributes nothing)
        total_opponent_points = 150.0 + 110.0 = 260.0
        avg_points = avg_opponent_points = 260.0 / 3

    Hand-computed roster 1 vs roster 2, combined (unfiltered, for regression):
        meetings = 2 + 3 = 5, wins = 1 + 1 = 2, losses = 0 + 1 = 1,
        ties = 1 + 0 = 1
        total_points = 220.0 + 260.0 = 480.0
        total_opponent_points = 190.0 + 260.0 = 450.0

    Hand-computed roster 1 vs roster 3: regular season only, one meeting
    (week 3): meetings=1, wins=1, losses=0, ties=0,
    total_points=80.0, total_opponent_points=60.0. No playoff meeting.

    Hand-computed roster 2 vs roster 3: playoffs only, one meeting (week 6):
    meetings=1, wins=1, losses=0, ties=0,
    total_points=200.0, total_opponent_points=190.0. No regular-season
    meeting.
    """
    return [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=130.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=90.0,
            points_2=90.0,
            winner=None,
            loser=None,
            is_tie=True,
            week=2,
            matchup_id=2,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=3,
            points_1=80.0,
            points_2=60.0,
            winner=1,
            loser=3,
            week=3,
            matchup_id=3,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=1,
            points_1=150.0,
            points_2=140.0,
            winner=2,
            loser=1,
            week=4,
            matchup_id=1,
            is_playoff=True,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=110.0,
            winner=1,
            loser=2,
            week=5,
            matchup_id=2,
            is_playoff=True,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=3,
            points_1=200.0,
            points_2=190.0,
            winner=2,
            loser=3,
            week=6,
            matchup_id=3,
            is_playoff=True,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=None,
            points_2=None,
            winner=None,
            loser=None,
            week=7,
            matchup_id=4,
            is_playoff=True,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=None,
            points_1=100.0,
            points_2=None,
            winner=None,
            loser=None,
            week=8,
            matchup_id=None,
            is_playoff=True,
        ),
    ]


def _phase_toy_history() -> MatchupHistory:
    return MatchupHistory(
        season_matchup_df=_season_matchup_df(_phase_toy_rows()),
        teams_df=_toy_teams_df(),
    )


def test_regular_season_head_to_head_df_matches_filtered_direct_call() -> None:
    season_matchup_df = _season_matchup_df(_phase_toy_rows())
    teams_df = _toy_teams_df()
    history = MatchupHistory(season_matchup_df=season_matchup_df, teams_df=teams_df)

    expected = build_head_to_head_records(
        season_matchup_df[season_matchup_df["is_playoff"] == False],  # noqa: E712
        teams_df,
    )
    pd.testing.assert_frame_equal(history.regular_season_head_to_head_df, expected)


def test_playoff_head_to_head_df_matches_filtered_direct_call() -> None:
    season_matchup_df = _season_matchup_df(_phase_toy_rows())
    teams_df = _toy_teams_df()
    history = MatchupHistory(season_matchup_df=season_matchup_df, teams_df=teams_df)

    expected = build_head_to_head_records(
        season_matchup_df[season_matchup_df["is_playoff"] == True],  # noqa: E712
        teams_df,
    )
    pd.testing.assert_frame_equal(history.playoff_head_to_head_df, expected)


def test_head_to_head_by_phase_toy_example_hand_computed() -> None:
    """Roster 1 vs roster 2 met in both phases; both splits match the hand
    computation in ``_phase_toy_rows``.
    """
    history = _phase_toy_history()

    result = history.head_to_head_by_phase(1, 2)

    assert isinstance(result, HeadToHeadByPhase)
    assert result.roster_id == 1
    assert result.opponent_roster_id == 2

    regular_season = result.regular_season
    assert isinstance(regular_season, HeadToHeadPhaseRecord)
    assert regular_season.owner == "Alec"
    assert regular_season.opponent_owner == "Mike"
    assert regular_season.meetings == 2
    assert regular_season.wins == 1
    assert regular_season.losses == 0
    assert regular_season.ties == 1
    assert regular_season.total_points == pytest.approx(220.0)
    assert regular_season.total_opponent_points == pytest.approx(190.0)
    assert regular_season.avg_points == pytest.approx(110.0)
    assert regular_season.avg_opponent_points == pytest.approx(95.0)

    playoffs = result.playoffs
    assert isinstance(playoffs, HeadToHeadPhaseRecord)
    assert playoffs.meetings == 3
    assert playoffs.wins == 1
    assert playoffs.losses == 1
    assert playoffs.ties == 0
    assert playoffs.total_points == pytest.approx(260.0)
    assert playoffs.total_opponent_points == pytest.approx(260.0)
    assert playoffs.avg_points == pytest.approx(260.0 / 3)
    assert playoffs.avg_opponent_points == pytest.approx(260.0 / 3)


def test_head_to_head_by_phase_is_directional() -> None:
    """``head_to_head_by_phase(2, 1)`` mirrors ``(1, 2)`` -- wins/losses
    swapped, points swapped, per phase.
    """
    history = _phase_toy_history()

    a_vs_b = history.head_to_head_by_phase(1, 2)
    b_vs_a = history.head_to_head_by_phase(2, 1)

    assert b_vs_a.regular_season.wins == a_vs_b.regular_season.losses == 0
    assert b_vs_a.regular_season.losses == a_vs_b.regular_season.wins == 1
    assert b_vs_a.regular_season.ties == a_vs_b.regular_season.ties == 1
    assert b_vs_a.playoffs.wins == a_vs_b.playoffs.losses == 1
    assert b_vs_a.playoffs.losses == a_vs_b.playoffs.wins == 1
    assert b_vs_a.playoffs.total_points == pytest.approx(
        a_vs_b.playoffs.total_opponent_points
    )


def test_head_to_head_by_phase_regular_season_only_pair_has_no_playoffs() -> None:
    """Rosters 1 and 3 only ever met in the regular season (week 3): the
    ``playoffs`` field is ``None``, not a zero-meetings record.
    """
    history = _phase_toy_history()

    result = history.head_to_head_by_phase(1, 3)

    assert result.regular_season is not None
    assert result.regular_season.meetings == 1
    assert result.regular_season.wins == 1
    assert result.regular_season.total_points == pytest.approx(80.0)
    assert result.regular_season.total_opponent_points == pytest.approx(60.0)
    assert result.playoffs is None


def test_head_to_head_by_phase_playoff_only_pair_has_no_regular_season() -> None:
    """Rosters 2 and 3 only ever met in the playoffs (week 6): the
    ``regular_season`` field is ``None``, not a zero-meetings record.
    """
    history = _phase_toy_history()

    result = history.head_to_head_by_phase(2, 3)

    assert result.regular_season is None
    assert result.playoffs is not None
    assert result.playoffs.meetings == 1
    assert result.playoffs.wins == 1
    assert result.playoffs.total_points == pytest.approx(200.0)
    assert result.playoffs.total_opponent_points == pytest.approx(190.0)


def test_head_to_head_by_phase_missing_points_meeting_counted_but_not_scored() -> None:
    """The week 7 playoff meeting between rosters 1 and 2 has no points on
    either side: it counts toward ``meetings`` but contributes to none of
    ``wins``/``losses``/``ties`` and nothing to the point totals -- the same
    FFA-040 rule, applied within the playoff-only slice.
    """
    history = _phase_toy_history()

    playoffs = history.head_to_head_by_phase(1, 2).playoffs

    # meetings=3 (weeks 4, 5, 7) but only weeks 4 and 5 are decided.
    assert playoffs.meetings == 3
    assert playoffs.wins + playoffs.losses + playoffs.ties == 2
    # Only weeks 4 (140.0) and 5 (120.0) contribute points; week 7 adds 0.
    assert playoffs.total_points == pytest.approx(140.0 + 120.0)


def test_head_to_head_by_phase_bye_row_excluded_within_phase() -> None:
    """The week 8 playoff bye (roster 1, no opponent) must not create a pair
    or inflate any playoff meeting count. The playoff table has exactly the
    four directional rows implied by the three real playoff pairings (1v2,
    2v1, 2v3, 3v2) -- no bye-derived row, and 1 vs 3 has no playoff row at
    all since they never met in the playoffs.
    """
    history = _phase_toy_history()

    playoff_pairs = set(
        zip(
            history.playoff_head_to_head_df["roster_id"],
            history.playoff_head_to_head_df["opponent_roster_id"],
        )
    )
    assert playoff_pairs == {(1, 2), (2, 1), (2, 3), (3, 2)}


def test_head_to_head_by_phase_never_met_returns_none() -> None:
    """A roster id absent from the season is never-met in either phase."""
    history = _phase_toy_history()

    assert history.head_to_head_by_phase(1, 99) is None
    assert history.head_to_head_by_phase(99, 1) is None


def test_head_to_head_by_phase_same_roster_returns_none() -> None:
    assert _phase_toy_history().head_to_head_by_phase(1, 1) is None


def test_head_to_head_by_phase_unmapped_owner_is_none_rather_than_raising() -> None:
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(_phase_toy_rows()),
        teams_df=_teams_df([_team_row(1, "Alec")]),
    )

    result = history.head_to_head_by_phase(1, 2)
    assert result.regular_season.owner == "Alec"
    assert result.regular_season.opponent_owner is None
    assert result.playoffs.owner == "Alec"
    assert result.playoffs.opponent_owner is None


def test_head_to_head_by_phase_values_are_plain_python_scalars() -> None:
    result = _phase_toy_history().head_to_head_by_phase(1, 2)

    assert type(result.regular_season.meetings) is int
    assert type(result.regular_season.wins) is int
    assert type(result.regular_season.total_points) is float
    assert type(result.playoffs.avg_points) is float


def test_combined_head_to_head_unaffected_by_phase_split() -> None:
    """The pre-existing combined ``head_to_head``/``head_to_head_df`` must
    keep returning the exact same all-phases numbers after FFA-044's
    phase-split attributes were added -- 5 combined meetings, matching
    regular season (2) plus playoffs (3).
    """
    history = _phase_toy_history()

    combined = history.head_to_head(1, 2)
    assert combined.meetings == 5
    assert combined.wins == 2
    assert combined.losses == 1
    assert combined.ties == 1
    assert combined.total_points == pytest.approx(480.0)
    assert combined.total_opponent_points == pytest.approx(450.0)

    direct = build_head_to_head_records(
        _season_matchup_df(_phase_toy_rows()), _toy_teams_df()
    )
    pd.testing.assert_frame_equal(history.head_to_head_df, direct)


def test_empty_season_head_to_head_by_phase_frames_and_lookups() -> None:
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df([]), teams_df=_teams_df([])
    )

    assert history.regular_season_head_to_head_df.empty
    assert history.playoff_head_to_head_df.empty
    assert history.head_to_head_by_phase(1, 2) is None


def test_all_bye_season_head_to_head_by_phase_frames_and_lookups() -> None:
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=None,
            points_1=55.5,
            points_2=None,
            winner=None,
            loser=None,
            matchup_id=None,
            is_playoff=is_playoff,
            week=week,
        )
        for week, is_playoff in ((1, False), (2, True))
    ]
    history = MatchupHistory(
        season_matchup_df=_season_matchup_df(rows), teams_df=_teams_df([])
    )

    assert history.regular_season_head_to_head_df.empty
    assert history.playoff_head_to_head_df.empty
    assert history.head_to_head_by_phase(1, 2) is None
