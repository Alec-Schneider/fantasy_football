"""Standings, head-to-head, all-play, luck, consistency, and power rankings."""

from fantasy_analyzer.analytics.all_play import (
    ALL_PLAY_STANDINGS_COLUMNS,
    build_all_play_standings,
)
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
from fantasy_analyzer.analytics.matchup_history import (
    HeadToHeadHistory,
    MatchupHistory,
    build_matchup_history,
)
from fantasy_analyzer.analytics.rivalries import (
    RIVALRY_COLUMNS,
    RivalryGame,
    build_rivalry_records,
)
from fantasy_analyzer.analytics.schedule_luck import (
    SCHEDULE_LUCK_COLUMNS,
    build_schedule_luck,
)
from fantasy_analyzer.analytics.standings import build_scoring_summary, build_standings
from fantasy_analyzer.analytics.summary import (
    LeagueSummary,
    LeagueSummaryView,
    build_league_summary,
)
from fantasy_analyzer.analytics.weekly_scores import (
    WEEKLY_SCORING_RANK_COLUMNS,
    build_weekly_scoring_ranks,
)

__all__ = [
    "build_all_play_standings",
    "build_league_summary",
    "build_scoring_summary",
    "build_standings",
    "build_head_to_head_records",
    "build_head_to_head_matrix",
    "build_matchup_history",
    "build_rivalry_records",
    "build_schedule_luck",
    "build_weekly_scoring_ranks",
    "format_head_to_head_matrix",
    "ALL_PLAY_STANDINGS_COLUMNS",
    "HEAD_TO_HEAD_COLUMNS",
    "HEAD_TO_HEAD_MATRIX_DIAGONAL",
    "HEAD_TO_HEAD_MATRIX_NO_MEETING",
    "HeadToHeadCell",
    "HeadToHeadHistory",
    "LeagueSummary",
    "LeagueSummaryView",
    "MatchupHistory",
    "RIVALRY_COLUMNS",
    "RivalryGame",
    "SCHEDULE_LUCK_COLUMNS",
    "WEEKLY_SCORING_RANK_COLUMNS",
]
