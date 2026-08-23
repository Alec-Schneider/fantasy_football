"""Load a full season of raw Sleeper matchups, week by week.

This module retrieves and organizes raw weekly matchup responses; it does
not pair opponents or derive outcomes -- that is downstream matchup
normalization. Each week is retained with its week number, playoff status
(per the league's :class:`~fantasy_analyzer.league.season.SeasonBoundaries`),
and the raw Sleeper matchup entries untouched.

The composition core (:func:`collect_season_matchups`) performs no network
access; :func:`load_season_matchups` is the thin fetching wrapper around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from fantasy_analyzer.league.season import SeasonBoundaries, is_playoff_week
from fantasy_analyzer.sleeper.client import SleeperClient


@dataclass(frozen=True)
class WeekMatchups:
    """One week of raw Sleeper matchups, tagged with season-phase metadata.

    Attributes:
        season: Season label for the league (Sleeper's native string form,
            e.g. ``"2025"``), or ``None`` if the caller did not supply one.
        week: The week number these matchups belong to.
        is_playoff: Whether ``week`` falls within the league's playoff
            weeks, per the boundaries supplied at load time.
        matchups: The raw Sleeper matchup entries for the week, exactly as
            returned by ``SleeperClient.get_matchups``. Empty if Sleeper
            returned no matchup data for the week.
    """

    season: Optional[str]
    week: int
    is_playoff: bool
    matchups: list[dict]


def collect_season_matchups(
    raw_weekly_matchups: Mapping[int, Optional[list[dict]]],
    boundaries: SeasonBoundaries,
    season: Optional[str] = None,
) -> list[WeekMatchups]:
    """Organize already-fetched weekly matchups into tagged ``WeekMatchups``.

    Pure composition core: performs no network access and expects callers
    to have already fetched each week's raw matchups (e.g. via
    ``SleeperClient.get_matchups``).

    Args:
        raw_weekly_matchups: Raw Sleeper matchup lists keyed by week number.
        boundaries: Season boundaries for the league, as produced by
            :func:`~fantasy_analyzer.league.season.derive_season_boundaries`.
            Defines which weeks are relevant and which are playoffs.
        season: Optional season label to retain on every week (e.g.
            ``LeagueSettings.season``). Treated as an opaque label.

    Returns:
        One ``WeekMatchups`` per week in ``boundaries`` (regular season
        followed by playoffs, i.e. ascending week order), each tagged with
        ``is_playoff``. A week missing from ``raw_weekly_matchups``, or
        whose value is ``None`` (Sleeper returns ``null`` for some
        unplayed weeks), is retained with an empty ``matchups`` list
        rather than dropped, so downstream code sees every relevant week
        explicitly.
    """
    weeks = list(boundaries.regular_season_weeks) + list(boundaries.playoff_weeks)

    return [
        WeekMatchups(
            season=season,
            week=week,
            is_playoff=is_playoff_week(week, boundaries),
            matchups=list(raw_weekly_matchups.get(week) or []),
        )
        for week in weeks
    ]


def load_season_matchups(
    client: SleeperClient,
    league_id: str,
    boundaries: SeasonBoundaries,
    season: Optional[str] = None,
) -> list[WeekMatchups]:
    """Fetch every relevant week of Sleeper matchups for a league season.

    Thin convenience wrapper around :func:`collect_season_matchups` that
    calls ``SleeperClient.get_matchups`` once per week in ``boundaries``.
    Prefer :func:`collect_season_matchups` directly when the raw weekly
    data has already been fetched or when testing without network access.

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league ID to load matchups for.
        boundaries: Season boundaries for the league, defining which weeks
            to fetch and which are playoffs.
        season: Optional season label to retain on every week (e.g.
            ``LeagueSettings.season``).

    Returns:
        One ``WeekMatchups`` per relevant week, in ascending week order,
        with playoff status tagged and raw matchup entries retained.
    """
    weeks = list(boundaries.regular_season_weeks) + list(boundaries.playoff_weeks)
    raw_weekly_matchups = {week: client.get_matchups(league_id, week) for week in weeks}

    return collect_season_matchups(raw_weekly_matchups, boundaries, season=season)
