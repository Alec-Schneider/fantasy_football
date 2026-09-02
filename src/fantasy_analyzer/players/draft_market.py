"""Normalize forward-looking 2026 draft-market data to Sleeper player IDs (FFA-075).

This is a **data-ingestion module only**. It ingests two independent
consensus draft-market sources -- FantasyFootballCalculator (FFC)'s
crowd-sourced average draft position (ADP), and DynastyProcess's republished
FantasyPros expert-consensus-rank (ECR) export -- and normalizes both to one
long-format canonical table, :data:`DRAFT_MARKET_COLUMNS`. It implements no
blending of the two sources, no ranking methodology, and no draft-strategy
logic; a downstream ``draft_board`` module (owned separately) is responsible
for combining this ingestion module's output into an actual ranking.

Every function in this module is a pure DataFrame-in/DataFrame-out
transform: no network access happens here. See ``draft_market_client.py``
for the raw HTTP downloaders and ``draft_market_cache.py`` for the
disk-caching + fetch-and-normalize glue that calls into this module. This
mirrors ``provider.py``/``nflverse_provider.py``'s split between a
provider-agnostic identity-column contract and the concrete normalizer that
fills it.

The ID join: two very different join keys for two sources
------------------------------------------------------------

FFC has no FantasyPros/DynastyProcess ID of its own, so its rows are joined
to Sleeper IDs by **normalized name + position** against DynastyProcess's
``db_playerids.csv`` (the same crosswalk asset
:mod:`fantasy_analyzer.players.crosswalk` uses, downloaded via the existing
:class:`~fantasy_analyzer.players.id_crosswalk_client.PlayerIdCrosswalkClient`
-- this module does **not** implement a second downloader for that file).
This is a genuine fuzzy match (AGENTS.md's "prefer immutable IDs" principle
does not apply because FFC simply has no immutable ID to prefer), verified
directly against a live 2026 pull at ~98% match for skill-position/QB/K
rows once :func:`_normalize_player_name`'s suffix/punctuation stripping is
applied (bare exact-string matching was materially worse, e.g. "Michael
Pittman Jr." against ``db_playerids``' "Michael Pittman"). The handful of
remaining misses are real data gaps (a name genuinely absent from
``db_playerids``, e.g. a just-signed undrafted rookie), not normalization
bugs.

DynastyProcess's FantasyPros export, by contrast, carries FantasyPros' own
numeric ``id`` for every non-defense row -- an explicit ID-to-ID join is
possible via ``db_playerids.fantasypros_id`` (coerced with
``pd.to_numeric(..., errors="coerce")``; it is not stored cleanly).
Verified directly: 188/200 of the top-200-ranked players join this way, and
every one of the 12 remaining misses is the systematic DST case documented
next -- there is no other unexplained gap in that sample.

The DST/DEF special case
--------------------------

Every miss in the ID-join verification above is a team defense
(FantasyPros' ``pos == "DST"``). This is not a data gap: Sleeper does not
assign team defenses a numeric ``player_id`` the way it does real players --
**Sleeper uses the team's own abbreviation as the defense's ``player_id``**
(e.g. ``"PHI"``), so there is nothing in ``db_playerids`` for either source
to join against; DynastyProcess's crosswalk is itself scoped to individual
players. Both :func:`build_ffc_draft_market` and
:func:`build_fantasypros_draft_market` special-case ``position == "DEF"``
rows: ``sleeper_player_id`` is set directly from the row's own normalized
team abbreviation, never looked up in ``player_ids``.

That normalization matters because the two sources, plus Sleeper itself,
do not all agree on every team code. Checked directly against a live pull:
FFC and FantasyPros' ``team`` column already match Sleeper's convention for
every team except Jacksonville, which FantasyPros' export spells ``"JAC"``
against Sleeper/FFC's ``"JAX"`` -- the sole entry in
:data:`TEAM_ABBREVIATION_ALIASES`. (``LAR``/``LAC``/``WAS``/``ARI`` were
specifically checked, per this ticket's guidance, and already match; they
are not aliased because there is nothing to alias.) Every team-abbreviation
column this module produces or reads is passed through
:func:`_normalize_team`, so a future source-side rename needs only a new
entry in that one dict.

Column dtypes
--------------

:data:`DRAFT_MARKET_COLUMNS` is documented with a fixed dtype per column
(``season``: ``int64``; ``consensus_rank``/``rank_sd``/``rank_best``/
``rank_worst``/``bye_week``: ``float64``; everything else: ``object``).
Every builder in this module -- including the empty-input case -- returns a
frame matching those dtypes exactly, so a caller can ``pd.concat`` this
module's output with itself (e.g. across seasons) or check ``pd.isna()``
without a dtype surprise, the same convention
``player_rankings.py``/``player_value.py`` document for their own
``_empty_frame`` helpers.

Missing values / edge cases
------------------------------

- **An unreachable source** (``FfcAdpClient``/``FantasyProsEcrClient``
  returning an empty, no-column ``DataFrame`` for a 404): the corresponding
  builder returns an empty :data:`DRAFT_MARKET_COLUMNS`-shaped frame, never
  raises. :func:`build_draft_market` simply omits that source's rows from
  the concatenated result.
- **A player neither join resolves**: kept, with ``sleeper_player_id`` (and
  ``gsis_id``) left ``None`` rather than the row being dropped -- a
  downstream consumer may still want the raw ADP/ECR value even without a
  Sleeper ID, and dropping the row would silently understate FFC's/
  FantasyPros' rankings depth. Check with ``pandas.isna()`` per this
  codebase's convention.
- **Duplicate names in ``db_playerids``** (retired players, practice-squad
  duplicates, and free-agent placeholder rows all sharing a real player's
  name): resolved by ``(normalized name, position)`` with a
  prefer-a-populated-``sleeper_id`` policy, last-value-wins on ties --
  the same collision policy
  :func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk_from_player_ids`
  documents for its own ``gsis_id``/``sleeper_player_id`` collisions,
  applied here to a different key.
- **Missing ``rank_sd``/``bye_week``/etc.**: left ``NaN`` (``float64``),
  never ``0`` or a sentinel -- ``0`` would be a real, meaningfully
  different standard deviation or bye week.

The wide player pool: :func:`build_draft_market_player_pool`
-------------------------------------------------------------

The long-format table above has one row per *(source, player)* -- exactly
right for keeping FFC's ADP and FantasyPros' ECR as independently
inspectable observations, but not the shape a downstream ranking/blending
consumer (the separate ``draft_board`` module) wants: that consumer needs
one row per player with both sources' values as sibling columns. See
:func:`build_draft_market_player_pool`'s own docstring for that pivot's
exact contract, including its ``position_ecr`` column (drawn from
FantasyPros' *per-position* ranking pages -- ``redraft-qb``, ``redraft-rb``,
etc. -- which live in the same ``db_fpecr_latest.csv`` asset, distinguished
by ``page_type``, so no second download is needed) and how it resolves a
player-identity field (name/position/team) when both sources disagree.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

#: Column order and dtype contract for every builder in this module. See
#: the module docstring's "Column dtypes" section.
DRAFT_MARKET_COLUMNS = [
    "season",
    "source",
    "sleeper_player_id",
    "gsis_id",
    "player_name",
    "position",
    "nfl_team",
    "consensus_rank",
    "rank_sd",
    "rank_best",
    "rank_worst",
    "bye_week",
]

#: ``DRAFT_MARKET_COLUMNS`` entries that are always ``float64``, including
#: on an empty frame. Every other column (except ``season``, handled
#: separately) is ``object``.
_FLOAT_COLUMNS = {"consensus_rank", "rank_sd", "rank_best", "rank_worst", "bye_week"}

#: The two source labels a conforming ``source`` column may carry.
FFC_ADP_SOURCE = "ffc_adp"
FANTASYPROS_ECR_SOURCE = "fantasypros_ecr"

#: FantasyPros' ``page_type`` value covering every position at once,
#: ranked together -- this is what :func:`build_fantasypros_draft_market`
#: filters ``db_fpecr_latest.csv`` to for the long-format table.
FANTASYPROS_OVERALL_PAGE_TYPE = "redraft-overall"

#: FantasyPros' per-position ``page_type`` values, keyed by this codebase's
#: (Sleeper-convention, post-alias) position label. Consumed only by
#: :func:`build_draft_market_player_pool` for its ``position_ecr`` column
#: -- see the module docstring's "wide player pool" section.
FANTASYPROS_POSITION_PAGE_TYPES = {
    "QB": "redraft-qb",
    "RB": "redraft-rb",
    "WR": "redraft-wr",
    "TE": "redraft-te",
    "K": "redraft-k",
    "DEF": "redraft-dst",
}

#: FFC's own position strings that differ from this codebase's Sleeper-
#: convention labels (``QB RB WR TE K DEF``). Verified directly: FFC's
#: only mismatch is ``"PK"`` for kicker; every other position string it
#: uses already matches.
FFC_POSITION_ALIASES: dict[str, str] = {"PK": "K"}

#: ``db_playerids.csv``'s own ``position`` column also spells kicker
#: ``"PK"`` rather than Sleeper's ``"K"`` -- verified directly. Applied to
#: that column (never to FFC's own rows a second time) before the
#: normalized-name-and-position join in
#: :func:`_player_ids_name_position_lookup`, so a kicker's already-aliased
#: ``"K"`` position (from either :data:`FFC_POSITION_ALIASES` or
#: :data:`FANTASYPROS_POSITION_ALIASES`) has something to match against.
#: Every other position ``db_playerids`` uses for offensive skill
#: positions/QB (``WR``/``RB``/``TE``/``QB``) already matches Sleeper's
#: convention.
PLAYER_IDS_POSITION_ALIASES: dict[str, str] = {"PK": "K"}

#: FantasyPros' own position strings that differ from Sleeper convention.
#: Verified directly: only team defense (``"DST"``) differs.
FANTASYPROS_POSITION_ALIASES: dict[str, str] = {"DST": "DEF"}

#: Team-abbreviation mismatches between the two sources and Sleeper's own
#: convention. See the module docstring's "DST/DEF special case" section
#: for what was checked and why this is currently a single entry.
TEAM_ABBREVIATION_ALIASES: dict[str, str] = {"JAC": "JAX"}

_NAME_PUNCTUATION_RE = re.compile(r"[.'’]")
_NAME_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_NAME_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

#: One row per resolved ``sleeper_player_id`` -- the shape
#: :func:`build_draft_market_player_pool` returns. See that function's
#: docstring.
DRAFT_MARKET_POOL_COLUMNS = [
    "sleeper_player_id",
    "player_name",
    "position",
    "nfl_team",
    "adp",
    "adp_sd",
    "adp_best",
    "adp_worst",
    "ecr",
    "ecr_sd",
    "ecr_best",
    "ecr_worst",
    "position_ecr",
    "bye_week",
]

#: ``DRAFT_MARKET_POOL_COLUMNS`` entries that are always ``object``; every
#: other column is ``float64``.
_POOL_OBJECT_COLUMNS = {"sleeper_player_id", "player_name", "position", "nfl_team"}


def _is_missing(value: object) -> bool:
    """True for ``None``/``NaN``/``NA``/empty string; false otherwise.

    Duplicated from the same helper in ``player_value.py``/
    ``player_rankings.py`` rather than imported, per this codebase's
    convention of not importing private names across modules.
    """
    if isinstance(value, str):
        return value == ""
    return pd.isna(value)


def _normalize_player_name(name: object) -> Optional[str]:
    """Normalize a player name for fuzzy name-based matching.

    Lowercases, strips periods/apostrophes, removes standalone generational
    suffixes (``Jr``, ``Sr``, ``II``-``V``), and collapses everything else
    to single spaces -- e.g. ``"Michael Pittman Jr."`` and
    ``"Amon-Ra St. Brown"`` normalize to ``"michael pittman"`` and
    ``"amon ra st brown"`` respectively. This is the one small
    normalization helper the ticket calls for; no equivalent already
    existed in :mod:`fantasy_analyzer.players.crosswalk`, which only ever
    joins by explicit ID.

    Returns:
        The normalized name, or ``None`` for a missing/blank input.
    """
    if _is_missing(name):
        return None
    text = _NAME_PUNCTUATION_RE.sub("", str(name).lower())
    text = _NAME_SUFFIX_RE.sub(" ", text)
    text = _NAME_NON_ALNUM_RE.sub(" ", text)
    normalized = " ".join(text.split())
    return normalized or None


def _normalize_position(position: object, aliases: dict[str, str]) -> Optional[str]:
    """Upper-case ``position`` and apply a source-specific alias map."""
    if _is_missing(position):
        return None
    text = str(position).strip().upper()
    return aliases.get(text, text)


def _normalize_team(team: object) -> Optional[str]:
    """Upper-case ``team`` and apply :data:`TEAM_ABBREVIATION_ALIASES`."""
    if _is_missing(team):
        return None
    text = str(team).strip().upper()
    return TEAM_ABBREVIATION_ALIASES.get(text, text)


def _coerce_sleeper_id(value: object) -> Optional[str]:
    """Render a numeric-ish ``sleeper_id`` as the plain-digit string Sleeper uses.

    ``db_playerids.csv`` stores ``sleeper_id`` as ``float64`` (the column
    mixes real IDs with ``NaN`` for unmatched rows); a naive ``str()`` cast
    would render ``"6794.0"`` instead of the ``"6794"`` Sleeper's own
    ``player_id`` strings use. Mirrors
    ``crosswalk.build_id_crosswalk_from_player_ids``'s identical cast.
    """
    if _is_missing(value):
        return None
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def _sleeper_gsis_lookup(
    working: pd.DataFrame, keys: list
) -> dict:
    """Zip ``keys`` against ``working``'s already-deduplicated ID columns.

    Shared tail of :func:`_player_ids_name_position_lookup` and
    :func:`_fantasypros_id_lookup`: both build a lookup keyed by some
    already-deduplicated join key, valued by ``(sleeper_id, gsis_id)``.
    ``working`` must already be deduplicated by the caller (this helper
    does not enforce uniqueness itself); ``keys`` must be the same length
    and row order as ``working``.
    """
    gsis_column = (
        working["gsis_id"] if "gsis_id" in working.columns else pd.Series(dtype=object)
    )
    gsis_values = gsis_column.reindex(working.index) if not gsis_column.empty else None
    return {
        key: (
            _coerce_sleeper_id(sleeper_id),
            None if gsis_values is None or _is_missing(gsis_value) else gsis_value,
        )
        for key, sleeper_id, gsis_value in zip(
            keys,
            working["sleeper_id"],
            gsis_values if gsis_values is not None else [None] * len(working),
        )
    }


def _player_ids_name_position_lookup(
    player_ids: pd.DataFrame,
) -> dict[tuple[str, str], tuple[Optional[str], Optional[str]]]:
    """Build a ``(normalized name, position) -> (sleeper_id, gsis_id)`` lookup.

    Used only for FFC rows, which carry no FantasyPros ID to join on. See
    the module docstring's "duplicate names" bullet for the collision
    policy applied when more than one ``db_playerids`` row shares a
    ``(normalized name, position)`` key.
    """
    if player_ids is None or player_ids.empty:
        return {}
    required = {"name", "position", "sleeper_id"}
    if not required.issubset(player_ids.columns):
        return {}

    working = player_ids.copy()
    working["norm_name"] = working["name"].map(_normalize_player_name)
    working["position"] = working["position"].map(
        lambda p: _normalize_position(p, PLAYER_IDS_POSITION_ALIASES)
    )
    working = working.dropna(subset=["norm_name"])
    # NaN sleeper_id sorts first, so keep="last" below prefers a row that
    # actually has a sleeper_id when duplicate keys collide.
    working = working.sort_values("sleeper_id", na_position="first")
    working = working.drop_duplicates(subset=["norm_name", "position"], keep="last")

    keys = list(zip(working["norm_name"], working["position"]))
    return _sleeper_gsis_lookup(working, keys)


def _fantasypros_id_lookup(
    player_ids: pd.DataFrame,
) -> dict[float, tuple[Optional[str], Optional[str]]]:
    """Build a ``fantasypros_id -> (sleeper_id, gsis_id)`` lookup.

    ``fantasypros_id`` is coerced with ``pd.to_numeric(..., errors="coerce")``
    per the ticket's finding that the source column is not clean.
    """
    if player_ids is None or player_ids.empty:
        return {}
    required = {"fantasypros_id", "sleeper_id"}
    if not required.issubset(player_ids.columns):
        return {}

    working = player_ids.copy()
    working["fantasypros_id"] = pd.to_numeric(
        working["fantasypros_id"], errors="coerce"
    )
    working = working.dropna(subset=["fantasypros_id"])
    working = working.sort_values("sleeper_id", na_position="first")
    working = working.drop_duplicates(subset=["fantasypros_id"], keep="last")

    return _sleeper_gsis_lookup(working, list(working["fantasypros_id"]))


def _empty_frame() -> pd.DataFrame:
    """An empty :data:`DRAFT_MARKET_COLUMNS`-shaped frame with correct dtypes.

    See ``player_rankings.py``'s ``_empty_frame`` for the identical
    reasoning: a bare ``pd.DataFrame(columns=...)`` is all-``object``
    dtype, which would upcast any ``pd.concat`` with a non-empty frame.
    """
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype=(
                    "int64"
                    if column == "season"
                    else "float64"
                    if column in _FLOAT_COLUMNS
                    else "object"
                )
            )
            for column in DRAFT_MARKET_COLUMNS
        }
    )


def _finalize(result: pd.DataFrame) -> pd.DataFrame:
    """Cast a raw builder result to :data:`DRAFT_MARKET_COLUMNS`' dtype contract."""
    result = result[DRAFT_MARKET_COLUMNS].copy()
    result["season"] = result["season"].astype("int64")
    for column in _FLOAT_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce").astype(
            "float64"
        )
    for column in DRAFT_MARKET_COLUMNS:
        if column not in _FLOAT_COLUMNS and column != "season":
            result[column] = result[column].astype("object")
    return result.reset_index(drop=True)


