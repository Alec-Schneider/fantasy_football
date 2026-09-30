"""Snap-count and expected-opportunity usage player-weeks (FFA-110).

nflverse's weekly player stats (``nflverse_provider``) tell a projection how
much a player *produced* and how much volume he saw, but not how much he was
on the field (no snap counts) nor how *good* his opportunities were (no
expected points). This module joins the two sources that fill those gaps
onto a single GSIS-keyed player-week table, with no network access: it reads
only the local caches ``scripts/fetch_usage_seasons.py`` populates.

Sources
--------------------------------------------------------------------------

**Snap counts** (``snap_counts_cache``): nflverse's republication of Pro
Football Reference snap counts, one row per player-game, every position.
Keyed on ``pfr_player_id``, so it needs an id mapping -- see below.

**Expected points** (``expected_points_cache``): ffverse's ffopportunity
model, one row per player-week with at least one charted opportunity.
``player_id`` there **is a GSIS id**: on 2026 weeks 1-3 every non-null
value has the ``00-NNNNNNN`` form and 954/954 rows join to nflverse's
player stats on ``(season, week, player_id)``, with targets, carries and
pass attempts equal on every joined row. Rows with a null ``player_id``
(one per team-game, 74 in 2026 so far) carry only unattributed targets and
are dropped -- they belong to no player.

What scoring system ffopportunity's fantasy points assume
--------------------------------------------------------------------------

**Full PPR.** Reverse-engineered from the 2026 file rather than taken on
trust: ``total_fantasy_points`` equals, on 100% of 954 player rows,

    0.04 x pass yds + 4 x pass TD - 2 x INT
    + 0.1 x (rush + rec yds) + 6 x (rush + rec TD) + 1 x reception
    + 2 x two-point conversion - 2 x fumble lost

The same formula with 0 or 0.5 per reception matches only 22-28% of rows.
The ``*_fantasy_points_exp`` columns use the same weights, minus the
fumble term (there is no fumble expectation) and with no charge for a
receiver's ``rec_interception_exp``: every row reconstructs from its
``*_exp`` components to within 0.07 points, which is the rounding of
two-decimal inputs. First downs are not scored.

So ``ep_total_fantasy_points_exp`` is a **full-PPR** xFP. A half-PPR league
should not use it directly: re-score the component expected stats
(``ep_receptions_exp``, ``ep_rec_yards_gained_exp``, ``ep_rec_touchdown_exp``,
``ep_rush_yards_gained_exp``, ``ep_rush_touchdown_exp``,
``ep_pass_yards_gained_exp``, ``ep_pass_touchdown_exp``,
``ep_pass_interception_exp``, the ``*_two_point_conv_exp`` and
``*_first_down_exp`` columns) under the league's own scoring settings. That
is why every component is passed through.

Team totals are passed through too, with one trap:
``ep_total_fantasy_points_exp_team`` is **receiving + rushing only**. It
omits passing xFP so that a completion is not counted twice, once for the
passer and once for the receiver. Summing ``ep_total_fantasy_points_exp``
over a team's players *does* double-count. An xFP share should therefore
divide a player's ``ep_rec_fantasy_points_exp + ep_rush_fantasy_points_exp``
by ``ep_total_fantasy_points_exp_team``. ``ep_rec_attempt_team`` includes the
unattributed targets on the dropped null-player rows, so it is the right
denominator for a target share.

The ``*_diff`` columns (actual minus expected) are not passed through, since
they are exactly derivable from the columns that are.

Mapping snap counts to GSIS ids
--------------------------------------------------------------------------

Two steps, in order, both conservative. A row neither step can place keeps
``gsis_id`` null in :func:`normalize_snap_counts`'s output, which is where the
unmapped diagnostics come from, and is dropped by
:func:`load_usage_player_weeks`, which is keyed on ``gsis_id``.

1. **ID crosswalk.** DynastyProcess's ``db_playerids.csv`` (``pfr_id`` ->
   ``gsis_id``), see :func:`build_pfr_to_gsis_lookup`. Only strictly
   one-to-one pairs are used. The file has a handful of ``pfr_id`` values
   carrying two different ``gsis_id`` values, and the reverse; both sides of
   such a conflict are dropped rather than guessed between.
2. **Name fallback**, only for still-unmapped pfr ids that logged at least
   one offensive snap. A snap row matches a nflverse player-stats row from
   the same season and week when normalized name, team, and position group
   all agree, and the match is **unique on both sides**: exactly one snap
   row and exactly one stats row share that key. Stats rows whose GSIS id the
   crosswalk already assigned are excluded, so a fallback can never collide
   with a crosswalk match. A pfr id's week-level matches are then pooled
   across the frame. If they all point to one GSIS id, that id is applied to
   *every* row of that pfr id, including weeks with snaps but no stats row.
   If they point to more than one, or that GSIS id is also claimed by
   another pfr id, it stays unmapped.

``snap_id_source`` records which step placed each row: ``"crosswalk"``,
``"name_fallback"``, or null.

Snap-count details
--------------------------------------------------------------------------

``offense_snap_pct`` is a fraction in [0, 1], computed as
``offense_snaps / team_offense_snaps``. It is not nflverse's own
``offense_pct``, which is rounded to two decimals. ``team_offense_snaps`` is
the team's offensive play count for that game, taken from a player at
``offense_pct == 1.0`` when there is one, which is exact because snaps are
integers. Otherwise it is estimated as the rounded median of
``offense_snaps / offense_pct`` over players at 50% or more, floored at the
team's most-used player. The plain "team maximum" is not good enough: in a
few team-games per season nobody played every snap (2022 week 8 PHI: most
snaps 53, true total 57).

``team`` is rewritten to nflverse's current franchise codes
(:data:`SNAP_TEAM_ALIASES`): snap counts say ``OAK``/``SD``/``STL`` for the
seasons before each move, where every other source says ``LV``/``LAC``/``LA``.
Without this, the name fallback cannot match those teams' players and
2014-2019 ``team`` values disagree with ffopportunity's.

Pro Football Reference occasionally assigns one ``pfr_player_id`` to two
different players in the same week (``DaviJa06``, three times in
2019-2021, all with zero offensive snaps). Every row in such a collision
is dropped, since there is no way to tell which one is which.

The row universe: which zeros are real
--------------------------------------------------------------------------

This is the point a projection model most needs to get right.

- :func:`load_usage_player_weeks` is the **full snap universe**: one row for
  every player-week that has a mapped snap row, an ep row, or both. That
  includes a player who logged offensive snaps and got no target, carry or
  pass attempt, which is a genuine zero-usage week. Such a week has
  ``offense_snaps > 0`` and null ``ep_*`` columns, because ffopportunity
  emits a row only when a player had a charted opportunity (just 4 of 5,373
  2025 regular-season rows have zero pass, rec and rush attempts).
  It also includes defensive and special-teams snap rows, with
  ``offense_snaps == 0``.
- nflverse's player stats contain a zero-usage skill-position week **only
  when the player recorded some other stat**: a return, a tackle, a fumble
  recovery. That happened for 758 of 6,037 2025 regular-season QB/RB/WR/TE
  rows. A player who ran routes, drew no target and recorded nothing else
  has **no stats row at all**.
- So :func:`attach_usage` only **enriches existing stat rows**. It can never
  add the missing zero-usage weeks. A model that wants them (snap share
  without targets is a leading role indicator) must start from
  :func:`load_usage_player_weeks` and left-join stats onto it, not the other
  way around.

Throughout, null means "no source row", never zero. A stat row with no snap
row gets null ``offense_snaps``; a snap row with no ep row gets null
``ep_*``. Filling either with zero is the caller's decision.

Regular season vs playoffs
--------------------------------------------------------------------------

Regular season only by default. Snap counts are filtered on
``game_type == "REG"``. ffopportunity has no season-type column, so its
regular season is ``week <= regular_season_last_week(season)`` (17 before
2021, 18 from 2021 on). Pass ``regular_season_only=False`` to keep
postseason weeks (19-22) from both sources.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

import numpy as np
import pandas as pd

from fantasy_analyzer.players.expected_points_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_EP_CACHE_DIR,
)
from fantasy_analyzer.players.expected_points_cache import load_expected_points_cache
from fantasy_analyzer.players.id_crosswalk_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_PLAYER_IDS_CACHE_DIR,
)
from fantasy_analyzer.players.id_crosswalk_cache import load_player_ids_cache
from fantasy_analyzer.players.nflverse_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_STATS_CACHE_DIR,
)
from fantasy_analyzer.players.nflverse_cache import load_player_stats_cache
from fantasy_analyzer.players.snap_counts_cache import (
    DEFAULT_CACHE_DIR as DEFAULT_SNAP_CACHE_DIR,
)
from fantasy_analyzer.players.snap_counts_cache import load_snap_counts_cache

#: First season of the NFL's 18-week (17-game) regular season.
_FIRST_18_WEEK_SEASON = 2021

#: ``snap_id_source`` values; see the module docstring's mapping section.
SNAP_ID_SOURCE_CROSSWALK = "crosswalk"
SNAP_ID_SOURCE_NAME_FALLBACK = "name_fallback"

#: Columns of :func:`normalize_snap_counts`'s output, in order.
SNAP_COUNT_COLUMNS = [
    "season",
    "week",
    "game_id",
    "gsis_id",
    "pfr_player_id",
    "player_name",
    "position",
    "team",
    "offense_snaps",
    "offense_snap_pct",
    "team_offense_snaps",
    "snap_id_source",
]

#: Prefix applied to every ffopportunity column this module passes through.
EXPECTED_POINTS_PREFIX = "ep_"

#: Raw ffopportunity player-level columns passed through, each renamed to
#: ``ep_<name>``: opportunity counts, actual and expected components, and
#: actual/expected fantasy points (full PPR -- see the module docstring).
#: The ``*_diff`` columns are deliberately omitted (actual minus expected).
EXPECTED_POINTS_COLUMNS = [
    "pass_attempt",
    "rec_attempt",
    "rush_attempt",
    "pass_air_yards",
    "rec_air_yards",
    "pass_completions",
    "receptions",
    "pass_completions_exp",
    "receptions_exp",
    "pass_yards_gained",
    "rec_yards_gained",
    "rush_yards_gained",
    "pass_yards_gained_exp",
    "rec_yards_gained_exp",
    "rush_yards_gained_exp",
    "pass_touchdown",
    "rec_touchdown",
    "rush_touchdown",
    "pass_touchdown_exp",
    "rec_touchdown_exp",
    "rush_touchdown_exp",
    "pass_two_point_conv",
    "rec_two_point_conv",
    "rush_two_point_conv",
    "pass_two_point_conv_exp",
    "rec_two_point_conv_exp",
    "rush_two_point_conv_exp",
    "pass_first_down",
    "rec_first_down",
    "rush_first_down",
    "pass_first_down_exp",
    "rec_first_down_exp",
    "rush_first_down_exp",
    "pass_interception",
    "rec_interception",
    "pass_interception_exp",
    "rec_interception_exp",
    "rec_fumble_lost",
    "rush_fumble_lost",
    "pass_fantasy_points",
    "rec_fantasy_points",
    "rush_fantasy_points",
    "pass_fantasy_points_exp",
    "rec_fantasy_points_exp",
    "rush_fantasy_points_exp",
    "total_yards_gained",
    "total_yards_gained_exp",
    "total_touchdown",
    "total_touchdown_exp",
    "total_first_down",
    "total_first_down_exp",
    "total_fantasy_points",
    "total_fantasy_points_exp",
]

#: Raw ffopportunity *team-game* totals passed through as share
#: denominators, each renamed to ``ep_<name>``. See the module docstring:
#: ``total_fantasy_points_exp_team`` excludes passing xFP.
EXPECTED_POINTS_TEAM_COLUMNS = [
    "pass_attempt_team",
    "rec_attempt_team",
    "rush_attempt_team",
    "pass_air_yards_team",
    "rec_air_yards_team",
    "pass_fantasy_points_exp_team",
    "rec_fantasy_points_exp_team",
    "rush_fantasy_points_exp_team",
    "total_fantasy_points_exp_team",
    "total_fantasy_points_team",
]

#: Identity columns of :func:`normalize_expected_points`'s output, before
#: the ``ep_*`` columns.
_EXPECTED_POINTS_IDENTITY_COLUMNS = [
    "season",
    "week",
    "game_id",
    "gsis_id",
    "player_name",
    "position",
    "team",
]

#: Leading columns of :func:`load_usage_player_weeks`'s output, before the
#: ``ep_*`` columns.
USAGE_IDENTITY_COLUMNS = [
    "season",
    "week",
    "gsis_id",
    "pfr_player_id",
    "player_name",
    "position",
    "team",
    "game_id",
    "offense_snaps",
    "offense_snap_pct",
    "team_offense_snaps",
    "snap_id_source",
]

#: Columns :func:`attach_usage` never copies onto a stat frame: the join key
#: and labels the stat frame already carries in its own vocabulary.
_ATTACH_EXCLUDED_COLUMNS = {
    "season",
    "week",
    "gsis_id",
    "player_name",
    "position",
    "team",
}

#: Snap counts label relocated franchises by their team code *at the time*
#: (``OAK`` through 2019, ``SD`` through 2016, ``STL`` through 2015), while
#: nflverse's player stats and ffopportunity use the current franchise code
#: for every season. Measured on the 2014-2026 caches, these three are the
#: only differences; ``game_id`` agrees across all three sources as-is.
SNAP_TEAM_ALIASES: dict[str, str] = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

#: Position groups for the name fallback. Pro Football Reference labels some
#: backs ``HB``/``FB`` where nflverse says ``RB``/``FB``; anything else is
#: compared as-is.
_POSITION_GROUPS = {"HB": "RB", "FB": "RB", "RB": "RB"}

# Same patterns as draft_market's name normalizer, duplicated rather than
# imported per this codebase's convention of not importing private names.
_NAME_PUNCTUATION_RE = re.compile(r"[.'’]")
_NAME_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
_NAME_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def regular_season_last_week(season: int) -> int:
    """The last regular-season week of ``season``: 18 from 2021, else 17."""
    return 18 if int(season) >= _FIRST_18_WEEK_SEASON else 17


def _normalize_player_name(name: object) -> Optional[str]:
    """Lowercase, strip punctuation and generational suffixes, collapse spaces."""
    if name is None or (not isinstance(name, str) and pd.isna(name)):
        return None
    text = _NAME_PUNCTUATION_RE.sub("", str(name).lower())
    text = _NAME_SUFFIX_RE.sub(" ", text)
    text = _NAME_NON_ALNUM_RE.sub(" ", text)
    normalized = " ".join(text.split())
    return normalized or None


def _position_group(position: object) -> Optional[str]:
    """Upper-case ``position`` and fold PFR's back labels onto ``RB``."""
    if position is None or (not isinstance(position, str) and pd.isna(position)):
        return None
    text = str(position).strip().upper()
    return _POSITION_GROUPS.get(text, text)


