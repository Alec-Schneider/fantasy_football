"""Tests for local draft-market caching and fetch-and-normalize glue.

These tests never touch the live FFC/DynastyProcess assets -- all HTTP
calls are mocked with requests_mock against sanitized fixtures. Mirrors
``test_id_crosswalk_cache.py``'s structure.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.draft_market_cache import (
    get_draft_market_cached,
    get_draft_market_player_pool_cached,
    get_ffc_adp_cached,
    get_fpecr_cached,
    load_ffc_adp_cache,
    load_fpecr_cache,
    refresh_ffc_adp_cache,
    refresh_fpecr_cache,
)
from fantasy_analyzer.players.draft_market_client import (
    FantasyProsEcrClient,
    FfcAdpClient,
)
from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "draft_market"


@pytest.fixture
def ffc_adp_payload() -> dict:
    return json.loads((FIXTURES_DIR / "ffc_adp.json").read_text())


@pytest.fixture
def fpecr_bytes() -> bytes:
    return (FIXTURES_DIR / "db_fpecr_latest.csv").read_bytes()


@pytest.fixture
def player_ids_bytes() -> bytes:
    return (FIXTURES_DIR / "db_playerids.csv").read_bytes()


# ---------------------------------------------------------------------------
# FFC ADP cache
# ---------------------------------------------------------------------------


def test_load_ffc_adp_cache_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_ffc_adp_cache(2026, cache_dir=tmp_path) is None


def test_refresh_ffc_adp_cache_writes_table_to_disk(
    tmp_path: Path, ffc_adp_payload: dict
) -> None:
    url = FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr")
    client = FfcAdpClient()

    with requests_mock_lib.Mocker() as m:
        m.get(url, json=ffc_adp_payload)
        result = refresh_ffc_adp_cache(client, 2026, cache_dir=tmp_path)

    cache_path = tmp_path / "ffc" / "adp_half-ppr_12_2026.csv"
    assert cache_path.exists()
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == len(result) == 5


def test_get_ffc_adp_cached_loads_from_cache_without_network(
    tmp_path: Path, ffc_adp_payload: dict
) -> None:
    cache_path = tmp_path / "ffc" / "adp_half-ppr_12_2026.csv"
    cache_path.parent.mkdir(parents=True)
    pd.DataFrame(ffc_adp_payload["players"]).to_csv(cache_path, index=False)
    client = FfcAdpClient()

    with requests_mock_lib.Mocker() as m:
        m.get(FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr"), status_code=500)
        result = get_ffc_adp_cached(client, 2026, cache_dir=tmp_path)

        assert not m.called

    assert len(result) == 5


def test_get_ffc_adp_cached_force_refresh_ignores_existing_cache(
    tmp_path: Path, ffc_adp_payload: dict
) -> None:
    cache_path = tmp_path / "ffc" / "adp_half-ppr_12_2026.csv"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("name,position,team,adp\nStale,WR,ZZZ,1\n")
    client = FfcAdpClient()
    url = FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr")

    with requests_mock_lib.Mocker() as m:
        m.get(url, json=ffc_adp_payload)
        result = get_ffc_adp_cached(
            client, 2026, cache_dir=tmp_path, force_refresh=True
        )

        assert m.called

    assert len(result) == 5


# ---------------------------------------------------------------------------
# FantasyPros ECR cache
# ---------------------------------------------------------------------------


def test_load_fpecr_cache_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_fpecr_cache(tmp_path) is None


def test_refresh_fpecr_cache_writes_table_to_disk(
    tmp_path: Path, fpecr_bytes: bytes
) -> None:
    client = FantasyProsEcrClient()

    with requests_mock_lib.Mocker() as m:
        m.get(FantasyProsEcrClient.FPECR_URL, content=fpecr_bytes)
        result = refresh_fpecr_cache(client, tmp_path)

    cache_path = tmp_path / "fantasypros" / "db_fpecr_latest.csv"
    assert cache_path.exists()
    on_disk = pd.read_csv(cache_path)
    assert len(on_disk) == len(result) == 13


def test_get_fpecr_cached_loads_from_cache_without_network(
    tmp_path: Path, fpecr_bytes: bytes
) -> None:
    cache_path = tmp_path / "fantasypros" / "db_fpecr_latest.csv"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(fpecr_bytes)
    client = FantasyProsEcrClient()

    with requests_mock_lib.Mocker() as m:
        m.get(FantasyProsEcrClient.FPECR_URL, status_code=500)
        result = get_fpecr_cached(client, tmp_path)

        assert not m.called

    assert len(result) == 13


# ---------------------------------------------------------------------------
# get_draft_market_cached / get_draft_market_player_pool_cached
# ---------------------------------------------------------------------------


def _mock_all_sources(
    m: requests_mock_lib.Mocker,
    ffc_adp_payload: dict,
    fpecr_bytes: bytes,
    player_ids_bytes: bytes,
) -> None:
    url = FfcAdpClient.ADP_URL_TEMPLATE.format(scoring="half-ppr")
    m.get(url, json=ffc_adp_payload)
    m.get(FantasyProsEcrClient.FPECR_URL, content=fpecr_bytes)
    m.get(PlayerIdCrosswalkClient.PLAYER_IDS_URL, content=player_ids_bytes)


def test_get_draft_market_cached_fetches_and_normalizes_all_sources(
    tmp_path: Path,
    ffc_adp_payload: dict,
    fpecr_bytes: bytes,
    player_ids_bytes: bytes,
) -> None:
    cache_dir = tmp_path / "draft_market"
    id_crosswalk_cache_dir = tmp_path / "id_crosswalk"

    with requests_mock_lib.Mocker() as m:
        _mock_all_sources(m, ffc_adp_payload, fpecr_bytes, player_ids_bytes)
        result = get_draft_market_cached(
            2026,
            cache_dir=cache_dir,
            id_crosswalk_cache_dir=id_crosswalk_cache_dir,
        )

    assert not result.empty
    assert set(result["source"]) == {"ffc_adp", "fantasypros_ecr"}
    allen = result.loc[result["player_name"] == "Josh Allen"]
    assert (allen["sleeper_player_id"] == "4984").all()


def test_get_draft_market_cached_reuses_disk_cache_without_network(
    tmp_path: Path,
    ffc_adp_payload: dict,
    fpecr_bytes: bytes,
    player_ids_bytes: bytes,
) -> None:
    cache_dir = tmp_path / "draft_market"
    id_crosswalk_cache_dir = tmp_path / "id_crosswalk"

    with requests_mock_lib.Mocker() as m:
        _mock_all_sources(m, ffc_adp_payload, fpecr_bytes, player_ids_bytes)
        get_draft_market_cached(
            2026, cache_dir=cache_dir, id_crosswalk_cache_dir=id_crosswalk_cache_dir
        )

    with requests_mock_lib.Mocker() as m:
        # No mocks registered at all -- any network call fails loudly.
        result = get_draft_market_cached(
            2026, cache_dir=cache_dir, id_crosswalk_cache_dir=id_crosswalk_cache_dir
        )
        assert not m.called

    assert not result.empty


def test_get_draft_market_player_pool_cached_returns_wide_pool(
    tmp_path: Path,
    ffc_adp_payload: dict,
    fpecr_bytes: bytes,
    player_ids_bytes: bytes,
) -> None:
    cache_dir = tmp_path / "draft_market"
    id_crosswalk_cache_dir = tmp_path / "id_crosswalk"

    with requests_mock_lib.Mocker() as m:
        _mock_all_sources(m, ffc_adp_payload, fpecr_bytes, player_ids_bytes)
        pool = get_draft_market_player_pool_cached(
            2026, cache_dir=cache_dir, id_crosswalk_cache_dir=id_crosswalk_cache_dir
        )

    assert not pool.empty
    assert pool["sleeper_player_id"].is_unique
    allen = pool.loc[pool["sleeper_player_id"] == "4984"].iloc[0]
    assert allen["adp"] == 10.0
    assert allen["ecr"] == 10.5
