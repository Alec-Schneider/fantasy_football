"""Expected points for one side of a head-to-head matchup (FFA-113).

The Matchup tab (``docs/matchup_tab.md``) shows the lineup *actually set in
Sleeper* for both managers, slot by slot, with a projected final score.
:func:`build_matchup_side` produces one side of that, and generalizes the
locked-starter logic of the dashboard's ``_build_lineup`` to either roster.

Expected points per starter
--------------------------------------------------------------------------

The projected final is the sum of these over the startable slots:

.. code-block:: text

    state                                          expected_points      pending
    empty slot ("0", "", None, missing)            0                    no
    NFL game kicked off (in_progress / final)      live points (0.0)    no
    not kicked off, unavailable (Out/IR/bye/...)   0                    no
    not kicked off, available, no projection       0 (projection_missing) no
    not kicked off, available, projected           the projection       yes

"Live points" is Sleeper's ``players_points`` (``0.0`` for a player absent
from it). "Pending" marks the starters that still carry variance; the win
probability model sums a per-player variance over them.

Documented approximation: a game in progress is scored at its live points,
which **understates** it -- the remaining minutes are not projected. This
matches ``_build_lineup``'s treatment of locked starters; the dashboard's
two scheduled refreshes (after Thursday night, and Tuesday) never land
mid-game, so the error only arises from an unscheduled mid-game refresh.

Availability follows :func:`~fantasy_analyzer.players.availability.add_availability`
(injury wins over bye when both apply). With a non-empty ``game_states``
mapping, a player whose team has no game that week is on a bye; with an
empty one, only the ``byes`` mapping can say so and ``game_state`` is
``None``. Bench rows use the same rule but are never summed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

import pandas as pd

from fantasy_analyzer.players.availability import (
    add_availability,
    normalize_injury_status,
)
from fantasy_analyzer.players.opponent_strength import NflGameState, normalize_team
from fantasy_analyzer.players.roster_fit import starting_slots

#: SlotRow keys of ``docs/matchup_tab.md``, in order.
MATCHUP_SLOT_COLUMNS = [
    "slot",
    "player_id",
    "full_name",
    "position",
    "team",
    "nfl_opponent",
    "is_home",
    "kickoff",
    "game_state",
    "injury_status",
    "injury_body_part",
    "available",
    "unavailable_reason",
    "projection",
    "actual_points",
    "expected_points",
    "pending",
    "projection_missing",
    "ppg_to_date",
    "last3_ppg",
    "snap_share",
    "target_share",
]

#: Columns copied from the projection frame when present.
_CONTEXT_COLUMNS = ["ppg_to_date", "last3_ppg", "snap_share", "target_share"]

#: Object columns whose missing values stay ``None``.
_LABEL_COLUMNS = [
    "player_id",
    "full_name",
    "position",
    "team",
    "nfl_opponent",
    "is_home",
    "kickoff",
    "game_state",
    "injury_status",
    "injury_body_part",
    "unavailable_reason",
]

#: Injury statuses that are startable but worth flagging for a pending starter.
_FLAGGED_STATUSES = ("Questionable", "Doubtful")

_EMPTY_IDS = frozenset({"", "0"})


@dataclass(frozen=True)
class MatchupSide:
    """One manager's lineup for the week, with expected points and alerts."""

    starters: pd.DataFrame
    bench: pd.DataFrame
    projected_total: float
    live_points_total: float
    players_remaining: int
    alerts: list[dict]


