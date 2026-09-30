"""Tests for the Sleeper<->nflverse ID crosswalk (FFA-062, FFA-109 name fallback).

Operates entirely on in-memory dicts and the sanitized Sleeper player-catalog
fixture -- no HTTP calls are made or mocked here, per AGENTS.md's separation
of data access from normalization. The one ``build_robust_id_crosswalk`` test
monkeypatches the DynastyProcess cache loader to return the fixture CSV.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    CROSSWALK_COLUMNS,
    build_id_crosswalk,
    build_id_crosswalk_from_player_ids,
    gsis_to_sleeper_lookup,
    sleeper_to_gsis_lookup,
)
from fantasy_analyzer.players.crosswalk import (
    MIN_FIRST_NAME_PREFIX,
    NAME_MATCH_COLUMNS,
    build_name_match_crosswalk,
    build_robust_id_crosswalk,
    extend_crosswalk_with_name_matches,
    fantasy_position,
    normalize_player_name,
    standardize_nflverse_identity,
)

PLAYER_CATALOG = {
    "4984": {
        "player_id": "4984",
        "full_name": "Josh Allen",
        "position": "QB",
        "team": "BUF",
        "gsis_id": "00-0034857",
    },
    "9001": {
        "player_id": "9001",
        "full_name": "Ja'Marr Chase",
        "position": "WR",
        "team": "CIN",
        "gsis_id": None,
    },
    "9002": {
        "player_id": "9002",
        "full_name": "Practice Squad Guy",
        "position": "RB",
        "team": "KC",
        # No gsis_id key at all -- mirrors the real API's shape for some
        # players.
    },
}


def test_build_id_crosswalk_pairs_a_normal_player() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert list(crosswalk.columns) == CROSSWALK_COLUMNS
    row = crosswalk.loc[crosswalk["sleeper_player_id"] == "4984"].iloc[0]
    assert row["gsis_id"] == "00-0034857"
    assert row["full_name"] == "Josh Allen"
    assert row["position"] == "QB"
    assert row["team"] == "BUF"


def test_build_id_crosswalk_excludes_null_gsis_id() -> None:
    """A player with gsis_id: null contributes no crosswalk row."""
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert "9001" not in set(crosswalk["sleeper_player_id"])


def test_build_id_crosswalk_excludes_missing_gsis_id_key() -> None:
    """A player missing the gsis_id key entirely contributes no crosswalk row."""
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert "9002" not in set(crosswalk["sleeper_player_id"])


def test_build_id_crosswalk_only_includes_players_with_a_usable_gsis_id() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    assert len(crosswalk) == 1
    assert list(crosswalk["sleeper_player_id"]) == ["4984"]


def test_build_id_crosswalk_empty_catalog_returns_empty_frame() -> None:
    crosswalk = build_id_crosswalk({})

    assert crosswalk.empty
    assert list(crosswalk.columns) == CROSSWALK_COLUMNS


def test_build_id_crosswalk_resolves_gsis_id_collision_last_wins() -> None:
    """Two Sleeper ids sharing a gsis_id: the later catalog entry wins."""
    catalog = {
        "1111": {
            "player_id": "1111",
            "full_name": "Stale Duplicate",
            "position": "WR",
            "team": "NYJ",
            "gsis_id": "00-0099999",
        },
        "2222": {
            "player_id": "2222",
            "full_name": "Current Player",
            "position": "WR",
            "team": "NYJ",
            "gsis_id": "00-0099999",
        },
    }

    crosswalk = build_id_crosswalk(catalog)

    assert len(crosswalk) == 1
    assert crosswalk.iloc[0]["sleeper_player_id"] == "2222"
    assert crosswalk.iloc[0]["full_name"] == "Current Player"


def test_gsis_to_sleeper_lookup_builds_a_reverse_dict() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    lookup = gsis_to_sleeper_lookup(crosswalk)

    assert lookup == {"00-0034857": "4984"}


def test_gsis_to_sleeper_lookup_empty_crosswalk_returns_empty_dict() -> None:
    empty = pd.DataFrame(columns=CROSSWALK_COLUMNS)

    assert gsis_to_sleeper_lookup(empty) == {}


def test_sleeper_to_gsis_lookup_builds_a_forward_dict() -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    lookup = sleeper_to_gsis_lookup(crosswalk)

    assert lookup == {"4984": "00-0034857"}


def test_sleeper_to_gsis_lookup_empty_crosswalk_returns_empty_dict() -> None:
    empty = pd.DataFrame(columns=CROSSWALK_COLUMNS)

    assert sleeper_to_gsis_lookup(empty) == {}


def test_build_id_crosswalk_from_fixture_catalog(load_sleeper_fixture) -> None:
    """The sanitized fixture carries a mix of populated/null/missing gsis_id."""
    player_catalog = load_sleeper_fixture("players.json")

    crosswalk = build_id_crosswalk(player_catalog)

    # "1000" has a populated gsis_id; "1002" has gsis_id: null; "1003" has
    # no gsis_id key at all -- only "1000" should produce a row.
    assert list(crosswalk["sleeper_player_id"]) == ["1000"]
    assert crosswalk.iloc[0]["gsis_id"] == "00-0034857"


# -------------------------
# build_id_crosswalk_from_player_ids (DynastyProcess source)
# -------------------------


def test_build_id_crosswalk_from_player_ids_pairs_a_normal_player(
    id_crosswalk_fixture_path,
) -> None:
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert list(crosswalk.columns) == CROSSWALK_COLUMNS
    row = crosswalk.loc[crosswalk["sleeper_player_id"] == "4984"].iloc[0]
    assert row["gsis_id"] == "00-0034857"
    assert row["full_name"] == "Josh Allen"
    assert row["position"] == "QB"
    assert row["team"] == "BUF"


def test_build_id_crosswalk_from_player_ids_sleeper_id_has_no_float_suffix(
    id_crosswalk_fixture_path,
) -> None:
    """The source stores sleeper_id numerically -- must render "4984", not "4984.0"."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "4984" in set(crosswalk["sleeper_player_id"])
    assert "4984.0" not in set(crosswalk["sleeper_player_id"])