def build_pfr_to_gsis_lookup(player_ids: pd.DataFrame) -> dict[str, str]:
    """Build a strictly one-to-one ``pfr_id -> gsis_id`` mapping.

    Args:
        player_ids: DynastyProcess's raw crosswalk, as returned by
            :func:`~fantasy_analyzer.players.id_crosswalk_cache.get_player_ids_cached`.

    Returns:
        ``{pfr_id: gsis_id}`` over rows carrying both ids. A pair repeated on
        several rows counts once. A ``pfr_id`` paired with more than one
        distinct ``gsis_id``, or a ``gsis_id`` paired with more than one
        distinct ``pfr_id``, is dropped entirely. Empty if either column is
        missing.
    """
    if not {"pfr_id", "gsis_id"}.issubset(player_ids.columns):
        return {}
    pairs = player_ids[["pfr_id", "gsis_id"]].dropna().astype(str)
    pairs = pairs[(pairs["pfr_id"] != "") & (pairs["gsis_id"] != "")]
    pairs = pairs.drop_duplicates()
    pairs = pairs[~pairs["pfr_id"].duplicated(keep=False)]
    pairs = pairs[~pairs["gsis_id"].duplicated(keep=False)]
    return dict(zip(pairs["pfr_id"], pairs["gsis_id"]))


