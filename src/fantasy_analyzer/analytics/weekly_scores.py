"""Build per-roster weekly scores and weekly scoring ranks (FFA-050).

Consumes FFA-033's
:func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`
output and reshapes it into one row per roster per week, ranked by the points
that roster scored that week. This module performs no network access; it
operates entirely on an already-built ``season_matchup_df``.

Metric definition
------------------

**Weekly scoring rank** -- within a single ``(season, week)``, the position of
a roster's own score among the scores of every roster that played that week,
ordered highest-first. ``weekly_rank = 1`` is the week's top score.

This is a *scoring* metric, not a *matchup* metric: it answers "who scored the
most this week", entirely independently of who each roster happened to be
scheduled against or whether that head-to-head was won. A roster can be rank 2
in a week and still lose its matchup (if it drew the week's rank-1 opponent),
or be rank 9 and win. Win/loss outcomes live in
:mod:`~fantasy_analyzer.analytics.head_to_head`; this module deliberately
ignores ``winner``/``loser``/``is_tie``/``margin`` and reads only ``points``.

Row shape: long, one row per roster-week
-----------------------------------------

``season_matchup_df`` is **wide** -- one row per matchup, carrying two
rosters (``roster_1_id``/``points_1`` and ``roster_2_id``/``points_2``). This
module emits the **long** equivalent: one row per ``(season, week,
roster_id)`` observation, with a single ``points`` column.

The reshape is per-observation, not per-row: each source row contributes
``(roster_1_id, points_1)`` and -- only when ``roster_2_id`` is present --
``(roster_2_id, points_2)``. A normal matchup row therefore contributes two
roster-week observations, and a bye row contributes exactly one.

The long shape is the point of this ticket, not incidental. Ranking within a
week requires all of the week's scores in one comparable column, and FFA-051's
all-play records ("how would this roster have done against every other roster
that week") need exactly this per-week set of ranked scores.

Bye rows are included -- and why that differs from FFA-040/FFA-042
--------------------------------------------------------------------

A bye row (``roster_2_id is None``, see
:mod:`~fantasy_analyzer.matchups.pairing`) is a roster that really played and
really scored, but had no opponent that week. Per
:mod:`~fantasy_analyzer.matchups.outcomes`, such a row has a present
``points_1`` while every *outcome* field (``winner``/``loser``/``margin``/
``point_differential``) is ``None`` -- because there was no opponent to derive
an outcome against, not because the score is unknown.

This module therefore **includes** the bye roster's score in that week's
ranking. ``build_head_to_head_records`` (FFA-040) and
``build_rivalry_records`` (FFA-042) exclude bye rows entirely, and this is the
one place FFA-050 must diverge from that precedent: those are matchup metrics,
whose unit of observation is a meeting between two rosters, and a bye is not a
meeting. A weekly scoring rank's unit of observation is a roster's score, and
a bye week has one. Dropping it would silently understate the week's field
size and shift every lower-ranked roster's rank up by one.

(``points_2`` is not read at all on a bye row: ``roster_2_id`` is ``None``, so
there is no roster to attribute a second score to.)

Missing points are excluded, never zero
----------------------------------------

An observation whose ``points`` is missing (``None``/``NaN`` -- e.g. an
unloaded week, or one side of a partially-loaded matchup) has **no defined
score**, so it is dropped from the output entirely: it gets no row, and does
not appear with a null ``weekly_rank``.

Two alternatives were rejected. Treating a missing score as ``0.0`` would
invent data and hand that roster an artificial last place, exactly the
"missing is not zero" rule ``reconciliation.py`` and ``rivalries.py`` already
follow. Emitting the row with ``weekly_rank = None`` would mean a rank column
that callers must null-check on every use, to represent a roster whose score
is unknown -- a row carrying no information beyond "this roster-week exists",
which the source ``season_matchup_df`` already says. Exclusion keeps the
invariant that **every row in this frame has a real score and a real rank**.

The exclusion is per *observation*, not per source row: in a matchup where
only one side's points are missing, the side with a real score is still
included and still ranked.

Consequently the number of rows in a week is the number of rosters with a
defined score that week, which may be fewer than the league size. Ranks are
dense over the rosters that are present -- a week where two of twelve rosters
have missing scores ranks the remaining ten 1..10.

Ranking rule
------------

Within each ``(season, week)`` group, rosters are ordered by descending
``points`` and assigned **standard competition ("1224") ranking**, the same
convention ``build_standings``'s ``rank`` and ``build_scoring_summary``'s
``scoring_rank`` already use: rosters with identical ``points`` share a rank,
and the next distinct rank skips the number of tied rosters. Two rosters tied
for the week's high score both get ``weekly_rank = 1`` and the next roster
gets ``3``, not ``2``.

Ranks are computed **independently per week**; there is no cross-week
comparison, so the same score can rank 1st in a low-scoring week and 6th in a
high-scoring one. ``(season, week)`` -- not ``week`` alone -- is the grouping
key, so a multi-season frame ranks each season's week 1 separately.

Regular season vs. playoffs
------------------------------

``weekly_rank`` is computed per week **regardless of season phase**. Playoff
rows are neither excluded nor ranked separately: a playoff week's rank is
still just "who scored the most among the rosters that played that week".
``is_playoff`` is carried through from the source row purely as an
informational column, so a caller wanting a phase-specific view (e.g.
regular-season scoring ranks only) can filter this frame afterward.

Note that filtering *after* the fact preserves each week's original rank
(computed against the full week's field), which is the intended behavior;
a caller who instead wants ranks recomputed within a phase-restricted field
should filter ``season_matchup_df`` before calling. As in
``head_to_head.py``, this ticket makes no phase distinction of its own.

Owner resolution
-----------------

``owner`` is resolved from ``teams_df["display_name"]`` by ``roster_id``,
the same lookup-by-dict pattern ``season_matchups.py`` and
``head_to_head.py`` use. A ``roster_id`` absent from ``teams_df`` (or an
empty ``teams_df``) resolves to ``None`` rather than raising, consistent with
``build_team_mapping``'s own missing-owner handling.

Missing values / edge cases
----------------------------

- **Empty ``season_matchup_df``**: returns an empty DataFrame with
  :data:`WEEKLY_SCORING_RANK_COLUMNS`.
- **A week in which every observation has missing points**: contributes no
  rows. If that is true of every week, the result is an empty (but
  correctly-shaped) frame rather than an error.
- **A single-roster week** (a one-team league, or a week where only one
  roster has a defined score): that roster trivially gets
  ``weekly_rank = 1``. No special-casing is needed or applied.
- **Duplicate roster-weeks**: a roster cannot play two matchups in the same
  week, so a well-formed ``season_matchup_df`` yields at most one observation
  per ``(season, week, roster_id)``. If an input violates that,
  :func:`build_weekly_scoring_ranks` raises ``ValueError`` rather than
  emitting two rows for one roster-week. This mirrors ``pairing.py``'s
  handling of a ``matchup_id`` shared by more than two rosters: the input is
  a data-integrity anomaly with no correct interpretation, and silently
  ranking a roster twice would corrupt both its own rank and the ranks of
  every roster below it (as well as FFA-051's all-play denominators, which
  are built on this frame).
- **Field size**: the number of rosters ranked in a week is deliberately not
  a column here; it is a one-line ``groupby`` for any caller that needs it,
  and FFA-051 owns the all-play metrics that actually depend on it.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_weekly_scoring_ranks`.
WEEKLY_SCORING_RANK_COLUMNS = [
    "season",
    "week",
    "is_playoff",
    "roster_id",
    "owner",
    "points",
    "weekly_rank",
]


def _sort_key(observation: dict) -> tuple:
    """Deterministic output ordering key: season, week, rank, then roster_id.

    ``season`` may be ``None`` (see ``MatchupOutcome.season``), which is not
    orderable against a string, so it is sorted as a leading boolean flag with
    ``None`` last rather than compared directly.
    """
    season = observation["season"]
    return (
        season is None,
        season if season is not None else "",
        observation["week"],
        observation["weekly_rank"],
        observation["roster_id"],
    )


def _assign_week_ranks(observations: list[dict]) -> None:
    """Assign ``weekly_rank`` in place to one week's scored observations.

    Orders ``observations`` by descending ``points`` and writes standard
    competition ("1224") ranks -- the same convention as
    :func:`~fantasy_analyzer.analytics.standings.build_standings` -- so tied
    scores share a rank and the next distinct rank skips the tied count.
    """
    ordered = sorted(observations, key=lambda obs: (-obs["points"], obs["roster_id"]))

    current_rank = 0
    previous_points = None
    for position, observation in enumerate(ordered, start=1):
        if observation["points"] != previous_points:
            current_rank = position
            previous_points = observation["points"]
        observation["weekly_rank"] = current_rank


def build_weekly_scoring_ranks(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row per roster-week, ranked by that week's points scored.

    Reshapes the wide, one-row-per-matchup ``season_matchup_df`` into a long,
    one-row-per-roster-per-week frame and ranks rosters within each
    ``(season, week)`` by descending ``points``. See the module docstring for
    the exact metric definition, why bye rows are included while
    missing-points observations are excluded, the standard competition
    ("1224") ranking convention, and the regular-season-vs-playoff behavior.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used to resolve the
            ``owner`` label.

    Returns:
        A DataFrame with columns :data:`WEEKLY_SCORING_RANK_COLUMNS`, one row
        per ``(season, week, roster_id)`` that has a defined score, sorted by
        ``season``, then ``week``, then ascending ``weekly_rank`` (ties broken
        by ascending ``roster_id``). ``weekly_rank`` is 1-indexed with ``1``
        the week's highest score. Returns an empty DataFrame with the
        expected columns if ``season_matchup_df`` is empty or if no
        observation has a defined score. A ``roster_id`` absent from
        ``teams_df`` (or an empty ``teams_df``) resolves to ``owner = None``
        rather than raising.

    Raises:
        ValueError: If the same ``(season, week, roster_id)`` appears more
            than once -- a roster cannot play two matchups in one week; see
            the module docstring's "Duplicate roster-weeks" note.
    """
    if season_matchup_df.empty:
        return pd.DataFrame(columns=WEEKLY_SCORING_RANK_COLUMNS)

    owner_by_roster = (
        teams_df.set_index("roster_id")["display_name"].to_dict()
        if not teams_df.empty
        else {}
    )

    weeks: dict[tuple, list[dict]] = {}
    seen: set[tuple] = set()

    for row in season_matchup_df.itertuples(index=False):
        season: Optional[str] = row.season if pd.notna(row.season) else None
        week = int(row.week)
        is_playoff = bool(row.is_playoff) if pd.notna(row.is_playoff) else False

        # A bye row (roster_2_id is None) contributes only roster 1's score --
        # a real score with no opponent, which still belongs in the week's
        # ranking. See the module docstring's "Bye rows are included" section.
        sides = [(row.roster_1_id, row.points_1)]
        if pd.notna(row.roster_2_id):
            sides.append((row.roster_2_id, row.points_2))

        for roster_id, points in sides:
            # A missing score cannot be ranked and is never treated as 0.0 --
            # the observation is dropped entirely.
            if pd.isna(points):
                continue

            roster_id = int(roster_id)
            key = (season, week, roster_id)
            if key in seen:
                raise ValueError(
                    f"roster_id {roster_id} has more than one scored matchup "
                    f"in season {season!r} week {week} -- a roster cannot "
                    "play twice in one week"
                )
            seen.add(key)

            weeks.setdefault((season, week), []).append(
                {
                    "season": season,
                    "week": week,
                    "is_playoff": is_playoff,
                    "roster_id": roster_id,
                    "points": float(points),
                    "weekly_rank": None,
                }
            )

    # Every observation may have been dropped (e.g. a wholly unloaded season):
    # return an empty, correctly-shaped frame rather than letting
    # pd.DataFrame([]) build a columnless frame.
    if not weeks:
        return pd.DataFrame(columns=WEEKLY_SCORING_RANK_COLUMNS)

    for observations in weeks.values():
        _assign_week_ranks(observations)

    rows = sorted(
        (
            observation
            for observations in weeks.values()
            for observation in observations
        ),
        key=_sort_key,
    )

    result = pd.DataFrame(rows)

    # ``owner`` is assigned as its own explicit ``dtype=object`` Series rather
    # than as a plain dict value inside ``rows``: pandas' newer default
    # string-dtype inference otherwise upcasts a column mixing real owner
    # names with ``None`` into a string dtype that silently turns ``None``
    # into ``NaN``, breaking the documented "unmapped owner -> ``None``"
    # contract (see ``head_to_head.py``'s identical note).
    result["owner"] = pd.Series(
        [owner_by_roster.get(roster_id) for roster_id in result["roster_id"]],
        dtype=object,
    )
    return result[WEEKLY_SCORING_RANK_COLUMNS]
