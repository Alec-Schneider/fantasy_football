"""Tests for snap-count/expected-points usage player-weeks (FFA-110).

No network: the raw sources come from sanitized fixtures
(``tests/fixtures/nflverse/snap_counts.csv``,
``tests/fixtures/ffopportunity/ep_weekly.csv``), and the ID crosswalk and
player stats are small in-test frames. ``ep_weekly.csv`` uses ffopportunity's
real 159-column header with toy values, so the passthrough column lists are
checked against the live schema. ``ep_weekly_real_sample.csv`` holds three
verbatim 2026 week-1 rows, used only to pin the documented full-PPR scoring.

The snap fixture's cast, by pfr id:

- ``QbxxAa00``/``WrxxBb00``/``RbxxCc00``/``TexxEe00``/``OlxxFf00``: AAA,
  crosswalk-mapped. AAA's week-1 total is exactly 60 (two 100% players).
- ``WrxxDd00`` "D.J. Delta Jr.": no crosswalk entry; name-matches stats row
  "DJ Delta" in week 1 and has snaps but no stats row in week 2.
- ``WrxxMm01`` "Mike Mapped": name-matches a stats row whose GSIS id the
  crosswalk already gave to ``WrxxMm00``, so it must stay unmapped.
- ``TexxKk00``: two different GSIS ids in the crosswalk, so dropped.
- ``DbxxNn00``: two different players sharing one pfr id in week 1.
- BBB has no 100% player: true total 57 (see the hand check below).
- ``WrxxJj00`` "Juliet Twin": two stats rows share his name, so ambiguous.
- ``WrxxOo00``: 2019 ``OAK``, which must come out as ``LV``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fantasy_analyzer.players.ros_backtest import build_scored_player_weeks
from fantasy_analyzer.players.usage import (
    EXPECTED_POINTS_COLUMNS,
    EXPECTED_POINTS_TEAM_COLUMNS,
    SNAP_COUNT_COLUMNS,
    SNAP_ID_SOURCE_CROSSWALK,
    SNAP_ID_SOURCE_NAME_FALLBACK,
    USAGE_IDENTITY_COLUMNS,
    attach_usage,
    build_pfr_to_gsis_lookup,
    load_usage_player_weeks,
    normalize_expected_points,
    normalize_snap_counts,
    regular_season_last_week,
    unmapped_snap_players,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
SNAP_FIXTURE = FIXTURES_DIR / "nflverse" / "snap_counts.csv"
EP_FIXTURE = FIXTURES_DIR / "ffopportunity" / "ep_weekly.csv"
EP_REAL_SAMPLE = FIXTURES_DIR / "ffopportunity" / "ep_weekly_real_sample.csv"


@pytest.fixture
def raw_snaps() -> pd.DataFrame:
    return pd.read_csv(SNAP_FIXTURE)


@pytest.fixture
def raw_ep() -> pd.DataFrame:
    return pd.read_csv(EP_FIXTURE)


@pytest.fixture
def player_ids() -> pd.DataFrame:
    """A DynastyProcess-shaped crosswalk (only the columns this module reads)."""
    pairs = [
        ("QbxxAa00", "00-0000001"),
        ("QbxxAa00", "00-0000001"),  # a repeated identical pair counts once
        ("WrxxBb00", "00-0000002"),
        ("RbxxCc00", "00-0000003"),
        ("TexxEe00", "00-0000005"),
        ("OlxxFf00", "00-0000006"),
        ("QbxxGg00", "00-0000007"),
        ("WrxxHh00", "00-0000008"),
        ("RbxxIi00", "00-0000009"),
        ("TexxKk00", "00-0000020"),  # one pfr id, two gsis ids
        ("TexxKk00", "00-0000021"),
        ("WrxxMm00", "00-0000012"),  # claims Mike Mapped's gsis id
        ("WrxxOo00", "00-0000013"),
        (None, "00-0000040"),
        ("NoGsis00", None),
    ]
    return pd.DataFrame(pairs, columns=["pfr_id", "gsis_id"])


def _stat_row(week: int, gsis_id: str, name: str, team: str, position: str) -> dict:
    return {
        "season": 2025,
        "week": week,
        "season_type": "REG",
        "player_id": gsis_id,
        "player_display_name": name,
        "team": team,
        "position": position,
    }


@pytest.fixture
def player_stats() -> pd.DataFrame:
    """Raw nflverse-shaped weekly stats: identity columns only."""
    return pd.DataFrame(
        [
            _stat_row(1, "00-0000001", "Alpha Quarterback", "AAA", "QB"),
            _stat_row(1, "00-0000002", "Bravo Receiver", "AAA", "WR"),
            _stat_row(1, "00-0000003", "Charlie Back", "AAA", "RB"),
            _stat_row(1, "00-0000004", "DJ Delta", "AAA", "WR"),
            _stat_row(1, "00-0000012", "Mike Mapped", "AAA", "WR"),
            _stat_row(1, "00-0000007", "Golf Passer", "BBB", "QB"),
            _stat_row(1, "00-0000008", "Hotel Wideout", "BBB", "WR"),
            _stat_row(1, "00-0000009", "India Runner", "BBB", "RB"),
            _stat_row(1, "00-0000010", "Juliet Twin", "BBB", "WR"),
            _stat_row(1, "00-0000011", "Juliet Twin", "BBB", "WR"),
            _stat_row(2, "00-0000001", "Alpha Quarterback", "AAA", "QB"),
            _stat_row(2, "00-0000002", "Bravo Receiver", "AAA", "WR"),
        ]
    )


@pytest.fixture
def snaps(raw_snaps, player_ids, player_stats) -> pd.DataFrame:
    return normalize_snap_counts(raw_snaps, player_ids, player_stats=player_stats)


def _row(frame: pd.DataFrame, pfr_player_id: str, week: int = 1) -> pd.Series:
    match = frame[(frame["pfr_player_id"] == pfr_player_id) & (frame["week"] == week)]
    assert len(match) == 1, f"expected one row for {pfr_player_id} week {week}"
    return match.iloc[0]


# --------------------------------------------------------------------------
# regular_season_last_week / build_pfr_to_gsis_lookup
# --------------------------------------------------------------------------


def test_regular_season_is_17_weeks_before_2021_and_18_after() -> None:
    assert regular_season_last_week(2020) == 17
    assert regular_season_last_week(2021) == 18
    assert regular_season_last_week(2026) == 18


def test_pfr_lookup_keeps_only_one_to_one_pairs(player_ids) -> None:
    conflict_on_gsis = pd.DataFrame(
        [("RbxxPp00", "00-0000030"), ("RbxxPq00", "00-0000030")],
        columns=["pfr_id", "gsis_id"],
    )
    lookup = build_pfr_to_gsis_lookup(pd.concat([player_ids, conflict_on_gsis]))

    assert lookup["QbxxAa00"] == "00-0000001"
    assert lookup["WrxxMm00"] == "00-0000012"
    assert "TexxKk00" not in lookup  # one pfr id, two gsis ids
    assert "RbxxPp00" not in lookup and "RbxxPq00" not in lookup  # one gsis, two pfr
    assert "NoGsis00" not in lookup
    assert "00-0000040" not in lookup.values()


def test_pfr_lookup_is_empty_without_the_id_columns() -> None:
    assert build_pfr_to_gsis_lookup(pd.DataFrame({"name": ["x"]})) == {}


# --------------------------------------------------------------------------
# normalize_snap_counts
# --------------------------------------------------------------------------


def test_snap_columns_and_regular_season_default(snaps) -> None:
    assert list(snaps.columns) == SNAP_COUNT_COLUMNS
    assert 19 not in set(snaps["week"])
    assert not snaps.duplicated(["season", "week", "pfr_player_id"]).any()


def test_postseason_is_kept_when_asked(raw_snaps, player_ids) -> None:
    result = normalize_snap_counts(raw_snaps, player_ids, regular_season_only=False)
    assert _row(result, "QbxxAa00", week=19)["offense_snaps"] == 70


def test_team_total_is_exact_when_someone_played_every_snap(snaps) -> None:
    """AAA week 1: two players at offense_pct 1.0 with 60 snaps, so 60 exactly.

    Bravo: 45 / 60 = 0.75. Echo played only special teams: a real 0.0.
    """
    bravo = _row(snaps, "WrxxBb00")
    assert bravo["team_offense_snaps"] == 60
    assert bravo["offense_snap_pct"] == pytest.approx(0.75)

    echo = _row(snaps, "TexxEe00")
    assert echo["offense_snaps"] == 0
    assert echo["offense_snap_pct"] == 0.0
    assert echo["gsis_id"] == "00-0000005"


def test_team_total_is_estimated_when_nobody_played_every_snap(snaps) -> None:
    """BBB week 1 has no 100% player, and its true total is 57.

    Hand check over players at 50%+ (Juliet at 0.21 is excluded):
    55 / 0.96 = 57.29, 50 / 0.88 = 56.82, 29 / 0.51 = 56.86. The median is
    56.86, which rounds to 57, above the team maximum of 55. So the QB's share
    is 55 / 57 = 0.965, not the 1.0 a "team max" rule would give.
    """
    golf = _row(snaps, "QbxxGg00")
    assert golf["team_offense_snaps"] == 57
    assert golf["offense_snap_pct"] == pytest.approx(55 / 57)
    assert _row(snaps, "WrxxJj00")["team_offense_snaps"] == 57


def test_relocated_franchise_codes_become_current_codes(snaps) -> None:
    oscar = snaps[snaps["pfr_player_id"] == "WrxxOo00"].iloc[0]
    assert oscar["team"] == "LV"
    assert oscar["season"] == 2019
    assert oscar["gsis_id"] == "00-0000013"


def test_pfr_id_shared_by_two_players_in_a_week_is_dropped(snaps) -> None:
    assert "DbxxNn00" not in set(snaps["pfr_player_id"])


def test_crosswalk_rows_are_labelled(snaps) -> None:
    alpha = _row(snaps, "QbxxAa00")
    assert alpha["gsis_id"] == "00-0000001"
    assert alpha["snap_id_source"] == SNAP_ID_SOURCE_CROSSWALK


def test_name_fallback_maps_every_week_of_a_matched_pfr_id(snaps) -> None:
    """Week 1 matches "D.J. Delta Jr." to "DJ Delta" on name, team and group.

    Week 2 has snaps but no stats row; it is mapped too, because the pfr id's
    identity was established in week 1.
    """
    week1 = _row(snaps, "WrxxDd00", week=1)
    week2 = _row(snaps, "WrxxDd00", week=2)
    assert week1["gsis_id"] == week2["gsis_id"] == "00-0000004"
    assert week1["snap_id_source"] == SNAP_ID_SOURCE_NAME_FALLBACK
    assert week2["snap_id_source"] == SNAP_ID_SOURCE_NAME_FALLBACK


def test_ambiguous_name_match_stays_unmapped(snaps) -> None:
    juliet = _row(snaps, "WrxxJj00")
    assert pd.isna(juliet["gsis_id"])
    assert pd.isna(juliet["snap_id_source"])


def test_fallback_never_reuses_a_gsis_id_the_crosswalk_assigned(snaps) -> None:
    assert pd.isna(_row(snaps, "WrxxMm01")["gsis_id"])


def test_crosswalk_conflict_stays_unmapped(snaps) -> None:
    assert pd.isna(_row(snaps, "TexxKk00")["gsis_id"])


def test_no_player_stats_means_no_fallback(raw_snaps, player_ids) -> None:
    result = normalize_snap_counts(raw_snaps, player_ids)
    assert pd.isna(_row(result, "WrxxDd00")["gsis_id"])
    assert SNAP_ID_SOURCE_NAME_FALLBACK not in set(result["snap_id_source"].dropna())


def test_fallback_needs_offense_snaps(raw_snaps, player_ids, player_stats) -> None:
    """A pfr id with zero offensive snaps is never name-matched."""
    no_offense = raw_snaps.copy()
    delta = no_offense["pfr_player_id"] == "WrxxDd00"
    no_offense.loc[delta, ["offense_snaps", "offense_pct"]] = 0

    result = normalize_snap_counts(no_offense, player_ids, player_stats=player_stats)
    assert pd.isna(_row(result, "WrxxDd00")["gsis_id"])


def test_empty_snap_input_returns_empty_frame(player_ids) -> None:
    result = normalize_snap_counts(pd.DataFrame(), player_ids)
    assert result.empty
    assert list(result.columns) == SNAP_COUNT_COLUMNS


def test_unmapped_summary_lists_only_offensive_players(snaps) -> None:
    summary = unmapped_snap_players(snaps)

    assert list(summary["pfr_player_id"]) == ["WrxxJj00", "TexxKk00", "WrxxMm01"]
    assert list(summary["offense_snaps"]) == [12, 8, 5]


def test_unmapped_summary_of_nothing_is_empty() -> None:
    assert unmapped_snap_players(pd.DataFrame()).empty


# --------------------------------------------------------------------------
# normalize_expected_points
# --------------------------------------------------------------------------


def test_every_passthrough_column_exists_in_the_live_schema(raw_ep) -> None:
    """The fixture's header is ffopportunity's real 159-column header."""
    assert len(raw_ep.columns) == 159
    missing = set(EXPECTED_POINTS_COLUMNS + EXPECTED_POINTS_TEAM_COLUMNS) - set(
        raw_ep.columns
    )
    assert not missing


def test_every_player_level_exp_column_is_passed_through_with_prefix(raw_ep) -> None:
    result = normalize_expected_points(raw_ep)

    player_exp = [
        column
        for column in raw_ep.columns
        if column.endswith("_exp") and not column.endswith("_team")
    ]
    assert player_exp  # sanity: the header really has them
    for column in player_exp:
        assert f"ep_{column}" in result.columns
    for column in (
        "ep_pass_attempt",
        "ep_rec_attempt",
        "ep_rush_attempt",
        "ep_total_fantasy_points",
        "ep_total_fantasy_points_exp",
        "ep_total_fantasy_points_exp_team",
    ):
        assert column in result.columns
    assert not [column for column in result.columns if column.endswith("_diff")]


def test_expected_points_drops_null_players_postseason_and_duplicate_keys(
    raw_ep,
) -> None:
    result = normalize_expected_points(raw_ep)

    assert result["gsis_id"].notna().all()
    assert 19 not in set(result["week"])
    assert "00-0000099" not in set(result["gsis_id"])
    assert not result.duplicated(["season", "week", "gsis_id"]).any()


def test_expected_points_values_and_labels(raw_ep) -> None:
    result = normalize_expected_points(raw_ep)
    bravo = result[(result["gsis_id"] == "00-0000002") & (result["week"] == 1)].iloc[0]

    assert bravo["team"] == "AAA"
    assert bravo["player_name"] == "Bravo Receiver"
    assert bravo["ep_rec_attempt"] == 8
    assert bravo["ep_receptions_exp"] == pytest.approx(5.5)
    assert bravo["ep_total_fantasy_points_exp"] == pytest.approx(15.5)


def test_expected_points_postseason_kept_when_asked(raw_ep) -> None:
    result = normalize_expected_points(raw_ep, regular_season_only=False)
    assert 19 in set(result["week"])


def test_expected_points_of_nothing_is_empty() -> None:
    assert normalize_expected_points(pd.DataFrame()).empty


def test_ffopportunity_fantasy_points_are_full_ppr() -> None:
    """Pins the module docstring's scoring claim on three real 2026 rows.

    Trey McBride, week 1: 9 receptions, 95 yards, 1 TD.
    Full PPR: 9 + 9.5 + 6 = 24.5, matching ``total_fantasy_points``. Half PPR
    would be 20.0.
    """
    real = pd.read_csv(EP_REAL_SAMPLE).fillna(0)

    def points(row: pd.Series, per_reception: float) -> float:
        return (
            0.04 * row["pass_yards_gained"]
            + 4 * row["pass_touchdown"]
            - 2 * row["pass_interception"]
            + 0.1 * (row["rush_yards_gained"] + row["rec_yards_gained"])
            + 6 * (row["rush_touchdown"] + row["rec_touchdown"])
            + per_reception * row["receptions"]
            + 2
            * (
                row["pass_two_point_conv"]
                + row["rush_two_point_conv"]
                + row["rec_two_point_conv"]
            )
            - 2 * (row["rush_fumble_lost"] + row["rec_fumble_lost"])
        )

    for _, row in real.iterrows():
        assert points(row, 1.0) == pytest.approx(row["total_fantasy_points"], abs=0.01)

    mcbride = real[real["full_name"] == "Trey McBride"].iloc[0]
    assert points(mcbride, 0.5) != pytest.approx(mcbride["total_fantasy_points"])

    # The expected columns use the same weights (no fumble expectation):
    exp = (
        mcbride["receptions_exp"]
        + 0.1 * mcbride["rec_yards_gained_exp"]
        + 6 * mcbride["rec_touchdown_exp"]
        + 2 * mcbride["rec_two_point_conv_exp"]
    )
    assert exp == pytest.approx(mcbride["rec_fantasy_points_exp"], abs=0.07)


# --------------------------------------------------------------------------
# load_usage_player_weeks
# --------------------------------------------------------------------------


@pytest.fixture
def cache_dirs(tmp_path, raw_snaps, raw_ep, player_ids, player_stats) -> dict:
    """Per-season cache files laid out the way the fetch script writes them."""
    dirs = {
        "snap_cache_dir": tmp_path / "nflverse",
        "ep_cache_dir": tmp_path / "ffopportunity",
        "player_ids_cache_dir": tmp_path / "id_crosswalk",
        "stats_cache_dir": tmp_path / "nflverse",
    }
    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    for season in (2019, 2025):
        raw_snaps[raw_snaps["season"] == season].to_csv(
            dirs["snap_cache_dir"] / f"snap_counts_{season}.csv", index=False
        )
        raw_ep[raw_ep["season"] == season].to_csv(
            dirs["ep_cache_dir"] / f"ep_weekly_{season}.csv", index=False
        )
        player_stats[player_stats["season"] == season].to_csv(
            dirs["stats_cache_dir"] / f"player_stats_{season}.csv", index=False
        )
    player_ids.to_csv(dirs["player_ids_cache_dir"] / "db_playerids.csv", index=False)
    return dirs


@pytest.fixture
def usage(cache_dirs) -> pd.DataFrame:
    return load_usage_player_weeks([2025], **cache_dirs)


def _usage_row(usage: pd.DataFrame, gsis_id: str, week: int = 1) -> pd.Series:
    match = usage[(usage["gsis_id"] == gsis_id) & (usage["week"] == week)]
    assert len(match) == 1
    return match.iloc[0]


def test_usage_is_one_row_per_player_week_with_contract_columns(usage) -> None:
    assert list(usage.columns[: len(USAGE_IDENTITY_COLUMNS)]) == USAGE_IDENTITY_COLUMNS
    assert all(
        column.startswith("ep_")
        for column in usage.columns[len(USAGE_IDENTITY_COLUMNS) :]
    )
    assert not usage.duplicated(["season", "week", "gsis_id"]).any()
    assert usage["gsis_id"].notna().all()
    assert set(usage["season"]) == {2025}
    assert 19 not in set(usage["week"])


def test_usage_outer_joins_the_two_sources(usage) -> None:
    both = _usage_row(usage, "00-0000002")
    assert both["offense_snaps"] == 45
    assert both["ep_rec_attempt"] == 8

    snap_only = _usage_row(usage, "00-0000005")  # special-teams-only week
    assert snap_only["offense_snaps"] == 0
    assert np.isnan(snap_only["ep_rec_attempt"])

    ep_only = _usage_row(usage, "00-0000014")
    assert np.isnan(ep_only["offense_snaps"])
    assert pd.isna(ep_only["snap_id_source"])
    assert ep_only["team"] == "AAA"
    assert ep_only["ep_rec_attempt"] == 1


def test_zero_usage_snap_week_is_in_the_universe(usage) -> None:
    """D.J. Delta's week 2: 16 snaps, no stats row, no ep row. Kept, not zeroed."""
    week2 = _usage_row(usage, "00-0000004", week=2)
    assert week2["offense_snaps"] == 16
    assert week2["offense_snap_pct"] == pytest.approx(0.25)
    assert np.isnan(week2["ep_total_fantasy_points_exp"])


