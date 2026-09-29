"""Resolve the current-state fantasy free-agent pool for one league (FFA-091).

This module answers a metric-definition question, per AGENTS.md's Data
Scientist role split, about a single league's **current** roster state (not
a historical/backtest snapshot -- see :mod:`fantasy_analyzer.players.ros_backtest`
for that, and :mod:`fantasy_analyzer.players.ros_projection` for the model
this pool eventually feeds via a separate ranking ticket, FFA-092).

Definition
--------------------------------------------------------------------------

A player is a **free agent** in a league if and only if all three hold:

1. He is present in Sleeper's NFL player catalog (the universe of every
   player Sleeper knows about --
   :meth:`~fantasy_analyzer.sleeper.client.SleeperClient.get_players` /
   :func:`~fantasy_analyzer.sleeper.cache.get_players_cached`).
2. He plays a position the league actually starts (derived from
   ``LeagueSettings.roster_positions`` via
   :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
   -- see :func:`resolve_startable_positions`). A league with no ``K``
   slot, for example, has no kicker free agents, regardless of how many
   unrostered kickers Sleeper's catalog carries.
3. He does not appear on any roster in the league, in **any** capacity --
   active roster spot, bench, IR/``reserve``, or ``taxi`` squad. All four
   are "rostered", not "available"; only a manager who drops the player (or
   his taxi/IR designation is cut) makes him a free agent again.

A player is additionally excluded, independent of the above, if Sleeper's
catalog marks him ``"Inactive"`` or ``"Retired"`` via its ``status`` field
(see "The ``status`` field" section below for how this is applied
defensively).

Toy example (hand-checkable)
--------------------------------------------------------------------------

A 2-team, 1-position-plus-bench league (``roster_positions =
["QB", "BN"]``, so only ``QB`` is startable) with a 4-player catalog:

============  ==========  ========  ===================================
player_id     position    status    rostered?
============  ==========  ========  ===================================
``"1"``       QB          Active    roster 1's ``players`` (started)
``"2"``       QB          Active    roster 2's ``reserve`` (IR)
``"3"``       QB          Active    not on any roster
``"4"``       QB          Retired   not on any roster
``"5"``       RB          Active    not on any roster
============  ==========  ========  ===================================

The free-agent pool is exactly ``{"3"}``: ``"1"`` and ``"2"`` are rostered
(IR counts as rostered), ``"4"`` is excluded by status, and ``"5"`` plays a
position (``RB``) this league does not start.

The ``status`` field
--------------------------------------------------------------------------

Nothing else in this codebase has previously read Sleeper's player-catalog
``status`` field (verified by inspection: no other module under
``src/fantasy_analyzer`` references it, and the shared sanitized fixture
``tests/fixtures/sleeper/players.json`` does not carry it). Sleeper's real
player objects do carry a ``status`` string (e.g. ``"Active"``,
``"Inactive"``, ``"Retired"``), but because it is new to this codebase this
module treats it strictly defensively:

- A **missing** ``status`` key, or ``None``, is treated as unknown/active
  -- it never excludes a player. A stale or minimal cached catalog entry
  must not silently vanish an otherwise-eligible free agent.
- Matching is case-insensitive against :data:`DEFAULT_EXCLUDED_STATUSES`.
- Any status value not in that set (``"Active"``, ``"Practice Squad"``,
  ``"PUP"``, etc.) passes through -- this module only excludes the two
  statuses the FFA-091 ticket names explicitly (inactive, retired), not a
  broader "is this player rosterable" judgment call.

Crosswalk coverage
--------------------------------------------------------------------------

:func:`build_free_agent_pool` accepts an optional ``crosswalk`` (the
:data:`~fantasy_analyzer.players.crosswalk.CROSSWALK_COLUMNS`-shaped
DataFrame from :func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk`
or :func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk_from_player_ids`).
A free agent with no crosswalk entry is **never dropped** -- per the ticket,
coverage gaps must stay visible for FFA-092's projection join, not silently
shrink the pool. Such a row gets ``gsis_id = None`` and ``has_crosswalk =
False`` rather than being excluded.

National ownership (optional enrichment)
--------------------------------------------------------------------------

:func:`build_free_agent_pool` also accepts an optional ``ownership_lookup``
(``sleeper_player_id -> player_owned_avg`` percentage, 0-100), which this
module does not build a live-network path for itself -- see
:func:`build_fantasypros_ownership_lookup`, a pure DataFrame-in transform a
caller can build once (outside this module, e.g. from
:func:`~fantasy_analyzer.players.draft_market_cache.get_fpecr_cached` and
:func:`~fantasy_analyzer.players.id_crosswalk_cache.get_player_ids_cached`)
and pass in. Omitting it leaves ``player_owned_avg`` entirely ``NaN`` -- it
is optional enrichment, not a required column, per the FFA-091 ticket.

What this module does not do
--------------------------------------------------------------------------

It resolves the *pool* only. It performs no network access, computes no
projection, and does not rank players -- that is FFA-092's
``mode="projected"`` work in ``player_rankings.py``, deliberately left
untouched here.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from fantasy_analyzer.players.crosswalk import sleeper_to_gsis_lookup
from fantasy_analyzer.players.draft_market import FANTASYPROS_OVERALL_PAGE_TYPE
from fantasy_analyzer.players.lineup_efficiency import START_SLOT_ELIGIBILITY

#: Column order for the DataFrame returned by :func:`build_free_agent_pool`.
FREE_AGENT_POOL_COLUMNS = [
    "player_id",
    "full_name",
    "position",
    "team",
    "status",
    "gsis_id",
    "has_crosswalk",
    "player_owned_avg",
]

#: Sleeper catalog ``status`` values excluded from the free-agent pool,
#: matched case-insensitively. See the module docstring's "``status``
#: field" section for why this is a narrow, explicit list rather than an
#: inferred "startable" judgment.
DEFAULT_EXCLUDED_STATUSES = frozenset({"inactive", "retired"})

#: Roster-dict keys that can carry rostered player IDs. ``players`` alone
#: should already be a superset of ``reserve`` (IR) and ``taxi`` on a
#: well-formed Sleeper roster (both are documented as subsets of
#: ``players``), but every key is unioned defensively so a malformed or
#: partially-populated roster dict (e.g. a hand-built test fixture, or a
#: future Sleeper response shape) can never cause a rostered player to be
#: misclassified as a free agent.
_ROSTERED_ID_KEYS = ("players", "starters", "reserve", "taxi")


def resolve_startable_positions(roster_positions: list[str]) -> set[str]:
    """Derive the set of positions a league actually starts.

    Each entry in ``roster_positions`` (``LeagueSettings.roster_positions``
    / ``LeagueSnapshot.roster_positions``) is looked up in
    :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`,
    which maps a slot label to the set of positions eligible to fill it
    (e.g. ``"FLEX" -> ("RB", "WR", "TE")``). Bench/IR/taxi slots (``"BN"``,
    ``"IR"``, ``"TAXI"``) and any other label not in that mapping
    contribute nothing -- they are not startable slots.

    Args:
        roster_positions: The league's ordered roster-slot list, including
            bench slots.

    Returns:
        The set of position labels (e.g. ``{"QB", "RB", "WR", "TE", "K",
        "DEF"}``) the league starts in at least one slot. Empty if
        ``roster_positions`` is empty or contains no recognized starting
        slot.

    Example:
        >>> slots = [
        ...     "QB", "RB", "RB", "WR", "WR", "TE", "FLEX",
        ...     "K", "DEF", "BN", "BN", "IR",
        ... ]
        >>> sorted(resolve_startable_positions(slots))
        ['DEF', 'K', 'QB', 'RB', 'TE', 'WR']
    """
    positions: set[str] = set()
    for slot in roster_positions:
        positions.update(START_SLOT_ELIGIBILITY.get(slot, ()))
    return positions


def rostered_player_ids(raw_rosters: list[dict]) -> set[str]:
    """Collect every Sleeper ``player_id`` rostered by any team in a league.

    Unions :data:`_ROSTERED_ID_KEYS` across every roster dict -- active
    roster spots, bench (both live only in ``players``), IR/``reserve``,
    and ``taxi``. All are "rostered", never "available" -- see the module
    docstring's definition, point 3.

    Args:
        raw_rosters: Raw roster dicts as returned by
            ``SleeperClient.get_rosters(league_id)``.

    Returns:
        The set of rostered Sleeper ``player_id`` strings, league-wide.
        Empty if ``raw_rosters`` is empty or every roster has no players.
    """
    ids: set[str] = set()
    for roster in raw_rosters:
        for key in _ROSTERED_ID_KEYS:
            for player_id in roster.get(key) or []:
                ids.add(player_id)
    return ids


def _is_excluded_status(
    status: object, excluded_statuses: frozenset[str]
) -> bool:
    """True if ``status`` case-insensitively matches an excluded status.

    A missing/``None``/non-string ``status`` is never excluded -- see the
    module docstring's "``status`` field" section.
    """
    if not isinstance(status, str) or not status:
        return False
    return status.strip().lower() in excluded_statuses


def _empty_pool() -> pd.DataFrame:
    """An empty :data:`FREE_AGENT_POOL_COLUMNS`-shaped frame with fixed dtypes."""
    frame = pd.DataFrame(columns=FREE_AGENT_POOL_COLUMNS)
    frame["has_crosswalk"] = frame["has_crosswalk"].astype(bool)
    frame["player_owned_avg"] = frame["player_owned_avg"].astype("float64")
    return frame


def build_free_agent_pool(
    raw_rosters: list[dict],
    player_catalog: dict,
    roster_positions: list[str],
    crosswalk: Optional[pd.DataFrame] = None,
    ownership_lookup: Optional[dict] = None,
    excluded_statuses: frozenset[str] = DEFAULT_EXCLUDED_STATUSES,
) -> pd.DataFrame:
    """Build a league's current-state fantasy free-agent pool.

    See the module docstring's "Definition" section for the exact rule and
    a hand-checkable toy example.

    Args:
        raw_rosters: Raw roster dicts as returned by
            ``SleeperClient.get_rosters(league_id)``.
        player_catalog: The raw Sleeper player catalog dict, keyed by
            ``player_id``, as returned by ``SleeperClient.get_players()`` /
            :func:`~fantasy_analyzer.sleeper.cache.get_players_cached`.
            This -- not ``LeagueSnapshot.players_df``, which only resolves
            IDs already on a roster -- is the universe this function scans.
        roster_positions: The league's ordered roster-slot list
            (``LeagueSettings.roster_positions`` /
            ``LeagueSnapshot.roster_positions``), used to derive startable
            positions via :func:`resolve_startable_positions`.
        crosswalk: An optional
            :data:`~fantasy_analyzer.players.crosswalk.CROSSWALK_COLUMNS`-shaped
            DataFrame. When given, ``gsis_id``/``has_crosswalk`` are filled
            from it; a free agent absent from it still gets a row (``
            gsis_id=None``, ``has_crosswalk=False``), never a dropped row.
            When omitted, every row has ``gsis_id=None``,
            ``has_crosswalk=False``.
        ownership_lookup: An optional ``sleeper_player_id ->
            player_owned_avg`` dict (see
            :func:`build_fantasypros_ownership_lookup`). When omitted,
            ``player_owned_avg`` is ``NaN`` for every row.
        excluded_statuses: Catalog ``status`` values (case-insensitive) to
            exclude. Defaults to :data:`DEFAULT_EXCLUDED_STATUSES`.

    Returns:
        A DataFrame with columns :data:`FREE_AGENT_POOL_COLUMNS`, one row
        per free agent, in Sleeper player-catalog iteration order. Empty
        (but correctly shaped) if the catalog is empty, the league starts
        no positions, or every startable-position player is rostered or
        excluded by status.
    """
    if not player_catalog:
        return _empty_pool()

    startable_positions = resolve_startable_positions(roster_positions)
    if not startable_positions:
        return _empty_pool()

    rostered = rostered_player_ids(raw_rosters)

    gsis_by_sleeper_id: dict[str, str] = {}
    if crosswalk is not None and not crosswalk.empty:
        gsis_by_sleeper_id = sleeper_to_gsis_lookup(crosswalk)

    ownership_lookup = ownership_lookup or {}

    rows = []
    for player_id, player in player_catalog.items():
        if not isinstance(player, dict):
            continue
        if player_id in rostered:
            continue

        position = player.get("position")
        if position not in startable_positions:
            continue

        if _is_excluded_status(player.get("status"), excluded_statuses):
            continue

        gsis_id = gsis_by_sleeper_id.get(player_id)

        rows.append(
            {
                "player_id": player_id,
                "full_name": player.get("full_name"),
                "position": position,
                "team": player.get("team"),
                "status": player.get("status"),
                "gsis_id": gsis_id,
                "has_crosswalk": gsis_id is not None,
                "player_owned_avg": ownership_lookup.get(player_id),
            }
        )

    pool = pd.DataFrame(rows, columns=FREE_AGENT_POOL_COLUMNS)
    pool["has_crosswalk"] = pool["has_crosswalk"].astype(bool)
    pool["player_owned_avg"] = pool["player_owned_avg"].astype("float64")
    return pool


def build_fantasypros_ownership_lookup(
    fpecr: pd.DataFrame,
    player_ids: pd.DataFrame,
    page_type: str = FANTASYPROS_OVERALL_PAGE_TYPE,
) -> dict[str, float]:
    """Build a ``sleeper_player_id -> player_owned_avg`` lookup.

    Optional enrichment source for ``ownership_lookup`` in
    :func:`build_free_agent_pool` -- see the module docstring's "National
    ownership" section. A pure DataFrame-in transform; it performs no
    network access or caching itself. Callers own fetching/caching
    ``fpecr`` (DynastyProcess's republished FantasyPros ECR export, e.g.
    via
    :func:`~fantasy_analyzer.players.draft_market_cache.get_fpecr_cached`)
    and ``player_ids`` (DynastyProcess's ID crosswalk, e.g. via
    :func:`~fantasy_analyzer.players.id_crosswalk_cache.get_player_ids_cached`).

    The join: ``fpecr`` carries FantasyPros' own numeric ``id`` and
    ``player_owned_avg``; ``player_ids`` carries both ``fantasypros_id``
    and ``sleeper_id`` for the same player (the same crosswalk asset
    :func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk_from_player_ids`
    uses). This is an explicit ID-to-ID join through that shared asset, not
    name matching, matching this codebase's stated ID-preference policy.
    ``fpecr`` is filtered to ``page_type`` first (default
    ``"redraft-overall"``, one row per player) so a player ranked on
    multiple FantasyPros pages (overall, per-position, dynasty, ...)
    contributes exactly one row.

    Args:
        fpecr: DynastyProcess's FantasyPros ECR export
            (``db_fpecr_latest.csv`` shape): at minimum ``page_type``,
            ``id``, and ``player_owned_avg`` columns.
        player_ids: DynastyProcess's ID crosswalk (``db_playerids.csv``
            shape): at minimum ``fantasypros_id`` and ``sleeper_id``
            columns.
        page_type: Which ``fpecr`` page to read ownership from. Defaults
            to FantasyPros' combined overall redraft page.

    Returns:
        A dict mapping each resolvable ``sleeper_player_id`` (string) to
        its ``player_owned_avg`` (float, 0-100). Rows missing ``id``,
        ``player_owned_avg``, a matching ``fantasypros_id``, or a
        ``sleeper_id`` on the matched row contribute nothing -- this
        function never raises for a missing/malformed input, it just
        yields fewer keys. Empty if either input is empty or missing a
        required column.
    """
    required_fpecr = {"page_type", "id", "player_owned_avg"}
    required_player_ids = {"fantasypros_id", "sleeper_id"}
    if (
        fpecr is None
        or player_ids is None
        or fpecr.empty
        or player_ids.empty
        or not required_fpecr.issubset(fpecr.columns)
        or not required_player_ids.issubset(player_ids.columns)
    ):
        return {}

    overall = fpecr[fpecr["page_type"] == page_type].copy()
    overall["id"] = pd.to_numeric(overall["id"], errors="coerce")
    overall = overall.dropna(subset=["id", "player_owned_avg"])
    overall["id"] = overall["id"].astype("int64")
    # Last-value-wins on a duplicate fantasypros id within the page, the
    # same collision policy used throughout this codebase's ID-join code
    # (e.g. crosswalk.py's "gsis_id collisions" section).
    overall = overall.drop_duplicates(subset="id", keep="last")

    crosswalk = player_ids.copy()
    crosswalk["fantasypros_id"] = pd.to_numeric(
        crosswalk["fantasypros_id"], errors="coerce"
    )
    crosswalk = crosswalk.dropna(subset=["fantasypros_id", "sleeper_id"])
    crosswalk["fantasypros_id"] = crosswalk["fantasypros_id"].astype("int64")
    crosswalk = crosswalk.drop_duplicates(subset="fantasypros_id", keep="last")
    fp_to_sleeper = dict(
        zip(
            crosswalk["fantasypros_id"],
            crosswalk["sleeper_id"].astype("int64").astype(str),
        )
    )

    lookup: dict[str, float] = {}
    for fp_id, owned_avg in zip(overall["id"], overall["player_owned_avg"]):
        sleeper_id = fp_to_sleeper.get(fp_id)
        if sleeper_id is not None:
            lookup[sleeper_id] = float(owned_avg)

    return lookup
