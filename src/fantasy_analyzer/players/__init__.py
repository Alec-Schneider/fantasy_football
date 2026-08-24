"""Player providers, nflverse integration, fantasy scoring, and roster efficiency."""

from fantasy_analyzer.players.crosswalk import (
    CROSSWALK_COLUMNS,
    build_id_crosswalk,
    gsis_to_sleeper_lookup,
    sleeper_to_gsis_lookup,
)
from fantasy_analyzer.players.lineup_efficiency import (
    LINEUP_EFFICIENCY_COLUMNS,
    ROSTER_EFFICIENCY_COLUMNS,
    build_lineup_efficiency_metrics,
    build_roster_efficiency_metrics,
)
from fantasy_analyzer.players.lineup_tendencies import (
    BENCH_ALLOCATION_COLUMNS,
    FLEX_USAGE_COLUMNS,
    POSITIONAL_PREFERENCE_COLUMNS,
    ROSTER_CONSTRUCTION_COLUMNS,
    START_SIT_TENDENCY_COLUMNS,
    build_bench_allocation_metrics,
    build_flex_usage_metrics,
    build_positional_preference_metrics,
    build_roster_construction_metrics,
    build_start_sit_tendency_metrics,
)
from fantasy_analyzer.players.matchup_contribution import (
    MATCHUP_POINTS_TOLERANCE,
    PLAYER_CONTRIBUTION_COLUMNS,
    POSITIONAL_ADVANTAGE_COLUMNS,
    RECONCILE_COLUMNS,
    build_matchup_player_contributions,
    build_positional_matchup_advantage,
    reconcile_matchup_points,
)
from fantasy_analyzer.players.nflverse_cache import (
    DEFAULT_CACHE_DIR as NFLVERSE_DEFAULT_CACHE_DIR,
)
from fantasy_analyzer.players.nflverse_cache import (
    get_player_stats_cached,
    load_player_stats_cache,
    refresh_player_stats_cache,
)
from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.nflverse_provider import (
    RAW_STAT_COLUMNS,
    NflverseWeeklyStatsProvider,
    normalize_player_stats,
)
from fantasy_analyzer.players.performance import (
    BOOM_BUST_THRESHOLD_STDEVS as PLAYER_BOOM_BUST_THRESHOLD_STDEVS,
)
from fantasy_analyzer.players.performance import (
    MIN_GAMES_FOR_BOOM_BUST,
    MIN_GAMES_FOR_DISPERSION,
    PLAYER_PERFORMANCE_COLUMNS,
    build_player_performance_metrics,
)
from fantasy_analyzer.players.player_analytics import (
    PlayerAnalytics,
    build_player_analytics,
)
from fantasy_analyzer.players.player_value import (
    PLAYER_VALUE_COLUMNS,
    POSITION_SCARCITY_COLUMNS,
    build_player_value_metrics,
    build_position_scarcity_metrics,
)
from fantasy_analyzer.players.player_week import (
    PLAYER_WEEK_COLUMNS,
    PlayerWeekFactTable,
    build_player_week_fact_table,
)
from fantasy_analyzer.players.position_strength import (
    BOOM_BUST_THRESHOLD_STDEVS as POSITION_BOOM_BUST_THRESHOLD_STDEVS,
)
from fantasy_analyzer.players.position_strength import (
    MIN_WEEKS_FOR_BOOM_BUST,
    MIN_WEEKS_FOR_DISPERSION,
    POSITION_STRENGTH_COLUMNS,
    build_position_strength_metrics,
)
from fantasy_analyzer.players.projections import (
    PROJECTION_IDENTITY_COLUMNS,
    ProjectionProvider,
    validate_projection_columns,
)
from fantasy_analyzer.players.provider import (
    PLAYER_WEEK_IDENTITY_COLUMNS,
    PlayerStatsProvider,
    validate_player_week_columns,
)
from fantasy_analyzer.players.scoring import (
    SCORING_KEY_TO_STAT_COLUMNS,
    ScoringResult,
    calculate_fantasy_points,
)

__all__ = [
    "PLAYER_WEEK_IDENTITY_COLUMNS",
    "PlayerStatsProvider",
    "validate_player_week_columns",
    "PROJECTION_IDENTITY_COLUMNS",
    "ProjectionProvider",
    "validate_projection_columns",
    "NflverseClient",
    "NflverseWeeklyStatsProvider",
    "RAW_STAT_COLUMNS",
    "normalize_player_stats",
    "NFLVERSE_DEFAULT_CACHE_DIR",
    "load_player_stats_cache",
    "refresh_player_stats_cache",
    "get_player_stats_cached",
    "CROSSWALK_COLUMNS",
    "build_id_crosswalk",
    "gsis_to_sleeper_lookup",
    "sleeper_to_gsis_lookup",
    "SCORING_KEY_TO_STAT_COLUMNS",
    "ScoringResult",
    "calculate_fantasy_points",
    "PLAYER_WEEK_COLUMNS",
    "PlayerWeekFactTable",
    "build_player_week_fact_table",
    "PLAYER_PERFORMANCE_COLUMNS",
    "PLAYER_BOOM_BUST_THRESHOLD_STDEVS",
    "MIN_GAMES_FOR_DISPERSION",
    "MIN_GAMES_FOR_BOOM_BUST",
    "build_player_performance_metrics",
    "POSITION_STRENGTH_COLUMNS",
    "POSITION_BOOM_BUST_THRESHOLD_STDEVS",
    "MIN_WEEKS_FOR_DISPERSION",
    "MIN_WEEKS_FOR_BOOM_BUST",
    "build_position_strength_metrics",
    "PLAYER_VALUE_COLUMNS",
    "POSITION_SCARCITY_COLUMNS",
    "build_player_value_metrics",
    "build_position_scarcity_metrics",
    "LINEUP_EFFICIENCY_COLUMNS",
    "ROSTER_EFFICIENCY_COLUMNS",
    "build_lineup_efficiency_metrics",
    "build_roster_efficiency_metrics",
    "ROSTER_CONSTRUCTION_COLUMNS",
    "BENCH_ALLOCATION_COLUMNS",
    "FLEX_USAGE_COLUMNS",
    "START_SIT_TENDENCY_COLUMNS",
    "POSITIONAL_PREFERENCE_COLUMNS",
    "build_roster_construction_metrics",
    "build_bench_allocation_metrics",
    "build_flex_usage_metrics",
    "build_start_sit_tendency_metrics",
    "build_positional_preference_metrics",
    "PlayerAnalytics",
    "build_player_analytics",
    "PLAYER_CONTRIBUTION_COLUMNS",
    "POSITIONAL_ADVANTAGE_COLUMNS",
    "RECONCILE_COLUMNS",
    "MATCHUP_POINTS_TOLERANCE",
    "build_matchup_player_contributions",
    "build_positional_matchup_advantage",
    "reconcile_matchup_points",
]
