"""Weekly matchup retrieval and matchup normalization."""

from fantasy_analyzer.matchups.loader import (
    WeekMatchups,
    collect_season_matchups,
    load_season_matchups,
)
from fantasy_analyzer.matchups.outcomes import (
    MatchupOutcome,
    derive_matchup_outcome,
    derive_season_outcomes,
)
from fantasy_analyzer.matchups.pairing import (
    MatchupPairing,
    pair_season_matchups,
    pair_week_matchups,
)

__all__ = [
    "collect_season_matchups",
    "load_season_matchups",
    "WeekMatchups",
    "MatchupPairing",
    "pair_season_matchups",
    "pair_week_matchups",
    "MatchupOutcome",
    "derive_matchup_outcome",
    "derive_season_outcomes",
]
