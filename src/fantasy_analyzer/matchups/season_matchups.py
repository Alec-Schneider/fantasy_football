"""Build the canonical season matchup DataFrame from paired outcomes.

Assembles :mod:`~fantasy_analyzer.matchups.outcomes`' per-matchup
``MatchupOutcome`` records into the single season-wide table AGENTS.md's
"Canonical Matchup Dataset" describes as the common input downstream
matchup analytics (Epic 5/6) should consume, rather than re-deriving
outcomes or re-joining owners from raw Sleeper data by hand.

This is the first point in the matchup pipeline (loader -> pairing ->
outcomes -> here) where roster IDs are resolved to owner labels, via a left
join against :func:`~fantasy_analyzer.league.teams.build_team_mapping`'s
``teams_df`` on the immutable ``roster_id``. It performs no network access.

Column semantics
-----------------

Per AGENTS.md's Data Modeling Guidelines ("prefer immutable IDs over names
whenever possible"), and because ``roster_1_id``/``roster_2_id`` are already
present as immutable join keys, this module treats ``owner_1``/``owner_2``
as the schema's human-readable exception: labels resolved from
``teams_df["display_name"]``, for display only. ``winner``/``loser``, by
contrast, carry ``MatchupOutcome.winner_roster_id``/``loser_roster_id``
through as-is -- they are roster IDs, not owner labels, so downstream
analytics (e.g. FFA-040 head-to-head records) can group or join on them
directly without a reverse owner lookup. A roster with no mapping in
``teams_df`` (unmapped or missing owner) gets ``owner_1``/``owner_2 =
None``, consistent with ``build_team_mapping``'s own missing-owner
handling.

``is_tie`` and ``point_differential`` are carried through from
``MatchupOutcome`` in addition to the columns AGENTS.md's schema lists.
Dropping them would make a tie (``winner``/``loser`` both ``None``,
``points_1 == points_2``) indistinguishable from an incomplete matchup
(``winner``/``loser`` both ``None``, points missing) -- a distinction
FFA-040's future "ties" metric needs. AGENTS.md notes the exact schema "may
evolve"; both fields already exist on the ``MatchupOutcome`` input, so this
retains information rather than adding a new metric.

Regular season vs. playoffs
------------------------------

``is_playoff`` is carried through from ``MatchupOutcome`` unchanged; this
module makes no phase-specific distinction of its own. Callers filter on
``is_playoff`` for phase-specific analysis, per FFA-022's boundaries.
"""

from __future__ import annotations

import pandas as pd

from fantasy_analyzer.matchups.outcomes import MatchupOutcome

#: Column order for the DataFrame returned by :func:`build_season_matchup_df`.
SEASON_MATCHUP_COLUMNS = [
    "season",
    "week",
    "is_playoff",
    "matchup_id",
    "roster_1_id",
    "roster_2_id",
    "owner_1",
    "owner_2",
    "points_1",
    "points_2",
    "winner",
    "loser",
    "is_tie",
    "margin",
    "point_differential",
]


def build_season_matchup_df(
    outcomes: list[MatchupOutcome], teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build the canonical season matchup DataFrame from paired outcomes.

    Args:
        outcomes: Per-matchup outcomes, as produced by
            :func:`~fantasy_analyzer.matchups.outcomes.derive_season_outcomes`.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame (see
            :func:`~fantasy_analyzer.league.teams.build_team_mapping`) with
            at least ``["roster_id", "display_name"]``, used to resolve the
            ``owner_1``/``owner_2`` labels.

    Returns:
        A DataFrame with columns ``["season", "week", "is_playoff",
        "matchup_id", "roster_1_id", "roster_2_id", "owner_1", "owner_2",
        "points_1", "points_2", "winner", "loser", "is_tie", "margin",
        "point_differential"]``, one row per input outcome, in the same
        order as ``outcomes``. See the module docstring for the exact
        meaning of ``owner_1``/``owner_2`` versus ``winner``/``loser``, and
        why ``is_tie``/``point_differential`` are retained.

        Returns an empty DataFrame with the expected columns if
        ``outcomes`` is empty. A roster_id absent from ``teams_df`` (or an
        empty ``teams_df``) resolves to ``owner_1``/``owner_2 = None``
        rather than raising.
    """
    if not outcomes:
        return pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)

    owner_by_roster = (
        teams_df.set_index("roster_id")["display_name"].to_dict()
        if not teams_df.empty
        else {}
    )

    rows = [
        {
            "season": outcome.season,
            "week": outcome.week,
            "is_playoff": outcome.is_playoff,
            "matchup_id": outcome.matchup_id,
            "roster_1_id": outcome.roster_1_id,
            "roster_2_id": outcome.roster_2_id,
            "owner_1": owner_by_roster.get(outcome.roster_1_id),
            "owner_2": (
                owner_by_roster.get(outcome.roster_2_id)
                if outcome.roster_2_id is not None
                else None
            ),
            "points_1": outcome.points_1,
            "points_2": outcome.points_2,
            "winner": outcome.winner_roster_id,
            "loser": outcome.loser_roster_id,
            "is_tie": outcome.is_tie,
            "margin": outcome.margin,
            "point_differential": outcome.point_differential,
        }
        for outcome in outcomes
    ]

    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)
