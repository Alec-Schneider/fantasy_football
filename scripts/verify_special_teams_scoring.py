#!/usr/bin/env python
"""Verify league scoring against Sleeper's own points, and backtest K/DEF (FFA-112).

Two modes.

``--scoring`` (default): Sleeper's raw matchup payload carries
``players_points`` -- Sleeper's own computed fantasy points for every
rostered player, starters and bench, including kickers and team ``DEF``
codes. That is an oracle for this package's scoring engine. For each
league preset in ``draft_league_presets.LEAGUES`` (its current season and,
by walking ``previous_league_id``, the one before), every rostered
player-week is re-scored from the cached nflverse data with
``calculate_fantasy_points`` (QB/RB/WR/TE/K) or
``build_team_defense_weeks`` + ``calculate_team_defense_points`` (DEF), and
compared. A match is ``|ours - Sleeper| < 0.05``.

``--backtest``: rolling-origin backtest of
``kicker_defense.build_kicker_defense_projections``'s estimator on
2019-2025 (each season fitted on 2016 through the season before), under
each league's scoring, plus the parameters fitted on all of 2016-2025.

Sleeper payloads are cached under ``.cache/sleeper/verification/`` so a
rerun makes no network calls; pass ``--refresh`` to refetch. nflverse
seasons must already be cached (``scripts/fetch_nflverse_seasons.py``).

Usage::

    python scripts/verify_special_teams_scoring.py
    python scripts/verify_special_teams_scoring.py --by-week
    python scripts/verify_special_teams_scoring.py --backtest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402
from draft_league_presets import LEAGUES  # noqa: E402

from fantasy_analyzer.players.crosswalk import (  # noqa: E402
    build_robust_id_crosswalk,
    sleeper_to_gsis_lookup,
)
from fantasy_analyzer.players.kicker_defense import (  # noqa: E402
    build_defense_weeks,
    build_kicker_weeks,
    build_team_week_schedule,
    fit_kicker_defense_parameters,
    resolve_kicker_gsis_ids,
    run_kicker_defense_backtest,
)
from fantasy_analyzer.players.nflverse_cache import (  # noqa: E402
    load_player_stats_cache,
)
from fantasy_analyzer.players.nflverse_defense import (  # noqa: E402
    build_team_defense_weeks,
)
from fantasy_analyzer.players.nflverse_schedule_cache import (  # noqa: E402
    load_games_cache,
)
from fantasy_analyzer.players.scoring import (  # noqa: E402
    TEAM_DEFENSE_KEY_TO_STAT_COLUMNS,
    calculate_fantasy_points,
    calculate_team_defense_points,
    points_allowed_tier,
)
from fantasy_analyzer.sleeper.cache import load_player_cache  # noqa: E402
from fantasy_analyzer.sleeper.client import SleeperClient  # noqa: E402

DEFAULT_CACHE_DIR = Path(".cache/sleeper/verification")
MATCH_TOLERANCE = 0.05
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


def _cached_json(path: Path, fetch, refresh: bool):
    """Load ``path`` or fetch-and-write it."""
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    payload = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return payload


def load_league_seasons(
    slugs: Sequence[str], cache_dir: Path, refresh: bool
) -> list[dict]:
    """Each preset's current league and its previous season, with matchups."""
    client = SleeperClient(timeout=30)
    seasons = []
    for slug in slugs:
        league_id: Optional[str] = LEAGUES[slug]["league_id"]
        for _ in range(2):
            if not league_id:
                break
            lid = league_id
            league = _cached_json(
                cache_dir / lid / "league.json",
                lambda lid=lid: client.get_league(lid),
                refresh,
            )
            last_week = int(league.get("settings", {}).get("last_scored_leg") or 0)
            matchups = {
                week: _cached_json(
                    cache_dir / lid / f"matchups_{week}.json",
                    lambda lid=lid, week=week: client.get_matchups(lid, week),
                    refresh,
                )
                for week in range(1, last_week + 1)
            }
            seasons.append({"slug": slug, "league": league, "matchups": matchups})
            league_id = league.get("previous_league_id")
    return seasons


