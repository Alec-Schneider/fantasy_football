"""Pair weekly Sleeper matchup entries into head-to-head opponents.

Sleeper's raw weekly matchup entries (see
:func:`~fantasy_analyzer.matchups.loader.collect_season_matchups`) are a flat
list of one row per roster, each tagged with a ``matchup_id`` shared by the
two rosters that played each other that week. This module groups those flat
entries by ``matchup_id`` into head-to-head pairs.

This is pairing only -- it does not derive winner/loser/margin (that is
downstream outcome normalization, FFA-032) and it does not resolve
``roster_id`` to an owner (see
:func:`~fantasy_analyzer.league.teams.build_team_mapping`).

Bye and incomplete cases
-------------------------

A standard two-team Sleeper matchup produces exactly two entries sharing one
``matchup_id``. Two cases fall short of that:

- **Bye**: Sleeper represents a roster with no opponent that week (e.g. an
  odd-sized league) with ``matchup_id: null`` on that roster's entry. Each
  such entry is its own unpaired :class:`MatchupPairing` -- multiple byes in
  the same week are never paired with each other, since a ``None``
  ``matchup_id`` does not mean "these rosters share a matchup."
- **Incomplete data**: a non-``null`` ``matchup_id`` shared by only one
  roster entry (e.g. a partially-loaded week) is also treated as an unpaired
  :class:`MatchupPairing`, preserving the real ``matchup_id`` rather than
  discarding it.

In both cases ``roster_2_id`` and ``points_2`` are ``None``.

A non-``null`` ``matchup_id`` shared by *more than two* roster entries is a
data-integrity anomaly under Sleeper's standard head-to-head format -- there
is no correct way to infer who played whom without guessing, and a wrong
guess would silently corrupt every downstream metric. :func:`pair_week_matchups`
raises ``ValueError`` for this case rather than picking an arbitrary pairing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fantasy_analyzer.matchups.loader import WeekMatchups


@dataclass(frozen=True)
class MatchupPairing:
    """One matchup within a week, with opponents paired by shared matchup_id.

    Attributes:
        season: Season label, carried through from the source
            ``WeekMatchups`` unchanged.
        week: The week number this matchup belongs to.
        is_playoff: Whether this matchup falls within a playoff week, carried
            through from the source ``WeekMatchups``.
        matchup_id: The raw Sleeper ``matchup_id`` shared by both roster
            entries, or ``None`` for a roster entry Sleeper tagged as a bye
            (no ``matchup_id`` at all).
        roster_1_id: The lower of the two paired ``roster_id``s, or the sole
            ``roster_id`` for a bye/incomplete case. Pairs are ordered by
            ascending ``roster_id`` rather than raw Sleeper entry order, so
            pairing output is deterministic regardless of input ordering.
        roster_2_id: The other paired ``roster_id``, or ``None`` if this
            matchup had no second roster entry (bye or incomplete data).
        points_1: ``roster_1_id``'s raw reported points for the week, exactly
            as Sleeper returned it (unvalidated, un-derived).
        points_2: ``roster_2_id``'s raw reported points for the week, or
            ``None`` when there is no ``roster_2_id``.
    """

    season: Optional[str]
    week: int
    is_playoff: bool
    matchup_id: Optional[int]
    roster_1_id: int
    roster_2_id: Optional[int]
    points_1: Optional[float]
    points_2: Optional[float]


def _build_pairing(
    week: WeekMatchups,
    matchup_id: Optional[int],
    entry_1: dict,
    entry_2: Optional[dict],
) -> MatchupPairing:
    return MatchupPairing(
        season=week.season,
        week=week.week,
        is_playoff=week.is_playoff,
        matchup_id=matchup_id,
        roster_1_id=entry_1["roster_id"],
        roster_2_id=entry_2["roster_id"] if entry_2 is not None else None,
        points_1=entry_1.get("points"),
        points_2=entry_2.get("points") if entry_2 is not None else None,
    )


def pair_week_matchups(week: WeekMatchups) -> list[MatchupPairing]:
    """Pair one week's flat Sleeper matchup entries by shared ``matchup_id``.

    Args:
        week: One week of raw matchup entries, as produced by
            :func:`~fantasy_analyzer.matchups.loader.collect_season_matchups`.

    Returns:
        One :class:`MatchupPairing` per distinct matchup and per bye entry
        in ``week.matchups``, sorted by ascending ``roster_1_id``. See the
        module docstring for how byes and incomplete matchup groups are
        represented.

    Raises:
        ValueError: If a non-``null`` ``matchup_id`` is shared by more than
            two roster entries -- see the module docstring.
    """
    groups: dict[int, list[dict]] = {}
    byes: list[dict] = []

    for entry in week.matchups:
        matchup_id = entry.get("matchup_id")
        if matchup_id is None:
            byes.append(entry)
        else:
            groups.setdefault(matchup_id, []).append(entry)

    pairings: list[MatchupPairing] = []

    for matchup_id, entries in groups.items():
        entries = sorted(entries, key=lambda e: e["roster_id"])
        if len(entries) > 2:
            roster_ids = [e["roster_id"] for e in entries]
            raise ValueError(
                f"week {week.week} matchup_id {matchup_id!r} has "
                f"{len(entries)} roster entries (expected at most 2): "
                f"roster_ids={roster_ids}"
            )
        entry_2 = entries[1] if len(entries) == 2 else None
        pairings.append(_build_pairing(week, matchup_id, entries[0], entry_2))

    for entry in byes:
        pairings.append(_build_pairing(week, None, entry, None))

    return sorted(pairings, key=lambda pairing: pairing.roster_1_id)


def pair_season_matchups(weeks: list[WeekMatchups]) -> list[MatchupPairing]:
    """Pair opponents for every week in a season.

    Thin wrapper that applies :func:`pair_week_matchups` to each week in
    turn, preserving week order.

    Args:
        weeks: One ``WeekMatchups`` per relevant week, as produced by
            :func:`~fantasy_analyzer.matchups.loader.collect_season_matchups`
            or :func:`~fantasy_analyzer.matchups.loader.load_season_matchups`.

    Returns:
        All ``MatchupPairing`` rows across every week, in the same week
        order as ``weeks``, with each week's pairings sorted by ascending
        ``roster_1_id``.
    """
    pairings: list[MatchupPairing] = []
    for week in weeks:
        pairings.extend(pair_week_matchups(week))
    return pairings
