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
verbatim -- one source of truth for what a ``FLEX`` accepts -- and solves
the identical count-vector problem over ``projected_ppg``. The tie-breaking
differs by necessity (there is no "was started" to prefer), so it falls
back to ``player_id`` ascending, which keeps the output deterministic.

The drop side
--------------------------------------------------------------------------

An add is only executable if something can be dropped. Each rostered
player gets a **marginal value**:

.. code-block:: text

    marginal_value = best_lineup(roster) - best_lineup(roster - player)

A player whose marginal value is 0.0 is, this week, free to drop: removing
him does not change the best lineup the manager can field. That is not the
same as "he is the worst player on the roster" -- a third-string
quarterback in a one-QB league has a marginal value of 0.0 even if his
projection is respectable, while a bye-week-covering fourth receiver may
not. This is the number that decides a roster move, so it is the number
reported.

``best_drop`` is the rostered player with the lowest marginal value, ties
broken toward the lower projection. Applying it gives

.. code-block:: text

    net_lineup_gain = best_lineup(roster - best_drop + candidate)
                      - best_lineup(roster)

which is the honest bottom line for the transaction: it can be lower than
``starting_ppg_gain`` when the only droppable player is himself a starter,
and it is never higher.

Scope and limits -- read before acting on the output
--------------------------------------------------------------------------

- **Per-game rates, not season totals.** Every figure is points per game.
  A candidate worth +1.5 ppg is worth that in each week he is started, not
  once.
- **No bye-week or injury planning.** The lineup is solved as though every
  rostered player is available every week. A bench player who exists to
  cover a week-9 bye looks droppable here. Cross-reference
  :func:`~fantasy_analyzer.players.opponent_strength.add_matchup_context`'s
  ``bye_week`` before acting on a drop.
- **No positional-scarcity or handcuff logic.** Dropping the backup to a
  starting running back is scored purely on this week's lineup.
- **No transaction costs**: no FAAB, no waiver priority, no roster-size or
  IR-slot rules. The league's own settings are not consulted.
- **The candidate's projection is taken as given**, inheriting every
  limitation of
  :mod:`fantasy_analyzer.players.ros_projection` -- in particular that a
  one-game sample is shrunk but not disbelieved.

The cost of an exhaustive search
--------------------------------------------------------------------------

:func:`build_add_drop_candidates` solves one lineup per candidate plus one
per rostered player. That is cheap for a shortlist and wasteful for a
12,000-row catalog, so the function takes ``max_candidates`` and considers
only the best that many by ``projected_ppg``. Pass a pre-filtered,
already-ranked frame (the top of a waiver board) rather than a whole pool.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

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


def starting_slots(roster_positions: Sequence[str]) -> list[str]:
    """The startable slots in a league's roster-position list.

    Any label not in
    :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
    (``BN``, ``IR``, ``TAXI``, an unrecognized custom label) is a bench
    slot and is excluded -- the same rule FFA-067 applies.

    Args:
        roster_positions: A league's ordered roster-slot list, e.g.
            ``snapshot.roster_positions``.

    Returns:
        The startable slot labels, in their original order.
    """
    return [slot for slot in roster_positions if slot in START_SLOT_ELIGIBILITY]


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
            zero-point starters.
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
        return LineupSolution(0.0, frozenset())

    usable = players[
        players["position"].isin(STARTABLE_POSITIONS) & players[ppg_column].notna()
    ]
    if usable.empty:
        return LineupSolution(0.0, frozenset())

    # Per position, players sorted best-first. Ties break on player_id so
    # the chosen lineup is stable across runs -- see the module docstring.
    candidates: dict[str, list[tuple[float, str]]] = {
        position: [] for position in STARTABLE_POSITIONS
    }
    for row in usable.itertuples(index=False):
        candidates[row.position].append(
            (float(getattr(row, ppg_column)), str(row.player_id))
        )
    for position in candidates:
        candidates[position].sort(key=lambda item: (-item[0], item[1]))

    prefix: dict[str, list[float]] = {}
    for position, entries in candidates.items():
        sums = [0.0]
        for points, _ in entries:
            sums.append(sums[-1] + points)
        prefix[position] = sums

    zero_state = tuple(0 for _ in STARTABLE_POSITIONS)
    reachable = {zero_state}
    for slot in slots:
        next_reachable = set(reachable)
        for state in reachable:
            for position in START_SLOT_ELIGIBILITY[slot]:
                index = _POSITION_INDEX[position]
                if state[index] < len(candidates[position]):
                    new_state = list(state)
                    new_state[index] += 1
                    next_reachable.add(tuple(new_state))
        reachable = next_reachable

    best_value = 0.0
    best_state = zero_state
    # Sorted iteration makes "first maximum wins" deterministic on ties.
    for state in sorted(reachable):
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


