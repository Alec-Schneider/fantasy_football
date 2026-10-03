#!/usr/bin/env python
"""Fit and persist the win-probability model (FFA-114).

Two measurements feed ``players/win_probability.py``:

**A. Player-level single-week SD.** A rolling-origin backtest of the
dashboard's own projection. For every test season ``s`` every constant of
the projection model -- EB ``n0``, the usage model, the blend weights, the
absent prior -- is fitted on seasons ``fit_start..s-1`` only (the same
fitting path as ``scripts/fit_usage_model.py``, at standard PPR). At each
cutoff ``c = 1..16`` the production entry points
(``build_free_agent_ros_projections`` for QB/RB/WR/TE and
``build_kicker_defense_projections`` for K/DEF) project week ``c + 1``;
that projection is compared with the player's actual week-``c + 1`` points
under each league's scoring. Residuals are restricted to a starter-caliber
population (the top-N projections at the position among the players who
played that week) and two SD forms are compared on held-out Gaussian NLL:
fit on the earlier seasons, test on the last one.

**B. Team-level calibration of ``lambda``.** For each league's calibration
season (default 2025), every regular-season matchup week >= 2 with both
teams' starters known: each team's ``mu`` is the sum of its starters'
cutoff-``w - 1`` projections and ``sd`` the root-sum-square of their SDs
(every starter pending, empty slots 0). ``lambda`` minimises log loss of the
winner. Week 1 is skipped: the projection pipeline requires ``cutoff >= 1``.

Network use (Sleeper) is confined to :func:`fetch_league_season`; every
other function takes frames and is deterministic. The rolling fits take
several minutes per test season and are cached under ``--cache-dir``.

Usage::

    python scripts/fit_win_probability.py                  # full fit
    python scripts/fit_win_probability.py --fit-only --seasons 2023
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from draft_league_presets import LEAGUES  # noqa: E402
from fit_usage_model import PPR_SCORING_SETTINGS  # noqa: E402

from fantasy_analyzer.players.crosswalk import (  # noqa: E402
    build_robust_id_crosswalk,
)
from fantasy_analyzer.players.kicker_defense import (  # noqa: E402
    DEFAULT_KICKER_DEFENSE_PARAMETERS,
    build_defense_weeks,
    build_kicker_defense_projections,
    build_kicker_weeks,
)
from fantasy_analyzer.players.nflverse_cache import (  # noqa: E402
    load_player_stats_cache,
)
from fantasy_analyzer.players.nflverse_schedule_cache import (  # noqa: E402
    load_games_cache,
)
from fantasy_analyzer.players.ros_backtest import (  # noqa: E402
    build_scored_player_weeks,
)
from fantasy_analyzer.players.ros_projection import (  # noqa: E402
    ShrinkageParameters,
    fit_shrinkage_on_rows,
    load_shrinkage_parameters,
    save_shrinkage_parameters,
)
from fantasy_analyzer.players.usage import load_usage_player_weeks  # noqa: E402
from fantasy_analyzer.players.usage_projection import (  # noqa: E402
    DEFAULT_FIT_CUTOFF_WEEKS,
    MODELED_POSITIONS,
    UsageModelParameters,
    attach_opportunity_quality,
    build_absent_prior_cohort,
    build_usage_panel,
    fit_usage_model_on_panel,
    load_usage_model_parameters,
    save_usage_model_parameters,
)
from fantasy_analyzer.players.waiver_rankings import (  # noqa: E402
    build_free_agent_ros_projections,
)
from fantasy_analyzer.players.win_probability import (  # noqa: E402
    DEFAULT_WIN_PROBABILITY_PARAMETERS_PATH,
    FORM_CONSTANT,
    FORM_SQRT,
    MIN_SQRT_PROJECTION,
    WinProbabilityParameters,
    save_win_probability_parameters,
    win_probability,
)

SKILL_POSITIONS = tuple(MODELED_POSITIONS)
KDEF_POSITIONS = ("K", "DEF")
ALL_POSITIONS = SKILL_POSITIONS + KDEF_POSITIONS

#: Starter-caliber population: projection rank at the position within the
#: number of starters across a 12-team league with this league's slots
#: (QB 1, RB 2 + flex share, WR 2 + flex share, TE 1, K 1, DEF 1).
STARTER_COUNTS = {"QB": 12, "RB": 30, "WR": 36, "TE": 12, "K": 12, "DEF": 12}

LEAGUE_SLUGS = tuple(LEAGUES)
#: First season of the projection model's fitting window (as in
#: ``scripts/fit_usage_model.py``); needs ``fit_start - 1`` for priors.
DEFAULT_FIT_START = 2015
DEFAULT_TEST_SEASONS = (2021, 2022, 2023, 2024, 2025)
LAST_CUTOFF = 16
BOOTSTRAP_REPS = 300
DEFAULT_CACHE_DIR = Path(".cache/win_probability")


# ---------------------------------------------------------------------------
# Network (Sleeper) -- isolated from the modelling below
# ---------------------------------------------------------------------------


def fetch_league_season(client, league_id: str, season: int) -> dict:
    """Fetch one past league season via ``previous_league_id`` chaining.

    ``league_id`` may be the current season's id; the chain is walked back
    until a league whose ``season`` equals ``season`` is found.

    Returns:
        ``{"league": <Sleeper league JSON>, "matchups": {week: [entries]}}``
        for weeks 1-18.
    """
    league = client.get_league(league_id)
    for _ in range(6):
        if int(league["season"]) == season:
            break
        previous = league.get("previous_league_id")
        if not previous:
            raise LookupError(f"No {season} season behind league {league_id}.")
        league = client.get_league(previous)
    else:
        raise LookupError(f"No {season} season behind league {league_id}.")
    matchups = {
        week: client.get_matchups(league["league_id"], week) for week in range(1, 19)
    }
    return {"league": league, "matchups": matchups}


def fetch_calibration_inputs(
    season: int, cache_dir: Path
) -> tuple[dict[str, dict], dict, pd.DataFrame]:
    """Fetch (or reload from cache) the league seasons, catalog and crosswalk."""
    from fantasy_analyzer.sleeper.client import SleeperClient

    client = SleeperClient()
    leagues: dict[str, dict] = {}
    for slug, preset in LEAGUES.items():
        cache_path = cache_dir / f"league_{slug}_{season}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text())
            payload["matchups"] = {int(k): v for k, v in payload["matchups"].items()}
        else:
            payload = fetch_league_season(client, preset["league_id"], season)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload))
        leagues[slug] = payload

    from fantasy_analyzer.sleeper.cache import get_players_cached

    catalog = get_players_cached(client)
    crosswalk = build_robust_id_crosswalk(catalog)
    return leagues, catalog, crosswalk


# ---------------------------------------------------------------------------
# Rolling-origin fits of the projection model
# ---------------------------------------------------------------------------


def ensure_rolling_fit(
    season: int,
    scored_ppr: pd.DataFrame,
    usage_weeks: Optional[pd.DataFrame],
    cache_dir: Path,
    fit_start: int = DEFAULT_FIT_START,
) -> tuple[ShrinkageParameters, UsageModelParameters]:
    """EB and usage parameters fitted on ``fit_start..season-1`` only (cached).

    Same fitting path as ``fit_usage_model`` (``build_usage_panel`` ->
    ``attach_opportunity_quality`` -> ``fit_usage_model_on_panel``), at
    standard PPR, so nothing from ``season`` or later reaches a constant.
    """
    eb_path = cache_dir / f"shrinkage_{season}.json"
    usage_path = cache_dir / f"usage_{season}.json"
    if eb_path.exists() and usage_path.exists():
        eb = load_shrinkage_parameters(eb_path)
        up = load_usage_model_parameters(usage_path)
        if eb is not None and up is not None:
            return eb, up

    fit_seasons = list(range(fit_start, season))
    skill = scored_ppr[scored_ppr["position"].isin(SKILL_POSITIONS)]
    panel = build_usage_panel(skill, fit_seasons, DEFAULT_FIT_CUTOFF_WEEKS)
    panel = attach_opportunity_quality(panel, usage_weeks, PPR_SCORING_SETTINGS)
    cohorts = [
        build_absent_prior_cohort(skill, year, cutoff)
        for year in fit_seasons
        for cutoff in DEFAULT_FIT_CUTOFF_WEEKS
    ]
    cohort = pd.concat([c for c in cohorts if not c.empty], ignore_index=True)
    eb = fit_shrinkage_on_rows(panel, fit_seasons, positions=MODELED_POSITIONS)
    up = fit_usage_model_on_panel(panel, cohort, fit_seasons, PPR_SCORING_SETTINGS, eb)
    cache_dir.mkdir(parents=True, exist_ok=True)
    save_shrinkage_parameters(eb, eb_path)
    save_usage_model_parameters(up, usage_path)
    return eb, up


# ---------------------------------------------------------------------------
# A. Player-level projection vs. actual
# ---------------------------------------------------------------------------


def _skill_pool(players: pd.DataFrame, season: int, cutoff: int) -> pd.DataFrame:
    """Every skill player seen in ``season`` through ``cutoff + 1`` or last season.

    ``cutoff + 1`` is included so a debut in the target week gets the
    absent-prior line, as an unowned rookie would on the dashboard.
    """
    seen = players[
        ((players["season"] == season) & (players["week"] <= cutoff + 1))
        | (players["season"] == season - 1)
    ].sort_values(["season", "week"])
    pool = seen.groupby("player_id", sort=True).agg(
        full_name=("player_name", "last"),
        position=("position", "last"),
        team=("team", "last"),
    )
    pool = pool.reset_index()
    pool["status"] = "Active"
    pool["gsis_id"] = pool["player_id"]
    pool["has_crosswalk"] = True
    return pool


def backtest_skill_projections(
    scored_by_league: Mapping[str, pd.DataFrame],
    scoring_by_league: Mapping[str, Mapping[str, float]],
    rolling: Mapping[int, tuple[ShrinkageParameters, UsageModelParameters]],
    usage_weeks: Optional[pd.DataFrame],
    seasons: Sequence[int],
) -> pd.DataFrame:
    """Projection at cutoff ``c`` vs. actual points in week ``c + 1``.

    Returns:
        ``league, season, cutoff, position, player_id, projection, actual``
        for QB/RB/WR/TE who played in week ``c + 1`` and have a projection.
    """
    rows = []
    for season in seasons:
        eb, up = rolling[season]
        usage = (
            usage_weeks[usage_weeks["season"].isin([season - 1, season])]
            if usage_weeks is not None
            else None
        )
        for slug, scored in scored_by_league.items():
            window = scored[scored["season"].isin([season - 1, season])]
            window = window[window["position"].isin(SKILL_POSITIONS)]
            for cutoff in range(1, LAST_CUTOFF + 1):
                pool = _skill_pool(window, season, cutoff)
                projected = build_free_agent_ros_projections(
                    pool,
                    window,
                    season,
                    cutoff,
                    eb,
                    usage_parameters=up,
                    scoring_settings=scoring_by_league[slug],
                    usage=usage,
                )
                actual = window[
                    (window["season"] == season) & (window["week"] == cutoff + 1)
                ].drop_duplicates("player_id")[["player_id", "fantasy_points"]]
                merged = projected[["player_id", "position", "projected_ppg"]].merge(
                    actual, on="player_id", how="inner"
                )
                merged = merged.dropna(subset=["projected_ppg", "fantasy_points"])
                rows.append(
                    pd.DataFrame(
                        {
                            "league": slug,
                            "season": season,
                            "cutoff": cutoff,
                            "position": merged["position"],
                            "player_id": merged["player_id"],
                            "projection": merged["projected_ppg"],
                            "actual": merged["fantasy_points"],
                        }
                    )
                )
        print(f"  skill backtest {season} done", file=sys.stderr, flush=True)
    return pd.concat(rows, ignore_index=True)


def _kdef_catalog(
    kicker_weeks: pd.DataFrame, defense_weeks: pd.DataFrame, season: int, week: int
) -> tuple[dict, pd.DataFrame]:
    """A synthetic Sleeper-style catalog + identity crosswalk for K and DEF.

    Historical kickers have no Sleeper id here, so each is keyed by his GSIS
    id with an identity crosswalk; his team is the team he played for in
    ``week`` (else his latest earlier team) so the schedule join works.
    """
    catalog: dict = {}
    this = kicker_weeks[kicker_weeks["season"] == season].sort_values("week")
    in_week = this[this["week"] == week].drop_duplicates("player_id", keep="last")
    latest = this[this["week"] < week].drop_duplicates("player_id", keep="last")
    team_of = {
        **dict(zip(latest["player_id"], latest["team"])),
        **dict(zip(in_week["player_id"], in_week["team"])),
    }
    names = kicker_weeks.drop_duplicates("player_id", keep="last").set_index(
        "player_id"
    )["player_name"]
    for gsis, team in team_of.items():
        catalog[gsis] = {
            "position": "K",
            "team": team,
            "full_name": names.get(gsis, gsis),
            "status": "Active",
        }
    for team in sorted(
        set(defense_weeks.loc[defense_weeks["season"] == season, "team"])
    ):
        catalog[team] = {
            "position": "DEF",
            "team": team,
            "first_name": team,
            "status": "Active",
        }
    ids = [key for key, value in catalog.items() if value["position"] == "K"]
    crosswalk = pd.DataFrame({"sleeper_player_id": ids, "gsis_id": ids})
    return catalog, crosswalk


def backtest_kdef_projections(
    raw_by_season: Mapping[int, pd.DataFrame],
    games: pd.DataFrame,
    scoring_by_league: Mapping[str, Mapping[str, float]],
    seasons: Sequence[int],
) -> pd.DataFrame:
    """The K/DEF model's ``week_projected_points`` vs. actual, same columns.

    K/DEF constants are :data:`DEFAULT_KICKER_DEFENSE_PARAMETERS`, which is
    what the dashboard uses (they are not refitted per season).
    """
    rows = []
    for season in seasons:
        raw = {y: raw_by_season[y] for y in (season - 1, season) if y in raw_by_season}
        for slug, scoring in scoring_by_league.items():
            kicker_weeks = pd.concat(
                [build_kicker_weeks(frame, scoring) for frame in raw.values()],
                ignore_index=True,
            )
            defense_weeks = pd.concat(
                [
                    build_defense_weeks(frame, games, year, scoring)
                    for year, frame in raw.items()
                ],
                ignore_index=True,
            )
            actual_all = pd.concat([kicker_weeks, defense_weeks], ignore_index=True)
            actual_all = actual_all[actual_all["season"] == season]
            for cutoff in range(1, LAST_CUTOFF + 1):
                week = cutoff + 1
                catalog, crosswalk = _kdef_catalog(
                    kicker_weeks, defense_weeks, season, week
                )
                projected = build_kicker_defense_projections(
                    catalog,
                    scoring,
                    season,
                    cutoff,
                    week,
                    raw,
                    games,
                    crosswalk=crosswalk,
                    parameters=DEFAULT_KICKER_DEFENSE_PARAMETERS,
                )
                actual = actual_all[actual_all["week"] == week].drop_duplicates(
                    ["player_id", "position"]
                )[["player_id", "position", "fantasy_points"]]
                merged = projected[
                    ["player_id", "position", "week_projected_points"]
                ].merge(actual, on=["player_id", "position"], how="inner")
                merged = merged.dropna(subset=["week_projected_points"])
                rows.append(
                    pd.DataFrame(
                        {
                            "league": slug,
                            "season": season,
                            "cutoff": cutoff,
                            "position": merged["position"],
                            "player_id": merged["player_id"],
                            "projection": merged["week_projected_points"],
                            "actual": merged["fantasy_points"],
                        }
                    )
                )
        print(f"  K/DEF backtest {season} done", file=sys.stderr, flush=True)
    return pd.concat(rows, ignore_index=True)


def restrict_to_starter_caliber(
    rows: pd.DataFrame, counts: Mapping[str, int] = STARTER_COUNTS
) -> pd.DataFrame:
    """Keep the top-N projections per (league, season, cutoff, position).

    Ranked among the players who played that week (the rows present), so
    ``counts`` is "the N-th best projected player who took the field".
    Ties in projection are broken by player id for determinism.
    """
    ordered = rows.sort_values(
        ["league", "season", "cutoff", "position", "projection", "player_id"],
        ascending=[True, True, True, True, False, True],
        kind="stable",
    )
    rank = ordered.groupby(["league", "season", "cutoff", "position"]).cumcount() + 1
    limit = ordered["position"].map(counts)
    return ordered[rank <= limit]


# ---------------------------------------------------------------------------
# SD forms: fit and held-out likelihood
# ---------------------------------------------------------------------------


def _scale(rows: pd.DataFrame, form: str) -> np.ndarray:
    """The multiplier of the coefficient: 1 (constant) or sqrt(floored proj)."""
    if form == FORM_CONSTANT:
        return np.ones(len(rows))
    return np.sqrt(np.maximum(rows["projection"].to_numpy(), MIN_SQRT_PROJECTION))


def fit_coefficients(rows: pd.DataFrame, form: str) -> tuple[dict[str, float], float]:
    """Gaussian MLE of ``s = coefficient * scale`` (zero-mean residuals).

    ``coefficient^2 = mean(residual^2 / scale^2)`` -- closed form for both
    forms. Returns the per-position coefficients and the pooled default.
    """
    residual = rows["actual"].to_numpy() - rows["projection"].to_numpy()
    ratio = (residual / _scale(rows, form)) ** 2
    frame = pd.DataFrame({"position": rows["position"].to_numpy(), "ratio": ratio})
    by_position = frame.groupby("position")["ratio"].mean().pow(0.5)
    return by_position.to_dict(), float(math.sqrt(frame["ratio"].mean()))


def gaussian_nll(
    rows: pd.DataFrame, form: str, coefficients: Mapping[str, float], default: float
) -> pd.Series:
    """Mean per-observation Gaussian NLL by position (index) plus ``"ALL"``."""
    residual = rows["actual"].to_numpy() - rows["projection"].to_numpy()
    coefficient = rows["position"].map(coefficients).fillna(default).to_numpy()
    sd = coefficient * _scale(rows, form)
    nll = 0.5 * np.log(2 * np.pi * sd**2) + residual**2 / (2 * sd**2)
    series = pd.Series(nll, index=rows.index).groupby(rows["position"]).mean()
    series["ALL"] = float(np.mean(nll))
    return series


def compare_forms(
    starters: pd.DataFrame, train_seasons: Sequence[int], test_season: int
) -> pd.DataFrame:
    """Held-out NLL (fit on ``train_seasons``, score ``test_season``) per form."""
    train = starters[starters["season"].isin(list(train_seasons))]
    test = starters[starters["season"] == test_season]
    out = {}
    for form in (FORM_CONSTANT, FORM_SQRT):
        coefficients, default = fit_coefficients(train, form)
        out[form] = gaussian_nll(test, form, coefficients, default)
    result = pd.DataFrame(out)
    result["n_test"] = test.groupby("position").size().reindex(result.index)
    result.loc["ALL", "n_test"] = len(test)
    return result


# ---------------------------------------------------------------------------
# B. Team-level calibration of lambda
# ---------------------------------------------------------------------------


def _project_starters(
    week: int,
    starters: pd.DataFrame,
    scored: pd.DataFrame,
    scoring: Mapping[str, float],
    season: int,
    eb: ShrinkageParameters,
    up: UsageModelParameters,
    usage: Optional[pd.DataFrame],
    catalog: Mapping[str, Mapping],
    crosswalk: pd.DataFrame,
    raw_by_season: Mapping[int, pd.DataFrame],
    games: pd.DataFrame,
    kicker_weeks: pd.DataFrame,
    defense_weeks: pd.DataFrame,
) -> pd.Series:
    """Sleeper starter id -> pre-kickoff projection for ``week`` (cutoff week-1)."""
    cutoff = week - 1
    ids = sorted(set(starters["sleeper_id"]))
    positions = {
        pid: ("DEF" if pid.isalpha() else catalog.get(pid, {}).get("position"))
        for pid in ids
    }
    lookup = (
        crosswalk.dropna(subset=["sleeper_player_id", "gsis_id"])
        .drop_duplicates("sleeper_player_id")
        .set_index(crosswalk["sleeper_player_id"].astype(str))["gsis_id"]
        .astype(str)
        .to_dict()
    )
    projection: dict[str, float] = {}

    skill_ids = [p for p in ids if positions[p] in SKILL_POSITIONS and p in lookup]
    if skill_ids:
        pool = pd.DataFrame(
            {
                "player_id": [lookup[p] for p in skill_ids],
                "full_name": [catalog[p].get("full_name") for p in skill_ids],
                "position": [positions[p] for p in skill_ids],
                "team": [catalog[p].get("team") for p in skill_ids],
                "status": "Active",
                "gsis_id": [lookup[p] for p in skill_ids],
                "has_crosswalk": True,
            }
        )
        result = build_free_agent_ros_projections(
            pool,
            scored,
            season,
            cutoff,
            eb,
            usage_parameters=up,
            scoring_settings=scoring,
            usage=usage,
        ).set_index("player_id")["projected_ppg"]
        for sleeper_id in skill_ids:
            value = result.get(lookup[sleeper_id])
            if value is not None and pd.notna(value):
                projection[sleeper_id] = float(value)

    kdef_ids = [p for p in ids if positions[p] in KDEF_POSITIONS]
    if kdef_ids:
        synthetic, _ = _kdef_catalog(kicker_weeks, defense_weeks, season, week)
        # Sleeper ids -> the catalog entry, with this week's team substituted
        # (the live catalog's team is the *current* one).
        gsis_team = {
            key: value["team"]
            for key, value in synthetic.items()
            if value["position"] == "K"
        }
        local: dict = {}
        for pid in kdef_ids:
            if positions[pid] == "DEF":
                local[pid] = synthetic.get(pid) or {
                    "position": "DEF",
                    "team": pid,
                    "first_name": pid,
                    "status": "Active",
                }
            elif pid in catalog:
                team = gsis_team.get(lookup.get(pid, ""), catalog[pid].get("team"))
                local[pid] = {**catalog[pid], "team": team}
        result = build_kicker_defense_projections(
            local,
            scoring,
            season,
            cutoff,
            week,
            raw_by_season,
            games,
            crosswalk=crosswalk,
            parameters=DEFAULT_KICKER_DEFENSE_PARAMETERS,
            include_player_ids=kdef_ids,
        ).set_index("player_id")["week_projected_points"]
        for pid in kdef_ids:
            value = result.get(pid)
            if value is not None and pd.notna(value):
                projection[pid] = float(value)
    return pd.Series(projection, dtype="float64")


def _starter_rows(entries: Sequence[Mapping]) -> pd.DataFrame:
    """One row per starter slot: roster, slot index, Sleeper id."""
    rows = []
    for entry in entries:
        for slot, sleeper_id in enumerate(entry.get("starters") or []):
            rows.append(
                {
                    "roster_id": entry["roster_id"],
                    "slot": slot,
                    "sleeper_id": str(sleeper_id),
                }
            )
    return pd.DataFrame(rows, columns=["roster_id", "slot", "sleeper_id"])


def build_calibration_games(
    league_payload: Mapping,
    catalog: Mapping[str, Mapping],
    crosswalk: pd.DataFrame,
    scored: pd.DataFrame,
    raw_by_season: Mapping[int, pd.DataFrame],
    games: pd.DataFrame,
    rolling: tuple[ShrinkageParameters, UsageModelParameters],
    usage: Optional[pd.DataFrame],
    season: int,
) -> pd.DataFrame:
    """Pre-kickoff projected lineups for every regular-season game, weeks >= 2.

    Returns one row per game with each side's starter projections as a list
    (``projections_a`` / ``positions_a``; NaN = no projection, empty slot ->
    absent) so ``mu`` / ``sd`` can be formed under any SD parameters.
    """
    league = league_payload["league"]
    scoring = league["scoring_settings"]
    last_regular = int(league["settings"].get("playoff_week_start") or 15) - 1
    eb, up = rolling
    window = scored[scored["season"].isin([season - 1, season])]
    kicker_weeks = pd.concat(
        [build_kicker_weeks(frame, scoring) for frame in raw_by_season.values()],
        ignore_index=True,
    )
    defense_weeks = pd.concat(
        [
            build_defense_weeks(frame, games, year, scoring)
            for year, frame in raw_by_season.items()
        ],
        ignore_index=True,
    )
    rows = []
    for week in range(2, last_regular + 1):
        entries = league_payload["matchups"].get(week) or []
        if not entries or any(not entry.get("starters") for entry in entries):
            continue
        starters = _starter_rows(entries)
        projection = _project_starters(
            week,
            starters,
            window,
            scoring,
            season,
            eb,
            up,
            usage,
            catalog,
            crosswalk,
            raw_by_season,
            games,
            kicker_weeks,
            defense_weeks,
        )
        by_matchup: dict = {}
        for entry in entries:
            by_matchup.setdefault(entry.get("matchup_id"), []).append(entry)
        for matchup_id, pair in by_matchup.items():
            if matchup_id is None or len(pair) != 2:
                continue
            sides = []
            for entry in pair:
                ids = [str(x) for x in entry["starters"]]
                live = [i for i in ids if i != "0"]
                sides.append(
                    {
                        "projections": [float(projection.get(i, np.nan)) for i in live],
                        "positions": [
                            "DEF" if i.isalpha() else catalog.get(i, {}).get("position")
                            for i in live
                        ],
                        "points": float(entry["points"] or 0.0),
                        "roster_id": entry["roster_id"],
                    }
                )
            a, b = sides
            if a["points"] <= 0 or b["points"] <= 0:
                continue
            rows.append(
                {
                    "week": week,
                    "matchup_id": matchup_id,
                    "roster_a": a["roster_id"],
                    "roster_b": b["roster_id"],
                    "projections_a": a["projections"],
                    "positions_a": a["positions"],
                    "projections_b": b["projections"],
                    "positions_b": b["positions"],
                    "points_a": a["points"],
                    "points_b": b["points"],
                }
            )
        print(
            f"  [{league['name']}] week {week} projected", file=sys.stderr, flush=True
        )
    return pd.DataFrame(rows)


def team_moments(
    projections: Sequence[float],
    positions: Sequence[str],
    parameters: WinProbabilityParameters,
) -> tuple[float, float]:
    """``(mu, sd)`` with every starter pending; no projection -> 0, no SD."""
    from fantasy_analyzer.players.win_probability import team_score_sd

    frame = pd.DataFrame(
        {
            "position": list(positions),
            "projection": list(projections),
            "pending": [not math.isnan(p) for p in projections],
        }
    )
    mu = float(np.nansum(projections))
    return mu, team_score_sd(frame, parameters)


def game_moments(
    games_frame: pd.DataFrame, parameters: WinProbabilityParameters
) -> pd.DataFrame:
    """Add ``mu_a, sd_a, mu_b, sd_b, a_wins, tie`` under ``parameters``' SDs."""
    out = games_frame.copy()
    moments_a = [
        team_moments(p, q, parameters)
        for p, q in zip(out["projections_a"], out["positions_a"])
    ]
    moments_b = [
        team_moments(p, q, parameters)
        for p, q in zip(out["projections_b"], out["positions_b"])
    ]
    out["mu_a"], out["sd_a"] = zip(*moments_a)
    out["mu_b"], out["sd_b"] = zip(*moments_b)
    out["tie"] = out["points_a"] == out["points_b"]
    out["a_wins"] = (out["points_a"] > out["points_b"]).astype(float)
    return out


