"""Compose a normalized ``LeagueSnapshot`` from raw Sleeper data.

This module is the composition layer for league normalization: it wires
together :func:`fantasy_analyzer.league.settings.normalize_league_settings`,
:func:`fantasy_analyzer.league.teams.build_team_mapping`, and
:func:`fantasy_analyzer.league.players.resolve_roster_players` into a single
``LeagueSnapshot`` object so downstream analytics never need to re-join raw
Sleeper endpoint responses. It performs no network access -- callers are
responsible for fetching the raw league, users, rosters, and player catalog
data first (see :func:`load_league_snapshot` for a thin fetching wrapper).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

import pandas as pd

from fantasy_analyzer.league.players import resolve_roster_players
from fantasy_analyzer.league.settings import LeagueSettings, normalize_league_settings
from fantasy_analyzer.league.teams import build_team_mapping
from fantasy_analyzer.sleeper.cache import DEFAULT_CACHE_PATH, get_players_cached
from fantasy_analyzer.sleeper.client import SleeperClient

#: Column order for the DataFrame produced by users_df normalization.
USERS_COLUMNS = ["user_id", "display_name", "team_name"]

#: Column order for the DataFrame produced by rosters_df normalization.
ROSTERS_COLUMNS = [
    "roster_id",
    "owner_id",
    "wins",
    "losses",
    "ties",
    "fpts",
    "fpts_against",
    "players",
    "starters",
]


@dataclass(frozen=True)
class LeagueSnapshot:
    """A normalized, self-contained snapshot of a Sleeper league.

    Assembles the outputs of ``league.settings``, ``league.teams``, and
    ``league.players`` into the common input downstream analytics should
    consume, per AGENTS.md's Core Domain Objects. Nothing here requires
    further raw Sleeper endpoint joins.

    Attributes:
        league: Normalized league metadata, scoring, and roster settings.
        teams_df: One row per roster describing its owner, from
            :func:`build_team_mapping`.
        users_df: One row per league user with columns
            ``["user_id", "display_name", "team_name"]``.
        rosters_df: One row per roster with columns ``["roster_id",
            "owner_id", "wins", "losses", "ties", "fpts", "fpts_against",
            "players", "starters"]``. ``fpts`` and ``fpts_against`` are
            combined floats -- see :func:`_combine_points_setting`.
        players_df: One row per distinct player ID appearing on any roster
            in the league, resolved via :func:`resolve_roster_players`.
        scoring_settings: Convenience passthrough of
            ``league.scoring_settings``.
        roster_positions: Convenience passthrough of
            ``league.roster_positions``.
    """

    league: LeagueSettings
    teams_df: pd.DataFrame
    users_df: pd.DataFrame
    rosters_df: pd.DataFrame
    players_df: pd.DataFrame
    scoring_settings: dict[str, float]
    roster_positions: list[str]


def _normalize_users_df(raw_users: list[dict]) -> pd.DataFrame:
    """Normalize raw Sleeper users into a minimal, predictable DataFrame."""
    rows = []
    for user in raw_users:
        display_name = user.get("display_name")
        team_name = (user.get("metadata") or {}).get("team_name") or display_name

        rows.append(
            {
                "user_id": user.get("user_id"),
                "display_name": display_name,
                "team_name": team_name,
            }
        )

    return pd.DataFrame(rows, columns=USERS_COLUMNS)


def _combine_points_setting(
    whole: Union[int, float, None], decimal: Union[int, float, None]
) -> Union[float, None]:
    """Combine Sleeper's split whole/decimal points settings into one float.

    Sleeper stores cumulative points (both ``fpts``/``fpts_decimal`` for
    points for, and ``fpts_against``/``fpts_against_decimal`` for points
    against) as a whole-number field plus a separate decimal field holding
    the fractional part as an integer 0-99 (e.g. ``fpts=1050,
    fpts_decimal=42`` means 1050.42 points). This combines the pair into a
    single float: ``whole + decimal / 100``.

    If ``whole`` is missing (``None``), the setting is considered entirely
    absent and ``None`` is returned -- this is the explicit missing-value
    rule, distinct from a real zero. If ``decimal`` is missing but ``whole``
    is present, the decimal part defaults to 0.
    """
    if whole is None:
        return None
    return whole + (decimal or 0) / 100


def _normalize_rosters_df(raw_rosters: list[dict]) -> pd.DataFrame:
    """Normalize raw Sleeper rosters into a minimal, predictable DataFrame."""
    rows = []
    for roster in raw_rosters:
        settings = roster.get("settings") or {}

        rows.append(
            {
                "roster_id": roster.get("roster_id"),
                "owner_id": roster.get("owner_id"),
                "wins": settings.get("wins"),
                "losses": settings.get("losses"),
                "ties": settings.get("ties"),
                "fpts": _combine_points_setting(
                    settings.get("fpts"), settings.get("fpts_decimal")
                ),
                "fpts_against": _combine_points_setting(
                    settings.get("fpts_against"), settings.get("fpts_against_decimal")
                ),
                "players": list(roster.get("players") or []),
                "starters": list(roster.get("starters") or []),
            }
        )

    return pd.DataFrame(rows, columns=ROSTERS_COLUMNS)


def _distinct_roster_player_ids(raw_rosters: list[dict]) -> list[str]:
    """Collect a league-wide, order-preserving, deduplicated player ID list."""
    seen: dict[str, None] = {}
    for roster in raw_rosters:
        for player_id in roster.get("players") or []:
            seen[player_id] = None

    return list(seen.keys())


def build_league_snapshot(
    raw_league: dict,
    raw_users: list[dict],
    raw_rosters: list[dict],
    player_catalog: dict,
) -> LeagueSnapshot:
    """Build a :class:`LeagueSnapshot` from already-fetched raw Sleeper data.

    This is the core, pure composition function: it performs no network
    access and expects callers to have already fetched ``raw_league``,
    ``raw_users``, ``raw_rosters``, and ``player_catalog`` (e.g. via
    ``SleeperClient`` and/or
    :func:`fantasy_analyzer.sleeper.cache.get_players_cached`).

    Args:
        raw_league: The raw dict returned by
            ``SleeperClient.get_league(league_id)``.
        raw_users: Raw league user dicts as returned by
            ``SleeperClient.get_users(league_id)``.
        raw_rosters: Raw league roster dicts as returned by
            ``SleeperClient.get_rosters(league_id)``.
        player_catalog: The raw Sleeper player catalog dict, keyed by
            ``player_id``, as returned by ``SleeperClient.get_players()`` or
            :func:`fantasy_analyzer.sleeper.cache.get_players_cached`.

    Returns:
        A fully populated ``LeagueSnapshot``. ``players_df`` contains one
        row per distinct player ID appearing across all rosters' ``players``
        lists (in first-seen order); IDs unresolvable against
        ``player_catalog`` produce ``None``/``NaN`` metadata rather than
        raising, per :func:`resolve_roster_players`.
    """
    league = normalize_league_settings(raw_league)
    teams_df = build_team_mapping(raw_users, raw_rosters)
    users_df = _normalize_users_df(raw_users)
    rosters_df = _normalize_rosters_df(raw_rosters)

    league_player_ids = _distinct_roster_player_ids(raw_rosters)
    players_df = resolve_roster_players(league_player_ids, player_catalog)

    return LeagueSnapshot(
        league=league,
        teams_df=teams_df,
        users_df=users_df,
        rosters_df=rosters_df,
        players_df=players_df,
        scoring_settings=league.scoring_settings,
        roster_positions=league.roster_positions,
    )


def load_league_snapshot(
    client: SleeperClient,
    league_id: str,
    player_cache_path: Union[str, Path] = DEFAULT_CACHE_PATH,
    force_refresh_players: bool = False,
) -> LeagueSnapshot:
    """Fetch raw Sleeper league data and build a ``LeagueSnapshot`` in one call.

    Thin convenience wrapper around :func:`build_league_snapshot` that
    performs the necessary ``SleeperClient`` calls (league, users, rosters)
    and loads the player catalog via
    :func:`fantasy_analyzer.sleeper.cache.get_players_cached`. Prefer
    :func:`build_league_snapshot` directly when the raw data has already
    been fetched or when testing without network access.

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league ID to snapshot.
        player_cache_path: Path to the local player catalog cache, passed
            through to :func:`get_players_cached`.
        force_refresh_players: If ``True``, force a fresh download of the
            player catalog instead of using any existing cache.

    Returns:
        A fully populated ``LeagueSnapshot``.
    """
    raw_league = client.get_league(league_id)
    raw_users = client.get_users(league_id)
    raw_rosters = client.get_rosters(league_id)
    player_catalog = get_players_cached(
        client, path=player_cache_path, force_refresh=force_refresh_players
    )

    return build_league_snapshot(raw_league, raw_users, raw_rosters, player_catalog)
