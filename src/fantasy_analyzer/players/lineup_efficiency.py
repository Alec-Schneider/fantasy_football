"""Weekly lineup efficiency and season roster efficiency metrics (FFA-067).

Consumes FFA-064's
:func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`
output (``PLAYER_WEEK_COLUMNS``-shaped, with provider raw-stat columns and a
``fantasy_points`` column) plus a league's ``roster_positions`` slot list
(``LeagueSettings.roster_positions`` / ``LeagueSnapshot.roster_positions``)
and answers the FFA-067 question for every roster-week: how much did the
manager actually score, how much could they have scored under the league's
own roster-position rules, how much did they leave on the bench, how
efficient was the lineup, and how many individual start/sit decisions were
suboptimal?

The optimizer must respect the league's roster slots (a bench quarterback
cannot displace a starting running back in a league with no SuperFlex), and
the exact problem -- assigning rostered players to slots, each player at
most once, maximizing total points, with FLEX slots accepting several
positions -- is combinatorial. This module solves it exactly and
deterministically; the algorithm and every tie-break are specified below,
because this repository's convention is that the docstring is the actual
specification, not the code.

This module performs no network access; it operates entirely on an
already-built ``player_week_df`` plus the league's slot list.

Weekly metrics (one row per ``(season, week, roster_id)`` present in the
input)
----------------------------------------------------------------------------

Let ``A`` be the set of players the manager actually started that week (the
rows with ``started == True``), ``B`` the benched players (``started ==
False``), and ``O`` the player set of a chosen optimal lineup (see "The
optimal-lineup problem" below). All ``fantasy_points`` values are used as-is
except ``NaN``, which is treated as ``0.0`` (see "Missing values" below).

- **actual_points** -- ``sum(points)`` over ``A``, the manager's realized
  starter score. ``0.0`` for a week in which nobody was started.
- **optimal_points** -- ``sum(points)`` over ``O``, the maximum total any
  *legal* lineup under ``roster_positions`` could have scored that week.
  ``0.0`` when no legal lineup scores positive points (see the negative-
  scorer and empty-roster edge cases).
- **bench_points** -- ``sum(points)`` over ``B``, the raw bench total.
  Informational only: it includes points that could not legally have been
  started (e.g. a second quarterback in a one-QB league), which is exactly
  why it is not the ticket's "points left on bench" metric.
- **points_left_on_bench** -- ``optimal_points - actual_points``, the
  points the manager left available but unstarted. Always ``>= 0``; ``0``
  iff the actual lineup was already optimal. This is the efficiency-
  theoretic reading of the ticket's "points left on bench": a bench player
  whose points could not legally replace anyone's (the second QB above)
  contributes nothing to it, because no legal lineup could have included
  him. (Formally, ``optimal_points - actual_points > 0`` implies some
  benched player should have started or some slot should have been filled:
  re-arranging the *same* player set across slots never changes the total,
  so a strictly better legal lineup must differ in its player set.)
- **efficiency_pct** -- ``actual_points / optimal_points``, the lineup
  efficiency percentage. ``NaN`` when ``optimal_points <= 0`` (division by
  zero, or a non-positive denominator -- see the negative-scorer edge
  case); otherwise in ``[0, 1]`` for non-negative scorers, and can fall
  outside ``[0, 1]`` only if a started player scored negative points (a
  defense that actively cost points).
- **is_suboptimal** -- ``True`` iff ``optimal_points > actual_points``
  (equivalently ``points_left_on_bench > 0``): the week contains at least
  one strictly costly start/sit decision.
- **suboptimal_starts** -- ``len(A) - len(A intersect O)``, the number of
  players the manager started who are not in the chosen optimal lineup:
  "wrong starts". Because ties are broken toward the players the manager
  actually started (see "Tie-breaking"), a bench player who merely *ties* a
  started player never counts here -- a tie is not a mistake.
- **suboptimal_sits** -- ``len(O intersect B)``, the number of benched
  players in the chosen optimal lineup: "wrong sits", the other side of the
  same decisions. When the actual lineup fills every slot, the two counts
  are equal; when the manager left a slot empty that a benched player could
  have filled, ``suboptimal_sits`` counts the fill and
  ``suboptimal_starts`` does not (the started players are all still in
  ``O``).

Season roster-efficiency summary (one row per ``(season, roster_id)``)
----------------------------------------------------------------------

:func:`build_roster_efficiency_metrics` aggregates the weekly table over
each roster-season: ``weeks_played`` (number of weeks with a weekly row),
``total_actual_points`` / ``total_optimal_points`` / ``total_bench_points``
/ ``total_points_left_on_bench`` (sums of the weekly values),
``efficiency_pct`` (``total_actual_points / total_optimal_points`` --
aggregate efficiency, not the mean of weekly efficiencies; ``NaN`` when the
denominator is ``<= 0``), ``suboptimal_weeks`` and ``suboptimal_week_pct``
(the frequency of weeks containing at least one suboptimal decision, the
ticket's "frequency of suboptimal start/sit decisions" at the week grain),
and ``total_suboptimal_starts`` / ``total_suboptimal_sits`` (the counts of
individual wrong starts / wrong sits summed across the season).

The optimal-lineup problem and its exact solution
--------------------------------------------------

**Problem.** Given the week's rostered players (each with exactly one
``position`` and a ``fantasy_points`` value) and the league's slot list,
choose at most one player per slot, a player in at most one slot, maximizing
the sum of points. Each slot accepts only players of eligible positions; a
slot may be left empty (a roster with no legal player at a slot -- a bye, an
IR-piled position, a zero-TE construction -- simply plays short).

**Slot eligibility.** The recognized starting slots and their eligible
positions are:

- ``QB`` -> ``{QB}``; ``RB`` -> ``{RB}``; ``WR`` -> ``{WR}``; ``TE`` ->
  ``{TE}``; ``K`` -> ``{K}``; ``DEF`` -> ``{DEF}``
- ``FLEX`` -> ``{RB, WR, TE}``
- ``SUPER_FLEX`` -> ``{QB, RB, WR, TE}``
- ``REC_FLEX`` -> ``{WR, TE}``; ``WRRB_FLEX`` -> ``{WR, RB}``

Any other slot label in ``roster_positions`` -- ``BN``, ``IR``, or an
unrecognized future slot -- is treated as a bench slot: it contributes no
starting requirement and no points. This is a degraded-but-safe default in
the spirit of ``player_week.py``'s missing-``players`` fallback: an
unrecognized starting slot would silently shrink the starting roster, but an
unrecognized label cannot be mapped to positions without guessing, and
raising would make every future Sleeper slot change a hard break. A player
whose ``position`` is not one of ``{QB, RB, WR, TE, K, DEF}`` (including a
missing position) is ineligible for every slot.

**Algorithm.** The key structural fact is that each player has exactly one
position, so the objective separates by position: for a chosen count vector
``c = (c_QB, c_RB, c_WR, c_TE, c_K, c_DEF)`` (how many players of each
position the lineup uses), the best achievable total is simply the sum of
each position's ``c_p`` highest-scoring players -- the choices at different
positions never compete for the same player. Two things remain: (1) which
count vectors are *feasible* -- assignable to the slot list, with ``c_p`` no
larger than the number of rostered players at position ``p`` -- and (2)
which feasible count vector maximizes the total.

(1) is computed by a small dynamic program over the starting slots: the
state is a count vector; the DP starts from the all-zero vector; each slot
either is skipped (leaving it empty) or increments one eligible position's
count. (2) then scans every reachable count vector, scores it with per-
position prefix sums of the sorted candidates, and keeps the best under the
tie-breaking rule below.

**Computational bounds.** The number of reachable count vectors is at most
``prod_p (min(available_p, cap_p) + 1)``, where ``cap_p`` is the most slots
that could ever absorb position ``p`` (its own slots plus every flex slot).
For a standard nine-starter league (``QB, RB, RB, WR, WR, TE, FLEX, K,
DEF``) that product is at most ``(1+1) * (3+1) * (3+1) * (2+1) * (1+1) *
(1+1) = 384`` states, and the DP visits each state once per slot with at
most four transitions -- a few thousand operations per roster-week, far
below the exponential cost of enumerating slot assignments directly. The
largest legal Sleeper starter set (a SuperFlex league adds a second QB and a
fourth RB/WR/TE to the caps) still stays in the low thousands of states.

Tie-breaking: deterministic, and ties are never mistakes
--------------------------------------------------------

Ties arise in two places, and both are broken deterministically with the
same intent: when two choices score the same, prefer the one closest to
what the manager actually did, so that a tie never *creates* a
"suboptimal" count.

- **Within a position** (which ``c_p`` of the position's players are
  selected): sort candidates by ``(-points, started-descending,
  sleeper_player_id-ascending)`` and take the first ``c_p``. Among equal
  scores, started players are selected before benched ones, so a benched
  player who merely ties a started player at the selection boundary never
  displaces him -- the tie is not counted as a wrong start.
- **Across count vectors**: maximize ``(value, agreement, -sits)``
  lexicographically, where ``agreement`` is the number of started players
  in the lineup and ``sits`` the number of benched players in it. First
  priority is the score; second, the number of started players retained
  (ties toward the actual lineup); third, the number of benched players
  added (a tie with the manager's lineup that costs nothing is not a
  mistake -- e.g. benching a zero-scorer who could have filled an empty
  slot). When two count vectors are tied on all three keys, the first in
  sorted state order wins; the choice is arbitrary among exact ties, but
  the *metrics* are not affected, because any two lineups tied on
  (value, agreement, sits) yield identical ``suboptimal_starts`` /
  ``suboptimal_sits``.

These rules make ``suboptimal_starts == suboptimal_sits == 0`` iff
``actual_points == optimal_points``: if the actual lineup is legal and
optimal, it is the unique best under the tie-breaking (it maximizes
agreement among optimal lineups by construction), and conversely any
strictly better legal lineup must differ in its player set, which the
counts then report.

Missing values / edge cases
----------------------------

- **Empty ``player_week_df``**: both builders return an empty DataFrame
  with their expected columns.
- **``NaN`` ``fantasy_points``**: treated as ``0.0`` for every purpose
  (actual, bench, and optimal candidates). FFA-064 never emits one, but a
  hand-built input should not corrupt the sums with a ``NaN``.
- **Missing ``season`` / ``week`` / ``roster_id``**: the row cannot be
  assigned to a roster-week and is skipped entirely -- mirroring
  ``performance.py``'s identical handling of ungroupable rows. ``season``,
  ``week`` and ``roster_id`` are cast to ``int`` for the group key (the
  same normalization ``player_week.py`` performs on ``season``).
- **Missing ``position`` (or a position outside ``{QB, RB, WR, TE, K,
  DEF}``)**: the player still counts toward ``actual_points`` /
  ``bench_points`` if started / benched, but is ineligible for every slot
  and can never appear in the optimal lineup -- the actual lineup is then
  not legal under this module's slot model (unreachable under FFA-064's
  contract, where every starter has a resolved position).
- **Duplicate ``sleeper_player_id`` within one roster-week**: should not
  occur in real data (``player_week.py`` preserves duplicates defensively);
  this module keeps the first row per player id and ignores the rest, so a
  player can never be started twice or double-counted in ``actual_points``.
- **A row with ``started`` and ``bench`` both false** (not expected under
  FFA-064's contract, where they are exact complements): treated as benched
  for ``bench_points`` and as not started everywhere else.
- **A week with no started players**: still gets a weekly row,
  ``actual_points = 0.0``, with the optimal lineup possibly scoring more --
  such a week is maximally suboptimal.
- **Empty or all-bench ``roster_positions``**: there are no starting slots,
  so ``optimal_points`` is ``0.0`` for every week and ``efficiency_pct`` is
  ``NaN`` (division by a zero denominator).
- **Negative scorers** (typically a defense): a ``-5`` DEF makes the empty
  lineup (``0.0``) strictly better than starting it, so the optimal lineup
  leaves the DEF slot empty; ``efficiency_pct`` is ``NaN`` whenever
  ``optimal_points <= 0``, and a manager who started the negative scorer is
  flagged suboptimal with the scorer counted as a wrong start.
- **Ties anywhere**: handled by the deterministic rules above; see
  "Tie-breaking".
- **Multiple seasons in one ``player_week_df``**: grouped separately (the
  key includes ``season``), never pooled -- the identical convention
  ``performance.py`` and ``position_strength.py`` document.

Regular season vs. playoffs: this module is phase-agnostic
------------------------------------------------------------

``player_week_df`` (FFA-064's output) has no ``is_playoff`` column -- the
identical situation ``performance.py`` and ``position_strength.py``
document -- so this module makes no phase distinction of its own and cannot:
every week present in the input for a roster-week enters the same
optimization and the same aggregation, regular season and playoff weeks
alike.

A caller wanting a phase-specific view must pre-filter ``player_week_df`` on
``week`` against the calling league's playoff-start boundary (FFA-022,
``LeagueSettings.playoff_week_start``) **before** calling these functions --
the same caller-filters-first pattern ``consistency.py``,
``performance.py``, and ``position_strength.py`` document.

Column dtypes
--------------

In the weekly frame, ``season`` / ``week`` / ``roster_id`` /
``suboptimal_starts`` / ``suboptimal_sits`` are plain ``int64``,
``is_suboptimal`` is ``bool``, every points/efficiency column is ``float64``
(undefined values as ``NaN``), and ``fantasy_team`` is ``object`` (it may
legitimately be ``None`` if the roster was never resolved to an owner --
``player_week.py``'s documented fallback). The season frame is the same
with ``weeks_played`` / ``suboptimal_weeks`` / ``total_suboptimal_starts`` /
``total_suboptimal_sits`` as ``int64`` and ``suboptimal_week_pct`` as
``float64``. Test undefined values with ``pd.isna``, not ``is None``.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

#: Column order for the DataFrame returned by
#: :func:`build_lineup_efficiency_metrics` -- one row per ``(season, week,
#: roster_id)`` present in the input. See the module docstring's "Weekly
#: metrics" section for the exact definitions.
LINEUP_EFFICIENCY_COLUMNS = [
    "season",
    "week",
    "roster_id",
    "fantasy_team",
    "actual_points",
    "optimal_points",
    "bench_points",
    "points_left_on_bench",
    "efficiency_pct",
    "is_suboptimal",
    "suboptimal_starts",
    "suboptimal_sits",
]

#: Column order for the DataFrame returned by
#: :func:`build_roster_efficiency_metrics` -- one row per ``(season,
#: roster_id)`` present in the input. See the module docstring's "Season
#: roster-efficiency summary" section for the exact definitions.
ROSTER_EFFICIENCY_COLUMNS = [
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
]

#: Starting-slot labels -> the positions each slot accepts. Any slot label
#: not in this mapping (``BN``, ``IR``, unrecognized labels) is a bench
#: slot -- see the module docstring's "Slot eligibility" section.
START_SLOT_ELIGIBILITY = {
    "QB": ("QB",),
    "RB": ("RB",),
    "WR": ("WR",),
    "TE": ("TE",),
    "FLEX": ("RB", "WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
    "REC_FLEX": ("WR", "TE"),
    "WRRB_FLEX": ("WR", "RB"),
    "K": ("K",),
    "DEF": ("DEF",),
}

#: The six startable positions, in the fixed order used for count-vector
#: states and for deterministic state iteration. A player whose position is
#: not in this tuple is ineligible for every slot.
_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

_POSITION_INDEX = {position: index for index, position in enumerate(_POSITIONS)}

#: Points/efficiency columns cast to ``float64`` in the weekly frame so
#: undefined values are ``NaN`` and the dtype does not vary with the data.
_WEEKLY_FLOAT_COLUMNS = [
    "actual_points",
    "optimal_points",
    "bench_points",
    "points_left_on_bench",
    "efficiency_pct",
]

#: Points/efficiency columns cast to ``float64`` in the season frame.
_SEASON_FLOAT_COLUMNS = [
    "total_actual_points",
    "total_optimal_points",
    "total_bench_points",
    "total_points_left_on_bench",
    "efficiency_pct",
    "suboptimal_week_pct",
]


def _optimal_lineup(
    candidates: dict[str, list[tuple[float, bool, Any]]],
    prefix: dict[str, list[float]],
    start_slots: list[str],
) -> tuple[float, int, int]:
    """Solve one roster-week's optimal-lineup problem.

    ``candidates[position]`` is the position's players sorted by
    ``(-points, started-descending, sleeper_player_id-ascending)`` (see
    "Tie-breaking" in the module docstring) and ``prefix[position][k]`` the
    sum of the first ``k`` of them. Returns ``(optimal_points,
    agreement, sits)`` for the chosen optimal lineup, where ``agreement``
    is the number of started players in it and ``sits`` the number of
    benched players in it -- the two numbers every downstream metric needs.
    """
    zero_state = tuple(0 for _ in _POSITIONS)

    # Feasible count vectors, via a DP over the starting slots: each slot is
    # either skipped (left empty) or filled by one eligible position, capped
    # at the number of rostered players of that position. The zero state is
    # always reachable (skip every slot), so the set is never empty.
    reachable = {zero_state}
    for slot in start_slots:
        eligible = START_SLOT_ELIGIBILITY[slot]
        next_reachable = set(reachable)
        for state in reachable:
            for position in eligible:
                index = _POSITION_INDEX[position]
                if state[index] < len(candidates[position]):
                    new_state = list(state)
                    new_state[index] += 1
                    next_reachable.add(tuple(new_state))
        reachable = next_reachable

    best_value: Optional[float] = None
    best_agreement = 0
    best_sits = 0
    # Sorted iteration keeps the "first max wins" rule deterministic when
    # two count vectors tie on (value, agreement, sits).
    for state in sorted(reachable):
        value = math.fsum(
            prefix[position][state[index]] for index, position in enumerate(_POSITIONS)
        )
        agreement = 0
        sits = 0
        for index, position in enumerate(_POSITIONS):
            for points, started, player_id in candidates[position][: state[index]]:
                if started:
                    agreement += 1
                else:
                    sits += 1
        if (
            best_value is None
            or value > best_value
            or (value == best_value and agreement > best_agreement)
            or (
                value == best_value and agreement == best_agreement and sits < best_sits
            )
        ):
            best_value = value
            best_agreement = agreement
            best_sits = sits

    # best_value is never None: the zero state (empty lineup) is always
    # reachable and evaluated.
    return (best_value or 0.0), best_agreement, best_sits


def _week_metrics(
    rows: list[tuple[Any, Any, float, bool]],
    start_slots: list[str],
) -> dict:
    """Compute one roster-week's full set of metrics.

    ``rows`` is the deduplicated roster-week's tuples
    ``(player_id, position, points, started)`` -- see
    :func:`build_lineup_efficiency_metrics` for how they are prepared.
    ``fantasy_team`` is read from the group's first row by the caller; this
    function does not need it.
    """
    started_ids = {player_id for player_id, _, _, started in rows if started}
    actual_points = math.fsum(points for _, _, points, started in rows if started)
    bench_points = math.fsum(points for _, _, points, started in rows if not started)

    candidates: dict[str, list[tuple[float, bool, Any]]] = {
        position: [] for position in _POSITIONS
    }
    for player_id, position, points, started in rows:
        if position in _POSITIONS:
            candidates[position].append((points, started, player_id))
    for position in _POSITIONS:
        candidates[position].sort(
            key=lambda item: (-item[0], not item[1], str(item[2]))
        )

    prefix: dict[str, list[float]] = {}
    for position in _POSITIONS:
        running = 0.0
        prefix[position] = [running]
        for points, _, _ in candidates[position]:
            running = math.fsum((running, points))
            prefix[position].append(running)

    optimal_points, agreement, sits = _optimal_lineup(candidates, prefix, start_slots)

    return {
        "actual_points": actual_points,
        "optimal_points": optimal_points,
        "bench_points": bench_points,
        "points_left_on_bench": optimal_points - actual_points,
        "efficiency_pct": (
            actual_points / optimal_points if optimal_points > 0 else float("nan")
        ),
        "is_suboptimal": optimal_points > actual_points,
        "suboptimal_starts": len(started_ids) - agreement,
        "suboptimal_sits": sits,
    }


def build_lineup_efficiency_metrics(
    player_week_df: pd.DataFrame,
    roster_positions: list[str],
) -> pd.DataFrame:
    """Build one row per ``(season, week, roster_id)`` of lineup-efficiency metrics.

    For every roster-week present in the input, computes the manager's
    actual starter score, the best legal lineup score under
    ``roster_positions`` (an exact, deterministic optimization -- see the
    module docstring's "The optimal-lineup problem" section for the
    algorithm and its computational bounds), the raw bench total, the
    points left on the bench (``optimal - actual``), the lineup efficiency
    percentage, a suboptimal-week flag, and the counts of wrong starts /
    wrong sits. See the module docstring's "Weekly metrics" section for the
    exact definitions and the tie-breaking / missing-value rules.

    Args:
        player_week_df: A
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            DataFrame (plus provider raw-stat columns and ``fantasy_points``
            last), as produced by
            :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`.
            Only ``season``, ``week``, ``roster_id``, ``fantasy_team``,
            ``sleeper_player_id``, ``position``, ``started``, ``bench`` and
            ``fantasy_points`` are read; raw stat columns are ignored. This
            function is phase-agnostic (see the module docstring); filter on
            ``week`` against a league's playoff-start boundary before
            calling for a phase-specific view.
        roster_positions: The league's ordered roster-slot list, e.g.
            ``LeagueSettings.roster_positions`` or
            ``LeagueSnapshot.roster_positions``
            (``["QB", "RB", "RB", ..., "BN", "BN"]``). Recognized starting
            slots are listed in the module docstring's "Slot eligibility"
            section; every other label (including ``BN`` and ``IR``) is a
            bench slot that contributes nothing.

    Returns:
        A DataFrame with columns :data:`LINEUP_EFFICIENCY_COLUMNS`, one row
        per ``(season, week, roster_id)`` present in the input, sorted by
        ascending ``season``, then ``week``, then ``roster_id`` (a
        deterministic display order). ``efficiency_pct`` is ``NaN`` whenever
        ``optimal_points <= 0``. Returns an empty DataFrame with the
        expected columns if the input is empty.
    """
    if player_week_df.empty:
        return pd.DataFrame(columns=LINEUP_EFFICIENCY_COLUMNS)

    start_slots = [
        slot for slot in (roster_positions or []) if slot in START_SLOT_ELIGIBILITY
    ]

    # Group the input rows into roster-weeks, skipping any row that cannot
    # be assigned to a (season, week, roster_id) -- see the module
    # docstring's "Missing values" section.
    groups: dict[tuple[int, int, Any], list] = {}
    for row in player_week_df.itertuples(index=False):
        if (
            pd.isna(getattr(row, "season", None))
            or pd.isna(getattr(row, "week", None))
            or pd.isna(getattr(row, "roster_id", None))
        ):
            continue
        key = (int(row.season), int(row.week), row.roster_id)
        groups.setdefault(key, []).append(row)

    weekly_rows: list[dict] = []
    for (season, week, roster_id), group_rows in groups.items():
        # Deduplicate by sleeper_player_id, keeping the first row -- a
        # player can never occupy two slots or be counted twice.
        seen: set = set()
        players: list[tuple[Any, Any, float, bool]] = []
        fantasy_team = None
        for row in group_rows:
            if fantasy_team is None:
                fantasy_team = getattr(row, "fantasy_team", None)
            player_id = getattr(row, "sleeper_player_id", None)
            if pd.isna(player_id) or player_id in seen:
                continue
            seen.add(player_id)
            points = getattr(row, "fantasy_points", None)
            players.append(
                (
                    player_id,
                    getattr(row, "position", None),
                    float(points) if not pd.isna(points) else 0.0,
                    bool(getattr(row, "started", False)),
                )
            )

        metrics = _week_metrics(players, start_slots)
        metrics["season"] = season
        metrics["week"] = week
        metrics["roster_id"] = int(roster_id)
        metrics["fantasy_team"] = fantasy_team
        weekly_rows.append(metrics)

    if not weekly_rows:
        return pd.DataFrame(columns=LINEUP_EFFICIENCY_COLUMNS)

    weekly_rows.sort(key=lambda row: (row["season"], row["week"], row["roster_id"]))

    result = pd.DataFrame(weekly_rows)
    result["season"] = result["season"].astype(int)
    result["week"] = result["week"].astype(int)
    result["roster_id"] = result["roster_id"].astype(int)
    result["suboptimal_starts"] = result["suboptimal_starts"].astype(int)
    result["suboptimal_sits"] = result["suboptimal_sits"].astype(int)
    for column in _WEEKLY_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    # Assigned as an explicit object-dtype Series, mirroring
    # performance.py's identical handling: pandas' string-dtype inference
    # would otherwise upcast a column mixing real labels with None.
    result["fantasy_team"] = pd.Series(result["fantasy_team"].tolist(), dtype=object)

    return result[LINEUP_EFFICIENCY_COLUMNS]


def build_roster_efficiency_metrics(
    player_week_df: pd.DataFrame,
    roster_positions: list[str],
) -> pd.DataFrame:
    """Build one row per ``(season, roster_id)`` of season roster-efficiency metrics.

    Aggregates :func:`build_lineup_efficiency_metrics`' weekly table over
    each roster-season: weeks played, total actual / optimal / bench /
    left-on-bench points, aggregate efficiency percentage, the number and
    fraction of suboptimal weeks, and the season totals of wrong starts and
    wrong sits. See the module docstring's "Season roster-efficiency
    summary" section for the exact definitions.

    Args:
        player_week_df: Same input contract as
            :func:`build_lineup_efficiency_metrics`.
        roster_positions: Same input contract as
            :func:`build_lineup_efficiency_metrics`.

    Returns:
        A DataFrame with columns :data:`ROSTER_EFFICIENCY_COLUMNS`, one row
        per ``(season, roster_id)`` present in the input, sorted by
        ascending ``season`` then ``roster_id``. ``efficiency_pct`` is
        ``NaN`` whenever the season's ``total_optimal_points <= 0``.
        Returns an empty DataFrame with the expected columns if the input
        is empty.
    """
    weekly = build_lineup_efficiency_metrics(player_week_df, roster_positions)
    if weekly.empty:
        return pd.DataFrame(columns=ROSTER_EFFICIENCY_COLUMNS)

    buckets: dict[tuple[int, Any], list] = {}
    for row in weekly.itertuples(index=False):
        buckets.setdefault((row.season, row.roster_id), []).append(row)

    season_rows: list[dict] = []
    for (season, roster_id), weeks in sorted(
        buckets.items(), key=lambda item: (item[0][0], str(item[0][1]))
    ):
        total_actual = math.fsum(week.actual_points for week in weeks)
        total_optimal = math.fsum(week.optimal_points for week in weeks)
        suboptimal_weeks = sum(1 for week in weeks if week.is_suboptimal)
        season_rows.append(
            {
                "season": season,
                "roster_id": roster_id,
                "fantasy_team": weeks[0].fantasy_team,
                "weeks_played": len(weeks),
                "total_actual_points": total_actual,
                "total_optimal_points": total_optimal,
                "total_bench_points": math.fsum(week.bench_points for week in weeks),
                "total_points_left_on_bench": math.fsum(
                    week.points_left_on_bench for week in weeks
                ),
                "efficiency_pct": (
                    total_actual / total_optimal if total_optimal > 0 else float("nan")
                ),
                "suboptimal_weeks": suboptimal_weeks,
                "suboptimal_week_pct": suboptimal_weeks / len(weeks),
                "total_suboptimal_starts": sum(
                    week.suboptimal_starts for week in weeks
                ),
                "total_suboptimal_sits": sum(week.suboptimal_sits for week in weeks),
            }
        )

    result = pd.DataFrame(season_rows)
    result["season"] = result["season"].astype(int)
    result["roster_id"] = result["roster_id"].astype(int)
    result["weeks_played"] = result["weeks_played"].astype(int)
    result["suboptimal_weeks"] = result["suboptimal_weeks"].astype(int)
    result["total_suboptimal_starts"] = result["total_suboptimal_starts"].astype(int)
    result["total_suboptimal_sits"] = result["total_suboptimal_sits"].astype(int)
    for column in _SEASON_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    result["fantasy_team"] = pd.Series(result["fantasy_team"].tolist(), dtype=object)

    return result[ROSTER_EFFICIENCY_COLUMNS]
