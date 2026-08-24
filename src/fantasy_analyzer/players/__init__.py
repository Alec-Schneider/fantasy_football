"""Player providers, nflverse integration, fantasy scoring, and roster efficiency."""

from fantasy_analyzer.players.crosswalk import (
    CROSSWALK_COLUMNS,
    build_id_crosswalk,
    gsis_to_sleeper_lookup,
    sleeper_to_gsis_lookup,
)
from fantasy_analyzer.players.nflverse_cache import (
    DEFAULT_CACHE_PATH as NFLVERSE_DEFAULT_CACHE_PATH,
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
    "NflverseClient",
    "NflverseWeeklyStatsProvider",
    "RAW_STAT_COLUMNS",
    "normalize_player_stats",
    "NFLVERSE_DEFAULT_CACHE_PATH",
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
]
