"""Tests for team-defense stat aggregation from raw nflverse player stats (FFA-074).

``build_team_defense_stats`` is tested directly against small in-memory
DataFrames (not the shared ``player_stats.csv`` fixture, which deliberately
carries no defensive columns -- see ``nflverse_provider.py``'s docstring).
``NflverseTeamDefenseProvider`` (which adds download/caching on top) is
tested with requests_mock against the shared player-stats and games
fixtures. Neither ever touches the live nflverse-data release.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.nflverse_defense import (
    TEAM_CODE_ALIASES,
    TEAM_DEFENSE_WEEK_COLUMNS,
    NflverseTeamDefenseProvider,
    build_team_defense_stats,
    build_team_defense_weeks,
)
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient
from fantasy_analyzer.players.points_allowed import normalize_points_allowed
from fantasy_analyzer.players.provider import validate_player_week_columns
from fantasy_analyzer.players.scoring import calculate_team_defense_points


def _raw_stats_row(**overrides: object) -> dict:
    row: dict = {
        "season": 2025,
        "week": 1,
        "team": None,
        "def_sacks": 0,
        "def_interceptions": 0,
        "def_fumbles_forced": 0,
        "def_tds": 0,
        "def_safeties": 0,
        "def_punt_blocks": 0,
        "def_pat_blocks": 0,
        "def_fg_blocks": 0,
        "fumble_recovery_opp": 0,
        "fumble_recovery_tds": 0,
        "special_teams_tds": 0,
    }
    row.update(overrides)
    return row


@pytest.fixture
def raw_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # BUF defense: two different players contribute to the same team.
            _raw_stats_row(team="BUF", def_sacks=2, def_interceptions=1),
            _raw_stats_row(team="BUF", special_teams_tds=1),
            # SEA defense: one player, different week to be excluded.
            _raw_stats_row(team="SEA", def_sacks=3, fumble_recovery_opp=1),
            _raw_stats_row(team="SEA", season=2025, week=2, def_sacks=9),
            # A player with no team on record -- must be excluded entirely.
            _raw_stats_row(team=None, def_sacks=5),
        ]
    )


@pytest.fixture
def points_allowed(nflverse_games_fixture_path: Path) -> pd.DataFrame:
    games = pd.read_csv(nflverse_games_fixture_path)
    return normalize_points_allowed(games)


# -------------------------
# build_team_defense_stats (pure, no network)
# -------------------------


def test_build_returns_one_row_per_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert len(result) == 2
    assert set(result["nfl_team"]) == {"BUF", "SEA"}


def test_build_sums_stats_across_multiple_players_on_the_same_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """BUF's def_sacks/def_interceptions come from one row, special_teams_tds
    from another -- both must land on the same aggregated BUF row."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)
    buf = result[result["nfl_team"] == "BUF"].iloc[0]

    assert buf["def_sacks"] == 2
    assert buf["def_interceptions"] == 1
    assert buf["special_teams_tds"] == 1


def test_build_excludes_rows_with_no_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """The 5th fixture row (team=None, def_sacks=5) must not create a phantom row
    or leak into BUF/SEA's totals."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert None not in set(result["nfl_team"])
    assert result["def_sacks"].sum() == 5  # 2 (BUF) + 3 (SEA), not +5 more


def test_build_excludes_other_weeks(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """SEA's week-2 row (def_sacks=9) must not appear in the week-1 result."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)
    sea = result[result["nfl_team"] == "SEA"].iloc[0]

    assert sea["def_sacks"] == 3


def test_build_joins_points_allowed_by_team(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    """BUF allowed BAL's 40; SEA allowed SF's 17 (see games.csv fixture)."""
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    buf = result[result["nfl_team"] == "BUF"].iloc[0]
    sea = result[result["nfl_team"] == "SEA"].iloc[0]
    assert buf["points_allowed"] == 40
    assert sea["points_allowed"] == 17


def test_build_leaves_points_allowed_nan_when_team_has_no_schedule_row(
    points_allowed: pd.DataFrame,
) -> None:
    """A team with player-week rows but no matching game (e.g. not yet
    published) gets NaN points_allowed, not a dropped row or a KeyError."""
    raw_stats = pd.DataFrame([_raw_stats_row(team="KC", def_sacks=1)])

    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert len(result) == 1
    assert pd.isna(result.iloc[0]["points_allowed"])


def test_build_aliases_team_codes_to_sleeper_convention(
    points_allowed: pd.DataFrame,
) -> None:
    """nflverse's 'LA' must come out as Sleeper's 'LAR' -- see TEAM_CODE_ALIASES."""
    assert TEAM_CODE_ALIASES["LA"] == "LAR"
    raw_stats = pd.DataFrame([_raw_stats_row(team="LA", def_sacks=1)])

    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    assert result.iloc[0]["sleeper_player_id"] == "LAR"
    assert result.iloc[0]["nfl_team"] == "LAR"


def test_build_result_satisfies_identity_column_contract(
    raw_stats: pd.DataFrame, points_allowed: pd.DataFrame
) -> None:
    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=1)

    validate_player_week_columns(result)  # does not raise
    buf = result[result["nfl_team"] == "BUF"].iloc[0]
    assert buf["position"] == "DEF"
    assert pd.isna(buf["gsis_id"])
    assert pd.isna(buf["player_name"])


