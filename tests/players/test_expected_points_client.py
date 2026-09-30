"""Tests for the raw ffopportunity expected-points HTTP client (FFA-110).

No live network: every HTTP call is mocked with requests_mock against the
sanitized ``tests/fixtures/ffopportunity/ep_weekly.csv`` fixture. Mirrors
``test_nflverse_schedule_client.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.expected_points_client import ExpectedPointsClient

EP_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "ffopportunity"
    / "ep_weekly.csv"
)


def _url(season: int) -> str:
    return ExpectedPointsClient.EP_WEEKLY_URL_TEMPLATE.format(season=season)


@pytest.fixture
def client() -> ExpectedPointsClient:
    return ExpectedPointsClient()


def test_url_template_points_at_the_latest_data_release() -> None:
    assert _url(2026) == (
        "https://github.com/ffverse/ffopportunity/releases/download/"
        "latest-data/ep_weekly_2026.csv"
    )


def test_download_expected_points_returns_raw_columns(
    client: ExpectedPointsClient,
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(_url(2025), content=EP_FIXTURE.read_bytes())
        result = client.download_expected_points(2025)

    assert len(result) == 12
    assert len(result.columns) == 159
    assert {"player_id", "posteam", "total_fantasy_points_exp"} <= set(result.columns)


def test_download_expected_points_returns_empty_frame_on_404(
    client: ExpectedPointsClient,
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(_url(1999), status_code=404)
        result = client.download_expected_points(1999)

    assert result.empty


def test_download_expected_points_raises_on_http_error(
    client: ExpectedPointsClient,
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(_url(2025), status_code=503)

        with pytest.raises(requests.exceptions.HTTPError):
            client.download_expected_points(2025)
