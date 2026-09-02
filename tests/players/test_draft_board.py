"""Tests for the 2026 draft board (FFA-076).

All tests operate on small hand-built ``market_df``/``prior_df`` frames --
no HTTP calls, no live Sleeper/nflverse/vendor access -- so every z-score,
blend, tier break, and VOR figure can be verified by independent hand
arithmetic (``statistics.fmean``/``pstdev`` computed directly in this file,
not imported from the module under test), per AGENTS.md's analytics-ticket
requirement for a hand-checkable toy example.

The single highest-priority behavior under test, called out explicitly in
the ticket: a player with no 2025 retrospective row (a rookie) must be
scored on market consensus alone and must not be penalized -- see
``test_rookie_with_no_prior_row_is_not_penalized`` and
``test_def_with_no_prior_data_is_not_dropped_from_board``.
"""

from __future__ import annotations

import math
from statistics import fmean, pstdev

import pandas as pd
import pytest

from fantasy_analyzer.players.draft_board import (
    DEFAULT_ADP_SD,
    DEFAULT_DRAFT_BOARD_WEIGHTS,
    DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS,
    DRAFT_BOARD_COLUMNS,
    DraftBoardWeights,
    build_draft_board,
    build_pick_availability_table,
    pick_availability_probability,
)
from fantasy_analyzer.players.draft_market import DRAFT_MARKET_POOL_COLUMNS


def _market_row(
    sleeper_player_id: str,
    position: str,
    adp: float | None = None,
    ecr: float | None = None,
    *,
    player_name: str | None = None,
    nfl_team: str | None = "AAA",
    bye_week: float | None = 7.0,
    adp_sd: float | None = None,
) -> dict:
    """A ``DRAFT_MARKET_POOL_COLUMNS``-shaped row (FFA-075's real contract).

    ``adp_best``/``adp_worst``/``ecr_sd``/``ecr_best``/``ecr_worst``/
    ``position_ecr`` are present (required by
    :data:`~fantasy_analyzer.players.draft_market.DRAFT_MARKET_POOL_COLUMNS`)
    but always ``None`` here -- this module never reads them.
    """
    return {
        "sleeper_player_id": sleeper_player_id,
        "player_name": player_name or sleeper_player_id,
        "position": position,
        "nfl_team": nfl_team,
        "adp": adp,
        "adp_sd": adp_sd,
        "adp_best": None,
        "adp_worst": None,
        "ecr": ecr,
        "ecr_sd": None,
        "ecr_best": None,
        "ecr_worst": None,
        "position_ecr": None,
        "bye_week": bye_week,
    }


def _prior_row(
    sleeper_player_id: str, ranking_score: float, league_rank: float
) -> dict:
    return {
        "sleeper_player_id": sleeper_player_id,
        "ranking_score": ranking_score,
        "league_rank": league_rank,
    }


def _get(df: pd.DataFrame, sleeper_player_id: str) -> pd.Series:
    match = df[df["sleeper_player_id"] == sleeper_player_id]
    assert len(match) == 1
    return match.iloc[0]


# ---------------------------------------------------------------------
# Empty / shape / dtype
# ---------------------------------------------------------------------


def test_empty_market_df_returns_empty_frame_with_columns_and_dtypes() -> None:
    market = pd.DataFrame(columns=DRAFT_MARKET_POOL_COLUMNS)
    result = build_draft_board(market)
    assert list(result.columns) == DRAFT_BOARD_COLUMNS
    assert result.empty
    assert result["components_used"].dtype == "int64"
    for column in (
        "adp",
        "ecr",
        "draft_score",
        "draft_rank",
        "adp_pool_rank",
        "tier",
        "vor",
    ):
        assert result[column].dtype == "float64"
    for column in ("sleeper_player_id", "player_name", "position", "nfl_team"):
        assert result[column].dtype == object


def test_missing_required_column_raises_value_error() -> None:
    """Validates against the full FFA-075 ``DRAFT_MARKET_POOL_COLUMNS``
    contract, not a bespoke subset -- a frame missing ``position`` (and
    everything else this toy frame omits) is rejected."""
    market = pd.DataFrame(
        [{"sleeper_player_id": "p1", "player_name": "P1", "adp": 1.0}]
    )
    with pytest.raises(ValueError, match="position"):
        build_draft_board(market)


