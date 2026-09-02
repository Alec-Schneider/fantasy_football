"""Tests for the pure draft-market normalizer/contract (FFA-075).

Operates entirely on in-memory DataFrames and sanitized fixture files --
no HTTP calls are made or mocked here, per AGENTS.md's separation of data
access from normalization. See ``test_draft_market_client.py`` and
``test_draft_market_cache.py`` for the network-adjacent layers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from fantasy_analyzer.players.draft_market import (
    DRAFT_MARKET_COLUMNS,
    DRAFT_MARKET_POOL_COLUMNS,
    FANTASYPROS_ECR_SOURCE,
    FFC_ADP_SOURCE,
    build_draft_market,
    build_draft_market_player_pool,
    build_fantasypros_draft_market,
    build_ffc_draft_market,
    validate_draft_market_columns,
)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "draft_market"


@pytest.fixture
def player_ids() -> pd.DataFrame:
    return pd.read_csv(FIXTURES_DIR / "db_playerids.csv", low_memory=False)


@pytest.fixture
def ffc_players() -> pd.DataFrame:
    payload = json.loads((FIXTURES_DIR / "ffc_adp.json").read_text())
    return pd.DataFrame(payload["players"])


@pytest.fixture
def fpecr_raw() -> pd.DataFrame:
    return pd.read_csv(FIXTURES_DIR / "db_fpecr_latest.csv", low_memory=False)


# ---------------------------------------------------------------------------
# build_ffc_draft_market
#
# Name/team normalization (suffix stripping, the JAC/JAX team alias) is
# exercised indirectly below through the public builders rather than by
# importing the private ``_normalize_player_name``/``_normalize_team``
# helpers directly, per this codebase's convention of not testing private
# names across a module boundary.
# ---------------------------------------------------------------------------


def test_build_ffc_draft_market_columns_and_dtypes(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)

    assert list(result.columns) == DRAFT_MARKET_COLUMNS
    assert result["season"].dtype == "int64"
    assert (result["source"] == FFC_ADP_SOURCE).all()
    assert (result["season"] == 2026).all()


def test_build_ffc_draft_market_joins_offense_by_normalized_name(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)

    allen = result.loc[result["player_name"] == "Josh Allen"].iloc[0]
    assert allen["sleeper_player_id"] == "4984"
    assert allen["gsis_id"] == "00-0034857"
    assert allen["consensus_rank"] == 10.0
    assert allen["rank_sd"] == 3.0
    assert allen["rank_best"] == 5.0
    assert allen["rank_worst"] == 15.0
    assert allen["bye_week"] == 7.0


def test_build_ffc_draft_market_strips_generational_suffix_for_join(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    """"Michael Pittman Jr." must join against the crosswalk's "Michael Pittman"."""
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)

    pittman = result.loc[result["player_name"] == "Michael Pittman Jr."].iloc[0]
    assert pittman["sleeper_player_id"] == "7000"


def test_build_ffc_draft_market_prefers_populated_sleeper_id_on_name_collision(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    """Two crosswalk rows share "Michael Pittman"; only one has a sleeper_id."""
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)

    pittman = result.loc[result["player_name"] == "Michael Pittman Jr."].iloc[0]
    assert pittman["sleeper_player_id"] == "7000"
    assert pd.notna(pittman["sleeper_player_id"])


def test_build_ffc_draft_market_aliases_pk_to_k_for_the_join(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    """FFC's "PK" and the crosswalk's "PK" must both normalize to "K"."""
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)

    kicker = result.loc[result["player_name"] == "Test Kicker"].iloc[0]
    assert kicker["position"] == "K"
    assert kicker["sleeper_player_id"] == "6162"
    assert kicker["gsis_id"] == "00-0061620"