def oracle_frame(league_season: dict, catalog: dict) -> pd.DataFrame:
    """One row per rostered player-week: Sleeper's own points."""
    league = league_season["league"]
    rows = []
    for week, teams in league_season["matchups"].items():
        for team in teams or []:
            for player_id, points in (team.get("players_points") or {}).items():
                rows.append(
                    {
                        "slug": league_season["slug"],
                        "league_id": league["league_id"],
                        "season": int(league["season"]),
                        "week": int(week),
                        "player_id": str(player_id),
                        "position": (catalog.get(player_id) or {}).get("position"),
                        "sleeper_points": float(points),
                    }
                )
    frame = pd.DataFrame(rows)
    # A player rostered twice in one league-week (never, but cheap to guard).
    return frame.drop_duplicates(["league_id", "week", "player_id"])


def score_league_season(
    oracle: pd.DataFrame,
    scoring_settings: dict,
    raw: pd.DataFrame,
    games: pd.DataFrame,
    season: int,
    sleeper_to_gsis: dict,
) -> pd.DataFrame:
    """Attach our points to every oracle row (0.0 when nflverse has no row)."""
    regular = raw[raw["season_type"] == "REG"]
    players = calculate_fantasy_points(regular, scoring_settings).points_df
    player_points = players[["player_id", "week", "fantasy_points"]].rename(
        columns={"player_id": "gsis_id"}
    )
    defense = calculate_team_defense_points(
        build_team_defense_weeks(raw, games, season), scoring_settings
    ).points_df[["team", "week", "fantasy_points"]]

    offense = oracle[oracle["position"].isin(["QB", "RB", "WR", "TE", "K"])].copy()
    offense["gsis_id"] = offense["player_id"].map(sleeper_to_gsis)
    offense = offense.merge(player_points, on=["gsis_id", "week"], how="left")
    team_def = oracle[oracle["position"] == "DEF"].merge(
        defense, left_on=["player_id", "week"], right_on=["team", "week"], how="left"
    )
    scored = pd.concat([offense, team_def.drop(columns="team")], ignore_index=True)
    scored["fantasy_points"] = scored["fantasy_points"].fillna(0.0)
    scored["diff"] = scored["fantasy_points"] - scored["sleeper_points"]
    scored["match"] = scored["diff"].abs() < MATCH_TOLERANCE
    return scored


def run_scoring(args: argparse.Namespace) -> None:
    catalog = load_player_cache()
    if catalog is None:
        raise SystemExit("No cached Sleeper catalog; run a pipeline that caches it.")
    games = load_games_cache()
    crosswalk = build_robust_id_crosswalk(catalog)
    base_lookup = sleeper_to_gsis_lookup(crosswalk)

    frames = []
    league_seasons = load_league_seasons(args.leagues, args.cache_dir, args.refresh)
    for league_season in league_seasons:
        league = league_season["league"]
        season = int(league["season"])
        raw = load_player_stats_cache(season)
        if raw is None:
            print(f"skip {league['name']} {season}: nflverse season not cached")
            continue
        kicker_ids = resolve_kicker_gsis_ids(
            catalog, build_kicker_weeks(raw, league["scoring_settings"]), crosswalk
        )
        lookup = {**base_lookup, **kicker_ids}
        oracle = oracle_frame(league_season, catalog)
        frames.append(
            score_league_season(
                oracle, league["scoring_settings"], raw, games, season, lookup
            )
        )
        settings = league["scoring_settings"]
        empty = pd.DataFrame()
        player_gaps = calculate_fantasy_points(empty, settings).unsupported_scoring_keys
        defense_gaps = calculate_team_defense_points(
            empty, settings
        ).unsupported_scoring_keys
        applied_by_defense = {
            key
            for key in settings
            if key in TEAM_DEFENSE_KEY_TO_STAT_COLUMNS
            or points_allowed_tier(key) is not None
        }
        weighted_unsupported = sorted(
            key
            for key in set(player_gaps) | set(defense_gaps)
            if settings[key] != 0 and key not in applied_by_defense
        )
        print(
            f"{league_season['slug']:9s} {season} {league['league_id']}: "
            f"weighted keys neither engine applies: {weighted_unsupported}"
        )
    scored = pd.concat(frames, ignore_index=True)
    scored = scored[scored["position"].isin(POSITIONS)]

    def summarize(group_columns: list[str]) -> pd.DataFrame:
        summary = scored.groupby(group_columns).agg(
            n=("match", "size"),
            matched=("match", "sum"),
            mean_abs_diff=("diff", lambda d: d.abs().mean()),
        )
        summary["match_rate"] = (summary["matched"] / summary["n"]).round(4)
        return summary

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 500)
    print("\nMatch rate by season and position (all leagues pooled):")
    print(summarize(["season", "position"]).to_string())
    print("\nMatch rate by league, season and position:")
    print(summarize(["slug", "season", "position"]).to_string())
    if args.by_week:
        print("\nMatch rate by league, season and week (K and DEF):")
        special = scored[scored["position"].isin(["K", "DEF"])]
        by_week = special.groupby(["slug", "season", "week", "position"])["match"].agg(
            ["size", "sum"]
        )
        print(by_week.unstack("position").to_string())
    residuals = scored[~scored["match"] & scored["position"].isin(args.residuals)]
    print(f"\nResiduals for {args.residuals} ({len(residuals)} rows):")
    print(
        residuals.sort_values(["position", "season", "week", "slug"])[
            [
                "slug",
                "season",
                "week",
                "position",
                "player_id",
                "sleeper_points",
                "fantasy_points",
                "diff",
            ]
        ].to_string(index=False)
    )