def _team_offense_snaps(snaps: pd.DataFrame) -> pd.Series:
    """Each row's team offensive play count for its game.

    See the module docstring: exact from a 100% player when present,
    otherwise the rounded median implied total of 50%+ players, floored at
    the team's most-used player.
    """
    keys = ["season", "week", "team"]
    offense = snaps["offense_snaps"]
    pct = snaps["offense_pct"]

    most_used = offense.groupby([snaps[key] for key in keys]).transform("max")

    full = offense.where(pct >= 1.0)
    exact = full.groupby([snaps[key] for key in keys]).transform("max")

    implied = (offense / pct).where(pct >= 0.5)
    estimated = implied.groupby([snaps[key] for key in keys]).transform("median")
    estimated = np.maximum(estimated.round(), most_used)

    return exact.fillna(estimated).fillna(most_used)


def _name_fallback_lookup(
    unmapped: pd.DataFrame,
    player_stats: pd.DataFrame,
    claimed_gsis_ids: set[str],
) -> dict[str, str]:
    """Match still-unmapped pfr ids to GSIS ids by name, team and position.

    Args:
        unmapped: Normalized snap rows with no crosswalk ``gsis_id`` and
            ``offense_snaps > 0``.
        player_stats: Raw nflverse weekly player-stats rows (``player_id``,
            ``player_display_name``, ``team``, ``position``, ``season``,
            ``week``).
        claimed_gsis_ids: GSIS ids the crosswalk already assigned; never
            eligible as a fallback target.

    Returns:
        ``{pfr_player_id: gsis_id}`` for pfr ids whose every unique
        week-level match agrees on one GSIS id that no other pfr id also
        matched. See the module docstring for the full rule.
    """
    required = {
        "season",
        "week",
        "player_id",
        "player_display_name",
        "team",
        "position",
    }
    if (
        unmapped.empty
        or player_stats.empty
        or not required.issubset(player_stats.columns)
    ):
        return {}

    stats = player_stats[list(required)].dropna(subset=["player_id"]).copy()
    stats["player_id"] = stats["player_id"].astype(str)
    stats = stats[~stats["player_id"].isin(claimed_gsis_ids)]
    stats["_name"] = stats["player_display_name"].map(_normalize_player_name)
    stats["_group"] = stats["position"].map(_position_group)

    snaps = unmapped[
        ["season", "week", "pfr_player_id", "player_name", "team", "position"]
    ].copy()
    snaps["_name"] = snaps["player_name"].map(_normalize_player_name)
    snaps["_group"] = snaps["position"].map(_position_group)

    key = ["season", "week", "team", "_group", "_name"]
    stats = stats.dropna(subset=key)
    snaps = snaps.dropna(subset=key)
    stats = stats[~stats.duplicated(key, keep=False)]
    snaps = snaps[~snaps.duplicated(key, keep=False)]

    matched = snaps.merge(stats[key + ["player_id"]], on=key, how="inner")
    if matched.empty:
        return {}

    per_pfr = matched.groupby("pfr_player_id")["player_id"].agg(lambda ids: set(ids))
    per_pfr = per_pfr[per_pfr.map(len) == 1].map(lambda ids: next(iter(ids)))
    per_pfr = per_pfr[~per_pfr.duplicated(keep=False)]
    return dict(per_pfr)


