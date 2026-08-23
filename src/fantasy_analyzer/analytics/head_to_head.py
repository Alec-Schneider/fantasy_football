"""Build pairwise manager-vs-manager head-to-head records (FFA-040).

Consumes FFA-033's
:func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`
output and aggregates it into one row per ordered ``(roster_id,
opponent_roster_id)`` pair that has met at least once, from ``roster_id``'s
perspective. This module performs no network access; it operates entirely on
an already-built ``season_matchup_df``.

Row shape: ordered, directional pairs
---------------------------------------

For every unordered meeting between two rosters (e.g. one week where roster A
played roster B), this module emits **two** rows: one from A's perspective
(``roster_id=A, opponent_roster_id=B``) and one from B's perspective
(``roster_id=B, opponent_roster_id=A``) -- mirror images of each other, not a
single combined row per unordered pair.

This is a deliberate shape choice, not an accident of how the aggregation
happens to fall out. A future ``analysis.head_to_head(team_a, team_b)``
lookup (FFA-043) wants "team_a's record against team_b" directly, without the
caller having to first figure out whether team_a was ``roster_1_id`` or
``roster_2_id`` in each historical row and flip signs accordingly. A future
head-to-head matrix (FFA-041) similarly wants to read "row = team, column =
opponent" directly out of a table already indexed that way, rather than
re-deriving both directions from a single unordered row at render time. An
unordered single-row-per-pair shape would push that perspective-flipping
logic into every downstream consumer instead of doing it once, here.

Metric definitions
-------------------

For an ordered pair ``(roster_id, opponent_roster_id)``, all metrics are
computed only from ``season_matchup_df`` rows where this pair actually met
(``{roster_1_id, roster_2_id} == {roster_id, opponent_roster_id}``):

- **meetings** -- count of qualifying rows. Guaranteed >= 1 for any row that
  appears in this module's output; a pair with zero meetings simply has no
  row (there is no zero-meetings row with ``meetings = 0`` -- see "Missing
  values / edge cases" below).
- **wins** / **losses** / **ties** -- from ``roster_id``'s perspective in
  those meetings, read directly off the existing ``winner``/``loser``/
  ``is_tie`` columns (``winner == roster_id`` -> win, ``loser == roster_id``
  -> loss, ``is_tie`` -> tie). A meeting whose outcome is unresolved (see the
  missing-points rule below) contributes to none of the three.
- **total_points** / **total_opponent_points** -- sum of ``roster_id``'s own
  points and ``opponent_roster_id``'s points, respectively, across those
  meetings.
- **avg_points** = ``total_points / meetings``; **avg_opponent_points** =
  ``total_opponent_points / meetings``. Since ``meetings`` is always >= 1 for
  an emitted row, this is never a division by zero.

Bye rows
--------

A bye row (``roster_2_id is None``, see
:mod:`~fantasy_analyzer.matchups.pairing`) has no opponent by definition.
This module excludes bye rows entirely from the pairing scan -- a bye never
counts as a meeting between two rosters, and never creates or contributes to
any ``(roster_id, opponent_roster_id)`` pair. This mirrors how
``outcomes.py``/``reconciliation.py`` already treat a bye as "no opponent"
rather than a meeting against a phantom roster.

Missing points
--------------

A row with a missing (``None``/``NaN``) ``points_1``/``points_2`` -- e.g. an
unloaded week -- still has a real, present ``roster_2_id`` (it is not a bye),
so it **still counts as a meeting** between the two rosters:
``meetings`` is incremented for both perspectives regardless of whether
points are present.

Per :mod:`~fantasy_analyzer.matchups.outcomes`, a missing-points row always
has ``winner``/``loser`` both ``None`` and ``is_tie`` ``False`` (outcome
derivation refuses to guess a winner without both scores) -- so such a
meeting is counted toward ``meetings`` but contributes to none of
``wins``/``losses``/``ties``. Whichever side's points value is present
(if any) is added to that side's points sum as usual; a missing points value
contributes nothing to ``total_points``/``total_opponent_points`` rather than
being treated as ``0`` or raising. This is the same "missing contributes
nothing, still counts toward the game total" rule ``reconciliation.py`` uses
for its own points sums, applied here identically per perspective.

Regular season vs. playoffs
------------------------------

This function combines **all** ``season_matchup_df`` rows -- regular season
and playoff alike -- into a single combined head-to-head record. It makes
**no** ``is_playoff`` distinction and must not be called with a
pre-filtered, phase-only subset if a combined record is what is wanted.
Splitting the head-to-head record by season phase (regular season only,
playoffs only) is explicitly deferred to FFA-044 ("Split Regular Season and
Playoff H2H"), a separate, later ticket -- this mirrors
``reconciliation.py``'s and ``standings.py``'s existing precedent of stating
the regular-season/playoff scope explicitly rather than leaving it implicit.

Owner resolution
-----------------

``owner``/``opponent_owner`` are resolved from ``teams_df["display_name"]``
by ``roster_id``, the same left-join-by-dict pattern
``season_matchups.py`` uses to resolve ``owner_1``/``owner_2``. A
``roster_id``/``opponent_roster_id`` absent from ``teams_df`` (or an empty
``teams_df``) resolves to ``None`` rather than raising, consistent with
``build_team_mapping``'s own missing-owner handling.

Missing values / edge cases
----------------------------

- **Empty ``season_matchup_df``**: returns an empty DataFrame with
  :data:`HEAD_TO_HEAD_COLUMNS`.
- **A pair with zero meetings**: never appears in the output at all -- there
  is no zero-``meetings`` row, since ``avg_points``/``avg_opponent_points``
  would be undefined for it.
- **Bye rows**: excluded entirely, as documented above.
"""

