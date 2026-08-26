"""Tests for team-defense stat aggregation from raw nflverse player stats (FFA-074).

``build_team_defense_stats`` is tested directly against small in-memory
DataFrames (not the shared ``player_stats.csv`` fixture, which deliberately
carries no defensive columns -- see ``nflverse_provider.py``'s docstring).
``NflverseTeamDefenseProvider`` (which adds download/caching on top) is
tested with requests_mock against the shared player-stats and games
fixtures. Neither ever touches the live nflverse-data release.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.nflverse_defense import (
    TEAM_CODE_ALIASES,
    NflverseTeamDefenseProvider,
    build_team_defense_stats,
)
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient
from fantasy_analyzer.players.points_allowed import normalize_points_allowed
from fantasy_analyzer.players.provider import validate_player_week_columns


def _raw_stats_row(**overrides: object) -> dict:
    row: dict = {
        "season": 2025,
        "week": 1,
        "team": None,
        "def_sacks": 0,
        "def_interceptions": 0,
        "def_fumbles_forced": 0,
        "def_tds": 0,
        "def_safeties": 0,
        "def_punt_blocks": 0,
        "def_pat_blocks": 0,
        "def_fg_blocks": 0,
        "fumble_recovery_opp": 0,
        "fumble_recovery_tds": 0,
        "special_teams_tds": 0,
    }
    row.update(overrides)
    return row


@pytest.fixture
def raw_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # BUF defense: two different players contribute to the same team.
            _raw_stats_row(team="BUF", def_sacks=2, def_interceptions=1),
            _raw_stats_row(team="BUF", special_teams_tds=1),
            # SEA defense: one player, different week to be excluded.
            _raw_stats_row(team="SEA", def_sacks=3, fumble_recovery_opp=1),
            _raw_stats_row(team="SEA", season=2025, week=2, def_sacks=9),
            # A player with no team on record -- must be excluded entirely.
            _raw_stats_row(team=None, def_sacks=5),
        ]
    )


@pytest.fixture
def points_allowed(nflverse_games_fixture_path: Path) -> pd.DataFrame:
    games = pd.read_csv(nflverse_games_fixture_path)
    return normalize_points_allowed(games)


# -------------------------
# build_team_defense_stats (pure, no network)
# -------------------------


def test_build_returns_one_row_per_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert len(result) == 2
    assert set(result["nfl_team"]) == {"BUF", "SEA"}


def test_build_sums_stats_across_multiple_players_on_the_same_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """BUF's def_sacks/def_interceptions come from one row, special_teams_tds
    from another -- both must land on the same aggregated BUF row."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)
    buf = result[result["nfl_team"] == "BUF"].iloc[0]

    assert buf["def_sacks"] == 2
    assert buf["def_interceptions"] == 1
    assert buf["special_teams_tds"] == 1


def test_build_excludes_rows_with_no_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """The 5th fixture row (team=None, def_sacks=5) must not create a phantom row
    or leak into BUF/SEA's totals."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert None not in set(result["nfl_team"])
    assert result["def_sacks"].sum() == 5  # 2 (BUF) + 3 (SEA), not +5 more


def test_build_excludes_other_weeks(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """SEA's week-2 row (def_sacks=9) must not appear in the week-1 result."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)
    sea = result[result["nfl_team"] == "SEA"].iloc[0]

    assert sea["def_sacks"] == 3


def test_build_joins_points_allowed_by_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """BUF allowed BAL's 40; SEA allowed SF's 17 (see games.csv fixture)."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    buf = result[result["nfl_team"] == "BUF"].iloc[0]
    sea = result[result["nfl_team"] == "SEA"].iloc[0]
    assert buf["points_allowed"] == 40
    assert sea["points_allowed"] == 17


def test_build_leaves_points_allowed_nan_when_team_has_no_schedule_row(
    points_allowed: pd.DataFrame,
) -> None:
    """A team with player-week rows but no matching game (e.g. not yet
    published) gets NaN points_allowed, not a dropped row or a KeyError."""
    raw_stats = pd.DataFrame([_raw_stats_row(team="KC", def_sacks=1)])

    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert len(result) == 1
    assert pd.isna(result.iloc[0]["points_allowed"])


def test_build_aliases_team_codes_to_sleeper_convention(
    points_allowed: pd.DataFrame,
) -> None:
    """nflverse's 'LA' must come out as Sleeper's 'LAR' -- see TEAM_CODE_ALIASES."""
    assert TEAM_CODE_ALIASES["LA"] == "LAR"
    raw_stats = pd.DataFrame([_raw_stats_row(team="LA", def_sacks=1)])

    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert result.iloc[0]["sleeper_player_id"] == "LAR"
    assert result.iloc[0]["nfl_team"] == "LAR"


def test_build_result_satisfies_identity_column_contract(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    validate_player_week_columns(result)  # does not raise
    buf = result[result["nfl_team"] == "BUF"].iloc[0]
    assert buf["position"] == "DEF"
    assert pd.isna(buf["gsis_id"])
    assert pd.isna(buf["player_name"])


def test_build_returns_empty_frame_for_a_week_with_no_data(
    points_allowed: pd.DataFrame,
) -> None:
    raw_stats = pd.DataFrame([_raw_stats_row(team="BUF")])

    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=99)

    assert result.empty


# -------------------------
# NflverseTeamDefenseProvider (network mocked)
# -------------------------


def _gzipped_fixture(path: Path) -> bytes:
    return gzip.compress(path.read_bytes())


def test_provider_weekly_stats_matches_pure_function(
    tmp_path: Path,
    nflverse_games_fixture_path: Path,
) -> None:
    raw_stats = pd.DataFrame(
        [
            _raw_stats_row(team="BUF", def_sacks=2),
            _raw_stats_row(team="SEA", def_sacks=3),
        ]
    )
    stats_csv = tmp_path / "raw_stats.csv"
    raw_stats.to_csv(stats_csv, index=False)

    provider = NflverseTeamDefenseProvider(cache_dir=tmp_path)

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.STATS_PLAYER_WEEK_URL_TEMPLATE.format(season=2025),
            content=gzip.compress(stats_csv.read_bytes()),
        )
        m.get(
            NflverseScheduleClient.GAMES_URL,
            content=nflverse_games_fixture_path.read_bytes(),
        )
        result = provider.weekly_stats(season=2025, week=1)

    assert len(result) == 2
    validate_player_week_columns(result)
    buf = result[result["nfl_team"] == "BUF"].iloc[0]
    assert buf["def_sacks"] == 2
    assert buf["points_allowed"] == 40
