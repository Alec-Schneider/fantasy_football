"""Tests for ``scripts/fetch_usage_seasons.py`` (FFA-110).

Only ``summarize_usage_season`` and the argument parser are tested, against
hand-built DataFrames: the download path it wraps is covered by the
snap-count and expected-points cache tests. No network.

``scripts/`` is not a package, so this file inserts it onto ``sys.path``
before importing, following ``tests/test_fetch_nflverse_seasons_script.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_usage_seasons import (  # noqa: E402
    MIN_REG_ROWS_PER_WEEK,
    build_arg_parser,
    summarize_usage_season,
)


def _snaps(rows_per_week: dict[int, int], game_type: str = "REG") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": 2025, "week": week, "game_type": game_type}
            for week, count in rows_per_week.items()
            for _ in range(count)
        ]
    )


def _ep(rows_per_week: dict[int, int], season: int = 2025) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"season": season, "week": week}
            for week, count in rows_per_week.items()
            for _ in range(count)
        ]
    )


def test_unpublished_season_is_reported() -> None:
    assert summarize_usage_season("snaps", 2011, pd.DataFrame()) == (
        "snaps 2011: no data published"
    )


def test_complete_snap_season() -> None:
    summary = summarize_usage_season(
        "snaps", 2025, _snaps({w: 1400 for w in range(1, 19)})
    )
    assert summary == "snaps 2025: 25200 rows, REG weeks 1-18"


def test_snap_postseason_rows_are_not_regular_season() -> None:
    frame = pd.concat([_snaps({1: 1400}), _snaps({19: 90}, game_type="WC")])
    summary = summarize_usage_season("snaps", 2025, frame)

    assert "REG weeks 1-1" in summary
    assert "PARTIAL" not in summary


def test_ep_regular_season_is_by_week_number() -> None:
    """ffopportunity has no season-type column: weeks 19-22 are playoffs."""
    frame = _ep({**{w: 330 for w in range(1, 19)}, 19: 120, 22: 19})
    summary = summarize_usage_season("ep", 2025, frame)

    assert "REG weeks 1-18" in summary
    assert "PARTIAL" not in summary

    before_2021 = summarize_usage_season(
        "ep", 2020, _ep({17: 300, 18: 40}, season=2020)
    )
    assert "REG weeks 17-17" in before_2021


def test_thin_first_week_of_a_new_season_is_flagged() -> None:
    thin = MIN_REG_ROWS_PER_WEEK["ep"] - 1
    summary = summarize_usage_season("ep", 2026, _ep({1: thin}, season=2026))
    assert "PARTIAL: week(s) 1 under-populated" in summary


def test_refresh_season_is_repeatable() -> None:
    args = build_arg_parser().parse_args(
        [
            "--start",
            "2025",
            "--end",
            "2026",
            "--refresh-season",
            "2026",
            "--refresh-season",
            "2025",
        ]
    )
    assert args.refresh_season == [2026, 2025]
    assert args.source == "both"