def normalize_snap_counts(
    raw: pd.DataFrame,
    player_ids: pd.DataFrame,
    *,
    player_stats: Optional[pd.DataFrame] = None,
    regular_season_only: bool = True,
) -> pd.DataFrame:
    """Normalize raw nflverse snap counts and map them to GSIS ids.

    Args:
        raw: Raw snap-count rows, as returned by
            :func:`~fantasy_analyzer.players.snap_counts_cache.get_snap_counts_cached`
            (one or several seasons concatenated).
        player_ids: DynastyProcess's raw crosswalk, for the ``pfr_id ->
            gsis_id`` step (see :func:`build_pfr_to_gsis_lookup`).
        player_stats: Raw nflverse weekly player stats for the same seasons,
            used only by the name fallback. ``None`` skips the fallback.
        regular_season_only: Keep only ``game_type == "REG"`` rows (the
            default). ``False`` keeps postseason games too.

    Returns:
        :data:`SNAP_COUNT_COLUMNS`, one row per (season, week,
        pfr_player_id), sorted by season, week, team, pfr id. **Includes
        unmapped rows** (null ``gsis_id`` and ``snap_id_source``) so a caller
        can measure coverage; :func:`unmapped_snap_players` summarizes them.
        Every position is kept, so defensive and special-teams rows carry
        ``offense_snaps == 0``. Empty (same columns) for an empty input.
    """
    required = {
        "season",
        "week",
        "pfr_player_id",
        "team",
        "offense_snaps",
        "offense_pct",
    }
    if raw.empty or not required.issubset(raw.columns):
        return pd.DataFrame(columns=SNAP_COUNT_COLUMNS)

    snaps = raw
    if regular_season_only and "game_type" in snaps.columns:
        snaps = snaps[snaps["game_type"] == "REG"]
    snaps = snaps.dropna(subset=["pfr_player_id"])

    key = ["season", "week", "pfr_player_id"]
    snaps = snaps[~snaps.duplicated(key, keep=False)]
    if snaps.empty:
        return pd.DataFrame(columns=SNAP_COUNT_COLUMNS)

    result = pd.DataFrame(
        {
            "season": snaps["season"].astype(int),
            "week": snaps["week"].astype(int),
            "game_id": snaps["game_id"] if "game_id" in snaps.columns else None,
            "pfr_player_id": snaps["pfr_player_id"].astype(str),
            "player_name": snaps["player"] if "player" in snaps.columns else None,
            "position": snaps["position"] if "position" in snaps.columns else None,
            "team": snaps["team"].replace(SNAP_TEAM_ALIASES),
            "offense_snaps": snaps["offense_snaps"].astype(float),
            "offense_pct": snaps["offense_pct"].astype(float),
        }
    )
    result["team_offense_snaps"] = _team_offense_snaps(result)
    result["offense_snap_pct"] = (
        (result["offense_snaps"] / result["team_offense_snaps"])
        .where(result["team_offense_snaps"] > 0, 0.0)
        .clip(0.0, 1.0)
    )

    lookup = build_pfr_to_gsis_lookup(player_ids)
    result["gsis_id"] = result["pfr_player_id"].map(lookup)
    result["snap_id_source"] = np.where(
        result["gsis_id"].notna(), SNAP_ID_SOURCE_CROSSWALK, None
    )

    if player_stats is not None:
        candidates = result[result["gsis_id"].isna() & (result["offense_snaps"] > 0)]
        fallback = _name_fallback_lookup(candidates, player_stats, set(lookup.values()))
        if fallback:
            fill = result["gsis_id"].isna() & result["pfr_player_id"].isin(fallback)
            result.loc[fill, "gsis_id"] = result.loc[fill, "pfr_player_id"].map(
                fallback
            )
            result.loc[fill, "snap_id_source"] = SNAP_ID_SOURCE_NAME_FALLBACK

    result = result.sort_values(["season", "week", "team", "pfr_player_id"])
    return result[SNAP_COUNT_COLUMNS].reset_index(drop=True)


