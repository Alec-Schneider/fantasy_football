"""Build season-long all-play standings from weekly scores (FFA-051).

Consumes FFA-050's
:func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
output and aggregates it into one row per roster, recording how that roster
would have fared if it had played **every** other roster every week rather
than only its actually-scheduled opponent. This module performs no network
access; it operates entirely on an already-built ``weekly_scoring_ranks_df``.

Metric definitions
-------------------

Within a single ``(season, week)``, for an ordered pair of distinct rosters
``r`` and ``o`` that both have a defined score that week, ``r``'s all-play
result against ``o`` is:

- **win** if ``points_r > points_o``
- **loss** if ``points_r < points_o``
- **tie** if ``points_r == points_o``

Every such comparison is symmetric by construction: ``r``'s win over ``o`` is
exactly ``o``'s loss to ``r``, and a tie is mutual (a tie is credited as a tie
to *both* rosters, never as a win to one and a loss to the other). Each
unordered pair in a week is evaluated once and credited to both sides, so the
league-wide invariant ``sum(all_play_wins) == sum(all_play_losses)`` holds
exactly, and ``sum(all_play_ties)`` is always even.

The season columns are then:

- **weeks_played** -- the number of weeks in which that roster has a defined
  score, i.e. the count of its rows in the input.
- **all_play_wins** / **all_play_losses** / **all_play_ties** -- the weekly
  all-play results above, summed over every week the roster appears in.
- **all_play_games** -- ``all_play_wins + all_play_losses + all_play_ties``,
  the total number of pairwise comparisons the roster took part in across the
  season. This is generally much larger than ``weeks_played``: a roster in a
  fully-scored 12-roster league accumulates 11 comparisons per week, so 14
  weeks produce 154 all-play games, not 14.
- **all_play_win_pct** -- ``(all_play_wins + 0.5 * all_play_ties) /
  all_play_games``, the same formula (and the same "half credit for a tie"
  convention) that ``standings.py``'s ``win_pct`` uses for real records, so
  the two are directly comparable. A roster with ``all_play_games == 0``
  gets ``0.0`` rather than a division-by-zero error or ``NaN`` -- the same
  explicit zero-denominator rule ``standings.py`` applies. See "Field size of
  one" below for the only case that can produce it.

Field size varies week to week
-------------------------------

The number of comparisons a roster accumulates in a week is ``field_size -
1``, where ``field_size`` is the number of rosters with a **defined score**
that week -- not the league size. FFA-050 excludes missing-points
observations entirely (a missing score is never treated as ``0.0``), so a
week in which two of twelve rosters have no loaded score has ``field_size =
10`` and contributes 9 comparisons to each of the ten present rosters, and
nothing at all to the two absent ones.

Consequently ``all_play_games`` is **not** guaranteed to be equal across
rosters, and ``all_play_win_pct`` -- a rate, not a count -- is the column to
compare rosters on. Two rosters with the same ``all_play_wins`` but different
``all_play_games`` did not have equally strong seasons.

Bye weeks are included, for the same reason FFA-050 ranks them: a bye is a
real score with no opponent, so it is perfectly eligible for comparison
against every other roster that scored that week. Nothing in this module
inspects whether a score came from a bye or from a played matchup; the input
frame does not distinguish them, and the metric does not care.

Field size of one
------------------

A week with exactly one scored roster (``field_size == 1``) offers that
roster nobody to compare against, so it contributes **zero** all-play
comparisons -- no self-comparison, and no synthetic opponent. The roster's
``weeks_played`` still counts that week (it did score), so ``weeks_played``
and ``all_play_games`` can disagree in the obvious direction.

If that is a roster's *only* week, its ``all_play_games`` is ``0`` and its
``all_play_win_pct`` is the documented ``0.0`` fallback. This is the only
legitimate zero-games case: a roster with zero weeks played has no rows in
the input at all and so gets no output row (see below).

Rows are input-driven: a roster with no scored week is absent
---------------------------------------------------------------

Output rows come exclusively from rosters present in
``weekly_scoring_ranks_df``. A league roster that never appears there -- one
whose every week's score is missing, or a roster added to ``teams_df`` that
never played -- gets **no row**, rather than an all-zero row. This follows
FFA-040's "a pair with zero meetings has no row" precedent: a rate metric
over zero observations is not meaningfully ``0.0``, it is undefined, and
emitting it invites callers to read a fabricated last place into it.

Why there is no ``teams_df`` parameter
----------------------------------------

``owner`` is read from the input frame's own ``owner`` column -- FFA-050
already resolved it from ``teams_df["display_name"]`` -- rather than being
re-resolved here. Combined with the input-driven row set above, that leaves
``teams_df`` with no role in this function, so it is not a parameter. This
mirrors ``head_to_head_matrix.py``, which likewise takes only its upstream
frame and inherits that frame's already-settled label and edge-case rules
instead of re-deriving them and risking drift.

A roster whose ``owner`` is unresolved in the input (``None``/``NaN``) stays
``None`` in the output rather than raising, consistent with FFA-050's own
contract. A roster's ``owner`` is read from the first row in which it has a
non-null value; ``owner`` is a per-roster label that FFA-050 resolves the
same way in every week, so this cannot disagree across weeks for a
well-formed input.

Ranking rule
------------

``all_play_rank`` orders rosters by descending ``all_play_win_pct`` using
**standard competition ("1224") ranking**, the same convention as
``standings.py``'s ``rank``, ``build_scoring_summary``'s ``scoring_rank``,
and ``weekly_scores.py``'s ``weekly_rank``: rosters with identical
``all_play_win_pct`` share a rank, and the next distinct rank skips the
number of tied rosters.

The rank key is ``all_play_win_pct`` **alone**. Unlike ``standings.py``,
which breaks record ties on ``points_for``, there is no second criterion
here: any obvious candidate (total points, ``all_play_wins``) either is not
carried on this frame or would penalize a roster for having played in
smaller fields. Genuinely tied rosters therefore share a rank rather than
being separated by an arbitrary rule. Rows are *ordered* by descending
``all_play_win_pct`` then ascending ``roster_id``, but that ``roster_id``
tiebreak is only a deterministic display order and is not reflected in
``all_play_rank``.

The column is named ``all_play_rank`` rather than ``rank`` to match the
``all_play_`` prefix the rest of the frame uses and the qualified-rank naming
of ``weekly_rank``/``scoring_rank``, and to stay unambiguous when this frame
is merged alongside ``standings.py``'s ``rank``.

Regular season vs. playoffs
------------------------------

This function computes a single **combined** all-play table across every week
present in the input -- regular season and playoff alike. It applies no
``is_playoff`` filter and makes no phase distinction of its own, matching
FFA-040/FFA-042/FFA-050's established precedent. ``is_playoff`` is not read
at all and is not carried into the output, since a season-total row spans
both phases and could not carry a single meaningful value for it.

A caller wanting a phase-specific view should filter
``weekly_scoring_ranks_df`` on ``is_playoff`` **before** calling. Note that
doing so also changes the comparison field: filtering to regular-season weeks
compares each roster only against rosters that scored in those weeks, which
is the intended meaning of a regular-season all-play record.

Missing values / edge cases
----------------------------

- **Empty ``weekly_scoring_ranks_df``**: returns an empty DataFrame with
  :data:`ALL_PLAY_STANDINGS_COLUMNS`.
- **A row with missing ``points``**: FFA-050 never emits one (every row in
  its output has a real score), but if a hand-built input contains one it is
  skipped entirely -- not compared, not counted toward ``weeks_played``, and
  never treated as ``0.0``. If that is true of every row, the result is an
  empty (but correctly-shaped) frame. This keeps the same "missing is not
  zero" rule as FFA-050 and ``reconciliation.py``.
- **Tied scores**: handled by direct pairwise comparison, so a tie is mutual
  by construction (see "Metric definitions"). Score equality is exact float
  equality, the same test ``weekly_scores.py`` uses to detect tied ranks;
  Sleeper reports points to two decimals, so near-miss floating point
  equality is not a practical concern and no tolerance is applied.
- **Multiple seasons in one frame**: ``(season, week)`` -- not ``week``
  alone -- is the grouping key, so a roster is never compared against a
  different season's week 1 scores. Season totals are then summed across all
  seasons present into a single row per roster; a caller wanting per-season
  all-play standings should filter the input by ``season`` first.
- **Duplicate roster-weeks**: not validated here.
  :func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
  already raises on an input that would produce two rows for one
  ``(season, week, roster_id)``, so any frame it produces satisfies the
  uniqueness invariant this module relies on.

Implementation note: pairwise, not closed-form
------------------------------------------------

Weekly results are computed by direct pairwise comparison over
``itertools.combinations`` of the week's scores, not by a closed-form
expression in ``weekly_rank`` and field size. The closed form is available
(with ``k`` rosters sharing a rank, each has ``k - 1`` ties and
``field_size - rank - k + 1`` wins), but it is easy to get subtly wrong in
exactly the tied cases that matter, whereas the pairwise form *is* the metric
definition and is auditable line by line. League fields are around a dozen
rosters, so the ``O(field_size^2)`` cost per week is irrelevant.
"""

