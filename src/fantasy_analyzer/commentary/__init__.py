"""Assemble already-computed analytics into LLM-prompt-ready commentary context.

See :mod:`fantasy_analyzer.commentary.context` for the two pure, network-free
context builders (FFA-090/FFA-091) and :mod:`fantasy_analyzer.commentary.prompts`
for the pure prompt-text templates built on top of them (FFA-092). CLI wiring
(FFA-093) builds on top of both in :mod:`fantasy_analyzer.cli`.
"""

from fantasy_analyzer.commentary.context import (
    DEFAULT_TOP_N_CONTRIBUTORS,
    STREAK_MIN_LENGTH,
    AllPlayWeekRecord,
    BenchScorer,
    HeadToHead,
    LeagueWeekContext,
    MatchupContext,
    MatchupExtreme,
    PlayerContribution,
    PowerRankingDelta,
    ScheduleLuckOutlier,
    ScheduleLuckOutliers,
    ScoringLeaderboardEntry,
    StandingsMovement,
    Streak,
    TeamWeekSummary,
    WeeklyScoringLeaderboard,
    build_league_week_context,
    build_matchup_context,
)
from fantasy_analyzer.commentary.prompts import (
    DEFAULT_TONE,
    TONE_DESCRIPTIONS,
    combined_matchup_prompt,
    league_week_recap_prompt,
    weekly_matchup_prompt,
)

__all__ = [
    "DEFAULT_TOP_N_CONTRIBUTORS",
    "STREAK_MIN_LENGTH",
    "AllPlayWeekRecord",
    "BenchScorer",
    "HeadToHead",
    "LeagueWeekContext",
    "MatchupContext",
    "MatchupExtreme",
    "PlayerContribution",
    "PowerRankingDelta",
    "ScheduleLuckOutlier",
    "ScheduleLuckOutliers",
    "ScoringLeaderboardEntry",
    "StandingsMovement",
    "Streak",
    "TeamWeekSummary",
    "WeeklyScoringLeaderboard",
    "build_league_week_context",
    "build_matchup_context",
    "DEFAULT_TONE",
    "TONE_DESCRIPTIONS",
    "combined_matchup_prompt",
    "league_week_recap_prompt",
    "weekly_matchup_prompt",
]