def test_build_id_crosswalk_from_player_ids_excludes_missing_sleeper_id(
    id_crosswalk_fixture_path,
) -> None:
    """A row with no sleeper_id (blank in the fixture) contributes no row."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "No Sleeper Match" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_excludes_missing_gsis_id(
    id_crosswalk_fixture_path,
) -> None:
    """A row with no gsis_id (blank in the fixture) contributes no row."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "No Gsis Match" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_resolves_gsis_id_collision_last_wins(
    id_crosswalk_fixture_path,
) -> None:
    """Two rows sharing a gsis_id ("00-0055555"): the later row wins."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    matches = crosswalk[crosswalk["gsis_id"] == "00-0055555"]
    assert len(matches) == 1
    assert matches.iloc[0]["full_name"] == "Current Player"
    assert "Stale Duplicate" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_resolves_sleeper_id_collision_last_wins(
    id_crosswalk_fixture_path,
) -> None:
    """Two rows sharing a sleeper_id ("6000"): the later row wins."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    matches = crosswalk[crosswalk["sleeper_player_id"] == "6000"]
    assert len(matches) == 1
    assert matches.iloc[0]["full_name"] == "New Mapping"
    assert "Old Mapping" not in set(crosswalk["full_name"])


def test_build_id_crosswalk_from_player_ids_only_includes_usable_rows(
    id_crosswalk_fixture_path,
) -> None:
    """7 source rows: 1 dropped (no sleeper_id), 1 dropped (no gsis_id), 2
    collision pairs collapse to 1 each -> 3 rows survive."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert len(crosswalk) == 3


def test_build_id_crosswalk_from_player_ids_empty_frame_returns_empty() -> None:
    crosswalk = build_id_crosswalk_from_player_ids(pd.DataFrame())

    assert crosswalk.empty
    assert list(crosswalk.columns) == CROSSWALK_COLUMNS


def test_build_id_crosswalk_from_player_ids_missing_column_raises() -> None:
    wrong_shape = pd.DataFrame({"sleeper_id": [1], "gsis_id": ["00-0000001"]})

    with pytest.raises(ValueError, match="name"):
        build_id_crosswalk_from_player_ids(wrong_shape)


def test_build_id_crosswalk_from_player_ids_ignores_unrelated_columns(
    id_crosswalk_fixture_path,
) -> None:
    """mfl_id is present in the fixture but not part of CROSSWALK_COLUMNS."""
    raw = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)

    crosswalk = build_id_crosswalk_from_player_ids(raw)

    assert "mfl_id" not in crosswalk.columns


# -------------------------
# FFA-109: conservative name fallback
# -------------------------


def _nflverse_row(gsis_id, name, position, team, season=2026, week=1):
    """One raw-shape nflverse row (``player_id`` is the GSIS id)."""
    return {
        "player_id": gsis_id,
        "player_name": "abbrev",
        "player_display_name": name,
        "position": position,
        "team": team,
        "season": season,
        "week": week,
        "season_type": "REG",
    }


def _catalog_player(player_id, name, position, team, gsis_id=None):
    return {
        "player_id": player_id,
        "full_name": name,
        "position": position,
        "team": team,
        "gsis_id": gsis_id,
    }


@pytest.fixture
def toy_name_catalog() -> dict:
    """The module docstring's toy example, Sleeper side."""
    return {
        "13324": _catalog_player("13324", "Matt Hibner", "TE", "BAL"),
        "13545": _catalog_player("13545", "Trey Smack", "K", "GB"),
    }