def validate_draft_market_columns(draft_market: pd.DataFrame) -> None:
    """Check that ``draft_market`` carries :data:`DRAFT_MARKET_COLUMNS`, in order.

    Mirrors ``projections.validate_projection_columns``. Does not check row
    values -- ``sleeper_player_id``/``gsis_id`` are legitimately ``None``
    per the module docstring's "missing values" section.

    Args:
        draft_market: A DataFrame as returned by :func:`build_draft_market`
            (or any conforming builder in this module).

    Raises:
        ValueError: If any of :data:`DRAFT_MARKET_COLUMNS` is missing, or
            the leading columns of ``draft_market`` are out of order.
    """
    actual_prefix = list(draft_market.columns[: len(DRAFT_MARKET_COLUMNS)])
    if actual_prefix != DRAFT_MARKET_COLUMNS:
        missing = [
            column
            for column in DRAFT_MARKET_COLUMNS
            if column not in draft_market.columns
        ]
        if missing:
            raise ValueError(
                "Draft-market DataFrame is missing required column(s): "
                f"{missing}."
            )
        raise ValueError(
            "Draft-market DataFrame's leading columns must be "
            f"{DRAFT_MARKET_COLUMNS} (in order); got {actual_prefix}."
        )


def build_ffc_draft_market(
    ffc_players: pd.DataFrame, player_ids: pd.DataFrame, season: int
) -> pd.DataFrame:
    """Normalize FantasyFootballCalculator's raw ADP table to canonical shape.

    Args:
        ffc_players: FFC's raw ``"players"`` array as a DataFrame, as
            returned by ``FfcAdpClient.download_adp`` (or a cached copy).
        player_ids: DynastyProcess's raw ``db_playerids.csv`` table (as
            returned by
            :meth:`~fantasy_analyzer.players.id_crosswalk_client.PlayerIdCrosswalkClient.download_player_ids`),
            used for the normalized-name/position join described in the
            module docstring. May be empty -- every row then simply keeps
            ``sleeper_player_id``/``gsis_id`` as ``None`` for non-defense
            positions (defenses still resolve via team abbreviation, which
            never needs ``player_ids``).
        season: The draft season this data describes, e.g. ``2026``.

    Returns:
        A :data:`DRAFT_MARKET_COLUMNS`-shaped DataFrame with
        ``source="ffc_adp"``. Empty (same columns/dtypes) if ``ffc_players``
        has no rows.
    """
    if ffc_players is None or ffc_players.empty:
        return _empty_frame()

    working = ffc_players.copy()
    working["position"] = working["position"].map(
        lambda p: _normalize_position(p, FFC_POSITION_ALIASES)
    )
    working["nfl_team"] = working["team"].map(_normalize_team)
    working["norm_name"] = working["name"].map(_normalize_player_name)

    is_def = working["position"] == "DEF"
    name_lookup = _player_ids_name_position_lookup(player_ids)

    sleeper_ids: list[Optional[str]] = []
    gsis_ids: list[Optional[str]] = []
    for is_defense, team, norm_name, position in zip(
        is_def, working["nfl_team"], working["norm_name"], working["position"]
    ):
        if is_defense:
            sleeper_ids.append(team)
            gsis_ids.append(None)
            continue
        match = name_lookup.get((norm_name, position)) if norm_name else None
        sleeper_ids.append(match[0] if match else None)
        gsis_ids.append(match[1] if match else None)

    result = pd.DataFrame(
        {
            "season": season,
            "source": FFC_ADP_SOURCE,
            "sleeper_player_id": sleeper_ids,
            "gsis_id": gsis_ids,
            "player_name": working["name"],
            "position": working["position"],
            "nfl_team": working["nfl_team"],
            "consensus_rank": working.get("adp"),
            "rank_sd": working.get("stdev"),
            "rank_best": working.get("high"),
            "rank_worst": working.get("low"),
            "bye_week": working.get("bye"),
        }
    )
    return _finalize(result)


