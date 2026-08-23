"""Normalize Sleeper owners and rosters into a stable team mapping.

This module joins the raw ``get_users()`` and ``get_rosters()`` responses
from :class:`fantasy_analyzer.sleeper.client.SleeperClient` on immutable IDs
(``user_id`` / ``owner_id``) to produce one row per roster describing who
owns it. It performs no network access -- callers are responsible for
fetching the raw Sleeper data first.
"""

from __future__ import annotations

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_team_mapping`.
TEAM_MAPPING_COLUMNS = ["roster_id", "owner_id", "display_name", "team_name"]


def build_team_mapping(users: list[dict], rosters: list[dict]) -> pd.DataFrame:
    """Build a stable roster-to-owner mapping for a league.

    Joins raw Sleeper ``rosters`` to raw Sleeper ``users`` on the immutable
    ``owner_id`` / ``user_id`` pair. ``display_name`` and ``team_name`` are
    carried along purely as human-readable labels -- they are never used as
    join keys and must not be treated as stable identifiers by callers.

    A roster's ``team_name`` falls back to its owner's ``display_name`` when
    the user has not set a custom team name (Sleeper stores this, when
    present, at ``user["metadata"]["team_name"]``).

    Args:
        users: Raw league user dicts as returned by
            ``SleeperClient.get_users()``. Each is expected to have
            ``user_id`` and ``display_name``, with an optional
            ``metadata.team_name``.
        rosters: Raw league roster dicts as returned by
            ``SleeperClient.get_rosters()``. Each is expected to have
            ``roster_id`` and ``owner_id``.

    Returns:
        A DataFrame with one row per roster and columns
        ``["roster_id", "owner_id", "display_name", "team_name"]``.
        Rosters with no owner (``owner_id`` is ``None``) or with an
        ``owner_id`` that does not match any league user produce ``None``
        for ``display_name`` and ``team_name`` rather than raising.
    """
    users_by_id = {user["user_id"]: user for user in users}

    rows = []
    for roster in rosters:
        owner_id = roster.get("owner_id")
        owner = users_by_id.get(owner_id)

        display_name = owner.get("display_name") if owner else None
        team_name = None
        if owner is not None:
            team_name = owner.get("metadata", {}).get("team_name") or display_name

        rows.append(
            {
                "roster_id": roster.get("roster_id"),
                "owner_id": owner_id,
                "display_name": display_name,
                "team_name": team_name,
            }
        )

    return pd.DataFrame(rows, columns=TEAM_MAPPING_COLUMNS)
