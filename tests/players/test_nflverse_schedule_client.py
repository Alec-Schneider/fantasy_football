"""Tests for the raw nflverse games/schedule HTTP download client (FFA-073).

These tests never touch the live nflverse-data release -- all HTTP calls are
mocked with requests_mock against a sanitized fixture CSV. Mirrors
``test_nflverse_client.py``'s structure for the sibling player-stats client.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient


@pytest.fixture
def client() -> NflverseScheduleClient:
    return NflverseScheduleClient()


def test_download_games_returns_a_dataframe(
    client: NflverseScheduleClient, nflverse_games_fixture_path: Path
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseScheduleClient.GAMES_URL,
            content=nflverse_games_fixture_path.read_bytes(),
        )
        result = client.download_games()

    assert len(result) == 6
    assert "home_team" in result.columns
    assert "away_score" in result.columns
    assert set(result["season"]) == {2024, 2025}


def test_download_games_raises_on_http_error(client: NflverseScheduleClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(NflverseScheduleClient.GAMES_URL, status_code=500)

        with pytest.raises(requests.exceptions.HTTPError):
            client.download_games()


def test_download_games_returns_empty_frame_on_404(
    client: NflverseScheduleClient,
) -> None:
    """The release asset being unreachable (404) is "no data", not an error."""
    with requests_mock_lib.Mocker() as m:
        m.get(NflverseScheduleClient.GAMES_URL, status_code=404)

        result = client.download_games()

    assert result.empty