def _resolve_fantasypros_page(
    page: pd.DataFrame, player_ids: pd.DataFrame
) -> pd.DataFrame:
    """Attach normalized ``position``/``nfl_team``/Sleeper-ID columns to one FP page.

    Shared by :func:`build_fantasypros_draft_market` (the
    ``redraft-overall`` page) and :func:`build_draft_market_player_pool`
    (the per-position pages, for ``position_ecr``) so both go through the
    identical DST-vs-explicit-ID-join logic.
    """
    working = page.copy()
    working["position"] = working["pos"].map(
        lambda p: _normalize_position(p, FANTASYPROS_POSITION_ALIASES)
    )
    working["nfl_team"] = working["team"].map(_normalize_team)

    is_def = working["position"] == "DEF"
    id_lookup = _fantasypros_id_lookup(player_ids)
    fp_ids = pd.to_numeric(working["id"], errors="coerce") if "id" in working else None

    sleeper_ids: list[Optional[str]] = []
    gsis_ids: list[Optional[str]] = []
    for idx, is_defense in zip(working.index, is_def):
        if is_defense:
            sleeper_ids.append(working.at[idx, "nfl_team"])
            gsis_ids.append(None)
            continue
        fp_id = fp_ids.at[idx] if fp_ids is not None else None
        match = id_lookup.get(fp_id) if fp_id is not None and pd.notna(fp_id) else None
        sleeper_ids.append(match[0] if match else None)
        gsis_ids.append(match[1] if match else None)

    working["sleeper_player_id"] = sleeper_ids
    working["gsis_id"] = gsis_ids
    return working


