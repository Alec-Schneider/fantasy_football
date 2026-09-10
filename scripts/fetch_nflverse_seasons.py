"""Populate the local nflverse cache with a range of seasons (FFA-088).

The rest-of-season projection work (FFA-089/090) is backtested against
held-out seasons, which needs many seasons of weekly player stats on disk in
a single consistent schema. This script is the one-line loop that puts them
there, over the existing
:func:`~fantasy_analyzer.players.nflverse_cache.get_player_stats_cached` --
it adds no new download or caching machinery of its own.

Why this exists rather than reusing ``.cache/nflverse/player_stats.csv``
--------------------------------------------------------------------------

That file is a 33 MB copy of nflverse's *retired* cumulative ``player_stats``
release asset, holding seasons 1999-2024 in the pre-migration schema (53
columns, ``recent_team``/``interceptions``/``sacks``). It is unreachable by
``load_player_stats_cache``, which looks only for per-season
``player_stats_<season>.csv`` filenames, and its column names do not match
what ``nflverse_provider`` expects. Rather than maintain a rename shim for a
frozen asset, this script re-downloads each season from the current
``stats_player`` release, which publishes per-season files back to 1999 in
the same 150-column schema the provider already targets.

Partially published seasons
----------------------------

An in-progress season is a normal, expected result, not an error: nflverse
publishes on its own schedule and a just-played week may not be processed
yet. This script reports each season's row count and week coverage so a
partially published season is *visible* rather than silently cached as if
complete -- downstream, FFA-090 must not read a missing player-week as a
zero.

Example::

    .venv/bin/python scripts/fetch_nflverse_seasons.py --start 2014 --end 2025

Network: one download per season not already cached (a few MB each).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd
import requests

from fantasy_analyzer.players.nflverse_cache import (
    DEFAULT_CACHE_DIR,
    get_player_stats_cached,
)
from fantasy_analyzer.players.nflverse_client import NflverseClient

#: Row count below which a published regular-season week is treated as
#: incompletely processed rather than genuinely small. Complete seasons in
#: the 2014-2025 cache carry roughly 1,000-1,100 rows per week; nflverse's
#: 2026 week 1 carried 67 the day after it was played.
MIN_ROWS_PER_WEEK = 300


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_nflverse_seasons.py",
        description="Populate the local nflverse cache with a range of seasons.",
    )
    parser.add_argument(
        "--start", type=int, required=True, help="First season to fetch, e.g. 2014."
    )
    parser.add_argument(
        "--end", type=int, required=True, help="Last season to fetch, inclusive."
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=f"Cache directory (default: {DEFAULT_CACHE_DIR}).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-download seasons already present in the cache.",
    )
    return parser


def summarize_season(season: int, stats: pd.DataFrame) -> str:
    """Return a one-line coverage summary for one cached season.

    Reports row count and regular-season week coverage so a partially
    published season is visible at a glance. A complete season carries
    roughly 1,000 rows per week; far fewer means nflverse has not finished
    processing that week yet.

    Args:
        season: The season being summarized, e.g. ``2025``.
        stats: That season's raw nflverse table, as cached.

    Returns:
        A human-readable summary line. Flags an empty season, and flags any
        regular-season week that is under a third of the season's own median
        week *or* under :data:`MIN_ROWS_PER_WEEK` rows. Both checks are
        needed: the relative one cannot see a season in which every week is
        thin, which is precisely a season one freshly played week old.
    """
    if stats.empty:
        return f"{season}: no data published yet"

    rows = len(stats)
    if "week" not in stats.columns:
        return f"{season}: {rows} rows (no week column)"

    regular = stats
    if "season_type" in stats.columns:
        regular = stats[stats["season_type"] == "REG"]
    if regular.empty:
        return f"{season}: {rows} rows, no regular-season weeks"

    per_week = regular.groupby("week").size()
    weeks = f"weeks {int(per_week.index.min())}-{int(per_week.index.max())}"

    # Two independent thresholds, because either alone has a blind spot. The
    # relative one catches a thin week in an otherwise-complete season; it is
    # useless when *every* week is thin, since then the median is thin too --
    # exactly the case of a season one partial week old. The absolute floor
    # catches that. Complete seasons run ~1,000-1,100 rows per week across
    # 2014-2025, so MIN_ROWS_PER_WEEK is well clear of a real week.
    thin = per_week[
        (per_week < per_week.median() / 3) | (per_week < MIN_ROWS_PER_WEEK)
    ]
    summary = f"{season}: {rows} rows, {weeks}"
    if len(thin):
        thin_weeks = ", ".join(str(int(week)) for week in thin.index)
        summary += f"  [PARTIAL: week(s) {thin_weeks} under-populated]"
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.end < args.start:
        print("--end must not be before --start", file=sys.stderr)
        return 2

    client = NflverseClient()
    failures = 0

    for season in range(args.start, args.end + 1):
        try:
            stats = get_player_stats_cached(
                client,
                season,
                cache_dir=args.cache_dir,
                force_refresh=args.force_refresh,
            )
        except requests.exceptions.RequestException as error:
            print(f"{season}: download failed ({error})", file=sys.stderr)
            failures += 1
            continue

        print(summarize_season(season, stats))

    if failures:
        print(f"\n{failures} season(s) failed to download.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
