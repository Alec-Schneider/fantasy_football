"""Tests for ``scripts/fetch_nflverse_seasons.py`` (FFA-088).

Only ``summarize_season`` is tested here, against hand-built DataFrames --
it holds the whole of the script's logic, and the download path it wraps is
already covered by ``tests/players/test_nflverse_cache.py``. No network.

``scripts/`` is not a package, so this file inserts it onto ``sys.path``
before importing, following ``tests/test_draft_report_script.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from fetch_nflverse_seasons import (  # noqa: E402
    MIN_ROWS_PER_WEEK,
    summarize_season,
)


def _season_frame(rows_per_week: dict[int, int], season: int = 2025) -> pd.DataFrame:
    """A minimal nflverse-shaped frame with the given regular-season weeks."""
    records = [
        {"season": season, "week": week, "season_type": "REG"}
        for week, count in rows_per_week.items()
        for _ in range(count)
    ]
    return pd.DataFrame(records)


def test_empty_season_is_reported_not_raised() -> None:
    assert summarize_season(2027, pd.DataFrame()) == "2027: no data published yet"


def test_complete_season_reports_row_count_and_week_span() -> None:
    stats = _season_frame({week: 1000 for week in range(1, 19)})
    summary = summarize_season(2025, stats)

    assert summary == "2025: 18000 rows, weeks 1-18"
    assert "PARTIAL" not in summary


def test_thin_week_inside_a_full_season_is_flagged() -> None:
    """The relative check: one week far below the season's own median."""
    rows = {week: 1000 for week in range(1, 18)}
    rows[18] = 40
    summary = summarize_season(2025, _season_frame(rows))

    assert "PARTIAL: week(s) 18 under-populated" in summary


def test_season_where_every_week_is_thin_is_still_flagged() -> None:
    """The absolute floor: the case the relative check cannot see.

    nflverse's 2026 file the day after week 1 held 67 rows. With a single
    week, that week *is* the median, so a median-relative test alone would
    call it complete. MIN_ROWS_PER_WEEK is what catches it.
    """
    summary = summarize_season(2026, _season_frame({1: 67}, season=2026))

    assert "PARTIAL: week(s) 1 under-populated" in summary


def test_a_week_exactly_at_the_floor_is_not_flagged() -> None:
    """The boundary is exclusive: `< MIN_ROWS_PER_WEEK` flags, equal does not."""
    stats = _season_frame({1: MIN_ROWS_PER_WEEK, 2: MIN_ROWS_PER_WEEK})
    assert "PARTIAL" not in summarize_season(2026, stats)

    thin = _season_frame({1: MIN_ROWS_PER_WEEK - 1, 2: MIN_ROWS_PER_WEEK})
    assert "PARTIAL: week(s) 1" in summarize_season(2026, thin)


def test_postseason_only_rows_are_reported_separately() -> None:
    stats = pd.DataFrame(
        [{"season": 2025, "week": 19, "season_type": "POST"}] * 100
    )
    assert summarize_season(2025, stats) == "2025: 100 rows, no regular-season weeks"


def test_frame_without_a_week_column_is_tolerated() -> None:
    stats = pd.DataFrame([{"season": 2025, "player_id": "00-0000001"}])
    assert summarize_season(2025, stats) == "2025: 1 rows (no week column)"


def test_frame_without_season_type_treats_every_row_as_regular_season() -> None:
    stats = pd.DataFrame([{"season": 2025, "week": 1}] * 900)
    assert summarize_season(2025, stats) == "2025: 900 rows, weeks 1-1"