def build_fantasypros_draft_market(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame, season: int
) -> pd.DataFrame:
    """Normalize DynastyProcess's FantasyPros ECR export to canonical shape.

    Filters to :data:`FANTASYPROS_OVERALL_PAGE_TYPE` (``"redraft-overall"``)
    -- the single ranked-together-across-positions page -- for this
    long-format table. The per-position pages
    (:data:`FANTASYPROS_POSITION_PAGE_TYPES`) are consumed only by
    :func:`build_draft_market_player_pool`'s ``position_ecr`` column, not
    here, to keep this function's output free of the "which of six
    equally-valid ECR numbers is *the* ``consensus_rank`` for this row"
    ambiguity a per-position row would introduce into a single long table.

    Args:
        fpecr_raw: DynastyProcess's raw ``db_fpecr_latest.csv`` table (all
            ``page_type`` values), as returned by
            :meth:`~fantasy_analyzer.players.draft_market_client.FantasyProsEcrClient.download_ecr`.
        player_ids: DynastyProcess's raw ``db_playerids.csv`` table, used
            for the ``fantasypros_id`` join described in the module
            docstring. May be empty.
        season: The draft season this data describes, e.g. ``2026``.

    Returns:
        A :data:`DRAFT_MARKET_COLUMNS`-shaped DataFrame with
        ``source="fantasypros_ecr"``. Empty (same columns/dtypes) if
        ``fpecr_raw`` is empty, lacks a ``page_type`` column, or has no
        ``redraft-overall`` rows.
    """
    if fpecr_raw is None or fpecr_raw.empty or "page_type" not in fpecr_raw.columns:
        return _empty_frame()

    overall = fpecr_raw[fpecr_raw["page_type"] == FANTASYPROS_OVERALL_PAGE_TYPE]
    if overall.empty:
        return _empty_frame()

    resolved = _resolve_fantasypros_page(overall, player_ids)
    result = pd.DataFrame(
        {
            "season": season,
            "source": FANTASYPROS_ECR_SOURCE,
            "sleeper_player_id": resolved["sleeper_player_id"],
            "gsis_id": resolved["gsis_id"],
            "player_name": resolved["player"],
            "position": resolved["position"],
            "nfl_team": resolved["nfl_team"],
            "consensus_rank": resolved.get("ecr"),
            "rank_sd": resolved.get("sd"),
            "rank_best": resolved.get("best"),
            "rank_worst": resolved.get("worst"),
            "bye_week": resolved.get("bye"),
        }
    )
    return _finalize(result)


