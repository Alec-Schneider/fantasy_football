"""Tests for matchup player contribution analysis (FFA-069).

All tests operate on hand-built ``season_matchup_df``/``player_week_df``
inputs -- no HTTP calls, no fixtures with opaque values -- so every
contribution, share, positional advantage, and reconciliation number can be
verified by hand arithmetic from the values written in each test, per
AGENTS.md's analytics-ticket requirement for a hand-checkable toy example.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS
from fantasy_analyzer.players import (
    PLAYER_CONTRIBUTION_COLUMNS,
    PLAYER_WEEK_COLUMNS,
    POSITIONAL_ADVANTAGE_COLUMNS,
    RECONCILE_COLUMNS,
    build_matchup_player_contributions,
    build_positional_matchup_advantage,
    reconcile_matchup_points,
)

STAT_COLUMNS = ["receptions", "receiving_yards"]
PLAYER_WEEK_TEST_COLUMNS = PLAYER_WEEK_COLUMNS + STAT_COLUMNS + ["fantasy_points"]


# --------------------------------------------------------------------------
# Row builders
# --------------------------------------------------------------------------


def _matchup_row(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    winner: int | None,
    loser: int | None,
    is_tie: bool = False,
    is_playoff: bool = False,
    week: int = 1,
    matchup_id: int | None = 1,
    season: int = 2025,
    owner_1: str | None = None,
    owner_2: str | None = None,
) -> dict:
    margin = None
    point_differential = None
    if points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": owner_1,
        "owner_2": owner_2,
        "points_1": points_1,
        "points_2": points_2,
        "winner": winner,
        "loser": loser,
        "is_tie": is_tie,
        "margin": margin,
        "point_differential": point_differential,
    }


def _matchup_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


def _player_row(
    season: int,
    week: int,
    roster_id: int,
    sleeper_player_id: str,
    fantasy_points: float | None,
    position: str | None,
    started: bool,
    fantasy_team: str | None = None,
    player_name: str | None = "Player",
    nfl_team: str | None = "SF",
) -> dict:
    return {
        "season": season,
        "week": week,
        "roster_id": roster_id,
        "fantasy_team": fantasy_team,
        "sleeper_player_id": sleeper_player_id,
        "gsis_id": f"g-{sleeper_player_id}",
        "player_name": player_name,
        "position": position,
        "nfl_team": nfl_team,
        "started": started,
        "bench": not started,
        "receptions": 4.0,
        "receiving_yards": 50.0,
        "fantasy_points": fantasy_points,
    }


def _player_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=PLAYER_WEEK_TEST_COLUMNS)
    frame = pd.DataFrame(rows, columns=PLAYER_WEEK_TEST_COLUMNS)
    for column in (
        "player_name",
        "position",
        "nfl_team",
        "sleeper_player_id",
        "fantasy_team",
    ):
        frame[column] = pd.Series(frame[column].tolist(), dtype=object)
    return frame


def _contribution_row(
    df: pd.DataFrame, roster_id: int, sleeper_player_id: str, week: int = 1
) -> pd.Series:
    match = df.loc[
        (df["roster_id"] == roster_id)
        & (df["sleeper_player_id"] == sleeper_player_id)
        & (df["week"] == week)
    ]
    assert len(match) == 1
    return match.iloc[0]


def _advantage_row(
    df: pd.DataFrame, roster_id: int, position: str, week: int = 1
) -> pd.Series:
    match = df.loc[
        (df["roster_id"] == roster_id)
        & (df["position"] == position)
        & (df["week"] == week)
    ]
    assert len(match) == 1
    return match.iloc[0]


def _reconcile_row(df: pd.DataFrame, roster_id: int, week: int = 1) -> pd.Series:
    match = df.loc[(df["roster_id"] == roster_id) & (df["week"] == week)]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# Hand-checkable toy example: one clean matchup + a tie + a bye
# --------------------------------------------------------------------------


def _toy_matchups() -> list[dict]:
    """Week 1: roster 1 (45.0) beats roster 2 (38.0). Week 2: roster 1 (30.0)
    ties roster 3 (30.0). Week 3: roster 4 has a bye (50.0, no opponent).

    Week 1 hand computation:
        roster 1 starters: QB1=20.0, RB1=15.0, WR1=10.0 -> sum = 45.0 = points_1
        roster 2 starters: QB2=18.0, RB2=12.0, WR2=8.0  -> sum = 38.0 = points_2
        margin (roster 1 perspective) = 45 - 38 = 7.0; result = "win"
        margin (roster 2 perspective) = 38 - 45 = -7.0; result = "loss"
        shares (roster 1): QB1 20/45=0.444..., RB1 15/45=0.333..., WR1 10/45=0.222...
        contribution_rank (roster 1): QB1=1, RB1=2, WR1=3
        positional_advantage (roster 1 perspective):
            QB: 20-18=2.0, RB: 15-12=3.0, WR: 10-8=2.0 (sums to margin, 7.0)

    Week 2 hand computation (tie):
        roster 1 starts one RB (RB1b=30.0) -> points_1 = 30.0
        roster 3 starts one WR (WR3=30.0)  -> points_2 = 30.0
        result = "tie" for both; margin = 0.0 for both
        positional advantage (roster 1 perspective): RB row (30, 1) vs (0, 0)
        -> advantage 30.0; WR row (0, 0) vs (30, 1) -> advantage -30.0
    """
    return [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=45.0,
            points_2=38.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
            owner_1="Alpha",
            owner_2="Beta",
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=3,
            points_1=30.0,
            points_2=30.0,
            winner=None,
            loser=None,
            is_tie=True,
            week=2,
            matchup_id=2,
            owner_1="Alpha",
            owner_2="Gamma",
        ),
        _matchup_row(
            roster_1_id=4,
            roster_2_id=None,
            points_1=50.0,
            points_2=None,
            winner=None,
            loser=None,
            week=3,
            matchup_id=None,
            owner_1="Delta",
        ),
    ]


def _toy_players() -> list[dict]:
    return [
        # Week 1: roster 1 vs roster 2.
        _player_row(2025, 1, 1, "QB1", 20.0, "QB", True, fantasy_team="Alpha"),
        _player_row(2025, 1, 1, "RB1", 15.0, "RB", True, fantasy_team="Alpha"),
        _player_row(2025, 1, 1, "WR1", 10.0, "WR", True, fantasy_team="Alpha"),
        _player_row(2025, 1, 1, "BN1", 99.0, "WR", False, fantasy_team="Alpha"),
        _player_row(2025, 1, 2, "QB2", 18.0, "QB", True, fantasy_team="Beta"),
        _player_row(2025, 1, 2, "RB2", 12.0, "RB", True, fantasy_team="Beta"),
        _player_row(2025, 1, 2, "WR2", 8.0, "WR", True, fantasy_team="Beta"),
        # Week 2: roster 1 vs roster 3 (tie).
        _player_row(2025, 2, 1, "RB1B", 30.0, "RB", True, fantasy_team="Alpha"),
        _player_row(2025, 2, 3, "WR3", 30.0, "WR", True, fantasy_team="Gamma"),
        # Week 3: roster 4's bye -- should be fully excluded downstream.
        _player_row(2025, 3, 4, "QB4", 50.0, "QB", True, fantasy_team="Delta"),
    ]


# --------------------------------------------------------------------------
# build_matchup_player_contributions
# --------------------------------------------------------------------------


class TestPlayerContributions:
    def test_toy_win_side_shares_and_ranks(self) -> None:
        df = build_matchup_player_contributions(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        assert list(df.columns) == PLAYER_CONTRIBUTION_COLUMNS

        qb1 = _contribution_row(df, 1, "QB1")
        rb1 = _contribution_row(df, 1, "RB1")
        wr1 = _contribution_row(df, 1, "WR1")

        assert qb1["fantasy_points"] == pytest.approx(20.0)
        assert qb1["team_points"] == pytest.approx(45.0)
        assert qb1["opponent_points"] == pytest.approx(38.0)
        assert qb1["share_of_team_points"] == pytest.approx(20.0 / 45.0)
        assert qb1["margin"] == pytest.approx(7.0)
        assert qb1["result"] == "win"
        assert qb1["contribution_rank"] == 1
        assert rb1["contribution_rank"] == 2
        assert wr1["contribution_rank"] == 3
        # Bench player never appears.
        assert not ((df["roster_id"] == 1) & (df["sleeper_player_id"] == "BN1")).any()

    def test_toy_loss_side_mirrors_win_side(self) -> None:
        df = build_matchup_player_contributions(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        qb2 = _contribution_row(df, 2, "QB2")
        assert qb2["fantasy_points"] == pytest.approx(18.0)
        assert qb2["team_points"] == pytest.approx(38.0)
        assert qb2["opponent_points"] == pytest.approx(45.0)
        assert qb2["margin"] == pytest.approx(-7.0)
        assert qb2["result"] == "loss"
        assert qb2["contribution_rank"] == 1

    def test_tie_result_and_zero_margin(self) -> None:
        df = build_matchup_player_contributions(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        rb1b = _contribution_row(df, 1, "RB1B", week=2)
        wr3 = _contribution_row(df, 3, "WR3", week=2)
        assert rb1b["result"] == "tie"
        assert wr3["result"] == "tie"
        assert rb1b["margin"] == pytest.approx(0.0)
        assert wr3["margin"] == pytest.approx(0.0)

    def test_bye_week_produces_no_rows(self) -> None:
        df = build_matchup_player_contributions(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        assert not (df["roster_id"] == 4).any()

    def test_tied_fantasy_points_share_rank(self) -> None:
        """Two started players tied on points share ``contribution_rank``."""
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=20.0,
                points_2=10.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, "RB", True),
            _player_row(2025, 1, 1, "B", 10.0, "WR", True),
            _player_row(2025, 1, 1, "C", 0.0, "TE", True),
            _player_row(2025, 1, 2, "D", 10.0, "QB", True),
        ]
        df = build_matchup_player_contributions(
            _matchup_df(matchups), _player_df(players)
        )
        a = _contribution_row(df, 1, "A")
        b = _contribution_row(df, 1, "B")
        c = _contribution_row(df, 1, "C")
        assert a["contribution_rank"] == 1
        assert b["contribution_rank"] == 1
        # Standard competition ranking: next distinct rank skips the tie.
        assert c["contribution_rank"] == 3

    def test_missing_fantasy_points_treated_as_zero(self) -> None:
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.0,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, "RB", True),
            _player_row(2025, 1, 1, "B", None, "WR", True),
            _player_row(2025, 1, 2, "C", 5.0, "QB", True),
        ]
        df = build_matchup_player_contributions(
            _matchup_df(matchups), _player_df(players)
        )
        b = _contribution_row(df, 1, "B")
        assert b["fantasy_points"] == pytest.approx(0.0)
        assert b["contribution_rank"] == 2

    def test_duplicate_player_id_keeps_first_row(self) -> None:
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.0,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, "RB", True),
            _player_row(2025, 1, 1, "A", 999.0, "RB", True),
            _player_row(2025, 1, 2, "C", 5.0, "QB", True),
        ]
        df = build_matchup_player_contributions(
            _matchup_df(matchups), _player_df(players)
        )
        rows = df.loc[(df["roster_id"] == 1) & (df["sleeper_player_id"] == "A")]
        assert len(rows) == 1
        assert rows.iloc[0]["fantasy_points"] == pytest.approx(10.0)

    def test_incomplete_matchup_has_no_result_or_margin(self) -> None:
        """Missing ``points_2`` -- an incomplete (not bye) matchup, per outcomes.py."""
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.0,
                points_2=None,
                winner=None,
                loser=None,
                is_tie=False,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, "RB", True),
        ]
        df = build_matchup_player_contributions(
            _matchup_df(matchups), _player_df(players)
        )
        a = _contribution_row(df, 1, "A")
        assert a["result"] is None
        assert pd.isna(a["margin"])
        assert pd.isna(a["opponent_points"])
        # team_points is still known (roster 1's own recorded score), so
        # share_of_team_points is still computable.
        assert a["share_of_team_points"] == pytest.approx(1.0)

    def test_missing_position_still_gets_a_contribution_row(self) -> None:
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.0,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, None, True),
            _player_row(2025, 1, 2, "C", 5.0, "QB", True),
        ]
        df = build_matchup_player_contributions(
            _matchup_df(matchups), _player_df(players)
        )
        a = _contribution_row(df, 1, "A")
        assert a["fantasy_points"] == pytest.approx(10.0)
        assert a["position"] is None

    def test_empty_inputs_return_empty_frame(self) -> None:
        empty_matchups = _matchup_df([])
        empty_players = _player_df([])
        df = build_matchup_player_contributions(empty_matchups, empty_players)
        assert df.empty
        assert list(df.columns) == PLAYER_CONTRIBUTION_COLUMNS

        df2 = build_matchup_player_contributions(
            _matchup_df(_toy_matchups()), empty_players
        )
        assert df2.empty

    def test_roster_week_absent_from_player_week_df_produces_no_rows(self) -> None:
        """A matchup row with no corresponding player_week_df rows at all."""
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.0,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        # player_week_df has data for a totally unrelated roster/week.
        players = [_player_row(2025, 9, 9, "Z", 1.0, "QB", True)]
        df = build_matchup_player_contributions(
            _matchup_df(matchups), _player_df(players)
        )
        assert df.empty


# --------------------------------------------------------------------------
# build_positional_matchup_advantage
# --------------------------------------------------------------------------


class TestPositionalAdvantage:
    def test_toy_week_one_advantages_sum_to_margin(self) -> None:
        df = build_positional_matchup_advantage(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        assert list(df.columns) == POSITIONAL_ADVANTAGE_COLUMNS

        qb = _advantage_row(df, 1, "QB")
        rb = _advantage_row(df, 1, "RB")
        wr = _advantage_row(df, 1, "WR")

        assert qb["own_points"] == pytest.approx(20.0)
        assert qb["opponent_points"] == pytest.approx(18.0)
        assert qb["positional_advantage"] == pytest.approx(2.0)
        assert rb["positional_advantage"] == pytest.approx(3.0)
        assert wr["positional_advantage"] == pytest.approx(2.0)

        total_advantage = (
            qb["positional_advantage"]
            + rb["positional_advantage"]
            + wr["positional_advantage"]
        )
        assert total_advantage == pytest.approx(7.0)  # roster 1's week-1 margin

    def test_position_started_only_by_opponent_gets_zero_row(self) -> None:
        """Week 2: roster 1 started RB only; roster 3 started WR only."""
        df = build_positional_matchup_advantage(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        rb_row = _advantage_row(df, 1, "RB", week=2)
        wr_row = _advantage_row(df, 1, "WR", week=2)

        assert rb_row["own_points"] == pytest.approx(30.0)
        assert rb_row["own_starters"] == 1
        assert rb_row["opponent_points"] == pytest.approx(0.0)
        assert rb_row["opponent_starters"] == 0
        assert rb_row["positional_advantage"] == pytest.approx(30.0)

        assert wr_row["own_points"] == pytest.approx(0.0)
        assert wr_row["own_starters"] == 0
        assert wr_row["opponent_points"] == pytest.approx(30.0)
        assert wr_row["opponent_starters"] == 1
        assert wr_row["positional_advantage"] == pytest.approx(-30.0)

    def test_bye_week_produces_no_rows(self) -> None:
        df = build_positional_matchup_advantage(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        assert not (df["roster_id"] == 4).any()

    def test_multiple_starters_at_one_position_are_summed(self) -> None:
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=25.0,
                points_2=10.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "RB1", 15.0, "RB", True),
            _player_row(2025, 1, 1, "RB2", 10.0, "RB", True),
            _player_row(2025, 1, 2, "RB3", 10.0, "RB", True),
        ]
        df = build_positional_matchup_advantage(
            _matchup_df(matchups), _player_df(players)
        )
        rb_row = _advantage_row(df, 1, "RB")
        assert rb_row["own_points"] == pytest.approx(25.0)
        assert rb_row["own_starters"] == 2
        assert rb_row["opponent_points"] == pytest.approx(10.0)
        assert rb_row["opponent_starters"] == 1
        assert rb_row["positional_advantage"] == pytest.approx(15.0)

    def test_missing_position_excluded_from_advantage(self) -> None:
        """Roster 1's only started player has an unresolved position, so
        roster 1 contributes nothing to the position union on its own side
        -- but it still gets a QB row (0 vs 5), driven entirely by
        roster 2's resolvable QB, per the "union of both sides' positions"
        rule."""
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.0,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, None, True),
            _player_row(2025, 1, 2, "C", 5.0, "QB", True),
        ]
        df = build_positional_matchup_advantage(
            _matchup_df(matchups), _player_df(players)
        )
        roster2_qb = _advantage_row(df, 2, "QB")
        assert roster2_qb["own_points"] == pytest.approx(5.0)
        assert roster2_qb["own_starters"] == 1
        assert roster2_qb["opponent_points"] == pytest.approx(0.0)
        assert roster2_qb["opponent_starters"] == 0
        assert roster2_qb["positional_advantage"] == pytest.approx(5.0)

        roster1_qb = _advantage_row(df, 1, "QB")
        assert roster1_qb["own_points"] == pytest.approx(0.0)
        assert roster1_qb["own_starters"] == 0
        assert roster1_qb["opponent_points"] == pytest.approx(5.0)
        assert roster1_qb["opponent_starters"] == 1
        assert roster1_qb["positional_advantage"] == pytest.approx(-5.0)
        # Roster 1's own unresolved-position player never enters any row.
        assert len(df.loc[df["roster_id"] == 1]) == 1

    def test_empty_inputs_return_empty_frame(self) -> None:
        df = build_positional_matchup_advantage(_matchup_df([]), _player_df([]))
        assert df.empty
        assert list(df.columns) == POSITIONAL_ADVANTAGE_COLUMNS


# --------------------------------------------------------------------------
# reconcile_matchup_points
# --------------------------------------------------------------------------


class TestReconcileMatchupPoints:
    def test_toy_week_one_reconciles_exactly(self) -> None:
        df = reconcile_matchup_points(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        assert list(df.columns) == RECONCILE_COLUMNS

        roster1 = _reconcile_row(df, 1)
        assert roster1["matchup_points"] == pytest.approx(45.0)
        assert roster1["started_points"] == pytest.approx(45.0)
        assert roster1["points_diff"] == pytest.approx(0.0)
        assert bool(roster1["points_match"]) is True

    def test_mismatch_is_flagged(self) -> None:
        """Sleeper's recorded score (12.0) disagrees with the summed started
        player_week_df total (10.0) -- e.g. a provider gap or unsupported
        scoring key."""
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=12.0,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, "RB", True),
            _player_row(2025, 1, 2, "B", 5.0, "QB", True),
        ]
        df = reconcile_matchup_points(_matchup_df(matchups), _player_df(players))
        roster1 = _reconcile_row(df, 1)
        assert roster1["matchup_points"] == pytest.approx(12.0)
        assert roster1["started_points"] == pytest.approx(10.0)
        assert roster1["points_diff"] == pytest.approx(2.0)
        assert bool(roster1["points_match"]) is False

        roster2 = _reconcile_row(df, 2)
        assert bool(roster2["points_match"]) is True

    def test_roster_week_absent_from_player_week_df_is_unknown_not_zero(self) -> None:
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.0,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        df = reconcile_matchup_points(_matchup_df(matchups), _player_df([]))
        roster1 = _reconcile_row(df, 1)
        assert pd.isna(roster1["started_points"])
        assert pd.isna(roster1["points_diff"])
        assert bool(roster1["points_match"]) is False

    def test_bye_week_excluded(self) -> None:
        df = reconcile_matchup_points(
            _matchup_df(_toy_matchups()), _player_df(_toy_players())
        )
        assert not (df["roster_id"] == 4).any()

    def test_custom_tolerance(self) -> None:
        matchups = [
            _matchup_row(
                roster_1_id=1,
                roster_2_id=2,
                points_1=10.05,
                points_2=5.0,
                winner=1,
                loser=2,
                week=1,
                matchup_id=1,
            )
        ]
        players = [
            _player_row(2025, 1, 1, "A", 10.0, "RB", True),
            _player_row(2025, 1, 2, "B", 5.0, "QB", True),
        ]
        strict = reconcile_matchup_points(_matchup_df(matchups), _player_df(players))
        roster1_strict = _reconcile_row(strict, 1)
        assert bool(roster1_strict["points_match"]) is False

        loose = reconcile_matchup_points(
            _matchup_df(matchups), _player_df(players), points_tolerance=0.1
        )
        roster1_loose = _reconcile_row(loose, 1)
        assert bool(roster1_loose["points_match"]) is True

    def test_empty_season_matchup_df_returns_empty_frame(self) -> None:
        df = reconcile_matchup_points(_matchup_df([]), _player_df(_toy_players()))
        assert df.empty
        assert list(df.columns) == RECONCILE_COLUMNS
