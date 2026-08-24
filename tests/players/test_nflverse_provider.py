"""Tests for the nflverse-backed PlayerStatsProvider (FFA-061).

``normalize_player_stats`` is tested directly against an in-memory/fixture
DataFrame with no HTTP involved. ``NflverseWeeklyStatsProvider`` (which adds
download/caching on top) is tested with requests_mock, following the same
pattern as ``tests/sleeper/test_cache.py``. Neither ever touches the live
nflverse-data release.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.players import PLAYER_WEEK_IDENTITY_COLUMNS, PlayerStatsProvider
from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.nflverse_provider import (
    RAW_STAT_COLUMNS,
    NflverseWeeklyStatsProvider,
    normalize_player_stats,
)
from fantasy_analyzer.players.provider import validate_player_week_columns


def _gzipped_fixture(path: Path) -> bytes:
    return gzip.compress(path.read_bytes())


@pytest.fixture
def raw_stats(nflverse_fixture_path: Path) -> pd.DataFrame:
    return pd.read_csv(nflverse_fixture_path)


# -------------------------
# normalize_player_stats (pure, no network)
# -------------------------


def test_normalize_filters_to_the_requested_season_and_week(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=1)

    assert len(result) == 2
    assert set(result["season"]) == {2025}
    assert set(result["week"]) == {1}
    assert list(result["player_name"]) == ["Josh Allen", "Some Rookie"]


def test_normalize_excludes_other_seasons(raw_stats: pd.DataFrame) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=1)

    assert "Old Season Player" not in set(result["player_name"])


def test_normalize_can_return_an_older_season(raw_stats: pd.DataFrame) -> None:
    result = normalize_player_stats(raw_stats, season=2024, week=1)

    assert len(result) == 1
    assert result.iloc[0]["player_name"] == "Old Season Player"
    assert result.iloc[0]["nfl_team"] == "DAL"


def test_normalize_result_carries_the_required_identity_columns(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=1)

    validate_player_week_columns(result)  # does not raise
    assert list(result.columns[: len(PLAYER_WEEK_IDENTITY_COLUMNS)]) == (
        PLAYER_WEEK_IDENTITY_COLUMNS
    )


def test_normalize_maps_gsis_id_and_player_name_and_team(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=1)
    allen = result[result["player_name"] == "Josh Allen"].iloc[0]

    assert allen["gsis_id"] == "00-0034857"
    assert allen["position"] == "QB"
    assert allen["nfl_team"] == "BUF"


def test_normalize_leaves_sleeper_player_id_none_on_every_row(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=1)

    assert result["sleeper_player_id"].isna().all()


def test_normalize_handles_a_row_missing_gsis_id_and_team(
    raw_stats: pd.DataFrame,
) -> None:
    """"Some Rookie" has a blank player_id and recent_team in the fixture."""
    result = normalize_player_stats(raw_stats, season=2025, week=1)
    rookie = result[result["player_name"] == "Some Rookie"].iloc[0]

    assert pd.isna(rookie["gsis_id"])
    assert pd.isna(rookie["nfl_team"])
    assert pd.isna(rookie["sleeper_player_id"])


def test_normalize_passes_through_documented_raw_stat_columns(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=2)
    chase = result[result["player_name"] == "Ja'Marr Chase"].iloc[0]

    assert chase["receptions"] == 8
    assert chase["receiving_yards"] == 120
    assert chase["receiving_tds"] == 1
    for stat_column in RAW_STAT_COLUMNS:
        assert stat_column in result.columns


def test_normalize_does_not_pass_through_fantasy_points(
    raw_stats: pd.DataFrame,
) -> None:
    """Computing fantasy points from league scoring settings is FFA-063's job."""
    result = normalize_player_stats(raw_stats, season=2025, week=1)

    assert "fantasy_points" not in result.columns
    assert "fantasy_points_ppr" not in result.columns


def test_normalize_returns_empty_frame_for_a_week_with_no_data(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=99)

    assert result.empty
    assert list(result.columns[: len(PLAYER_WEEK_IDENTITY_COLUMNS)]) == (
        PLAYER_WEEK_IDENTITY_COLUMNS
    )


def test_normalize_returns_empty_frame_for_a_season_with_no_data(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2099, week=1)

    assert result.empty
    validate_player_week_columns(result)  # does not raise


def test_normalize_a_player_who_did_not_play_has_no_row(
    raw_stats: pd.DataFrame,
) -> None:
    result = normalize_player_stats(raw_stats, season=2025, week=2)

    assert "Josh Allen" not in set(result["player_name"])
    assert len(result) == 1


# -------------------------
# NflverseWeeklyStatsProvider (network mocked)
# -------------------------


def test_provider_satisfies_the_protocol_structurally() -> None:
    provider = NflverseWeeklyStatsProvider()

    assert isinstance(provider, PlayerStatsProvider)


def test_provider_weekly_stats_returns_the_requested_week(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    provider = NflverseWeeklyStatsProvider(cache_path=cache_path)

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        result = provider.weekly_stats(season=2025, week=1)

    assert len(result) == 2
    validate_player_week_columns(result)


def test_provider_downloads_once_and_reuses_in_memory_across_calls(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    provider = NflverseWeeklyStatsProvider(cache_path=cache_path)

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        provider.weekly_stats(season=2025, week=1)
        provider.weekly_stats(season=2025, week=2)

        assert m.call_count == 1


def test_provider_reuses_disk_cache_across_provider_instances(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        NflverseWeeklyStatsProvider(cache_path=cache_path).weekly_stats(2025, 1)
        assert m.call_count == 1

        # A second provider instance should read the now-populated disk
        # cache rather than hitting the network again.
        result = NflverseWeeklyStatsProvider(cache_path=cache_path).weekly_stats(
            2025, 2
        )
        assert m.call_count == 1

    assert len(result) == 1


def test_provider_force_refresh_bypasses_the_disk_cache(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    cache_path.write_text("player_id,season,week\n00-9999,1999,1\n")

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        provider = NflverseWeeklyStatsProvider(
            cache_path=cache_path, force_refresh=True
        )
        result = provider.weekly_stats(season=2025, week=1)

        assert m.called

    assert len(result) == 2


def test_provider_weekly_stats_empty_for_a_week_with_no_data(
    tmp_path: Path, nflverse_fixture_path: Path
) -> None:
    cache_path = tmp_path / "player_stats.csv"
    provider = NflverseWeeklyStatsProvider(cache_path=cache_path)

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.PLAYER_STATS_URL,
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        result = provider.weekly_stats(season=2030, week=1)

    assert result.empty
    validate_player_week_columns(result)
