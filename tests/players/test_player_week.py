"""Tests for the player-week fantasy fact table (FFA-064).

All tests operate on the pure, no-network :func:`build_player_week_fact_table`
against hand-built ``WeekMatchups``/``teams_df``/``players_df`` inputs and an
in-memory fake :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`
(mirroring ``tests/players/test_provider.py``'s ``FakePlayerStatsProvider``),
so every expected ``fantasy_points`` value can be verified by hand per
AGENTS.md's analytics-ticket requirement for a hand-checkable toy example.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.matchups import WeekMatchups
from fantasy_analyzer.players import (
    PLAYER_WEEK_COLUMNS,
    PLAYER_WEEK_IDENTITY_COLUMNS,
    PlayerWeekFactTable,
    build_league_wide_player_week_fact_table,
    build_player_week_fact_table,
)

#: A representative, partially-unsupported scoring block: pass_yd/pass_td/
#: rec/rec_yd are all mapped (see ``players.scoring``), bonus_rec_te is
#: deliberately not, so tests can assert it is surfaced rather than dropped.
SCORING_SETTINGS = {
    "pass_yd": 0.04,
    "pass_td": 4,
    "rec": 0.5,
    "rec_yd": 0.1,
    "bonus_rec_te": 0.5,
}


class FakePlayerStatsProvider:
    """A minimal in-memory ``PlayerStatsProvider`` (mirrors ``test_provider.py``)."""

    def __init__(self, rows: list[dict], stat_columns: list[str]) -> None:
        columns = PLAYER_WEEK_IDENTITY_COLUMNS + stat_columns
        self._df = pd.DataFrame(rows, columns=columns)
        self.calls: list[tuple[int, int]] = []

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        self.calls.append((season, week))
        matches = self._df[(self._df["season"] == season) & (self._df["week"] == week)]
        return matches.reset_index(drop=True)


def _teams_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["roster_id", "owner_id", "display_name", "team_name"]
    return pd.DataFrame(rows, columns=columns)


def _players_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["player_id", "full_name", "position", "team"]
    return pd.DataFrame(rows, columns=columns)


TEAMS_DF = _teams_df(
    [
        {"roster_id": 1, "owner_id": "u1", "display_name": "Alec", "team_name": "Alec"},
        {"roster_id": 2, "owner_id": "u2", "display_name": "Mike", "team_name": "Mike"},
        {"roster_id": 3, "owner_id": "u3", "display_name": "Sam", "team_name": "Sam"},
    ]
)

#: Identity-fallback catalog: "1001" (bench player with no nflverse match)
#: resolves here; "1003" is deliberately absent from both sources to
#: exercise the fully-unresolvable case.
PLAYERS_DF = _players_df(
    [
        {"player_id": "1001", "full_name": "Bench Guy", "position": "RB", "team": "SF"},
    ]
)

STAT_COLUMNS = ["passing_yards", "passing_tds", "receptions", "receiving_yards"]

WEEK_ONE_STATS_ROWS = [
    {
        "season": 2025,
        "week": 1,
        "sleeper_player_id": "1000",
        "gsis_id": "00-1000",
        "player_name": "Josh Allen",
        "position": "QB",
        "nfl_team": "BUF",
        "passing_yards": 300,
        "passing_tds": 3,
        "receptions": 0,
        "receiving_yards": 0,
    },
    {
        "season": 2025,
        "week": 1,
        "sleeper_player_id": "1002",
        "gsis_id": "00-1002",
        "player_name": "Some WR",
        "position": "WR",
        "nfl_team": "MIA",
        "passing_yards": 0,
        "passing_tds": 0,
        "receptions": 5,
        "receiving_yards": 60,
    },
    # No row for "1001" (bench) or "1003" -- both DNP/bye/no-data cases.
]

WEEK_TWO_STATS_ROWS = [
    {
        "season": 2025,
        "week": 2,
        "sleeper_player_id": "2000",
        "gsis_id": "00-2000",
        "player_name": "Bye Week Guy",
        "position": "QB",
        "nfl_team": "SEA",
        "passing_yards": 200,
        "passing_tds": 1,
        "receptions": 0,
        "receiving_yards": 0,
    },
]


def _week_one() -> WeekMatchups:
    return WeekMatchups(
        season="2025",
        week=1,
        is_playoff=False,
        matchups=[
            {
                "roster_id": 1,
                "matchup_id": 1,
                "points": 24.0,
                "starters": ["1000"],
                "players": ["1000", "1001"],
            },
            {
                "roster_id": 2,
                "matchup_id": 1,
                "points": 8.5,
                "starters": ["1002"],
                "players": ["1002", "1003"],
            },
        ],
    )


def _week_two_bye() -> WeekMatchups:
    """A single, unpaired (matchup_id=None) bye entry for roster 3."""
    return WeekMatchups(
        season="2025",
        week=2,
        is_playoff=False,
        matchups=[
            {
                "roster_id": 3,
                "matchup_id": None,
                "points": 20.0,
                "starters": ["2000"],
                "players": ["2000"],
            }
        ],
    )


@pytest.fixture
def provider() -> FakePlayerStatsProvider:
    return FakePlayerStatsProvider(
        WEEK_ONE_STATS_ROWS + WEEK_TWO_STATS_ROWS, STAT_COLUMNS
    )


# -------------------------
# Happy path / hand-checkable toy example
# -------------------------


def test_toy_example_multi_roster_multi_week(
    provider: FakePlayerStatsProvider,
) -> None:
    """Hand-computed expectations for every row across two weeks.

    Week 1, roster 1: "1000" started, 300 passing_yards * 0.04 = 12.0, plus
    3 passing_tds * 4 = 12.0 -> 24.0 fantasy_points. "1001" benched, no
    provider stats -> 0.0.
    Week 1, roster 2: "1002" started, 5 receptions * 0.5 = 2.5, plus 60
    receiving_yards * 0.1 = 6.0 -> 8.5 fantasy_points. "1003" benched, no
    provider stats and no players_df fallback -> 0.0, all identity fields
    None.
    Week 2, roster 3 (a bye entry, matchup_id=None): "2000" started, 200
    passing_yards * 0.04 = 8.0, plus 1 passing_td * 4 = 4.0 -> 12.0.
    """
    result = build_player_week_fact_table(
        [_week_one(), _week_two_bye()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )

    assert isinstance(result, PlayerWeekFactTable)
    df = result.player_week_df
    assert list(df.columns[: len(PLAYER_WEEK_COLUMNS)]) == PLAYER_WEEK_COLUMNS
    assert list(df.columns)[-1] == "fantasy_points"
    assert len(df) == 5

    by_id = df.set_index("sleeper_player_id")

    row_1000 = by_id.loc["1000"]
    assert row_1000["season"] == 2025
    assert row_1000["week"] == 1
    assert row_1000["roster_id"] == 1
    assert row_1000["fantasy_team"] == "Alec"
    assert row_1000["player_name"] == "Josh Allen"
    assert row_1000["position"] == "QB"
    assert row_1000["nfl_team"] == "BUF"
    assert bool(row_1000["started"]) is True
    assert bool(row_1000["bench"]) is False
    assert row_1000["fantasy_points"] == pytest.approx(24.0)

    row_1002 = by_id.loc["1002"]
    assert row_1002["roster_id"] == 2
    assert row_1002["fantasy_team"] == "Mike"
    assert bool(row_1002["started"]) is True
    assert bool(row_1002["bench"]) is False
    assert row_1002["fantasy_points"] == pytest.approx(8.5)

    row_2000 = by_id.loc["2000"]
    assert row_2000["week"] == 2
    assert row_2000["roster_id"] == 3
    assert row_2000["fantasy_team"] == "Sam"
    assert bool(row_2000["started"]) is True
    assert row_2000["fantasy_points"] == pytest.approx(12.0)


# -------------------------
# started / bench detection
# -------------------------


def test_bench_player_is_flagged_started_false_bench_true(
    provider: FakePlayerStatsProvider,
) -> None:
    result = build_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    row = result.player_week_df.set_index("sleeper_player_id").loc["1001"]

    assert bool(row["started"]) is False
    assert bool(row["bench"]) is True


def test_started_and_bench_are_complementary_for_every_row(
    provider: FakePlayerStatsProvider,
) -> None:
    result = build_player_week_fact_table(
        [_week_one(), _week_two_bye()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    df = result.player_week_df

    assert (df["started"] != df["bench"]).all()


# -------------------------
# Rostered player with no provider stats (bye/inactive/DNP)
# -------------------------


def test_rostered_player_with_no_provider_stats_gets_a_zero_point_row_not_dropped(
    provider: FakePlayerStatsProvider,
) -> None:
    result = build_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    df = result.player_week_df

    assert "1001" in set(df["sleeper_player_id"])
    row = df.set_index("sleeper_player_id").loc["1001"]
    assert row["fantasy_points"] == pytest.approx(0.0)
    assert not pd.isna(row["fantasy_points"])
    for stat_column in STAT_COLUMNS:
        assert pd.isna(row[stat_column])


def test_bye_week_roster_entry_with_no_matchup_id_is_included(
    provider: FakePlayerStatsProvider,
) -> None:
    """A raw entry with matchup_id=None (Sleeper's bye convention) is still
    processed -- this module never inspects matchup_id at all."""
    result = build_player_week_fact_table(
        [_week_two_bye()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    df = result.player_week_df

    assert len(df) == 1
    assert df.iloc[0]["sleeper_player_id"] == "2000"
    assert df.iloc[0]["roster_id"] == 3


# -------------------------
# Identity fallback to players_df
# -------------------------


def test_identity_falls_back_to_players_df_when_provider_has_no_match(
    provider: FakePlayerStatsProvider,
) -> None:
    result = build_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    row = result.player_week_df.set_index("sleeper_player_id").loc["1001"]

    assert row["player_name"] == "Bench Guy"
    assert row["position"] == "RB"
    assert row["nfl_team"] == "SF"


def test_identity_stays_none_when_neither_source_has_a_match(
    provider: FakePlayerStatsProvider,
) -> None:
    """ "1003" has no provider row and no players_df row -- stays None, not raised."""
    result = build_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    row = result.player_week_df.set_index("sleeper_player_id").loc["1003"]

    assert pd.isna(row["player_name"])
    assert pd.isna(row["position"])
    assert pd.isna(row["nfl_team"])
    assert row["fantasy_points"] == pytest.approx(0.0)


def test_provider_identity_wins_over_players_df_when_both_have_a_match(
    provider: FakePlayerStatsProvider,
) -> None:
    """ "1000" is resolved by the provider (nflverse-shaped); players_df has
    no entry for it at all, proving the provider's own value is used
    directly rather than merely as a fallback trigger."""
    result = build_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    row = result.player_week_df.set_index("sleeper_player_id").loc["1000"]

    assert row["player_name"] == "Josh Allen"
    assert row["gsis_id"] == "00-1000"


# -------------------------
# unsupported_scoring_keys surfaced
# -------------------------


def test_unsupported_scoring_key_is_surfaced_on_the_result(
    provider: FakePlayerStatsProvider,
) -> None:
    result = build_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )

    assert result.unsupported_scoring_keys == ["bonus_rec_te"]


# -------------------------
# players list fallback when the raw entry has no "players" key
# -------------------------


def test_missing_players_key_falls_back_to_starters(
    provider: FakePlayerStatsProvider,
) -> None:
    """This repo's shared minimal fixture predates the "players" field --
    an entry with only "starters" still produces a (started) row for it."""
    week = WeekMatchups(
        season="2025",
        week=1,
        is_playoff=False,
        matchups=[
            {"roster_id": 5, "matchup_id": None, "points": 10.0, "starters": ["5000"]}
        ],
    )
    teams_df = _teams_df([{"roster_id": 5, "owner_id": "u5", "display_name": "Pat"}])

    result = build_player_week_fact_table(
        [week], teams_df, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    df = result.player_week_df

    assert len(df) == 1
    assert df.iloc[0]["sleeper_player_id"] == "5000"
    assert bool(df.iloc[0]["started"]) is True
    assert bool(df.iloc[0]["bench"]) is False


def test_real_matchups_fixture_produces_a_row_per_roster_player(
    load_sleeper_fixture, provider: FakePlayerStatsProvider
) -> None:
    """Integration check against the shared, now players-array-bearing fixture."""
    raw = load_sleeper_fixture("matchups.json")
    week = WeekMatchups(season="2025", week=1, is_playoff=False, matchups=raw)

    result = build_player_week_fact_table(
        [week], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    df = result.player_week_df

    assert set(df["sleeper_player_id"]) == {"1000", "1001", "1002", "1003"}
    assert set(df[df["roster_id"] == 1]["sleeper_player_id"]) == {"1000", "1001"}
    assert set(df[df["roster_id"] == 2]["sleeper_player_id"]) == {"1002", "1003"}


# -------------------------
# Empty input edge cases
# -------------------------


def test_empty_weeks_list_yields_empty_frame_with_expected_columns(
    provider: FakePlayerStatsProvider,
) -> None:
    result = build_player_week_fact_table(
        [], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )

    assert result.player_week_df.empty
    assert list(result.player_week_df.columns[: len(PLAYER_WEEK_COLUMNS)]) == (
        PLAYER_WEEK_COLUMNS
    )
    assert list(result.player_week_df.columns)[-1] == "fantasy_points"
    assert result.unsupported_scoring_keys == ["bonus_rec_te"]
    assert provider.calls == []


def test_week_with_empty_matchups_is_skipped_without_calling_the_provider(
    provider: FakePlayerStatsProvider,
) -> None:
    empty_week = WeekMatchups(season="2025", week=9, is_playoff=False, matchups=[])

    result = build_player_week_fact_table(
        [_week_one(), empty_week], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )

    assert (9, 9) not in provider.calls
    assert 9 not in set(result.player_week_df["week"])


def test_empty_roster_and_players_df_do_not_raise(
    provider: FakePlayerStatsProvider,
) -> None:
    result = build_player_week_fact_table(
        [_week_one()], _teams_df([]), _players_df([]), provider, SCORING_SETTINGS
    )

    assert len(result.player_week_df) == 4
    assert result.player_week_df["fantasy_team"].isna().all()


def test_week_with_entries_but_no_season_label_raises(
    provider: FakePlayerStatsProvider,
) -> None:
    week = WeekMatchups(
        season=None,
        week=1,
        is_playoff=False,
        matchups=[
            {"roster_id": 1, "matchup_id": 1, "points": 10.0, "starters": ["1000"]}
        ],
    )

    with pytest.raises(ValueError, match="season"):
        build_player_week_fact_table(
            [week], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
        )


def test_week_with_no_entries_and_no_season_label_is_skipped_without_raising(
    provider: FakePlayerStatsProvider,
) -> None:
    week = WeekMatchups(season=None, week=1, is_playoff=False, matchups=[])

    result = build_player_week_fact_table(
        [week], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )

    assert result.player_week_df.empty


# -------------------------
# build_league_wide_player_week_fact_table (also FFA-064)
# -------------------------

#: A free agent -- real week-1 provider stats, on nobody's roster.
#: 3 receptions * 0.5 + 40 receiving_yards * 0.1 = 1.5 + 4.0 = 5.5.
FREE_AGENT_ROW = {
    "season": 2025,
    "week": 1,
    "sleeper_player_id": "9999",
    "gsis_id": "00-9999",
    "player_name": "Waiver Wire Guy",
    "position": "RB",
    "nfl_team": "DAL",
    "passing_yards": 0,
    "passing_tds": 0,
    "receptions": 3,
    "receiving_yards": 40,
}

#: A provider row the crosswalk could not resolve to a Sleeper ID -- must
#: never surface as a row, rostered-only or league-wide.
UNRESOLVABLE_ROW = {
    "season": 2025,
    "week": 1,
    "sleeper_player_id": None,
    "gsis_id": "00-0000",
    "player_name": "No Crosswalk Match",
    "position": "WR",
    "nfl_team": "NYJ",
    "passing_yards": 0,
    "passing_tds": 0,
    "receptions": 2,
    "receiving_yards": 15,
}


@pytest.fixture
def league_wide_provider() -> FakePlayerStatsProvider:
    return FakePlayerStatsProvider(
        WEEK_ONE_STATS_ROWS
        + [FREE_AGENT_ROW, UNRESOLVABLE_ROW]
        + WEEK_TWO_STATS_ROWS,
        STAT_COLUMNS,
    )


def test_league_wide_includes_a_free_agent_with_correct_points(
    league_wide_provider: FakePlayerStatsProvider,
) -> None:
    result = build_league_wide_player_week_fact_table(
        [_week_one(), _week_two_bye()],
        TEAMS_DF,
        PLAYERS_DF,
        league_wide_provider,
        SCORING_SETTINGS,
    )
    df = result.player_week_df

    assert "9999" in set(df["sleeper_player_id"])
    row = df.set_index("sleeper_player_id").loc["9999"]
    assert pd.isna(row["roster_id"])
    assert pd.isna(row["fantasy_team"])
    assert bool(row["started"]) is False
    assert bool(row["bench"]) is False
    assert row["fantasy_points"] == pytest.approx(5.5)
    assert row["player_name"] == "Waiver Wire Guy"


def test_league_wide_drops_a_provider_row_with_no_resolvable_sleeper_id(
    league_wide_provider: FakePlayerStatsProvider,
) -> None:
    result = build_league_wide_player_week_fact_table(
        [_week_one(), _week_two_bye()],
        TEAMS_DF,
        PLAYERS_DF,
        league_wide_provider,
        SCORING_SETTINGS,
    )
    df = result.player_week_df

    assert "No Crosswalk Match" not in set(df["player_name"])
    assert not df["sleeper_player_id"].isna().any()


def test_league_wide_still_includes_every_rostered_player_row_unchanged(
    provider: FakePlayerStatsProvider,
    league_wide_provider: FakePlayerStatsProvider,
) -> None:
    """Rostered rows carry the identical roster context as the rostered-only
    builder -- the two functions diverge only in which extra rows are added."""
    rostered_only = build_player_week_fact_table(
        [_week_one(), _week_two_bye()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    league_wide = build_league_wide_player_week_fact_table(
        [_week_one(), _week_two_bye()],
        TEAMS_DF,
        PLAYERS_DF,
        league_wide_provider,
        SCORING_SETTINGS,
    )

    rostered_ids = set(rostered_only.player_week_df["sleeper_player_id"])
    league_wide_by_id = league_wide.player_week_df.set_index("sleeper_player_id")

    for player_id in rostered_ids:
        rostered_row = rostered_only.player_week_df.set_index(
            "sleeper_player_id"
        ).loc[player_id]
        wide_row = league_wide_by_id.loc[player_id]
        assert wide_row["roster_id"] == rostered_row["roster_id"]
        assert wide_row["fantasy_team"] == rostered_row["fantasy_team"]
        assert bool(wide_row["started"]) == bool(rostered_row["started"])
        assert bool(wide_row["bench"]) == bool(rostered_row["bench"])
        assert wide_row["fantasy_points"] == pytest.approx(
            rostered_row["fantasy_points"]
        )


def test_league_wide_row_count_is_rostered_count_plus_free_agents(
    provider: FakePlayerStatsProvider,
    league_wide_provider: FakePlayerStatsProvider,
) -> None:
    rostered_only = build_player_week_fact_table(
        [_week_one(), _week_two_bye()], TEAMS_DF, PLAYERS_DF, provider, SCORING_SETTINGS
    )
    league_wide = build_league_wide_player_week_fact_table(
        [_week_one(), _week_two_bye()],
        TEAMS_DF,
        PLAYERS_DF,
        league_wide_provider,
        SCORING_SETTINGS,
    )

    # +1 free agent ("9999"); the unresolvable row is dropped, not counted.
    assert len(league_wide.player_week_df) == len(rostered_only.player_week_df) + 1


def test_league_wide_columns_and_column_order_match_rostered_only(
    league_wide_provider: FakePlayerStatsProvider,
) -> None:
    result = build_league_wide_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, league_wide_provider, SCORING_SETTINGS
    )
    df = result.player_week_df

    assert list(df.columns[: len(PLAYER_WEEK_COLUMNS)]) == PLAYER_WEEK_COLUMNS
    assert list(df.columns)[-1] == "fantasy_points"


def test_league_wide_empty_weeks_list_yields_empty_frame(
    league_wide_provider: FakePlayerStatsProvider,
) -> None:
    result = build_league_wide_player_week_fact_table(
        [], TEAMS_DF, PLAYERS_DF, league_wide_provider, SCORING_SETTINGS
    )

    assert result.player_week_df.empty
    assert list(result.player_week_df.columns[: len(PLAYER_WEEK_COLUMNS)]) == (
        PLAYER_WEEK_COLUMNS
    )


def test_league_wide_unsupported_scoring_key_is_still_surfaced(
    league_wide_provider: FakePlayerStatsProvider,
) -> None:
    result = build_league_wide_player_week_fact_table(
        [_week_one()], TEAMS_DF, PLAYERS_DF, league_wide_provider, SCORING_SETTINGS
    )

    assert result.unsupported_scoring_keys == ["bonus_rec_te"]
