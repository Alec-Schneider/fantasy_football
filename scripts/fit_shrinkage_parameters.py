#!/usr/bin/env python
"""Fit and persist per-position shrinkage parameters (FFA-101).

``build_free_agent_rankings`` (and anything else calling
``load_shrinkage_parameters``) uses a **uniform, unfitted** ``n0 = 3.0``
unless a fitted parameter file exists. ``docs/ros-projection-accuracy.md``
measures the fitted per-position values as meaningfully more accurate, but
fitting needs a multi-season corpus on disk and takes real time -- not
something a single ranking command should do.

This script closes that gap: run it once (and again when a season ends) and
every downstream ranking picks the fitted values up automatically.

Prerequisite -- cache the seasons to fit on::

    python scripts/fetch_nflverse_seasons.py --start 2016 --end 2025

Then::

    python scripts/fit_shrinkage_parameters.py --start 2016 --end 2025

Scoring: the fit needs *fantasy points*, which depend on a league's scoring
settings. Rather than pick a league, this defaults to a standard PPR
ruleset (``--scoring ppr``), because ``n0`` describes how fast a position's
evidence accumulates -- a property of the position's week-to-week variance
relative to its between-player spread, which is not very sensitive to the
scoring ruleset. Pass ``--league-id`` to fit against a specific league's
actual settings instead.

Writes ``.cache/nflverse/shrinkage_parameters.json`` by default.
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
    DEFAULT_SHRINKAGE_PARAMETERS_PATH,
    fit_shrinkage,
    save_shrinkage_parameters,
)
from fantasy_analyzer.sleeper.client import SleeperClient  # noqa: E402

#: A conventional full-PPR ruleset, used when no league is named. Only the
#: keys that matter to the offensive skill positions the fit covers.
PPR_SCORING_SETTINGS = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "fum_lost": -2.0,
}

#: Positions the fit is restricted to by default.
#:
#: Left unrestricted, ``fit_shrinkage`` fits every position present in the
#: corpus -- and nflverse tracks incidental stat rows for offensive
#: linemen, defensive backs and long snappers, whose fantasy points under
#: an offensive ruleset are almost always exactly zero. A zero-variance
#: column "fits" to whatever grid value happens to come first, at an MAE
#: near 0.000, producing authoritative-looking nonsense (measured: ``OT``
#: n0 = 12.0, ``CB`` n0 = 0.5).
#:
#: Kickers are excluded for a different reason: the default PPR ruleset
#: below carries no field-goal keys at all, so every kicker scores 0.0 and
#: fits the same degenerate way. Pass ``--positions QB RB WR TE K``
#: *together with* ``--league-id`` (whose real settings do score kicking)
#: if a fitted kicker value is wanted.
#:
#: Every position left unfitted falls back to ``default_n0``, which is the
#: honest outcome for a position this corpus cannot speak to.
DEFAULT_FIT_POSITIONS = ("QB", "RB", "WR", "TE")

#: Cutoff weeks the fit pools over. Spans the range a waiver decision is
#: actually made in; see ``fit_shrinkage``'s docstring on why pooling
#: across cutoffs is correct rather than convenient.
DEFAULT_CUTOFF_WEEKS = (3, 5, 7, 9, 11)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start", type=int, default=2016, help="First season to fit on."
    )
    parser.add_argument("--end", type=int, default=2025, help="Last season to fit on.")
    parser.add_argument(
        "--league-id",
        default=None,
        help="Fit against this Sleeper league's scoring settings instead of PPR.",
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_SHRINKAGE_PARAMETERS_PATH),
        help="Where to write the fitted parameters.",
    )
    parser.add_argument(
        "--cutoff-weeks",
        type=int,
        nargs="+",
        default=list(DEFAULT_CUTOFF_WEEKS),
        help="Cutoff weeks to pool the fit over.",
    )
    parser.add_argument(
        "--positions",
        nargs="+",
        default=list(DEFAULT_FIT_POSITIONS),
        help="Positions to fit; every other position falls back to default_n0.",
    )
    args = parser.parse_args(argv)

    seasons = list(range(args.start, args.end + 1))

    if args.league_id:
        snapshot = load_league_snapshot(SleeperClient(), args.league_id)
        scoring_settings = snapshot.scoring_settings
        print(f"Scoring: league {args.league_id}", file=sys.stderr)
    else:
        scoring_settings = PPR_SCORING_SETTINGS
        print("Scoring: standard PPR", file=sys.stderr)

    frames = []
    missing = []
    for season in seasons:
        cached = load_player_stats_cache(season)
        if cached is None or cached.empty:
            missing.append(season)
            continue
        frames.append(cached)

    if missing:
        print(
            f"WARNING: no cached stats for {missing}; run "
            f"scripts/fetch_nflverse_seasons.py --start {args.start} --end {args.end}",
            file=sys.stderr,
        )
    if not frames:
        print("No cached seasons at all -- nothing to fit.", file=sys.stderr)
        return 1

    print(f"Scoring {len(frames)} cached seasons...", file=sys.stderr)
    scored = build_scored_player_weeks(frames, scoring_settings)

    fit_seasons = sorted(set(scored["season"].unique()))
    print(
        f"Fitting n0 for {args.positions} over seasons "
        f"{fit_seasons[0]}-{fit_seasons[-1]} at cutoffs {args.cutoff_weeks}...",
        file=sys.stderr,
    )
    parameters = fit_shrinkage(
        scored, fit_seasons, args.cutoff_weeks, positions=args.positions
    )

    destination = save_shrinkage_parameters(parameters, args.out)
    print(f"\nWrote {destination}\n", file=sys.stderr)
    for position in sorted(parameters.n0_by_position):
        mae = (parameters.fit_mae or {}).get(position)
        mae_text = f"  MAE {mae:.3f}" if mae is not None else ""
        print(
            f"  {position:<5} n0 = {parameters.n0_by_position[position]:<5}{mae_text}"
        )
    if not parameters.n0_by_position:
        print(
            f"  (no position had enough rows; every one falls back to "
            f"{parameters.default_n0})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
