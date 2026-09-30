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

A last-resort, conservative name fallback (FFA-109)
--------------------------------------------------------------------------

Both ID sources lag the NFL's own roster moves. DynastyProcess usually
learns a new player's ``gsis_id`` (from nflverse) before it learns his
``sleeper_id``, and Sleeper's own catalog ``gsis_id`` is sparse. The
coverage audit (:mod:`fantasy_analyzer.players.coverage`) measured the
result on 2026-09-29, after week 3: six nflverse players with 2026 fantasy
activity mapped to no Sleeper id -- the TE Matthew Hibner (BAL), the RB DJ
Herman (MIA), the QB Jack Strand (ATL), and the kickers Trey Smack (GB),
Dominic Zvada (NYG) and Drew Stevens (WAS), all rookies. DynastyProcess
carried every one of their ``gsis_id``\\ s with a blank ``sleeper_id``;
five of the six were in Sleeper's catalog, on the same team, at the same
position, under the same name (Hibner as "Matt Hibner").

:func:`build_name_match_crosswalk` closes that gap by name, and it is
deliberately the *only* place in this module that reads a name. It is a
fallback for ids neither explicit source maps, never an override of one,
and it is built to leave a player unmapped rather than guess:

1. **Candidates.** nflverse side: every ``gsis_id`` in the supplied stats
   frame, at a fantasy position (``QB``, ``RB``, ``WR``, ``TE``, ``K``;
   nflverse's ``FB``/``HB`` count as ``RB``), that the existing crosswalk
   does not map. Its name/position/team are taken from its most recent
   row. Sleeper side: every catalog player at the same positions with an
   NFL team.
2. **Keys.** Names are normalized by :func:`normalize_player_name`
   (accents stripped, lower-cased, punctuation removed, hyphens as spaces,
   trailing ``Jr``/``Sr``/``II``-``V`` dropped). Teams are compared in
   nflverse's vocabulary (Sleeper's ``LAR`` is nflverse's ``LA``).
3. **Tier 1, ``exact_name``.** Normalized full name, position and team
   all equal.
4. **Tier 2, ``first_name_prefix``.** Same last name(s), position and
   team, and one first name is a prefix of the other with the shorter at
   least :data:`MIN_FIRST_NAME_PREFIX` characters long ("matt" /
   "matthew"). Only tried for players tier 1 left unmatched.
5. **Uniqueness, both ways.** A tier accepts a pair only if the nflverse
   player has exactly one Sleeper candidate *and* that Sleeper player has
   exactly one nflverse candidate. Candidates are counted over **all**
   players at the key, already-mapped ones included, so a namesake on the
   same team and position -- mapped or not -- makes the key ambiguous and
   both stay unmapped.
6. **No overrides.** A Sleeper player the crosswalk already maps, or whose
   own catalog ``gsis_id`` names a different player, is never re-mapped.

Toy example: nflverse has ``00-1`` "Matthew Hibner" TE BAL and ``00-2``
"Trey Smack" K GB, neither mapped; Sleeper has ``"13324"`` "Matt Hibner" TE
BAL and ``"13545"`` "Trey Smack" K GB. Smack matches at tier 1, Hibner at
tier 2. Add a second Sleeper "Trey Smack" K GB and Smack stays unmapped.

The fallback only reaches players present in the stats frame it is given,
which is the right population: a player with no nflverse row has nothing
to project from, so mapping him changes no number downstream.
:func:`build_robust_id_crosswalk` applies it when passed ``nflverse_stats``.
"""

from __future__ import annotations

import unicodedata
from typing import Optional

import pandas as pd

from fantasy_analyzer.players.opponent_strength import normalize_team

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


def build_robust_id_crosswalk(
    player_catalog: dict,
    *,
    force_refresh_ids: bool = False,
    nflverse_stats: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build the most complete Sleeper <-> nflverse ID crosswalk available (FFA-097).

    Unions the two single-source builders above, preferring DynastyProcess:
    :func:`build_id_crosswalk_from_player_ids` covers essentially the whole
    player universe, while :func:`build_id_crosswalk` (Sleeper's own sparse
    ``gsis_id`` field) contributes only the players DynastyProcess has not
    synced yet -- typically very recent signings.

    Preferring the union is not a marginal improvement for a free-agent
    population. Measured against the 2026 week-1 catalog, the
    Sleeper-catalog-only crosswalk resolved **111 of 615** NFL-signed free
    agents in a 12-team league (RB 12/108, WR 26/222); the union resolved
    **520 of 615**. Every unresolved player reaches
    :func:`~fantasy_analyzer.players.waiver_rankings.build_waiver_wire_rankings`
    with ``has_crosswalk = False`` and therefore no projection at all, so a
    sparse crosswalk does not degrade a waiver ranking gracefully -- it
    silently removes four fifths of the wire from it.

    This function lived in ``scripts/player_analysis.py`` until FFA-097
    moved it here, so that CLI surfaces (not just that one script) can use
    it; that script now imports it from this module.

    Args:
        player_catalog: The raw Sleeper player catalog dict, as returned by
            :func:`fantasy_analyzer.sleeper.cache.get_players_cached`. Used
            for the Sleeper-side union source.
        force_refresh_ids: Re-download DynastyProcess's ``db_playerids.csv``
            instead of reading the local cache. The cache is never
            TTL-checked (see ``id_crosswalk_cache.py``), so pass ``True``
            when a recent signing must resolve.
        nflverse_stats: Optional nflverse player-week stats (raw
            ``stats_player_week`` shape or the provider's normalized shape,
            any number of seasons). When given, the result is extended with
            :func:`build_name_match_crosswalk`'s conservative name fallback
            for nflverse players neither ID source maps -- see the module
            docstring's "last-resort" section. Defaults to ``None`` (no
            fallback, the pre-FFA-109 behavior).

    Returns:
        A :data:`CROSSWALK_COLUMNS`-shaped DataFrame, one row per Sleeper
        player either source can resolve, with DynastyProcess's mapping
        winning on overlap, plus any name-fallback rows. Falls back to the
        Sleeper-catalog-only crosswalk alone (with a warning on stderr) if
        DynastyProcess's asset cannot be fetched -- coverage degrades
        rather than the whole pipeline failing.
    """
    # Imported here rather than at module scope: this module is otherwise
    # pure (catalog dict / DataFrame in, DataFrame out) and is imported by
    # code that must not pull in the network/caching layer transitively.
    import sys

    import requests

    from fantasy_analyzer.players.id_crosswalk_cache import get_player_ids_cached
    from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient

    sleeper_only = build_id_crosswalk(player_catalog)

    try:
        raw_ids = get_player_ids_cached(
            PlayerIdCrosswalkClient(), force_refresh=force_refresh_ids
        )
        dynastyprocess = build_id_crosswalk_from_player_ids(raw_ids)
    except (requests.exceptions.RequestException, ValueError) as exc:
        print(
            f"WARNING: DynastyProcess ID crosswalk unavailable ({exc}); "
            "falling back to the Sleeper-catalog-only crosswalk (lower "
            "player coverage).",
            file=sys.stderr,
        )
        combined = sleeper_only
    else:
        # DynastyProcess wins on overlap (concat + keep="last"): it is the
        # actively-maintained, near-complete source; the Sleeper-only rows
        # fill in only what DynastyProcess does not cover.
        combined = pd.concat([sleeper_only, dynastyprocess], ignore_index=True)
        combined = combined.drop_duplicates(subset="sleeper_player_id", keep="last")
        combined = combined.reset_index(drop=True)

    if nflverse_stats is not None:
        combined = extend_crosswalk_with_name_matches(
            combined, player_catalog, nflverse_stats
        )
    return combined


#: Fantasy positions nflverse publishes player-week rows for, in Sleeper's
#: vocabulary. Team defenses (``DEF``) have no nflverse player rows at all.
NFLVERSE_FANTASY_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K"})

#: nflverse/DynastyProcess ``position`` spellings that differ from Sleeper's.
_POSITION_ALIASES = {"FB": "RB", "HB": "RB", "PK": "K"}

#: Generational suffixes :func:`normalize_player_name` drops from the end.
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

#: Shortest first name the ``first_name_prefix`` tier of
#: :func:`build_name_match_crosswalk` treats as a prefix of another
#: ("matt"/"matthew" qualifies; a lone initial does not).
MIN_FIRST_NAME_PREFIX = 3

#: Column order for :func:`build_name_match_crosswalk`'s output:
#: :data:`CROSSWALK_COLUMNS` plus which tier produced the match.
NAME_MATCH_COLUMNS = CROSSWALK_COLUMNS + ["match_method"]


def normalize_player_name(name: object) -> Optional[str]:
    """Normalize a player name for the name-match fallback.

    Strips accents, lower-cases, turns hyphens into spaces, removes every
    other non-alphanumeric character (so "D.J." and "DJ" agree, as do
    "Ja'Marr" and "JaMarr"), collapses whitespace, and drops trailing
    generational suffixes (``jr``, ``sr``, ``ii``-``v``) from names of three
    or more tokens.

    Args:
        name: A display name from any source.

    Returns:
        The normalized name, or ``None`` for a non-string or empty input.

    Example:
        >>> normalize_player_name("Amon-Ra St. Brown")
        'amon ra st brown'
        >>> normalize_player_name("Marvin Harrison Jr.")
        'marvin harrison'
    """
    if not isinstance(name, str):
        return None
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = "".join(
        character
        for character in ascii_name.lower().replace("-", " ")
        if character.isalnum() or character.isspace()
    )
    tokens = cleaned.split()
    while len(tokens) > 2 and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens) or None


