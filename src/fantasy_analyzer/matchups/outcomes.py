"""Derive winner/loser/tie/margin outcomes for paired weekly matchups.

Builds on :mod:`~fantasy_analyzer.matchups.pairing`'s ``MatchupPairing`` --
that module explicitly deferred outcome derivation here (see its module
docstring): who won, who lost, whether the matchup was a tie, and the
scoring margin/differential between the two rosters.

Owner resolution (mapping ``roster_id`` to a manager) is still out of
scope; ``winner_roster_id``/``loser_roster_id`` are raw Sleeper roster IDs,
consistent with AGENTS.md's preference for immutable IDs over display
labels. FFA-033's season matchup DataFrame is expected to join those IDs
to owner labels downstream.

Outcome logic
-------------

For a complete matchup (both ``roster_2_id`` and both rosters' ``points``
present):

- **point_differential** -- ``points_1 - points_2``, signed from
  ``roster_1_id``'s perspective (positive means roster 1 scored more).
- **margin** -- ``abs(point_differential)``, the non-negative margin of
  victory (or ``0.0`` for a tie). ``winner``/``loser`` already carry
  direction, so ``margin`` itself does not need to.
- **is_tie** -- ``True`` when ``points_1 == points_2``. Both
  ``winner_roster_id`` and ``loser_roster_id`` are ``None`` in this case --
  a tie has neither.
- **winner_roster_id** / **loser_roster_id** -- whichever of
  ``roster_1_id`` / ``roster_2_id`` scored higher / lower, or ``None`` for
  both when tied.

Incomplete matchups (byes / partial data)
-------------------------------------------

A matchup with no second roster (a bye, or a non-``null`` ``matchup_id``
missing its second entry -- see ``pairing.py``) has no opponent to compare
against. The same applies if either side's ``points`` is missing (e.g. an
unloaded week). In both cases this module makes **no** guess: all outcome
fields are ``None``/``False`` (``winner_roster_id``, ``loser_roster_id``,
``margin``, and ``point_differential`` are ``None``; ``is_tie`` is
``False``) rather than treating a missing opponent as a loss, a win, or a
0-0 tie.

Regular season vs. playoffs
------------------------------

This module does not treat playoff weeks any differently from regular
season weeks -- ``is_playoff`` is carried through from the source
``MatchupPairing`` unchanged, and winner/loser/tie/margin are derived
identically regardless of season phase. Phase-specific analysis (e.g.
playoffs-only head-to-head) is downstream of this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fantasy_analyzer.matchups.pairing import MatchupPairing


@dataclass(frozen=True)
class MatchupOutcome:
    """A ``MatchupPairing`` enriched with derived winner/loser/tie/margin.

    Carries every ``MatchupPairing`` field unchanged, plus the outcome
    fields derived by :func:`derive_matchup_outcome`.

    Attributes:
        season: Season label, carried through unchanged.
        week: The week number this matchup belongs to.
        is_playoff: Whether this matchup falls within a playoff week,
            carried through unchanged.
        matchup_id: The raw Sleeper ``matchup_id``, or ``None`` for a bye.
        roster_1_id: The lower of the two paired ``roster_id``s (or the
            sole ``roster_id`` for a bye/incomplete case).
        roster_2_id: The other paired ``roster_id``, or ``None``.
        points_1: ``roster_1_id``'s raw reported points.
        points_2: ``roster_2_id``'s raw reported points, or ``None``.
        winner_roster_id: The ``roster_id`` that scored more points, or
            ``None`` if tied or if the matchup is incomplete (see module
            docstring).
        loser_roster_id: The ``roster_id`` that scored fewer points, or
            ``None`` if tied or incomplete.
        is_tie: ``True`` if both rosters scored identical points.
            ``False`` for an incomplete matchup -- a missing opponent is
            not a tie.
        margin: ``abs(points_1 - points_2)``, the non-negative margin of
            victory (``0.0`` for a tie), or ``None`` if incomplete.
        point_differential: ``points_1 - points_2``, signed from
            ``roster_1_id``'s perspective, or ``None`` if incomplete.
    """

    season: Optional[str]
    week: int
    is_playoff: bool
    matchup_id: Optional[int]
    roster_1_id: int
    roster_2_id: Optional[int]
    points_1: Optional[float]
    points_2: Optional[float]
    winner_roster_id: Optional[int]
    loser_roster_id: Optional[int]
    is_tie: bool
    margin: Optional[float]
    point_differential: Optional[float]


def derive_matchup_outcome(pairing: MatchupPairing) -> MatchupOutcome:
    """Derive winner/loser/tie/margin for one paired matchup.

    Args:
        pairing: A single paired matchup, as produced by
            :func:`~fantasy_analyzer.matchups.pairing.pair_week_matchups`.

    Returns:
        A :class:`MatchupOutcome` carrying ``pairing``'s fields unchanged
        plus the derived outcome fields. See the module docstring for the
        exact outcome logic and the incomplete-matchup edge case.
    """
    if (
        pairing.roster_2_id is None
        or pairing.points_1 is None
        or pairing.points_2 is None
    ):
        return MatchupOutcome(
            season=pairing.season,
            week=pairing.week,
            is_playoff=pairing.is_playoff,
            matchup_id=pairing.matchup_id,
            roster_1_id=pairing.roster_1_id,
            roster_2_id=pairing.roster_2_id,
            points_1=pairing.points_1,
            points_2=pairing.points_2,
            winner_roster_id=None,
            loser_roster_id=None,
            is_tie=False,
            margin=None,
            point_differential=None,
        )

    point_differential = pairing.points_1 - pairing.points_2
    margin = abs(point_differential)

    if point_differential == 0:
        winner_roster_id: Optional[int] = None
        loser_roster_id: Optional[int] = None
        is_tie = True
    elif point_differential > 0:
        winner_roster_id = pairing.roster_1_id
        loser_roster_id = pairing.roster_2_id
        is_tie = False
    else:
        winner_roster_id = pairing.roster_2_id
        loser_roster_id = pairing.roster_1_id
        is_tie = False

    return MatchupOutcome(
        season=pairing.season,
        week=pairing.week,
        is_playoff=pairing.is_playoff,
        matchup_id=pairing.matchup_id,
        roster_1_id=pairing.roster_1_id,
        roster_2_id=pairing.roster_2_id,
        points_1=pairing.points_1,
        points_2=pairing.points_2,
        winner_roster_id=winner_roster_id,
        loser_roster_id=loser_roster_id,
        is_tie=is_tie,
        margin=margin,
        point_differential=point_differential,
    )


def derive_season_outcomes(pairings: list[MatchupPairing]) -> list[MatchupOutcome]:
    """Derive outcomes for every paired matchup in a season.

    Thin wrapper that applies :func:`derive_matchup_outcome` to each
    pairing in turn, preserving order.

    Args:
        pairings: Paired matchups, as produced by
            :func:`~fantasy_analyzer.matchups.pairing.pair_season_matchups`.

    Returns:
        One :class:`MatchupOutcome` per input pairing, in the same order.
    """
    return [derive_matchup_outcome(pairing) for pairing in pairings]