def unmapped_snap_players(snaps: pd.DataFrame) -> pd.DataFrame:
    """Summarize pfr ids with offensive snaps that no GSIS id was found for.

    Args:
        snaps: :func:`normalize_snap_counts`'s output.

    Returns:
        One row per unmapped ``pfr_player_id`` with ``offense_snaps > 0``:
        ``pfr_player_id``, ``player_name``, ``position``, ``team`` (each the
        most recent label), ``weeks`` and total ``offense_snaps``. Sorted by
        descending snaps, then pfr id.
    """
    columns = [
        "pfr_player_id",
        "player_name",
        "position",
        "team",
        "weeks",
        "offense_snaps",
    ]
    if snaps.empty:
        return pd.DataFrame(columns=columns)
    unmapped = snaps[snaps["gsis_id"].isna() & (snaps["offense_snaps"] > 0)]
    if unmapped.empty:
        return pd.DataFrame(columns=columns)
    ordered = unmapped.sort_values(["season", "week"])
    summary = ordered.groupby("pfr_player_id").agg(
        player_name=("player_name", "last"),
        position=("position", "last"),
        team=("team", "last"),
        weeks=("week", "size"),
        offense_snaps=("offense_snaps", "sum"),
    )
    summary = summary.reset_index().sort_values(
        ["offense_snaps", "pfr_player_id"], ascending=[False, True]
    )
    return summary[columns].reset_index(drop=True)


