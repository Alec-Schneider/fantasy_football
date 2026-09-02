"""Tests for the raw FFC/FantasyPros draft-market HTTP download clients.

These tests never touch the live FFC or DynastyProcess assets -- all HTTP
calls are mocked with requests_mock against sanitized fixtures. Mirrors
``test_id_crosswalk_client.py``'s structure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.draft_market_client import (
    FantasyProsEcrClient,
    FfcAdpClient,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "draft_market"


@pytest.fixture
def ffc_adp_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "ffc_adp.json").read_text())


@pytest.fixture
def fpecr_fixture_path() -> Path:
    return FIXTURES_DIR / "db_fpecr_latest.csv"


@pytest.fixture
def ffc_client() -> FfcAdpClient:
    return FfcAdpClient()


@pytest.fixture
def fpecr_client() -> FantasyProsEcrClient:
    return FantasyProsEcrClient()


def test_download_adp_returns_a_dataframe(
    ffc_client: FfcAdpClient, ffc_adp_fixture: dict
) -> None:
    url = FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr")
    with requests_mock_lib.Mocker() as m:
        m.get(url, json=ffc_adp_fixture)
        result = ffc_client.download_adp(2026, teams=12, scoring="half-ppr")

    assert len(result) == 5
    assert "Josh Allen" in set(result["name"])
    assert set(result["position"]) == {"QB", "WR", "PK", "DEF"}


def test_download_adp_passes_expected_query_params(
    ffc_client: FfcAdpClient, ffc_adp_fixture: dict
) -> None:
    url = FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr")
    with requests_mock_lib.Mocker() as m:
        m.get(url, json=ffc_adp_fixture)
        ffc_client.download_adp(2026, teams=10, scoring="half-ppr")

    query = m.request_history[0].qs
    assert query["teams"] == ["10"]
    assert query["year"] == ["2026"]
    assert query["position"] == ["all"]


def test_download_adp_raises_on_http_error(ffc_client: FfcAdpClient) -> None:
    url = FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr")
    with requests_mock_lib.Mocker() as m:
        m.get(url, status_code=500)

        with pytest.raises(requests.exceptions.HTTPError):
            ffc_client.download_adp(2026)


def test_download_adp_returns_empty_frame_on_404(ffc_client: FfcAdpClient) -> None:
    """The endpoint being unreachable (404) is "no data", not an error."""
    url = FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr")
    with requests_mock_lib.Mocker() as m:
        m.get(url, status_code=404)

        result = ffc_client.download_adp(2026)

    assert result.empty


def test_download_ecr_returns_a_dataframe(
    fpecr_client: FantasyProsEcrClient, fpecr_fixture_path: Path
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(FantasyProsEcrClient.FPECR_URL, content=fpecr_fixture_path.read_bytes())
        result = fpecr_client.download_ecr()

    assert len(result) == 13
    assert "page_type" in result.columns
    assert "Josh Allen" in set(result["player"])


def test_download_ecr_raises_on_http_error(
    fpecr_client: FantasyProsEcrClient,
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(FantasyProsEcrClient.FPECR_URL, status_code=500)

        with pytest.raises(requests.exceptions.HTTPError):
            fpecr_client.download_ecr()


def test_download_ecr_returns_empty_frame_on_404(
    fpecr_client: FantasyProsEcrClient,
) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(FantasyProsEcrClient.FPECR_URL, status_code=404)

        result = fpecr_client.download_ecr()

    assert result.empty