def test_usage_labels_prefer_nflverse_vocabulary(usage) -> None:
    charlie = _usage_row(usage, "00-0000003")
    assert charlie["position"] == "RB"  # ep's label, not PFR's "HB"

    delta = _usage_row(usage, "00-0000004")
    assert delta["player_name"] == "DJ Delta"
    assert delta["pfr_player_id"] == "WrxxDd00"


def test_unmapped_snap_rows_are_not_in_usage(usage) -> None:
    assert not {"WrxxJj00", "WrxxMm01", "TexxKk00"} & set(
        usage["pfr_player_id"].dropna()
    )


def test_usage_across_seasons_applies_team_aliases(cache_dirs) -> None:
    usage = load_usage_player_weeks([2025, 2019], **cache_dirs)
    oscar = _usage_row(usage, "00-0000013")

    assert set(usage["season"]) == {2019, 2025}
    assert oscar["team"] == "LV"
    assert oscar["ep_rec_attempt"] == 5
    assert list(usage["season"]) == sorted(usage["season"])


def test_explicit_player_ids_override_the_cache(cache_dirs, player_ids) -> None:
    without_bravo = player_ids[player_ids["pfr_id"] != "WrxxBb00"]
    usage = load_usage_player_weeks(
        [2025], **cache_dirs, player_ids=without_bravo, name_fallback=False
    )
    bravo = _usage_row(usage, "00-0000002")
    assert np.isnan(bravo["offense_snaps"])  # no snap row placed; ep row remains


