"""Tests for league-wide composite player value rankings (FFA-073).

All tests operate on hand-built ``performance_df``-shaped inputs -- no HTTP
calls, no live Sleeper or nflverse access, no opaque fixture values -- so
every replacement level, VORP, z-score, blend and rank can be verified by
hand arithmetic from the values written in each test, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.

The methodology under test: FFA-068 supplies ``points_above_replacement``,
``ppg_above_replacement``, ``replacement_ppg`` and ``scarcity_ratio``;
FFA-065 supplies ``cv`` and ``scoring_ceiling``; this module shrinks the
rate VORP toward replacement (``n * x / (n + k)``), population-z-scores all
five components across the whole season pool, blends them with renormalized
weights (dropping -- never zero-filling -- an unmeasurable component), and
applies standard competition ("1224") ranking to the result.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.players.performance import PLAYER_PERFORMANCE_COLUMNS
from fantasy_analyzer.players.player_rankings import (
    DEFAULT_RANKING_WEIGHTS,
    LEAGUE_PLAYER_RANKING_COLUMNS,
    RankingWeights,
    build_league_player_rankings,
)

#: The columns FFA-065 emits. The helpers below populate only the subset
#: this module reads (identity, games/points, ``cv``, ``scoring_ceiling``);
#: the rest are NaN, which this module never looks at.
PERFORMANCE_TEST_COLUMNS = PLAYER_PERFORMANCE_COLUMNS


def _row(
    sleeper_player_id: str,
    position: str,
    points_per_game: float,
    games_played: float,
    cv: float | None,
    scoring_ceiling: float | None,
    season: int = 2025,
    total_points: float | None = None,
    player_name: str | None = "Player",
    nfl_team: str | None = "SF",
) -> dict:
    """One ``performance_df``-shaped row.

    ``total_points`` defaults to ``points_per_game * games_played`` (FFA-065's
    own invariant); pass it explicitly only to test a frame that violates it.
    """
    return {
        "season": season,
        "sleeper_player_id": sleeper_player_id,
        "player_name": player_name,
        "position": position,
        "nfl_team": nfl_team,
        "games_played": games_played,
        "total_points": (
            points_per_game * games_played if total_points is None else total_points
        ),
        "points_per_game": points_per_game,
        "median_points": float("nan"),
        "stdev_points": float("nan"),
        "cv": float("nan") if cv is None else cv,
        "scoring_floor": float("nan"),
        "scoring_ceiling": (
            float("nan") if scoring_ceiling is None else scoring_ceiling
        ),
        "boom_games": float("nan"),
        "boom_pct": float("nan"),
        "bust_games": float("nan"),
        "bust_pct": float("nan"),
    }


def _df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=PERFORMANCE_TEST_COLUMNS)
    frame = pd.DataFrame(rows, columns=PERFORMANCE_TEST_COLUMNS)
    for column in ("player_name", "position", "nfl_team", "sleeper_player_id"):
        frame[column] = pd.Series(frame[column].tolist(), dtype=object)
    return frame


def _get_row(df: pd.DataFrame, sleeper_player_id: str, season: int = 2025) -> pd.Series:
    match = df.loc[
        (df["sleeper_player_id"] == sleeper_player_id) & (df["season"] == season)
    ]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# Hand-checkable toy example
# --------------------------------------------------------------------------

TOY_ROSTER_POSITIONS = ["QB", "RB", "WR", "BN"]
TOY_NUM_TEAMS = 3


def _toy_rows() -> list[dict]:
    """Six players, three positions, season 2025 -- worked out by hand.

    League: ``num_teams = 3``, ``roster_positions = [QB, RB, WR, BN]`` ->
    one starting slot each, so every position's starter cutoff is 3.

    Inputs (every player plays 16 games; total_points = ppg * 16):

        id    pos  ppg      total   cv     ceiling
        QB1   QB   10.625   170.0   0.25   34.5
        QB2   QB    8.75    140.0   0.85   28.5
        QB3   QB    7.5     120.0   0.55   22.5
        RB1   RB   17.875   286.0   0.45   36.0
        RB2   RB   11.0     176.0   0.15   24.0
        WR1   WR    9.0     144.0   0.75   28.0

    Replacement (FFA-068): QB field 3 = cutoff 3 -> QB3, 7.5 ppg. RB field 2,
    cutoff 3 clamped to 2 -> RB2, 11.0 ppg. WR field 1, cutoff 3 clamped to
    1 -> WR1 himself, 9.0 ppg.

    points_above_replacement = total - replacement_ppg * 16:
        QB1 170 - 120 = 50    QB2 140 - 120 = 20    QB3 0
        RB1 286 - 176 = 110   RB2 0                 WR1 0

    z_value: pool {50, 20, 0, 110, 0, 0}; mean = 180/6 = 30;
        pvar = (400 + 100 + 900 + 6400 + 900 + 900)/6 = 9600/6 = 1600;
        pstdev = 40. z = (x - 30)/40:
        QB1 0.5   QB2 -0.25   QB3 -0.75   RB1 2.0   RB2 -0.75   WR1 -0.75

    shrunk_ppg_above_replacement = 16 * ppg_above_replacement / (16 + 4)
    = 0.8 * ppg_above_replacement:
        QB1 0.8 * 3.125 = 2.5    QB2 0.8 * 1.25 = 1.0    RB1 0.8 * 6.875 = 5.5
        QB3 / RB2 / WR1 are the replacement players themselves -> 0.0

    z_rate: pool {2.5, 1.0, 0, 5.5, 0, 0}; mean = 9/6 = 1.5;
        pvar = (1 + .25 + 2.25 + 16 + 2.25 + 2.25)/6 = 24/6 = 4; pstdev = 2.
        Because every player has the same games_played, the shrunk rate is
        exactly points_above_replacement / 20 -- a positive linear rescale --
        so z_rate equals z_value here by construction. Tests further down
        (shrinkage, custom weights) exercise the case where they differ.

    z_reliability = z(-cv): pool {-0.25, -0.85, -0.55, -0.45, -0.15, -0.75};
        mean = -3.0/6 = -0.5; deviations {0.25, -0.35, -0.05, 0.05, 0.35,
        -0.25}; pvar = (0.0625 + 0.1225 + 0.0025 + 0.0025 + 0.1225 +
        0.0625)/6 = 0.375/6 = 0.0625; pstdev = 0.25. z = deviation / 0.25:
        QB1 1.0   QB2 -1.4   QB3 -0.2   RB1 0.2   RB2 1.4   WR1 -1.0

    z_upside = z(scoring_ceiling - replacement_ppg):
        QB1 34.5 - 7.5 = 27   QB2 28.5 - 7.5 = 21   QB3 22.5 - 7.5 = 15
        RB1 36.0 - 11.0 = 25  RB2 24.0 - 11.0 = 13  WR1 28.0 - 9.0 = 19
        mean = 120/6 = 20; deviations {7, 1, -5, 5, -7, -1};
        pvar = (49 + 1 + 25 + 25 + 49 + 1)/6 = 150/6 = 25; pstdev = 5. z:
        QB1 1.4   QB2 0.2   QB3 -1.0   RB1 1.0   RB2 -1.4   WR1 -0.2

    z_scarcity = z(scarcity_ratio), broadcast from the position row:
        QB (10.625 - 7.5)/7.5 = 3.125/7.5 = 5/12; RB 6.875/11 = 5/8;
        WR (9 - 9)/9 = 0.
        pool {5/12, 5/12, 5/12, 5/8, 5/8, 0}; mean = 2.5/6 = 5/12;
        deviations {0, 0, 0, 5/24, 5/24, -5/12};
        pvar = (2*(5/24)^2 + (5/12)^2)/6 = (50/576 + 100/576)/6 = 25/576;
        pstdev = 5/24. z: QB players 0, RB players 1, WR1 -2.

    Because all six players have 16 games, shrunk_ppg_above_replacement is
    a positive rescale of points_above_replacement here, so z_rate == z_value
    by construction in this toy (see the module docstring's "value and rate
    are not independent"). The shrinkage tests below cover the case where
    they diverge.

    ranking_score, default weights (0.30 value, 0.20 rate, 0.20 reliability,
    0.15 upside, 0.15 scarcity -- they sum to 1.0 and all five components
    are available for all six players, so no renormalization applies):

        QB1  .3(0.5)  + .2(0.5)  + .2(1.0)  + .15(1.4)  + .15(0)  =  0.6600
        QB2  .3(-.25) + .2(-.25) + .2(-1.4) + .15(0.2)  + .15(0)  = -0.3750
        QB3  .3(-.75) + .2(-.75) + .2(-0.2) + .15(-1.0) + .15(0)  = -0.5650
        RB1  .3(2.0)  + .2(2.0)  + .2(0.2)  + .15(1.0)  + .15(1)  =  1.3400
        RB2  .3(-.75) + .2(-.75) + .2(1.4)  + .15(-1.4) + .15(1)  = -0.1550
        WR1  .3(-.75) + .2(-.75) + .2(-1.0) + .15(-0.2) + .15(-2) = -0.9050

    league_rank (no ties): RB1 1, QB1 2, RB2 3, QB2 4, QB3 5, WR1 6.
    Note RB2 -- a replacement-level RB with zero VORP -- outranks QB2, on
    reliability (RB2 is the toy's steadiest player, QB2 its most volatile)
    widened by the scarcity tilt. This is the composite disagreeing with
    FFA-068's pure-VORP value_rank, which is the whole point of the module.

    position_rank: QB1 1 / QB2 2 / QB3 3; RB1 1 / RB2 2; WR1 1.
    league_percentile = 1 - (rank - 1)/6: 1.0, 5/6, 4/6, 0.5, 2/6, 1/6.
    """
    return [
        _row("QB1", "QB", 10.625, 16, 0.25, 34.5),
        _row("QB2", "QB", 8.75, 16, 0.85, 28.5),
        _row("QB3", "QB", 7.5, 16, 0.55, 22.5),
        _row("RB1", "RB", 17.875, 16, 0.45, 36.0),
        _row("RB2", "RB", 11.0, 16, 0.15, 24.0),
        _row("WR1", "WR", 9.0, 16, 0.75, 28.0),
    ]


def _toy_rankings(**kwargs) -> pd.DataFrame:
    return build_league_player_rankings(
        _df(_toy_rows()), TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS, **kwargs
    )


def test_toy_example_hand_computed_inputs() -> None:
    """The FFA-065/FFA-068 values this module carries through, verbatim."""
    df = _toy_rankings()

    assert len(df) == 6

    qb1 = _get_row(df, "QB1")
    assert qb1["games_played"] == pytest.approx(16.0)
    assert qb1["points_per_game"] == pytest.approx(10.625)
    assert qb1["total_points"] == pytest.approx(170.0)
    assert qb1["replacement_ppg"] == pytest.approx(7.5)
    assert qb1["ppg_above_replacement"] == pytest.approx(3.125)
    assert qb1["points_above_replacement"] == pytest.approx(50.0)
    # 16 * 3.125 / (16 + 4) = 50 / 20 = 2.5
    assert qb1["shrunk_ppg_above_replacement"] == pytest.approx(2.5)
    assert qb1["cv"] == pytest.approx(0.25)
    assert qb1["scoring_ceiling"] == pytest.approx(34.5)
    assert qb1["scarcity_ratio"] == pytest.approx(5 / 12)

    rb1 = _get_row(df, "RB1")
    assert rb1["replacement_ppg"] == pytest.approx(11.0)
    assert rb1["points_above_replacement"] == pytest.approx(110.0)
    assert rb1["shrunk_ppg_above_replacement"] == pytest.approx(5.5)
    assert rb1["scarcity_ratio"] == pytest.approx(0.625)

    wr1 = _get_row(df, "WR1")
    # A one-player position: the player is his own replacement.
    assert wr1["points_above_replacement"] == pytest.approx(0.0)
    assert wr1["shrunk_ppg_above_replacement"] == pytest.approx(0.0)
    assert wr1["scarcity_ratio"] == pytest.approx(0.0)


def test_toy_example_hand_computed_components() -> None:
    """The five z-scores, exactly as derived in ``_toy_rows``' docstring."""
    df = _toy_rankings()

    expected = {
        # id: (z_value, z_rate, z_reliability, z_upside, z_scarcity)
        "QB1": (0.5, 0.5, 1.0, 1.4, 0.0),
        "QB2": (-0.25, -0.25, -1.4, 0.2, 0.0),
        "QB3": (-0.75, -0.75, -0.2, -1.0, 0.0),
        "RB1": (2.0, 2.0, 0.2, 1.0, 1.0),
        "RB2": (-0.75, -0.75, 1.4, -1.4, 1.0),
        "WR1": (-0.75, -0.75, -1.0, -0.2, -2.0),
    }
    for player_id, (value, rate, reliability, upside, scarcity) in expected.items():
        row = _get_row(df, player_id)
        assert row["z_value"] == pytest.approx(value), player_id
        assert row["z_rate"] == pytest.approx(rate), player_id
        assert row["z_reliability"] == pytest.approx(reliability), player_id
        assert row["z_upside"] == pytest.approx(upside), player_id
        assert row["z_scarcity"] == pytest.approx(scarcity), player_id
        assert row["components_used"] == 5, player_id


def test_toy_example_hand_computed_scores_and_ranks() -> None:
    """The blend, the ranks, the display order and the percentiles."""
    df = _toy_rankings()

    expected_scores = {
        "QB1": 0.66,
        "QB2": -0.375,
        "QB3": -0.565,
        "RB1": 1.34,
        "RB2": -0.155,
        "WR1": -0.905,
    }
    for player_id, score in expected_scores.items():
        assert _get_row(df, player_id)["ranking_score"] == pytest.approx(score), (
            player_id
        )

    # Display order is best-first within the season.
    assert list(df["sleeper_player_id"]) == ["RB1", "QB1", "RB2", "QB2", "QB3", "WR1"]
    assert list(df["league_rank"]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert list(df["position_rank"]) == [1.0, 1.0, 2.0, 2.0, 3.0, 1.0]
    assert list(df["league_percentile"]) == pytest.approx(
        [1.0, 5 / 6, 4 / 6, 3 / 6, 2 / 6, 1 / 6]
    )

    # The composite is not FFA-068's value_rank: RB2 has zero VORP and still
    # outranks QB2 (VORP 20) on reliability, widened by the scarcity tilt.
    assert _get_row(df, "RB2")["points_above_replacement"] == pytest.approx(0.0)
    assert _get_row(df, "QB2")["points_above_replacement"] == pytest.approx(20.0)
    assert _get_row(df, "RB2")["ranking_score"] > _get_row(df, "QB2")["ranking_score"]


# --------------------------------------------------------------------------
# Ties
# --------------------------------------------------------------------------


def _tie_rows() -> list[dict]:
    """WRb and WRc are identical in every input, so they must tie.

    Two positions (so the scarcity component has two distinct values and
    stays measurable), four WRs and two QBs, ``num_teams = 4`` with
    ``[QB, WR, BN]`` -> WR cutoff 4 (the whole field), QB cutoff 4 clamped
    to 2.
    """
    return [
        _row("WRa", "WR", 25.0, 10, 0.20, 40.0),
        _row("WRb", "WR", 20.0, 10, 0.40, 30.0),
        _row("WRc", "WR", 20.0, 10, 0.40, 30.0),
        _row("WRd", "WR", 10.0, 10, 0.60, 15.0),
        _row("QBa", "QB", 22.0, 10, 0.30, 35.0),
        _row("QBb", "QB", 18.0, 10, 0.50, 25.0),
    ]


def test_tied_scores_share_a_rank_and_the_next_rank_skips() -> None:
    df = build_league_player_rankings(_df(_tie_rows()), ["QB", "WR", "BN"], 4)

    wrb = _get_row(df, "WRb")
    wrc = _get_row(df, "WRc")
    assert wrb["ranking_score"] == pytest.approx(wrc["ranking_score"])
    assert wrb["league_rank"] == wrc["league_rank"]

    ranks = list(df["league_rank"])
    ids = list(df["sleeper_player_id"])
    tied_rank = wrb["league_rank"]
    assert ranks.count(tied_rank) == 2
    # Standard competition ranking: the next distinct rank skips the pair.
    following = [rank for rank in ranks if rank > tied_rank]
    assert min(following) == tied_rank + 2
    # Display order within the tie is ascending sleeper_player_id.
    assert ids.index("WRb") == ids.index("WRc") - 1
    # Ranks are non-decreasing down the frame (the promised display order).
    assert ranks == sorted(ranks)


def test_tied_players_share_position_rank_and_percentile() -> None:
    df = build_league_player_rankings(_df(_tie_rows()), ["QB", "WR", "BN"], 4)

    wrb = _get_row(df, "WRb")
    wrc = _get_row(df, "WRc")
    assert wrb["position_rank"] == wrc["position_rank"]
    assert wrb["league_percentile"] == pytest.approx(wrc["league_percentile"])
    # Percentile is 1 - (rank - 1) / n_ranked with n_ranked = 6.
    assert wrb["league_percentile"] == pytest.approx(
        1.0 - (wrb["league_rank"] - 1.0) / 6.0
    )

    # WRa is the best WR and the best player overall in this frame.
    wra = _get_row(df, "WRa")
    assert wra["league_rank"] == 1.0
    assert wra["position_rank"] == 1.0
    assert wra["league_percentile"] == pytest.approx(1.0)

    # position_rank is computed within (season, position): the QB pool is
    # ranked 1..2 regardless of where those players sit league-wide.
    qb_ranks = sorted(df.loc[df["position"] == "QB", "position_rank"].tolist())
    assert qb_ranks == [1.0, 2.0]
    wr_ranks = sorted(df.loc[df["position"] == "WR", "position_rank"].tolist())
    assert wr_ranks == [1.0, 2.0, 2.0, 4.0]


# --------------------------------------------------------------------------
# Missing components: dropped, and the surviving weights renormalized
# --------------------------------------------------------------------------


def _missing_cv_rows() -> list[dict]:
    """RBb played one game, so FFA-065 leaves his ``cv`` undefined.

    ``num_teams = 2``, ``roster_positions = [QB, RB, BN]`` -> cutoff 2 at
    both positions, which is each position's whole field, so the worse
    player at each position is replacement.

        id    pos  ppg  games  total  cv     ceiling
        QBa   QB   20   10     200    0.20   30
        QBb   QB   10   10     100    0.40   20
        RBa   RB   15   10     150    0.30   25
        RBb   RB    5    1       5    NaN    15

    replacement: QB 10.0, RB 5.0.
    points_above_replacement: QBa 200 - 100 = 100; QBb 0;
        RBa 150 - 50 = 100; RBb 5 - 5*1 = 0.
        pool {100, 0, 100, 0}: mean 50, pstdev 50 -> z_value = +1/-1/+1/-1.
    shrunk rate: QBa 10*10/14 = 100/14; QBb 0; RBa 10*10/14 = 100/14; RBb 0.
        pool has the same two-valued shape -> z_rate = +1/-1/+1/-1.
    z_reliability: only three usable -cv values {-0.20, -0.30, -0.40};
        mean -0.30; deviations {0.10, 0, -0.10}; pvar = 0.02/3;
        pstdev = sqrt(0.02/3); z = deviation / pstdev = +sqrt(1.5), 0,
        -sqrt(1.5) for QBa, RBa, QBb. RBb has no z_reliability at all.
    z_upside: ceilings above replacement {20, 10, 20, 10}; mean 15;
        pstdev 5 -> +1/-1/+1/-1.
    z_scarcity: QB (20-10)/10 = 1.0; RB (15-5)/5 = 2.0; pool {1,1,2,2};
        mean 1.5; pstdev 0.5 -> QBs -1, RBs +1.
    """
    return [
        _row("QBa", "QB", 20.0, 10, 0.20, 30.0),
        _row("QBb", "QB", 10.0, 10, 0.40, 20.0),
        _row("RBa", "RB", 15.0, 10, 0.30, 25.0),
        _row("RBb", "RB", 5.0, 1, None, 15.0),
    ]


def test_missing_cv_drops_the_component_and_renormalizes() -> None:
    df = build_league_player_rankings(_df(_missing_cv_rows()), ["QB", "RB", "BN"], 2)

    rbb = _get_row(df, "RBb")
    assert pd.isna(rbb["cv"])
    assert pd.isna(rbb["z_reliability"])
    assert rbb["components_used"] == 4
    # Surviving weights 0.30 + 0.20 + 0.15 + 0.15 = 0.80, renormalized:
    # (0.30*-1 + 0.20*-1 + 0.15*-1 + 0.15*+1) / 0.80 = -0.50 / 0.80
    assert rbb["z_value"] == pytest.approx(-1.0)
    assert rbb["z_rate"] == pytest.approx(-1.0)
    assert rbb["z_upside"] == pytest.approx(-1.0)
    assert rbb["z_scarcity"] == pytest.approx(1.0)
    assert rbb["ranking_score"] == pytest.approx(-0.50 / 0.80)

    # A fully-observed player still uses all five, with no renormalization
    # (the default weights already sum to 1.0).
    qba = _get_row(df, "QBa")
    assert qba["components_used"] == 5
    assert qba["z_reliability"] == pytest.approx(math.sqrt(1.5))
    assert qba["ranking_score"] == pytest.approx(
        0.30 * 1.0 + 0.20 * 1.0 + 0.20 * math.sqrt(1.5) + 0.15 * 1.0 + 0.15 * -1.0
    )

    # RBa sits exactly at the reliability mean, so his z is 0.0 -- a used
    # component that contributes nothing, which is not the same as a
    # dropped one.
    rba = _get_row(df, "RBa")
    assert rba["z_reliability"] == pytest.approx(0.0)
    assert rba["components_used"] == 5


def test_non_positive_replacement_makes_scarcity_undefined() -> None:
    """A position whose ``replacement_ppg <= 0`` has no ``scarcity_ratio``.

    Three positions, ``num_teams = 2``, ``[QB, RB, K, BN]`` -> cutoff 2 at
    each, which is each field. The kicker replacement scores 0.0 ppg, so
    FFA-068 emits ``scarcity_ratio = NaN`` for the whole K position (a
    non-positive denominator has no percentage meaning), and both kickers
    lose the scarcity component. QB and RB still have two distinct ratios
    between them, so the component remains measurable for those players.
    """
    rows = [
        _row("QBa", "QB", 20.0, 10, 0.20, 30.0),
        _row("QBb", "QB", 10.0, 10, 0.40, 20.0),
        _row("RBa", "RB", 15.0, 10, 0.30, 25.0),
        _row("RBb", "RB", 5.0, 10, 0.50, 12.0),
        _row("Ka", "K", 5.0, 10, 0.45, 12.0),
        _row("Kb", "K", 0.0, 10, None, 0.0),
    ]
    df = build_league_player_rankings(_df(rows), ["QB", "RB", "K", "BN"], 2)

    for kicker in ("Ka", "Kb"):
        row = _get_row(df, kicker)
        assert row["replacement_ppg"] == pytest.approx(0.0)
        assert pd.isna(row["scarcity_ratio"])
        assert pd.isna(row["z_scarcity"])

    # Ka keeps the other four; Kb also has no cv, so he keeps three.
    assert _get_row(df, "Ka")["components_used"] == 4
    assert _get_row(df, "Kb")["components_used"] == 3

    # QB/RB scarcity is unaffected: ratios 1.0 and 2.0, pool {1,1,2,2}.
    assert _get_row(df, "QBa")["scarcity_ratio"] == pytest.approx(1.0)
    assert _get_row(df, "QBa")["z_scarcity"] == pytest.approx(-1.0)
    assert _get_row(df, "RBa")["scarcity_ratio"] == pytest.approx(2.0)
    assert _get_row(df, "RBa")["z_scarcity"] == pytest.approx(1.0)
    assert _get_row(df, "QBa")["components_used"] == 5


def _degenerate_rows() -> list[dict]:
    """Three one-player positions -- every player is his own replacement.

    Every VORP and every rate VORP is 0, so both pools are zero-variance and
    ``z_value``/``z_rate`` are undefined for everyone. Every position's
    ``scarcity_ratio`` is 0 (best == replacement), so that pool is
    zero-variance too. WR1 additionally has no ``cv`` and no
    ``scoring_ceiling``, leaving him with no usable component at all.

    Reliability: usable -cv values {-0.2, -0.3}; mean -0.25; pstdev 0.05;
        z = +1 (QB1), -1 (RB1).
    Upside: ceilings above replacement {30-20, 30-15} = {10, 15}; mean 12.5;
        pstdev 2.5; z = -1 (QB1), +1 (RB1).
    Scores over the two surviving weights 0.20 + 0.15 = 0.35:
        QB1 (0.20*1 + 0.15*-1)/0.35 =  0.05/0.35
        RB1 (0.20*-1 + 0.15*1)/0.35 = -0.05/0.35
    """
    return [
        _row("QB1", "QB", 20.0, 10, 0.20, 30.0),
        _row("RB1", "RB", 15.0, 10, 0.30, 30.0),
        _row("WR1", "WR", 10.0, 10, None, None),
    ]


def test_player_with_no_usable_component_scores_nan_and_ranks_nan() -> None:
    df = build_league_player_rankings(
        _df(_degenerate_rows()), ["QB", "RB", "WR", "BN"], 1
    )

    wr1 = _get_row(df, "WR1")
    assert wr1["components_used"] == 0
    assert pd.isna(wr1["ranking_score"])
    assert pd.isna(wr1["league_rank"])
    assert pd.isna(wr1["position_rank"])
    assert pd.isna(wr1["league_percentile"])
    # Unscored players sort last.
    assert list(df["sleeper_player_id"])[-1] == "WR1"

    qb1 = _get_row(df, "QB1")
    rb1 = _get_row(df, "RB1")
    assert qb1["components_used"] == 2
    assert pd.isna(qb1["z_value"])
    assert pd.isna(qb1["z_rate"])
    assert pd.isna(qb1["z_scarcity"])
    assert qb1["ranking_score"] == pytest.approx(0.05 / 0.35)
    assert rb1["ranking_score"] == pytest.approx(-0.05 / 0.35)
    # n_ranked counts only the scored players (2), not WR1.
    assert qb1["league_rank"] == 1.0
    assert qb1["league_percentile"] == pytest.approx(1.0)
    assert rb1["league_rank"] == 2.0
    assert rb1["league_percentile"] == pytest.approx(0.5)


def test_zero_variance_component_is_nan_for_every_player() -> None:
    """Every player shares one ``cv``, so reliability can rank nobody."""
    rows = [dict(row, cv=0.40) for row in _toy_rows()]
    df = build_league_player_rankings(_df(rows), TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS)

    assert df["z_reliability"].isna().all()
    assert not df["z_reliability"].isin([math.inf, -math.inf]).any()
    assert list(df["components_used"]) == [4, 4, 4, 4, 4, 4]

    # QB1's other four components are unchanged; the weights renormalize
    # over 0.30 + 0.20 + 0.15 + 0.15 = 0.80.
    qb1 = _get_row(df, "QB1")
    assert qb1["ranking_score"] == pytest.approx(
        (0.30 * 0.5 + 0.20 * 0.5 + 0.15 * 1.4 + 0.15 * 0.0) / 0.80
    )


def test_single_player_frame_has_no_measurable_component() -> None:
    rows = [_row("QB1", "QB", 20.0, 10, 0.20, 30.0)]
    df = build_league_player_rankings(_df(rows), ["QB", "BN"], 1)

    assert len(df) == 1
    row = df.iloc[0]
    for column in ("z_value", "z_rate", "z_reliability", "z_upside", "z_scarcity"):
        assert pd.isna(row[column]), column
    assert row["components_used"] == 0
    assert pd.isna(row["ranking_score"])
    assert pd.isna(row["league_rank"])
    assert pd.isna(row["position_rank"])
    assert pd.isna(row["league_percentile"])
    floats = df.select_dtypes("float64")
    assert not floats.isin([math.inf, -math.inf]).any().any()


# --------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------


def test_weights_are_renormalized_when_they_do_not_sum_to_one() -> None:
    """``(2, 1)`` on value/upside is exactly ``(2/3, 1/3)``."""
    unnormalized = RankingWeights(
        value=2.0, rate=0.0, reliability=0.0, upside=1.0, scarcity=0.0
    )
    normalized = RankingWeights(
        value=2 / 3, rate=0.0, reliability=0.0, upside=1 / 3, scarcity=0.0
    )
    df = _toy_rankings(weights=unnormalized)
    same = _toy_rankings(weights=normalized)

    assert list(df["sleeper_player_id"]) == list(same["sleeper_player_id"])
    assert list(df["ranking_score"]) == pytest.approx(list(same["ranking_score"]))

    # QB1: (2 * 0.5 + 1 * 1.4) / 3 = 2.4 / 3 = 0.8
    qb1 = _get_row(df, "QB1")
    assert qb1["components_used"] == 2
    assert qb1["ranking_score"] == pytest.approx(0.8)
    # RB1: (2 * 2.0 + 1 * 1.0) / 3 = 5 / 3
    assert _get_row(df, "RB1")["ranking_score"] == pytest.approx(5 / 3)
    # RB2: (2 * -0.75 + 1 * -1.4) / 3 = -2.9 / 3
    assert _get_row(df, "RB2")["ranking_score"] == pytest.approx(-2.9 / 3)


def test_custom_weights_change_the_ordering() -> None:
    """All weight on reliability reorders the toy by ``-cv`` alone."""
    weights = RankingWeights(
        value=0.0, rate=0.0, reliability=1.0, upside=0.0, scarcity=0.0
    )
    df = _toy_rankings(weights=weights)

    # ranking_score is exactly z_reliability (one component, renormalized).
    assert list(df["ranking_score"]) == pytest.approx(list(df["z_reliability"]))
    assert list(df["components_used"]) == [1, 1, 1, 1, 1, 1]
    # Ordered by ascending cv: RB2 .15, QB1 .25, RB1 .45, QB3 .55, WR1 .75,
    # QB2 .85.
    assert list(df["sleeper_player_id"]) == ["RB2", "QB1", "RB1", "QB3", "WR1", "QB2"]
    assert _get_row(df, "RB2")["ranking_score"] == pytest.approx(1.4)
    assert _get_row(df, "QB2")["ranking_score"] == pytest.approx(-1.4)


def test_scarcity_weight_zero_recovers_the_untilted_reading() -> None:
    """``scarcity=0.0`` drops the double-counted component entirely.

    ``scarcity_ratio`` is a property of the *position*, so removing it
    shifts whole positions relative to each other rather than reordering
    players within one. In this toy it does not change the final order at
    all -- WR1 is last either way -- but it closes most of the gap the tilt
    had opened: WR1, the only player at a zero-scarcity position
    (``z_scarcity = -2``), trails QB3 by 0.340 under the defaults and by
    only 0.047 once the tilt is removed.

    "Level-shifting, not necessarily order-changing" is the honest claim to
    assert here. An assertion that some specific pair always flips would be
    over-fitted to this toy's numbers -- under the previous 0.40/0.25 weights
    exactly one pair (RB2/QB2) flipped, and it did so by 0.065, which is
    noise-level agreement, not a property of the metric.
    """
    weights = RankingWeights(
        value=0.30, rate=0.20, reliability=0.20, upside=0.15, scarcity=0.0
    )
    df = _toy_rankings(weights=weights)

    assert list(df["components_used"]) == [4, 4, 4, 4, 4, 4]
    # Surviving weights sum to 0.85 and are renormalized:
    #   QB2 (-0.075 - 0.05 - 0.28 + 0.03) / 0.85 = -0.375 / 0.85
    #   RB2 (-0.225 - 0.15 + 0.28 - 0.21) / 0.85 = -0.305 / 0.85
    #   QB3 (-0.225 - 0.15 - 0.04 - 0.15) / 0.85 = -0.565 / 0.85
    #   WR1 (-0.225 - 0.15 - 0.20 - 0.03) / 0.85 = -0.605 / 0.85
    assert _get_row(df, "QB2")["ranking_score"] == pytest.approx(-0.375 / 0.85)
    assert _get_row(df, "RB2")["ranking_score"] == pytest.approx(-0.305 / 0.85)
    assert _get_row(df, "QB3")["ranking_score"] == pytest.approx(-0.565 / 0.85)
    assert _get_row(df, "WR1")["ranking_score"] == pytest.approx(-0.605 / 0.85)
    assert list(df["sleeper_player_id"]) == ["RB1", "QB1", "RB2", "QB2", "QB3", "WR1"]

    # WR1's deficit to QB3 collapses once the position-level tilt is gone.
    tilted = _toy_rankings()
    tilted_gap = (
        _get_row(tilted, "QB3")["ranking_score"]
        - _get_row(tilted, "WR1")["ranking_score"]
    )
    untilted_gap = (
        _get_row(df, "QB3")["ranking_score"] - _get_row(df, "WR1")["ranking_score"]
    )
    assert tilted_gap == pytest.approx(0.34)
    assert untilted_gap == pytest.approx(0.04 / 0.85)
    assert untilted_gap < tilted_gap

    # The z-scores themselves are untouched -- only the blend changed.
    assert _get_row(df, "RB2")["z_scarcity"] == pytest.approx(1.0)


def test_invalid_weights_raise() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RankingWeights(value=-0.1)
    with pytest.raises(ValueError, match="non-negative"):
        RankingWeights(scarcity=float("nan"))
    with pytest.raises(ValueError, match="at least one positive weight"):
        RankingWeights(value=0.0, rate=0.0, reliability=0.0, upside=0.0, scarcity=0.0)


def test_default_weights_sum_to_one() -> None:
    assert DEFAULT_RANKING_WEIGHTS.total() == pytest.approx(1.0)
    assert DEFAULT_RANKING_WEIGHTS == RankingWeights(
        value=0.30, rate=0.20, reliability=0.20, upside=0.15, scarcity=0.15
    )
    # value + rate is capped at half the blend because the two are two
    # views of one quantity -- see the module docstring.
    assert DEFAULT_RANKING_WEIGHTS.value + DEFAULT_RANKING_WEIGHTS.rate == (
        pytest.approx(0.50)
    )


# --------------------------------------------------------------------------
# Rate shrinkage
# --------------------------------------------------------------------------


def _shrinkage_rows() -> list[dict]:
    """A two-game cameo against a ten-game regular.

    ``num_teams = 2``, ``[QB, RB, BN]`` -> cutoff 2 at both positions.
    replacement: QB 15.0 (QBb), RB 10.0 (RBb).
        QBa: 2 games, ppg 25 -> ppg_above_replacement = +10.0
        RBa: 10 games, ppg 18 -> ppg_above_replacement = +8.0
    With k = 4: QBa 2*10/(2+4) = 20/6 = 3.333...; RBa 10*8/14 = 80/14 =
    5.714... -- the cameo is shrunk below the regular.
    With k = 0: QBa 2*10/2 = 10.0; RBa 10*8/10 = 8.0 -- the raw rates, and
    the cameo is back on top.
    """
    return [
        _row("QBa", "QB", 25.0, 2, 0.20, 40.0),
        _row("QBb", "QB", 15.0, 10, 0.40, 25.0),
        _row("RBa", "RB", 18.0, 10, 0.30, 30.0),
        _row("RBb", "RB", 10.0, 10, 0.50, 18.0),
    ]


def test_shrinkage_pulls_a_small_sample_toward_replacement() -> None:
    df = build_league_player_rankings(_df(_shrinkage_rows()), ["QB", "RB", "BN"], 2)

    qba = _get_row(df, "QBa")
    rba = _get_row(df, "RBa")
    assert qba["games_played"] == pytest.approx(2.0)
    assert qba["ppg_above_replacement"] == pytest.approx(10.0)
    # The module docstring's worked example: 2 * 10 / (2 + 4) = 3.333...
    assert qba["shrunk_ppg_above_replacement"] == pytest.approx(20 / 6)
    assert rba["shrunk_ppg_above_replacement"] == pytest.approx(80 / 14)
    assert qba["shrunk_ppg_above_replacement"] < rba["shrunk_ppg_above_replacement"]
    assert qba["z_rate"] < rba["z_rate"]


def test_zero_shrinkage_is_exactly_the_raw_rate() -> None:
    df = build_league_player_rankings(
        _df(_shrinkage_rows()), ["QB", "RB", "BN"], 2, rate_shrinkage_games=0.0
    )

    qba = _get_row(df, "QBa")
    rba = _get_row(df, "RBa")
    assert qba["shrunk_ppg_above_replacement"] == pytest.approx(10.0)
    assert qba["shrunk_ppg_above_replacement"] == pytest.approx(
        qba["ppg_above_replacement"]
    )
    assert rba["shrunk_ppg_above_replacement"] == pytest.approx(8.0)
    # Ordering on the rate component flips relative to k = 4.
    assert qba["z_rate"] > rba["z_rate"]


def test_zero_games_and_zero_shrinkage_is_nan_not_a_zero_division() -> None:
    """``n + k == 0`` has no defined rate; the component is simply dropped.

    RBa is a hand-built degenerate row FFA-065 never emits (zero games, zero
    points). With ``rate_shrinkage_games = 0`` his shrunk rate divides 0 by
    0, which must be ``NaN`` rather than a ``ZeroDivisionError``. He is also
    the worst RB, so he *is* the RB replacement at 0.0 ppg, which makes
    FFA-068 emit ``scarcity_ratio = NaN`` for the whole RB position -- so
    two components drop for him, not one.
    """
    rows = [
        _row("QBa", "QB", 20.0, 10, 0.20, 30.0),
        _row("QBb", "QB", 10.0, 10, 0.40, 20.0),
        _row("RBa", "RB", 0.0, 0, 0.30, 5.0, total_points=0.0),
        _row("RBb", "RB", 5.0, 10, 0.50, 12.0),
    ]
    df = build_league_player_rankings(
        _df(rows), ["QB", "RB", "BN"], 2, rate_shrinkage_games=0.0
    )

    rba = _get_row(df, "RBa")
    assert rba["games_played"] == pytest.approx(0.0)
    assert pd.isna(rba["shrunk_ppg_above_replacement"])
    assert pd.isna(rba["z_rate"])
    assert pd.isna(rba["scarcity_ratio"])
    assert rba["components_used"] == 3


def test_negative_shrinkage_raises() -> None:
    with pytest.raises(ValueError, match="rate_shrinkage_games"):
        build_league_player_rankings(
            _df(_toy_rows()),
            TOY_ROSTER_POSITIONS,
            TOY_NUM_TEAMS,
            rate_shrinkage_games=-1.0,
        )


# --------------------------------------------------------------------------
# Modes
# --------------------------------------------------------------------------


def test_projected_mode_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="FFA-072"):
        _toy_rankings(mode="projected")
    # Raised before the data is even looked at, so the seam is stable.
    with pytest.raises(NotImplementedError):
        build_league_player_rankings(_df([]), ["QB"], 1, mode="projected")


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        _toy_rankings(mode="prospective")


def test_projections_df_is_ignored_in_retrospective_mode() -> None:
    with_projections = _toy_rankings(projections_df=pd.DataFrame({"season": [2025]}))
    assert list(with_projections["ranking_score"]) == pytest.approx(
        list(_toy_rankings()["ranking_score"])
    )


# --------------------------------------------------------------------------
# Frame shape, dtypes and input validation
# --------------------------------------------------------------------------


def test_output_columns_and_dtypes_are_pinned() -> None:
    df = _toy_rankings()

    assert list(df.columns) == LEAGUE_PLAYER_RANKING_COLUMNS
    assert df["season"].dtype == "int64"
    assert df["components_used"].dtype == "int64"
    for column in (
        "games_played",
        "points_per_game",
        "total_points",
        "replacement_ppg",
        "ppg_above_replacement",
        "shrunk_ppg_above_replacement",
        "points_above_replacement",
        "cv",
        "scoring_ceiling",
        "scarcity_ratio",
        "z_value",
        "z_rate",
        "z_reliability",
        "z_upside",
        "z_scarcity",
        "ranking_score",
        "league_rank",
        "position_rank",
        "league_percentile",
    ):
        assert df[column].dtype == "float64", column
    for column in ("sleeper_player_id", "player_name", "position", "nfl_team"):
        assert df[column].dtype == object, column


def test_empty_frame_returns_an_empty_typed_frame() -> None:
    df = build_league_player_rankings(_df([]), TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS)

    assert df.empty
    assert list(df.columns) == LEAGUE_PLAYER_RANKING_COLUMNS
    assert df["season"].dtype == "int64"
    assert df["components_used"].dtype == "int64"
    assert df["ranking_score"].dtype == "float64"
    assert df["league_rank"].dtype == "float64"
    assert df["sleeper_player_id"].dtype == object
    # An empty result never upcasts a concat with a real one.
    combined = pd.concat([df, _toy_rankings()], ignore_index=True)
    assert combined["season"].dtype == "int64"
    assert combined["ranking_score"].dtype == "float64"


def test_missing_required_column_raises() -> None:
    """``cv`` and ``scoring_ceiling`` are this module's own requirements."""
    frame = _df(_toy_rows()).drop(columns=["cv"])
    with pytest.raises(ValueError, match="cv"):
        build_league_player_rankings(frame, TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS)

    frame = _df(_toy_rows()).drop(columns=["scoring_ceiling", "total_points"])
    with pytest.raises(ValueError, match="scoring_ceiling"):
        build_league_player_rankings(frame, TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS)


def test_duplicate_player_season_rows_raise() -> None:
    """Inherited from FFA-068 and deliberately not caught."""
    rows = _toy_rows() + [dict(_toy_rows()[0])]
    with pytest.raises(ValueError, match="duplicate"):
        build_league_player_rankings(_df(rows), TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS)


def test_none_label_stays_none_alongside_real_labels() -> None:
    rows = _toy_rows()
    rows[0]["player_name"] = None
    df = build_league_player_rankings(_df(rows), TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS)

    assert _get_row(df, "QB1")["player_name"] is None
    assert _get_row(df, "QB2")["player_name"] == "Player"


def test_seasons_are_never_pooled() -> None:
    """Two seasons rank independently, each with its own z-score pool."""
    rows = _toy_rows() + [
        dict(row, season=2024, sleeper_player_id=row["sleeper_player_id"])
        for row in _toy_rows()
    ]
    df = build_league_player_rankings(_df(rows), TOY_ROSTER_POSITIONS, TOY_NUM_TEAMS)

    assert len(df) == 12
    assert list(df["season"]) == [2024] * 6 + [2025] * 6
    for season in (2024, 2025):
        season_df = df.loc[df["season"] == season]
        assert list(season_df["league_rank"]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        assert _get_row(df, "RB1", season=season)["ranking_score"] == pytest.approx(
            1.34
        )
