"""Tests for the raw nflverse snap-count HTTP download client (FFA-110).

No live network: every HTTP call is mocked with requests_mock against the
sanitized ``tests/fixtures/nflverse/snap_counts.csv`` fixture. Mirrors
``test_nflverse_schedule_client.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.snap_counts_client import SnapCountsClient

SNAP_FIXTURE = (
    Path(__file__).resolve().parent.parent / "fixtures" / "nflverse" / "snap_counts.csv"
)


def _url(season: int) -> str:
    return SnapCountsClient.SNAP_COUNTS_URL_TEMPLATE.format(season=season)


@pytest.fixture
def client() -> SnapCountsClient:
    return SnapCountsClient()


def test_url_template_points_at_the_snap_counts_release() -> None:
    assert _url(2026) == (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        "snap_counts/snap_counts_2026.csv"
    )


def test_download_snap_counts_returns_raw_columns(client: SnapCountsClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(_url(2025), content=SNAP_FIXTURE.read_bytes())
        result = client.download_snap_counts(2025)

    assert len(result) == 19
    assert {"pfr_player_id", "offense_snaps", "offense_pct", "game_type"} <= set(
        result.columns
    )


def test_download_snap_counts_returns_empty_frame_on_404(
    client: SnapCountsClient,
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(_url(2011), status_code=404)
        result = client.download_snap_counts(2011)

    assert result.empty


def test_header_only_asset_returns_empty_frame_with_columns(
    client: SnapCountsClient,
) -> None:
    """2012's published asset is a header row and nothing else."""
    header = SNAP_FIXTURE.read_text().splitlines()[0] + "\n"
    with requests_mock_lib.Mocker() as m:
        m.get(_url(2012), text=header)
        result = client.download_snap_counts(2012)

    assert result.empty
    assert "pfr_player_id" in result.columns


def test_download_snap_counts_raises_on_http_error(client: SnapCountsClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(_url(2025), status_code=500)

        with pytest.raises(requests.exceptions.HTTPError):
            client.download_snap_counts(2025)
