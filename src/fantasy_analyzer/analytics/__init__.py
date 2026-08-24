"""Standings, head-to-head, all-play, luck, consistency, and power rankings."""

from fantasy_analyzer.analytics.all_play import (
    ALL_PLAY_STANDINGS_COLUMNS,
    build_all_play_standings,
)
from fantasy_analyzer.analytics.consistency import (
    BOOM_BUST_THRESHOLD_STDEVS,
    CONSISTENCY_METRICS_COLUMNS,
    build_consistency_metrics,
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
from fantasy_analyzer.analytics.league_analytics import (
    LeagueAnalytics,
    build_league_analytics,
)
from fantasy_analyzer.analytics.matchup_history import (
    HeadToHeadHistory,
    MatchupHistory,
    build_matchup_history,
)
from fantasy_analyzer.analytics.power_rankings import (
    ALL_PLAY_WIN_PCT_WEIGHT,
    MEAN_POINTS_WEIGHT,
    POWER_RANKING_COLUMNS,
    WIN_PCT_WEIGHT,
    build_power_rankings,
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
from fantasy_analyzer.analytics.strength_of_schedule import (
    STRENGTH_OF_SCHEDULE_COLUMNS,
    build_strength_of_schedule,
)
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
    "build_consistency_metrics",
    "build_league_analytics",
    "build_league_summary",
    "build_power_rankings",
    "build_scoring_summary",
    "build_standings",
    "build_head_to_head_records",
    "build_head_to_head_matrix",
    "build_matchup_history",
    "build_rivalry_records",
    "build_schedule_luck",
    "build_strength_of_schedule",
    "build_weekly_scoring_ranks",
    "format_head_to_head_matrix",
    "ALL_PLAY_STANDINGS_COLUMNS",
    "ALL_PLAY_WIN_PCT_WEIGHT",
    "BOOM_BUST_THRESHOLD_STDEVS",
    "CONSISTENCY_METRICS_COLUMNS",
    "HEAD_TO_HEAD_COLUMNS",
    "HEAD_TO_HEAD_MATRIX_DIAGONAL",
    "HEAD_TO_HEAD_MATRIX_NO_MEETING",
    "HeadToHeadCell",
    "HeadToHeadHistory",
    "LeagueAnalytics",
    "LeagueSummary",
    "LeagueSummaryView",
    "MatchupHistory",
    "MEAN_POINTS_WEIGHT",
    "POWER_RANKING_COLUMNS",
    "RIVALRY_COLUMNS",
    "RivalryGame",
    "SCHEDULE_LUCK_COLUMNS",
    "STRENGTH_OF_SCHEDULE_COLUMNS",
    "WEEKLY_SCORING_RANK_COLUMNS",
    "WIN_PCT_WEIGHT",
]
