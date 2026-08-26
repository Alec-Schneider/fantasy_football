"""Tests for deriving team points-allowed from nflverse's games table (FFA-073).

``normalize_points_allowed`` is tested directly against an in-memory/fixture
DataFrame with no HTTP involved. ``NflverseScheduleProvider`` (which adds
download/caching on top) is tested with requests_mock, following the same
pattern as ``test_nflverse_provider.py``. Neither ever touches the live
nflverse-data release.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient
from fantasy_analyzer.players.points_allowed import (
    POINTS_ALLOWED_COLUMNS,
    NflverseScheduleProvider,
    normalize_points_allowed,
)


@pytest.fixture
def raw_games(nflverse_games_fixture_path: Path) -> pd.DataFrame:
    return pd.read_csv(nflverse_games_fixture_path)


def _mock_url(m: requests_mock_lib.Mocker, **kwargs) -> None:
    m.get(NflverseScheduleClient.GAMES_URL, **kwargs)


# -------------------------
# normalize_points_allowed (pure, no network)
# -------------------------


def test_normalize_produces_two_rows_per_regular_season_game(
    raw_games: pd.DataFrame,
) -> None:
    """Fixture has 4 REG games with final scores -> 8 team-week rows."""
    result = normalize_points_allowed(raw_games)

    assert list(result.columns) == POINTS_ALLOWED_COLUMNS
    assert len(result) == 8


def test_normalize_hand_checked_toy_example(raw_games: pd.DataFrame) -> None:
    """BUF 41, BAL 40 (2025 week 1): each team's points_allowed is the other's score."""
    result = normalize_points_allowed(raw_games)

    week_1_2025 = (result["week"] == 1) & (result["season"] == 2025)
    buf = result[(result["team"] == "BUF") & week_1_2025]
    bal = result[(result["team"] == "BAL") & week_1_2025]

    assert buf.iloc[0]["points_allowed"] == 40
    assert bal.iloc[0]["points_allowed"] == 41


def test_normalize_excludes_non_regular_season_games(raw_games: pd.DataFrame) -> None:
    """The fixture's 2025 week-1 WC game (KC/DEN) must not appear."""
    result = normalize_points_allowed(raw_games)

    week_1_2025 = result[(result["week"] == 1) & (result["season"] == 2025)]
    assert "KC" not in set(week_1_2025["team"])
    assert "DEN" not in set(result["team"])


def test_normalize_excludes_games_with_no_final_score(raw_games: pd.DataFrame) -> None:
    """The fixture's unplayed week-3 DAL/NYG game has no score and must not appear."""
    result = normalize_points_allowed(raw_games)

    assert "DAL" not in set(result["team"])
    assert "NYG" not in set(result["team"])


def test_normalize_keeps_seasons_distinct(raw_games: pd.DataFrame) -> None:
    result = normalize_points_allowed(raw_games)

    kc_2024 = result[(result["team"] == "KC") & (result["season"] == 2024)]
    assert len(kc_2024) == 1
    assert kc_2024.iloc[0]["points_allowed"] == 20


def test_normalize_returns_empty_frame_for_missing_required_columns() -> None:
    result = normalize_points_allowed(pd.DataFrame({"season": [2025]}))

    assert result.empty
    assert list(result.columns) == POINTS_ALLOWED_COLUMNS


def test_normalize_returns_empty_frame_for_empty_input() -> None:
    result = normalize_points_allowed(pd.DataFrame())

    assert result.empty
    assert list(result.columns) == POINTS_ALLOWED_COLUMNS


# -------------------------
# NflverseScheduleProvider (network mocked)
# -------------------------


def test_provider_points_allowed_returns_the_requested_week(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    provider = NflverseScheduleProvider(cache_dir=tmp_path)

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=nflverse_games_fixture_path.read_bytes())
        result = provider.points_allowed(season=2025, week=1)

    assert list(result.columns) == ["team", "points_allowed"]
    assert len(result) == 4
    assert set(result["team"]) == {"BUF", "BAL", "SEA", "SF"}


def test_provider_downloads_once_and_reuses_in_memory_across_calls(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    provider = NflverseScheduleProvider(cache_dir=tmp_path)

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=nflverse_games_fixture_path.read_bytes())
        provider.points_allowed(season=2025, week=1)
        provider.points_allowed(season=2025, week=2)
        provider.points_allowed(season=2024, week=1)

        assert m.call_count == 1


def test_provider_returns_empty_for_a_week_with_no_games(
    tmp_path: Path, nflverse_games_fixture_path: Path
) -> None:
    provider = NflverseScheduleProvider(cache_dir=tmp_path)

    with requests_mock_lib.Mocker() as m:
        _mock_url(m, content=nflverse_games_fixture_path.read_bytes())
        result = provider.points_allowed(season=2025, week=99)

    assert result.empty
