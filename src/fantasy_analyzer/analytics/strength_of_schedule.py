"""Strength of schedule from a single season matchup frame (FFA-054).

Answers "how tough were the opponents this roster actually faced?" by
averaging, over every week the roster had a real opponent, a season-long
measure of *that specific opponent's* quality. A roster with a high average
faced strong opponents; a low average, weak ones. This module performs no
network access; it operates entirely on an already-built
``season_matchup_df``.

Note what this metric is and is not. It describes the **schedule**, not the
roster: nothing about the roster's own scoring, record, or luck enters its
own row. It is the natural companion to FFA-052's ``schedule_luck``, which
measures how much a roster's *record* diverged from its scoring strength;
this module instead measures one concrete reason such a divergence can arise.
The two are not redundant and neither implies the other -- a roster can draw
a brutal set of opponents and still be lucky, if it happened to catch each of
them in their bad weeks.

Two measures of opponent strength, both reported
--------------------------------------------------

There is no single obviously-correct definition of "opponent quality", so
this module computes **two** and puts them side by side rather than picking
one and hiding the choice:

- **avg_opponent_win_pct** averages each opponent's *actual* win percentage.
  This is the traditional definition, and the one a reader who has seen an
  NFL "opponents' combined win percentage" table will expect.
- **avg_opponent_all_play_win_pct** averages each opponent's *all-play* win
  percentage (FFA-051), i.e. how often that opponent outscored a randomly
  drawn league-mate. This is schedule-independent, so unlike the first
  measure it is not itself contaminated by whether the opponent's own record
  was lucky or unlucky.

The all-play variant is arguably the more principled "true strength" proxy,
but the actual-record variant is what "strength of schedule" conventionally
means, and dropping either would throw away the most interesting thing here:
**where the two disagree**. A roster whose ``avg_opponent_win_pct`` is high
while its ``avg_opponent_all_play_win_pct`` is middling faced opponents who
were themselves lucky -- it played teams with good records that were not
actually scoring like good teams. Reporting only the first measure would
call that a hard schedule; reporting only the second would call it an
average one; reporting both says the more useful thing, which is that the
schedule *looked* hard on paper and was not.

Both columns are averages of quantities that already use the same "half
credit for a tie" convention (``standings.py``'s ``win_pct``,
``all_play.py``'s ``all_play_win_pct``), so the two are on the same 0-1 scale
and are directly comparable to each other and to a roster's own record.

Metric definitions
-------------------

Let ``S`` be the per-roster strength table this module builds internally by
calling :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
on the *same* ``season_matchup_df`` that was passed in (see the next section
for why this matters). ``S[o].win_pct`` and ``S[o].all_play_win_pct`` are
opponent ``o``'s two season-long strength numbers.

For a roster ``r``, let ``O(r)`` be the **multiset** of opponents obtained by
scanning every row of ``season_matchup_df`` in which ``r`` appears as
``roster_1_id`` or ``roster_2_id`` and:

1. the row has a real opponent -- ``roster_2_id`` is not ``None`` (a bye row
   has no opponent at all and is skipped); **and**
2. that opponent has a row in ``S`` (see "Bye weeks versus unresolvable
   opponents" below for the case where it does not).

``O(r)`` is a multiset, not a set: an opponent faced twice contributes twice.
The metrics are per-week averages, so playing the league's strongest roster
in two of fourteen weeks should weigh twice as heavily as playing it once.
Note that this row scan does **not** require the week's own points to be
present -- see "A missing score is not a missing opponent" below.

Then:

- **opponent_weeks** -- ``|O(r)|``, the number of weeks that entered the two
  averages, and the sample size behind them. It is deliberately the first
  metric column: at around a dozen weeks these are small-sample averages.
- **unresolved_opponent_weeks** -- the number of weeks with a real opponent
  that were skipped by rule 2 above. Normally ``0``. It is reported so that a
  roster whose ``opponent_weeks`` is short because an opponent's strength was
  unknown is distinguishable from one that simply played fewer games.
- **avg_opponent_win_pct** --
  ``(1 / |O(r)|) * sum over o in O(r) of S[o].win_pct``.
- **avg_opponent_all_play_win_pct** --
  ``(1 / |O(r)|) * sum over o in O(r) of S[o].all_play_win_pct``.

Both averages are unweighted means over opponent-weeks. Since a roster with
``opponent_weeks == 0`` gets no row at all (see below), neither is ever a
division by zero.

Opponent strength and the opponent list must cover the same games
-------------------------------------------------------------------

This is FFA-052's structural problem in a new place, and it is solved the
same way. If the opponent-strength numbers were computed over one set of
games (say, all 18 loaded weeks) while the opponent list was drawn from
another (say, the 14 regular-season weeks), the resulting average would
describe a schedule that nobody played. The failure is silent: the number
still looks like a plausible strength of schedule.

:func:`build_strength_of_schedule` is therefore designed so that mistake is
**structurally impossible for its caller**, not merely warned about. It takes
one shared input -- ``season_matchup_df`` -- and builds *both* halves from
it:

- the **opponent-strength** side by calling
  ``build_schedule_luck(season_matchup_df, teams_df)`` (imported and reused,
  not reimplemented), which itself already guarantees that its ``win_pct``
  and ``all_play_win_pct`` columns cover the same games as each other;
- the **opponent list** side by scanning the same frame's rows directly.

There is no parameter through which a caller can hand in a pre-built,
independently-filtered strength table, and Sleeper's season-cumulative roster
counters are never consulted. Whatever rows the caller passes define both
sides at once.

The consequence for callers is a single rule:

    Pass ``season_matchup_df[season_matchup_df["is_playoff"] == False]`` for
    a regular-season-only view. Do **not** build the two halves from
    separately-filtered frames -- there is no supported way to do so here,
    and doing it by hand outside this module reintroduces the phase-mismatch
    bug.

An opponent's strength includes its games against you
-------------------------------------------------------

``S[o].win_pct`` and ``S[o].all_play_win_pct`` are opponent ``o``'s strength
over its **whole** season, including the very games it played against ``r``.
There is no leave-one-out correction removing ``r``'s own contribution from
its opponents' strength numbers.

This is deliberate, and it is standard: the NFL's "opponents' combined win
percentage" works exactly this way, as do most published strength-of-schedule
tables. It does introduce a small, known bias -- beating an opponent lowers
that opponent's win percentage and therefore lowers your own measured
strength of schedule, so strong rosters' schedules look marginally easier
than they were, and weak rosters' marginally harder. At this scale the effect
is bounded and small: with roughly a dozen rosters meeting once or twice, a
single result moves an opponent's ``win_pct`` by at most ``1 / games_played``
and its ``all_play_win_pct`` by far less (one week's result is one of many
pairwise comparisons). A leave-one-out variant would require recomputing
every opponent's full record and all-play rate once per meeting, which is a
large amount of machinery for a correction smaller than the sampling noise of
a 14-game season. It is documented here rather than implemented.

A related and unavoidable artifact worth naming, since it surprises readers:
because a roster never plays itself, the league's *best* roster has the
league's weakest schedule almost mechanically (it is the only roster that
never has to face itself), and the worst roster the toughest. Strength of
schedule is negatively correlated with team quality by construction; it is
not evidence of unfair scheduling.

Bye weeks versus unresolvable opponents
-----------------------------------------

Two different things can stop a week from contributing to the averages, and
they are counted differently:

- **A bye row** (``roster_2_id is None``, see
  :mod:`~fantasy_analyzer.matchups.pairing`) has **no opponent at all**. It
  is skipped entirely and counts toward neither ``opponent_weeks`` nor
  ``unresolved_opponent_weeks``. There was no schedule to be strong or weak
  that week. This matches how ``head_to_head.py``, ``outcomes.py`` and
  ``reconciliation.py`` already treat a bye.
- **An unresolvable opponent** is a real, present opponent whose own strength
  could not be looked up, because it has no row in ``S``.
  ``build_schedule_luck`` emits no row for a roster with zero *decided*
  games, so this arises when every one of that opponent's games in the frame
  was itself undecided (missing points). The week is skipped from both
  averages -- guessing a strength for a roster with no recorded result would
  be inventing data, the same "missing is not zero, not a guess" rule
  FFA-050/FFA-051 apply to missing scores -- but it *is* counted in
  ``unresolved_opponent_weeks`` so the omission is visible rather than silent.

A missing score is not a missing opponent
-------------------------------------------

A row with a real ``roster_2_id`` but missing ``points_1``/``points_2`` (an
unloaded week, not a bye) **still counts** as an opponent-week, provided that
opponent is resolvable in ``S``. Strength of schedule needs only two things
from a row: who the opponent was, and how good that opponent's season was.
Neither depends on this particular week's score having loaded.

This is a genuine departure from FFA-040/FFA-042/FFA-050, which exclude
missing-points rows -- correctly, because *their* metrics (points, margins,
weekly ranks) are functions of the score itself and cannot be computed
without it. Here the score is not an input, so excluding the row would
discard a known fact about the schedule for no reason. Note that such a week
does not feed the opponent's own strength numbers, since
``build_schedule_luck`` sees no decision and no score in it either; it simply
does not exist on that side of the calculation.

Ranking rule
------------

**Rank 1 is the toughest schedule** -- the roster with the *highest* average
opponent strength -- for both rank columns.

This is stated loudly because "strength of schedule rank" is genuinely
ambiguous in casual usage: some readers assume rank 1 means the hardest
schedule, others that it means the best-off team (the easiest schedule).
Here, as in ``all_play.py``'s ``all_play_rank``, rank 1 goes to the largest
value of the thing being ranked -- so rank 1 means "faced the strongest
opponents", which is bad news for the roster, not a compliment. Both rank
columns use the same direction; there is no column on which 1 means easiest.

- **sos_rank** ranks ``avg_opponent_win_pct`` descending.
- **all_play_sos_rank** ranks ``avg_opponent_all_play_win_pct`` descending.

Each is computed independently over its own column, so the two can and often
will disagree -- that disagreement is the point of reporting both, and
reading them together is the intended use. Both use standard competition
("1224") ranking, the same convention as every other rank column in this
package: tied values share a rank and the next distinct rank skips the tied
count. There is no secondary tiebreak on either -- any candidate (the other
average, ``opponent_weeks``) would be an arbitrary rule masquerading as a
measurement -- so genuinely tied rosters genuinely share a rank. Equality is
exact float equality; two rosters that faced the same multiset of opponents
reach the same float through the same code path, which is the case that
matters in practice.

Rows are *ordered* by descending ``avg_opponent_win_pct`` then ascending
``roster_id``, but that ``roster_id`` tiebreak is display order only and is
not reflected in either rank.

Regular season vs. playoffs
------------------------------

This function applies **no** ``is_playoff`` filter and makes no phase
distinction of its own -- it computes a single combined result over every row
it is given, matching FFA-040/FFA-042/FFA-050/FFA-051/FFA-052's established
precedent. ``is_playoff`` is not carried into the output, since a
season-total row spans both phases.

Filtering is the caller's job, and per "Opponent strength and the opponent
list must cover the same games" above, filtering ``season_matchup_df``
*before* the call is both the only supported way to do it and automatically
consistent across both halves of the calculation. The conventional and most
meaningful view is regular-season-only: a playoff bracket is seeded, not
scheduled, so "the strength of the schedule you were handed" does not mean
the same thing there. Be aware that filtering also changes the strength
numbers themselves -- a regular-season-only call measures opponents by their
regular-season records, which is the intended meaning.

Missing values / edge cases
----------------------------

- **Empty ``season_matchup_df``**: returns an empty DataFrame with
  :data:`STRENGTH_OF_SCHEDULE_COLUMNS`.
- **A roster with ``opponent_weeks == 0``** -- no row. This covers a roster
  absent from the frame entirely, a roster whose every row is a bye (the
  guillotine-format case FFA-052 hit in live validation), and the rare roster
  whose every opponent was unresolvable. An average over zero opponent-weeks
  is undefined, not ``0.0``, and emitting ``0.0`` would read as "faced the
  weakest possible schedule". This follows the same "zero observations -> no
  row" precedent as ``head_to_head.py``, ``all_play.py`` and
  ``schedule_luck.py``. Note that the last case loses that roster's
  ``unresolved_opponent_weeks`` count along with the rest of its row.
- **A roster absent from ``S`` can still get a row here.** The output row set
  comes from the opponent scan, not from ``S``: a roster whose own games were
  all undecided has no strength of its own but still faced real opponents,
  and its schedule is perfectly well defined. Conversely a roster present in
  ``S`` whose every row is a bye gets no row here.
- **Ties** in either average share a rank under standard competition ranking
  (see "Ranking rule").
- **Multiple seasons in one frame** are pooled into a single row per roster,
  inheriting that behavior from ``build_schedule_luck``; opponent strengths
  are likewise season-pooled. Filter by ``season`` first for a per-season
  view.
- **An internally inconsistent frame** -- a recorded winner on a row with no
  points -- makes ``build_schedule_luck`` raise ``ValueError``, and that
  propagates out of this function unchanged rather than being caught and
  turned into an unresolvable opponent.
"""

