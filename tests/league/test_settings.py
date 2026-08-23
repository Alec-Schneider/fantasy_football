"""Tests for league settings normalization.

These tests operate on already-fetched raw Sleeper league dicts -- no HTTP
calls are made or mocked here, per AGENTS.md's separation of data access
from normalization.
"""

from fantasy_analyzer.league import LeagueSettings, normalize_league_settings


def test_normalize_league_settings_from_fixture(load_sleeper_fixture) -> None:
    raw_league = load_sleeper_fixture("league.json")

    settings = normalize_league_settings(raw_league)

    assert isinstance(settings, LeagueSettings)
    assert settings.league_id == "111111111111111111"
    assert settings.name == "Test League"
    assert settings.season == "2025"
    assert settings.season_type == "regular"
    assert settings.status == "in_season"
    assert settings.total_rosters == 10
    assert settings.draft_id == "999999999999999999"
    assert settings.previous_league_id == "888888888888888888"


def test_normalize_league_settings_scoring_settings(load_sleeper_fixture) -> None:
    raw_league = load_sleeper_fixture("league.json")

    settings = normalize_league_settings(raw_league)

    assert settings.scoring_settings["pass_td"] == 4
    assert settings.scoring_settings["rec"] == 0.5
    assert settings.scoring_settings["rush_td"] == 6
    assert settings.scoring_settings["fum_lost"] == -2


def test_normalize_league_settings_roster_positions(load_sleeper_fixture) -> None:
    raw_league = load_sleeper_fixture("league.json")

    settings = normalize_league_settings(raw_league)

    assert settings.roster_positions.count("QB") == 1
    assert settings.roster_positions.count("BN") == 6
    assert "FLEX" in settings.roster_positions


def test_normalize_league_settings_playoff_and_waiver_fields(
    load_sleeper_fixture,
) -> None:
    raw_league = load_sleeper_fixture("league.json")

    settings = normalize_league_settings(raw_league)

    assert settings.playoff_week_start == 15
    assert settings.playoff_teams == 6
    assert settings.waiver_type == 2
    assert settings.waiver_budget == 100
    assert settings.trade_deadline == 12


def test_normalize_league_settings_missing_settings_block_uses_defaults() -> None:
    """A league response with no ``settings`` block must not crash."""
    raw_league = {
        "league_id": "1",
        "name": "No Settings League",
        "season": "2025",
    }

    settings = normalize_league_settings(raw_league)

    assert settings.league_id == "1"
    assert settings.scoring_settings == {}
    assert settings.roster_positions == []
    assert settings.playoff_week_start is None
    assert settings.playoff_teams is None
    assert settings.waiver_type is None
    assert settings.waiver_budget is None
    assert settings.trade_deadline is None
    assert settings.draft_id is None
    assert settings.previous_league_id is None


def test_normalize_league_settings_handles_empty_dict() -> None:
    """An entirely empty raw league dict must not crash."""
    settings = normalize_league_settings({})

    assert settings.league_id is None
    assert settings.name is None
    assert settings.season is None
    assert settings.total_rosters is None
    assert settings.scoring_settings == {}
    assert settings.roster_positions == []


def test_normalize_league_settings_null_settings_and_scoring_blocks() -> None:
    """Explicit ``None`` values for nested blocks must not crash."""
    raw_league = {
        "league_id": "2",
        "settings": None,
        "scoring_settings": None,
        "roster_positions": None,
    }

    settings = normalize_league_settings(raw_league)

    assert settings.league_id == "2"
    assert settings.scoring_settings == {}
    assert settings.roster_positions == []
    assert settings.playoff_week_start is None