from __future__ import annotations

from itertools import combinations
from typing import Optional

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_all_play_standings`.
ALL_PLAY_STANDINGS_COLUMNS = [
    "roster_id",
    "owner",
    "weeks_played",
    "all_play_wins",
    "all_play_losses",
    "all_play_ties",
    "all_play_games",
    "all_play_win_pct",
    "all_play_rank",
]


def _all_play_win_pct(wins: int, losses: int, ties: int) -> float:
    """Compute all-play win percentage, returning ``0.0`` at zero games.

    ``(wins + 0.5 * ties) / (wins + losses + ties)`` -- the same formula and
    the same zero-denominator rule as
    :func:`fantasy_analyzer.analytics.standings._win_pct`, reimplemented here
    rather than imported so this module does not depend on another module's
    private helper (the same choice ``weekly_scores.py`` made for its ranking
    loop).
    """
    games = wins + losses + ties
    if games == 0:
        return 0.0
    return (wins + 0.5 * ties) / games


def _roster_bucket(totals: dict, roster_id: int) -> dict:
    """Return (creating if absent) the running all-play totals for a roster."""
    if roster_id not in totals:
        totals[roster_id] = {
            "owner": None,
            "weeks_played": 0,
            "all_play_wins": 0,
            "all_play_losses": 0,
            "all_play_ties": 0,
        }
    return totals[roster_id]


def _score_week(week_scores: list[tuple[int, float]], totals: dict) -> None:
    """Credit one week's pairwise all-play results into ``totals`` in place.

    Evaluates each unordered pair of distinct rosters in the week exactly
    once and credits both sides symmetrically, so a win for one roster is
    always exactly a loss for the other and a tie is always mutual. A week
    with fewer than two scored rosters yields no pairs and credits nothing.
    """
    for (left_id, left_points), (right_id, right_points) in combinations(
        week_scores, 2
    ):
        if left_points > right_points:
            totals[left_id]["all_play_wins"] += 1
            totals[right_id]["all_play_losses"] += 1
        elif left_points < right_points:
            totals[left_id]["all_play_losses"] += 1
            totals[right_id]["all_play_wins"] += 1
        else:
            totals[left_id]["all_play_ties"] += 1
            totals[right_id]["all_play_ties"] += 1


def build_all_play_standings(weekly_scoring_ranks_df: pd.DataFrame) -> pd.DataFrame:
    """Build one row of season-long all-play standings per roster.

    For every ``(season, week)`` in ``weekly_scoring_ranks_df``, compares each
    roster's score against every *other* roster's score that week (win/loss/
    tie), then sums those hypothetical results across the season into a
    schedule-independent record. See the module docstring for the exact metric
    definitions, the varying-field-size caveat, the zero-comparison and
    missing-value rules, the ranking convention, and the combined
    regular-season-plus-playoff behavior.

    Args:
        weekly_scoring_ranks_df: A
            :data:`~fantasy_analyzer.analytics.weekly_scores.WEEKLY_SCORING_RANK_COLUMNS`-shaped
            DataFrame, as produced by
            :func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`.
            Only ``season``, ``week``, ``roster_id``, ``points``, and ``owner``
            are read; ``is_playoff`` and ``weekly_rank`` are ignored.

    Returns:
        A DataFrame with columns :data:`ALL_PLAY_STANDINGS_COLUMNS`, one row
        per roster that has at least one scored week in the input, sorted by
        descending ``all_play_win_pct`` then ascending ``roster_id``.
        ``all_play_rank`` is 1-indexed standard competition ranking on
        ``all_play_win_pct`` alone (ties share a rank; the next rank skips
        accordingly). Returns an empty DataFrame with the expected columns if
        the input is empty or contains no row with a defined score. A roster
        whose ``owner`` is unresolved in the input stays ``None`` rather than
        raising.
    """
    if weekly_scoring_ranks_df.empty:
        return pd.DataFrame(columns=ALL_PLAY_STANDINGS_COLUMNS)

    weeks: dict[tuple, list[tuple[int, float]]] = {}
    totals: dict[int, dict] = {}

    for row in weekly_scoring_ranks_df.itertuples(index=False):
        # FFA-050 never emits a missing score, but a hand-built input might:
        # such an observation has no defined score, so it is skipped entirely
        # rather than compared or treated as 0.0.
        if pd.isna(row.points):
            continue

        roster_id = int(row.roster_id)
        season: Optional[str] = row.season if pd.notna(row.season) else None

        bucket = _roster_bucket(totals, roster_id)
        bucket["weeks_played"] += 1
        if bucket["owner"] is None and pd.notna(row.owner):
            bucket["owner"] = row.owner

        # (season, week) -- not week alone -- so a multi-season frame never
        # compares one season's scores against another's.
        weeks.setdefault((season, int(row.week)), []).append(
            (roster_id, float(row.points))
        )

    # Every observation may have been skipped (e.g. a frame of missing
    # scores): return an empty, correctly-shaped frame rather than letting
    # pd.DataFrame([]) build a columnless frame.
    if not totals:
        return pd.DataFrame(columns=ALL_PLAY_STANDINGS_COLUMNS)

    for week_scores in weeks.values():
        _score_week(week_scores, totals)

    rows = []
    for roster_id, values in totals.items():
        wins = values["all_play_wins"]
        losses = values["all_play_losses"]
        ties = values["all_play_ties"]
        rows.append(
            {
                "roster_id": roster_id,
                "weeks_played": values["weeks_played"],
                "all_play_wins": wins,
                "all_play_losses": losses,
                "all_play_ties": ties,
                "all_play_games": wins + losses + ties,
                "all_play_win_pct": _all_play_win_pct(wins, losses, ties),
            }
        )

    result = pd.DataFrame(rows)
    result = result.sort_values(
        by=["all_play_win_pct", "roster_id"], ascending=[False, True]
    ).reset_index(drop=True)

    # Standard competition ("1224") ranking on all_play_win_pct alone: tied
    # rosters share a rank, and the next distinct rank skips the tied count.
    # The roster_id sort above is display order only and is not a rank
    # tiebreak -- see the module docstring's "Ranking rule" section.
    ranks = []
    current_rank = 0
    previous_key = None
    for position, key in enumerate(result["all_play_win_pct"], start=1):
        if key != previous_key:
            current_rank = position
            previous_key = key
        ranks.append(current_rank)
    result["all_play_rank"] = ranks

    # ``owner`` is assigned as its own explicit ``dtype=object`` Series rather
    # than as a plain dict value inside ``rows``: pandas' newer default
    # string-dtype inference otherwise upcasts a column mixing real owner
    # names with ``None`` into a string dtype that silently turns ``None``
    # into ``NaN``, breaking the documented "unresolved owner -> ``None``"
    # contract (see ``head_to_head.py``/``weekly_scores.py``'s identical note).
    result["owner"] = pd.Series(
        [totals[roster_id]["owner"] for roster_id in result["roster_id"]],
        dtype=object,
    )
    return result[ALL_PLAY_STANDINGS_COLUMNS]