@pytest.fixture
def toy_name_stats() -> pd.DataFrame:
    """The module docstring's toy example, nflverse side."""
    return pd.DataFrame(
        [
            _nflverse_row("00-1", "Matthew Hibner", "TE", "BAL"),
            _nflverse_row("00-2", "Trey Smack", "K", "GB"),
        ]
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Amon-Ra St. Brown", "amon ra st brown"),
        ("Marvin Harrison Jr.", "marvin harrison"),
        ("Kenneth Walker III", "kenneth walker"),
        ("D.J. Moore", "dj moore"),
        ("Ja'Marr Chase", "jamarr chase"),
        ("José  Ramírez", "jose ramirez"),
        # Two tokens: "V" is kept -- only 3+ token names lose a suffix.
        ("John V", "john v"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_player_name(raw, expected) -> None:
    assert normalize_player_name(raw) == expected


def test_fantasy_position_aliases_and_rejects() -> None:
    assert fantasy_position("FB") == "RB"
    assert fantasy_position("PK") == "K"
    assert fantasy_position("WR") == "WR"
    assert fantasy_position("LB") is None
    assert fantasy_position(None) is None


def test_standardize_nflverse_identity_raw_shape_prefers_display_name() -> None:
    raw = pd.DataFrame([_nflverse_row("00-1", "Josh Allen", "QB", "BUF")])

    frame = standardize_nflverse_identity(raw)

    row = frame.iloc[0]
    assert row["gsis_id"] == "00-1"
    assert row["player_name"] == "Josh Allen"
    assert row["nfl_team"] == "BUF"
    assert row["fantasy_position"] == "QB"


def test_standardize_nflverse_identity_normalized_shape_passes_through() -> None:
    normalized = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "sleeper_player_id": None,
                "gsis_id": "00-1",
                "player_name": "Josh Allen",
                "position": "QB",
                "nfl_team": "BUF",
            }
        ]
    )

    frame = standardize_nflverse_identity(normalized)

    assert frame.iloc[0]["gsis_id"] == "00-1"
    assert frame.iloc[0]["player_name"] == "Josh Allen"
    assert frame.iloc[0]["nfl_team"] == "BUF"


def test_name_match_toy_example_matches_docstring(
    toy_name_catalog, toy_name_stats
) -> None:
    matches = build_name_match_crosswalk(toy_name_catalog, toy_name_stats)

    assert list(matches.columns) == NAME_MATCH_COLUMNS
    assert list(matches["gsis_id"]) == ["00-1", "00-2"]
    by_gsis = matches.set_index("gsis_id")
    assert by_gsis.loc["00-1", "sleeper_player_id"] == "13324"
    assert by_gsis.loc["00-1", "match_method"] == "first_name_prefix"
    # Sleeper's own name/position/team are reported.
    assert by_gsis.loc["00-1", "full_name"] == "Matt Hibner"
    assert by_gsis.loc["00-2", "sleeper_player_id"] == "13545"
    assert by_gsis.loc["00-2", "match_method"] == "exact_name"


def test_name_match_second_sleeper_namesake_leaves_both_unmapped(
    toy_name_catalog, toy_name_stats
) -> None:
    toy_name_catalog["99999"] = _catalog_player("99999", "Trey Smack", "K", "GB")

    matches = build_name_match_crosswalk(toy_name_catalog, toy_name_stats)

    assert list(matches["gsis_id"]) == ["00-1"]


def test_name_match_second_nflverse_namesake_leaves_both_unmapped(
    toy_name_catalog,
) -> None:
    stats = pd.DataFrame(
        [
            _nflverse_row("00-2", "Trey Smack", "K", "GB"),
            _nflverse_row("00-3", "Trey Smack", "K", "GB"),
        ]
    )

    assert build_name_match_crosswalk(toy_name_catalog, stats).empty


def test_name_match_already_mapped_namesake_still_counts_as_ambiguous(
    toy_name_catalog, toy_name_stats
) -> None:
    # A second Sleeper "Trey Smack" K GB that the crosswalk already maps to
    # someone else: the key is still ambiguous, so the unmapped one is not
    # guessed at.
    toy_name_catalog["99999"] = _catalog_player("99999", "Trey Smack", "K", "GB")
    crosswalk = pd.DataFrame(
        [["99999", "00-9", "Trey Smack", "K", "GB"]], columns=CROSSWALK_COLUMNS
    )

    matches = build_name_match_crosswalk(toy_name_catalog, toy_name_stats, crosswalk)

    assert "00-2" not in set(matches["gsis_id"])