def test_build_returns_empty_frame_for_a_week_with_no_data(
    points_allowed: pd.DataFrame,
) -> None:
    raw_stats = pd.DataFrame([_raw_stats_row(team="BUF")])

    result = build_team_defense_stats(raw_stats, points_allowed, season=2025, week=99)

    assert result.empty


# -------------------------
# NflverseTeamDefenseProvider (network mocked)
# -------------------------


def _gzipped_fixture(path: Path) -> bytes:
    return gzip.compress(path.read_bytes())


def test_provider_weekly_stats_matches_pure_function(
    tmp_path: Path,
    nflverse_games_fixture_path: Path,
) -> None:
    raw_stats = pd.DataFrame(
        [
            _raw_stats_row(team="BUF", def_sacks=2),
            _raw_stats_row(team="SEA", def_sacks=3),
        ]
    )
    stats_csv = tmp_path / "raw_stats.csv"
    raw_stats.to_csv(stats_csv, index=False)

    provider = NflverseTeamDefenseProvider(cache_dir=tmp_path)

    with requests_mock_lib.Mocker() as m:
        m.get(
            NflverseClient.STATS_PLAYER_WEEK_URL_TEMPLATE.format(season=2025),
            content=gzip.compress(stats_csv.read_bytes()),
        )
        m.get(
            NflverseScheduleClient.GAMES_URL,
            content=nflverse_games_fixture_path.read_bytes(),
        )
        result = provider.weekly_stats(season=2025, week=1)

    assert len(result) == 2
    validate_player_week_columns(result)
    buf = result[result["nfl_team"] == "BUF"].iloc[0]
    assert buf["def_sacks"] == 2
    assert buf["points_allowed"] == 40


# -------------------------
# build_team_defense_weeks (FFA-112)
# -------------------------


def _player(team: str, position_group: str, **stats: float) -> dict:
    row = {
        "season": 2019,
        "week": 1,
        "season_type": "REG",
        "player_id": f"{team}-{position_group}-{len(stats)}",
        "team": team,
        "position_group": position_group,
    }
    row.update(stats)
    return row


@pytest.fixture
def toy_games() -> pd.DataFrame:
    """Week 1: Raiders (historic code OAK) 17, Rams (nflverse LA) 12.

    Week 2: an unplayed game -- no final score, so no rows.
    """
    return pd.DataFrame(
        [
            {
                "season": 2019,
                "week": 1,
                "game_type": "REG",
                "home_team": "OAK",
                "away_team": "LA",
                "home_score": 17.0,
                "away_score": 12.0,
            },
            {
                "season": 2019,
                "week": 2,
                "game_type": "REG",
                "home_team": "LA",
                "away_team": "SEA",
                "home_score": None,
                "away_score": None,
            },
        ]
    )


@pytest.fixture
def toy_week_stats() -> pd.DataFrame:
    """Raiders score 17 = rush TD 6 + PAT 1 + 2 FG 6 + credited safety 2
    + one *penalty* safety (2) credited to no player. Rams score 12 =
    fumble-return TD 6 (by a linebacker) + 2 FG 6."""
    rows = [
        # Raiders (nflverse stats already use the current code, LV).
        _player("LV", "QB", rushing_tds=1, sacks_suffered=3),
        _player("LV", "SPEC", pat_made=1, fg_made=2),
        _player("LV", "LB", def_safeties=1),
        _player("LV", "DB", def_interceptions=1, fumble_recovery_opp=1),
        _player("LV", "DL", def_fumbles_forced=1, def_punt_blocks=1),
        # Rams.
        _player("LA", "QB", sacks_suffered=2),
        _player(
            "LA",
            "WR",
            punt_returns=2,
            fumbles_lost_total=1,
            rushing_fumbles_lost=0,
        ),
        _player("LA", "LB", fumble_recovery_opp=1, fumble_recovery_tds=1),
        _player("LA", "SPEC", fg_made=2),
    ]
    frame = pd.DataFrame(rows)
    # nflverse's weekly player-less row: the week's unattributed stats under
    # an arbitrary team. It must not hand anyone a safety.
    junk = {
        "season": 2019,
        "week": 1,
        "season_type": "REG",
        "player_id": None,
        "team": "SEA",
        "def_safeties": 1,
    }
    return pd.concat([frame, pd.DataFrame([junk])], ignore_index=True)