def test_never_fetched_season_raises(cache_dirs) -> None:
    with pytest.raises(FileNotFoundError, match="2024"):
        load_usage_player_weeks([2024], **cache_dirs)


def test_unpublished_season_contributes_no_rows(cache_dirs) -> None:
    """A season the fetch script cached from a 404 is an empty file."""
    pd.DataFrame().to_csv(
        cache_dirs["snap_cache_dir"] / "snap_counts_2012.csv", index=False
    )
    pd.DataFrame().to_csv(
        cache_dirs["ep_cache_dir"] / "ep_weekly_2012.csv", index=False
    )

    usage = load_usage_player_weeks([2012], **cache_dirs, name_fallback=False)
    assert usage.empty
    assert list(usage.columns[: len(USAGE_IDENTITY_COLUMNS)]) == USAGE_IDENTITY_COLUMNS


def test_missing_crosswalk_cache_raises(cache_dirs, tmp_path) -> None:
    dirs = {**cache_dirs, "player_ids_cache_dir": tmp_path / "nowhere"}
    with pytest.raises(FileNotFoundError, match="crosswalk"):
        load_usage_player_weeks([2025], **dirs)


# --------------------------------------------------------------------------
# attach_usage
# --------------------------------------------------------------------------


def _raw_stats_for_scoring() -> pd.DataFrame:
    """Raw nflverse-shaped rows for build_scored_player_weeks."""
    rows = [
        ("00-0000002", "Bravo Receiver", "WR", 1, 6, 80, 1),
        ("00-0000004", "DJ Delta", "WR", 1, 2, 25, 0),
        ("00-0000077", "No Usage Rows", "WR", 1, 1, 9, 0),
        ("00-0000002", "Bravo Receiver", "WR", 2, 7, 90, 0),
    ]
    return pd.DataFrame(
        [
            {
                "season": 2025,
                "week": week,
                "season_type": "REG",
                "player_id": gsis,
                "player_display_name": name,
                "position": position,
                "team": "AAA",
                "receptions": receptions,
                "receiving_yards": yards,
                "receiving_tds": tds,
            }
            for gsis, name, position, week, receptions, yards, tds in rows
        ]
    )


