"""Populate the local snap-count and expected-points caches (FFA-110).

The opportunity-first projection work backtests on many seasons of usage
data, which needs every season on disk before
:func:`~fantasy_analyzer.players.usage.load_usage_player_weeks` (which never
touches the network) can read it. This script is the loop that puts it
there, over the existing cache helpers -- it adds no download or caching
machinery of its own, following ``fetch_nflverse_seasons.py``.

Two sources, each optional via ``--source``:

``snaps``
    nflverse's ``snap_counts_<season>.csv`` into ``.cache/nflverse``.
    Published from 2013 (2012 is a header-only file; earlier seasons 404).
``ep``
    ffopportunity's ``ep_weekly_<season>.csv`` into ``.cache/ffopportunity``.
    Published from 2006.

It also makes sure DynastyProcess's ID crosswalk
(``.cache/id_crosswalk/db_playerids.csv``) is cached, because snap counts
are keyed on PFR ids and are useless to the rest of the codebase without
the ``pfr_id -> gsis_id`` mapping. An existing crosswalk file is reused,
not re-downloaded; pass ``--refresh-crosswalk`` to replace it.

The current season changes weekly, so ``--refresh-season`` re-downloads
just that one season while leaving every settled season's cache alone::

    # first-time backfill
    .venv/bin/python scripts/fetch_usage_seasons.py --start 2014 --end 2026

    # every Tuesday during the season
    .venv/bin/python scripts/fetch_usage_seasons.py --start 2026 --end 2026 \\
        --refresh-season 2026

Each season prints a one-line summary of its regular-season week coverage,
flagging thin weeks, so a partially processed week is visible rather than
silently cached as complete -- the same concern ``fetch_nflverse_seasons.py``
documents.

Network: one download per season per source not already cached (0.4-5 MB).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

import pandas as pd
import requests

from fantasy_analyzer.players.expected_points_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_EP_CACHE_DIR,
)
from fantasy_analyzer.players.expected_points_cache import get_expected_points_cached
from fantasy_analyzer.players.expected_points_client import ExpectedPointsClient
from fantasy_analyzer.players.id_crosswalk_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_ID_CACHE_DIR,
)
from fantasy_analyzer.players.id_crosswalk_cache import get_player_ids_cached
from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient
from fantasy_analyzer.players.snap_counts_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_SNAP_CACHE_DIR,
)
from fantasy_analyzer.players.snap_counts_cache import get_snap_counts_cached
from fantasy_analyzer.players.snap_counts_client import SnapCountsClient
from fantasy_analyzer.players.usage import regular_season_last_week

#: Row count below which a published regular-season week is flagged as
#: incompletely processed, per source. Measured over the 2014-2025 caches,
#: the thinnest complete regular-season week carried roughly 1,150 snap rows
#: (every player on every active team, bye weeks included) and roughly 250
#: ep rows (skill players with at least one opportunity). The floors sit well
#: below both, so they catch a half-processed week without false alarms.
MIN_REG_ROWS_PER_WEEK = {"snaps": 700, "ep": 150}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_usage_seasons.py",
        description=(
            "Populate the local nflverse snap-count and ffopportunity "
            "expected-points caches with a range of seasons."
        ),
    )
    parser.add_argument(
        "--start", type=int, required=True, help="First season to fetch, e.g. 2014."
    )
    parser.add_argument(
        "--end", type=int, required=True, help="Last season to fetch, inclusive."
    )
    parser.add_argument(
        "--source",
        choices=("both", "snaps", "ep"),
        default="both",
        help="Which source(s) to fetch (default: both).",
    )
    parser.add_argument(
        "--snap-cache-dir",
        type=Path,
        default=DEFAULT_SNAP_CACHE_DIR,
        help=f"Snap-count cache directory (default: {DEFAULT_SNAP_CACHE_DIR}).",
    )
    parser.add_argument(
        "--ep-cache-dir",
        type=Path,
        default=DEFAULT_EP_CACHE_DIR,
        help=f"Expected-points cache directory (default: {DEFAULT_EP_CACHE_DIR}).",
    )
    parser.add_argument(
        "--id-cache-dir",
        type=Path,
        default=DEFAULT_ID_CACHE_DIR,
        help=f"ID-crosswalk cache directory (default: {DEFAULT_ID_CACHE_DIR}).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-download every season in range, even if already cached.",
    )
    parser.add_argument(
        "--refresh-season",
        type=int,
        action="append",
        default=[],
        metavar="SEASON",
        help=(
            "Re-download just this season (repeatable). Use for the "
            "in-progress season, which changes weekly."
        ),
    )
    parser.add_argument(
        "--refresh-crosswalk",
        action="store_true",
        help="Re-download DynastyProcess's ID crosswalk even if cached.",
    )
    return parser


def _regular_season_rows(source: str, frame: pd.DataFrame) -> pd.DataFrame:
    """The regular-season rows of one raw season table.

    Snap counts carry ``game_type`` (``REG`` for the regular season);
    ffopportunity carries no season-type column, so its regular season is
    every week at or before :func:`regular_season_last_week`.
    """
    if source == "snaps":
        if "game_type" in frame.columns:
            return frame[frame["game_type"] == "REG"]
        return frame
    if "season" not in frame.columns:
        return frame
    last_week = frame["season"].map(regular_season_last_week)
    return frame[frame["week"] <= last_week]


def summarize_usage_season(source: str, season: int, frame: pd.DataFrame) -> str:
    """Return a one-line coverage summary for one cached source-season.

    Args:
        source: ``"snaps"`` or ``"ep"``.
        season: The season being summarized, e.g. ``2026``.
        frame: That season's raw table, as cached.

    Returns:
        A human-readable summary: total rows and the regular-season week
        span, with any regular-season week under a third of the season's own
        median week *or* under :data:`MIN_REG_ROWS_PER_WEEK` flagged as
        partial. Both checks are needed for the reason
        ``fetch_nflverse_seasons.summarize_season`` gives: the relative one
        cannot see a season in which every week is thin.
    """
    label = f"{source} {season}"
    if frame.empty:
        return f"{label}: no data published"
    rows = len(frame)
    if "week" not in frame.columns:
        return f"{label}: {rows} rows (no week column)"

    regular = _regular_season_rows(source, frame)
    if regular.empty:
        return f"{label}: {rows} rows, no regular-season weeks"

    per_week = regular.groupby("week").size()
    weeks = f"weeks {int(per_week.index.min())}-{int(per_week.index.max())}"
    floor = MIN_REG_ROWS_PER_WEEK.get(source, 0)
    thin = per_week[(per_week < per_week.median() / 3) | (per_week < floor)]

    summary = f"{label}: {rows} rows, REG {weeks}"
    if len(thin):
        thin_weeks = ", ".join(str(int(week)) for week in thin.index)
        summary += f"  [PARTIAL: week(s) {thin_weeks} under-populated]"
    return summary


def _fetch_one(
    fetch: Callable[[], pd.DataFrame], source: str, season: int
) -> Optional[str]:
    """Run one cached fetch, returning its summary or ``None`` on failure."""
    try:
        frame = fetch()
    except requests.exceptions.RequestException as error:
        print(f"{source} {season}: download failed ({error})", file=sys.stderr)
        return None
    return summarize_usage_season(source, season, frame)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.end < args.start:
        print("--end must not be before --start", file=sys.stderr)
        return 2

    try:
        player_ids = get_player_ids_cached(
            PlayerIdCrosswalkClient(),
            cache_dir=args.id_cache_dir,
            force_refresh=args.refresh_crosswalk,
        )
        print(f"id crosswalk: {len(player_ids)} rows")
    except requests.exceptions.RequestException as error:
        print(f"id crosswalk: download failed ({error})", file=sys.stderr)
        return 1

    snap_client = SnapCountsClient()
    ep_client = ExpectedPointsClient()
    refresh_seasons = set(args.refresh_season)
    failures = 0

    for season in range(args.start, args.end + 1):
        force = args.force_refresh or season in refresh_seasons
        fetches: list[tuple[str, Callable[[], pd.DataFrame]]] = []
        if args.source in ("both", "snaps"):
            fetches.append(
                (
                    "snaps",
                    lambda season=season, force=force: get_snap_counts_cached(
                        snap_client,
                        season,
                        cache_dir=args.snap_cache_dir,
                        force_refresh=force,
                    ),
                )
            )
        if args.source in ("both", "ep"):
            fetches.append(
                (
                    "ep",
                    lambda season=season, force=force: get_expected_points_cached(
                        ep_client,
                        season,
                        cache_dir=args.ep_cache_dir,
                        force_refresh=force,
                    ),
                )
            )

        for source, fetch in fetches:
            summary = _fetch_one(fetch, source, season)
            if summary is None:
                failures += 1
            else:
                print(summary)

    if failures:
        print(f"\n{failures} source-season(s) failed to download.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
