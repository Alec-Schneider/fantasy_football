"""Player providers, nflverse integration, fantasy scoring, and roster efficiency."""

from fantasy_analyzer.players.crosswalk import (
    CROSSWALK_COLUMNS,
    build_id_crosswalk,
    build_id_crosswalk_from_player_ids,
    gsis_to_sleeper_lookup,
    sleeper_to_gsis_lookup,
)
from fantasy_analyzer.players.draft_board import (
    DEFAULT_ADP_SD,
    DEFAULT_DRAFT_BOARD_WEIGHTS,
    DEFAULT_DRAFT_NUM_TEAMS,
    DEFAULT_DRAFT_ROSTER_POSITIONS,
    DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS,
    DEFAULT_TIER_GAP_THRESHOLD,
    DRAFT_BOARD_COLUMNS,
    DraftBoardWeights,
    build_draft_board,
    build_pick_availability_table,
    pick_availability_probability,
)
from fantasy_analyzer.players.draft_grade import (
    SCORED_DRAFT_PICK_COLUMNS,
    score_draft_picks,
)
from fantasy_analyzer.players.draft_market import (
    DRAFT_MARKET_COLUMNS,
    DRAFT_MARKET_POOL_COLUMNS,
    FANTASYPROS_ECR_SOURCE,
    FANTASYPROS_OVERALL_PAGE_TYPE,
    FANTASYPROS_POSITION_PAGE_TYPES,
    FFC_ADP_SOURCE,
    TEAM_ABBREVIATION_ALIASES,
    build_draft_market,
    build_draft_market_player_pool,
    build_fantasypros_draft_market,
    build_ffc_draft_market,
    validate_draft_market_columns,
)
from fantasy_analyzer.players.draft_market_cache import (
    DEFAULT_CACHE_DIR as DRAFT_MARKET_DEFAULT_CACHE_DIR,
)
from fantasy_analyzer.players.draft_market_cache import (
    get_draft_market_cached,
    get_draft_market_player_pool_cached,
    get_ffc_adp_cached,
    get_fpecr_cached,
    load_ffc_adp_cache,
    load_fpecr_cache,
    refresh_ffc_adp_cache,
    refresh_fpecr_cache,
)
from fantasy_analyzer.players.draft_market_client import (
    FantasyProsEcrClient,
    FfcAdpClient,
)
from fantasy_analyzer.players.draft_points_value import (
    DEFAULT_POINTS_CURVE_EXCLUDED_POSITIONS,
    POINTS_VALUE_PICK_COLUMNS,
    PointsValueCurve,
    fit_points_value_curve,
    score_points_value,
)
from fantasy_analyzer.players.draft_report import (
    DEFAULT_DRAFT_GRADE_WEIGHTS,
    DRAFT_TALKING_POINT_COLUMNS,
    TEAM_DRAFT_GRADE_COLUMNS,
    DraftGradeWeights,
    build_draft_talking_points,
    build_team_draft_grades,
)
from fantasy_analyzer.players.id_crosswalk_cache import (
    DEFAULT_CACHE_DIR as ID_CROSSWALK_DEFAULT_CACHE_DIR,
)
from fantasy_analyzer.players.id_crosswalk_cache import (
    get_player_ids_cached,
    load_player_ids_cache,
    refresh_player_ids_cache,
)
from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient
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
from fantasy_analyzer.players.nflverse_defense import (
    TEAM_CODE_ALIASES,
    TEAM_DEFENSE_RAW_STAT_COLUMNS,
    NflverseTeamDefenseProvider,
    build_team_defense_stats,
)
from fantasy_analyzer.players.nflverse_provider import (
    OPPORTUNITY_COLUMNS,
    RAW_STAT_COLUMNS,
    NflverseWeeklyStatsProvider,
    normalize_player_stats,
)
from fantasy_analyzer.players.nflverse_schedule_cache import (
    DEFAULT_CACHE_DIR as NFLVERSE_SCHEDULE_DEFAULT_CACHE_DIR,
)
from fantasy_analyzer.players.nflverse_schedule_cache import (
    get_games_cached,
    load_games_cache,
    refresh_games_cache,
)
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient
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
from fantasy_analyzer.players.player_rankings import (
    DEFAULT_RANKING_WEIGHTS,
    DEFAULT_RATE_SHRINKAGE_GAMES,
    LEAGUE_PLAYER_RANKING_COLUMNS,
    RankingWeights,
    build_league_player_rankings,
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
    build_league_wide_player_week_fact_table,
    build_player_week_fact_table,
)
from fantasy_analyzer.players.points_allowed import (
    POINTS_ALLOWED_COLUMNS,
    NflverseScheduleProvider,
    normalize_points_allowed,
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
from fantasy_analyzer.players.ros_backtest import (
    DEFAULT_BASELINES,
    ROS_EVALUATION_COLUMNS,
    ROS_METRIC_COLUMNS,
    RosEvaluationSet,
    build_ros_evaluation_set,
    build_scored_player_weeks,
    filter_to_waiver_population,
    run_ros_backtest,
    score_baselines,
    score_ros_predictions,
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
    "ROS_EVALUATION_COLUMNS",
    "ROS_METRIC_COLUMNS",
    "DEFAULT_BASELINES",
    "RosEvaluationSet",
    "build_scored_player_weeks",
    "build_ros_evaluation_set",
    "score_ros_predictions",
    "score_baselines",
    "filter_to_waiver_population",
    "run_ros_backtest",
    "NflverseClient",
    "NflverseWeeklyStatsProvider",
    "RAW_STAT_COLUMNS",
    "OPPORTUNITY_COLUMNS",
    "normalize_player_stats",
    "NFLVERSE_DEFAULT_CACHE_DIR",
    "load_player_stats_cache",
    "refresh_player_stats_cache",
    "get_player_stats_cached",
    "CROSSWALK_COLUMNS",
    "build_id_crosswalk",
    "build_id_crosswalk_from_player_ids",
    "gsis_to_sleeper_lookup",
    "sleeper_to_gsis_lookup",
    "DRAFT_BOARD_COLUMNS",
    "DraftBoardWeights",
    "DEFAULT_DRAFT_BOARD_WEIGHTS",
    "DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS",
    "DEFAULT_DRAFT_ROSTER_POSITIONS",
    "DEFAULT_DRAFT_NUM_TEAMS",
    "DEFAULT_TIER_GAP_THRESHOLD",
    "DEFAULT_ADP_SD",
    "build_draft_board",
    "pick_availability_probability",
    "build_pick_availability_table",
    "SCORED_DRAFT_PICK_COLUMNS",
    "score_draft_picks",
    "DRAFT_MARKET_COLUMNS",
    "DRAFT_MARKET_POOL_COLUMNS",
    "FFC_ADP_SOURCE",
    "FANTASYPROS_ECR_SOURCE",
    "FANTASYPROS_OVERALL_PAGE_TYPE",
    "FANTASYPROS_POSITION_PAGE_TYPES",
    "TEAM_ABBREVIATION_ALIASES",
    "build_ffc_draft_market",
    "build_fantasypros_draft_market",
    "build_draft_market",
    "build_draft_market_player_pool",
    "validate_draft_market_columns",
    "FfcAdpClient",
    "FantasyProsEcrClient",
    "DEFAULT_POINTS_CURVE_EXCLUDED_POSITIONS",
    "POINTS_VALUE_PICK_COLUMNS",
    "PointsValueCurve",
    "fit_points_value_curve",
    "score_points_value",
    "DRAFT_MARKET_DEFAULT_CACHE_DIR",
    "load_ffc_adp_cache",
    "refresh_ffc_adp_cache",
    "get_ffc_adp_cached",
    "load_fpecr_cache",
    "refresh_fpecr_cache",
    "get_fpecr_cached",
    "get_draft_market_cached",
    "get_draft_market_player_pool_cached",
    "TEAM_DRAFT_GRADE_COLUMNS",
    "DRAFT_TALKING_POINT_COLUMNS",
    "DraftGradeWeights",
    "DEFAULT_DRAFT_GRADE_WEIGHTS",
    "build_team_draft_grades",
    "build_draft_talking_points",
    "PlayerIdCrosswalkClient",
    "ID_CROSSWALK_DEFAULT_CACHE_DIR",
    "load_player_ids_cache",
    "refresh_player_ids_cache",
    "get_player_ids_cached",
    "SCORING_KEY_TO_STAT_COLUMNS",
    "ScoringResult",
    "calculate_fantasy_points",
    "PLAYER_WEEK_COLUMNS",
    "PlayerWeekFactTable",
    "build_player_week_fact_table",
    "build_league_wide_player_week_fact_table",
    "NflverseScheduleClient",
    "NFLVERSE_SCHEDULE_DEFAULT_CACHE_DIR",
    "load_games_cache",
    "refresh_games_cache",
    "get_games_cached",
    "NflverseScheduleProvider",
    "POINTS_ALLOWED_COLUMNS",
    "normalize_points_allowed",
    "NflverseTeamDefenseProvider",
    "TEAM_CODE_ALIASES",
    "TEAM_DEFENSE_RAW_STAT_COLUMNS",
    "build_team_defense_stats",
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
    "LEAGUE_PLAYER_RANKING_COLUMNS",
    "DEFAULT_RANKING_WEIGHTS",
    "DEFAULT_RATE_SHRINKAGE_GAMES",
    "RankingWeights",
    "build_league_player_rankings",
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
