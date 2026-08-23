"""Normalize raw Sleeper league metadata, scoring, and roster settings.

This module converts the raw response of
:meth:`fantasy_analyzer.sleeper.client.SleeperClient.get_league` into a
typed, predictable structure so downstream code never needs to understand
Sleeper's raw ``settings`` / ``scoring_settings`` shapes. It performs no
network access -- callers are responsible for fetching the raw league dict
first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LeagueSettings:
    """Normalized league metadata, scoring settings, and roster rules.

    Attributes:
        league_id: Sleeper's immutable league identifier.
        name: League display name. This is a label, not a key.
        season: Season year, as a string (Sleeper's native representation,
            e.g. ``"2025"``).
        season_type: Sleeper season type (e.g. ``"regular"``).
        status: League status (e.g. ``"in_season"``, ``"complete"``).
        total_rosters: Number of rosters/teams in the league.
        scoring_settings: Mapping of Sleeper scoring category -> point
            value (e.g. ``{"pass_td": 4, "rec": 0.5}``).
        roster_positions: Ordered list of roster slots, including bench
            slots (e.g. ``["QB", "RB", "RB", ..., "BN", "BN"]``).
        playoff_week_start: First week of the playoffs, if configured.
        playoff_teams: Number of teams that make the playoffs, if
            configured.
        waiver_type: Sleeper's numeric waiver type code, if configured.
        waiver_budget: FAAB budget, if configured.
        trade_deadline: Last week trades are allowed, if configured.
        draft_id: Associated draft ID, if present.
        previous_league_id: The prior season's league ID, if this league is
            a continuation of one, else ``None``.
    """

    league_id: Optional[str]
    name: Optional[str]
    season: Optional[str]
    season_type: Optional[str]
    status: Optional[str]
    total_rosters: Optional[int]
    scoring_settings: dict[str, float] = field(default_factory=dict)
    roster_positions: list[str] = field(default_factory=list)
    playoff_week_start: Optional[int] = None
    playoff_teams: Optional[int] = None
    waiver_type: Optional[int] = None
    waiver_budget: Optional[int] = None
    trade_deadline: Optional[int] = None
    draft_id: Optional[str] = None
    previous_league_id: Optional[str] = None


def normalize_league_settings(raw_league: dict) -> LeagueSettings:
    """Build a :class:`LeagueSettings` from a raw Sleeper league response.

    Missing or absent optional fields do not raise -- they are surfaced as
    ``None`` (or an empty dict/list for ``scoring_settings`` /
    ``roster_positions``) so downstream code can rely on the attribute
    always being present with a predictable type.

    Args:
        raw_league: The raw dict returned by
            ``SleeperClient.get_league(league_id)``.

    Returns:
        A normalized, typed ``LeagueSettings`` instance.
    """
    settings = raw_league.get("settings") or {}

    return LeagueSettings(
        league_id=raw_league.get("league_id"),
        name=raw_league.get("name"),
        season=raw_league.get("season"),
        season_type=raw_league.get("season_type"),
        status=raw_league.get("status"),
        total_rosters=raw_league.get("total_rosters"),
        scoring_settings=dict(raw_league.get("scoring_settings") or {}),
        roster_positions=list(raw_league.get("roster_positions") or []),
        playoff_week_start=settings.get("playoff_week_start"),
        playoff_teams=settings.get("playoff_teams"),
        waiver_type=settings.get("waiver_type"),
        waiver_budget=settings.get("waiver_budget"),
        trade_deadline=settings.get("trade_deadline"),
        draft_id=raw_league.get("draft_id"),
        previous_league_id=raw_league.get("previous_league_id"),
    )
