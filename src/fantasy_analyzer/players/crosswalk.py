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

A second, more complete source: :func:`build_id_crosswalk_from_player_ids`
--------------------------------------------------------------------------

Sleeper's catalog ``gsis_id`` field is populated for only a minority of
players -- verified directly while diagnosing a ranking-quality bug: as of
this addition, roughly 32% of Sleeper's ~12,000-player catalog, and the
gaps are not correlated with how good a player is (Justin Jefferson's own
catalog entry has ``gsis_id: None``). :func:`build_id_crosswalk` run alone
therefore silently drops most of the league, which starves
``player_value.py``'s replacement-level computation of most of its intended
comparison pool and distorts every VORP built on it -- most visibly once a
league-wide (free-agent-inclusive) player pool is in play (see
``player_week.py``'s ``build_league_wide_player_week_fact_table``), where a
too-small, non-representative comparison pool can let a merely
well-ID-mapped mediocre player look elite purely because most of his real
competition was invisible.

:func:`build_id_crosswalk_from_player_ids` builds the identical
:data:`CROSSWALK_COLUMNS` shape from a different, more complete source:
`DynastyProcess <https://github.com/dynastyprocess/data>`_'s
``db_playerids.csv``, a community-maintained multi-platform ID crosswalk
that, as of this addition, carries a populated ``sleeper_id`` for
essentially its entire ~12,500-row table (verified directly). This is
**still an explicit ID-to-ID join** -- AGENTS.md's "prefer immutable IDs
over names" principle and this module's original no-fuzzy-matching stance
both hold -- it is only the *source* of the explicit IDs that changes: from
Sleeper's own sparse ``gsis_id`` field to a purpose-built, actively
maintained crosswalk file. See ``id_crosswalk_client.py`` and
``id_crosswalk_cache.py`` for the network/caching layer this function
consumes, and that client module's docstring for the full investigation
that motivated this addition (including why nflverse's own ``players``
release, checked first, was not usable: it has no ``sleeper_id`` column).

The original ``build_id_crosswalk`` is unchanged and remains the
lighter-weight, single-source, no-extra-network-hop option -- callers who
only need Sleeper's own rostered players resolved (rather than a
league-wide free-agent-inclusive pool) may still prefer it, and every
existing caller and test of it keeps working exactly as before.
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


#: The DynastyProcess ``db_playerids.csv`` columns this normalizer reads,
#: mapped to this codebase's :data:`CROSSWALK_COLUMNS`. Every other column
#: the source carries (``mfl_id``, ``espn_id``, ``yahoo_id``, ...) is
#: ignored -- this codebase has no use for platform IDs beyond Sleeper and
#: nflverse's own ``gsis_id``.
_PLAYER_IDS_SOURCE_COLUMNS = {
    "sleeper_player_id": "sleeper_id",
    "gsis_id": "gsis_id",
    "full_name": "name",
    "position": "position",
    "team": "team",
}


def build_id_crosswalk_from_player_ids(player_ids: pd.DataFrame) -> pd.DataFrame:
    """Build a Sleeper <-> nflverse ID crosswalk from DynastyProcess's ID table.

    See the module docstring's "A second, more complete source" section for
    why this exists alongside :func:`build_id_crosswalk` and why it is still
    an explicit ID-to-ID join, not fuzzy matching.

    Args:
        player_ids: DynastyProcess's raw ``db_playerids.csv`` table, as
            returned by
            :meth:`~fantasy_analyzer.players.id_crosswalk_client.PlayerIdCrosswalkClient.download_player_ids`
            (or a cached copy of it, e.g. via
            :func:`~fantasy_analyzer.players.id_crosswalk_cache.get_player_ids_cached`).

    Returns:
        A DataFrame with columns :data:`CROSSWALK_COLUMNS`, one row per
        source row with both a non-empty ``sleeper_id`` and a non-empty
        ``gsis_id`` -- a row missing either cannot join anything this
        codebase's ``sleeper_player_id``/``gsis_id`` keys need, so it
        contributes no row, mirroring :func:`build_id_crosswalk`'s
        "no usable ID, no row" convention. ``sleeper_player_id`` is cast to
        ``str`` (the source stores it numerically; every Sleeper ID
        elsewhere in this codebase is a string). If two source rows share a
        ``gsis_id`` (or a ``sleeper_player_id``), only the last-encountered
        one is kept -- the identical last-value-wins policy
        :func:`build_id_crosswalk` documents for its own collision case, now
        applied to both keys since either could in principle collide in a
        third-party multi-platform table. An empty or wrong-shaped input
        (missing one of :data:`_PLAYER_IDS_SOURCE_COLUMNS`' values) raises
        ``ValueError`` naming the missing column(s), except an entirely
        empty DataFrame (no rows, no columns), which returns an empty
        crosswalk rather than raising -- matching
        ``NflverseScheduleClient.download_games``'s "unreachable asset"
        convention of an all-empty ``DataFrame`` for "no data available".

    Raises:
        ValueError: If a non-trivial ``player_ids`` frame is missing one of
            the source columns :data:`_PLAYER_IDS_SOURCE_COLUMNS` names.
    """
    if player_ids.empty and not len(player_ids.columns):
        return pd.DataFrame(columns=CROSSWALK_COLUMNS)

    missing = [
        source_column
        for source_column in _PLAYER_IDS_SOURCE_COLUMNS.values()
        if source_column not in player_ids.columns
    ]
    if missing:
        raise ValueError(
            "player_ids is missing expected column(s): "
            + ", ".join(sorted(set(missing)))
            + "; expected DynastyProcess's db_playerids.csv shape"
        )

    usable = player_ids[
        player_ids["sleeper_id"].notna() & player_ids["gsis_id"].notna()
    ]

    # The source stores sleeper_id numerically (float64, since the raw
    # column mixes real IDs with NaN for players it has no Sleeper match
    # for); a naive str() cast would render "6794.0" instead of the "6794"
    # Sleeper's own player_id strings use, silently breaking every join.
    # ``usable`` has already dropped every NaN sleeper_id above, so this
    # int cast is safe.
    sleeper_ids = usable["sleeper_id"].astype("int64").astype(str)

    crosswalk = pd.DataFrame(
        {
            output_column: (
                sleeper_ids
                if output_column == "sleeper_player_id"
                else usable[source_column]
            )
            for output_column, source_column in _PLAYER_IDS_SOURCE_COLUMNS.items()
        },
        columns=CROSSWALK_COLUMNS,
    )
    crosswalk = crosswalk.drop_duplicates(subset="gsis_id", keep="last")
    crosswalk = crosswalk.drop_duplicates(subset="sleeper_player_id", keep="last")

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