_erf = np.vectorize(math.erf, otypes=[float])


def log_loss_for_lambda(games_frame: pd.DataFrame, multiplier: float) -> float:
    """Mean log loss of the winner at margin-SD multiplier ``multiplier``."""
    scored = games_frame[~games_frame["tie"]]
    margin = scored["mu_a"] - scored["mu_b"]
    spread = multiplier * np.sqrt(scored["sd_a"] ** 2 + scored["sd_b"] ** 2)
    p = 0.5 * (1.0 + _erf(margin / spread / math.sqrt(2.0)))
    p = np.clip(p, 1e-12, 1 - 1e-12)
    y = scored["a_wins"].to_numpy()
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def fit_lambda(games_frame: pd.DataFrame) -> float:
    """Minimise log loss over ``lambda``: log-grid, then golden-section."""
    grid = np.exp(np.linspace(np.log(0.2), np.log(6.0), 121))
    losses = [log_loss_for_lambda(games_frame, x) for x in grid]
    index = int(np.argmin(losses))
    low = grid[max(index - 1, 0)]
    high = grid[min(index + 1, len(grid) - 1)]
    ratio = (math.sqrt(5) - 1) / 2
    a, b = low, high
    for _ in range(60):
        c = b - ratio * (b - a)
        d = a + ratio * (b - a)
        if log_loss_for_lambda(games_frame, c) < log_loss_for_lambda(games_frame, d):
            b = d
        else:
            a = c
    return float((a + b) / 2)