def build_draft_market(
    ffc_players: pd.DataFrame,
    fpecr_raw: pd.DataFrame,
    player_ids: pd.DataFrame,
    season: int,
) -> pd.DataFrame:
    """Build the combined long-format draft-market table for both sources.

    Args:
        ffc_players: FFC's raw ADP players table; see
            :func:`build_ffc_draft_market`.
        fpecr_raw: DynastyProcess's raw FantasyPros ECR export; see
            :func:`build_fantasypros_draft_market`.
        player_ids: DynastyProcess's raw ``db_playerids.csv`` table, shared
            by both sources' ID joins.
        season: The draft season this data describes, e.g. ``2026``.

    Returns:
        A :data:`DRAFT_MARKET_COLUMNS`-shaped DataFrame, one row per
        (source, player), concatenating both sources' normalized output.
        Empty (same columns/dtypes) if both sources are empty -- a
        one-source-unreachable case still returns the other source's rows
        rather than failing the whole build, per the module docstring's
        "an unreachable source" bullet.
    """
    frames = [
        build_ffc_draft_market(ffc_players, player_ids, season),
        build_fantasypros_draft_market(fpecr_raw, player_ids, season),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return _empty_frame()
    return _finalize(pd.concat(frames, ignore_index=True))


def _empty_pool_frame() -> pd.DataFrame:
    """An empty :data:`DRAFT_MARKET_POOL_COLUMNS`-shaped frame with correct dtypes."""
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype="object" if column in _POOL_OBJECT_COLUMNS else "float64"
            )
            for column in DRAFT_MARKET_POOL_COLUMNS
        }
    )


