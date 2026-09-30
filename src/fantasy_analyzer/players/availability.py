"""Can a player play in a given week? Injuries and byes (FFA-107).

:mod:`fantasy_analyzer.players.roster_fit` (FFA-100) solved lineups in pure
projection space: every rostered player was assumed available every week.
Measured on a real roster, that put two players whose Sleeper
``injury_status`` was ``"Out"`` into the recommended starting lineup. This
module is the single definition of availability the lineup solver and the
dashboard share, so the rule lives in one place instead of being
re-implemented as a display filter.

The rule
--------------------------------------------------------------------------

A player is **unavailable in week** ``w`` -- judged from his status as of
``current_week``, the week about to be played -- iff either

.. code-block:: text

    w == bye_week
    current_week <= w < current_week + weeks_out(injury_status)

where ``weeks_out`` comes from :data:`DEFAULT_INJURY_WEEKS_OUT`. A status
describes *now*: it says nothing about a week already played, so a week
before ``current_week`` is never ruled out by injury.

``weeks_out`` per status, and why
--------------------------------------------------------------------------

Sleeper's ``injury_status`` vocabulary, measured on the 2026-09-29 catalog
(12,229 entries): ``None``, ``Questionable``, ``IR``, ``Out``, ``NA``,
``PUP``, ``Sus``, ``COV``, ``DNR``, and one empty string.

- ``Out``, ``Doubtful``, ``COV`` -> **1 week** (the coming week only).
  These are weekly game designations; next week's status is a new fact
  that a refreshed catalog will carry.
- ``IR``, ``PUP``, ``NA``, ``Sus``/``Suspended``, ``DNR`` -> **4 weeks**,
  counting the coming week. Four games is the NFL's minimum stay on
  reserve/injured, reserve/PUP and reserve/non-football-injury (Sleeper's
  ``NA``) once the season is under way. It is a **lower bound**: many IR
  stays are season-ending, and the catalog carries no
  ``injury_start_date`` to count from (``None`` for every ``IR`` entry in
  the catalog above). ``Sus`` and ``DNR`` ("did not report") have no
  published length at all, so they take the same horizon by analogy.

The lower bound is the deliberate side to err on. The decision this feeds
is a *drop*: overstating a rostered player's absence makes him look
droppable, which is precisely the failure FFA-107 exists to prevent.
Callers who know better (a season-ending injury, a known suspension
length) pass their own ``weeks_out`` mapping.

``Questionable`` is **startable**. A questionable player usually plays,
so he stays in the lineup and is merely flagged
(:data:`FLAGGED_INJURY_STATUSES`). An unrecognized status string is
likewise treated as available -- missing information is not evidence of
absence.

Regular season versus playoffs
--------------------------------------------------------------------------

Nothing here depends on the phase of the fantasy season. Byes only occur
in the NFL regular season, and the injury rule is phase-agnostic; which
weeks a decision is evaluated over is the caller's choice (see
:func:`~fantasy_analyzer.players.roster_fit.build_add_drop_candidates`).
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

import pandas as pd

#: Weeks, counting the week about to be played, that each Sleeper
#: ``injury_status`` keeps a player out of a lineup. See the module
#: docstring's "``weeks_out`` per status, and why" -- in particular that the
#: multi-week figures are the NFL's minimum stay, a lower bound.
DEFAULT_INJURY_WEEKS_OUT: dict[str, int] = {
    "Out": 1,
    "Doubtful": 1,
    "COV": 1,
    "IR": 4,
    "PUP": 4,
    "NA": 4,
    "Sus": 4,
    "Suspended": 4,
    "DNR": 4,
}

#: Sleeper ``injury_status`` values that rule a player out of the coming
#: week. Carries both ``"Sus"`` (what the live catalog actually emits) and
#: ``"Suspended"`` (the long form an older filter used): with only the long
#: form, a suspended player would have been started.
UNAVAILABLE_INJURY_STATUSES = frozenset(
    status for status, weeks in DEFAULT_INJURY_WEEKS_OUT.items() if weeks > 0
)

#: The subset of :data:`UNAVAILABLE_INJURY_STATUSES` that lasts beyond the
#: coming week under the default rule. A free agent with one of these is a
#: stash, not a pickup for this week's lineup.
LONG_TERM_INJURY_STATUSES = frozenset(
    status for status, weeks in DEFAULT_INJURY_WEEKS_OUT.items() if weeks > 1
)

#: Statuses that leave a player startable but worth a second look before
#: kickoff.
FLAGGED_INJURY_STATUSES = frozenset({"Questionable"})

#: Columns :func:`add_availability` appends.
AVAILABILITY_COLUMNS = ["on_bye", "available", "unavailable_reason"]


def normalize_injury_status(status: object) -> Optional[str]:
    """Collapse Sleeper's "no injury" spellings to ``None``.

    Args:
        status: A raw ``injury_status`` value.

    Returns:
        ``None`` for ``None``, ``NaN`` and blank strings (the catalog
        carries at least one ``""``); otherwise the stripped string.
    """
    if status is None:
        return None
    if isinstance(status, float) and pd.isna(status):
        return None
    text = str(status).strip()
    return text or None


def _as_week(value: object) -> Optional[int]:
    """A bye-week cell as ``int``, or ``None`` when absent/unparseable."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def injury_weeks_out(
    injury_status: object,
    *,
    weeks_out: Mapping[str, int] = DEFAULT_INJURY_WEEKS_OUT,
) -> int:
    """How many weeks, counting the coming week, a status keeps a player out.

    Args:
        injury_status: A raw Sleeper ``injury_status``.
        weeks_out: Status -> weeks mapping. Defaults to
            :data:`DEFAULT_INJURY_WEEKS_OUT`.

    Returns:
        ``0`` for a healthy player, a flagged-but-startable status such as
        ``"Questionable"``, or any status not in ``weeks_out``.
    """
    status = normalize_injury_status(injury_status)
    if status is None:
        return 0
    return max(0, int(weeks_out.get(status, 0)))