def fantasy_position(position: object) -> Optional[str]:
    """Map an nflverse/DynastyProcess position onto Sleeper's fantasy vocabulary.

    Args:
        position: A position label, e.g. ``"FB"`` or ``"PK"``.

    Returns:
        One of :data:`NFLVERSE_FANTASY_POSITIONS` (``"FB"``/``"HB"`` ->
        ``"RB"``, ``"PK"`` -> ``"K"``), or ``None`` for any other position
        or a missing value.
    """
    if not isinstance(position, str):
        return None
    position = _POSITION_ALIASES.get(position, position)
    return position if position in NFLVERSE_FANTASY_POSITIONS else None


def standardize_nflverse_identity(stats: pd.DataFrame) -> pd.DataFrame:
    """Give an nflverse player-week frame canonical identity column names.

    Two shapes circulate in this codebase: nflverse's raw
    ``stats_player_week`` table (``player_id`` is the GSIS id,
    ``player_display_name``, ``team``), as the local cache stores it, and
    :class:`~fantasy_analyzer.players.nflverse_provider.NflverseWeeklyStatsProvider`'s
    normalized output (``gsis_id``, ``player_name``, ``nfl_team``). The raw
    shape is recognized by the absence of ``gsis_id``.

    Args:
        stats: Either shape, any number of seasons and weeks.

    Returns:
        A copy with ``gsis_id``, ``player_name``, ``nfl_team``,
        ``position``, ``season`` and ``week`` present (``None``-filled when
        the input lacks them), plus ``fantasy_position`` from
        :func:`fantasy_position`. Every other column passes through. The
        raw shape's abbreviated ``player_name`` ("J.Allen") is replaced by
        ``player_display_name``.
    """
    frame = stats.copy()
    if "gsis_id" not in frame.columns:
        renames = {"player_id": "gsis_id", "team": "nfl_team"}
        if "player_display_name" in frame.columns:
            frame = frame.drop(columns=["player_name"], errors="ignore")
            renames["player_display_name"] = "player_name"
        frame = frame.rename(columns=renames)
    for column in ("gsis_id", "player_name", "nfl_team", "position", "season", "week"):
        if column not in frame.columns:
            frame[column] = None
    frame["fantasy_position"] = frame["position"].map(fantasy_position)
    return frame