def _position_ecr_table(
    fpecr_raw: pd.DataFrame, player_ids: pd.DataFrame
) -> pd.DataFrame:
    """Build a ``sleeper_player_id -> position_ecr`` table from FP's per-position pages.

    Each of :data:`FANTASYPROS_POSITION_PAGE_TYPES` ranks players only
    against others at the same position, unlike the ``redraft-overall``
    page :func:`build_fantasypros_draft_market` uses. A player appears on
    at most one such page (its own position), so no cross-position
    collision is possible; a duplicate ``sleeper_player_id`` within one
    page (e.g. a data anomaly) keeps the last-encountered row.
    """
    if (
        fpecr_raw is None
        or fpecr_raw.empty
        or "page_type" not in fpecr_raw.columns
    ):
        return pd.DataFrame(columns=["sleeper_player_id", "position_ecr"])

    rows = []
    for page_type in FANTASYPROS_POSITION_PAGE_TYPES.values():
        page = fpecr_raw[fpecr_raw["page_type"] == page_type]
        if page.empty:
            continue
        resolved = _resolve_fantasypros_page(page, player_ids)
        rows.append(
            resolved[["sleeper_player_id", "ecr"]].rename(
                columns={"ecr": "position_ecr"}
            )
        )

    if not rows:
        return pd.DataFrame(columns=["sleeper_player_id", "position_ecr"])

    combined = pd.concat(rows, ignore_index=True)
    combined = combined.dropna(subset=["sleeper_player_id"])
    combined["position_ecr"] = pd.to_numeric(
        combined["position_ecr"], errors="coerce"
    )
    return combined.drop_duplicates(subset=["sleeper_player_id"], keep="last")