def build_drop_candidates(
    roster: pd.DataFrame,
    roster_positions: Sequence[str],
    *,
    ppg_column: str = "projected_ppg",
) -> pd.DataFrame:
    """Rank a manager's own players by how little it costs to drop them.

    ``marginal_value`` is defined in the module docstring's "The drop
    side" section: the drop in best-lineup points per game caused by
    removing the player. Zero means the roster's best lineup is unchanged
    without him.

    Args:
        roster: The manager's players -- ``player_id``, ``full_name``,
            ``position``, and a projection column.
        roster_positions: The league's ordered roster-slot list.
        ppg_column: The per-game projection column.

    Returns:
        A DataFrame with :data:`DROP_CANDIDATE_COLUMNS`, sorted by
        ascending ``marginal_value`` then ascending projection, so row 0
        is the cheapest player to drop. Empty (same columns) if ``roster``
        is empty.
    """
    empty = pd.DataFrame(
        {column: pd.Series(dtype=object) for column in DROP_CANDIDATE_COLUMNS}
    )
    if roster.empty:
        return empty

    baseline = optimal_lineup(roster, roster_positions, ppg_column=ppg_column)

    rows = []
    for row in roster.itertuples(index=False):
        player_id = str(row.player_id)
        without = roster[roster["player_id"].astype(str) != player_id]
        solution = optimal_lineup(without, roster_positions, ppg_column=ppg_column)
        projection = getattr(row, ppg_column)
        rows.append(
            {
                "player_id": player_id,
                "full_name": getattr(row, "full_name", None),
                "position": row.position,
                "projected_ppg": (
                    float(projection) if pd.notna(projection) else float("nan")
                ),
                "is_starter": player_id in baseline.starters,
                "marginal_value": baseline.points_per_game - solution.points_per_game,
                "drop_rank": 0,
            }
        )

    result = pd.DataFrame(rows, columns=DROP_CANDIDATE_COLUMNS)
    result = result.sort_values(
        ["marginal_value", "projected_ppg"],
        kind="stable",
        na_position="first",
    ).reset_index(drop=True)
    result["drop_rank"] = range(1, len(result) + 1)
    result["marginal_value"] = result["marginal_value"].astype("float64")
    result["projected_ppg"] = result["projected_ppg"].astype("float64")
    result["is_starter"] = result["is_starter"].astype(bool)
    return result


