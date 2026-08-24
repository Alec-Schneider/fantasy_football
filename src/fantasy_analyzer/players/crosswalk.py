"""Build a Sleeper <-> nflverse player ID crosswalk from Sleeper's catalog (FFA-062).

Sleeper's own player catalog (``SleeperClient.get_players()`` /
:func:`fantasy_analyzer.sleeper.cache.get_players_cached`) carries a native
``gsis_id`` field on most player objects, alongside Sleeper's own
``player_id``. That ``gsis_id`` is the same GSIS-format identifier nflverse
uses as its native player ID (``player_id`` in nflverse's raw stats table --
see ``nflverse_provider``'s column-mapping table, which maps it into this
codebase's ``gsis_id`` identity column).

Because Sleeper already carries this field, building the crosswalk this
ticket needs is a straightforward extraction/join, not a name/position/team
matching problem: for every Sleeper player with a populated ``gsis_id``, this
module records the ``(sleeper_player_id, gsis_id)`` pair. AGENTS.md is
explicit that explicit ID mappings should be preferred over fuzzy name
matching -- this module never inspects a player's name, position, or team to
decide a match; it only reads the catalog's own ``gsis_id`` field.

Return shapes
--------------

:func:`build_id_crosswalk` returns a ``pandas.DataFrame`` with columns
:data:`CROSSWALK_COLUMNS` (``sleeper_player_id``, ``gsis_id``, ``full_name``,
``position``, ``team``) -- one row per Sleeper player that has a usable
``gsis_id``. The DataFrame form is kept as the primary/debuggable shape (it
can be inspected, filtered, or written to disk like any other canonical
table in this codebase), and :func:`gsis_to_sleeper_lookup` /
:func:`sleeper_to_gsis_lookup` derive fast ``dict[str, str]`` lookups from it
on demand for callers (e.g. ``nflverse_provider``) that just need a single
join key mapped to another.

Players with no ``gsis_id``
-----------------------------

Not every Sleeper player has a populated ``gsis_id`` -- backups, practice-
squad players, and non-offensive-skill players (kickers, defenses, etc.)
frequently have ``gsis_id: null``, or omit the key entirely. Such players
contribute **no row** to the crosswalk: there is nothing to map them to, and
including a row with ``gsis_id: None`` would make the ``gsis_id`` column an
unreliable join key (a ``None``-to-``None`` join would spuriously match every
such player to every nflverse row with a missing ``gsis_id``, e.g. the
"Some Rookie" case in the nflverse fixture). This mirrors
``resolve_player``'s convention of never raising for an unresolvable ID, just
inverted: here, an unmapped Sleeper player is represented by *absence* from
the crosswalk rather than a row of ``None`` fields, because the crosswalk is
a mapping table, not a per-ID resolution of every input ID (contrast with
``resolve_player``, which is always asked about one specific ID and must
answer for it).

``gsis_id`` collisions
------------------------

In principle a stale or inconsistent catalog could have two Sleeper
``player_id``\\ s point at the same ``gsis_id``. This module's policy is
**last-value-wins**: if this occurs, :func:`build_id_crosswalk` keeps only
the last-encountered row for that ``gsis_id`` (per Python's dict iteration
order over ``player_catalog``, which is insertion order), dropping the
earlier one. This is a deliberate, simple, documented choice rather than
silently allowing an ambiguous many-to-one mapping to reach
:func:`gsis_to_sleeper_lookup` (a ``dict`` can only ever hold one value per
key regardless). No sanitized fixture in this codebase currently exercises a
genuine collision from live data; this policy exists to make the behavior
well-defined if one is ever encountered.
"""

from __future__ import annotations

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_id_crosswalk`.
CROSSWALK_COLUMNS = ["sleeper_player_id", "gsis_id", "full_name", "position", "team"]


def build_id_crosswalk(player_catalog: dict) -> pd.DataFrame:
    """Build a Sleeper <-> nflverse ID crosswalk from the Sleeper player catalog.

    Args:
        player_catalog: The raw Sleeper player catalog dict, keyed by
            ``player_id``, as returned by ``SleeperClient.get_players()`` or
            :func:`fantasy_analyzer.sleeper.cache.get_players_cached`.

    Returns:
        A DataFrame with columns :data:`CROSSWALK_COLUMNS`, one row per
        Sleeper player that has a non-empty ``gsis_id`` in the catalog.
        Players with ``gsis_id`` missing, ``None``, or blank contribute no
        row -- see the module docstring's "Players with no ``gsis_id``"
        section. If two Sleeper players share the same ``gsis_id``, only the
        last-encountered one (in catalog iteration order) is kept -- see the
        module docstring's "``gsis_id`` collisions" section. An empty
        ``player_catalog`` produces an empty DataFrame with the same
        columns, not an error.
    """
    rows = []
    for player_id, player in player_catalog.items():
        if not isinstance(player, dict):
            continue

        gsis_id = player.get("gsis_id")
        if not gsis_id:
            continue

        rows.append(
            {
                "sleeper_player_id": player_id,
                "gsis_id": gsis_id,
                "full_name": player.get("full_name"),
                "position": player.get("position"),
                "team": player.get("team"),
            }
        )

    crosswalk = pd.DataFrame(rows, columns=CROSSWALK_COLUMNS)
    crosswalk = crosswalk.drop_duplicates(subset="gsis_id", keep="last")

    return crosswalk.reset_index(drop=True)


def gsis_to_sleeper_lookup(crosswalk: pd.DataFrame) -> dict[str, str]:
    """Build a fast ``gsis_id -> sleeper_player_id`` lookup from a crosswalk.

    Args:
        crosswalk: A DataFrame as returned by :func:`build_id_crosswalk` (or
            any DataFrame carrying ``sleeper_player_id`` and ``gsis_id``
            columns).

    Returns:
        A ``dict`` mapping each ``gsis_id`` to its ``sleeper_player_id``.
        Empty if ``crosswalk`` is empty.
    """
    return dict(zip(crosswalk["gsis_id"], crosswalk["sleeper_player_id"]))


def sleeper_to_gsis_lookup(crosswalk: pd.DataFrame) -> dict[str, str]:
    """Build a fast ``sleeper_player_id -> gsis_id`` lookup from a crosswalk.

    Args:
        crosswalk: A DataFrame as returned by :func:`build_id_crosswalk` (or
            any DataFrame carrying ``sleeper_player_id`` and ``gsis_id``
            columns).

    Returns:
        A ``dict`` mapping each ``sleeper_player_id`` to its ``gsis_id``.
        Empty if ``crosswalk`` is empty.
    """
    return dict(zip(crosswalk["sleeper_player_id"], crosswalk["gsis_id"]))