def test_name_match_never_overrides_the_crosswalk(
    toy_name_catalog, toy_name_stats
) -> None:
    crosswalk = pd.DataFrame(
        [
            ["13324", "00-7", "Matt Hibner", "TE", "BAL"],  # Sleeper id mapped
            ["55555", "00-2", "Someone", "K", "GB"],  # gsis id mapped
        ],
        columns=CROSSWALK_COLUMNS,
    )

    assert build_name_match_crosswalk(toy_name_catalog, toy_name_stats, crosswalk).empty


def test_name_match_respects_a_conflicting_catalog_gsis_id(toy_name_stats) -> None:
    catalog = {
        "13545": _catalog_player("13545", "Trey Smack", "K", "GB", gsis_id="00-8")
    }

    assert build_name_match_crosswalk(catalog, toy_name_stats).empty


@pytest.mark.parametrize(
    ("sleeper_position", "sleeper_team"),
    [("K", "DAL"), ("P", "GB"), ("K", None)],
)
def test_name_match_requires_same_position_and_team(
    toy_name_stats, sleeper_position, sleeper_team
) -> None:
    catalog = {
        "13545": _catalog_player("13545", "Trey Smack", sleeper_position, sleeper_team)
    }

    assert build_name_match_crosswalk(catalog, toy_name_stats).empty


def test_name_match_normalizes_team_and_fullback() -> None:
    # Sleeper "LAR" is nflverse "LA"; nflverse "FB" is Sleeper "RB".
    catalog = {"1": _catalog_player("1", "Big Back", "RB", "LAR")}
    stats = pd.DataFrame([_nflverse_row("00-1", "Big Back", "FB", "LA")])

    matches = build_name_match_crosswalk(catalog, stats)

    assert list(matches["sleeper_player_id"]) == ["1"]


def test_name_match_first_name_prefix_needs_minimum_length() -> None:
    assert MIN_FIRST_NAME_PREFIX == 3
    catalog = {"1": _catalog_player("1", "Al Jones", "WR", "SEA")}
    stats = pd.DataFrame([_nflverse_row("00-1", "Albert Jones", "WR", "SEA")])

    assert build_name_match_crosswalk(catalog, stats).empty


def test_name_match_uses_the_latest_nflverse_row() -> None:
    # Traded mid-season: only his latest team should be compared.
    catalog = {"1": _catalog_player("1", "Moving Man", "WR", "DAL")}
    stats = pd.DataFrame(
        [
            _nflverse_row("00-1", "Moving Man", "WR", "NYJ", season=2026, week=1),
            _nflverse_row("00-1", "Moving Man", "WR", "DAL", season=2026, week=3),
        ]
    )

    assert list(build_name_match_crosswalk(catalog, stats)["gsis_id"]) == ["00-1"]


def test_name_match_empty_inputs(toy_name_catalog, toy_name_stats) -> None:
    assert (
        list(build_name_match_crosswalk(toy_name_catalog, pd.DataFrame()).columns)
        == NAME_MATCH_COLUMNS
    )
    assert build_name_match_crosswalk({}, toy_name_stats).empty


def test_extend_crosswalk_with_name_matches_appends_only_new_rows(
    toy_name_catalog, toy_name_stats
) -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    extended = extend_crosswalk_with_name_matches(
        crosswalk, toy_name_catalog, toy_name_stats
    )

    assert list(extended.columns) == CROSSWALK_COLUMNS
    assert len(extended) == len(crosswalk) + 2
    assert extended.iloc[: len(crosswalk)].equals(crosswalk)
    assert gsis_to_sleeper_lookup(extended)["00-1"] == "13324"


def test_extend_crosswalk_with_no_matches_returns_input(toy_name_catalog) -> None:
    crosswalk = build_id_crosswalk(PLAYER_CATALOG)

    extended = extend_crosswalk_with_name_matches(
        crosswalk, toy_name_catalog, pd.DataFrame()
    )

    assert extended is crosswalk


def test_build_robust_id_crosswalk_applies_name_fallback_when_given_stats(
    monkeypatch, id_crosswalk_fixture_path, toy_name_catalog, toy_name_stats
) -> None:
    import fantasy_analyzer.players.id_crosswalk_cache as id_cache

    raw_ids = pd.read_csv(id_crosswalk_fixture_path, low_memory=False)
    monkeypatch.setattr(
        id_cache, "get_player_ids_cached", lambda *args, **kwargs: raw_ids
    )

    without = build_robust_id_crosswalk(toy_name_catalog)
    with_stats = build_robust_id_crosswalk(
        toy_name_catalog, nflverse_stats=toy_name_stats
    )

    assert "00-1" not in set(without["gsis_id"])
    assert len(with_stats) == len(without) + 2
    assert sleeper_to_gsis_lookup(with_stats)["13545"] == "00-2"