from __future__ import annotations

import pandas as pd

from fantasy_analyzer.analytics.schedule_luck import build_schedule_luck

#: Column order for the DataFrame returned by :func:`build_strength_of_schedule`.
STRENGTH_OF_SCHEDULE_COLUMNS = [
    "roster_id",
    "owner",
    "opponent_weeks",
    "unresolved_opponent_weeks",
    "avg_opponent_win_pct",
    "sos_rank",
    "avg_opponent_all_play_win_pct",
    "all_play_sos_rank",
]


def _roster_bucket(totals: dict, roster_id: int) -> dict:
    """Return (creating if absent) the running schedule totals for a roster."""
    if roster_id not in totals:
        totals[roster_id] = {
            "opponent_weeks": 0,
            "unresolved_opponent_weeks": 0,
            "opponent_win_pct_total": 0.0,
            "opponent_all_play_win_pct_total": 0.0,
        }
    return totals[roster_id]


def _competition_ranks(values: list[float]) -> list[int]:
    """Standard competition ("1224") ranks, highest value first.

    Returns one 1-indexed rank per input value, in the input's own order:
    tied values share a rank and the next distinct rank skips the tied count.
    Unlike the in-place ranking loops in ``all_play.py`` and
    ``schedule_luck.py``, this does not assume ``values`` is already sorted,
    because this module ranks two different columns and can only sort its rows
    by one of them.
    """
    order = sorted(range(len(values)), key=lambda index: -values[index])

    ranks = [0] * len(values)
    current_rank = 0
    previous_key = None
    for position, index in enumerate(order, start=1):
        key = values[index]
        if key != previous_key:
            current_rank = position
            previous_key = key
        ranks[index] = current_rank
    return ranks


