"""Derive regular-season and playoff week boundaries for a league.

Sleeper's league settings expose ``playoff_week_start`` (the first playoff
week) but do not expose a single canonical "total weeks in the fantasy
season" field. That value is implied by how many playoff rounds a league
plays, and it varies by season (e.g. the NFL/Sleeper fantasy season is 18
weeks in 2025). Per AGENTS.md, library logic must not silently hardcode a
season-specific assumption like "the season is 18 weeks" -- callers must
supply ``total_weeks`` explicitly for the season they are analyzing.

This module performs no network access -- callers are responsible for
constructing a :class:`~fantasy_analyzer.league.settings.LeagueSettings`
first (e.g. via :func:`~fantasy_analyzer.league.settings.normalize_league_settings`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fantasy_analyzer.league.settings import LeagueSettings


@dataclass(frozen=True)
class SeasonBoundaries:
    """Explicit regular-season and playoff week ranges for a league season.

    Attributes:
        regular_season_weeks: Enumerated list of regular-season week
            numbers, e.g. ``[1, 2, ..., 14]``.
        playoff_weeks: Enumerated list of playoff week numbers, e.g.
            ``[15, 16, 17, 18]``.
        playoff_week_start: The first playoff week, as sourced from the
            league's settings. ``None`` if the league's settings did not
            specify one.
        total_weeks: The total number of weeks in the season, as supplied
            by the caller.
    """

    regular_season_weeks: list[int]
    playoff_weeks: list[int]
    playoff_week_start: Optional[int]
    total_weeks: int


def derive_season_boundaries(
    league_settings: LeagueSettings, total_weeks: int
) -> SeasonBoundaries:
    """Derive explicit regular-season and playoff week ranges.

    Weeks 1 through ``playoff_week_start - 1`` are regular season; weeks
    ``playoff_week_start`` through ``total_weeks`` (inclusive) are playoffs.

    Args:
        league_settings: Normalized league settings, as produced by
            :func:`~fantasy_analyzer.league.settings.normalize_league_settings`.
        total_weeks: The total number of weeks in the fantasy season (e.g.
            ``18`` for the 2025 NFL season). This is season-specific and
            must be supplied explicitly by the caller rather than assumed
            by this module.

    Returns:
        A :class:`SeasonBoundaries` with explicit, enumerable week lists.

        If ``league_settings.playoff_week_start`` is ``None`` (missing or
        malformed settings), the entire ``1..total_weeks`` range is treated
        as regular season and ``playoff_weeks`` is empty -- there is no
        reliable way to know where the postseason begins, so this module
        conservatively assumes there isn't one rather than guessing.

        If ``playoff_week_start`` is at or beyond ``total_weeks + 1``, or
        the league is misconfigured such that no playoff weeks fit within
        ``total_weeks``, ``playoff_weeks`` is empty rather than raising.

        If ``playoff_week_start == 1``, ``regular_season_weeks`` is empty
        (the entire season is playoffs) rather than raising.
    """
    playoff_week_start = league_settings.playoff_week_start

    if playoff_week_start is None:
        return SeasonBoundaries(
            regular_season_weeks=list(range(1, total_weeks + 1)),
            playoff_weeks=[],
            playoff_week_start=None,
            total_weeks=total_weeks,
        )

    regular_season_weeks = list(range(1, min(playoff_week_start, total_weeks + 1)))
    playoff_weeks = list(range(playoff_week_start, total_weeks + 1))

    return SeasonBoundaries(
        regular_season_weeks=regular_season_weeks,
        playoff_weeks=playoff_weeks,
        playoff_week_start=playoff_week_start,
        total_weeks=total_weeks,
    )


def is_playoff_week(week: int, boundaries: SeasonBoundaries) -> bool:
    """Return whether ``week`` falls within ``boundaries.playoff_weeks``.

    Args:
        week: The week number to check.
        boundaries: Season boundaries, as produced by
            :func:`derive_season_boundaries`.

    Returns:
        ``True`` if ``week`` is a playoff week, ``False`` otherwise
        (including for weeks outside ``1..total_weeks``).
    """
    return week in boundaries.playoff_weeks