def build_draft_market_player_pool(
    draft_market: pd.DataFrame,
    fpecr_raw: pd.DataFrame,
    player_ids: pd.DataFrame,
) -> pd.DataFrame:
    """Pivot the long-format draft-market table to one row per Sleeper player.

    This is the shape a downstream blending/ranking consumer (the separate
    ``draft_board`` module) is expected to consume: FFC's ADP and
    FantasyPros' overall ECR as sibling columns on the same row, plus a
    per-position ECR column, rather than the long table's one-row-per-
    (source, player) shape.

    Args:
        draft_market: A :data:`DRAFT_MARKET_COLUMNS`-shaped DataFrame, as
            returned by :func:`build_draft_market` (both sources'
            normalized rows). Rows with ``sleeper_player_id`` unset are
            excluded from this pivot -- there is no key to pivot them on;
            callers who need those rows should use ``draft_market``
            directly.
        fpecr_raw: DynastyProcess's raw FantasyPros ECR export, used here
            (in addition to ``draft_market``) to source the per-position
            ``position_ecr`` column -- see :data:`FANTASYPROS_POSITION_PAGE_TYPES`.
            May be empty, in which case ``position_ecr`` is ``NaN`` for
            every row.
        player_ids: DynastyProcess's raw ``db_playerids.csv`` table, needed
            to resolve the per-position pages' Sleeper IDs the same way
            :func:`build_fantasypros_draft_market` does for the overall
            page.

    Returns:
        A :data:`DRAFT_MARKET_POOL_COLUMNS`-shaped DataFrame, one row per
        ``sleeper_player_id`` that either source resolved. ``player_name``/
        ``position``/``nfl_team`` prefer FantasyPros' values when both
        sources have a row for that player (FantasyPros' overall page
        covers more of the pool -- 517 vs. FFC's ~233 rows as of this
        ticket -- so it is the more complete identity source), falling
        back to FFC's values when only FFC resolved that player. Empty
        (same columns/dtypes) if neither source has any resolved rows.
    """
    if draft_market is None or draft_market.empty:
        return _empty_pool_frame()

    matched = draft_market[draft_market["sleeper_player_id"].notna()]
    if matched.empty:
        return _empty_pool_frame()

    identity_and_rank = [
        "sleeper_player_id",
        "player_name",
        "position",
        "nfl_team",
        "consensus_rank",
        "rank_sd",
        "rank_best",
        "rank_worst",
        "bye_week",
    ]

    ffc_wide = (
        matched.loc[matched["source"] == FFC_ADP_SOURCE, identity_and_rank]
        .rename(
            columns={
                "consensus_rank": "adp",
                "rank_sd": "adp_sd",
                "rank_best": "adp_best",
                "rank_worst": "adp_worst",
            }
        )
        .drop_duplicates(subset="sleeper_player_id", keep="last")
    )
    fpecr_wide = (
        matched.loc[matched["source"] == FANTASYPROS_ECR_SOURCE, identity_and_rank]
        .rename(
            columns={
                "consensus_rank": "ecr",
                "rank_sd": "ecr_sd",
                "rank_best": "ecr_best",
                "rank_worst": "ecr_worst",
            }
        )
        .drop_duplicates(subset="sleeper_player_id", keep="last")
    )

    pool = pd.merge(
        fpecr_wide,
        ffc_wide,
        on="sleeper_player_id",
        how="outer",
        suffixes=("_fp", "_ffc"),
    )

    for column in ("player_name", "position", "nfl_team", "bye_week"):
        fp_column, ffc_column = f"{column}_fp", f"{column}_ffc"
        fp_values = pool[fp_column] if fp_column in pool.columns else None
        ffc_values = pool[ffc_column] if ffc_column in pool.columns else None
        if fp_values is not None and ffc_values is not None:
            pool[column] = fp_values.combine_first(ffc_values)
        elif fp_values is not None:
            pool[column] = fp_values
        elif ffc_values is not None:
            pool[column] = ffc_values
        pool = pool.drop(
            columns=[c for c in (fp_column, ffc_column) if c in pool.columns]
        )

    position_ecr = _position_ecr_table(fpecr_raw, player_ids)
    pool = pool.merge(position_ecr, on="sleeper_player_id", how="left")

    for column in DRAFT_MARKET_POOL_COLUMNS:
        if column not in pool.columns:
            pool[column] = pd.NA

    pool = pool[DRAFT_MARKET_POOL_COLUMNS].copy()
    for column in DRAFT_MARKET_POOL_COLUMNS:
        if column in _POOL_OBJECT_COLUMNS:
            pool[column] = pool[column].astype("object")
        else:
            pool[column] = pd.to_numeric(pool[column], errors="coerce").astype(
                "float64"
            )

    pool = pool.sort_values(
        ["ecr", "adp"], na_position="last", kind="stable"
    ).reset_index(drop=True)
    return pool