def test_build_ffc_draft_market_defense_uses_team_code_as_sleeper_id(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)

    defense = result.loc[result["player_name"] == "Seattle Defense"].iloc[0]
    assert defense["position"] == "DEF"
    assert defense["sleeper_player_id"] == "SEA"
    assert pd.isna(defense["gsis_id"])


def test_build_ffc_draft_market_leaves_unmatched_player_id_none(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)

    unmatched = result.loc[result["player_name"] == "No Match Player"].iloc[0]
    assert pd.isna(unmatched["sleeper_player_id"])
    assert pd.isna(unmatched["gsis_id"])
    # The row is still present with its raw ADP value, not dropped.
    assert unmatched["consensus_rank"] == 220.0


def test_build_ffc_draft_market_empty_input_returns_empty_shaped_frame(
    player_ids: pd.DataFrame,
) -> None:
    result = build_ffc_draft_market(pd.DataFrame(), player_ids, season=2026)

    assert result.empty
    assert list(result.columns) == DRAFT_MARKET_COLUMNS
    assert result["season"].dtype == "int64"
    assert result["consensus_rank"].dtype == "float64"


def test_build_ffc_draft_market_handles_empty_player_ids(
    ffc_players: pd.DataFrame,
) -> None:
    result = build_ffc_draft_market(ffc_players, pd.DataFrame(), season=2026)

    assert len(result) == len(ffc_players)
    # Non-defense rows can't resolve without a crosswalk; defenses still can.
    defense = result.loc[result["player_name"] == "Seattle Defense"].iloc[0]
    assert defense["sleeper_player_id"] == "SEA"
    allen = result.loc[result["player_name"] == "Josh Allen"].iloc[0]
    assert pd.isna(allen["sleeper_player_id"])


# ---------------------------------------------------------------------------
# build_fantasypros_draft_market
# ---------------------------------------------------------------------------


