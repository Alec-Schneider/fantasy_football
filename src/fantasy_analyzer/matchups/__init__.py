"""Weekly matchup retrieval and matchup normalization."""

from fantasy_analyzer.matchups.loader import (
    WeekMatchups,
    collect_season_matchups,
    load_season_matchups,
)

__all__ = [
    "collect_season_matchups",
    "load_season_matchups",
    "WeekMatchups",
]