def normalize_expected_points(
    raw: pd.DataFrame, *, regular_season_only: bool = True
) -> pd.DataFrame:
    """Normalize raw ffopportunity weekly expected points to GSIS player-weeks.

    Args:
        raw: Raw ffopportunity rows, as returned by
            :func:`~fantasy_analyzer.players.expected_points_cache.get_expected_points_cached`
            (one or several seasons concatenated).
        regular_season_only: Keep only weeks at or before
            :func:`regular_season_last_week` (the default); ffopportunity has
            no season-type column.

    Returns:
        ``season``, ``week``, ``game_id``, ``gsis_id`` (ffopportunity's
        ``player_id``), ``player_name``, ``position``, ``team`` (``posteam``),
        then every :data:`EXPECTED_POINTS_COLUMNS` and
        :data:`EXPECTED_POINTS_TEAM_COLUMNS` entry present in ``raw``,
        renamed ``ep_<name>``. Rows with a null ``player_id`` (unattributed
        team targets) are dropped. One row per (season, week, gsis_id);
        should the source ever repeat a key, every copy is dropped rather
        than one picked arbitrarily. Empty (identity columns only) for an
        empty input.
    """
    required = {"season", "week", "player_id"}
    if raw.empty or not required.issubset(raw.columns):
        return pd.DataFrame(columns=_EXPECTED_POINTS_IDENTITY_COLUMNS)

    expected = raw.dropna(subset=["player_id"])
    if regular_season_only:
        last_week = expected["season"].map(regular_season_last_week)
        expected = expected[expected["week"] <= last_week]
    key = ["season", "week", "player_id"]
    expected = expected[~expected.duplicated(key, keep=False)]

    identity = {
        "season": expected["season"].astype(int),
        "week": expected["week"].astype(int),
        "game_id": expected.get("game_id"),
        "gsis_id": expected["player_id"].astype(str),
        "player_name": expected.get("full_name"),
        "position": expected.get("position"),
        "team": expected.get("posteam"),
    }
    passthrough = {
        f"{EXPECTED_POINTS_PREFIX}{column}": expected[column]
        for column in EXPECTED_POINTS_COLUMNS + EXPECTED_POINTS_TEAM_COLUMNS
        if column in expected.columns
    }
    result = pd.DataFrame({**identity, **passthrough}, index=expected.index)
    result = result.sort_values(["season", "week", "gsis_id"])
    return result.reset_index(drop=True)


