"""Resolve raw Sleeper player IDs into player metadata.

A roster's ``players`` / ``starters`` lists (see
``SleeperClient.get_rosters()``) are bare Sleeper ``player_id`` strings. This
module resolves those IDs against a Sleeper player catalog -- as returned by
``SleeperClient.get_players()`` or
:func:`fantasy_analyzer.sleeper.cache.get_players_cached` -- into readable
metadata (name, position, NFL team). It performs no network access -- callers
are responsible for fetching/caching the player catalog first.

Not every ID in a roster's ``players`` list is guaranteed to be present in
the catalog: defense/special-teams "players" are sometimes represented by
team abbreviations (e.g. ``"BUF"``) rather than numeric player IDs, and a
stale cached catalog may be missing players who have since retired or been
dropped from Sleeper entirely. Resolution never raises for these cases --
unresolvable IDs come back with the ``player_id`` preserved and ``None`` for
every other field, so callers can see exactly what wasn't resolved.
"""

from __future__ import annotations

import pandas as pd

#: Column order for the DataFrame returned by :func:`resolve_roster_players`.
PLAYER_RESOLUTION_COLUMNS = ["player_id", "full_name", "position", "team"]


def resolve_player(player_id: str, player_catalog: dict) -> dict:
    """Resolve a single Sleeper ``player_id`` against a player catalog.

    Args:
        player_id: A Sleeper player ID, as it appears in a roster's
            ``players`` / ``starters`` list.
        player_catalog: The raw Sleeper player catalog dict, keyed by
            ``player_id``, as returned by ``SleeperClient.get_players()``.

    Returns:
        A dict with keys ``player_id``, ``full_name``, ``position``, and
        ``team``. When ``player_id`` is not present in ``player_catalog``
        (e.g. a team-abbreviation defense ID or a retired/dropped player
        missing from a stale cache), ``full_name``, ``position``, and
        ``team`` are all ``None`` -- ``player_id`` is always preserved.
    """
    player = player_catalog.get(player_id)

    if player is None:
        return {
            "player_id": player_id,
            "full_name": None,
            "position": None,
            "team": None,
        }

    full_name = player.get("full_name")
    if not full_name:
        first_name = player.get("first_name")
        last_name = player.get("last_name")
        if first_name or last_name:
            full_name = " ".join(part for part in (first_name, last_name) if part)

    return {
        "player_id": player_id,
        "full_name": full_name,
        "position": player.get("position"),
        "team": player.get("team"),
    }


def resolve_roster_players(player_ids: list[str], player_catalog: dict) -> pd.DataFrame:
    """Resolve a roster's player IDs into a metadata DataFrame.

    Args:
        player_ids: Sleeper player IDs, as they appear in a roster's
            ``players`` (or ``starters``) list.
        player_catalog: The raw Sleeper player catalog dict, keyed by
            ``player_id``, as returned by ``SleeperClient.get_players()``.

    Returns:
        A DataFrame with one row per entry in ``player_ids`` (duplicates
        preserved, in the original order) and columns ``["player_id",
        "full_name", "position", "team"]``. IDs absent from
        ``player_catalog`` produce a row with ``None`` for every field
        except ``player_id`` rather than raising.
    """
    rows = [resolve_player(player_id, player_catalog) for player_id in player_ids]
    return pd.DataFrame(rows, columns=PLAYER_RESOLUTION_COLUMNS)