def run_backtest(args: argparse.Namespace) -> None:
    games = load_games_cache()
    seasons = range(args.first_fit_season - 1, args.last_season + 1)
    raw_by_season = {season: load_player_stats_cache(season) for season in seasons}
    missing = [season for season, raw in raw_by_season.items() if raw is None]
    if missing:
        raise SystemExit(f"nflverse seasons not cached: {missing}")
    schedules = {season: build_team_week_schedule(games, season) for season in seasons}
    catalog_leagues = load_league_seasons(args.leagues, args.cache_dir, args.refresh)
    current = [ls for ls in catalog_leagues if ls["league"]["status"] != "complete"]
    for league_season in current or catalog_leagues:
        settings = league_season["league"]["scoring_settings"]
        weeks = pd.concat(
            [build_kicker_weeks(raw, settings) for raw in raw_by_season.values()]
            + [
                build_defense_weeks(raw, games, season, settings)
                for season, raw in raw_by_season.items()
            ],
            ignore_index=True,
        )
        results = run_kicker_defense_backtest(
            weeks,
            schedules,
            list(range(args.first_eval_season, args.last_season + 1)),
            first_fit_season=args.first_fit_season,
            cutoffs=args.cutoffs,
        )
        pooled = results.groupby(["position", "horizon", "method"]).apply(
            lambda frame: pd.Series(
                {
                    "n": int(frame["n"].sum()),
                    "mae": (frame["mae"] * frame["n"]).sum() / frame["n"].sum(),
                }
            ),
            include_groups=False,
        )
        full = fit_kicker_defense_parameters(
            weeks,
            schedules,
            list(range(args.first_fit_season, args.last_season + 1)),
        )
        print(
            f"\n{league_season['slug']} ({league_season['league']['season']} "
            f"scoring): holdout {args.first_eval_season}-{args.last_season}, "
            f"cutoffs {list(args.cutoffs)}"
        )
        print(pooled.round(3).to_string())
        print(f"fitted on {args.first_fit_season}-{args.last_season}: {full}")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--leagues", nargs="+", default=list(LEAGUES))
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--by-week", action="store_true")
    parser.add_argument("--residuals", nargs="*", default=["K", "DEF"])
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--first-fit-season", type=int, default=2016)
    parser.add_argument("--first-eval-season", type=int, default=2019)
    parser.add_argument("--last-season", type=int, default=2025)
    parser.add_argument("--cutoffs", type=int, nargs="+", default=[3, 4])
    args = parser.parse_args(argv)
    if args.backtest:
        run_backtest(args)
    else:
        run_scoring(args)


if __name__ == "__main__":
    main()