def _load_required(
    loader: Callable[[int, Union[str, Path]], Optional[pd.DataFrame]],
    season: int,
    cache_dir: Union[str, Path],
    label: str,
) -> pd.DataFrame:
    """Load one cached season, raising if it was never fetched."""
    frame = loader(season, cache_dir)
    if frame is None:
        raise FileNotFoundError(
            f"No cached {label} for season {season} under {cache_dir}. "
            "Run scripts/fetch_usage_seasons.py (snap counts, expected points) "
            "or scripts/fetch_nflverse_seasons.py (player stats) first."
        )
    return frame


def load_usage_player_weeks(
    seasons: Iterable[int],
    *,
    snap_cache_dir: Union[str, Path] = DEFAULT_SNAP_CACHE_DIR,
    ep_cache_dir: Union[str, Path] = DEFAULT_EP_CACHE_DIR,
    player_ids: Optional[pd.DataFrame] = None,
    player_ids_cache_dir: Union[str, Path] = DEFAULT_PLAYER_IDS_CACHE_DIR,
    stats_cache_dir: Union[str, Path] = DEFAULT_STATS_CACHE_DIR,
    name_fallback: bool = True,
    regular_season_only: bool = True,
) -> pd.DataFrame:
    """Load snap counts and expected points for ``seasons`` as GSIS player-weeks.

    Reads only local caches and never touches the network. A season the
    fetch script cached as unpublished contributes no rows; a season that
    was never fetched raises.

    Args:
        seasons: Seasons to load, e.g. ``range(2016, 2027)``.
        snap_cache_dir: Where ``snap_counts_<season>.csv`` lives.
        ep_cache_dir: Where ``ep_weekly_<season>.csv`` lives.
        player_ids: DynastyProcess's raw crosswalk. ``None`` reads it from
            ``player_ids_cache_dir``.
        player_ids_cache_dir: Where ``db_playerids.csv`` lives.
        stats_cache_dir: Where ``player_stats_<season>.csv`` lives, for the
            name fallback.
        name_fallback: Apply the name/team/position fallback to pfr ids the
            crosswalk misses (default ``True``).
        regular_season_only: Regular season only (default); see the module
            docstring.

    Returns:
        One row per (season, week, gsis_id) present in either source (an
        outer join): :data:`USAGE_IDENTITY_COLUMNS`, then the ``ep_*``
        columns. Snap rows no GSIS id could be found for are dropped.
        ``player_name``/``position`` prefer ffopportunity's nflverse labels
        and fall back to the snap row's PFR labels; ``team`` and ``game_id``
        prefer the snap row. Null means "no source row", never zero. Sorted
        by season, week, gsis_id.

    Raises:
        FileNotFoundError: If a needed cache file (snap counts, expected
            points, the crosswalk, or player stats when ``name_fallback``) has
            never been fetched.
    """
    seasons = sorted({int(season) for season in seasons})

    if player_ids is None:
        player_ids = load_player_ids_cache(player_ids_cache_dir)
        if player_ids is None:
            raise FileNotFoundError(
                f"No cached ID crosswalk under {player_ids_cache_dir}. "
                "Run scripts/fetch_usage_seasons.py first."
            )

    snap_frames, ep_frames, stat_frames = [], [], []
    for season in seasons:
        snap_frames.append(
            _load_required(
                load_snap_counts_cache, season, snap_cache_dir, "snap counts"
            )
        )
        ep_frames.append(
            _load_required(
                load_expected_points_cache, season, ep_cache_dir, "expected points"
            )
        )
        if name_fallback:
            stat_frames.append(
                _load_required(
                    load_player_stats_cache, season, stats_cache_dir, "player stats"
                )
            )

    def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        non_empty = [frame for frame in frames if not frame.empty]
        return pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()

    player_stats = _concat(stat_frames) if name_fallback else None
    if (
        player_stats is not None
        and "season_type" in player_stats.columns
        and regular_season_only
    ):
        player_stats = player_stats[player_stats["season_type"] == "REG"]

    snaps = normalize_snap_counts(
        _concat(snap_frames),
        player_ids,
        player_stats=player_stats,
        regular_season_only=regular_season_only,
    )
    snaps = snaps[snaps["gsis_id"].notna()]
    expected = normalize_expected_points(
        _concat(ep_frames), regular_season_only=regular_season_only
    )

    return _combine_usage(snaps, expected)


