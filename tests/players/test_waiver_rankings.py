"""Tests for waiver-wire value ranking (FFA-092).

All tests operate on hand-built free-agent pools and small in-memory
scored-player-week frames -- no HTTP calls, no live nflverse/Sleeper access
-- so the shrinkage blend, replacement level, and VORP ranking can all be
verified by hand arithmetic. The toy scenario mirrors the module
docstring's worked example.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from fantasy_analyzer.players.free_agents import FREE_AGENT_POOL_COLUMNS
from fantasy_analyzer.players.ros_projection import ShrinkageParameters
from fantasy_analyzer.players.waiver_rankings import (
    DEFAULT_ABSENT_PRIOR_RATIO,
    FREE_AGENT_PROJECTION_COLUMNS,
    OPPORTUNITY_SUMMARY_COLUMNS,
    WAIVER_WIRE_RANKING_COLUMNS,
    build_free_agent_ros_projections,
    build_projection_performance_frame,
    build_waiver_wire_rankings,
    confidence_tier,
)

PARAMETERS = ShrinkageParameters(n0_by_position={"WR": 3.0}, default_n0=3.0)


def _pool_row(
    player_id: str,
    position: str,
    gsis_id: str | None,
    has_crosswalk: bool,
    full_name: str = "Player",
    team: str = "SF",
    status: str = "Active",
    player_owned_avg: float | None = None,
) -> dict:
    return {
        "player_id": player_id,
        "full_name": full_name,
        "position": position,
        "team": team,
        "status": status,
        "gsis_id": gsis_id,
        "has_crosswalk": has_crosswalk,
        "player_owned_avg": player_owned_avg,
    }


def _free_agent_pool(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=FREE_AGENT_POOL_COLUMNS)
    frame["has_crosswalk"] = frame["has_crosswalk"].astype(bool)
    frame["player_owned_avg"] = frame["player_owned_avg"].astype("float64")
    return frame


def _week_row(gsis_id: str, season: int, week: int, points: float) -> dict:
    return {
        "season": season,
        "week": week,
        "player_id": gsis_id,
        "player_name": "NFL Player",
        "position": "WR",
        "fantasy_points": points,
    }


# The toy scenario: three WR free agents with a crosswalk match and one
# without. See the module docstring's worked example for WR_A.
POOL = _free_agent_pool(
    [
        _pool_row("10", "WR", "gwa", True, full_name="WR A", player_owned_avg=12.0),
        _pool_row("11", "WR", "gwb", True, full_name="WR B", player_owned_avg=3.0),
        _pool_row("12", "WR", "gwc", True, full_name="WR C", player_owned_avg=1.0),
        _pool_row("13", "WR", None, False, full_name="WR D (no crosswalk)"),
    ]
)

SCORED_WEEKS = pd.DataFrame(
    [
        _week_row("gwa", 2025, 1, 8.0),
        _week_row("gwa", 2025, 2, 12.0),
        _week_row("gwa", 2025, 3, 10.0),
        _week_row("gwa", 2025, 4, 6.0),
        # gwb and gwc: no rows this season -- zero games to date.
    ]
)

PRIOR_SEASON_WEEKS = pd.DataFrame(
    [
        # Four identical weeks: gwb's prior ppg is 5.0 either way, but four
        # games clears DEFAULT_MIN_PRIOR_GAMES so the prior is *trusted*
        # and the toy arithmetic below is the pure blend. See
        # test_thin_prior_season_falls_back_to_positional_mean for the
        # under-sampled case.
        _week_row("gwb", 2024, 1, 5.0),
        _week_row("gwb", 2024, 2, 5.0),
        _week_row("gwb", 2024, 3, 5.0),
        _week_row("gwb", 2024, 4, 5.0),
        # gwc has no prior-season row either -- falls back to the
        # positional mean among free agents with games to date.
    ]
)


# --------------------------------------------------------------------------
# confidence_tier
# --------------------------------------------------------------------------


def test_confidence_tier_thresholds() -> None:
    assert confidence_tier(0) == "low"
    assert confidence_tier(2) == "low"
    assert confidence_tier(3) == "medium"
    assert confidence_tier(7) == "medium"
    assert confidence_tier(8) == "high"
    assert confidence_tier(100) == "high"


def test_confidence_tier_undefined_games_to_date() -> None:
    assert confidence_tier(None) is None
    assert confidence_tier(float("nan")) is None


# --------------------------------------------------------------------------
# build_free_agent_ros_projections
# --------------------------------------------------------------------------


def test_empty_pool_returns_empty_frame() -> None:
    result = build_free_agent_ros_projections(
        _free_agent_pool([]), SCORED_WEEKS, 2025, 4, PARAMETERS
    )
    assert result.empty
    assert list(result.columns) == FREE_AGENT_PROJECTION_COLUMNS


def test_cutoff_week_below_one_raises() -> None:
    with pytest.raises(ValueError, match="cutoff_week"):
        build_free_agent_ros_projections(POOL, SCORED_WEEKS, 2025, 0, PARAMETERS)


def test_toy_projection_matches_module_docstring_worked_example() -> None:
    """WR A: 4 games at 9.0 ppg, alone in the observed pool.

    w = 4 / (4 + 3) = 4/7. With only WR_A having games this season, the
    positional-mean fallback for his own (absent) prior equals his own
    ppg_to_date (9.0), so ``projected_ppg`` collapses to 9.0 regardless of
    the weight -- exactly the module docstring's worked example.
    """
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    assert len(result) == 4

    wa = result.loc[result["player_id"] == "10"].iloc[0]
    assert wa["games_to_date"] == pytest.approx(4.0)
    assert wa["ppg_to_date"] == pytest.approx(9.0)
    assert wa["prior_resolved_ppg"] == pytest.approx(9.0)
    assert wa["blend_weight"] == pytest.approx(4.0 / 7.0)
    assert wa["projected_ppg"] == pytest.approx(9.0)
    assert wa["remaining_games"] == pytest.approx(13.0)
    assert wa["projected_ros_points"] == pytest.approx(117.0)
    assert wa["confidence_tier"] == "medium"


def test_zero_games_free_agent_uses_prior_season():
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    wb = result.loc[result["player_id"] == "11"].iloc[0]
    assert wb["games_to_date"] == pytest.approx(0.0)
    assert pd.isna(wb["ppg_to_date"])
    assert wb["prior_season_ppg"] == pytest.approx(5.0)
    assert wb["prior_resolved_ppg"] == pytest.approx(5.0)
    assert wb["blend_weight"] == pytest.approx(0.0)
    assert wb["projected_ppg"] == pytest.approx(5.0)
    assert wb["projected_ros_points"] == pytest.approx(65.0)
    assert wb["confidence_tier"] == "low"


def test_zero_games_no_prior_gets_the_absent_prior():
    """FFA-104: no games and no prior resolves *below* the positional mean.

    The positional mean among free agents with >= 1 game this season is
    WR_A alone at 9.0. WR_C has neither games nor a prior, so with no usage
    model supplied he gets ``DEFAULT_ABSENT_PRIOR_RATIO["WR"] * 9.0 = 0.41
    * 9.0 = 3.69`` -- not the 9.0 the pre-FFA-104 fallback gave him.
    """
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    wc = result.loc[result["player_id"] == "12"].iloc[0]
    assert wc["games_to_date"] == pytest.approx(0.0)
    assert pd.isna(wc["prior_season_ppg"])
    assert DEFAULT_ABSENT_PRIOR_RATIO["WR"] == pytest.approx(0.41)
    assert wc["prior_resolved_ppg"] == pytest.approx(3.69)
    assert wc["projected_ppg"] == pytest.approx(3.69)
    assert wc["eb_projected_ppg"] == pytest.approx(3.69)
    assert wc["projection_model"] == "absent_prior"
    assert wc["confidence_tier"] == "low"


def test_no_crosswalk_free_agent_gets_null_projection_not_dropped():
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    assert len(result) == 4
    wd = result.loc[result["player_id"] == "13"].iloc[0]
    assert pd.isna(wd["games_to_date"])
    assert pd.isna(wd["ppg_to_date"])
    assert pd.isna(wd["projected_ppg"])
    assert pd.isna(wd["projected_ros_points"])
    assert wd["confidence_tier"] is None
    # remaining_games is a pure schedule fact -- still populated.
    assert wd["remaining_games"] == pytest.approx(13.0)


def test_season_end_week_controls_remaining_games() -> None:
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, season_end_week=10
    )
    wa = result.loc[result["player_id"] == "10"].iloc[0]
    assert wa["remaining_games"] == pytest.approx(6.0)


def test_cutoff_at_or_past_season_end_gives_zero_remaining_games() -> None:
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 17, PARAMETERS, season_end_week=17
    )
    assert (result["remaining_games"] == 0.0).all()


# --------------------------------------------------------------------------
# build_waiver_wire_rankings
# --------------------------------------------------------------------------

ROSTER_POSITIONS = ["QB", "RB", "WR", "BN"]
NUM_TEAMS = 3


def test_empty_pool_returns_empty_ranking_frame() -> None:
    result = build_waiver_wire_rankings(
        _free_agent_pool([]),
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
    )
    assert result.empty
    assert list(result.columns) == WAIVER_WIRE_RANKING_COLUMNS


def test_toy_waiver_ranking_vorp_and_ties() -> None:
    """Field of 3 WRs with a projection (A, B, C); starter cutoff clamps to 3.

    WR_C has no games and no prior, so (FFA-104) he projects at the
    absent prior ``0.41 * 9.0 = 3.69`` ppg and is now the replacement
    level. ``points_above_replacement = 13 * (ppg - 3.69)``:

        WR_A: 13 * 5.31 = 69.03   WR_B: 13 * 1.31 = 17.03   WR_C: 0

    Before FFA-104, WR_C inherited the positional mean (9.0) and tied WR_A
    for rank 1 -- the defect: a player with no data ranked with the best
    free agent. Ties are covered by
    ``test_absent_prior_players_tie_below_players_with_evidence``. WR_D has
    no crosswalk and so no projection at all -- he is excluded from the
    VORP computation entirely and gets ``NaN`` in every VORP column and
    ``waiver_rank``, sorting last, per the "null, not dropped" convention.
    """
    result = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    assert len(result) == 4

    by_id = {row["player_id"]: row for _, row in result.iterrows()}

    assert by_id["10"]["replacement_ppg"] == pytest.approx(3.69)
    assert by_id["10"]["points_above_replacement"] == pytest.approx(69.03)
    assert by_id["11"]["points_above_replacement"] == pytest.approx(17.03)
    assert by_id["12"]["points_above_replacement"] == pytest.approx(0.0)

    assert by_id["10"]["waiver_rank"] == pytest.approx(1.0)
    assert by_id["11"]["waiver_rank"] == pytest.approx(2.0)
    assert by_id["12"]["waiver_rank"] == pytest.approx(3.0)
    assert math.isnan(by_id["13"]["waiver_rank"])

    # Explanatory columns survive the merge.
    assert by_id["10"]["blend_weight"] == pytest.approx(4.0 / 7.0)
    assert by_id["10"]["confidence_tier"] == "medium"
    assert by_id["11"]["confidence_tier"] == "low"

    # Unranked player (no crosswalk) sorts last.
    assert result.iloc[-1]["player_id"] == "13"

    # player_owned_avg carried through from the pool.
    assert by_id["10"]["player_owned_avg"] == pytest.approx(12.0)


def test_no_projectable_players_returns_all_null_vorp() -> None:
    only_no_crosswalk = _free_agent_pool(
        [_pool_row("99", "WR", None, False, full_name="Nobody")]
    )
    result = build_waiver_wire_rankings(
        only_no_crosswalk,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
    )
    assert len(result) == 1
    assert math.isnan(result.iloc[0]["waiver_rank"])
    assert math.isnan(result.iloc[0]["points_above_replacement"])


# --------------------------------------------------------------------------
# build_projection_performance_frame
# --------------------------------------------------------------------------


def test_build_projection_performance_frame_shape_and_values() -> None:
    waiver_df = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    performance_df = build_projection_performance_frame(waiver_df, season=2025)

    assert set(
        [
            "season",
            "sleeper_player_id",
            "player_name",
            "position",
            "nfl_team",
            "games_played",
            "points_per_game",
            "total_points",
        ]
    ).issubset(performance_df.columns)
    assert (performance_df["season"] == 2025).all()

    wa = performance_df.loc[performance_df["sleeper_player_id"] == "10"].iloc[0]
    assert wa["games_played"] == pytest.approx(13.0)
    assert wa["points_per_game"] == pytest.approx(9.0)
    assert wa["total_points"] == pytest.approx(117.0)

    # No-crosswalk player is included, not dropped -- NaN points_per_game.
    wd = performance_df.loc[performance_df["sleeper_player_id"] == "13"].iloc[0]
    assert pd.isna(wd["points_per_game"])


def test_build_projection_performance_frame_empty_input() -> None:
    result = build_projection_performance_frame(pd.DataFrame(), season=2025)
    assert result.empty
    assert "sleeper_player_id" in result.columns


# --------------------------------------------------------------------------
# FFA-096 -- minimum prior-season games guard
# --------------------------------------------------------------------------


def _thin_prior_pool() -> pd.DataFrame:
    """WR A (4 games this season) plus WR E, whose only prior game was huge."""
    return _free_agent_pool(
        [
            _pool_row("10", "WR", "gwa", True, full_name="WR A"),
            _pool_row("14", "WR", "gwe", True, full_name="WR E (one prior game)"),
        ]
    )


THIN_PRIOR_WEEKS = pd.DataFrame([_week_row("gwe", 2024, 18, 30.0)])


def test_thin_prior_season_falls_back_to_positional_mean() -> None:
    """A one-game prior is reported but not trusted (FFA-096).

    WR E has no 2025 games, so ``w = 0`` exactly and his projection *is*
    his resolved prior. His raw prior is 30.0 ppg off a single week-18
    2024 appearance -- the Phil Mafah case from
    :data:`DEFAULT_MIN_PRIOR_GAMES`'s docstring. With the guard at its
    default of 4 games the prior is untrusted, and with no games either he
    is an absent-prior player (FFA-104): ``0.41 *`` the positional mean
    among WRs with games to date (WR A's 9.0) ``= 3.69``.

    The raw figures survive in the output so a board can show why: the
    guard nulls the *resolved* prior, never the reported one.
    """
    result = build_free_agent_ros_projections(
        _thin_prior_pool(),
        SCORED_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=THIN_PRIOR_WEEKS,
    )
    we = result.loc[result["player_id"] == "14"].iloc[0]

    assert we["prior_season_ppg"] == pytest.approx(30.0)
    assert we["prior_season_games"] == pytest.approx(1.0)
    assert we["blend_weight"] == pytest.approx(0.0)
    assert we["prior_resolved_ppg"] == pytest.approx(3.69)
    assert we["projected_ppg"] == pytest.approx(3.69)
    assert we["projection_model"] == "absent_prior"


def test_min_prior_games_zero_restores_the_untrusted_prior() -> None:
    """``min_prior_games=0`` disables the guard entirely."""
    result = build_free_agent_ros_projections(
        _thin_prior_pool(),
        SCORED_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=THIN_PRIOR_WEEKS,
        min_prior_games=0,
    )
    we = result.loc[result["player_id"] == "14"].iloc[0]
    assert we["prior_resolved_ppg"] == pytest.approx(30.0)
    assert we["projected_ppg"] == pytest.approx(30.0)


def test_min_prior_games_guard_applies_to_players_with_games_to_date() -> None:
    """The guard also reaches the blended population, not just zero-game rows.

    WR A has 4 games at 9.0 ppg and (here) a single 30.0-ppg prior game.
    Guarded, his prior resolves to the positional mean -- which, with WR A
    the only WR who has played, is his own 9.0 -- so the blend is
    ``0.5714 * 9.0 + 0.4286 * 9.0 = 9.0``. Unguarded the prior is trusted
    and the blend pulls upward: ``0.5714 * 9.0 + 0.4286 * 30.0 = 18.0``.
    """
    pool = _free_agent_pool([_pool_row("10", "WR", "gwa", True, full_name="WR A")])
    prior = pd.DataFrame([_week_row("gwa", 2024, 18, 30.0)])

    guarded = build_free_agent_ros_projections(
        pool, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=prior
    ).iloc[0]
    assert guarded["projected_ppg"] == pytest.approx(9.0)

    unguarded = build_free_agent_ros_projections(
        pool,
        SCORED_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=prior,
        min_prior_games=0,
    ).iloc[0]
    assert unguarded["projected_ppg"] == pytest.approx((4 / 7) * 9.0 + (3 / 7) * 30.0)


def test_min_prior_games_rejects_negative() -> None:
    with pytest.raises(ValueError, match="min_prior_games"):
        build_free_agent_ros_projections(
            POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, min_prior_games=-1
        )


# --------------------------------------------------------------------------
# FFA-095 -- replacement level measured over a league-wide population
# --------------------------------------------------------------------------


ROSTERED_POOL = _free_agent_pool(
    [
        _pool_row("20", "WR", "gws1", True, full_name="Rostered WR 1"),
        _pool_row("21", "WR", "gws2", True, full_name="Rostered WR 2"),
        _pool_row("22", "WR", "gws3", True, full_name="Rostered WR 3"),
    ]
)

ROSTERED_WEEKS = pd.concat(
    [
        SCORED_WEEKS,
        pd.DataFrame(
            [
                _week_row("gws1", 2025, 1, 20.0),
                _week_row("gws2", 2025, 1, 18.0),
                _week_row("gws3", 2025, 1, 16.0),
            ]
        ),
    ],
    ignore_index=True,
)


def test_replacement_population_raises_the_bar_and_is_not_returned() -> None:
    """Rostered players set the replacement level, then leave (FFA-095).

    Without ``replacement_population`` the starter cutoff lands inside the
    free-agent pool alone. With it, three strong rostered WRs enter the
    ranking population, push the last startable WR upward, and are then
    dropped from the output -- only the four free agents come back.
    """
    wire_only = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    league_wide = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=ROSTERED_POOL,
    )

    # Same players out, every time: the rostered three never appear.
    assert set(league_wide["player_id"]) == set(POOL["player_id"])
    assert set(wire_only["player_id"]) == set(POOL["player_id"])

    wire_bar = wire_only["replacement_ppg"].dropna().iloc[0]
    league_bar = league_wide["replacement_ppg"].dropna().iloc[0]
    assert league_bar > wire_bar

    # WR B is the one player whose *projection* is population-independent:
    # zero games to date plus a trusted four-game prior means his
    # projected_ppg is 5.0 either way, with no positional-mean fallback
    # involved. So his ppg_above_replacement must drop by exactly the shift
    # in the bar, isolating the replacement-level change from the
    # fallback-prior change documented in the module docstring.
    wire_b = wire_only.loc[wire_only["player_id"] == "11"].iloc[0]
    league_b = league_wide.loc[league_wide["player_id"] == "11"].iloc[0]
    assert wire_b["projected_ppg"] == pytest.approx(5.0)
    assert league_b["projected_ppg"] == pytest.approx(5.0)
    assert wire_b["ppg_above_replacement"] - league_b[
        "ppg_above_replacement"
    ] == pytest.approx(league_bar - wire_bar)


def test_replacement_population_widens_the_fallback_prior() -> None:
    """The positional-mean fallback becomes league-wide too (FFA-095).

    WR C has neither games this season nor a prior season, so on this
    EB-only path his projection is ``0.41 *`` the positional mean (FFA-104).
    Over the wire alone that mean is WR A's 9.0; adding three rostered WRs
    at 20/18/16 raises it. This is the documented knock-on effect of
    supplying a replacement_population -- and the population dependence
    FFA-104's fitted absent-prior line removes when a usage model is
    supplied.
    """
    wire_only = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    league_wide = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=ROSTERED_POOL,
    )

    wire_c = wire_only.loc[wire_only["player_id"] == "12"].iloc[0]
    league_c = league_wide.loc[league_wide["player_id"] == "12"].iloc[0]

    assert wire_c["prior_resolved_ppg"] == pytest.approx(0.41 * 9.0)
    # 0.41 * mean(9.0, 20.0, 18.0, 16.0) -- WR A plus the three rostered WRs.
    assert league_c["prior_resolved_ppg"] == pytest.approx(0.41 * 15.75)
    assert league_c["projected_ppg"] == pytest.approx(0.41 * 15.75)


def test_replacement_population_reranks_only_free_agents() -> None:
    """``waiver_rank`` stays a dense 1..n over the claimable players."""
    result = build_waiver_wire_rankings(
        POOL,
        ROSTERED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=ROSTERED_POOL,
    )
    ranked = result["waiver_rank"].dropna()
    assert ranked.min() == 1.0
    # Competition ranking, so the set of ranks is a prefix-with-ties, never
    # a sparse remnant of a league-wide rank (which would start above 1).
    assert ranked.max() <= len(ranked)


def test_empty_replacement_population_matches_the_default() -> None:
    baseline = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
    )
    explicit_empty = build_waiver_wire_rankings(
        POOL,
        SCORED_WEEKS,
        2025,
        4,
        ROSTER_POSITIONS,
        NUM_TEAMS,
        PARAMETERS,
        prior_season_weeks=PRIOR_SEASON_WEEKS,
        replacement_population=_free_agent_pool([]),
    )
    pd.testing.assert_frame_equal(baseline, explicit_empty)


# --------------------------------------------------------------------------
# FFA-098 -- season-to-date opportunity summary
# --------------------------------------------------------------------------


OPPORTUNITY_WEEKS = pd.DataFrame(
    [
        {
            **_week_row("gwa", 2025, 1, 8.0),
            "targets": 10.0,
            "carries": 1.0,
            "target_share": 0.30,
            "air_yards_share": 0.40,
            "wopr": 0.6,
            "racr": 0.8,
            "receiving_air_yards": 100.0,
            "receiving_epa": 4.0,
            "rushing_epa": 1.0,
            "passing_epa": 0.0,
        },
        {
            # A zero-target week the player *did* play: it must pull the
            # per-game rate down, not be skipped.
            **_week_row("gwa", 2025, 2, 0.0),
            "targets": 0.0,
            "carries": 3.0,
            "target_share": 0.10,
            "air_yards_share": 0.20,
            "wopr": 0.2,
            "racr": 0.4,
            "receiving_air_yards": 0.0,
            "receiving_epa": -2.0,
            "rushing_epa": 1.0,
            "passing_epa": 0.0,
        },
    ]
)


def test_opportunity_columns_are_per_game_summaries() -> None:
    """Rate columns average; volume columns divide by games played."""
    pool = _free_agent_pool([_pool_row("10", "WR", "gwa", True, full_name="WR A")])
    result = build_free_agent_ros_projections(
        pool, OPPORTUNITY_WEEKS, 2025, 4, PARAMETERS
    ).iloc[0]

    assert result["games_to_date"] == pytest.approx(2.0)

    # Rates: mean of the two weeks.
    assert result["target_share"] == pytest.approx(0.20)
    assert result["air_yards_share"] == pytest.approx(0.30)
    assert result["wopr"] == pytest.approx(0.40)
    assert result["racr"] == pytest.approx(0.60)

    # Volumes: total / games_to_date, so the 0-target week counts.
    assert result["targets_per_game"] == pytest.approx(5.0)
    assert result["carries_per_game"] == pytest.approx(2.0)
    assert result["air_yards_per_game"] == pytest.approx(50.0)
    assert result["receiving_epa_per_game"] == pytest.approx(1.0)
    assert result["rushing_epa_per_game"] == pytest.approx(1.0)
    assert result["passing_epa_per_game"] == pytest.approx(0.0)


def test_opportunity_columns_null_when_source_absent() -> None:
    """An older cache with no usage columns yields NaN, not a missing column."""
    result = build_free_agent_ros_projections(
        POOL, SCORED_WEEKS, 2025, 4, PARAMETERS, prior_season_weeks=PRIOR_SEASON_WEEKS
    )
    for column in OPPORTUNITY_SUMMARY_COLUMNS:
        assert column in result.columns
        assert result[column].isna().all()


def test_opportunity_columns_null_for_unplayed_and_uncrosswalked() -> None:
    pool = _free_agent_pool(
        [
            _pool_row("10", "WR", "gwa", True, full_name="WR A"),
            _pool_row("12", "WR", "gwc", True, full_name="WR C (no games)"),
            _pool_row("13", "WR", None, False, full_name="WR D (no crosswalk)"),
        ]
    )
    result = build_free_agent_ros_projections(
        pool, OPPORTUNITY_WEEKS, 2025, 4, PARAMETERS
    ).set_index("player_id")

    assert result.loc["10", "targets_per_game"] == pytest.approx(5.0)
    assert pd.isna(result.loc["12", "targets_per_game"])
    assert pd.isna(result.loc["13", "targets_per_game"])


def test_opportunity_columns_survive_into_the_ranking() -> None:
    pool = _free_agent_pool([_pool_row("10", "WR", "gwa", True, full_name="WR A")])
    result = build_waiver_wire_rankings(
        pool, OPPORTUNITY_WEEKS, 2025, 4, ROSTER_POSITIONS, NUM_TEAMS, PARAMETERS
    )
    assert set(OPPORTUNITY_SUMMARY_COLUMNS).issubset(WAIVER_WIRE_RANKING_COLUMNS)
    assert result.iloc[0]["target_share"] == pytest.approx(0.20)


# --------------------------------------------------------------------------
# FFA-111 -- usage-model integration, explanation columns, FFA-104 ties
# --------------------------------------------------------------------------

from fantasy_analyzer.players.usage_projection import (  # noqa: E402
    RATE_DEFINITIONS,
    STAT_LINE_COLUMNS,
    RateParameters,
    UsageModelParameters,
    VolumeParameters,
)
from fantasy_analyzer.players.waiver_rankings import (  # noqa: E402
    MODEL_EXPLANATION_COLUMNS,
)

HALF_PPR = {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6.0}

_STAT_ZEROES = {column: 0.0 for column in STAT_LINE_COLUMNS}


def _stat_week(
    gsis_id: str, season: int, week: int, position: str = "WR", **stats
) -> dict:
    row = {
        "season": season,
        "week": week,
        "player_id": gsis_id,
        "player_name": gsis_id,
        "position": position,
        **_STAT_ZEROES,
    }
    row.update(stats)
    row["fantasy_points"] = (
        0.5 * row["receptions"]
        + 0.1 * row["receiving_yards"]
        + 6 * row["receiving_tds"]
    )
    return row


#: WR A: four games of 8 targets, 4 catches, 50 yards -> 7.0 half-PPR each.
USAGE_WEEKS = pd.DataFrame(
    [
        _stat_week("gwa", 2025, week, targets=8, receptions=4, receiving_yards=50)
        for week in range(1, 5)
    ]
    + [_stat_week("gk", 2025, week, position="K") for week in range(1, 5)]
)


def _usage_parameters(blend: float = 0.75, **overrides) -> UsageModelParameters:
    """Hand-set constants (not fitted) for the integration toy example."""
    zero = VolumeParameters(1.0, 0.0, 0.0, 0.0, 0.0)
    rates = {
        rate: RateParameters(k=1e6, prior_weight=0.0, mean=0.0)
        for rate in RATE_DEFINITIONS
    }
    rates["catch_rate"] = RateParameters(k=32.0, prior_weight=0.0, mean=0.75)
    rates["receiving_yards_per_target"] = RateParameters(
        k=32.0, prior_weight=0.0, mean=7.25
    )
    rates["receiving_td_rate"] = RateParameters(k=32.0, prior_weight=0.0, mean=0.05)
    fields = dict(
        volume={
            "WR": {
                "targets": VolumeParameters(1.0, 0.0, 0.0, 8.0, 8.0),
                "carries": zero,
                "attempts": zero,
            }
        },
        rates={"WR": rates},
        blend_weight={"WR": blend},
        absent_prior_stat_line={
            "WR": {
                **_STAT_ZEROES,
                "targets": 2.0,
                "receptions": 1.0,
                "receiving_yards": 10.0,
            }
        },
    )
    fields.update(overrides)
    return UsageModelParameters(**fields)


def _usage_pool(extra_columns: bool = False) -> pd.DataFrame:
    pool = _free_agent_pool(
        [
            _pool_row("10", "WR", "gwa", True, full_name="WR A"),
            _pool_row("30", "WR", "gz1", True, full_name="Absent 1"),
            _pool_row("31", "WR", "gz2", True, full_name="Absent 2"),
            _pool_row("40", "K", "gk", True, full_name="Kicker"),
            _pool_row("SF", "DEF", None, False, full_name="49ers D/ST"),
        ]
    )
    if extra_columns:
        pool["is_rostered"] = [False, False, False, True, True]
        pool["roster_id"] = pd.array([None, None, None, 3, 4], dtype="Int64")
    return pool


def test_usage_model_projection_and_blend_by_hand() -> None:
    """WR A, cutoff week 4, half-PPR.

    EB: WR A is the only WR with games, so his prior resolves to his own
    7.0 and ``eb_projected_ppg = 7.0``. Usage: targets (4*8 + 1*8)/5 = 8.0;
    catch (16 + 32*0.75)/64 = 0.625; yards/target (200 + 32*7.25)/64 = 6.75;
    TD (0 + 32*0.05)/64 = 0.025. Stat line 8 targets, 5 catches, 54 yards,
    0.2 TD -> 2.5 + 5.4 + 1.2 = 9.1. Blend 0.75*9.1 + 0.25*7.0 = 8.575, and
    ``projected_ros_points = 8.575 * 13``.
    """
    result = build_free_agent_ros_projections(
        _usage_pool(),
        USAGE_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=pd.DataFrame(),
        usage_parameters=_usage_parameters(),
        scoring_settings=HALF_PPR,
    )
    wa = result.loc[result["player_id"] == "10"].iloc[0]
    assert wa["eb_projected_ppg"] == pytest.approx(7.0)
    assert wa["usage_projected_ppg"] == pytest.approx(9.1)
    assert wa["projected_ppg"] == pytest.approx(8.575)
    assert wa["projection_model"] == "blend"
    assert wa["projected_ros_points"] == pytest.approx(8.575 * 13)
    assert wa["projected_targets_per_game"] == pytest.approx(8.0)
    assert wa["projected_carries_per_game"] == pytest.approx(0.0)
    assert wa["projected_pass_attempts_per_game"] == pytest.approx(0.0)
    # No usage frame: snap/xFP explanation columns are NaN, never zero.
    assert math.isnan(wa["snap_share"])
    assert math.isnan(wa["xfp_per_game"])


def test_usage_frame_supplies_snap_and_xfp_columns() -> None:
    """Snap share mean(0.8, 0.8, 0.6, 1.0) = 0.8, last two 0.8.

    xFP per game (half-PPR): 0.5*5 + 0.1*60 + 6*0.5 = 11.5, so points over
    expected = 7.0 - 11.5 = -4.5: he has scored less than his usage was
    worth. With snap data present the main (snap) parameter set applies.
    """
    usage = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": week,
                "gsis_id": "gwa",
                "offense_snaps": 50,
                "offense_snap_pct": pct,
                "ep_rec_attempt": 8.0,
                "ep_receptions_exp": 5.0,
                "ep_rec_yards_gained_exp": 60.0,
                "ep_rec_touchdown_exp": 0.5,
            }
            for week, pct in zip(range(1, 5), [0.8, 0.8, 0.6, 1.0])
        ]
    )
    parameters = _usage_parameters(
        blend=0.75, no_snap_fallback=_usage_parameters(blend=0.5)
    )
    with_usage = build_free_agent_ros_projections(
        _usage_pool(),
        USAGE_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=pd.DataFrame(),
        usage_parameters=parameters,
        scoring_settings=HALF_PPR,
        usage=usage,
    )
    wa = with_usage.loc[with_usage["player_id"] == "10"].iloc[0]
    assert wa["snap_share"] == pytest.approx(0.8)
    assert wa["snap_share_last2"] == pytest.approx(0.8)
    assert wa["xfp_per_game"] == pytest.approx(11.5)
    assert wa["points_over_expected_per_game"] == pytest.approx(-4.5)
    assert wa["projected_ppg"] == pytest.approx(8.575)

    # Without the usage frame the separately fitted no-snap set applies:
    # 0.5 * 9.1 + 0.5 * 7.0 = 8.05.
    without = build_free_agent_ros_projections(
        _usage_pool(),
        USAGE_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=pd.DataFrame(),
        usage_parameters=parameters,
        scoring_settings=HALF_PPR,
        usage=None,
    )
    assert without.loc[without["player_id"] == "10", "projected_ppg"].iloc[0] == (
        pytest.approx(8.05)
    )


def test_usage_model_needs_scoring_settings() -> None:
    result = build_free_agent_ros_projections(
        _usage_pool(),
        USAGE_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=pd.DataFrame(),
        usage_parameters=_usage_parameters(),
    )
    wa = result.loc[result["player_id"] == "10"].iloc[0]
    assert wa["projected_ppg"] == pytest.approx(7.0)
    assert wa["projection_model"] == "eb"
    assert math.isnan(wa["usage_projected_ppg"])


def test_kicker_defense_and_extra_pool_columns_are_tolerated() -> None:
    """A ``build_player_universe``-shaped pool: K keeps EB, DEF has nothing."""
    result = build_free_agent_ros_projections(
        _usage_pool(extra_columns=True),
        USAGE_WEEKS,
        2025,
        4,
        PARAMETERS,
        prior_season_weeks=pd.DataFrame(),
        usage_parameters=_usage_parameters(),
        scoring_settings=HALF_PPR,
    )
    assert list(result.columns) == FREE_AGENT_PROJECTION_COLUMNS
    kicker = result.loc[result["player_id"] == "40"].iloc[0]
    defense = result.loc[result["player_id"] == "SF"].iloc[0]
    assert kicker["projection_model"] == "eb"
    assert math.isnan(kicker["usage_projected_ppg"])
    assert kicker["projected_ppg"] == pytest.approx(kicker["eb_projected_ppg"])
    assert defense["projection_model"] is None
    assert math.isnan(defense["projected_ppg"])


def test_absent_prior_uses_the_fitted_line_and_players_tie() -> None:
    """FFA-104 with a usage model: the absent line, scored in this league.

    ``2 targets, 1 catch, 10 yards`` -> 0.5 + 1.0 = 1.5 half-PPR points for
    both absent WRs -- identical, so they share a ``waiver_rank`` (standard
    competition ranking) below WR A, who has real evidence.
    """
    ranked = build_waiver_wire_rankings(
        _usage_pool(),
        USAGE_WEEKS,
        2025,
        4,
        ["WR", "WR", "BN"],
        2,
        PARAMETERS,
        prior_season_weeks=pd.DataFrame(),
        usage_parameters=_usage_parameters(),
        scoring_settings=HALF_PPR,
    )
    by_id = ranked.set_index("player_id")
    for player_id in ("30", "31"):
        assert by_id.loc[player_id, "projected_ppg"] == pytest.approx(1.5)
        assert by_id.loc[player_id, "eb_projected_ppg"] == pytest.approx(1.5)
        assert by_id.loc[player_id, "projection_model"] == "absent_prior"
    assert by_id.loc["30", "waiver_rank"] == by_id.loc["31", "waiver_rank"]
    assert by_id.loc["10", "waiver_rank"] < by_id.loc["30", "waiver_rank"]


def test_absent_prior_players_tie_below_players_with_evidence() -> None:
    """FFA-104 without a usage model: ratio * positional mean, tied.

    Before FFA-104 both absent WRs inherited WR A's 7.0 and tied him for
    rank 1. Now both get 0.41 * 7.0 = 2.87 and tie each other, below him.
    """
    ranked = build_waiver_wire_rankings(
        _usage_pool(),
        USAGE_WEEKS,
        2025,
        4,
        ["WR", "WR", "BN"],
        2,
        PARAMETERS,
        prior_season_weeks=pd.DataFrame(),
    )
    by_id = ranked.set_index("player_id")
    assert by_id.loc["30", "projected_ppg"] == pytest.approx(0.41 * 7.0)
    assert by_id.loc["31", "projected_ppg"] == pytest.approx(0.41 * 7.0)
    assert by_id.loc["30", "waiver_rank"] == by_id.loc["31", "waiver_rank"]
    assert by_id.loc["10", "waiver_rank"] == pytest.approx(1.0)
    assert by_id.loc["30", "waiver_rank"] > 1.0
    assert by_id.loc["30", "projection_model"] == "absent_prior"


def test_model_explanation_columns_are_in_both_schemas() -> None:
    assert set(MODEL_EXPLANATION_COLUMNS) <= set(FREE_AGENT_PROJECTION_COLUMNS)
    assert set(MODEL_EXPLANATION_COLUMNS) <= set(WAIVER_WIRE_RANKING_COLUMNS)
    empty = build_free_agent_ros_projections(
        _free_agent_pool([]), SCORED_WEEKS, 2025, 4, PARAMETERS
    )
    assert empty["projection_model"].dtype == object
    assert empty["usage_projected_ppg"].dtype == "float64"