def test_duplicate_sleeper_player_id_in_market_df_raises() -> None:
    market = pd.DataFrame(
        [
            _market_row("p1", "RB", adp=1.0, ecr=1.0),
            _market_row("p1", "RB", adp=2.0, ecr=2.0),
        ]
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_draft_board(market)


def test_duplicate_sleeper_player_id_in_prior_df_raises() -> None:
    market = pd.DataFrame([_market_row("p1", "RB", adp=1.0, ecr=1.0)])
    prior = pd.DataFrame([_prior_row("p1", 1.0, 1.0), _prior_row("p1", 2.0, 2.0)])
    with pytest.raises(ValueError, match="duplicate"):
        build_draft_board(market, prior)


def test_dtypes_on_a_populated_board() -> None:
    market = pd.DataFrame(
        [
            _market_row("p1", "RB", adp=1.0, ecr=1.0),
            _market_row("p2", "WR", adp=2.0, ecr=2.0),
        ]
    )
    result = build_draft_board(market)
    assert result["components_used"].dtype == "int64"
    for column in (
        "adp",
        "ecr",
        "z_adp",
        "z_ecr",
        "market_score",
        "draft_score",
        "draft_rank",
        "position_rank",
        "adp_pool_rank",
        "adp_delta",
        "tier",
        "vor",
    ):
        assert result[column].dtype == "float64"


# ---------------------------------------------------------------------
# The central requirement: rookies (and DEF, which has zero 2025 rows)
# are never penalized for missing retrospective data.
# ---------------------------------------------------------------------


def test_rookie_with_no_prior_row_is_not_penalized() -> None:
    """A player absent from ``prior_df`` scores on market alone.

    Drop-and-renormalize means the level-2 blend collapses to
    ``draft_score = market_score`` exactly for this player -- not a
    zero-filled or shrunk value.
    """
    market = pd.DataFrame(
        [
            _market_row("veteran", "WR", adp=10.0, ecr=9.0),
            _market_row("veteran2", "WR", adp=15.0, ecr=16.0),
            _market_row("rookie", "WR", adp=12.0, ecr=11.0),
        ]
    )
    # Two players with a prior row -- a population of one gives every
    # z-score no defined variance to measure against (see
    # ``_population_zscores``), so at least two are needed for this test
    # to exercise a *defined* z_prior rather than the separate "z-score
    # undefined for the whole pool" edge case.
    prior = pd.DataFrame(
        [_prior_row("veteran", 1.5, 20.0), _prior_row("veteran2", -0.8, 60.0)]
    )

    board = build_draft_board(market, prior)

    rookie = _get(board, "rookie")
    assert pd.isna(rookie["prior_ranking_score"])
    assert pd.isna(rookie["z_prior"])
    assert rookie["components_used"] == 1
    assert rookie["draft_score"] == pytest.approx(rookie["market_score"])

    veteran = _get(board, "veteran")
    assert veteran["components_used"] == 2
    assert veteran["draft_score"] != pytest.approx(veteran["market_score"])


def test_def_with_no_prior_data_is_not_dropped_from_board() -> None:
    """DEF has zero 2025 rows in the real retrospective frame (FFA-064's
    scoring engine cannot map any team-defense rule). A DEF player must
    still appear on the board, ranked on market consensus alone, exactly
    like a rookie.
    """
    market = pd.DataFrame(
        [
            _market_row("qb1", "QB", adp=5.0, ecr=4.0),
            _market_row("def1", "DEF", adp=140.0, ecr=150.0),
        ]
    )
    prior = pd.DataFrame([_prior_row("qb1", 2.0, 5.0)])  # no DEF row at all

    board = build_draft_board(market, prior)

    assert "DEF" in set(board["position"])
    def_row = _get(board, "def1")
    assert pd.isna(def_row["prior_ranking_score"])
    assert pd.isna(def_row["prior_league_rank"])
    assert def_row["components_used"] == 1
    assert def_row["draft_score"] == pytest.approx(def_row["market_score"])
    assert not pd.isna(def_row["draft_rank"])


def test_k_and_def_prior_forced_off_even_when_a_matching_prior_row_exists() -> None:
    """Even if a 2025 row happens to exist for a K/DEF player, the
    retrospective component is suppressed at the source (not merely
    down-weighted) -- see the module docstring's "K and DEF are excluded"
    section: K's 2025 scoring is partial (unmapped fgm/fum rules) and not
    comparable to QB/RB/WR/TE.
    """
    market = pd.DataFrame(
        [
            _market_row("k1", "K", adp=150.0, ecr=160.0),
            _market_row("def1", "DEF", adp=140.0, ecr=150.0),
        ]
    )
    # Both have a (hypothetical) 2025 row -- should be ignored anyway.
    prior = pd.DataFrame(
        [_prior_row("k1", 5.0, 1.0), _prior_row("def1", 5.0, 1.0)]
    )

    board = build_draft_board(market, prior)

    for player_id in ("k1", "def1"):
        row = _get(board, player_id)
        assert pd.isna(row["prior_ranking_score"])
        assert pd.isna(row["z_prior"])
        assert row["draft_score"] == pytest.approx(row["market_score"])


def test_retrospective_excluded_positions_is_overridable() -> None:
    """Passing an empty exclusion set restores the generic drop/keep path,
    so a K's prior row is used if the caller explicitly opts in."""
    market = pd.DataFrame(
        [
            _market_row("k1", "K", adp=150.0, ecr=160.0),
            _market_row("k2", "K", adp=160.0, ecr=170.0),
        ]
    )
    # Two prior rows -- see the population-size note in
    # ``test_rookie_with_no_prior_row_is_not_penalized``.
    prior = pd.DataFrame([_prior_row("k1", 3.0, 1.0), _prior_row("k2", -1.0, 30.0)])

    board = build_draft_board(
        market, prior, retrospective_excluded_positions=frozenset()
    )

    k1 = _get(board, "k1")
    assert k1["prior_ranking_score"] == pytest.approx(3.0)
    assert k1["components_used"] == 2
    assert DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS == frozenset({"K", "DEF"})


def test_prior_df_none_scores_the_whole_board_on_market_alone() -> None:
    market = pd.DataFrame(
        [
            _market_row("p1", "RB", adp=1.0, ecr=1.0),
            _market_row("p2", "WR", adp=5.0, ecr=6.0),
        ]
    )
    board = build_draft_board(market, None)
    assert (board["draft_score"] == board["market_score"]).all()
    assert (board["components_used"] == 1).all()
    assert board["prior_ranking_score"].isna().all()


# ---------------------------------------------------------------------
# Hand-computed market sub-blend (z_adp, z_ecr, market_score)
# ---------------------------------------------------------------------


def test_hand_computed_market_subblend() -> None:
    """Four players with symmetric adp/ecr, verified against independently
    computed log-transformed z-scores using ``statistics`` directly."""
    market = pd.DataFrame(
        [
            _market_row("p1", "RB", adp=1.0, ecr=2.0),
            _market_row("p2", "RB", adp=2.0, ecr=1.0),
            _market_row("p3", "RB", adp=4.0, ecr=8.0),
            _market_row("p4", "RB", adp=8.0, ecr=4.0),
        ]
    )
    board = build_draft_board(market)

    adp_pairs = [("p1", 1.0), ("p2", 2.0), ("p3", 4.0), ("p4", 8.0)]
    ecr_pairs = [("p1", 2.0), ("p2", 1.0), ("p3", 8.0), ("p4", 4.0)]
    adp_raw = {pid: -math.log(a) for pid, a in adp_pairs}
    ecr_raw = {pid: -math.log(e) for pid, e in ecr_pairs}
    adp_mean, adp_sd = fmean(adp_raw.values()), pstdev(adp_raw.values())
    ecr_mean, ecr_sd = fmean(ecr_raw.values()), pstdev(ecr_raw.values())

    w = DEFAULT_DRAFT_BOARD_WEIGHTS
    for pid in ("p1", "p2", "p3", "p4"):
        z_adp = (adp_raw[pid] - adp_mean) / adp_sd
        z_ecr = (ecr_raw[pid] - ecr_mean) / ecr_sd
        expected_market_score = (w.adp * z_adp + w.ecr * z_ecr) / (w.adp + w.ecr)
        row = _get(board, pid)
        assert row["z_adp"] == pytest.approx(z_adp)
        assert row["z_ecr"] == pytest.approx(z_ecr)
        assert row["market_score"] == pytest.approx(expected_market_score)
        # No prior_df -> draft_score is exactly market_score.
        assert row["draft_score"] == pytest.approx(expected_market_score)

    # p1/p2 are ADP/ECR mirror images of each other (adp<->ecr swapped),
    # so their market_scores are equal only if adp and ecr weights were
    # equal -- under the 0.6/0.4 default they are not, and p1 (better
    # ADP) should slightly outrank p2 (better ECR) since adp is weighted
    # higher.
    assert _get(board, "p1")["market_score"] > _get(board, "p2")["market_score"]


# ---------------------------------------------------------------------
# Missing adp / ecr (drop-and-renormalize at the market level)
# ---------------------------------------------------------------------


def test_missing_adp_falls_back_to_ecr_alone() -> None:
    market = pd.DataFrame(
        [
            _market_row("has_both", "WR", adp=5.0, ecr=5.0),
            _market_row("ecr_only", "WR", adp=None, ecr=6.0),
        ]
    )
    board = build_draft_board(market)
    row = _get(board, "ecr_only")
    assert pd.isna(row["z_adp"])
    assert not pd.isna(row["z_ecr"])
    assert row["market_score"] == pytest.approx(row["z_ecr"])


def test_missing_both_adp_and_ecr_with_no_prior_is_unscored() -> None:
    market = pd.DataFrame(
        [
            _market_row("scored", "WR", adp=5.0, ecr=5.0),
            _market_row("unscored", "WR", adp=None, ecr=None),
        ]
    )
    board = build_draft_board(market)
    row = _get(board, "unscored")
    assert pd.isna(row["market_score"])
    assert pd.isna(row["draft_score"])
    assert row["components_used"] == 0
    assert pd.isna(row["draft_rank"])
    # Unscored players sort last.
    assert board.iloc[-1]["sleeper_player_id"] == "unscored"


# ---------------------------------------------------------------------
# adp_delta sign convention
# ---------------------------------------------------------------------


def test_adp_delta_sign_convention() -> None:
    """Positive adp_delta = this board ranks the player better than the
    market does (a VALUE); negative = the market ranks them better than
    this board does (a REACH relative to this board).

    Four players with ADP order 1 < 2 < 3 < 4 (``star1`` .. ``star3``,
    ``reach``); a large retrospective boost on ``star3`` (market's worst
    of the four) pulls it ahead of ``reach`` (market's 3rd-best, but with
    no retrospective data at all) on the final board.
    """
    market = pd.DataFrame(
        [
            _market_row("star1", "RB", adp=1.0, ecr=1.0),
            _market_row("star2", "RB", adp=2.0, ecr=2.0),
            _market_row("reach", "RB", adp=3.0, ecr=3.0),
            _market_row("star3", "RB", adp=4.0, ecr=4.0),
        ]
    )
    prior = pd.DataFrame(
        [
            _prior_row("star1", 10.0, 1.0),
            _prior_row("star2", 8.0, 2.0),
            _prior_row("star3", 30.0, 3.0),
        ]
    )
    board = build_draft_board(market, prior)

    reach_row = _get(board, "reach")
    star3_row = _get(board, "star3")

    # star3 (worst ADP of the group) leapfrogs reach (better ADP, no
    # retrospective backing) on the final board.
    assert star3_row["draft_rank"] < reach_row["draft_rank"]

    assert star3_row["adp_delta"] == pytest.approx(
        star3_row["adp"] - star3_row["draft_rank"]
    )
    assert star3_row["adp_delta"] > 0  # this board likes star3 more -> VALUE

    assert reach_row["adp_delta"] == pytest.approx(
        reach_row["adp"] - reach_row["draft_rank"]
    )
    assert reach_row["adp_delta"] < 0  # the market likes reach more -> REACH


def test_adp_delta_is_nan_when_adp_missing() -> None:
    market = pd.DataFrame(
        [
            _market_row("has_adp", "TE", adp=30.0, ecr=30.0),
            _market_row("no_adp", "TE", adp=None, ecr=32.0),
        ]
    )
    board = build_draft_board(market)
    assert pd.isna(_get(board, "no_adp")["adp_delta"])
    assert pd.isna(_get(board, "no_adp")["adp_pool_rank"])


def test_no_adp_players_do_not_shift_adp_having_deltas() -> None:
    """The regression this ticket was fixed for: ``adp_delta`` must never
    be computed against the full-board ``draft_rank``, because a no-ADP
    player who legitimately outranks (or underranks) several ADP-having
    players on ``draft_score`` shifts everyone's ``draft_rank`` without
    touching their ``adp`` at all. ``adp_pool_rank``/``adp_delta`` -- based
    on a rank restricted to the ADP-having subset -- must be completely
    unaffected by such insertions.
    """
    adp_having = [
        _market_row("p1", "RB", adp=1.0, ecr=4.0),
        _market_row("p2", "RB", adp=2.0, ecr=3.0),
        _market_row("p3", "RB", adp=3.0, ecr=2.0),
        _market_row("p4", "RB", adp=4.0, ecr=1.0),
    ]
    board_without = build_draft_board(pd.DataFrame(adp_having))

    # Two no-ADP, no-ECR "phantom" players scored purely on a prior
    # retrospective score, one high enough to outrank every ADP-having
    # player on draft_score, one low enough to sit below all of them.
    # Because they carry no adp/ecr, they cannot perturb the adp/ecr
    # z-score population the four real players are scored against; because
    # none of the four real players has a prior row, they cannot perturb
    # a z_prior term the four real players use either.
    phantoms = [
        _market_row("phantom_high", "RB", adp=None, ecr=None),
        _market_row("phantom_low", "RB", adp=None, ecr=None),
    ]
    prior = pd.DataFrame(
        [
            _prior_row("phantom_high", 100.0, 1.0),
            _prior_row("phantom_low", -100.0, 2.0),
        ]
    )
    board_with = build_draft_board(pd.DataFrame(adp_having + phantoms), prior)

    # Confirm the phantom actually did shift draft_rank -- otherwise this
    # test would not be exercising the bug it guards against.
    phantom_row = _get(board_with, "phantom_high")
    assert phantom_row["draft_rank"] == 1.0
    for player_id in ("p1", "p2", "p3", "p4"):
        assert (
            _get(board_with, player_id)["draft_rank"]
            == _get(board_without, player_id)["draft_rank"] + 1
        )

    # adp_pool_rank and adp_delta are untouched by the phantoms' presence.
    for player_id in ("p1", "p2", "p3", "p4"):
        before = _get(board_without, player_id)
        after = _get(board_with, player_id)
        assert after["adp_pool_rank"] == pytest.approx(before["adp_pool_rank"])
        assert after["adp_delta"] == pytest.approx(before["adp_delta"])

    # The phantoms themselves have no ADP, so no delta is defined for them.
    assert pd.isna(_get(board_with, "phantom_high")["adp_delta"])
    assert pd.isna(_get(board_with, "phantom_low")["adp_delta"])


# ---------------------------------------------------------------------
# Ties: draft_rank, position_rank, and tier
# ---------------------------------------------------------------------


def test_tied_draft_scores_share_a_rank_and_the_next_rank_skips() -> None:
    market = pd.DataFrame(
        [
            _market_row("a", "WR", adp=10.0, ecr=10.0),
            _market_row("b", "WR", adp=10.0, ecr=10.0),  # identical -> tie
            _market_row("c", "WR", adp=30.0, ecr=30.0),
        ]
    )
    board = build_draft_board(market).sort_values("draft_rank")
    a, b, c = (_get(board, pid) for pid in ("a", "b", "c"))
    assert a["draft_score"] == pytest.approx(b["draft_score"])
    assert a["draft_rank"] == b["draft_rank"] == 1.0
    assert c["draft_rank"] == 3.0  # rank 2 is skipped, not reused


def test_tied_draft_scores_never_start_a_new_tier() -> None:
    market = pd.DataFrame(
        [
            _market_row("a", "WR", adp=10.0, ecr=10.0),
            _market_row("b", "WR", adp=10.0, ecr=10.0),
            # A third, distinctly-valued player so the pool has nonzero
            # variance and z_adp/z_ecr are actually defined for a and b.
            _market_row("c", "WR", adp=30.0, ecr=30.0),
        ]
    )
    board = build_draft_board(market)
    assert _get(board, "a")["tier"] == _get(board, "b")["tier"]


# ---------------------------------------------------------------------
# Tier break rule -- hand-computed worked example
# ---------------------------------------------------------------------


def test_tier_break_rule_hand_computed() -> None:
    """Force ``draft_score`` to equal a z-scored ``ranking_score`` exactly
    by setting the market weight to 0, so the tier boundaries can be
    checked against an independently computed z-score list.
    """
    market = pd.DataFrame(
        [
            _market_row("rb_a", "RB", adp=1.0, ecr=1.0),
            _market_row("rb_b", "RB", adp=2.0, ecr=2.0),
            _market_row("rb_c", "RB", adp=3.0, ecr=3.0),
            _market_row("rb_d", "RB", adp=4.0, ecr=4.0),
        ]
    )
    prior = pd.DataFrame(
        [
            _prior_row("rb_a", 210.0, 1.0),
            _prior_row("rb_b", 205.0, 2.0),
            _prior_row("rb_c", 140.0, 3.0),
            _prior_row("rb_d", 138.0, 4.0),
        ]
    )
    weights = DraftBoardWeights(market=0.0, prior=1.0)
    board = build_draft_board(market, prior, weights=weights)

    raw = [210.0, 205.0, 140.0, 138.0]
    mean, sd = fmean(raw), pstdev(raw)
    z = {
        "rb_a": (210.0 - mean) / sd,
        "rb_b": (205.0 - mean) / sd,
        "rb_c": (140.0 - mean) / sd,
        "rb_d": (138.0 - mean) / sd,
    }
    for pid, expected in z.items():
        assert _get(board, pid)["draft_score"] == pytest.approx(expected)

    # Gaps: a-b = 0.146 (<0.30, same tier); b-c = 1.895 (>=0.30, new
    # tier); c-d = 0.058 (<0.30, same tier) -> tiers [1, 1, 2, 2].
    assert z["rb_a"] - z["rb_b"] < 0.30
    assert z["rb_b"] - z["rb_c"] >= 0.30
    assert z["rb_c"] - z["rb_d"] < 0.30
    assert _get(board, "rb_a")["tier"] == _get(board, "rb_b")["tier"] == 1.0
    assert _get(board, "rb_c")["tier"] == _get(board, "rb_d")["tier"] == 2.0


def test_unscored_players_get_nan_tier() -> None:
    market = pd.DataFrame(
        [
            _market_row("scored", "WR", adp=5.0, ecr=5.0),
            _market_row("scored2", "WR", adp=25.0, ecr=25.0),
            _market_row("unscored", "WR", adp=None, ecr=None),
        ]
    )
    board = build_draft_board(market)
    assert pd.isna(_get(board, "unscored")["tier"])
    assert not pd.isna(_get(board, "scored")["tier"])


# ---------------------------------------------------------------------
# VOR -- hand-computed against a small, non-clamped replacement rank
# ---------------------------------------------------------------------


def test_vor_hand_computed_with_a_non_clamped_replacement_rank() -> None:
    """1 team, 2 RB starting slots, no flex -> cutoff = 1 * 2 = 2, so the
    *second*-best RB (not the worst) is the replacement player."""
    market = pd.DataFrame(
        [
            _market_row("rb_a", "RB", adp=1.0, ecr=1.0),
            _market_row("rb_b", "RB", adp=2.0, ecr=2.0),
            _market_row("rb_c", "RB", adp=3.0, ecr=3.0),
            _market_row("rb_d", "RB", adp=4.0, ecr=4.0),
        ]
    )
    prior = pd.DataFrame(
        [
            _prior_row("rb_a", 210.0, 1.0),
            _prior_row("rb_b", 205.0, 2.0),
            _prior_row("rb_c", 140.0, 3.0),
            _prior_row("rb_d", 138.0, 4.0),
        ]
    )
    weights = DraftBoardWeights(market=0.0, prior=1.0)
    board = build_draft_board(
        market, prior, weights=weights, roster_positions=["RB", "RB"], num_teams=1
    )

    raw = [210.0, 205.0, 140.0, 138.0]
    mean, sd = fmean(raw), pstdev(raw)
    z = {v: (r - mean) / sd for v, r in zip(["rb_a", "rb_b", "rb_c", "rb_d"], raw)}
    replacement = z["rb_b"]  # rank 2 of 4, the cutoff

    for pid in z:
        expected_vor = z[pid] - replacement
        assert _get(board, pid)["vor"] == pytest.approx(expected_vor)
    assert _get(board, "rb_b")["vor"] == pytest.approx(0.0)
    assert _get(board, "rb_a")["vor"] > 0
    assert _get(board, "rb_c")["vor"] < 0


def test_vor_clamps_to_worst_scored_player_when_field_is_smaller_than_cutoff() -> None:
    """Default 12-team config (RB cutoff 36) against a 2-player pool: the
    replacement rank clamps to the field size (the worst scored player)."""
    market = pd.DataFrame(
        [
            _market_row("rb_a", "RB", adp=1.0, ecr=1.0),
            _market_row("rb_b", "RB", adp=50.0, ecr=50.0),
        ]
    )
    board = build_draft_board(market)
    worst = board.sort_values("draft_score").iloc[0]
    assert worst["vor"] == pytest.approx(0.0)


def test_vor_is_nan_when_position_has_no_scored_players() -> None:
    market = pd.DataFrame([_market_row("def1", "DEF", adp=None, ecr=None)])
    board = build_draft_board(market)
    assert pd.isna(_get(board, "def1")["vor"])


# ---------------------------------------------------------------------
# DraftBoardWeights validation
# ---------------------------------------------------------------------


def test_weights_reject_negative_value() -> None:
    with pytest.raises(ValueError):
        DraftBoardWeights(adp=-0.1)


def test_weights_reject_both_adp_and_ecr_zero() -> None:
    with pytest.raises(ValueError):
        DraftBoardWeights(adp=0.0, ecr=0.0)


def test_weights_reject_both_market_and_prior_zero() -> None:
    with pytest.raises(ValueError):
        DraftBoardWeights(market=0.0, prior=0.0)


def test_weights_need_not_sum_to_one() -> None:
    # 2:1 ratio identical to 0.6667:0.3333 after renormalization.
    market = pd.DataFrame(
        [
            _market_row("p1", "RB", adp=1.0, ecr=2.0),
            _market_row("p2", "RB", adp=3.0, ecr=4.0),
        ]
    )
    board_a = build_draft_board(
        market, weights=DraftBoardWeights(adp=2.0, ecr=1.0, market=1.0, prior=0.0)
    )
    board_b = build_draft_board(
        market, weights=DraftBoardWeights(adp=2 / 3, ecr=1 / 3, market=1.0, prior=0.0)
    )
    p1_a = board_a[board_a["sleeper_player_id"] == "p1"].iloc[0]
    p1_b = board_b[board_b["sleeper_player_id"] == "p1"].iloc[0]
    assert p1_a["market_score"] == pytest.approx(p1_b["market_score"])


# ---------------------------------------------------------------------
# Pick availability
# ---------------------------------------------------------------------


def test_pick_availability_at_exact_adp_is_half() -> None:
    # z = 0 -> Phi(0) = 0.5 -> availability = 0.5.
    prob = pick_availability_probability(20, adp=20.0, adp_sd=5.0)
    assert prob == pytest.approx(0.5)


def test_pick_availability_decreases_as_pick_number_increases() -> None:
    early = pick_availability_probability(10, adp=20.0, adp_sd=5.0)
    late = pick_availability_probability(40, adp=20.0, adp_sd=5.0)
    assert early > 0.5 > late


def test_pick_availability_missing_adp_is_nan() -> None:
    assert math.isnan(pick_availability_probability(10, adp=None))


def test_pick_availability_falls_back_to_default_sd() -> None:
    with_none = pick_availability_probability(25, adp=20.0, adp_sd=None)
    with_default = pick_availability_probability(25, adp=20.0, adp_sd=DEFAULT_ADP_SD)
    assert with_none == pytest.approx(with_default)


def test_pick_availability_rejects_pick_number_below_one() -> None:
    with pytest.raises(ValueError):
        pick_availability_probability(0, adp=5.0)


def test_pick_availability_table_shape() -> None:
    board = build_draft_board(
        pd.DataFrame(
            [
                _market_row("p1", "RB", adp=5.0, ecr=5.0, adp_sd=2.0),
                _market_row("p2", "WR", adp=20.0, ecr=20.0, adp_sd=4.0),
            ]
        )
    )
    table = build_pick_availability_table(board, [5, 20, 29])
    assert "prob_available_pick_5" in table.columns
    assert "prob_available_pick_20" in table.columns
    assert "prob_available_pick_29" in table.columns
    # p1's adp (5) means near-certain gone by pick 29, definitely by 20.
    p1 = table[table["sleeper_player_id"] == "p1"].iloc[0]
    assert p1["prob_available_pick_29"] < p1["prob_available_pick_5"]