def _clean(value: Any) -> Any:
    """``None`` for ``NaN``/``None``, else the value unchanged."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return value
    return value


def _is_empty_id(player_id: Any) -> bool:
    """Whether a Sleeper starters entry denotes an empty slot."""
    return _clean(player_id) is None or str(player_id).strip() in _EMPTY_IDS


def _catalog_name(entry: Mapping[str, Any]) -> Optional[str]:
    """``full_name``, else ``first_name last_name``, else ``None``."""
    name = _clean(entry.get("full_name"))
    if name:
        return str(name)
    joined = " ".join(
        str(part) for part in (entry.get("first_name"), entry.get("last_name")) if part
    )
    return joined or None


def _kickoff_text(game: Optional[NflGameState]) -> Optional[str]:
    """ISO 8601 kickoff with offset, or ``None``."""
    if game is None or game.kickoff is None:
        return None
    return game.kickoff.isoformat()


def _build_rows(
    entries: Sequence[tuple[str, Optional[str]]],
    projections: pd.DataFrame,
    catalog: Mapping[str, Mapping[str, Any]],
    live_points: Mapping[str, float],
    game_states: Mapping[str, NflGameState],
    week: int,
    byes: Mapping[str, Optional[int]],
    ppg_column: str,
) -> pd.DataFrame:
    """One :data:`MATCHUP_SLOT_COLUMNS` row per ``(slot, player_id)`` entry."""
    projection_rows: dict[str, Mapping[str, Any]] = {}
    if not projections.empty and "player_id" in projections.columns:
        for record in projections.to_dict("records"):
            projection_rows.setdefault(str(record["player_id"]), record)

    labels: list[dict[str, Any]] = []
    for slot, player_id in entries:
        if player_id is None:
            labels.append({})
            continue
        row = projection_rows.get(player_id, {})
        entry = catalog.get(player_id) or {}
        position = _clean(row.get("position")) or _clean(entry.get("position"))
        team = _clean(row.get("team")) or _clean(entry.get("team"))
        if team is None and position == "DEF":
            team = player_id
        team = None if team is None else str(team)
        nfl_team = normalize_team(team)
        game = game_states.get(nfl_team) if nfl_team is not None else None
        on_bye = bool(game_states) and nfl_team is not None and game is None
        labels.append(
            {
                "row": row,
                "full_name": _clean(row.get("full_name")) or _catalog_name(entry),
                "position": position,
                "team": team,
                "game": game,
                "injury_status": normalize_injury_status(entry.get("injury_status")),
                "injury_body_part": _clean(entry.get("injury_body_part")),
                # Setting bye_week to ``week`` lets add_availability apply its
                # own injury-over-bye precedence.
                "bye_week": week if on_bye else byes.get(nfl_team),
                "on_bye_by_schedule": on_bye,
            }
        )

    availability = add_availability(
        pd.DataFrame(
            {
                "injury_status": [label.get("injury_status") for label in labels],
                "bye_week": pd.Series(
                    [label.get("bye_week") for label in labels], dtype=object
                ),
            }
        ),
        week,
    )

    rows: list[dict[str, Any]] = []
    for (slot, player_id), label, available, reason in zip(
        entries,
        labels,
        availability["available"],
        availability["unavailable_reason"],
    ):
        record: dict[str, Any] = {column: None for column in MATCHUP_SLOT_COLUMNS}
        record["slot"] = slot
        if player_id is None:
            record.update(
                available=False,
                unavailable_reason="Empty slot",
                expected_points=0.0,
                pending=False,
                projection_missing=False,
            )
            rows.append(record)
            continue

        game: Optional[NflGameState] = label["game"]
        if label["on_bye_by_schedule"]:
            game_state: Optional[str] = "bye"
        else:
            game_state = game.state if game is not None else None
        kicked_off = game_state in ("in_progress", "final")
        available = bool(available)

        projection = _clean(label["row"].get(ppg_column))
        projection = None if projection is None else float(projection)
        actual = float(live_points.get(player_id, 0.0)) if kicked_off else None
        if kicked_off:
            expected = actual
        elif not available or projection is None:
            expected = 0.0
        else:
            expected = projection
        pending = (not kicked_off) and available and projection is not None

        record.update(
            player_id=player_id,
            full_name=label["full_name"],
            position=label["position"],
            team=label["team"],
            nfl_opponent=game.opponent if game is not None else None,
            is_home=game.is_home if game is not None else None,
            kickoff=_kickoff_text(game),
            game_state=game_state,
            injury_status=label["injury_status"],
            injury_body_part=label["injury_body_part"],
            available=available,
            unavailable_reason=_clean(reason),
            projection=projection,
            actual_points=actual,
            expected_points=float(expected),
            pending=bool(pending),
            projection_missing=bool(
                (not kicked_off) and available and projection is None
            ),
        )
        for column in _CONTEXT_COLUMNS:
            value = _clean(label["row"].get(column))
            record[column] = None if value is None else float(value)
        rows.append(record)

    frame = pd.DataFrame(rows, columns=MATCHUP_SLOT_COLUMNS)
    # Label columns keep ``None`` (JSON null) rather than pandas' NaN.
    for column in _LABEL_COLUMNS:
        frame[column] = pd.Series(
            [_clean(value) for value in frame[column]], index=frame.index, dtype=object
        )
    return frame


def build_matchup_side(
    starters: Sequence[Optional[str]],
    players: Sequence[str],
    roster_positions: Sequence[str],
    projections: pd.DataFrame,
    catalog: Mapping[str, Mapping[str, Any]],
    live_points: Mapping[str, float],
    game_states: Mapping[str, NflGameState],
    week: int,
    *,
    byes: Optional[Mapping[str, Optional[int]]] = None,
    reserve: Iterable[str] = (),
    ppg_column: str = "projected_ppg",
) -> MatchupSide:
    """Expected points, game states and alerts for one side of a matchup.

    See the module docstring for the expected-points rule table.

    Worked example (hand-checkable). Slots ``[QB, RB]``; the QB's game is
    final with 20.0 live points; the RB is unplayed and projected 10.0.
    Expected points are ``20.0`` and ``10.0``, so ``projected_total`` is
    ``30.0``, ``live_points_total`` is ``20.0`` and ``players_remaining``
    is ``1``.

    Args:
        starters: Sleeper's week ``starters``, aligned to
            ``starting_slots(roster_positions)``. ``"0"``, ``""``, ``None``
            or a missing trailing entry is an empty slot.
        players: Sleeper's week ``players`` (the whole roster).
        roster_positions: The league's roster slots.
        projections: Frame keyed by ``player_id`` carrying ``full_name``,
            ``position``, ``team``, ``ppg_column`` and optionally
            ``ppg_to_date``/``last3_ppg``/``snap_share``/``target_share``.
        catalog: Sleeper's player catalog; supplies labels for players
            without a projection row, and injury status for everyone.
        live_points: Sleeper's ``players_points``.
        game_states: :func:`~fantasy_analyzer.players.opponent_strength.nfl_game_states`
            output. Empty means "no schedule information".
        week: The week being played.
        byes: nflverse team -> bye week; consulted for bye status.
        reserve: Player ids on the IR slot (bench rows labelled ``IR``).
        ppg_column: The per-game projection column.

    Returns:
        A :class:`MatchupSide`. Alerts cover starters only, in slot order:
        an empty slot, the reason an unavailable starter yet to play can't
        play, a missing projection, and "Questionable"/"Doubtful" flags on
        pending starters (an Out/Doubtful player is unavailable, so
        "Doubtful" surfaces through the unavailable reason, once). Starters
        whose game has kicked off raise none.
    """
    byes = byes or {}
    slots = starting_slots(roster_positions)
    starter_ids: list[Optional[str]] = [
        None
        if index >= len(starters) or _is_empty_id(starters[index])
        else str(starters[index])
        for index in range(len(slots))
    ]
    starter_frame = _build_rows(
        list(zip(slots, starter_ids)),
        projections,
        catalog,
        live_points,
        game_states,
        week,
        byes,
        ppg_column,
    )

    reserve_ids = {str(player_id) for player_id in reserve}
    taken = {player_id for player_id in starter_ids if player_id is not None}
    bench_ids = sorted(
        {str(player_id) for player_id in players} - taken - _EMPTY_IDS
    )
    bench = _build_rows(
        [
            ("IR" if player_id in reserve_ids else "BN", player_id)
            for player_id in bench_ids
        ],
        projections,
        catalog,
        live_points,
        game_states,
        week,
        byes,
        ppg_column,
    )
    # Stable sort over the player_id-ordered rows: projection desc, None last.
    bench = bench.assign(_none=bench["projection"].isna()).sort_values(
        ["_none", "projection"], ascending=[True, False], kind="stable"
    )
    bench = bench.drop(columns="_none").reset_index(drop=True)

    alerts: list[dict] = []
    for row in starter_frame.to_dict("records"):
        def alert(reason: str) -> None:
            alerts.append(
                {
                    "player_id": row["player_id"],
                    "full_name": row["full_name"],
                    "slot": row["slot"],
                    "reason": reason,
                }
            )

        if row["player_id"] is None:
            alert("Empty slot")
            continue
        if row["game_state"] in ("in_progress", "final"):
            continue
        if not row["available"]:
            alert(str(row["unavailable_reason"]))
        if row["projection_missing"]:
            alert("No projection")
        if row["pending"] and row["injury_status"] in _FLAGGED_STATUSES:
            alert(str(row["injury_status"]))

    return MatchupSide(
        starters=starter_frame,
        bench=bench,
        projected_total=math.fsum(starter_frame["expected_points"]),
        live_points_total=math.fsum(starter_frame["actual_points"].dropna()),
        players_remaining=int(starter_frame["pending"].sum()),
        alerts=alerts,
    )


def build_position_edges(
    my_starters: pd.DataFrame, opponent_starters: pd.DataFrame
) -> pd.DataFrame:
    """Projected-points difference per slot group, me minus opponent.

    Sums ``expected_points`` by ``slot`` (so two RB slots form one ``RB``
    group, and ``FLEX`` is its own). Groups appear in order of first
    appearance in ``my_starters``, then any only the opponent has; a side
    lacking a group counts ``0.0``. A tied group has ``edge == 0.0``.

    Args:
        my_starters: ``MatchupSide.starters`` for me.
        opponent_starters: ``MatchupSide.starters`` for the opponent.

    Returns:
        A frame with columns ``group, me, opponent, edge``.
    """

    def totals(frame: pd.DataFrame) -> dict[str, float]:
        sums: dict[str, list[float]] = {}
        for slot, points in zip(frame["slot"], frame["expected_points"]):
            sums.setdefault(slot, []).append(float(points))
        return {slot: math.fsum(values) for slot, values in sums.items()}

    mine, theirs = totals(my_starters), totals(opponent_starters)
    groups = list(mine) + [group for group in theirs if group not in mine]
    return pd.DataFrame(
        {
            "group": groups,
            "me": [mine.get(group, 0.0) for group in groups],
            "opponent": [theirs.get(group, 0.0) for group in groups],
            "edge": [
                mine.get(group, 0.0) - theirs.get(group, 0.0) for group in groups
            ],
        },
        columns=["group", "me", "opponent", "edge"],
    )
