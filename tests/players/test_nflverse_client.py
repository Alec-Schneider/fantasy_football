"""Tests for the raw nflverse HTTP download client (FFA-061).

These tests never touch the live nflverse-data release -- all HTTP calls are
mocked with requests_mock against a sanitized fixture CSV.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
import requests
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.nflverse_client import NflverseClient


@pytest.fixture
def client() -> NflverseClient:
    return NflverseClient()


def _gzipped_fixture(path: Path) -> bytes:
    return gzip.compress(path.read_bytes())


def test_download_player_stats_returns_a_dataframe(
    client: NflverseClient, nflverse_fixture_path: Path
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.STATS_PLAYER_WEEK_URL_TEMPLATE.format(season=2025),
            content=_gzipped_fixture(nflverse_fixture_path),
        )
        result = client.download_player_stats(2025)

    assert len(result) == 4
    assert "player_id" in result.columns
    assert "recent_team" in result.columns
    assert set(result["season"]) == {2024, 2025}


def test_download_player_stats_raises_on_http_error(client: NflverseClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.STATS_PLAYER_WEEK_URL_TEMPLATE.format(season=2025),
            status_code=500,
        )

        with pytest.raises(requests.exceptions.HTTPError):
            client.download_player_stats(2025)


def test_download_player_stats_returns_empty_frame_for_unpublished_season(
    client: NflverseClient,
) -> None:
    """A season with no release asset yet (404) is "no data", not an error."""
    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.STATS_PLAYER_WEEK_URL_TEMPLATE.format(season=2099),
            status_code=404,
        )

        result = client.download_player_stats(2099)

    assert result.empty