def test_build_fantasypros_draft_market_columns_and_dtypes(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_fantasypros_draft_market(fpecr_raw, player_ids, season=2026)

    assert list(result.columns) == DRAFT_MARKET_COLUMNS
    assert (result["source"] == FANTASYPROS_ECR_SOURCE).all()
    # Only the "redraft-overall" page_type rows are included (7 in the
    # fixture), not the per-position pages.
    assert len(result) == 7


def test_build_fantasypros_draft_market_joins_by_fantasypros_id(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_fantasypros_draft_market(fpecr_raw, player_ids, season=2026)

    allen = result.loc[result["player_name"] == "Josh Allen"].iloc[0]
    assert allen["sleeper_player_id"] == "4984"
    assert allen["gsis_id"] == "00-0034857"
    assert allen["consensus_rank"] == 10.5
    assert allen["rank_sd"] == 2.1
    assert allen["rank_best"] == 8.0
    assert allen["rank_worst"] == 14.0
    assert allen["bye_week"] == 7.0


def test_build_fantasypros_draft_market_resolves_id_collision_to_populated_sleeper_id(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    """fantasypros_id 3001 is shared by an unmatched and a matched crosswalk row."""
    result = build_fantasypros_draft_market(fpecr_raw, player_ids, season=2026)

    row = result.loc[result["player_name"] == "Current Guy"].iloc[0]
    assert row["sleeper_player_id"] == "8888"


def test_build_fantasypros_draft_market_dst_uses_team_code_with_alias(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    """DynastyProcess spells Jacksonville "JAC"; Sleeper's own code is "JAX"."""
    result = build_fantasypros_draft_market(fpecr_raw, player_ids, season=2026)

    jax = result.loc[result["player_name"] == "Jacksonville Jaguars"].iloc[0]
    assert jax["position"] == "DEF"
    assert jax["nfl_team"] == "JAX"
    assert jax["sleeper_player_id"] == "JAX"

    sea = result.loc[result["player_name"] == "Seattle Seahawks"].iloc[0]
    assert sea["sleeper_player_id"] == "SEA"


def test_build_fantasypros_draft_market_leaves_unmatched_id_none(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_fantasypros_draft_market(fpecr_raw, player_ids, season=2026)

    unmatched = result.loc[result["player_name"] == "No Fantasypros Match"].iloc[0]
    assert pd.isna(unmatched["sleeper_player_id"])
    assert unmatched["consensus_rank"] == 200.0


def test_build_fantasypros_draft_market_empty_input_returns_empty_shaped_frame(
    player_ids: pd.DataFrame,
) -> None:
    result = build_fantasypros_draft_market(pd.DataFrame(), player_ids, season=2026)

    assert result.empty
    assert list(result.columns) == DRAFT_MARKET_COLUMNS


def test_build_fantasypros_draft_market_missing_page_type_column_is_empty(
    player_ids: pd.DataFrame,
) -> None:
    wrong_shape = pd.DataFrame({"player": ["X"], "ecr": [1.0]})
    result = build_fantasypros_draft_market(wrong_shape, player_ids, season=2026)

    assert result.empty
    assert list(result.columns) == DRAFT_MARKET_COLUMNS


def test_build_fantasypros_draft_market_no_overall_rows_is_empty(
    player_ids: pd.DataFrame,
) -> None:
    only_position_pages = pd.DataFrame(
        {
            "page_type": ["redraft-qb"],
            "player": ["X"],
            "pos": ["QB"],
            "team": ["BUF"],
            "ecr": [1.0],
        }
    )
    result = build_fantasypros_draft_market(
        only_position_pages, player_ids, season=2026
    )

    assert result.empty


# ---------------------------------------------------------------------------
# build_draft_market
# ---------------------------------------------------------------------------


def test_build_draft_market_combines_both_sources(
    ffc_players: pd.DataFrame, fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_draft_market(ffc_players, fpecr_raw, player_ids, season=2026)

    assert list(result.columns) == DRAFT_MARKET_COLUMNS
    assert set(result["source"]) == {FFC_ADP_SOURCE, FANTASYPROS_ECR_SOURCE}
    assert len(result) == len(ffc_players) + 7
    validate_draft_market_columns(result)


def test_build_draft_market_one_source_unreachable_still_returns_the_other(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_draft_market(ffc_players, pd.DataFrame(), player_ids, season=2026)

    assert not result.empty
    assert set(result["source"]) == {FFC_ADP_SOURCE}


def test_build_draft_market_both_sources_empty_returns_empty_shaped_frame(
    player_ids: pd.DataFrame,
) -> None:
    result = build_draft_market(pd.DataFrame(), pd.DataFrame(), player_ids, season=2026)

    assert result.empty
    assert list(result.columns) == DRAFT_MARKET_COLUMNS


# ---------------------------------------------------------------------------
# validate_draft_market_columns
# ---------------------------------------------------------------------------


def test_validate_draft_market_columns_accepts_a_conforming_frame(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    result = build_ffc_draft_market(ffc_players, player_ids, season=2026)
    validate_draft_market_columns(result)  # should not raise


def test_validate_draft_market_columns_raises_on_missing_column() -> None:
    wrong_shape = pd.DataFrame({"season": [2026]})

    with pytest.raises(ValueError, match="missing required column"):
        validate_draft_market_columns(wrong_shape)


def test_validate_draft_market_columns_raises_on_out_of_order_columns() -> None:
    reordered = pd.DataFrame({column: [] for column in reversed(DRAFT_MARKET_COLUMNS)})

    with pytest.raises(ValueError, match="leading columns"):
        validate_draft_market_columns(reordered)


# ---------------------------------------------------------------------------
# build_draft_market_player_pool
# ---------------------------------------------------------------------------


def test_build_draft_market_player_pool_columns_and_dtypes(
    ffc_players: pd.DataFrame, fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    draft_market = build_draft_market(ffc_players, fpecr_raw, player_ids, season=2026)
    pool = build_draft_market_player_pool(draft_market, fpecr_raw, player_ids)

    assert list(pool.columns) == DRAFT_MARKET_POOL_COLUMNS
    assert pool["sleeper_player_id"].dtype == object
    assert pool["adp"].dtype == "float64"
    assert pool["ecr"].dtype == "float64"


def test_build_draft_market_player_pool_one_row_per_sleeper_player(
    ffc_players: pd.DataFrame, fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    draft_market = build_draft_market(ffc_players, fpecr_raw, player_ids, season=2026)
    pool = build_draft_market_player_pool(draft_market, fpecr_raw, player_ids)

    assert pool["sleeper_player_id"].is_unique
    # Josh Allen is in both FFC (sleeper 4984) and FantasyPros (sleeper
    # 4984) sources -- must collapse to one row with both adp and ecr set.
    allen = pool.loc[pool["sleeper_player_id"] == "4984"].iloc[0]
    assert allen["adp"] == 10.0
    assert allen["ecr"] == 10.5
    assert allen["position_ecr"] == 1.0


def test_build_draft_market_player_pool_excludes_unmatched_rows(
    ffc_players: pd.DataFrame, fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    draft_market = build_draft_market(ffc_players, fpecr_raw, player_ids, season=2026)
    pool = build_draft_market_player_pool(draft_market, fpecr_raw, player_ids)

    assert "No Match Player" not in set(pool["player_name"])
    assert "No Fantasypros Match" not in set(pool["player_name"])


def test_build_draft_market_player_pool_includes_kicker_and_defense(
    ffc_players: pd.DataFrame, fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    draft_market = build_draft_market(ffc_players, fpecr_raw, player_ids, season=2026)
    pool = build_draft_market_player_pool(draft_market, fpecr_raw, player_ids)

    assert "K" in set(pool["position"])
    assert "DEF" in set(pool["position"])

    kicker = pool.loc[pool["sleeper_player_id"] == "6162"].iloc[0]
    assert kicker["position_ecr"] == 4.0

    sea_def = pool.loc[pool["sleeper_player_id"] == "SEA"].iloc[0]
    assert sea_def["position"] == "DEF"
    jax_def = pool.loc[pool["sleeper_player_id"] == "JAX"].iloc[0]
    assert jax_def["position"] == "DEF"
    assert jax_def["position_ecr"] == 2.0


def test_build_draft_market_player_pool_prefers_fantasypros_identity_fields(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    """When only one source resolves a player, that source's identity wins."""
    ffc_only = pd.DataFrame(
        [
            {
                "player_id": 10,
                "name": "Josh Allen",
                "position": "QB",
                "team": "BUF",
                "adp": 5.0,
                "high": 1,
                "low": 8,
                "stdev": 1.0,
                "bye": 7,
            }
        ]
    )
    draft_market = build_draft_market(ffc_only, fpecr_raw, player_ids, season=2026)
    pool = build_draft_market_player_pool(draft_market, fpecr_raw, player_ids)

    allen = pool.loc[pool["sleeper_player_id"] == "4984"].iloc[0]
    assert allen["adp"] == 5.0
    assert allen["ecr"] == 10.5


def test_build_draft_market_player_pool_empty_draft_market_is_empty() -> None:
    empty_market = pd.DataFrame(columns=DRAFT_MARKET_COLUMNS)
    pool = build_draft_market_player_pool(empty_market, pd.DataFrame(), pd.DataFrame())

    assert pool.empty
    assert list(pool.columns) == DRAFT_MARKET_POOL_COLUMNS


def test_build_draft_market_player_pool_handles_empty_fpecr_raw(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame
) -> None:
    draft_market = build_draft_market(
        ffc_players, pd.DataFrame(), player_ids, season=2026
    )
    pool = build_draft_market_player_pool(draft_market, pd.DataFrame(), player_ids)

    assert not pool.empty
    assert pool["position_ecr"].isna().all()