def build_strength_of_schedule(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row per roster of average faced-opponent strength.

    For every week a roster had a real opponent, looks up that opponent's
    season-long ``win_pct`` and ``all_play_win_pct`` and averages each across
    the roster's whole schedule. Both opponent-strength columns come from
    :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
    called on the *same* ``season_matchup_df`` the opponent list is scanned
    from, so the two halves always cover the same set of games -- see the
    module docstring for why that matters, for the exact formulas, the
    rank-direction convention (rank 1 = toughest), the bye vs. unresolvable
    opponent distinction, and the accepted no-leave-one-out simplification.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
            Filter it to ``is_playoff == False`` *before* calling for the
            conventional regular-season-only view; this function applies no
            phase filter of its own.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used to resolve the
            ``owner`` label and passed through to ``build_schedule_luck``.

    Returns:
        A DataFrame with columns :data:`STRENGTH_OF_SCHEDULE_COLUMNS`, one row
        per roster with at least one resolvable opponent-week in the input,
        sorted by descending ``avg_opponent_win_pct`` then ascending
        ``roster_id``. ``sos_rank`` and ``all_play_sos_rank`` are 1-indexed
        standard competition ranks on their respective averages, with ``1``
        the **toughest** schedule in both cases. A roster with zero
        opponent-weeks (never played, bye rows only, or every opponent
        unresolvable) is absent. Returns an empty DataFrame with the expected
        columns if ``season_matchup_df`` is empty or no roster has a
        resolvable opponent-week. A roster whose ``owner`` is unresolved stays
        ``None`` rather than raising.

    Raises:
        ValueError: Propagated unchanged from
            :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
            if the input is internally inconsistent (a decided game on a row
            with no points).
    """
    if season_matchup_df.empty:
        return pd.DataFrame(columns=STRENGTH_OF_SCHEDULE_COLUMNS)

    # Opponent strengths and the opponent list are both derived from this one
    # frame -- the whole point of the single-input design; see the module
    # docstring's "Opponent strength and the opponent list must cover the same
    # games" section.
    strength = build_schedule_luck(season_matchup_df, teams_df)
    strength_by_roster = {
        int(row.roster_id): (float(row.win_pct), float(row.all_play_win_pct))
        for row in strength.itertuples(index=False)
    }

    owner_by_roster = (
        teams_df.set_index("roster_id")["display_name"].to_dict()
        if not teams_df.empty
        else {}
    )

    totals: dict[int, dict] = {}

    for row in season_matchup_df.itertuples(index=False):
        # A bye row has no opponent at all: it is not an opponent-week and not
        # an unresolved one either. See the module docstring's "Bye weeks
        # versus unresolvable opponents" section.
        if pd.isna(row.roster_2_id):
            continue

        roster_1_id = int(row.roster_1_id)
        roster_2_id = int(row.roster_2_id)

        # Two perspectives per row -- each side is the other's opponent. The
        # week's own points are deliberately not consulted: SOS needs only the
        # opponent's identity. See "A missing score is not a missing opponent".
        for own_id, opponent_id in (
            (roster_1_id, roster_2_id),
            (roster_2_id, roster_1_id),
        ):
            bucket = _roster_bucket(totals, own_id)
            opponent_strength = strength_by_roster.get(opponent_id)
            if opponent_strength is None:
                # A real opponent whose own strength is unknown: skipped from
                # both averages rather than guessed at, but counted so the
                # omission stays visible.
                bucket["unresolved_opponent_weeks"] += 1
                continue

            opponent_win_pct, opponent_all_play_win_pct = opponent_strength
            bucket["opponent_weeks"] += 1
            bucket["opponent_win_pct_total"] += opponent_win_pct
            bucket["opponent_all_play_win_pct_total"] += opponent_all_play_win_pct

    rows = [
        {
            "roster_id": roster_id,
            "opponent_weeks": values["opponent_weeks"],
            "unresolved_opponent_weeks": values["unresolved_opponent_weeks"],
            "avg_opponent_win_pct": (
                values["opponent_win_pct_total"] / values["opponent_weeks"]
            ),
            "avg_opponent_all_play_win_pct": (
                values["opponent_all_play_win_pct_total"] / values["opponent_weeks"]
            ),
        }
        for roster_id, values in totals.items()
        # Zero opponent-weeks -> no row: an average over zero weeks is
        # undefined, not 0.0. This is where a bye-only roster drops out.
        if values["opponent_weeks"] > 0
    ]

    # Every roster may have been dropped (e.g. a frame of byes only): return an
    # empty, correctly-shaped frame rather than letting pd.DataFrame([]) build
    # a columnless frame.
    if not rows:
        return pd.DataFrame(columns=STRENGTH_OF_SCHEDULE_COLUMNS)

    result = pd.DataFrame(rows)
    result = result.sort_values(
        by=["avg_opponent_win_pct", "roster_id"], ascending=[False, True]
    ).reset_index(drop=True)

    # Rank 1 = toughest schedule on both columns, ranked independently of each
    # other and of the row order -- see the module docstring's "Ranking rule".
    result["sos_rank"] = _competition_ranks(list(result["avg_opponent_win_pct"]))
    result["all_play_sos_rank"] = _competition_ranks(
        list(result["avg_opponent_all_play_win_pct"])
    )

    # ``owner`` is assigned as its own explicit ``dtype=object`` Series rather
    # than as a plain dict value inside ``rows``: pandas' newer default
    # string-dtype inference otherwise upcasts a column mixing real owner
    # names with ``None`` into a string dtype that silently turns ``None``
    # into ``NaN``, breaking the documented "unresolved owner -> ``None``"
    # contract (see ``head_to_head.py``/``schedule_luck.py``'s identical note).
    result["owner"] = pd.Series(
        [owner_by_roster.get(roster_id) for roster_id in result["roster_id"]],
        dtype=object,
    )
    return result[STRENGTH_OF_SCHEDULE_COLUMNS]