def test_attach_usage_to_scored_player_weeks(usage) -> None:
    """build_scored_player_weeks names its id column ``player_id`` (a GSIS id)."""
    scored = build_scored_player_weeks(
        [_raw_stats_for_scoring()], {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6}
    )
    assert "player_id" in scored.columns and "gsis_id" not in scored.columns

    result = attach_usage(scored, usage)

    assert len(result) == len(scored)
    assert list(result["player_id"]) == list(scored["player_id"])
    assert list(result.columns[: len(scored.columns)]) == list(scored.columns)

    bravo = result[(result["player_id"] == "00-0000002") & (result["week"] == 1)].iloc[
        0
    ]
    assert bravo["fantasy_points"] == pytest.approx(0.5 * 6 + 8.0 + 6)
    assert bravo["offense_snap_pct"] == pytest.approx(0.75)
    assert bravo["ep_total_fantasy_points_exp"] == pytest.approx(15.5)
    assert bravo["team"] == "AAA"  # the stat frame's own column, untouched

    nobody = result[result["player_id"] == "00-0000077"].iloc[0]
    assert np.isnan(nobody["offense_snaps"])  # no source row: NaN, not zero
    assert np.isnan(nobody["ep_rec_attempt"])


def test_attach_usage_with_another_id_column_and_float_keys(usage) -> None:
    frame = pd.DataFrame(
        {"season": [2025.0], "week": [1.0], "gsis_id": ["00-0000003"], "x": [1]}
    )
    result = attach_usage(frame, usage, player_id_column="gsis_id")

    assert result.iloc[0]["offense_snaps"] == 30
    assert result.iloc[0]["ep_rush_attempt"] == 15
    assert "player_name" not in result.columns
    assert "position" not in result.columns


def test_attach_usage_keeps_rows_with_a_missing_id(usage) -> None:
    frame = pd.DataFrame({"season": [2025], "week": [1], "player_id": [None]})
    result = attach_usage(frame, usage)

    assert len(result) == 1
    assert np.isnan(result.iloc[0]["offense_snaps"])


def test_attach_usage_requires_the_key_columns(usage) -> None:
    with pytest.raises(KeyError, match="player_id"):
        attach_usage(pd.DataFrame({"season": [2025], "week": [1]}), usage)


def test_attach_usage_refuses_to_attach_twice(usage) -> None:
    frame = pd.DataFrame({"season": [2025], "week": [1], "player_id": ["00-0000002"]})
    once = attach_usage(frame, usage)

    with pytest.raises(ValueError, match="offense_snaps"):
        attach_usage(once, usage)
