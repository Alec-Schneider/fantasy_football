"""Tests for the LeagueSummary composition service (FFA-023).

``LeagueSummary`` is pure composition over ``build_standings``,
``build_scoring_summary``, and ``derive_season_boundaries`` -- it defines no
new metrics of its own. These tests therefore check that its outputs equal
what calling those functions directly would produce, plus one small
hand-built toy example for the composed ``league_summary()`` view, per
AGENTS.md's analytics-ticket requirement for a hand-checkable example.
"""

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    LeagueSummary,
    LeagueSummaryView,
    build_league_summary,
    build_scoring_summary,
    build_standings,
)
from fantasy_analyzer.league import (
    SeasonBoundaries,
    build_league_snapshot,
    derive_season_boundaries,
)


def _fixture_snapshot(load_sleeper_fixture):
    raw_league = load_sleeper_fixture("league.json")
    raw_users = load_sleeper_fixture("users.json")
    raw_rosters = load_sleeper_fixture("rosters.json")
    player_catalog = load_sleeper_fixture("players.json")
    return build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)


def test_league_summary_standings_matches_build_standings(load_sleeper_fixture) -> None:
    snapshot = _fixture_snapshot(load_sleeper_fixture)
    summary = LeagueSummary(snapshot=snapshot, total_weeks=18)

    expected = build_standings(snapshot.rosters_df, snapshot.teams_df)
    pd.testing.assert_frame_equal(summary.standings(), expected)


def test_league_summary_scoring_summary_matches_build_scoring_summary(
    load_sleeper_fixture,
) -> None:
    snapshot = _fixture_snapshot(load_sleeper_fixture)
    summary = LeagueSummary(snapshot=snapshot, total_weeks=18)

    expected = build_scoring_summary(snapshot.rosters_df, snapshot.teams_df)
    pd.testing.assert_frame_equal(summary.scoring_summary(), expected)


def test_league_summary_season_boundaries_computed_at_construction(
    load_sleeper_fixture,
) -> None:
    """season_boundaries is computed once in __post_init__, not lazily.

    Fixture's playoff_week_start is 15 (cross-checked in test_season.py), so
    for an 18-week season weeks 1-14 are regular season and 15-18 are
    playoffs.
    """
    snapshot = _fixture_snapshot(load_sleeper_fixture)
    summary = LeagueSummary(snapshot=snapshot, total_weeks=18)

    expected = derive_season_boundaries(snapshot.league, total_weeks=18)
    assert summary.season_boundaries == expected
    assert isinstance(summary.season_boundaries, SeasonBoundaries)
    assert summary.season_boundaries.playoff_weeks == [15, 16, 17, 18]
    assert summary.season_boundaries.regular_season_weeks == list(range(1, 15))
    assert summary.season_boundaries.total_weeks == 18


def test_league_summary_view_composes_league_metadata_and_metrics(
    load_sleeper_fixture,
) -> None:
    snapshot = _fixture_snapshot(load_sleeper_fixture)
    summary = LeagueSummary(snapshot=snapshot, total_weeks=18)

    view = summary.league_summary()

    assert isinstance(view, LeagueSummaryView)
    assert view.league_id == snapshot.league.league_id
    assert view.name == snapshot.league.name
    assert view.season == snapshot.league.season
    assert view.status == snapshot.league.status
    pd.testing.assert_frame_equal(view.standings, summary.standings())
    pd.testing.assert_frame_equal(view.scoring_summary, summary.scoring_summary())
    assert view.season_boundaries == summary.season_boundaries


def test_build_league_summary_factory_matches_direct_construction(
    load_sleeper_fixture,
) -> None:
    snapshot = _fixture_snapshot(load_sleeper_fixture)

    via_factory = build_league_summary(snapshot, total_weeks=18)
    via_constructor = LeagueSummary(snapshot=snapshot, total_weeks=18)

    assert isinstance(via_factory, LeagueSummary)
    assert via_factory.total_weeks == via_constructor.total_weeks
    assert via_factory.season_boundaries == via_constructor.season_boundaries
    pd.testing.assert_frame_equal(via_factory.standings(), via_constructor.standings())


