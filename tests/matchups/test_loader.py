"""Tests for full-season Sleeper matchup loading.

The composition core (:func:`collect_season_matchups`) is tested purely,
with no HTTP involved. The thin fetching wrapper
(:func:`load_season_matchups`) is exercised via ``requests_mock`` against
sanitized fixture responses -- the live Sleeper API is never contacted.
"""

import requests_mock as requests_mock_lib

from fantasy_analyzer.league import LeagueSettings, derive_season_boundaries
from fantasy_analyzer.matchups import (
    WeekMatchups,
    collect_season_matchups,
    load_season_matchups,
)
from fantasy_analyzer.sleeper import SleeperClient


def _boundaries(playoff_week_start: int | None, total_weeks: int):
    settings = LeagueSettings(
        league_id="1",
        name="Test League",
        season="2025",
        season_type="regular",
        status="in_season",
        total_rosters=10,
        playoff_week_start=playoff_week_start,
    )
    return derive_season_boundaries(settings, total_weeks=total_weeks)


# -------------------------
# collect_season_matchups (pure core)
# -------------------------


def test_collect_tags_weeks_and_playoff_status() -> None:
    """Toy example checked by hand: 4 weeks, playoffs start week 3.

    Weeks 1-2 are regular season, weeks 3-4 are playoffs.
    """
    boundaries = _boundaries(playoff_week_start=3, total_weeks=4)
    raw = {
        1: [{"roster_id": 1, "matchup_id": 1, "points": 100.0}],
        2: [{"roster_id": 1, "matchup_id": 1, "points": 90.0}],
        3: [{"roster_id": 1, "matchup_id": 1, "points": 80.0}],
        4: [{"roster_id": 1, "matchup_id": 1, "points": 70.0}],
    }

    season = collect_season_matchups(raw, boundaries, season="2025")

    assert [w.week for w in season] == [1, 2, 3, 4]
    assert [w.is_playoff for w in season] == [False, False, True, True]
    assert all(w.season == "2025" for w in season)


def test_collect_retains_raw_matchup_entries(load_sleeper_fixture) -> None:
    boundaries = _boundaries(playoff_week_start=2, total_weeks=2)
    raw_matchups = load_sleeper_fixture("matchups.json")

    season = collect_season_matchups({1: raw_matchups, 2: []}, boundaries)

    assert season[0].matchups == raw_matchups


def test_collect_retains_missing_and_null_weeks_as_empty() -> None:
    """Weeks Sleeper has no data for stay present with empty matchups."""
    boundaries = _boundaries(playoff_week_start=3, total_weeks=3)

    season = collect_season_matchups({1: None}, boundaries)  # weeks 2-3 absent

    assert [w.week for w in season] == [1, 2, 3]
    assert [w.matchups for w in season] == [[], [], []]


def test_collect_without_playoff_config_marks_no_playoff_weeks() -> None:
    boundaries = _boundaries(playoff_week_start=None, total_weeks=3)

    season = collect_season_matchups({}, boundaries)

    assert [w.week for w in season] == [1, 2, 3]
    assert not any(w.is_playoff for w in season)


def test_collect_defaults_season_label_to_none() -> None:
    boundaries = _boundaries(playoff_week_start=2, total_weeks=2)

    season = collect_season_matchups({}, boundaries)

    assert all(w.season is None for w in season)


# -------------------------
# load_season_matchups (fetching wrapper)
# -------------------------


def test_load_season_matchups_fetches_every_relevant_week(
    load_sleeper_fixture,
) -> None:
    boundaries = _boundaries(playoff_week_start=3, total_weeks=4)
    raw_matchups = load_sleeper_fixture("matchups.json")
    client = SleeperClient()
    league_id = "9999"

    with requests_mock_lib.Mocker() as m:
        for week in (1, 2, 3, 4):
            m.get(
                f"{SleeperClient.BASE_URL}/league/{league_id}/matchups/{week}",
                json=raw_matchups if week == 1 else [],
            )

        season = load_season_matchups(client, league_id, boundaries, season="2025")

    assert m.call_count == 4
    assert [w.week for w in season] == [1, 2, 3, 4]
    assert [w.is_playoff for w in season] == [False, False, True, True]
    assert season[0] == WeekMatchups(
        season="2025", week=1, is_playoff=False, matchups=raw_matchups
    )
    assert season[3].matchups == []
