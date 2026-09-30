"""Which free agent actually improves *your* lineup, and who to drop (FFA-100).

:mod:`fantasy_analyzer.players.waiver_rankings` answers a league-level
question: who are the most valuable unrostered players, measured against
the league's replacement level. That is the right first cut, and it is
also not the question a manager is holding. A manager is holding *"does
this player start for me, and over whom"* -- and the two answers diverge
constantly. A tight end 2.5 points above replacement is a significant add
for a manager starting a replacement-level tight end and worth nothing at
all to the manager who already rosters two better ones.

This module closes that gap by scoring every candidate against the
manager's own roster, in **projection space**:

.. code-block:: text

    starting_ppg_gain = best_lineup(roster + candidate) - best_lineup(roster)

If that is zero, the candidate does not crack the lineup, whatever his
VORP says. If it is positive, the difference names exactly who he
displaces.

Why projection space, not week space
--------------------------------------------------------------------------

:func:`~fantasy_analyzer.players.lineup_efficiency.build_lineup_efficiency_metrics`
(FFA-067) already solves the optimal-lineup problem, but it solves it for
*realized* weeks: it needs a player-week fact table carrying ``started``/
``bench`` flags and actual points, and it answers "how well did this
manager set his lineup". A waiver decision is about weeks that have not
happened, where there are no realized points and no start/sit flags --
only projections. Feeding a synthetic player-week frame into that function
to get at its solver would mean fabricating exactly the columns it treats
as ground truth.

So this module runs the same *algorithm* on different inputs.
:func:`optimal_lineup` reuses FFA-067's
:data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
verbatim -- one source of truth for what a ``FLEX`` accepts, including the
``K`` and ``DEF`` slots -- and solves the identical count-vector problem
over ``projected_ppg``. The tie-breaking differs by necessity (there is no
"was started" to prefer), so it falls back to ``player_id`` ascending,
which keeps the output deterministic.

Team defenses need no special casing. Sleeper identifies a ``DEF`` by its
team code (``"SEA"``) where every other player has a numeric id; ids are
compared as strings throughout, so ``"SEA"`` is simply another id. The
spellings ``"DST"`` and ``"D/ST"`` are read as ``DEF``
(:data:`POSITION_ALIASES`), so a projection source using either drops
straight in.

The drop side
--------------------------------------------------------------------------

An add is only executable if something can be dropped. Each rostered
player gets a **marginal value**:

.. code-block:: text

    marginal_value = best_lineup(roster) - best_lineup(roster - player)

A player whose marginal value is 0.0 is free to drop: removing him does
not change the best lineup the manager can field. That is not the same as
"he is the worst player on the roster" -- a third-string quarterback in a
one-QB league has a marginal value of 0.0 even if his projection is
respectable, while a bye-week-covering fourth receiver may not (see the
next section: over a horizon, covering a bye *is* value). This is the
number that decides a roster move, so it is the number reported.

``best_drop`` is the droppable rostered player with the lowest marginal
value, ties broken toward the lower projection and then ``player_id``. A
rostered player with **no projection** has an unknown value, not a zero
one -- the solve can never start him, so a computed marginal value would
read 0.0 and make him the first drop (measured: a rookie kicker with no ID
crosswalk was offered as the drop for every move). His ``marginal_value``
is ``NaN``, he ranks after every valued player, and he is never
``best_drop``. Applying it gives

.. code-block:: text

    net_lineup_gain = best_lineup(roster - best_drop + candidate)
                      - best_lineup(roster)

which is the honest bottom line for the transaction: it can be lower than
``starting_ppg_gain`` when the only droppable player is himself a starter,
and it is never higher. With an open roster spot (``open_roster_spots >
0``) no drop is needed, ``best_drop`` is ``None`` and the net gain equals
the starting gain.

Availability and the rest-of-season horizon (FFA-107)
--------------------------------------------------------------------------

A lineup is only as good as the players who can take the field. The
availability rule itself -- which injury statuses rule a player out, and
for how many weeks -- lives in :mod:`fantasy_analyzer.players.availability`.
This module consumes it in two forms:

- **One week: an ``available`` column.** :func:`optimal_lineup` never
  starts a row whose ``available`` is ``False``
  (:func:`~fantasy_analyzer.players.availability.add_availability` writes
  it). A frame without the column is fully available -- FFA-100's
  behavior, unchanged.
- **A horizon: ``week`` and ``season_end_week``.**
  :func:`build_drop_candidates` and :func:`build_add_drop_candidates`
  evaluate every week in ``W = [week, max(week, season_end_week)]``,
  reading each player's ``injury_status`` and ``bye_week`` columns (either
  may be absent). ``season_end_week`` omitted means ``W = [week]``. An
  ``available`` column, if present, is read as a statement about ``week``
  and combined with the per-week rule.

A drop is a rest-of-season decision, so it is scored over the horizon, not
the coming week alone. For a set of players ``S``:

.. code-block:: text

    L_w(S) = best_lineup({p in S : p is available in week w})
    ROS(S) = sum over w in W of L_w(S)

Every value or gain column is that quantity's change **divided by**
``|W|``: a mean per remaining week, which keeps it on the per-game scale
FFA-100 reported. Without a horizon (``week=None``) ``|W| = 1`` and every
number is identical to FFA-100's. The undivided figure is reported
alongside (``marginal_value_total``, ``net_lineup_gain_total``), with
``weeks_evaluated = |W|``.

Worked example (hand-checkable; tested). Slots ``["QB", "RB", "FLEX"]``,
``week = 4``, ``season_end_week = 6``. QB1 20.0; RB1 12.0 with status
``Out``; WR1 11.0 with a week-5 bye; RB2 9.0.

- Week 4 (RB1 out): QB1 + RB2 + WR1 = 40.0.
- Week 5 (WR1 on bye): QB1 + RB1 + RB2 = 41.0.
- Week 6 (everyone): QB1 + RB1 + WR1 = 43.0. ``ROS = 124.0``.
- Without RB1: 40.0 / 29.0 / 40.0 = 109.0, so RB1's
  ``marginal_value_total`` is 15.0 and ``marginal_value`` 5.0. A
  coming-week-only solve scores him 0.0 -- he cannot play week 4 -- and
  would have offered him as a free drop. That is the failure this horizon
  exists to prevent.
- RB2, free to drop in a one-week, everyone-healthy solve, covers both the
  week-4 injury and the week-5 bye: his ``marginal_value_total`` is 18.0.

Ties: a player's ``marginal_value`` and a candidate's gains are compared
after rounding to 1e-9, so two genuinely equal values are never split by
floating-point noise; the documented secondary keys then decide.

Streaming-level fill (opt-in)
--------------------------------------------------------------------------

By default a slot the week's lineup cannot fill scores 0.0. That is not
what happens in a real league: when a starter is on bye, the manager
streams someone off the waiver wire. Scoring the hole at zero credits
bench depth with the *whole* of a backup's projection in every week he
covers, when all he is really worth is his margin over the streamer.

Pass ``empty_slot_values`` (position -> per-game points streamable off the
wire, normally each position's replacement level) to
:func:`build_drop_candidates` / :func:`build_add_drop_candidates` and every
slot may instead be streamed at its value. A slot is worth the value of the
**cheapest** position it accepts (:func:`slot_fill_values`): a ``FLEX``
taking RB/WR/TE is filled at ``min(RB, WR, TE)``, the conservative reading.
The lineup solve then maximizes real starters plus streamed slots, so a
rostered player below the streamer is simply not started:

.. code-block:: text

    L_w(S) = max over lineups of  sum(real starters) + sum(streamed slots)

Worked example (hand-checkable; tested). Slots ``["QB", "RB"]``, weeks
4-6, streamable RB 6.0 and QB 10.0. QB1 20.0; RB1 12.0 on bye in week 5;
backup RB2 9.0, who starts only in week 5.

- Without the fill, removing RB2 leaves week 5's RB slot empty: he is
  worth his full 9.0.
- With it, the slot is streamed at 6.0: he is worth ``9.0 - 6.0 = 3.0``.
- A 5.0 backup is worth 5.0 without the fill and 0.0 with it -- the
  streamer is better than he is.

``None`` (the default) runs the original solver and reproduces its output
exactly. Streamed slots count in ``points_per_game`` but are never listed
in ``starters``; a candidate who replaces a streamer displaces nobody.
Ties at nine decimals prefer the lineup with more real starters.

Reserve (IR) slots and open roster spots
--------------------------------------------------------------------------

Sleeper holds IR-slot players in a roster's ``reserve`` list. They are
also in ``players``, but they do not occupy a ``roster_positions`` slot --
a league's ``roster_positions`` never contains its reserve slots (they are
``settings.reserve_slots``). So:

- ``reserve_player_ids`` are **never drop candidates**. Dropping one does
  not free a bench spot, so he cannot "make room" for an add.
- They still **count in the lineup evaluation** for the weeks they are
  available: they are the manager's players, and the week a starter comes
  back from IR genuinely lowers the value of the backup who covered for
  him. Because the IR horizon is a lower bound (see
  :mod:`~fantasy_analyzer.players.availability`), that effect is if
  anything overstated for a season-ending injury -- read a borderline drop
  at his position with that in mind.
- :func:`open_roster_spots` counts capacity the same way: a roster is full
  when its non-reserve, non-taxi players fill ``roster_positions``.

Scope and limits -- read before acting on the output
--------------------------------------------------------------------------

- **Per-week means, not season totals.** Every gain and value is points
  per week, averaged over the horizon. A candidate worth +1.5 is worth
  that per remaining week on average, not once.
- **Availability is a documented rule, not a forecast.** Injury horizons
  are the fixed lengths in
  :data:`~fantasy_analyzer.players.availability.DEFAULT_INJURY_WEEKS_OUT`;
  byes come from whatever ``bye_week`` the caller supplies (typically
  :func:`~fantasy_analyzer.players.opponent_strength.add_matchup_context`).
- **One best drop, not one per candidate.** ``best_drop`` is chosen once
  from the roster and applied to every candidate. A candidate who would be
  better paired with a different drop (say, the backup at his own
  position) is scored against the roster-wide cheapest one -- unless the
  caller asks for ``same_position_drop``, which pairs each candidate with
  the cheapest drop at his own position.
- **An empty slot scores 0.0 unless ``empty_slot_values`` is given**,
  which overstates bench depth as bye coverage -- most visibly at
  ``K``/``DEF``, where a second kicker "covers" a whole week. See
  "Streaming-level fill". ``same_position_drop`` remains the right way to
  score K/DEF moves either way.
- **The streamer is a fixed per-position value**, the same every week; it
  does not model who is actually on the wire in a given week, nor the
  roster move streaming costs.
- **No positional-scarcity or handcuff logic.** Dropping the backup to a
  starting running back is scored purely on projected lineups.
- **No transaction costs**: no FAAB and no waiver priority.
- **The candidate's projection is taken as given**, inheriting every
  limitation of
  :mod:`fantasy_analyzer.players.ros_projection` -- in particular that a
  one-game sample is shrunk but not disbelieved -- and a projection is a
  constant per-game rate across the horizon.

The cost of an exhaustive search
--------------------------------------------------------------------------

:func:`build_add_drop_candidates` evaluates one roster per candidate plus
one per rostered player, and each evaluation spans ``|W|`` weeks. Weeks in
which the same players are available share a single solve -- a roster's
availability changes only on its players' bye and injury weeks, so a
14-week horizon typically needs a handful of distinct solves, not 14 --
and solves are memoized by player set. The function still takes
``max_candidates`` and considers only the best that many by
``projected_ppg``. Pass a pre-filtered, already-ranked frame (the top of a
waiver board) rather than a whole pool.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Mapping, Optional, Sequence

import pandas as pd

from fantasy_analyzer.players.availability import (
    DEFAULT_INJURY_WEEKS_OUT,
    unavailable_weeks,
)
from fantasy_analyzer.players.lineup_efficiency import START_SLOT_ELIGIBILITY

#: The startable positions, in a fixed order so count-vector states are
#: deterministic. Derived from
#: :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
#: rather than restated, so a slot type added there cannot silently leave a
#: position unstartable here.
STARTABLE_POSITIONS = tuple(
    sorted({position for slot in START_SLOT_ELIGIBILITY.values() for position in slot})
)

_POSITION_INDEX = {
    position: index for index, position in enumerate(STARTABLE_POSITIONS)
}

#: Other sources' spellings of a Sleeper position. Sleeper itself says
#: ``DEF``; several projection feeds say ``DST`` or ``D/ST``.
POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF"}

#: Roster-position labels that hold players outside the roster's capacity.
#: Sleeper keeps these out of ``roster_positions`` entirely, but a caller
#: may pass a list that includes them.
_NON_CAPACITY_SLOTS = frozenset({"IR", "TAXI"})

#: Rounding applied to value/gain sort keys so floating-point noise cannot
#: break a documented tie. See the module docstring's horizon section.
_TIE_DECIMALS = 9

#: Default cap on how many candidates :func:`build_add_drop_candidates`
#: evaluates. See the module docstring's "The cost of an exhaustive search".
DEFAULT_MAX_CANDIDATES = 60

#: Column order for :func:`build_add_drop_candidates`'s output.
ADD_DROP_COLUMNS = [
    "player_id",
    "full_name",
    "position",
    "team",
    "projected_ppg",
    "starts_immediately",
    "starting_ppg_gain",
    "displaces_player_id",
    "displaces_name",
    "best_drop_player_id",
    "best_drop_name",
    "best_drop_marginal_value",
    "net_lineup_gain",
    "net_gain_this_week",
    "net_lineup_gain_total",
    "weeks_evaluated",
    "add_drop_rank",
]

#: Column order for :func:`build_drop_candidates`'s output.
DROP_CANDIDATE_COLUMNS = [
    "player_id",
    "full_name",
    "position",
    "projected_ppg",
    "is_starter",
    "marginal_value",
    "marginal_value_total",
    "weeks_evaluated",
    "drop_rank",
]


def _as_nullable_labels(values: pd.Series) -> pd.Series:
    """Force a label column to object dtype carrying ``None``, never ``NaN``.

    Constructing a DataFrame from dicts whose label values mix strings and
    ``None`` lets pandas coerce the ``None`` to ``NaN``, dtype-dependently.
    These columns mean "there is no such player", which callers test with
    ``is None`` -- the same convention ``waiver_rankings.py`` documents for
    ``confidence_tier``.
    """
    return pd.Series(
        [None if value is None or pd.isna(value) else value for value in values],
        index=values.index,
        dtype=object,
    )


@dataclass(frozen=True)
class LineupSolution:
    """The best startable lineup available from a set of players.

    Attributes:
        points_per_game: Summed ``projected_ppg`` of the chosen starters.
        starters: The chosen starters' ``player_id`` values, as a frozen
            set so two solutions can be differenced directly.
    """

    points_per_game: float
    starters: frozenset[str]


_EMPTY_SOLUTION = LineupSolution(0.0, frozenset())

#: A solver input row: ``(position, projected points, player_id)``.
_Entry = tuple[str, float, str]


def starting_slots(roster_positions: Sequence[str]) -> list[str]:
    """The startable slots in a league's roster-position list.

    Any label not in
    :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
    (``BN``, ``IR``, ``TAXI``, an unrecognized custom label) is a bench
    slot and is excluded -- the same rule FFA-067 applies. ``K`` and ``DEF``
    are startable.

    Args:
        roster_positions: A league's ordered roster-slot list, e.g.
            ``snapshot.roster_positions``.

    Returns:
        The startable slot labels, in their original order.
    """
    return [slot for slot in roster_positions if slot in START_SLOT_ELIGIBILITY]


def _canonical_position(position: object) -> Optional[str]:
    """A startable position label, resolving :data:`POSITION_ALIASES`."""
    if position is None or (isinstance(position, float) and pd.isna(position)):
        return None
    label = str(position)
    label = POSITION_ALIASES.get(label, label)
    return label if label in _POSITION_INDEX else None


def _marked_unavailable(flag: object) -> bool:
    """Whether an ``available`` cell explicitly says ``False``.

    ``None``/``NaN`` mean "unknown", which is treated as available, the
    same way :func:`optimal_lineup` treats them.
    """
    if flag is None:
        return False
    try:
        if pd.isna(flag):
            return False
    except (TypeError, ValueError):
        return False
    return not bool(flag)


def _lineup_entries(players: pd.DataFrame, ppg_column: str) -> list[_Entry]:
    """Solver entries for every row with a startable position and a projection."""
    entries: list[_Entry] = []
    for player_id, position, points in zip(
        players["player_id"], players["position"], players[ppg_column]
    ):
        label = _canonical_position(position)
        if label is None or points is None or pd.isna(points):
            continue
        entries.append((label, float(points), str(player_id)))
    return entries


@lru_cache(maxsize=4096)
def _reachable_states(
    slots: tuple[str, ...], counts: tuple[int, ...]
) -> tuple[tuple[int, ...], ...]:
    """Every feasible per-position starter-count vector, sorted.

    Depends only on the slot list and on how many players each position
    has (capped at what the slots could ever take), which is why it is
    memoized: the horizon evaluation re-solves near-identical rosters.
    """
    zero_state = tuple(0 for _ in STARTABLE_POSITIONS)
    reachable = {zero_state}
    for slot in slots:
        next_reachable = set(reachable)
        for state in reachable:
            for position in START_SLOT_ELIGIBILITY[slot]:
                index = _POSITION_INDEX[position]
                if state[index] < counts[index]:
                    new_state = list(state)
                    new_state[index] += 1
                    next_reachable.add(tuple(new_state))
        reachable = next_reachable
    return tuple(sorted(reachable))


@lru_cache(maxsize=4096)
def _full_states(
    slots: tuple[str, ...], counts: tuple[int, ...]
) -> tuple[tuple[int, ...], ...]:
    """The reachable states that start as many players as possible, sorted.

    When every projection is strictly positive, the optimum is always one
    of these: feasible starter sets form a transversal matroid, so any
    smaller feasible set extends to a full one with strictly more points.
    Every other state is therefore strictly beaten, and skipping it cannot
    change which state is the first maximum -- it only saves the work.
    """
    states = _reachable_states(slots, counts)
    most = max(sum(state) for state in states)
    return tuple(state for state in states if sum(state) == most)


def _solve(entries: Iterable[_Entry], slots: Sequence[str]) -> LineupSolution:
    """The exact best lineup over ``entries`` -- see :func:`optimal_lineup`."""
    if not slots:
        return _EMPTY_SOLUTION

    # Per position, players sorted best-first. Ties break on player_id so
    # the chosen lineup is stable across runs -- see the module docstring.
    candidates: dict[str, list[tuple[float, str]]] = {
        position: [] for position in STARTABLE_POSITIONS
    }
    for position, points, player_id in entries:
        candidates[position].append((points, player_id))
    if not any(candidates.values()):
        return _EMPTY_SOLUTION
    for position in candidates:
        candidates[position].sort(key=lambda item: (-item[0], item[1]))

    prefix: dict[str, list[float]] = {}
    for position, players in candidates.items():
        sums = [0.0]
        for points, _ in players:
            sums.append(sums[-1] + points)
        prefix[position] = sums

    slot_tuple = tuple(slots)
    capacity = [
        sum(1 for slot in slot_tuple if position in START_SLOT_ELIGIBILITY[slot])
        for position in STARTABLE_POSITIONS
    ]
    counts = tuple(
        min(len(candidates[position]), capacity[index])
        for index, position in enumerate(STARTABLE_POSITIONS)
    )

    # With a zero or negative projection in play, starting fewer players
    # can win, so only then is the full state space searched.
    all_positive = all(
        points > 0 for players in candidates.values() for points, _ in players
    )
    states = (
        _full_states(slot_tuple, counts)
        if all_positive
        else _reachable_states(slot_tuple, counts)
    )

    best_value = 0.0
    best_state = tuple(0 for _ in STARTABLE_POSITIONS)
    # Sorted iteration makes "first maximum wins" deterministic on ties.
    for state in states:
        value = math.fsum(
            prefix[position][state[index]]
            for index, position in enumerate(STARTABLE_POSITIONS)
        )
        if value > best_value:
            best_value = value
            best_state = state

    starters = {
        player_id
        for index, position in enumerate(STARTABLE_POSITIONS)
        for _, player_id in candidates[position][: best_state[index]]
    }
    return LineupSolution(best_value, frozenset(starters))


def slot_fill_values(
    slots: Sequence[str], empty_slot_values: Mapping[str, float]
) -> list[float]:
    """Each startable slot's streaming value, from per-position values.

    A slot is worth the value of the **cheapest** position it accepts --
    a ``FLEX`` taking RB/WR/TE is filled at ``min(RB, WR, TE)`` -- the
    conservative reading of "what a streamer gives". Positions absent from
    ``empty_slot_values`` are skipped; a slot with none of its positions
    present, or a negative value, is worth ``0.0`` (an empty slot).

    Args:
        slots: Startable slot labels, e.g. :func:`starting_slots`'s output.
        empty_slot_values: Position -> per-game points available off the
            waiver wire.

    Returns:
        One value per slot, in ``slots`` order.
    """
    values = []
    for slot in slots:
        eligible = [
            float(empty_slot_values[position])
            for position in START_SLOT_ELIGIBILITY[slot]
            if position in empty_slot_values
            and not pd.isna(empty_slot_values[position])
        ]
        values.append(max(0.0, min(eligible)) if eligible else 0.0)
    return values


def _solve_with_fill(
    entries: Iterable[_Entry], slots: Sequence[str], fills: Sequence[float]
) -> LineupSolution:
    """The exact best lineup when every slot can instead be streamed.

    A dynamic program over slots whose state is the per-position count of
    real starters (as in :func:`_solve`): each slot takes the next-best
    real player of an eligible position, or its streaming value from
    ``fills``. Within a position the top ``k`` are always the ones used, so
    the state fixes the real starters and the program is exact.

    Ties at nine decimals prefer the state with more real starters (a
    rostered player level with a streamer starts), then the first state in
    sorted order. ``starters`` holds real players only; ``points_per_game``
    includes the streamed slots.
    """
    candidates: dict[str, list[tuple[float, str]]] = {
        position: [] for position in STARTABLE_POSITIONS
    }
    for position, points, player_id in entries:
        candidates[position].append((points, player_id))
    for position in candidates:
        candidates[position].sort(key=lambda item: (-item[0], item[1]))

    best: dict[tuple[int, ...], float] = {tuple(0 for _ in STARTABLE_POSITIONS): 0.0}
    for slot, fill in zip(slots, fills):
        following: dict[tuple[int, ...], float] = {}
        for state, value in best.items():
            streamed = value + fill
            if streamed > following.get(state, -math.inf):
                following[state] = streamed
            for position in START_SLOT_ELIGIBILITY[slot]:
                index = _POSITION_INDEX[position]
                used = state[index]
                if used < len(candidates[position]):
                    new_state = state[:index] + (used + 1,) + state[index + 1 :]
                    started = value + candidates[position][used][0]
                    if started > following.get(new_state, -math.inf):
                        following[new_state] = started
        best = following

    chosen = max(
        sorted(best),
        key=lambda state: (round(best[state], _TIE_DECIMALS), sum(state)),
    )
    starters = {
        player_id
        for index, position in enumerate(STARTABLE_POSITIONS)
        for _, player_id in candidates[position][: chosen[index]]
    }
    return LineupSolution(best[chosen], frozenset(starters))


def optimal_lineup(
    players: pd.DataFrame,
    roster_positions: Sequence[str],
    *,
    ppg_column: str = "projected_ppg",
) -> LineupSolution:
    """Solve the best startable lineup from ``players`` by projected points.

    Exhaustive over feasible per-position starter counts (the same
    count-vector dynamic program FFA-067 uses), so the result is the exact
    optimum, not a greedy approximation. Within a position, taking the top
    ``k`` by projection is optimal for any ``k``, so only the counts need
    searching.

    Worked example (hand-checkable). Slots ``["QB", "RB", "FLEX"]`` and
    four players -- QB1 20.0, RB1 12.0, RB2 9.0, WR1 11.0:

    - ``QB`` can only take QB1 (20.0).
    - ``RB`` takes RB1 (12.0).
    - ``FLEX`` accepts RB/WR/TE, so it takes WR1 (11.0) over RB2 (9.0).
    - Total ``43.0``; RB2 is the odd one out.

    Args:
        players: A frame with ``player_id``, ``position`` and a per-game
            projection column. Rows with a missing projection, or a
            position no slot accepts, are ignored rather than treated as
            zero-point starters. If the frame has an ``available`` column,
            rows where it is ``False`` are never started (see the module
            docstring's availability section); without the column every
            row is available.
        roster_positions: The league's ordered roster-slot list; bench
            slots are filtered out by :func:`starting_slots`.
        ppg_column: The per-game projection column to maximize.

    Returns:
        A :class:`LineupSolution`. With no startable players or no
        startable slots, ``points_per_game`` is ``0.0`` and ``starters``
        is empty -- a league that starts nobody, not an error.
    """
    slots = starting_slots(roster_positions)
    if players.empty or not slots:
        return _EMPTY_SOLUTION
    if "available" in players.columns:
        players = players[~players["available"].map(_marked_unavailable).astype(bool)]
        if players.empty:
            return _EMPTY_SOLUTION
    return _solve(_lineup_entries(players, ppg_column), slots)


def assign_lineup_slots(
    players: pd.DataFrame,
    starters: Iterable[str],
    roster_positions: Sequence[str],
    *,
    ppg_column: str = "projected_ppg",
) -> list[tuple[str, Optional[str]]]:
    """Place a solved lineup's starters into named slots, for display.

    :func:`optimal_lineup` decides *who* starts; it never needs to say
    which starter sits in the ``FLEX``. A page that renders a lineup does.
    Dedicated slots are filled before flexible ones and, within a slot,
    the best projection goes first -- so the ``RB`` slots hold the top two
    running backs and the ``FLEX`` holds the next-best eligible player. A
    backtracking search guarantees that any feasible starter set is fully
    placed (a greedy pass can strand a tight end behind a receiver in a
    ``REC_FLEX``).

    Args:
        players: A frame with ``player_id``, ``position`` and
            ``ppg_column`` covering at least the starters.
        starters: The starters' ``player_id`` values, e.g.
            ``optimal_lineup(...).starters``.
        roster_positions: The league's ordered roster-slot list.
        ppg_column: The projection column that orders players within a
            slot type.

    Returns:
        One ``(slot, player_id)`` pair per startable slot, in
        ``roster_positions`` order. ``player_id`` is ``None`` for a slot
        nobody fills. A starter who cannot be placed (absent from
        ``players``, or a set no slot arrangement can hold) is omitted.
    """
    slots = starting_slots(roster_positions)
    wanted = {str(player_id) for player_id in starters}
    entries = sorted(
        (entry for entry in _lineup_entries(players, ppg_column) if entry[2] in wanted),
        key=lambda entry: (-entry[1], entry[2]),
    )
    # One entry per id, best first.
    seen: set[str] = set()
    unique: list[_Entry] = []
    for entry in entries:
        if entry[2] not in seen:
            seen.add(entry[2])
            unique.append(entry)

    order = sorted(
        range(len(slots)),
        key=lambda index: (len(START_SLOT_ELIGIBILITY[slots[index]]), index),
    )
    failed: set[tuple[int, frozenset[str]]] = set()

    def place(step: int, remaining: tuple[_Entry, ...]) -> Optional[dict[int, str]]:
        if not remaining:
            return {}
        if step == len(order):
            return None
        key = (step, frozenset(entry[2] for entry in remaining))
        if key in failed:
            return None
        slot_index = order[step]
        eligible = START_SLOT_ELIGIBILITY[slots[slot_index]]
        for position in range(len(remaining)):
            if remaining[position][0] in eligible:
                rest = place(step + 1, remaining[:position] + remaining[position + 1 :])
                if rest is not None:
                    rest[slot_index] = remaining[position][2]
                    return rest
        rest = place(step + 1, remaining)
        if rest is None:
            failed.add(key)
        return rest

    placed = place(0, tuple(unique))
    if placed is None:
        # Not a feasible starter set: place what a greedy pass can.
        placed = {}
        pool = list(unique)
        for slot_index in order:
            eligible = START_SLOT_ELIGIBILITY[slots[slot_index]]
            for position, entry in enumerate(pool):
                if entry[0] in eligible:
                    placed[slot_index] = entry[2]
                    pool.pop(position)
                    break
    return [(slot, placed.get(index)) for index, slot in enumerate(slots)]


def open_roster_spots(raw_roster: Mapping, roster_positions: Sequence[str]) -> int:
    """Empty roster spots on a raw Sleeper roster.

    Reserve (IR) and taxi players are in the roster's ``players`` list but
    do not use a ``roster_positions`` slot, so they are not counted -- see
    the module docstring's "Reserve (IR) slots and open roster spots".

    Worked example: 16 roster positions, 17 ``players`` of whom 1 is in
    ``reserve`` -> 16 held, 0 open. Drop to 15 ``players`` -> 1 open.

    Args:
        raw_roster: One element of Sleeper's ``/league/<id>/rosters``
            payload (``players``, ``reserve``, ``taxi``).
        roster_positions: The league's ordered roster-slot list.

    Returns:
        ``max(0, capacity - held)``.
    """
    capacity = sum(1 for slot in roster_positions if slot not in _NON_CAPACITY_SLOTS)
    players = {str(player_id) for player_id in (raw_roster.get("players") or [])}
    outside = {
        str(player_id)
        for key in ("reserve", "taxi")
        for player_id in (raw_roster.get(key) or [])
    }
    return max(0, capacity - len(players - outside))


class _HorizonEvaluator:
    """Lineup points for any subset of a fixed player pool, week by week.

    Implements ``L_w`` and ``ROS`` from the module docstring's horizon
    section. Per-player unavailable weeks are computed once; each
    evaluation then groups the horizon's weeks by the set of players
    actually available and solves once per distinct set, memoized.
    """

    def __init__(
        self,
        frames: Sequence[pd.DataFrame],
        roster_positions: Sequence[str],
        *,
        ppg_column: str,
        week: Optional[int],
        season_end_week: Optional[int],
        weeks_out: Mapping[str, int],
        empty_slot_values: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.slots = starting_slots(roster_positions)
        self._fills = (
            None
            if empty_slot_values is None
            else slot_fill_values(self.slots, empty_slot_values)
        )
        if week is None:
            self.weeks: tuple[Optional[int], ...] = (None,)
        else:
            last = week if season_end_week is None else max(week, season_end_week)
            self.weeks = tuple(range(week, last + 1))

        self.entries: dict[str, _Entry] = {}
        out: dict[Optional[int], set[str]] = {w: set() for w in self.weeks}
        seen: set[str] = set()
        for frame in frames:
            if frame.empty:
                continue
            count = len(frame)
            statuses = (
                list(frame["injury_status"])
                if "injury_status" in frame.columns
                else [None] * count
            )
            byes = (
                list(frame["bye_week"])
                if "bye_week" in frame.columns
                else [None] * count
            )
            flags = (
                list(frame["available"])
                if "available" in frame.columns
                else [True] * count
            )
            for raw_id, position, points, status, bye, flag in zip(
                frame["player_id"],
                frame["position"],
                frame[ppg_column],
                statuses,
                byes,
                flags,
            ):
                player_id = str(raw_id)
                if player_id in seen:
                    continue
                seen.add(player_id)

                label = _canonical_position(position)
                if label is not None and points is not None and not pd.isna(points):
                    self.entries[player_id] = (label, float(points), player_id)

                # An ``available`` column describes the coming week only.
                if _marked_unavailable(flag):
                    out[self.weeks[0]].add(player_id)
                if week is not None:
                    for missed in unavailable_weeks(
                        status,
                        bye,
                        self.weeks,  # type: ignore[arg-type]
                        current_week=week,
                        weeks_out=weeks_out,
                    ):
                        out[missed].add(player_id)

        self._out = {w: frozenset(ids) for w, ids in out.items()}
        self._cache: dict[frozenset[str], LineupSolution] = {}

    @property
    def weeks_evaluated(self) -> int:
        """``|W|``."""
        return len(self.weeks)

    def _solve_active(self, active: frozenset[str]) -> LineupSolution:
        solution = self._cache.get(active)
        if solution is None:
            entries = [self.entries[pid] for pid in active if pid in self.entries]
            if self._fills is None:
                solution = _solve(entries, self.slots)
            elif not self.slots:
                solution = _EMPTY_SOLUTION
            else:
                solution = _solve_with_fill(entries, self.slots, self._fills)
            self._cache[active] = solution
        return solution

    def solve(self, player_ids: frozenset[str]) -> list[LineupSolution]:
        """``L_w(player_ids)`` for every ``w`` in the horizon, in week order."""
        return [self._solve_active(player_ids - self._out[week]) for week in self.weeks]


def _total(solutions: Sequence[LineupSolution]) -> float:
    """``ROS``: the horizon's summed lineup points."""
    return math.fsum(solution.points_per_game for solution in solutions)


def _tie_key(values: pd.Series) -> pd.Series:
    """A value column rounded so floating-point noise cannot break a tie."""
    return values.astype("float64").round(_TIE_DECIMALS)


def _drop_table(
    roster: pd.DataFrame,
    evaluator: _HorizonEvaluator,
    roster_ids: frozenset[str],
    reserve_ids: frozenset[str],
    ppg_column: str,
) -> pd.DataFrame:
    """:func:`build_drop_candidates`'s frame, over a prepared evaluator."""
    baseline = evaluator.solve(roster_ids)
    baseline_total = _total(baseline)
    weeks = evaluator.weeks_evaluated

    rows = []
    seen: set[str] = set()
    for row in roster.itertuples(index=False):
        player_id = str(row.player_id)
        if player_id in reserve_ids or player_id in seen:
            continue
        seen.add(player_id)
        projection = getattr(row, ppg_column)
        # No projection means an unknown value, not a zero one: such a
        # player never starts in the solve, so his computed marginal value
        # would be 0.0 and he would top the list. Report NaN instead.
        if projection is None or pd.isna(projection):
            marginal_total = float("nan")
        else:
            marginal_total = baseline_total - _total(
                evaluator.solve(roster_ids - {player_id})
            )
        rows.append(
            {
                "player_id": player_id,
                "full_name": getattr(row, "full_name", None),
                "position": row.position,
                "projected_ppg": (
                    float(projection) if pd.notna(projection) else float("nan")
                ),
                "is_starter": player_id in baseline[0].starters,
                "marginal_value": marginal_total / weeks,
                "marginal_value_total": marginal_total,
                "weeks_evaluated": weeks,
                "drop_rank": 0,
            }
        )

    result = pd.DataFrame(rows, columns=DROP_CANDIDATE_COLUMNS)
    if result.empty:
        return result
    result["_value_key"] = _tie_key(result["marginal_value"])
    result = (
        result.sort_values(
            ["_value_key", "projected_ppg", "player_id"],
            kind="stable",
            na_position="last",
        )
        .drop(columns="_value_key")
        .reset_index(drop=True)
    )
    result["drop_rank"] = range(1, len(result) + 1)
    for column in ("marginal_value", "marginal_value_total", "projected_ppg"):
        result[column] = result[column].astype("float64")
    result["weeks_evaluated"] = result["weeks_evaluated"].astype("int64")
    result["is_starter"] = result["is_starter"].astype(bool)
    return result


def build_drop_candidates(
    roster: pd.DataFrame,
    roster_positions: Sequence[str],
    *,
    ppg_column: str = "projected_ppg",
    week: Optional[int] = None,
    season_end_week: Optional[int] = None,
    weeks_out: Mapping[str, int] = DEFAULT_INJURY_WEEKS_OUT,
    reserve_player_ids: Iterable[str] = (),
    empty_slot_values: Optional[Mapping[str, float]] = None,
) -> pd.DataFrame:
    """Rank a manager's own players by how little it costs to drop them.

    ``marginal_value`` is defined in the module docstring's "The drop
    side" section, and extended over a horizon in its "Availability and
    the rest-of-season horizon" section: the mean per-week drop in
    best-lineup points caused by removing the player. Zero means the
    roster's best lineup is unchanged without him in every horizon week.

    Args:
        roster: The manager's players -- ``player_id``, ``full_name``,
            ``position``, and a projection column; optionally
            ``injury_status``, ``bye_week`` and ``available``.
        roster_positions: The league's ordered roster-slot list.
        ppg_column: The per-game projection column.
        week: The week about to be played. ``None`` (the default) solves a
            single, availability-blind-except-``available`` period, which
            is FFA-100's behavior.
        season_end_week: Last week of the horizon, normally the final
            regular-season week. Ignored without ``week``.
        weeks_out: Injury status -> weeks out; see
            :mod:`~fantasy_analyzer.players.availability`.
        reserve_player_ids: Players in Sleeper ``reserve`` (IR) slots.
            They count in the lineup evaluation but are never listed as
            drops -- dropping one frees no roster spot.
        empty_slot_values: Position -> per-game points a manager can
            stream off the waiver wire (normally each position's
            replacement level). When given, a slot the week's lineup
            cannot fill -- or fills with someone worse -- scores its
            streaming value instead of 0.0; see the module docstring's
            "Streaming-level fill". ``None`` (the default) leaves empty
            slots at 0.0, exactly as before.

    Returns:
        A DataFrame with :data:`DROP_CANDIDATE_COLUMNS`, sorted by
        ascending ``marginal_value``, then ascending projection, then
        ``player_id``, so row 0 is the cheapest player to drop. A player
        with no projection has ``NaN`` values and sorts last.
        ``is_starter`` refers to the first horizon week. Empty (same
        columns) if ``roster`` is empty.
    """
    empty = pd.DataFrame(
        {column: pd.Series(dtype=object) for column in DROP_CANDIDATE_COLUMNS}
    )
    if roster.empty:
        return empty

    evaluator = _HorizonEvaluator(
        [roster],
        roster_positions,
        ppg_column=ppg_column,
        week=week,
        season_end_week=season_end_week,
        weeks_out=weeks_out,
        empty_slot_values=empty_slot_values,
    )
    roster_ids = frozenset(roster["player_id"].astype(str))
    result = _drop_table(
        roster,
        evaluator,
        roster_ids,
        frozenset(str(player_id) for player_id in reserve_player_ids),
        ppg_column,
    )
    return empty if result.empty else result


def build_add_drop_candidates(
    roster: pd.DataFrame,
    candidates: pd.DataFrame,
    roster_positions: Sequence[str],
    *,
    ppg_column: str = "projected_ppg",
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    week: Optional[int] = None,
    season_end_week: Optional[int] = None,
    weeks_out: Mapping[str, int] = DEFAULT_INJURY_WEEKS_OUT,
    reserve_player_ids: Iterable[str] = (),
    open_roster_spots: int = 0,
    same_position_drop: bool = False,
    empty_slot_values: Optional[Mapping[str, float]] = None,
) -> pd.DataFrame:
    """Score free agents by what they add to *this* manager's lineup.

    See the module docstring for the definitions of ``starting_ppg_gain``,
    ``best_drop_marginal_value`` and ``net_lineup_gain``, their horizon
    form, and the scope limits that decide how far this output should be
    trusted. Over a horizon ``W`` (``n = |W|``, ``w1`` its first week):

    - ``starting_ppg_gain = (ROS(R + c) - ROS(R)) / n``
    - ``net_lineup_gain = (ROS(R - d + c) - ROS(R)) / n``, with ``d`` the
      best drop (none when ``open_roster_spots > 0``)
    - ``net_lineup_gain_total`` is the same without the division, and
      ``net_gain_this_week = L_w1(R - d + c) - L_w1(R)``
    - ``starts_immediately``: ``c`` starts in ``w1``
    - ``displaces_*``: whom ``c`` pushes out of the lineup in the first
      horizon week in which he starts (``None`` if he never does)

    Args:
        roster: The manager's current players -- ``player_id``,
            ``full_name``, ``position``, and a projection column;
            optionally ``injury_status``, ``bye_week`` and ``available``.
        candidates: Available players, same shape. Typically the top of a
            :func:`~fantasy_analyzer.players.waiver_rankings.build_waiver_wire_rankings`
            board, already filtered to real free agents. A candidate
            already on ``roster`` is ignored.
        roster_positions: The league's ordered roster-slot list.
        ppg_column: The per-game projection column on both frames.
        max_candidates: Evaluate only this many candidates, chosen by
            descending projection. See the module docstring's cost note.
        week: The week about to be played. ``None`` keeps FFA-100's
            single-period behavior.
        season_end_week: Last week of the horizon, normally the final
            regular-season week. Ignored without ``week``.
        weeks_out: Injury status -> weeks out; see
            :mod:`~fantasy_analyzer.players.availability`.
        reserve_player_ids: Players in Sleeper ``reserve`` (IR) slots --
            never chosen as the drop. Nor is a player with no projection;
            if no droppable player has a known value, ``best_drop`` is
            ``None`` and the net gain equals the starting gain.
        open_roster_spots: Empty roster spots (see
            :func:`open_roster_spots`). Positive means an add needs no
            drop.
        same_position_drop: If ``True``, each candidate's drop is the
            cheapest droppable rostered player *at his own position* (same
            ranking and ties as ``best_drop``), falling back to the
            roster-wide ``best_drop`` when the roster has none. Meant for
            positions that only ever fill their own slot (``K``, ``DEF``):
            there the roster-wide cheapest drop is usually a bench skill
            player, and "carry a second kicker" is scored as a full week
            of bye coverage (an empty slot scores 0.0) rather than as the
            upgrade a manager would actually make. See the module
            docstring's "One best drop" limit.
        empty_slot_values: As for :func:`build_drop_candidates`.

    Returns:
        A DataFrame with :data:`ADD_DROP_COLUMNS`, sorted by descending
        ``net_lineup_gain`` (``add_drop_rank`` 1 = best transaction), then
        descending ``starting_ppg_gain``, then descending projection, then
        ``player_id``. Empty (same columns) if either input is empty.
    """
    empty = pd.DataFrame(
        {column: pd.Series(dtype=object) for column in ADD_DROP_COLUMNS}
    )
    if roster.empty or candidates.empty:
        return empty

    roster_ids = frozenset(roster["player_id"].astype(str))
    shortlist = candidates[
        candidates[ppg_column].notna()
        & ~candidates["player_id"].astype(str).isin(roster_ids)
    ]
    if shortlist.empty:
        return empty
    shortlist = shortlist.sort_values(
        [ppg_column, "player_id"], ascending=[False, True], kind="stable"
    ).head(max_candidates)

    evaluator = _HorizonEvaluator(
        [roster, shortlist],
        roster_positions,
        ppg_column=ppg_column,
        week=week,
        season_end_week=season_end_week,
        weeks_out=weeks_out,
        empty_slot_values=empty_slot_values,
    )
    weeks = evaluator.weeks_evaluated
    baseline = evaluator.solve(roster_ids)
    baseline_total = _total(baseline)

    best_drop_id: Optional[str] = None
    best_drop_value = float("nan")
    # position -> (player_id, marginal_value) of its cheapest valued drop.
    drop_by_position: dict[str, tuple[str, float]] = {}
    if open_roster_spots <= 0:
        drops = _drop_table(
            roster,
            evaluator,
            roster_ids,
            frozenset(str(player_id) for player_id in reserve_player_ids),
            ppg_column,
        )
        valued = drops[drops["marginal_value"].notna()]
        if not valued.empty:
            best_drop_id = str(valued.iloc[0]["player_id"])
            best_drop_value = float(valued.iloc[0]["marginal_value"])
        if same_position_drop:
            # ``drops`` is already in drop order, so the first row per
            # position is that position's cheapest drop.
            for drop in valued.itertuples(index=False):
                label = _canonical_position(drop.position) or str(drop.position)
                drop_by_position.setdefault(
                    label, (str(drop.player_id), float(drop.marginal_value))
                )

    roster_names = {
        str(row.player_id): getattr(row, "full_name", None)
        for row in roster.itertuples(index=False)
    }

    rows = []
    for row in shortlist.itertuples(index=False):
        player_id = str(row.player_id)
        with_add = evaluator.solve(roster_ids | {player_id})
        gain_total = _total(with_add) - baseline_total

        displaced_id = None
        for before, after_add in zip(baseline, with_add):
            if player_id in after_add.starters:
                displaced = sorted(before.starters - after_add.starters)
                displaced_id = displaced[0] if displaced else None
                break

        drop_id, drop_value = best_drop_id, best_drop_value
        label = _canonical_position(row.position) or str(row.position)
        if same_position_drop and label in drop_by_position:
            drop_id, drop_value = drop_by_position[label]

        if drop_id is None:
            after = with_add
        else:
            after = evaluator.solve((roster_ids - {drop_id}) | {player_id})
        net_total = _total(after) - baseline_total

        rows.append(
            {
                "player_id": player_id,
                "full_name": getattr(row, "full_name", None),
                "position": row.position,
                "team": getattr(row, "team", None),
                "projected_ppg": float(getattr(row, ppg_column)),
                "starts_immediately": player_id in with_add[0].starters,
                "starting_ppg_gain": gain_total / weeks,
                "displaces_player_id": displaced_id,
                "displaces_name": roster_names.get(displaced_id)
                if displaced_id
                else None,
                "best_drop_player_id": drop_id,
                "best_drop_name": roster_names.get(drop_id) if drop_id else None,
                "best_drop_marginal_value": drop_value,
                "net_lineup_gain": net_total / weeks,
                "net_gain_this_week": after[0].points_per_game
                - baseline[0].points_per_game,
                "net_lineup_gain_total": net_total,
                "weeks_evaluated": weeks,
                "add_drop_rank": 0,
            }
        )

    result = pd.DataFrame(rows, columns=ADD_DROP_COLUMNS)
    # Ties break toward the better projection before falling back to
    # player_id. In practice most of a real board ties at exactly 0.00 --
    # a deep roster is improved by almost nothing on the wire -- and
    # ordering that block by id would bury the near-misses under whoever
    # happened to have the lowest Sleeper id.
    result["_net_key"] = _tie_key(result["net_lineup_gain"])
    result["_gain_key"] = _tie_key(result["starting_ppg_gain"])
    result = (
        result.sort_values(
            ["_net_key", "_gain_key", "projected_ppg", "player_id"],
            ascending=[False, False, False, True],
            kind="stable",
        )
        .drop(columns=["_net_key", "_gain_key"])
        .reset_index(drop=True)
    )
    result["add_drop_rank"] = range(1, len(result) + 1)
    for column in (
        "displaces_player_id",
        "displaces_name",
        "best_drop_player_id",
        "best_drop_name",
    ):
        result[column] = _as_nullable_labels(result[column])
    for column in (
        "projected_ppg",
        "starting_ppg_gain",
        "best_drop_marginal_value",
        "net_lineup_gain",
        "net_gain_this_week",
        "net_lineup_gain_total",
    ):
        result[column] = result[column].astype("float64")
    result["weeks_evaluated"] = result["weeks_evaluated"].astype("int64")
    result["starts_immediately"] = result["starts_immediately"].astype(bool)
    return result


def build_roster_projection_frame(
    player_ids: Sequence[str],
    projections: pd.DataFrame,
    *,
    id_column: str = "player_id",
) -> pd.DataFrame:
    """Select a manager's rostered players out of a league-wide projection.

    A convenience join: Sleeper gives a roster as a list of
    ``player_id`` strings, while every projection in this package is a
    frame keyed by the same id.

    Args:
        player_ids: The manager's rostered Sleeper player ids, e.g.
            ``snapshot.rosters_df`` row's ``players`` list.
        projections: Any projection frame keyed by ``id_column`` --
            notably
            :func:`~fantasy_analyzer.players.waiver_rankings.build_free_agent_ros_projections`'s
            output built over the league-wide pool.
        id_column: The id column in ``projections``.

    Returns:
        The subset of ``projections`` whose id is in ``player_ids``. A
        rostered player absent from ``projections`` simply has no row --
        he contributes nothing to a lineup solve, which is the same
        outcome as a ``NaN`` projection.
    """
    wanted = {str(player_id) for player_id in player_ids}
    if projections.empty or not wanted:
        return projections.iloc[0:0]
    return projections[projections[id_column].astype(str).isin(wanted)].reset_index(
        drop=True
    )