def test_team_defense_weeks_hand_checked_toy_example(
    toy_week_stats: pd.DataFrame, toy_games: pd.DataFrame
) -> None:
    result = build_team_defense_weeks(toy_week_stats, toy_games, 2019)

    assert list(result.columns) == TEAM_DEFENSE_WEEK_COLUMNS
    assert sorted(result["team"]) == ["LAR", "LV"]
    raiders = result.set_index("team").loc["LV"]
    rams = result.set_index("team").loc["LAR"]

    # Raiders' defense: sacks are the Rams' sacks_suffered (2); the one
    # recovery was of a muffed punt, so it is a special-teams recovery; the
    # penalty safety is recovered from the score (17 - 15 = 2).
    assert raiders["opponent"] == "LAR"
    assert raiders["sacks"] == 2
    assert raiders["interceptions"] == 1
    assert raiders["fumble_recoveries"] == 0
    assert raiders["st_fumble_recoveries"] == 1
    assert raiders["forced_fumbles"] == 1
    assert raiders["blocked_kicks"] == 1
    assert raiders["unattributed_safeties"] == 1
    assert raiders["safeties"] == 2
    # 12 allowed, less the Rams' 6-point defensive touchdown.
    assert raiders["points_allowed"] == 12
    assert raiders["def_points_allowed"] == 6

    # Rams' defense: the linebacker's fumble return is a defensive TD, and
    # the Raiders' two safeties come off the 17 they allowed.
    assert rams["def_tds"] == 1
    assert rams["fumble_recoveries"] == 1
    assert rams["sacks"] == 3
    assert rams["points_allowed"] == 17
    assert rams["def_points_allowed"] == 13
    assert rams["score_residual"] == 0


def test_team_defense_weeks_score_end_to_end(
    toy_week_stats: pd.DataFrame, toy_games: pd.DataFrame
) -> None:
    """Scored with a New Wave/Zipline-shaped DEF ruleset.

    Raiders: tier(6) 7 + sacks 2 + INT 2 + ST recovery 1 + FF 1
    + 2 safeties 4 + blocked punt 2 = 19. Rams: tier(13) 4 + sacks 3
    + defensive TD 6 + recovery 2 = 15.
    """
    settings = {
        "sack": 1,
        "int": 2,
        "fum_rec": 2,
        "def_st_fum_rec": 1,
        "ff": 1,
        "def_st_ff": 1,
        "def_td": 6,
        "def_st_td": 6,
        "safe": 2,
        "blk_kick": 2,
        "pts_allow_0": 10,
        "pts_allow_1_6": 7,
        "pts_allow_7_13": 4,
        "pts_allow_14_20": 1,
        "pts_allow_21_27": 0,
        "pts_allow_28_34": -1,
        "pts_allow_35p": -4,
    }
    weeks = build_team_defense_weeks(toy_week_stats, toy_games, 2019)

    points = calculate_team_defense_points(weeks, settings).points_df.set_index("team")[
        "fantasy_points"
    ]

    assert points["LV"] == pytest.approx(19.0)
    assert points["LAR"] == pytest.approx(15.0)


def test_offensive_player_fumble_touchdown_is_not_a_defensive_touchdown(
    toy_games: pd.DataFrame,
) -> None:
    """A receiver recovering the defense's fumble (after his own QB's
    interception) in the end zone scores an *offensive* touchdown: the
    Raiders' defense is charged the full 12, and the Rams get no DEF TD."""
    stats = pd.DataFrame(
        [
            _player("LV", "SPEC", fg_made=5, pat_made=2),
            _player("LA", "WR", fumble_recovery_opp=1, fumble_recovery_tds=1),
            _player("LA", "SPEC", fg_made=2),
        ]
    )

    result = build_team_defense_weeks(stats, toy_games, 2019).set_index("team")

    assert result.loc["LAR", "def_tds"] == 0
    assert result.loc["LV", "def_points_allowed"] == 12


def test_team_defense_weeks_without_position_group_counts_every_recovery_td(
    toy_games: pd.DataFrame,
) -> None:
    stats = pd.DataFrame(
        [
            {
                "season": 2019,
                "week": 1,
                "player_id": "a",
                "team": "LA",
                "fumble_recovery_opp": 1,
                "fumble_recovery_tds": 1,
            },
        ]
    )

    result = build_team_defense_weeks(stats, toy_games, 2019).set_index("team")

    assert result.loc["LAR", "def_tds"] == 1


def test_team_defense_weeks_empty_inputs_return_the_schema(
    toy_games: pd.DataFrame,
) -> None:
    no_games = build_team_defense_weeks(pd.DataFrame(), pd.DataFrame(), 2019)
    no_stats = build_team_defense_weeks(pd.DataFrame(), toy_games, 2019)

    assert no_games.empty
    assert list(no_games.columns) == TEAM_DEFENSE_WEEK_COLUMNS
    # A played game with no player rows still yields both teams, zeroed.
    assert sorted(no_stats["team"]) == ["LAR", "LV"]
    assert no_stats["sacks"].sum() == 0