def _split_name(name_key: str) -> tuple[str, str]:
    """``("first", "rest of the name")`` for a normalized name."""
    first, _, rest = name_key.partition(" ")
    return first, rest


def _first_names_compatible(first_a: str, first_b: str) -> bool:
    """Equal, or one a prefix of the other with the shorter long enough."""
    if first_a == first_b:
        return True
    shorter, longer = sorted((first_a, first_b), key=len)
    return len(shorter) >= MIN_FIRST_NAME_PREFIX and longer.startswith(shorter)


def _names_match(method: str, a: dict, b: dict) -> bool:
    """Whether two name-keyed candidates match under a fallback tier."""
    if method == "exact_name":
        return a["name_key"] == b["name_key"]
    return (
        bool(a["last"])
        and a["last"] == b["last"]
        and _first_names_compatible(a["first"], b["first"])
    )


def _nflverse_candidates(nflverse_stats: pd.DataFrame) -> list[dict]:
    """One name-keyed identity per nflverse ``gsis_id``, from its latest row."""
    frame = standardize_nflverse_identity(nflverse_stats)
    frame = frame[frame["gsis_id"].notna()].copy()
    frame["_season"] = pd.to_numeric(frame["season"], errors="coerce")
    frame["_week"] = pd.to_numeric(frame["week"], errors="coerce")
    frame = frame.sort_values(
        ["_season", "_week"], kind="mergesort", na_position="first"
    )
    latest = frame.drop_duplicates(subset="gsis_id", keep="last")

    candidates = []
    for row in latest.to_dict(orient="records"):
        name_key = normalize_player_name(row["player_name"])
        team = normalize_team(row["nfl_team"])
        position = row["fantasy_position"]
        # ``Series.map`` renders an unmapped position as NaN, not None.
        if name_key is None or team is None or not isinstance(position, str):
            continue
        first, last = _split_name(name_key)
        candidates.append(
            {
                "gsis_id": str(row["gsis_id"]),
                "name_key": name_key,
                "first": first,
                "last": last,
                "group": (position, team),
            }
        )
    return sorted(candidates, key=lambda candidate: candidate["gsis_id"])


