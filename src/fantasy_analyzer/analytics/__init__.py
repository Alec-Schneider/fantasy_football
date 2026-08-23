"""Standings, head-to-head, all-play, luck, consistency, and power rankings."""

from fantasy_analyzer.analytics.head_to_head import (
    HEAD_TO_HEAD_COLUMNS,
    build_head_to_head_records,
)
from fantasy_analyzer.analytics.head_to_head_matrix import (
    HEAD_TO_HEAD_MATRIX_DIAGONAL,
    HEAD_TO_HEAD_MATRIX_NO_MEETING,
    HeadToHeadCell,
    build_head_to_head_matrix,
    format_head_to_head_matrix,
)
from fantasy_analyzer.analytics.standings import build_scoring_summary, build_standings
from fantasy_analyzer.analytics.summary import (
    LeagueSummary,
    LeagueSummaryView,
    build_league_summary,
)

__all__ = [
    "build_league_summary",
    "build_scoring_summary",
    "build_standings",
    "build_head_to_head_records",
    "build_head_to_head_matrix",
    "format_head_to_head_matrix",
    "HEAD_TO_HEAD_COLUMNS",
    "HEAD_TO_HEAD_MATRIX_DIAGONAL",
    "HEAD_TO_HEAD_MATRIX_NO_MEETING",
    "HeadToHeadCell",
    "LeagueSummary",
    "LeagueSummaryView",
]