def _combine_usage(snaps: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    """Outer-join mapped snap rows and ep rows on (season, week, gsis_id)."""
    key = ["season", "week", "gsis_id"]
    ep_columns = [
        column
        for column in expected.columns
        if column.startswith(EXPECTED_POINTS_PREFIX)
    ]

    snap_side = snaps.copy()
    ep_side = expected.rename(
        columns={
            "game_id": "_ep_game_id",
            "player_name": "_ep_player_name",
            "position": "_ep_position",
            "team": "_ep_team",
        }
    )
    for frame in (snap_side, ep_side):
        frame["season"] = frame["season"].astype(int)
        frame["week"] = frame["week"].astype(int)
        frame["gsis_id"] = frame["gsis_id"].astype(str)

    combined = snap_side.merge(ep_side, on=key, how="outer", validate="one_to_one")

    combined["player_name"] = combined["_ep_player_name"].combine_first(
        combined["player_name"]
    )
    combined["position"] = combined["_ep_position"].combine_first(combined["position"])
    combined["team"] = combined["team"].combine_first(combined["_ep_team"])
    combined["game_id"] = combined["game_id"].combine_first(combined["_ep_game_id"])

    for column in ("offense_snaps", "offense_snap_pct", "team_offense_snaps"):
        combined[column] = combined[column].astype(float)

    combined = combined[USAGE_IDENTITY_COLUMNS + ep_columns]
    combined = combined.sort_values(key)
    return combined.reset_index(drop=True)


def attach_usage(
    player_weeks: pd.DataFrame,
    usage: pd.DataFrame,
    *,
    player_id_column: str = "player_id",
) -> pd.DataFrame:
    """Left-join usage columns onto a scored player-week frame.

    Built for :func:`~fantasy_analyzer.players.ros_backtest.build_scored_player_weeks`'s
    output, whose id column is **always named** ``player_id``: that
    function's own ``player_id_column`` argument selects which *input* column
    to read, not the output name. Called on raw nflverse tables, that input
    must stay the default ``"player_id"`` (a GSIS id); the raw tables have no
    ``gsis_id`` column, so ``player_id_column="gsis_id"`` raises ``KeyError``
    there.

    Args:
        player_weeks: Any frame with ``season``, ``week`` and a GSIS id
            column.
        usage: :func:`load_usage_player_weeks`'s output.
        player_id_column: The GSIS id column in ``player_weeks``. It must hold
            GSIS ids: a Sleeper-keyed frame matches nothing.

    Returns:
        ``player_weeks`` with its rows and order unchanged, plus every usage
        column except the key and the ``player_name``/``position``/``team``
        labels the stat frame already has. A stat row with no usage row gets
        null usage columns, never zero. This only enriches existing stat rows
        and cannot add the zero-usage weeks nflverse stats omit; see the
        module docstring's "row universe" section.

    Raises:
        KeyError: If ``player_weeks`` lacks ``season``, ``week`` or
            ``player_id_column``.
        ValueError: If ``player_weeks`` already has one of the usage columns
            being attached (for instance, attached twice).
    """
    missing = {"season", "week", player_id_column} - set(player_weeks.columns)
    if missing:
        raise KeyError(f"player_weeks is missing column(s): {sorted(missing)}")

    attach_columns = [
        column for column in usage.columns if column not in _ATTACH_EXCLUDED_COLUMNS
    ]
    overlap = sorted(set(attach_columns) & set(player_weeks.columns))
    if overlap:
        raise ValueError(f"player_weeks already has usage column(s): {overlap}")

    right = usage[["season", "week", "gsis_id"] + attach_columns].copy()
    right["season"] = right["season"].astype(int)
    right["week"] = right["week"].astype(int)
    right["gsis_id"] = right["gsis_id"].astype(str)

    left_keys = pd.DataFrame(
        {
            "season": pd.to_numeric(player_weeks["season"]).to_numpy(),
            "week": pd.to_numeric(player_weeks["week"]).to_numpy(),
            "gsis_id": player_weeks[player_id_column]
            .map(lambda value: None if pd.isna(value) else str(value))
            .to_numpy(),
        }
    )
    joined = left_keys.merge(
        right, on=["season", "week", "gsis_id"], how="left", validate="many_to_one"
    )

    result = player_weeks.copy()
    for column in attach_columns:
        result[column] = joined[column].to_numpy()
    return result
