#!/usr/bin/env python
"""Fit and persist the opportunity-first usage model (FFA-111).

``build_free_agent_ros_projections`` (and ``build_waiver_wire_rankings``)
run the usage model only when handed a fitted
:class:`~fantasy_analyzer.players.usage_projection.UsageModelParameters`.
Fitting needs a multi-season corpus and several minutes, so -- like
``scripts/fit_shrinkage_parameters.py`` -- it runs once and the result is
read back with ``load_usage_model_parameters()``.

Prerequisites -- cache the seasons to fit on (and the one before the first)::

    python scripts/fetch_nflverse_seasons.py --start 2014 --end 2025
    python scripts/fetch_usage_seasons.py --start 2014 --end 2025

Then::

    python scripts/fit_usage_model.py --start 2015 --end 2025

What is scoring-dependent: only the per-position blend weights (the EB
projection it blends against is in points). The volume and rate constants
are fitted in stat space and the absent-prior line is a stat line, so both
are scoring-independent. Measured blend weights differ by at most 0.05
between full PPR and half-PPR, so one fit serves every league; pass
``--league-id`` to fit against a specific league's settings instead.

The EB constants the blend is fitted against are the persisted
``shrinkage_parameters.json`` when it exists (the ones production uses),
otherwise they are fitted here on the same seasons.

Writes ``.cache/nflverse/usage_model_parameters.json`` by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fantasy_analyzer.league.snapshot import load_league_snapshot  # noqa: E402
from fantasy_analyzer.players.nflverse_cache import (  # noqa: E402
    load_player_stats_cache,
)
from fantasy_analyzer.players.ros_backtest import (  # noqa: E402
    build_scored_player_weeks,
)
from fantasy_analyzer.players.ros_projection import (  # noqa: E402
    load_shrinkage_parameters,
)
from fantasy_analyzer.players.usage_projection import (  # noqa: E402
    DEFAULT_FIT_CUTOFF_WEEKS,
    DEFAULT_USAGE_PARAMETERS_PATH,
    MODELED_POSITIONS,
    fit_usage_model,
    save_usage_model_parameters,
)
from fantasy_analyzer.sleeper.client import SleeperClient  # noqa: E402

#: Full-PPR ruleset used when no league is named. Same as
#: ``fit_shrinkage_parameters.PPR_SCORING_SETTINGS``, plus two-point
#: conversions, which every league in this project scores.
PPR_SCORING_SETTINGS = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "pass_2pt": 2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rush_2pt": 2.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "rec_2pt": 2.0,
    "fum_lost": -2.0,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start", type=int, default=2015, help="First season to fit on."
    )
    parser.add_argument("--end", type=int, default=2025, help="Last season to fit on.")
    parser.add_argument(
        "--league-id",
        default=None,
        help="Fit the blend weights against this league's scoring instead of PPR.",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_USAGE_PARAMETERS_PATH),
        help="Where to write the fitted parameters.",
    )
    parser.add_argument(
        "--cutoff-weeks",
        type=int,
        nargs="+",
        default=list(DEFAULT_FIT_CUTOFF_WEEKS),
        help="Cutoff weeks to pool the fit over.",
    )
    parser.add_argument(
        "--no-usage",
        action="store_true",
        help="Fit the no-snap model only (skip snap counts / expected points).",
    )
    args = parser.parse_args(argv)

    fit_seasons = list(range(args.start, args.end + 1))

    if args.league_id:
        snapshot = load_league_snapshot(SleeperClient(), args.league_id)
        scoring_settings = snapshot.scoring_settings
        print(f"Scoring: league {args.league_id}", file=sys.stderr)
    else:
        scoring_settings = PPR_SCORING_SETTINGS
        print("Scoring: standard PPR", file=sys.stderr)

    frames, missing = [], []
    for season in range(args.start - 1, args.end + 1):
        cached = load_player_stats_cache(season)
        if cached is None or cached.empty:
            missing.append(season)
            continue
        frames.append(cached)
    if missing:
        print(
            f"WARNING: no cached stats for {missing}; run "
            "scripts/fetch_nflverse_seasons.py first.",
            file=sys.stderr,
        )
    if not frames:
        print("No cached seasons at all -- nothing to fit.", file=sys.stderr)
        return 1
    scored = build_scored_player_weeks(frames, scoring_settings)

    usage_weeks = None
    if not args.no_usage:
        try:
            from fantasy_analyzer.players.usage import load_usage_player_weeks

            usage_weeks = load_usage_player_weeks(range(args.start - 1, args.end + 1))
        except (FileNotFoundError, ValueError, OSError) as error:
            print(
                f"WARNING: usage caches unavailable ({error}); fitting the "
                "no-snap model only.",
                file=sys.stderr,
            )

    eb_parameters = load_shrinkage_parameters()
    print(
        "EB constants: "
        + ("persisted shrinkage_parameters.json" if eb_parameters else "fitted here"),
        file=sys.stderr,
    )
    print(
        f"Fitting {list(MODELED_POSITIONS)} on {fit_seasons[0]}-{fit_seasons[-1]} "
        f"at cutoffs {args.cutoff_weeks} (several minutes)...",
        file=sys.stderr,
    )
    parameters = fit_usage_model(
        scored,
        fit_seasons,
        scoring_settings,
        usage_weeks=usage_weeks,
        cutoff_weeks=args.cutoff_weeks,
        eb_parameters=eb_parameters,
    )
    destination = save_usage_model_parameters(parameters, args.out)
    print(f"\nWrote {destination}\n", file=sys.stderr)

    for label, fitted in (
        ("snap model", parameters),
        ("no-snap fallback", parameters.no_snap_fallback),
    ):
        if fitted is None:
            continue
        print(f"{label}:")
        for position in fitted.positions():
            weight = fitted.blend_weight.get(position)
            volume = fitted.volume[position]
            print(
                f"  {position:<3} blend weight on usage = {weight}  "
                + "  ".join(
                    f"{stat}: n0={values.n0} d={values.prior_weight} "
                    f"rho={values.recency_weight} snap_n0={values.snap_n0}"
                    for stat, values in volume.items()
                    if values.baseline > 1.0
                )
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
