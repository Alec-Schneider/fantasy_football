"""Manager lineup-tendency analytics from the player-week fact table (FFA-070).

Consumes FFA-064's
:func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`
output (``PLAYER_WEEK_COLUMNS``-shaped, with provider raw-stat columns and a
``fantasy_points`` column) plus FFA-067's
:mod:`fantasy_analyzer.players.lineup_efficiency` and, for FLEX usage, the
league's ``roster_positions`` slot list, and answers a different question
than either: not "how much did a team score" (``position_strength.py``) or
"how efficient was a lineup" (``lineup_efficiency.py``), but "what did this
manager's roster-construction and start/sit *habits* look like across a
season" -- which positions they stockpiled, which they benched, which
position soaked up their FLEX slots, and how often their actual lineup
deviated from the efficiency-optimal one.

This module performs no network access; it operates entirely on an
already-built ``player_week_df`` (plus ``roster_positions`` for the two
functions that need slot structure) and defines **five** of the ticket's six
metrics as new, small aggregations or thin compositions on top of FFA-067.
The sixth, waiver-player utilization, is deliberately **out of scope** -- see
"Waiver-player utilization: scoped out" below.

Shared grouping convention: ``(season, fantasy_team, position)``
-----------------------------------------------------------------------

Like ``position_strength.py``.

Every frame below (except :func:`build_start_sit_tendency_metrics`, which is
per-``(season, roster_id)`` because it is a thin wrapper over FFA-067's own
grain) groups by ``fantasy_team`` -- read directly from
``player_week_df``'s own resolved column, exactly as ``position_strength.py``
does and for the identical reason: a manager's *tendencies* are a
team-identity question, not a roster-id bookkeeping one. A row whose
``season``, ``fantasy_team``, or ``position`` is missing/null cannot be
assigned to any group and is skipped entirely from every function in this
module, the same rule ``position_strength.py`` documents. Seasons are never
pooled (every grouping key includes ``season``); a multi-season
``player_week_df`` produces separate rows per season, and a caller wanting a
multi-season view must pre-aggregate.

``started`` / ``bench`` resolution: ``started`` wins ties
------------------------------------------------------------

FFA-064's contract makes ``started`` and ``bench`` exact complements, but
this module (like ``lineup_efficiency.py``) defensively handles a
hand-built row where that invariant does not hold: a row counts as
*started* if ``bool(started)`` is true, and as *benched* otherwise --
including the not-expected case of both ``started`` and ``bench`` being
``True`` (started wins) or both ``False`` (treated as benched, matching
``lineup_efficiency.py``'s identical rule). A row can therefore never be
double-counted as both.

1. Roster construction -- :func:`build_roster_construction_metrics`
---------------------------------------------------------------------

**Definition.** One row per ``(season, fantasy_team, position)`` present in
the input, with:

- ``distinct_players`` -- the count of distinct ``sleeper_player_id`` values
  the team rostered at that position that season, started or benched, with
  no "qualifying game" filter (unlike ``position_strength.py``'s
  ``positional_depth``): a rostered player who never played still
  represents a real roster-construction decision (a stash, a handcuff, an
  IR body), which is exactly what this metric describes. A row with a
  missing ``sleeper_player_id`` (not expected under FFA-064's contract)
  contributes to ``rostered_player_weeks`` below but not to
  ``distinct_players``, defensively.
- ``rostered_player_weeks`` -- the total count of player-week rows (started
  plus benched) the team had at that position that season -- the volume
  counterpart to ``distinct_players``: two players rostered for one week
  each and one player rostered for two weeks both give
  ``rostered_player_weeks == 2``, but the former gives
  ``distinct_players == 2`` and the latter ``1``.
- ``roster_share`` -- ``rostered_player_weeks`` divided by the team-season's
  total ``rostered_player_weeks`` across every position row this function
  emits (i.e. across every position the team ever rostered a player at that
  season). Because a row only exists when ``rostered_player_weeks >= 1``
  (see below), the shared denominator is always positive for any team-season
  with at least one row, so this column is never ``NaN`` here.

A ``(season, fantasy_team, position)`` group with zero rostered player-weeks
gets no row at all (there is nothing to report); every group that does
appear therefore has ``rostered_player_weeks >= 1``.

Toy example (hand-checked, see the test module): Team Alpha, 2025, rosters
RB1 for weeks 1-2 and RB2 for week 1 only (``RB``: 3 player-weeks, 2 distinct
players) and WR1 for weeks 1-2 (``WR``: 2 player-weeks, 1 distinct player).
``roster_share`` for RB = 3/5 = 0.6, for WR = 2/5 = 0.4.

2. Bench allocation -- :func:`build_bench_allocation_metrics`
-----------------------------------------------------------------

**Definition.** One row per ``(season, fantasy_team, position)`` with **at
least one benched player-week** that season, with:

- ``bench_weeks`` -- the count of benched (``started`` false, per the
  resolution rule above) player-week rows at that position.
- ``bench_share`` -- ``bench_weeks`` divided by the team-season's total
  ``bench_weeks`` across every position row this function emits. As with
  ``roster_share`` above, a row only exists when its own ``bench_weeks >=
  1``, so the denominator is always positive and this column is never
  ``NaN`` here.

A ``(season, fantasy_team, position)`` with zero benched weeks (every
rostered week at that position was started) gets no row -- the identical
"a distribution over zero observations is undefined, not empty-but-real"
convention ``position_strength.py`` uses for started weeks, applied here to
benched weeks. This means a position a manager always started and never
benched is legitimately absent from this frame, which is itself a finding
(no bench allocation to report), not a gap.

3. FLEX usage -- :func:`build_flex_usage_metrics`
------------------------------------------------------

**The question.** Which position most often filled a FLEX-*type* slot
(``FLEX``, ``SUPER_FLEX``, ``REC_FLEX``, ``WRRB_FLEX`` -- FFA-067's
:data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`)
for a manager, over a season? This is asked of the manager's **actual**
lineup, not the efficiency-optimal one (contrast with
:func:`build_start_sit_tendency_metrics` below, which is explicitly about
the optimal lineup): FLEX usage describes what a manager actually did with
their FLEX slots, which is a real, observable habit, independent of whether
those choices were the best available that week.

**Why this cannot reuse FFA-067's per-slot assignment.**
``player_week_df`` records only ``started``/``bench`` per player, never
which *named slot* (``QB`` vs ``FLEX`` vs ``SUPER_FLEX``) a started player
occupied -- see FFA-064's own docstring, which explicitly does not carry
per-player slot labels. FFA-067's optimizer assigns players to slots, but
only to solve for the *best* lineup; it has no concept of "the slot this
already-started player actually sat in." Reusing it here would mean solving
a different optimization problem (assign the *actual* started set to slots)
that FFA-067 does not expose and that is unnecessary for this question, for
the reason below.

**The closed-form alternative used here.** Because every non-FLEX starting
slot in :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
is dedicated to exactly one position (``QB`` -> 1 slot, ``RB`` -> 2 slots,
etc.), a team's *actual* legal lineup (Sleeper enforces slot legality when a
manager sets it, so the observed ``started`` set for a real league is always
assignable to ``roster_positions``) can start more players at a position
than that position has dedicated slots for **only** by using FLEX-type slot
capacity. So, for one roster-week:

```text
flex_starts(position) = max(0, started_count(position) - fixed_slot_count(position))
```

summed across the position's weeks in a season, where ``fixed_slot_count``
counts only the single-position slots (``QB``, ``RB``, ``WR``, ``TE``,
``K``, ``DEF`` labels), never a FLEX-type slot -- both derived once from
``roster_positions`` via
:data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`.
This attributes flex usage to a position without needing to know *which*
named FLEX-type slot (if a league has more than one) absorbed it, which the
ticket's question does not ask for either. Only positions eligible for at
least one FLEX-type slot in this league (per the same eligibility table) are
ever considered -- a position that cannot legally fill any FLEX-type slot
(``K``/``DEF`` under the recognized slot vocabulary) can never accrue
``flex_starts``, matching the eligibility rules FFA-067 already documents.

**Definition.** One row per ``(season, fantasy_team, position)`` with
``flex_starts > 0`` that season, with:

- ``flex_starts`` -- the season sum of the per-week excess above.
- ``flex_start_share`` -- ``flex_starts`` divided by the team-season's total
  ``flex_starts`` across every position row this function emits. Never
  ``NaN`` here for the same reason as ``roster_share`` above (a row only
  exists with a positive numerator, so the shared denominator is always
  positive).
- ``flex_usage_rank`` -- standard competition ("1224") ranking of
  ``flex_starts`` within the ``(season, fantasy_team)`` group, descending
  (rank 1 = the position that most often filled a FLEX-type slot for that
  manager that season) -- the identical convention
  ``position_strength.py``'s ``positional_rank`` uses, applied within one
  team's own positions instead of across teams. Ties share a rank and the
  next distinct rank skips the tied count; the tie-break for row ordering
  (not rank value) is alphabetical by ``position`` label, for
  determinism.

**No clamp against total FLEX-type slot capacity.** A real, Sleeper-enforced
lineup cannot have its summed excess exceed the league's total FLEX-type
slot count, but this module does not verify or clamp against that: it
reports the excess exactly as computed from the observed ``started`` counts.
A hand-built ``player_week_df`` describing an illegal lineup (more players
started at a position than any legal assignment could accommodate) will
silently over-report ``flex_starts`` rather than raising -- a documented
limitation, not a validation gap this module is responsible for closing
(``lineup_efficiency.py`` is the module that reasons about legality).

**No FLEX-type slots in this league.** If ``roster_positions`` contains no
FLEX-type slot at all (every recognized slot is single-position, or there
are no recognized starting slots), no position is ever FLEX-eligible and
this function returns an empty frame regardless of ``player_week_df`` --
there is nothing to attribute.

Toy example (hand-checked, see the test module): a two-RB, one-FLEX league
(``["RB", "RB", "FLEX", "BN"]``; ``FLEX`` accepts ``RB``/``WR``/``TE``, so
``RB``, ``WR``, and ``TE`` are all FLEX-eligible, with ``fixed_slot_count``
2 for ``RB`` and 0 for ``WR``/``TE``). Team Alpha starts 3 RBs and 0
WR/TE in week 1 (``RB`` excess = 3 - 2 = 1) and 2 RBs plus 1 WR in week 2
(``RB`` excess = 0, ``WR`` excess = 1 - 0 = 1). Season: ``RB`` flex_starts
= 1, ``WR`` flex_starts = 1 -- tied at rank 1, ``flex_start_share`` = 0.5
each.

4. Start/sit tendencies -- :func:`build_start_sit_tendency_metrics`
-------------------------------------------------------------------------

**Definition.** This function defines **no new arithmetic**: it is a thin
wrapper over FFA-067's
:func:`~fantasy_analyzer.players.lineup_efficiency.build_roster_efficiency_metrics`
(the same per-``(season, roster_id)`` season table
:data:`~fantasy_analyzer.players.lineup_efficiency.ROSTER_EFFICIENCY_COLUMNS`
already computes, unchanged) plus two derived *rate* columns computed from
that frame's own already-defined totals:

- ``suboptimal_starts_per_week`` = ``total_suboptimal_starts /
  weeks_played``
- ``suboptimal_sits_per_week`` = ``total_suboptimal_sits / weeks_played``

Both are ``NaN`` only when ``weeks_played == 0``, which cannot occur for a
row FFA-067 emits (a season row only exists for a roster with at least one
weekly row, so ``weeks_played >= 1`` always), so in practice these columns
are always defined for every row this function returns.

This function deliberately does **not** attempt to break "wrong start" /
"wrong sit" counts down by position. FFA-067's optimizer reports
*aggregate* wrong-start/wrong-sit counts per roster-week
(:data:`~fantasy_analyzer.players.lineup_efficiency.LINEUP_EFFICIENCY_COLUMNS`'s
``suboptimal_starts``/``suboptimal_sits``) but not *which position* each
wrong decision belongs to -- that information is internal to
``_optimal_lineup``'s count-vector search and is not part of its public
return value. Reconstructing a per-position breakdown would mean re-deriving
which specific players the optimizer's chosen count vector selected at each
position for every roster-week, which is a materially larger extension of
FFA-067's public surface than this ticket's "how often a manager's actual
lineup differs from the efficiency-optimal one" asks for; the frequency
question is fully answered at the roster-week grain the wrapped function
already provides. A future ticket wanting position-level wrong-start/wrong-
sit attribution would need FFA-067 itself extended to expose the optimizer's
per-position selections, not a new module built on top of its current
public output.

``roster_id``, not ``fantasy_team``, is this function's grouping key
(inherited unchanged from ``build_roster_efficiency_metrics``) -- the one
function in this module that does not follow the shared
``(season, fantasy_team, position)`` convention above, because it wraps a
function whose own grain is ``(season, roster_id)`` and this module does not
re-key it.

5. Positional preferences -- :func:`build_positional_preference_metrics`
------------------------------------------------------------------------------

**Definition.** A **rollup**, not an independent metric: one row per
``(season, fantasy_team, position)`` combining the same three underlying
signals :func:`build_roster_construction_metrics` and
:func:`build_bench_allocation_metrics` already define
(``distinct_players``, ``rostered_player_weeks``, ``roster_share``,
``bench_weeks``, ``bench_share``) with one further signal computed the same
way -- a count of *started* player-weeks and its team-season share
(``started_weeks``, ``start_share``) -- so that one row shows how a manager
treated a position across roster construction, starting, and benching
together. This is computed by one shared internal accumulation
(:func:`_accumulate_position_counts`) rather than by calling and
outer-joining the three standalone functions, so that the row universe is
guaranteed complete (the union of every position ever rostered, started, or
benched for the team-season) and every share's denominator is computed
once, consistently, rather than risking a mismatched merge; the standalone
functions are separately built on the identical accumulation for the same
reason.

Columns, for a row present whenever the team rostered at least one
player-week at that position that season (the same "row exists" rule as
:func:`build_roster_construction_metrics`, since this function's row
universe is a superset of that function's):

- ``distinct_players``, ``rostered_player_weeks``, ``roster_share`` --
  identical definitions to :func:`build_roster_construction_metrics`.
- ``started_weeks`` -- the count of started player-week rows at that
  position that season.
- ``start_share`` -- ``started_weeks`` divided by the team-season's total
  ``started_weeks`` across every position this function emits. ``NaN`` only
  when the team-season's total started weeks across every position is
  ``<= 0`` (an entire team-season with no started rows at all, e.g. an
  all-bench synthetic input) -- unlike ``roster_share``, this column's row
  universe is **not** restricted to positions with a positive numerator (a
  position the team rostered but never started legitimately gets
  ``started_weeks == 0``, ``start_share == 0.0``), so the "always positive
  denominator" argument used elsewhere in this module does not apply and the
  guard is real, not defensive-only.
- ``bench_weeks``, ``bench_share`` -- identical definitions to
  :func:`build_bench_allocation_metrics`, but (unlike that function's own
  output) present for **every** row this function emits, including a
  position the team started every week and never benched
  (``bench_weeks == 0``, ``bench_share == 0.0``). ``bench_share`` is
  ``NaN`` only when the team-season's total benched weeks across every
  position is ``<= 0`` (the team never benched anyone all season at any
  position), for the identical reason as ``start_share``.

Waiver-player utilization: scoped out
-----------------------------------------

The ticket's sixth "Analyze" bullet, waiver-player utilization, asks how
much a manager relied on waiver-wire adds versus drafted players. That
requires knowing each rostered player's **acquisition method**
(draft / waiver / free agent / trade), which is not present anywhere in
``player_week_df`` or any other normalized dataset in this codebase.
Investigation before implementing this module found:

- :meth:`~fantasy_analyzer.sleeper.client.SleeperClient.get_transactions`
  exists (``GET league/{league_id}/transactions/{week}``) and is tested
  against ``tests/fixtures/sleeper/transactions.json``, but nothing
  normalizes its output anywhere in ``src/`` -- a repo-wide search for
  "transaction" outside ``sleeper/client.py`` and its own test/fixture finds
  nothing.
- Building a usable "acquisition method per rostered player-week" dataset
  from that raw endpoint is **not** a small addition on top of this
  analytics ticket. It requires: fetching transactions for every week of a
  season (one HTTP call per week, unlike the single-shot endpoints this
  package's other data-access modules wrap), reconciling ``adds``/``drops``
  entries of three different transaction ``type``s (``waiver``,
  ``free_agent``, ``trade``) against roster history over time, resolving
  what happened at the draft itself (a player never appearing in any
  transaction was presumably drafted or already rostered -- which needs
  :meth:`~fantasy_analyzer.sleeper.client.SleeperClient.get_draft_picks` as
  a second new data source), deciding a caching strategy for a genuinely
  new, non-trivial dataset, and designing its canonical schema. That is
  exactly the kind of "new Sleeper endpoint client, caching, new canonical
  dataset" work AGENTS.md assigns to the Software Engineer / Data Engineer
  roles as its own ticket-sized unit, not a Data Scientist analytics
  composition on top of already-normalized data -- the pattern every other
  function in this module (and every sibling FFA-06x module) follows.

Per AGENTS.md's explicit instruction not to silently expand a ticket into
unrelated features, and its "make the smallest reasonable adjustment and
document it" guidance when a ticket cannot be implemented exactly as
written: this module implements the other five metrics in full and leaves
waiver-player utilization undone. A follow-up ticket (a natural "FFA-073" or
similar, not created here) would need, at minimum: a normalized
``waiver_transactions_df`` (owned by a Data/Software Engineer role, per
AGENTS.md's role split) built from
:meth:`~fantasy_analyzer.sleeper.client.SleeperClient.get_transactions`
across a season's weeks plus
:meth:`~fantasy_analyzer.sleeper.client.SleeperClient.get_draft_picks`,
before a Data Scientist ticket like this one could compose a
"waiver-add-vs-drafted production" analysis on top of it, mirroring exactly
how this module composes on top of FFA-064's already-normalized fact table.

Regular season vs. playoffs: every function here is phase-agnostic
------------------------------------------------------------------------

``player_week_df`` (FFA-064's output) has no ``is_playoff`` column -- the
identical situation ``position_strength.py`` and ``lineup_efficiency.py``
document -- so no function in this module makes a phase distinction of its
own: every week present in the input for a team-position (or roster,
for :func:`build_start_sit_tendency_metrics`) enters the same aggregation,
regular season and playoff weeks alike. A caller wanting a phase-specific
view must pre-filter ``player_week_df`` on ``week`` against the calling
league's playoff-start boundary (FFA-022,
``LeagueSettings.playoff_week_start``) **before** calling any function in
this module -- the same caller-filters-first pattern every FFA-06x module in
this package documents. A manager's playoff-only tendencies (a much smaller
sample -- typically 1-3 weeks) are a distinct, real question a caller can
ask by filtering first; this module does not answer it by default.

Missing values / edge cases
----------------------------

- **Empty ``player_week_df``**: every function returns an empty DataFrame
  with its own documented columns.
- **A row with missing ``season``/``fantasy_team``/``position``**: skipped
  from every function, per "Shared grouping convention" above.
- **A row with missing ``sleeper_player_id``**: contributes to
  ``rostered_player_weeks``/``started_weeks``/``bench_weeks`` counts
  (which need only ``started``) but not to ``distinct_players`` -- not
  expected under FFA-064's contract, handled defensively.
- **``roster_positions`` with no recognized starting slots at all** (every
  label unrecognized, or the list is empty): :func:`build_flex_usage_metrics`
  returns an empty frame (no FLEX-eligible positions exist);
  :func:`build_start_sit_tendency_metrics` inherits FFA-067's own
  "``optimal_points`` is always ``0.0``" degenerate behavior unchanged.
- **Multiple seasons in one ``player_week_df``**: grouped separately (every
  key includes ``season``), never pooled -- the identical convention every
  sibling module documents.

Column dtypes
--------------

``season`` is plain ``int64`` in every frame. Count columns
(``distinct_players``, ``rostered_player_weeks``, ``bench_weeks``,
``flex_starts``, ``flex_usage_rank``, ``started_weeks``) are plain
``int64``. Share columns (``roster_share``, ``bench_share``,
``flex_start_share``, ``start_share``, ``suboptimal_starts_per_week``,
``suboptimal_sits_per_week``) are ``float64`` with undefined values as
``NaN``. ``fantasy_team`` and ``position`` are ``object`` (may legitimately
be ``None`` where FFA-064 itself could not resolve them). Test undefined
values with ``pd.isna``, not ``is None``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from fantasy_analyzer.players.lineup_efficiency import (
    START_SLOT_ELIGIBILITY,
    build_roster_efficiency_metrics,
)

#: Column order for :func:`build_roster_construction_metrics`.
ROSTER_CONSTRUCTION_COLUMNS = [
    "season",
    "fantasy_team",
    "position",
    "distinct_players",
    "rostered_player_weeks",
    "roster_share",
]

#: Column order for :func:`build_bench_allocation_metrics`.
BENCH_ALLOCATION_COLUMNS = [
    "season",
    "fantasy_team",
    "position",
    "bench_weeks",
    "bench_share",
]

#: Column order for :func:`build_flex_usage_metrics`.
FLEX_USAGE_COLUMNS = [
    "season",
    "fantasy_team",
    "position",
    "flex_starts",
    "flex_start_share",
    "flex_usage_rank",
]

#: Column order for :func:`build_start_sit_tendency_metrics` -- FFA-067's
#: ``ROSTER_EFFICIENCY_COLUMNS`` plus two derived rate columns.
START_SIT_TENDENCY_COLUMNS = [
    "season",
    "roster_id",
    "fantasy_team",
    "weeks_played",
    "total_actual_points",
    "total_optimal_points",
    "total_bench_points",
    "total_points_left_on_bench",
    "efficiency_pct",
    "suboptimal_weeks",
    "suboptimal_week_pct",
    "total_suboptimal_starts",
    "total_suboptimal_sits",
    "suboptimal_starts_per_week",
    "suboptimal_sits_per_week",
]

#: Column order for :func:`build_positional_preference_metrics`.
POSITIONAL_PREFERENCE_COLUMNS = [
    "season",
    "fantasy_team",
    "position",
    "distinct_players",
    "rostered_player_weeks",
    "roster_share",
    "started_weeks",
    "start_share",
    "bench_weeks",
    "bench_share",
]


def _accumulate_position_counts(
    player_week_df: pd.DataFrame,
) -> dict[tuple[int, Any, Any], dict[str, Any]]:
    """Fold ``player_week_df`` into per-``(season, fantasy_team, position)`` counts.

    Shared by :func:`build_roster_construction_metrics`,
    :func:`build_bench_allocation_metrics`, and
    :func:`build_positional_preference_metrics` -- see the module
    docstring's "Positional preferences" section for why one accumulation is
    used instead of three independent passes. Returns a dict keyed by
    ``(season, fantasy_team, position)`` with ``started_weeks`` (int),
    ``bench_weeks`` (int), and ``distinct_players`` (set) accumulators. Rows
    with a missing ``season``/``fantasy_team``/``position`` are skipped
    entirely (see "Shared grouping convention").
    """
    counts: dict[tuple[int, Any, Any], dict[str, Any]] = {}
    for row in player_week_df.itertuples(index=False):
        season = getattr(row, "season", None)
        fantasy_team = getattr(row, "fantasy_team", None)
        position = getattr(row, "position", None)
        if pd.isna(season) or pd.isna(fantasy_team) or pd.isna(position):
            continue

        key = (int(season), fantasy_team, position)
        bucket = counts.setdefault(
            key, {"started_weeks": 0, "bench_weeks": 0, "distinct_players": set()}
        )

        started = bool(getattr(row, "started", False))
        if started:
            bucket["started_weeks"] += 1
        else:
            bucket["bench_weeks"] += 1

        player_id = getattr(row, "sleeper_player_id", None)
        if pd.notna(player_id):
            bucket["distinct_players"].add(player_id)

    return counts


def _team_totals(
    counts: dict[tuple[int, Any, Any], dict[str, Any]], field: str
) -> dict[tuple[int, Any], float]:
    """Sum one accumulator ``field`` across positions, per ``(season, fantasy_team)``.
    """
    totals: dict[tuple[int, Any], float] = {}
    for (season, fantasy_team, _position), bucket in counts.items():
        team_key = (season, fantasy_team)
        totals[team_key] = totals.get(team_key, 0) + bucket[field]
    return totals


def _sort_rows(rows: list[dict]) -> list[dict]:
    """Sort by ascending ``season``, then ``fantasy_team``, then ``position``."""
    rows.sort(
        key=lambda row: (row["season"], str(row["fantasy_team"]), str(row["position"]))
    )
    return rows


def _label_columns_as_object(result: pd.DataFrame) -> pd.DataFrame:
    """Assign ``fantasy_team``/``position`` as explicit object-dtype Series.

    Mirrors ``position_strength.py``'s and ``lineup_efficiency.py``'s
    identical handling: pandas' string-dtype inference would otherwise
    upcast a column mixing real labels with ``None`` into a dtype that
    silently turns ``None`` into ``NaN``.
    """
    for column in ("fantasy_team", "position"):
        if column in result.columns:
            result[column] = pd.Series(result[column].tolist(), dtype=object)
    return result


def build_roster_construction_metrics(player_week_df: pd.DataFrame) -> pd.DataFrame:
    """Build one row per ``(season, fantasy_team, position)`` of roster construction.

    How many distinct players, and how many total rostered player-weeks, a
    manager carried at each position that season, and each position's share
    of the team's total rostered player-weeks. See the module docstring's
    "Roster construction" section for the exact definitions.

    Args:
        player_week_df: A
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            DataFrame, as produced by
            :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`.
            This function is phase-agnostic; filter on ``week`` against a
            league's playoff-start boundary before calling for a
            phase-specific view.

    Returns:
        A DataFrame with columns :data:`ROSTER_CONSTRUCTION_COLUMNS`, one row
        per ``(season, fantasy_team, position)`` with at least one rostered
        player-week in the input, sorted by ascending ``season``, then
        ``fantasy_team``, then ``position``. Returns an empty DataFrame with
        the expected columns if the input is empty or every row is
        ungroupable.
    """
    if player_week_df.empty:
        return pd.DataFrame(columns=ROSTER_CONSTRUCTION_COLUMNS)

    counts = _accumulate_position_counts(player_week_df)
    if not counts:
        return pd.DataFrame(columns=ROSTER_CONSTRUCTION_COLUMNS)

    for bucket in counts.values():
        bucket["rostered_player_weeks"] = (
            bucket["started_weeks"] + bucket["bench_weeks"]
        )
    team_totals = _team_totals(counts, "rostered_player_weeks")

    rows: list[dict] = []
    for (season, fantasy_team, position), bucket in counts.items():
        rostered_player_weeks = bucket["rostered_player_weeks"]
        team_total = team_totals[(season, fantasy_team)]
        rows.append(
            {
                "season": season,
                "fantasy_team": fantasy_team,
                "position": position,
                "distinct_players": len(bucket["distinct_players"]),
                "rostered_player_weeks": rostered_player_weeks,
                "roster_share": (
                    rostered_player_weeks / team_total
                    if team_total > 0
                    else float("nan")
                ),
            }
        )

    rows = _sort_rows(rows)
    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["distinct_players"] = result["distinct_players"].astype(int)
    result["rostered_player_weeks"] = result["rostered_player_weeks"].astype(int)
    result["roster_share"] = result["roster_share"].astype(float)
    result = _label_columns_as_object(result)
    return result[ROSTER_CONSTRUCTION_COLUMNS]


def build_bench_allocation_metrics(player_week_df: pd.DataFrame) -> pd.DataFrame:
    """Build one row per ``(season, fantasy_team, position)`` of bench allocation.

    How many benched player-weeks a manager accumulated at each position
    that season, and each position's share of the team's total benched
    player-weeks. See the module docstring's "Bench allocation" section for
    the exact definitions, including why a position never benched gets no
    row.

    Args:
        player_week_df: Same input contract as
            :func:`build_roster_construction_metrics`.

    Returns:
        A DataFrame with columns :data:`BENCH_ALLOCATION_COLUMNS`, one row
        per ``(season, fantasy_team, position)`` with at least one benched
        player-week in the input, sorted by ascending ``season``, then
        ``fantasy_team``, then ``position``. Returns an empty DataFrame with
        the expected columns if the input is empty, every row is
        ungroupable, or no team ever benched anyone.
    """
    if player_week_df.empty:
        return pd.DataFrame(columns=BENCH_ALLOCATION_COLUMNS)

    counts = _accumulate_position_counts(player_week_df)
    bench_only = {
        key: bucket for key, bucket in counts.items() if bucket["bench_weeks"] > 0
    }
    if not bench_only:
        return pd.DataFrame(columns=BENCH_ALLOCATION_COLUMNS)

    team_totals = _team_totals(bench_only, "bench_weeks")

    rows: list[dict] = []
    for (season, fantasy_team, position), bucket in bench_only.items():
        team_total = team_totals[(season, fantasy_team)]
        rows.append(
            {
                "season": season,
                "fantasy_team": fantasy_team,
                "position": position,
                "bench_weeks": bucket["bench_weeks"],
                "bench_share": (
                    bucket["bench_weeks"] / team_total
                    if team_total > 0
                    else float("nan")
                ),
            }
        )

    rows = _sort_rows(rows)
    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["bench_weeks"] = result["bench_weeks"].astype(int)
    result["bench_share"] = result["bench_share"].astype(float)
    result = _label_columns_as_object(result)
    return result[BENCH_ALLOCATION_COLUMNS]


def _flex_eligibility(
    roster_positions: list[str],
) -> tuple[dict[str, int], set[str]]:
    """Derive fixed single-position slot counts and FLEX-eligible positions.

    See the module docstring's "FLEX usage" section for the closed-form
    reasoning. ``fixed_slot_counts[position]`` counts only slots dedicated
    to exactly one position; ``flex_eligible_positions`` is every position
    that appears in any *multi*-position slot's eligible set.
    """
    fixed_slot_counts: dict[str, int] = {}
    flex_eligible_positions: set[str] = set()

    for slot in roster_positions or []:
        eligible = START_SLOT_ELIGIBILITY.get(slot)
        if eligible is None:
            continue
        if len(eligible) == 1:
            position = eligible[0]
            fixed_slot_counts[position] = fixed_slot_counts.get(position, 0) + 1
        else:
            flex_eligible_positions.update(eligible)

    return fixed_slot_counts, flex_eligible_positions


def build_flex_usage_metrics(
    player_week_df: pd.DataFrame, roster_positions: list[str]
) -> pd.DataFrame:
    """Build one row per ``(season, fantasy_team, position)`` of FLEX-slot usage.

    Which position most often filled a FLEX-type slot (``FLEX``,
    ``SUPER_FLEX``, ``REC_FLEX``, ``WRRB_FLEX``) in a manager's **actual**
    lineup, over a season -- computed from the excess of started players at
    a position beyond that position's dedicated single-position slots. See
    the module docstring's "FLEX usage" section for the exact formula, why
    it does not (and does not need to) reuse FFA-067's slot optimizer, and
    its edge cases.

    Args:
        player_week_df: Same input contract as
            :func:`build_roster_construction_metrics`.
        roster_positions: The league's ordered roster-slot list, e.g.
            ``LeagueSnapshot.roster_positions``. Recognized starting slots
            and their eligible positions are
            :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`;
            any other label (including ``BN``/``IR``) contributes nothing.

    Returns:
        A DataFrame with columns :data:`FLEX_USAGE_COLUMNS`, one row per
        ``(season, fantasy_team, position)`` with ``flex_starts > 0``,
        sorted by ascending ``season``, then ``fantasy_team``, then
        ``position``. Returns an empty DataFrame with the expected columns
        if the input is empty, no position in this league is FLEX-eligible,
        or no team ever exceeded a position's dedicated slot count.
    """
    if player_week_df.empty:
        return pd.DataFrame(columns=FLEX_USAGE_COLUMNS)

    fixed_slot_counts, flex_eligible_positions = _flex_eligibility(roster_positions)
    if not flex_eligible_positions:
        return pd.DataFrame(columns=FLEX_USAGE_COLUMNS)

    # weekly_started_counts[(season, fantasy_team, week, position)] = number
    # of started rows sharing that key.
    weekly_started_counts: dict[tuple, int] = {}
    for row in player_week_df.itertuples(index=False):
        season = getattr(row, "season", None)
        fantasy_team = getattr(row, "fantasy_team", None)
        position = getattr(row, "position", None)
        week = getattr(row, "week", None)
        if (
            pd.isna(season)
            or pd.isna(fantasy_team)
            or pd.isna(position)
            or pd.isna(week)
        ):
            continue
        if position not in flex_eligible_positions:
            continue
        if not bool(getattr(row, "started", False)):
            continue

        key = (int(season), fantasy_team, week, position)
        weekly_started_counts[key] = weekly_started_counts.get(key, 0) + 1

    season_totals: dict[tuple[int, Any, Any], int] = {}
    for (season, fantasy_team, _week, position), count in weekly_started_counts.items():
        excess = max(0, count - fixed_slot_counts.get(position, 0))
        if excess <= 0:
            continue
        key = (season, fantasy_team, position)
        season_totals[key] = season_totals.get(key, 0) + excess

    if not season_totals:
        return pd.DataFrame(columns=FLEX_USAGE_COLUMNS)

    team_totals: dict[tuple[int, Any], int] = {}
    for (season, fantasy_team, _position), flex_starts in season_totals.items():
        team_key = (season, fantasy_team)
        team_totals[team_key] = team_totals.get(team_key, 0) + flex_starts

    rows: list[dict] = []
    for (season, fantasy_team, position), flex_starts in season_totals.items():
        team_total = team_totals[(season, fantasy_team)]
        rows.append(
            {
                "season": season,
                "fantasy_team": fantasy_team,
                "position": position,
                "flex_starts": flex_starts,
                "flex_start_share": (
                    flex_starts / team_total if team_total > 0 else float("nan")
                ),
            }
        )

    _assign_flex_usage_ranks(rows)

    rows = _sort_rows(rows)
    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["flex_starts"] = result["flex_starts"].astype(int)
    result["flex_start_share"] = result["flex_start_share"].astype(float)
    result["flex_usage_rank"] = result["flex_usage_rank"].astype(int)
    result = _label_columns_as_object(result)
    return result[FLEX_USAGE_COLUMNS]


def _assign_flex_usage_ranks(rows: list[dict]) -> None:
    """Assign ``flex_usage_rank`` in place within each ``(season, fantasy_team)`` group.

    Standard competition ("1224") ranking by descending ``flex_starts`` --
    see the module docstring's "FLEX usage" section.
    """
    groups: dict[tuple[int, Any], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["season"], row["fantasy_team"]), []).append(row)

    for group_rows in groups.values():
        ordered = sorted(
            group_rows,
            key=lambda row: (-row["flex_starts"], str(row["position"])),
        )
        current_rank = 0
        previous_flex_starts = None
        for position, row in enumerate(ordered, start=1):
            if row["flex_starts"] != previous_flex_starts:
                current_rank = position
                previous_flex_starts = row["flex_starts"]
            row["flex_usage_rank"] = current_rank


def build_start_sit_tendency_metrics(
    player_week_df: pd.DataFrame, roster_positions: list[str]
) -> pd.DataFrame:
    """Build one row per ``(season, roster_id)`` of start/sit tendency rates.

    Thin wrapper over FFA-067's
    :func:`~fantasy_analyzer.players.lineup_efficiency.build_roster_efficiency_metrics`:
    every column of that frame, unchanged, plus two derived per-week rates,
    ``suboptimal_starts_per_week`` and ``suboptimal_sits_per_week``. See the
    module docstring's "Start/sit tendencies" section for the exact
    definitions and why this does not attempt a per-position breakdown.

    Args:
        player_week_df: Same input contract as
            :func:`~fantasy_analyzer.players.lineup_efficiency.build_roster_efficiency_metrics`
            (unchanged).
        roster_positions: Same input contract as that function.

    Returns:
        A DataFrame with columns :data:`START_SIT_TENDENCY_COLUMNS`, one row
        per ``(season, roster_id)`` present in the input, sorted by
        ascending ``season`` then ``roster_id`` (inherited from the wrapped
        function). Returns an empty DataFrame with the expected columns if
        the input is empty.
    """
    season_df = build_roster_efficiency_metrics(player_week_df, roster_positions)
    if season_df.empty:
        return pd.DataFrame(columns=START_SIT_TENDENCY_COLUMNS)

    result = season_df.copy()
    result["suboptimal_starts_per_week"] = (
        result["total_suboptimal_starts"] / result["weeks_played"]
    ).astype(float)
    result["suboptimal_sits_per_week"] = (
        result["total_suboptimal_sits"] / result["weeks_played"]
    ).astype(float)
    return result[START_SIT_TENDENCY_COLUMNS]


def build_positional_preference_metrics(player_week_df: pd.DataFrame) -> pd.DataFrame:
    """Build one row per ``(season, fantasy_team, position)`` of positional preference.

    A rollup of roster construction, starting, and benching for each
    position a manager rostered that season: how many players, how many
    rostered/started/benched player-weeks, and each one's share of the
    team's season total. See the module docstring's "Positional
    preferences" section for the exact definitions and why this is computed
    as one shared accumulation rather than three separately-merged frames.

    Args:
        player_week_df: Same input contract as
            :func:`build_roster_construction_metrics`.

    Returns:
        A DataFrame with columns :data:`POSITIONAL_PREFERENCE_COLUMNS`, one
        row per ``(season, fantasy_team, position)`` with at least one
        rostered player-week in the input, sorted by ascending ``season``,
        then ``fantasy_team``, then ``position``. Returns an empty DataFrame
        with the expected columns if the input is empty or every row is
        ungroupable.
    """
    if player_week_df.empty:
        return pd.DataFrame(columns=POSITIONAL_PREFERENCE_COLUMNS)

    counts = _accumulate_position_counts(player_week_df)
    if not counts:
        return pd.DataFrame(columns=POSITIONAL_PREFERENCE_COLUMNS)

    for bucket in counts.values():
        bucket["rostered_player_weeks"] = (
            bucket["started_weeks"] + bucket["bench_weeks"]
        )

    roster_totals = _team_totals(counts, "rostered_player_weeks")
    started_totals = _team_totals(counts, "started_weeks")
    bench_totals = _team_totals(counts, "bench_weeks")

    rows: list[dict] = []
    for (season, fantasy_team, position), bucket in counts.items():
        team_key = (season, fantasy_team)
        roster_total = roster_totals[team_key]
        started_total = started_totals[team_key]
        bench_total = bench_totals[team_key]
        rows.append(
            {
                "season": season,
                "fantasy_team": fantasy_team,
                "position": position,
                "distinct_players": len(bucket["distinct_players"]),
                "rostered_player_weeks": bucket["rostered_player_weeks"],
                "roster_share": (
                    bucket["rostered_player_weeks"] / roster_total
                    if roster_total > 0
                    else float("nan")
                ),
                "started_weeks": bucket["started_weeks"],
                "start_share": (
                    bucket["started_weeks"] / started_total
                    if started_total > 0
                    else float("nan")
                ),
                "bench_weeks": bucket["bench_weeks"],
                "bench_share": (
                    bucket["bench_weeks"] / bench_total
                    if bench_total > 0
                    else float("nan")
                ),
            }
        )

    rows = _sort_rows(rows)
    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["distinct_players"] = result["distinct_players"].astype(int)
    result["rostered_player_weeks"] = result["rostered_player_weeks"].astype(int)
    result["started_weeks"] = result["started_weeks"].astype(int)
    result["bench_weeks"] = result["bench_weeks"].astype(int)
    for column in ("roster_share", "start_share", "bench_share"):
        result[column] = result[column].astype(float)
    result = _label_columns_as_object(result)
    return result[POSITIONAL_PREFERENCE_COLUMNS]
