"""Tests for the LeagueAnalytics composition service (FFA-057).

``LeagueAnalytics`` is pure composition over FFA-050 through FFA-056's already
tested ``build_*`` functions -- it defines no new metrics of its own. These
tests therefore check that each method's output equals what calling the
underlying ``build_*`` function directly would produce (the composition is
wired to the right inputs/frames, per AGENTS.md's composition-only
requirement), plus the caching behavior (``weekly_scoring_ranks_df`` is shared,
not recomputed, by ``all_play()``/``consistency()``) and the documented edge
cases (empty input, no bracket data supplied).

Inputs are hand-built ``season_matchup_df``/``teams_df`` frames and small raw
playoff-bracket payload dicts -- no HTTP calls.
"""

import pandas as pd

from fantasy_analyzer.analytics import (
    LeagueAnalytics,
    build_all_play_standings,
    build_consistency_metrics,
    build_league_analytics,
    build_power_rankings,
    build_schedule_luck,
    build_strength_of_schedule,
    build_weekly_scoring_ranks,
)
from fantasy_analyzer.matchups.playoffs import (
    build_final_placements,
    build_playoff_brackets,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _game(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    week: int = 1,
    matchup_id: int | None = 1,
    is_playoff: bool = False,
    season: str = "2025",
) -> dict:
    """One ``SEASON_MATCHUP_COLUMNS`` row with outcome fields derived by hand.

    Mirrors :mod:`fantasy_analyzer.matchups.outcomes`'s rules: a matchup with
    a missing opponent or a missing score has no winner, no loser, no tie, and
    no margin. Pass ``roster_2_id=None`` for a bye.
    """
    winner: int | None = None
    loser: int | None = None
    is_tie = False
    margin: float | None = None
    point_differential: float | None = None

    if roster_2_id is not None and points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
        if points_1 > points_2:
            winner, loser = roster_1_id, roster_2_id
        elif points_1 < points_2:
            winner, loser = roster_2_id, roster_1_id
        else:
            is_tie = True

    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": None,
        "owner_2": None,
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
    """Three rosters, three weeks, one bye per week (odd-sized league).

    Week 1: roster 1 (120.0) beats roster 2 (100.0); roster 3 byes (90.0).
    Week 2: roster 2 (110.0) beats roster 3 (95.0); roster 1 byes (85.0).
    Week 3: roster 1 (115.0) beats roster 3 (105.0); roster 2 byes (80.0).

    Records: roster 1 = 2-0, roster 2 = 1-1, roster 3 = 0-2. Every roster has
    two decided games and one bye, so every FFA-052/FFA-054/FFA-056 builder
    produces a row for every roster.
    """
    return [
        _game(1, 2, 120.0, 100.0, week=1, matchup_id=1),
        _game(3, None, 90.0, None, week=1, matchup_id=None),
        _game(2, 3, 110.0, 95.0, week=2, matchup_id=1),
        _game(1, None, 85.0, None, week=2, matchup_id=None),
        _game(1, 3, 115.0, 105.0, week=3, matchup_id=1),
        _game(2, None, 80.0, None, week=3, matchup_id=None),
    ]


def _toy_teams_df() -> pd.DataFrame:
    return _teams_df([_team_row(1, "Alec"), _team_row(2, "Mike"), _team_row(3, "Joe")])


def _toy_analytics(**kwargs) -> LeagueAnalytics:
    return LeagueAnalytics(
        season_matchup_df=_season_matchup_df(_toy_rows()),
        teams_df=_toy_teams_df(),
        **kwargs,
    )


def _winners_bracket_raw() -> list[dict]:
    """One played, placement-awarding championship match: 1 beats 2, p=1."""
    return [{"r": 1, "m": 1, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1}]


def _losers_bracket_raw() -> list[dict]:
    """One played, placement-awarding third-place match: 3 beats... itself?

    Uses roster 3 as the lone participant of a (degenerate but valid) 3rd
    place match against a placeholder roster id 4, awarding places 3 and 4.
    """
    return [{"r": 1, "m": 1, "t1": 3, "t2": 4, "w": 3, "l": 4, "p": 3}]


# --- weekly_scoring_ranks_df caching -----------------------------------


def test_weekly_scoring_ranks_df_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_weekly_scoring_ranks(
        _season_matchup_df(_toy_rows()), _toy_teams_df()
    )
    pd.testing.assert_frame_equal(analytics.weekly_scoring_ranks_df, expected)


# --- all_play() ------------------------------------------------------------


def test_all_play_matches_build_all_play_standings_composition() -> None:
    """Hand-verifies the composition wiring per the ticket's requirement: the
    result must equal chaining build_weekly_scoring_ranks into
    build_all_play_standings on the same inputs, not some parallel path.
    """
    analytics = _toy_analytics()

    expected = build_all_play_standings(
        build_weekly_scoring_ranks(_season_matchup_df(_toy_rows()), _toy_teams_df())
    )
    pd.testing.assert_frame_equal(analytics.all_play(), expected)


def test_all_play_uses_cached_weekly_scoring_ranks_df() -> None:
    """The frame ``all_play()`` builds from is object-identical to the cached
    attribute, not a freshly rebuilt copy.
    """
    analytics = _toy_analytics()

    expected = build_all_play_standings(analytics.weekly_scoring_ranks_df)
    pd.testing.assert_frame_equal(analytics.all_play(), expected)


# --- schedule_luck() ---------------------------------------------------


def test_schedule_luck_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_schedule_luck(_season_matchup_df(_toy_rows()), _toy_teams_df())
    pd.testing.assert_frame_equal(analytics.schedule_luck(), expected)


# --- consistency() -------------------------------------------------------


def test_consistency_matches_build_consistency_metrics_default_threshold() -> None:
    analytics = _toy_analytics()

    expected = build_consistency_metrics(analytics.weekly_scoring_ranks_df)
    pd.testing.assert_frame_equal(analytics.consistency(), expected)


def test_consistency_passes_through_custom_threshold() -> None:
    analytics = _toy_analytics()

    expected = build_consistency_metrics(
        analytics.weekly_scoring_ranks_df, boom_bust_threshold=1.5
    )
    pd.testing.assert_frame_equal(
        analytics.consistency(boom_bust_threshold=1.5), expected
    )
    # Different threshold, different (or at least independently computed)
    # result object -- confirms the argument actually reaches the builder.
    default = analytics.consistency()
    custom = analytics.consistency(boom_bust_threshold=1.5)
    assert list(default.columns) == list(custom.columns)


# --- strength_of_schedule() ----------------------------------------------


def test_strength_of_schedule_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_strength_of_schedule(
        _season_matchup_df(_toy_rows()), _toy_teams_df()
    )
    pd.testing.assert_frame_equal(analytics.strength_of_schedule(), expected)


# --- power_rankings() ------------------------------------------------------


def test_power_rankings_matches_direct_call() -> None:
    analytics = _toy_analytics()

    expected = build_power_rankings(_season_matchup_df(_toy_rows()), _toy_teams_df())
    pd.testing.assert_frame_equal(analytics.power_rankings(), expected)


# --- playoff_brackets() / final_placements() --------------------------


def test_playoff_brackets_matches_direct_call() -> None:
    analytics = _toy_analytics(
        winners_bracket_raw=_winners_bracket_raw(),
        losers_bracket_raw=_losers_bracket_raw(),
    )

    expected = build_playoff_brackets(_winners_bracket_raw(), _losers_bracket_raw())
    pd.testing.assert_frame_equal(analytics.playoff_brackets(), expected)


def test_final_placements_matches_direct_call() -> None:
    analytics = _toy_analytics(
        winners_bracket_raw=_winners_bracket_raw(),
        losers_bracket_raw=_losers_bracket_raw(),
    )

    bracket_df = build_playoff_brackets(_winners_bracket_raw(), _losers_bracket_raw())
    expected = build_final_placements(bracket_df, _toy_teams_df())
    result = analytics.final_placements()

    pd.testing.assert_frame_equal(result, expected)
    assert set(result["placement"]) == {1, 2, 3, 4}


def test_final_placements_uses_own_playoff_brackets_not_independent_rebuild() -> None:
    """final_placements() must be built from this instance's own
    playoff_brackets() output, not a separately reconstructed bracket frame.
    """
    analytics = _toy_analytics(winners_bracket_raw=_winners_bracket_raw())

    expected = build_final_placements(analytics.playoff_brackets(), analytics.teams_df)
    pd.testing.assert_frame_equal(analytics.final_placements(), expected)


def test_no_bracket_data_supplied_gives_empty_playoff_frames() -> None:
    analytics = _toy_analytics()

    assert analytics.playoff_brackets().empty
    assert analytics.final_placements().empty


# --- empty season_matchup_df ---------------------------------------------


def test_empty_season_produces_empty_frames_everywhere() -> None:
    analytics = LeagueAnalytics(
        season_matchup_df=_season_matchup_df([]), teams_df=_teams_df([])
    )

    assert analytics.weekly_scoring_ranks_df.empty
    assert analytics.all_play().empty
    assert analytics.schedule_luck().empty
    assert analytics.consistency().empty
    assert analytics.strength_of_schedule().empty
    assert analytics.power_rankings().empty
    assert analytics.playoff_brackets().empty
    assert analytics.final_placements().empty


# --- build_league_analytics factory ---------------------------------------


def test_build_league_analytics_factory_matches_direct_construction() -> None:
    season_matchup_df = _season_matchup_df(_toy_rows())
    teams_df = _toy_teams_df()
    winners_raw = _winners_bracket_raw()

    via_factory = build_league_analytics(
        season_matchup_df, teams_df, winners_bracket_raw=winners_raw
    )
    via_constructor = LeagueAnalytics(
        season_matchup_df=season_matchup_df,
        teams_df=teams_df,
        winners_bracket_raw=winners_raw,
    )

    assert isinstance(via_factory, LeagueAnalytics)
    pd.testing.assert_frame_equal(
        via_factory.weekly_scoring_ranks_df, via_constructor.weekly_scoring_ranks_df
    )
    pd.testing.assert_frame_equal(via_factory.all_play(), via_constructor.all_play())
    pd.testing.assert_frame_equal(
        via_factory.playoff_brackets(), via_constructor.playoff_brackets()
    )


def test_build_league_analytics_factory_defaults_bracket_args_to_none() -> None:
    analytics = build_league_analytics(_season_matchup_df(_toy_rows()), _toy_teams_df())

    assert analytics.winners_bracket_raw is None
    assert analytics.losers_bracket_raw is None
    assert analytics.playoff_brackets().empty