def test_league_summary_toy_example_hand_computed() -> None:
    """Two-team toy example, hand-computed end to end through league_summary().

    Team A (roster 1): 3-1-0 (4 games), fpts=440.0, fpts_against=400.0
        win_pct          = 3 / 4 = 0.75
        point_diff        = 40.0
        points_per_game   = 440.0 / 4 = 110.0
        avg_margin        = 40.0 / 4 = 10.0
    Team B (roster 2): 1-3-0 (4 games), fpts=400.0, fpts_against=440.0
        win_pct          = 1 / 4 = 0.25
        point_diff        = -40.0
        points_per_game   = 400.0 / 4 = 100.0
        avg_margin        = -40.0 / 4 = -10.0

    A has higher win_pct -> standings rank 1; A also has higher points_for
    -> scoring_rank 1.

    playoff_week_start=5, total_weeks=6 -> regular_season_weeks=[1,2,3,4],
    playoff_weeks=[5,6].
    """
    from fantasy_analyzer.league.settings import LeagueSettings
    from fantasy_analyzer.league.snapshot import LeagueSnapshot

    league_settings = LeagueSettings(
        league_id="toy-1",
        name="Toy League",
        season="2025",
        season_type="regular",
        status="in_season",
        total_rosters=2,
        playoff_week_start=5,
    )
    teams_df = pd.DataFrame(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "display_name": "Alice",
                "team_name": "Team Alice",
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "display_name": "Bob",
                "team_name": "Team Bob",
            },
        ]
    )
    rosters_df = pd.DataFrame(
        [
            {
                "roster_id": 1,
                "owner_id": "u1",
                "wins": 3,
                "losses": 1,
                "ties": 0,
                "fpts": 440.0,
                "fpts_against": 400.0,
                "players": [],
                "starters": [],
            },
            {
                "roster_id": 2,
                "owner_id": "u2",
                "wins": 1,
                "losses": 3,
                "ties": 0,
                "fpts": 400.0,
                "fpts_against": 440.0,
                "players": [],
                "starters": [],
            },
        ]
    )
    snapshot = LeagueSnapshot(
        league=league_settings,
        teams_df=teams_df,
        users_df=pd.DataFrame(),
        rosters_df=rosters_df,
        players_df=pd.DataFrame(),
        scoring_settings={},
        roster_positions=[],
    )

    summary = LeagueSummary(snapshot=snapshot, total_weeks=6)
    view = summary.league_summary()

    assert view.league_id == "toy-1"
    assert view.name == "Toy League"
    assert view.season == "2025"
    assert view.status == "in_season"

    row_a = view.standings.loc[view.standings["roster_id"] == 1].iloc[0]
    assert row_a["win_pct"] == pytest.approx(0.75)
    assert row_a["point_diff"] == pytest.approx(40.0)
    assert row_a["rank"] == 1

    row_b = view.standings.loc[view.standings["roster_id"] == 2].iloc[0]
    assert row_b["win_pct"] == pytest.approx(0.25)
    assert row_b["rank"] == 2

    scoring_a = view.scoring_summary.loc[view.scoring_summary["roster_id"] == 1].iloc[0]
    assert scoring_a["points_per_game"] == pytest.approx(110.0)
    assert scoring_a["avg_margin"] == pytest.approx(10.0)
    assert scoring_a["scoring_rank"] == 1

    scoring_b = view.scoring_summary.loc[view.scoring_summary["roster_id"] == 2].iloc[0]
    assert scoring_b["points_per_game"] == pytest.approx(100.0)
    assert scoring_b["avg_margin"] == pytest.approx(-10.0)
    assert scoring_b["scoring_rank"] == 2

    assert view.season_boundaries.regular_season_weeks == [1, 2, 3, 4]
    assert view.season_boundaries.playoff_weeks == [5, 6]
    assert view.season_boundaries.playoff_week_start == 5
    assert view.season_boundaries.total_weeks == 6


def test_league_summary_empty_snapshot_produces_empty_metrics_without_raising() -> None:
    """A sparse/empty LeagueSnapshot must not crash summary construction."""
    from fantasy_analyzer.league.settings import LeagueSettings
    from fantasy_analyzer.league.snapshot import LeagueSnapshot

    league_settings = LeagueSettings(
        league_id="empty-1",
        name=None,
        season=None,
        season_type=None,
        status=None,
        total_rosters=None,
    )
    snapshot = LeagueSnapshot(
        league=league_settings,
        teams_df=pd.DataFrame(
            columns=["roster_id", "owner_id", "display_name", "team_name"]
        ),
        users_df=pd.DataFrame(),
        rosters_df=pd.DataFrame(
            columns=[
                "roster_id",
                "owner_id",
                "wins",
                "losses",
                "ties",
                "fpts",
                "fpts_against",
                "players",
                "starters",
            ]
        ),
        players_df=pd.DataFrame(),
        scoring_settings={},
        roster_positions=[],
    )

    summary = LeagueSummary(snapshot=snapshot, total_weeks=18)

    assert summary.standings().empty
    assert summary.scoring_summary().empty
    # No playoff_week_start -> entire range treated as regular season.
    assert summary.season_boundaries.regular_season_weeks == list(range(1, 19))
    assert summary.season_boundaries.playoff_weeks == []

    view = summary.league_summary()
    assert view.league_id == "empty-1"
    assert view.standings.empty
    assert view.scoring_summary.empty