def is_available(
    injury_status: object,
    bye_week: object,
    week: int,
    *,
    current_week: int,
    weeks_out: Mapping[str, int] = DEFAULT_INJURY_WEEKS_OUT,
) -> bool:
    """Whether a player can play in ``week``, per the module docstring's rule.

    Worked example (hand-checkable). ``current_week = 4``, default
    ``weeks_out``:

    - An ``"Out"`` player with a week-9 bye misses weeks 4 and 9 only.
    - An ``"IR"`` player with a week-6 bye misses weeks 4-7 (the four-week
      minimum), which already covers his bye.
    - A ``"Questionable"`` player with no bye misses nothing.

    Args:
        injury_status: The player's Sleeper ``injury_status`` as of
            ``current_week``.
        bye_week: His NFL team's bye week, or ``None``/``NaN`` if unknown.
        week: The week being asked about.
        current_week: The week about to be played -- the week the status
            describes.
        weeks_out: Status -> weeks mapping.

    Returns:
        ``False`` if ``week`` is his bye or falls inside his injury
        absence, else ``True``.
    """
    if _as_week(bye_week) == week:
        return False
    out = injury_weeks_out(injury_status, weeks_out=weeks_out)
    return not (current_week <= week < current_week + out)


def unavailable_weeks(
    injury_status: object,
    bye_week: object,
    weeks: Iterable[int],
    *,
    current_week: int,
    weeks_out: Mapping[str, int] = DEFAULT_INJURY_WEEKS_OUT,
) -> frozenset[int]:
    """The subset of ``weeks`` a player cannot play, per :func:`is_available`.

    Args:
        injury_status: The player's Sleeper ``injury_status``.
        bye_week: His NFL team's bye week, or ``None``.
        weeks: The weeks to test.
        current_week: The week about to be played.
        weeks_out: Status -> weeks mapping.

    Returns:
        The weeks he is unavailable, as a frozen set.
    """
    return frozenset(
        week
        for week in weeks
        if not is_available(
            injury_status,
            bye_week,
            week,
            current_week=current_week,
            weeks_out=weeks_out,
        )
    )


def add_availability(
    players: pd.DataFrame,
    week: int,
    *,
    injury_column: str = "injury_status",
    bye_column: str = "bye_week",
    weeks_out: Mapping[str, int] = DEFAULT_INJURY_WEEKS_OUT,
) -> pd.DataFrame:
    """Append coming-week availability columns to a player frame.

    Adds :data:`AVAILABILITY_COLUMNS`:

    - ``on_bye`` -- his team's bye is ``week``.
    - ``available`` -- :func:`is_available` for ``week`` with
      ``current_week = week``. This is the column
      :func:`~fantasy_analyzer.players.roster_fit.optimal_lineup` honors.
    - ``unavailable_reason`` -- the injury status when that rules him out,
      else ``"Bye"`` when the bye does, else ``None``. Injury wins when
      both apply, because it is the reason that outlasts the week.

    Args:
        players: Any player frame. ``injury_column``/``bye_column`` are
            optional; a missing column reads as "no injury"/"no bye".
        week: The week about to be played.
        injury_column: Column holding Sleeper ``injury_status``.
        bye_column: Column holding the bye week.
        weeks_out: Status -> weeks mapping.

    Returns:
        A copy of ``players`` with the three columns appended.
    """
    result = players.copy()
    count = len(result)
    statuses = (
        list(result[injury_column])
        if injury_column in result.columns
        else [None] * count
    )
    byes = list(result[bye_column]) if bye_column in result.columns else [None] * count

    on_bye: list[bool] = []
    available: list[bool] = []
    reasons: list[Optional[str]] = []
    for status, bye in zip(statuses, byes):
        injured = injury_weeks_out(status, weeks_out=weeks_out) > 0
        bye_now = _as_week(bye) == week
        on_bye.append(bye_now)
        available.append(not (injured or bye_now))
        if injured:
            reasons.append(normalize_injury_status(status))
        elif bye_now:
            reasons.append("Bye")
        else:
            reasons.append(None)

    result["on_bye"] = pd.Series(on_bye, index=result.index, dtype=bool)
    result["available"] = pd.Series(available, index=result.index, dtype=bool)
    result["unavailable_reason"] = pd.Series(reasons, index=result.index, dtype=object)
    return result