def _sleeper_candidates(player_catalog: dict) -> list[dict]:
    """Name-keyed Sleeper catalog players at a fantasy position with a team."""
    candidates = []
    for player_id, player in player_catalog.items():
        if not isinstance(player, dict):
            continue
        position = player.get("position")
        team = normalize_team(player.get("team"))
        if position not in NFLVERSE_FANTASY_POSITIONS or team is None:
            continue
        display = player.get("full_name") or " ".join(
            part for part in (player.get("first_name"), player.get("last_name")) if part
        )
        name_key = normalize_player_name(display)
        if name_key is None:
            continue
        first, last = _split_name(name_key)
        candidates.append(
            {
                "sleeper_player_id": str(player_id),
                "full_name": player.get("full_name") or display,
                "position": position,
                "team": player.get("team"),
                "catalog_gsis_id": player.get("gsis_id") or None,
                "name_key": name_key,
                "first": first,
                "last": last,
                "group": (position, team),
            }
        )
    return candidates


def build_name_match_crosswalk(
    player_catalog: dict,
    nflverse_stats: pd.DataFrame,
    crosswalk: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Map nflverse players no ID source covers to Sleeper ids by name (FFA-109).

    The conservative last-resort fallback described in the module
    docstring's "last-resort" section, including its toy example: two
    tiers (``exact_name``, then ``first_name_prefix``), same position and
    team required, and a pair is accepted only when it is unique in both
    directions over every player at that key. Ambiguity leaves both sides
    unmapped. Never re-maps a Sleeper id ``crosswalk`` already maps, or
    one whose catalog ``gsis_id`` names a different player.

    Args:
        player_catalog: The raw Sleeper player catalog dict.
        nflverse_stats: nflverse player-week stats in either shape
            :func:`standardize_nflverse_identity` accepts. Only players
            present here can be matched.
        crosswalk: The existing :data:`CROSSWALK_COLUMNS`-shaped crosswalk
            whose gaps to fill. ``None`` treats every nflverse player as
            unmapped.

    Returns:
        A DataFrame with columns :data:`NAME_MATCH_COLUMNS` holding only
        the new matches, sorted by ``gsis_id``. ``full_name``/``position``/
        ``team`` are Sleeper's. ``match_method`` is ``"exact_name"`` or
        ``"first_name_prefix"``. Empty (same columns) when nothing matches
        or either input is empty.
    """
    if nflverse_stats is None or nflverse_stats.empty or not player_catalog:
        return pd.DataFrame(columns=NAME_MATCH_COLUMNS)

    mapped_gsis: set[str] = set()
    mapped_sleeper: set[str] = set()
    if crosswalk is not None and not crosswalk.empty:
        mapped_gsis = set(crosswalk["gsis_id"].dropna().astype(str))
        mapped_sleeper = set(crosswalk["sleeper_player_id"].dropna().astype(str))

    nflverse_by_group: dict[tuple, list[dict]] = {}
    for candidate in _nflverse_candidates(nflverse_stats):
        nflverse_by_group.setdefault(candidate["group"], []).append(candidate)
    sleeper_by_group: dict[tuple, list[dict]] = {}
    for candidate in _sleeper_candidates(player_catalog):
        sleeper_by_group.setdefault(candidate["group"], []).append(candidate)

    matches: list[dict] = []
    for method in ("exact_name", "first_name_prefix"):
        for group in sorted(nflverse_by_group):
            nflverse_group = nflverse_by_group[group]
            sleeper_group = sleeper_by_group.get(group, [])
            for nflverse_player in nflverse_group:
                if nflverse_player["gsis_id"] in mapped_gsis:
                    continue
                sleeper_matches = [
                    sleeper_player
                    for sleeper_player in sleeper_group
                    if _names_match(method, nflverse_player, sleeper_player)
                ]
                if len(sleeper_matches) != 1:
                    continue
                sleeper_player = sleeper_matches[0]
                reverse_matches = [
                    other
                    for other in nflverse_group
                    if _names_match(method, other, sleeper_player)
                ]
                if len(reverse_matches) != 1:
                    continue
                if sleeper_player["sleeper_player_id"] in mapped_sleeper:
                    continue
                catalog_gsis = sleeper_player["catalog_gsis_id"]
                if catalog_gsis and catalog_gsis != nflverse_player["gsis_id"]:
                    continue

                matches.append(
                    {
                        "sleeper_player_id": sleeper_player["sleeper_player_id"],
                        "gsis_id": nflverse_player["gsis_id"],
                        "full_name": sleeper_player["full_name"],
                        "position": sleeper_player["position"],
                        "team": sleeper_player["team"],
                        "match_method": method,
                    }
                )
                mapped_gsis.add(nflverse_player["gsis_id"])
                mapped_sleeper.add(sleeper_player["sleeper_player_id"])

    result = pd.DataFrame(matches, columns=NAME_MATCH_COLUMNS)
    return result.sort_values("gsis_id", kind="mergesort").reset_index(drop=True)


def extend_crosswalk_with_name_matches(
    crosswalk: pd.DataFrame,
    player_catalog: dict,
    nflverse_stats: pd.DataFrame,
) -> pd.DataFrame:
    """Append :func:`build_name_match_crosswalk`'s matches to ``crosswalk``.

    Existing rows are untouched; matches only ever add a ``gsis_id`` and a
    ``sleeper_player_id`` that ``crosswalk`` did not already contain.

    Args:
        crosswalk: A :data:`CROSSWALK_COLUMNS`-shaped crosswalk.
        player_catalog: The raw Sleeper player catalog dict.
        nflverse_stats: nflverse player-week stats, either shape.

    Returns:
        ``crosswalk`` plus one row per name match, :data:`CROSSWALK_COLUMNS`
        only (the ``match_method`` is dropped -- call
        :func:`build_name_match_crosswalk` directly to see it).
    """
    matches = build_name_match_crosswalk(player_catalog, nflverse_stats, crosswalk)
    if matches.empty:
        return crosswalk
    return pd.concat(
        [crosswalk, matches[CROSSWALK_COLUMNS]], ignore_index=True
    ).reset_index(drop=True)


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
