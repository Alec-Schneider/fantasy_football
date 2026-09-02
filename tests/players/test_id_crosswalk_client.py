"""Tests for the raw DynastyProcess player-ID crosswalk HTTP download client.

These tests never touch the live DynastyProcess asset -- all HTTP calls are
mocked with requests_mock against a sanitized fixture CSV. Mirrors
``test_nflverse_schedule_client.py``'s structure for the sibling cumulative
CSV client.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient


@pytest.fixture
def client() -> PlayerIdCrosswalkClient:
    return PlayerIdCrosswalkClient()


def test_download_player_ids_returns_a_dataframe(
    client: PlayerIdCrosswalkClient, id_crosswalk_fixture_path: Path
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            PlayerIdCrosswalkClient.PLAYER_IDS_URL,
            content=id_crosswalk_fixture_path.read_bytes(),
        )
        result = client.download_player_ids()

    assert len(result) == 7
    assert "sleeper_id" in result.columns
    assert "gsis_id" in result.columns
    assert "Josh Allen" in set(result["name"])


def test_download_player_ids_raises_on_http_error(
    client: PlayerIdCrosswalkClient,
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(PlayerIdCrosswalkClient.PLAYER_IDS_URL, status_code=500)

        with pytest.raises(requests.exceptions.HTTPError):
            client.download_player_ids()


def test_download_player_ids_returns_empty_frame_on_404(
    client: PlayerIdCrosswalkClient,
) -> None:
    """The asset being unreachable (404) is "no data", not an error."""
    with requests_mock_lib.Mocker() as m:
        m.get(PlayerIdCrosswalkClient.PLAYER_IDS_URL, status_code=404)

        result = client.download_player_ids()

    assert result.empty