from __future__ import annotations

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_head_to_head_records`.
HEAD_TO_HEAD_COLUMNS = [
    "roster_id",
    "opponent_roster_id",
    "owner",
    "opponent_owner",
    "meetings",
    "wins",
    "losses",
    "ties",
    "total_points",
    "total_opponent_points",
    "avg_points",
    "avg_opponent_points",
]


def _pair_bucket(totals: dict, roster_id: int, opponent_roster_id: int) -> dict:
    """Return (creating if absent) the running totals dict for an ordered pair."""
    key = (roster_id, opponent_roster_id)
    if key not in totals:
        totals[key] = {
            "meetings": 0,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "total_points": 0.0,
            "total_opponent_points": 0.0,
        }
    return totals[key]


def build_head_to_head_records(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row per ordered ``(roster_id, opponent_roster_id)`` pair.

    Aggregates every non-bye row of ``season_matchup_df`` -- regular season
    and playoff alike -- into directional head-to-head totals from each
    roster's own perspective. See the module docstring for the exact metric
    definitions, the directional-shape justification, the bye/missing-points
    rules, and why playoff rows must not be filtered out.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used to resolve
            ``owner``/``opponent_owner`` labels.

    Returns:
        A DataFrame with columns :data:`HEAD_TO_HEAD_COLUMNS`, one row per
        ordered pair of rosters that met at least once, sorted by ascending
        ``roster_id`` then ascending ``opponent_roster_id``. Returns an
        empty DataFrame with the expected columns if ``season_matchup_df``
        is empty. A roster_id absent from ``teams_df`` (or an empty
        ``teams_df``) resolves to ``owner``/``opponent_owner = None`` rather
        than raising.
    """
    if season_matchup_df.empty:
        return pd.DataFrame(columns=HEAD_TO_HEAD_COLUMNS)

    owner_by_roster = (
        teams_df.set_index("roster_id")["display_name"].to_dict()
        if not teams_df.empty
        else {}
    )

    totals: dict = {}

    for row in season_matchup_df.itertuples(index=False):
        # Bye rows have no opponent and never count as a meeting -- see the
        # module docstring's "Bye rows" section.
        if pd.isna(row.roster_2_id):
            continue

        roster_1_id = int(row.roster_1_id)
        roster_2_id = int(row.roster_2_id)
        winner = int(row.winner) if pd.notna(row.winner) else None
        loser = int(row.loser) if pd.notna(row.loser) else None
        is_tie = bool(row.is_tie) if pd.notna(row.is_tie) else False
        points_1 = row.points_1
        points_2 = row.points_2

        # Two perspectives per row: (roster_1 vs roster_2) and its mirror
        # (roster_2 vs roster_1). See the module docstring's "Row shape"
        # section for why both directions are emitted.
        perspectives = (
            (roster_1_id, roster_2_id, points_1, points_2),
            (roster_2_id, roster_1_id, points_2, points_1),
        )
        for own_id, opp_id, own_points, opp_points in perspectives:
            bucket = _pair_bucket(totals, own_id, opp_id)
            bucket["meetings"] += 1

            if winner is not None and winner == own_id:
                bucket["wins"] += 1
            elif loser is not None and loser == own_id:
                bucket["losses"] += 1
            elif is_tie:
                bucket["ties"] += 1
            # An unresolved outcome (missing points, per outcomes.py) leaves
            # winner/loser both None and is_tie False -- no win/loss/tie
            # credit, but the meeting itself was already counted above. See
            # the module docstring's "Missing points" section.

            if pd.notna(own_points):
                bucket["total_points"] += own_points
            if pd.notna(opp_points):
                bucket["total_opponent_points"] += opp_points

    # A non-empty season_matchup_df made entirely of bye rows produces zero
    # pairs -- return an empty, correctly-shaped frame rather than letting
    # pd.DataFrame([]) build a columnless frame that the assignments below
    # can't index into.
    if not totals:
        return pd.DataFrame(columns=HEAD_TO_HEAD_COLUMNS)

    # ``owner``/``opponent_owner`` are built and assigned as their own
    # explicit ``dtype=object`` Series below rather than as plain dict
    # values inside ``rows``. Pandas' newer default string-dtype inference
    # otherwise upcasts a column that mixes real owner names with ``None``
    # (e.g. one row's ``owner`` is a name while another row's ``owner`` is
    # unmapped) into a string dtype that silently turns ``None`` into
    # ``NaN`` -- breaking the documented "unmapped owner -> ``None``, not
    # raising" contract for callers doing ``is None`` checks (see
    # ``season_matchups.py``'s identical contract).
    rows = [
        {
            "roster_id": roster_id,
            "opponent_roster_id": opponent_roster_id,
            "meetings": values["meetings"],
            "wins": values["wins"],
            "losses": values["losses"],
            "ties": values["ties"],
            "total_points": values["total_points"],
            "total_opponent_points": values["total_opponent_points"],
            "avg_points": values["total_points"] / values["meetings"],
            "avg_opponent_points": values["total_opponent_points"] / values["meetings"],
        }
        for (roster_id, opponent_roster_id), values in totals.items()
    ]

    result = pd.DataFrame(rows)
    result = result.sort_values(by=["roster_id", "opponent_roster_id"]).reset_index(
        drop=True
    )
    result["owner"] = pd.Series(
        [owner_by_roster.get(roster_id) for roster_id in result["roster_id"]],
        dtype=object,
    )
    result["opponent_owner"] = pd.Series(
        [
            owner_by_roster.get(opponent_roster_id)
            for opponent_roster_id in result["opponent_roster_id"]
        ],
        dtype=object,
    )
    return result[HEAD_TO_HEAD_COLUMNS]