def probabilities(
    games_frame: pd.DataFrame, parameters: WinProbabilityParameters
) -> np.ndarray:
    """``P(a wins)`` per game via the package's ``win_probability``."""
    return np.array(
        [
            win_probability(r.mu_a, r.sd_a, r.mu_b, r.sd_b, parameters)
            for r in games_frame.itertuples()
        ]
    )


def forecast_metrics(p_a: np.ndarray, a_wins: np.ndarray, mu_diff: np.ndarray) -> dict:
    """Brier, log loss and favorite-wins accuracy of ``P(a wins)``."""
    clipped = np.clip(p_a, 1e-12, 1 - 1e-12)
    favorite_decided = mu_diff != 0
    favorite_won = (mu_diff > 0) == (a_wins == 1)
    return {
        "n": int(len(p_a)),
        "brier": float(np.mean((p_a - a_wins) ** 2)),
        "log_loss": float(
            -np.mean(a_wins * np.log(clipped) + (1 - a_wins) * np.log(1 - clipped))
        ),
        "favorite_accuracy": float(np.mean(favorite_won[favorite_decided])),
        "n_favorite": int(favorite_decided.sum()),
    }


def calibration_table(
    p_a: np.ndarray,
    a_wins: np.ndarray,
    edges: Sequence[float] = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
) -> pd.DataFrame:
    """Five bins on the favorite's probability: predicted vs. observed."""
    favorite_p = np.maximum(p_a, 1 - p_a)
    favorite_won = np.where(p_a >= 0.5, a_wins, 1 - a_wins)
    labels = pd.cut(favorite_p, bins=list(edges), include_lowest=True, right=False)
    frame = pd.DataFrame({"bin": labels, "p": favorite_p, "won": favorite_won})
    table = frame.groupby("bin", observed=False).agg(
        n=("won", "size"), mean_predicted=("p", "mean"), observed=("won", "mean")
    )
    table.index = table.index.astype(str)
    return table


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seasons",
        type=int,
        nargs="+",
        default=list(DEFAULT_TEST_SEASONS),
        help="Backtest seasons for the player-level SD (rolling origin).",
    )
    parser.add_argument("--calibration-season", type=int, default=2025)
    parser.add_argument("--fit-start", type=int, default=DEFAULT_FIT_START)
    parser.add_argument("--out", default=str(DEFAULT_WIN_PROBABILITY_PARAMETERS_PATH))
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument(
        "--fit-only",
        action="store_true",
        help="Only fit and cache the rolling projection models for --seasons.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Also write every measured table to this JSON file.",
    )
    args = parser.parse_args(argv)
    cache_dir = Path(args.cache_dir)
    seasons = sorted(args.seasons)
    last_season = max(seasons + [args.calibration_season])

    frames = {
        year: load_player_stats_cache(year)
        for year in range(args.fit_start - 1, last_season + 1)
    }
    missing = [year for year, frame in frames.items() if frame is None or frame.empty]
    if missing:
        print(f"Missing nflverse caches for {missing}.", file=sys.stderr)
        return 1
    games = load_games_cache()
    if games is None:
        print("Missing .cache/nflverse/games.csv.", file=sys.stderr)
        return 1
    usage_weeks = None
    try:
        usage_weeks = load_usage_player_weeks(
            range(args.fit_start - 1, last_season + 1)
        )
    except (FileNotFoundError, ValueError, OSError) as error:
        print(
            f"WARNING: no snap/xFP caches ({error}); no-snap model only.",
            file=sys.stderr,
        )

    scored_ppr = build_scored_player_weeks(frames.values(), PPR_SCORING_SETTINGS)
    rolling = {
        season: ensure_rolling_fit(
            season, scored_ppr, usage_weeks, cache_dir, args.fit_start
        )
        for season in sorted(
            set(seasons) | (set() if args.fit_only else {args.calibration_season})
        )
    }
    if args.fit_only:
        print(f"Rolling fits cached under {cache_dir}.", file=sys.stderr)
        return 0

    leagues_scoring: dict[str, Mapping[str, float]] = {}
    try:
        league_payloads, catalog, crosswalk = fetch_calibration_inputs(
            args.calibration_season, cache_dir
        )
        leagues_scoring = {
            slug: payload["league"]["scoring_settings"]
            for slug, payload in league_payloads.items()
        }
        sleeper_ok = True
    except Exception as error:  # network or API failure: degrade, report
        print(f"WARNING: Sleeper unreachable ({error!r}).", file=sys.stderr)
        league_payloads, catalog, crosswalk, sleeper_ok = {}, {}, pd.DataFrame(), False
    if not leagues_scoring:
        leagues_scoring = {slug: PPR_SCORING_SETTINGS for slug in LEAGUES}

    scored_by_league = {
        slug: build_scored_player_weeks(frames.values(), scoring)
        for slug, scoring in leagues_scoring.items()
    }
    skill_rows = backtest_skill_projections(
        scored_by_league, leagues_scoring, rolling, usage_weeks, seasons
    )
    kdef_rows = backtest_kdef_projections(frames, games, leagues_scoring, seasons)
    all_rows = pd.concat([skill_rows, kdef_rows], ignore_index=True)
    starters = restrict_to_starter_caliber(all_rows)
    report: dict = {
        "seasons": seasons,
        "population_counts": STARTER_COUNTS,
        "n_rows_all": int(len(all_rows)),
        "n_rows_starter": int(len(starters)),
    }

    # --- A: choose the SD form on held-out NLL --------------------------------
    test_season = seasons[-1]
    train_seasons = seasons[:-1]
    held_out = compare_forms(starters, train_seasons, test_season)
    print(f"\nHeld-out NLL (fit {train_seasons}, test {test_season}):")
    print(held_out.round(4).to_string())
    totals = held_out.loc["ALL", [FORM_CONSTANT, FORM_SQRT]]
    form = str(totals.idxmin())
    report["held_out_nll"] = held_out.round(5).reset_index().to_dict("records")
    report["form"] = form
    print(f"Chosen form: {form}")

    pooled, default = fit_coefficients(starters, form)
    per_league = {
        slug: fit_coefficients(starters[starters["league"] == slug], form)[0]
        for slug in leagues_scoring
    }
    print("\nPooled coefficients:", {k: round(v, 4) for k, v in pooled.items()})
    spread = {}
    for position in pooled:
        values = [per_league[slug][position] for slug in per_league]
        spread[position] = (max(values) - min(values)) / pooled[position]
    for slug, coefficients in per_league.items():
        print(slug, {k: round(v, 4) for k, v in coefficients.items()})
    print(
        "Relative max-min spread by position:",
        {k: round(v, 4) for k, v in spread.items()},
    )
    train_coefficients, train_default = fit_coefficients(
        starters[starters["season"].isin(train_seasons)], form
    )
    bias = (
        (starters["actual"] - starters["projection"])
        .groupby(starters["position"])
        .mean()
    )
    report["pooled_coefficients"] = {k: _round(v) for k, v in pooled.items()}
    report["per_league_coefficients"] = {
        slug: {k: _round(v) for k, v in c.items()} for slug, c in per_league.items()
    }
    report["league_relative_spread"] = {k: _round(v) for k, v in spread.items()}
    report["n_by_position"] = starters.groupby("position").size().to_dict()
    report["n_by_league_position"] = {
        slug: starters[starters["league"] == slug].groupby("position").size().to_dict()
        for slug in leagues_scoring
    }
    report["mean_residual"] = {k: _round(v) for k, v in bias.items()}
    report["train_only_coefficients"] = {
        k: _round(v) for k, v in train_coefficients.items()
    }

    base_metadata = {
        "sd_fit_seasons": seasons,
        "sd_held_out_season": test_season,
        "sd_n_player_weeks": int(len(starters)),
        "sd_form_nll": {
            name: _round(totals[name], 5) for name in (FORM_CONSTANT, FORM_SQRT)
        },
        "starter_counts": STARTER_COUNTS,
        "per_league_coefficients": report["per_league_coefficients"],
        "league_relative_spread": report["league_relative_spread"],
    }

    # --- B: calibrate lambda --------------------------------------------------
    calibrated = False
    multiplier = 1.0
    metadata = dict(base_metadata)
    if sleeper_ok:
        season = args.calibration_season
        raw_by_season = {y: frames[y] for y in (season - 1, season)}
        games_by_league = {}
        for slug, payload in league_payloads.items():
            games_by_league[slug] = build_calibration_games(
                payload,
                catalog,
                crosswalk,
                scored_by_league[slug],
                raw_by_season,
                games,
                rolling[season],
                usage_weeks[usage_weeks["season"].isin([season - 1, season])]
                if usage_weeks is not None
                else None,
                season,
            ).assign(league=slug)
        raw_games = pd.concat(games_by_league.values(), ignore_index=True)
        stored = WinProbabilityParameters(
            form=form,
            coefficients=pooled,
            default_coefficient=default,
            margin_sd_multiplier=1.0,
            calibrated=False,
        )
        train_only = WinProbabilityParameters(
            form=form,
            coefficients=train_coefficients,
            default_coefficient=train_default,
            margin_sd_multiplier=1.0,
            calibrated=False,
        )
        moments = game_moments(raw_games, stored)
        n_ties = int(moments["tie"].sum())
        scored_games = moments[~moments["tie"]].reset_index(drop=True)
        multiplier = fit_lambda(scored_games)
        calibrated = True
        # Missing-projection accounting.
        slots = sum(len(x) for x in raw_games["projections_a"]) + sum(
            len(x) for x in raw_games["projections_b"]
        )
        missing_slots = sum(
            int(np.isnan(x).sum()) for x in raw_games["projections_a"]
        ) + sum(int(np.isnan(x).sum()) for x in raw_games["projections_b"])

        fitted = WinProbabilityParameters(
            form=form,
            coefficients=pooled,
            default_coefficient=default,
            margin_sd_multiplier=multiplier,
            calibrated=True,
        )
        unit = WinProbabilityParameters(
            form=form,
            coefficients=pooled,
            default_coefficient=default,
            margin_sd_multiplier=1.0,
            calibrated=True,
        )
        y = scored_games["a_wins"].to_numpy()
        diff = (scored_games["mu_a"] - scored_games["mu_b"]).to_numpy()
        results = {
            "coin_flip": forecast_metrics(np.full(len(y), 0.5), y, diff),
            "lambda_1": forecast_metrics(probabilities(scored_games, unit), y, diff),
            "lambda_fitted": forecast_metrics(
                probabilities(scored_games, fitted), y, diff
            ),
        }
        # Favorite accuracy is undefined for a coin flip.
        results["coin_flip"]["favorite_accuracy"] = None
        table_fitted = calibration_table(probabilities(scored_games, fitted), y)
        table_unit = calibration_table(probabilities(scored_games, unit), y)

        loo = {}
        for slug in games_by_league:
            rest = scored_games[scored_games["league"] != slug]
            held = scored_games[scored_games["league"] == slug]
            lam = fit_lambda(rest)
            held_params = WinProbabilityParameters(
                form=form,
                coefficients=pooled,
                default_coefficient=default,
                margin_sd_multiplier=lam,
                calibrated=True,
            )
            held_y = held["a_wins"].to_numpy()
            held_diff = (held["mu_a"] - held["mu_b"]).to_numpy()
            loo[slug] = {
                "lambda_from_other_leagues": _round(lam),
                "lambda_in_league": _round(fit_lambda(held.reset_index(drop=True))),
                "n_games": int(len(held)),
                "held_out": forecast_metrics(
                    probabilities(held, held_params), held_y, held_diff
                ),
                "held_out_lambda_1": forecast_metrics(
                    probabilities(held, unit), held_y, held_diff
                ),
            }
        # Sensitivity: SD coefficients fitted without the calibration season.
        sensitivity_moments = game_moments(raw_games, train_only)
        sensitivity_moments = sensitivity_moments[
            ~sensitivity_moments["tie"]
        ].reset_index(drop=True)
        sensitivity_lambda = fit_lambda(sensitivity_moments)

        # Team-level residual diagnostics: how far the pre-kickoff mean was
        # from the realised score, against the model's own SD.
        residual = np.concatenate(
            [
                (scored_games["points_a"] - scored_games["mu_a"]).to_numpy(),
                (scored_games["points_b"] - scored_games["mu_b"]).to_numpy(),
            ]
        )
        model_sd = np.concatenate(
            [scored_games["sd_a"].to_numpy(), scored_games["sd_b"].to_numpy()]
        )
        # Bootstrap over games (seeded): lambda and the log-loss gain over a
        # coin flip at the fitted lambda. Weeks share players, so this
        # understates the uncertainty a little.
        rng = np.random.default_rng(0)
        boot_lambda, boot_gain = [], []
        for _ in range(BOOTSTRAP_REPS):
            draw = scored_games.iloc[
                rng.integers(0, len(scored_games), len(scored_games))
            ].reset_index(drop=True)
            boot_lambda.append(fit_lambda(draw))
            boot_gain.append(math.log(2.0) - log_loss_for_lambda(draw, multiplier))
        by_league_n = scored_games.groupby("league").size().to_dict()
        mean_sd_a = float(scored_games["sd_a"].mean())
        mean_margin_sd = float(
            (np.sqrt(scored_games["sd_a"] ** 2 + scored_games["sd_b"] ** 2)).mean()
        )
        actual_margin = scored_games["points_a"] - scored_games["points_b"]
        report["calibration"] = {
            "n_games": int(len(scored_games)),
            "n_ties_dropped": n_ties,
            "n_by_league": by_league_n,
            "weeks": "2..last regular-season week per league",
            "starter_slots": int(slots),
            "slots_without_projection": int(missing_slots),
            "lambda": _round(multiplier),
            "metrics": results,
            "calibration_fitted": table_fitted.round(4)
            .reset_index()
            .to_dict("records"),
            "calibration_lambda_1": table_unit.round(4)
            .reset_index()
            .to_dict("records"),
            "leave_one_league_out": loo,
            "lambda_with_train_only_sd": _round(sensitivity_lambda),
            "team_residual_mean": _round(float(residual.mean())),
            "team_residual_sd": _round(float(residual.std(ddof=0))),
            "team_model_sd_rms": _round(float(np.sqrt(np.mean(model_sd**2)))),
            "bootstrap_reps": BOOTSTRAP_REPS,
            "lambda_bootstrap_95": [
                _round(float(np.percentile(boot_lambda, 2.5))),
                _round(float(np.percentile(boot_lambda, 97.5))),
            ],
            "log_loss_gain_vs_coin_bootstrap_95": [
                _round(float(np.percentile(boot_gain, 2.5))),
                _round(float(np.percentile(boot_gain, 97.5))),
            ],
            "mean_team_sd": _round(mean_sd_a),
            "mean_unscaled_margin_sd": _round(mean_margin_sd),
            "actual_margin_sd": _round(float(actual_margin.std(ddof=0))),
            "mean_abs_projected_margin": _round(float(np.abs(diff).mean())),
        }
        calib = report["calibration"]
        print(
            f"\nCalibration games: {calib['n_games']} {by_league_n}, "
            f"ties dropped {n_ties}"
        )
        print(f"Starter slots {slots}, without projection {missing_slots}")
        print(
            json.dumps(
                {
                    k: calib[k]
                    for k in (
                        "team_residual_mean",
                        "team_residual_sd",
                        "team_model_sd_rms",
                        "lambda_bootstrap_95",
                        "log_loss_gain_vs_coin_bootstrap_95",
                    )
                }
            )
        )
        print(
            f"lambda = {multiplier:.4f} "
            f"(train-only SD sensitivity {sensitivity_lambda:.4f})"
        )
        print(json.dumps(results, indent=2))
        print("Calibration (fitted lambda):")
        print(table_fitted.round(3).to_string())
        print("Calibration (lambda=1):")
        print(table_unit.round(3).to_string())
        print(json.dumps(loo, indent=2))
        metadata.update(
            {
                "calibration_season": season,
                "calibration_n_games": int(len(scored_games)),
                "calibration_metrics": {
                    name: {
                        k: (_round(v) if isinstance(v, float) else v)
                        for k, v in m.items()
                    }
                    for name, m in results.items()
                },
                "lambda_bootstrap_95": calib["lambda_bootstrap_95"],
                "leave_one_league_out_lambda": {
                    slug: item["lambda_from_other_leagues"]
                    for slug, item in loo.items()
                },
            }
        )
    else:
        print("Calibration skipped: lambda = 1.0, calibrated = False.", file=sys.stderr)

    parameters = WinProbabilityParameters(
        form=form,
        coefficients={k: float(v) for k, v in pooled.items()},
        default_coefficient=float(default),
        margin_sd_multiplier=float(multiplier),
        calibrated=calibrated,
        metadata=metadata,
    )
    destination = save_win_probability_parameters(parameters, args.out)
    print(f"\nWrote {destination}", file=sys.stderr)
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