def build_add_drop_candidates(
    roster: pd.DataFrame,
    candidates: pd.DataFrame,
    roster_positions: Sequence[str],
    *,
    ppg_column: str = "projected_ppg",
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> pd.DataFrame:
    """Score free agents by what they add to *this* manager's lineup.

    See the module docstring for the definitions of ``starting_ppg_gain``,
    ``best_drop_marginal_value`` and ``net_lineup_gain``, and for the
    scope limits (no byes, no injuries, no transaction costs) that decide
    how far this output should be trusted.

    Args:
        roster: The manager's current players -- ``player_id``,
            ``full_name``, ``position``, and a projection column.
        candidates: Available players, same shape. Typically the top of a
            :func:`~fantasy_analyzer.players.waiver_rankings.build_waiver_wire_rankings`
            board, already filtered to real free agents.
        roster_positions: The league's ordered roster-slot list.
        ppg_column: The per-game projection column on both frames.
        max_candidates: Evaluate only this many candidates, chosen by
            descending projection. See the module docstring's cost note.

    Returns:
        A DataFrame with :data:`ADD_DROP_COLUMNS`, sorted by descending
        ``net_lineup_gain`` (``add_drop_rank`` 1 = best transaction), then
        descending ``starting_ppg_gain``, then ``player_id``. Empty (same
        columns) if either input is empty.
    """
    empty = pd.DataFrame(
        {column: pd.Series(dtype=object) for column in ADD_DROP_COLUMNS}
    )
    if roster.empty or candidates.empty:
        return empty

    baseline = optimal_lineup(roster, roster_positions, ppg_column=ppg_column)
    drops = build_drop_candidates(roster, roster_positions, ppg_column=ppg_column)

    shortlist = candidates[candidates[ppg_column].notna()]
    if shortlist.empty:
        return empty
    shortlist = shortlist.sort_values(
        [ppg_column, "player_id"], ascending=[False, True], kind="stable"
    ).head(max_candidates)

    roster_names = {
        str(row.player_id): getattr(row, "full_name", None)
        for row in roster.itertuples(index=False)
    }

    rows = []
    for row in shortlist.itertuples(index=False):
        player_id = str(row.player_id)
        addition = pd.DataFrame(
            [
                {
                    "player_id": player_id,
                    "full_name": getattr(row, "full_name", None),
                    "position": row.position,
                    ppg_column: float(getattr(row, ppg_column)),
                }
            ]
        )
        with_add = optimal_lineup(
            pd.concat([roster, addition], ignore_index=True),
            roster_positions,
            ppg_column=ppg_column,
        )
        gain = with_add.points_per_game - baseline.points_per_game
        displaced = sorted(baseline.starters - with_add.starters)
        displaced_id = displaced[0] if displaced else None

        # The best drop is the cheapest rostered player who is not the
        # candidate himself (he is not on the roster) -- but a player the
        # candidate displaces is by definition cheap, so the search is
        # over the whole roster and the two answers often coincide.
        if drops.empty:
            best_drop_id = None
            best_drop_value = float("nan")
            net_gain = gain
        else:
            best_drop = drops.iloc[0]
            best_drop_id = str(best_drop["player_id"])
            best_drop_value = float(best_drop["marginal_value"])
            swapped = pd.concat(
                [
                    roster[roster["player_id"].astype(str) != best_drop_id],
                    addition,
                ],
                ignore_index=True,
            )
            after = optimal_lineup(swapped, roster_positions, ppg_column=ppg_column)
            net_gain = after.points_per_game - baseline.points_per_game

        rows.append(
            {
                "player_id": player_id,
                "full_name": getattr(row, "full_name", None),
                "position": row.position,
                "team": getattr(row, "team", None),
                "projected_ppg": float(getattr(row, ppg_column)),
                "starts_immediately": player_id in with_add.starters,
                "starting_ppg_gain": gain,
                "displaces_player_id": displaced_id,
                "displaces_name": roster_names.get(displaced_id)
                if displaced_id
                else None,
                "best_drop_player_id": best_drop_id,
                "best_drop_name": roster_names.get(best_drop_id)
                if best_drop_id
                else None,
                "best_drop_marginal_value": best_drop_value,
                "net_lineup_gain": net_gain,
                "add_drop_rank": 0,
            }
        )

    result = pd.DataFrame(rows, columns=ADD_DROP_COLUMNS)
    # Ties break toward the better projection before falling back to
    # player_id. In practice most of a real board ties at exactly 0.00 --
    # a deep roster is improved by almost nothing on the wire -- and
    # ordering that block by id would bury the near-misses under whoever
    # happened to have the lowest Sleeper id.
    result = result.sort_values(
        ["net_lineup_gain", "starting_ppg_gain", "projected_ppg", "player_id"],
        ascending=[False, False, False, True],
        kind="stable",
    ).reset_index(drop=True)
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
    ):
        result[column] = result[column].astype("float64")
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
