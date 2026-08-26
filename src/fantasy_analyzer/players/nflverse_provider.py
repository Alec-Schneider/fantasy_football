"""nflverse-backed implementation of :class:`PlayerStatsProvider` (FFA-061).

This module normalizes nflverse's raw, per-season weekly player-stats table
(downloaded/cached one season at a time via ``nflverse_client``/
``nflverse_cache``) into the canonical shape defined by
``fantasy_analyzer.players.provider``, and exposes
:class:`NflverseWeeklyStatsProvider`, a concrete provider that satisfies
:class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`
structurally (see that module's docstring for why ``Protocol`` conformance
requires no inheritance).

Column mapping
--------------

nflverse's raw column names (verified against the live
``stats_player_week_<season>.csv.gz`` release asset -- see
``nflverse_client``'s module docstring for the release-tag migration this
reflects) map to the required identity columns as follows:

================  =====================================================
Identity column   nflverse source column
================  =====================================================
``season``        ``season``
``week``          ``week``
``sleeper_player_id``  *(none -- always* ``None``*, see below)*
``gsis_id``       ``player_id`` (nflverse's native GSIS-format player id,
                   e.g. ``"00-0034857"``)
``player_name``   ``player_display_name`` (nflverse also has a separate,
                   abbreviated ``player_name`` column, e.g.
                   ``"J.Allen"`` -- deliberately not used here, since it
                   collides with this interface's own ``player_name``
                   identity column and is less useful as a display name)
``nfl_team``      ``team``
================  =====================================================

.. note::
   ``team`` (formerly ``recent_team``), ``passing_interceptions``
   (formerly ``interceptions``), and ``sacks_suffered`` (formerly
   ``sacks``) reflect the column names as of the current
   ``stats_player_week`` release. The pre-migration ``player_stats``
   release (see ``nflverse_client``'s docstring) used the older names;
   this module targets only the current release, since that is the only
   one ``NflverseClient`` downloads from.

``sleeper_player_id`` requires an optional crosswalk
-------------------------------------------------------

nflverse has no notion of a Sleeper player id. By default (no crosswalk
supplied), every row this provider returns leaves ``sleeper_player_id`` as
``None`` -- exactly the convention documented in ``provider``'s module
docstring.

FFA-062 (``fantasy_analyzer.players.crosswalk``) builds a
``gsis_id -> sleeper_player_id`` mapping from Sleeper's own player catalog
(which carries a native ``gsis_id`` field). Both :func:`normalize_player_stats`
and :class:`NflverseWeeklyStatsProvider` accept an optional ``id_crosswalk``
DataFrame (see :func:`fantasy_analyzer.players.crosswalk.build_id_crosswalk`)
-- when supplied, ``sleeper_player_id`` is populated for every row whose
``gsis_id`` has a match in the crosswalk, and left ``None`` for rows with no
match (an unrecognized ``gsis_id``, or a row with no ``gsis_id`` at all,
e.g. the "Some Rookie" fixture case). Passing no crosswalk (the default)
preserves the original, always-``None`` behavior for callers who have not
yet wired one up.

Additional stat columns
------------------------

Beyond the required identity prefix, this provider passes through a fixed,
documented subset of nflverse's raw per-stat columns (see
:data:`RAW_STAT_COLUMNS`): basic passing/rushing/receiving counting stats,
two-point conversions, and kicking stats (field-goal-distance bands and
extra points) likely to matter for a league's scoring rules. Deliberately
excluded: nflverse's own ``fantasy_points``/``fantasy_points_ppr`` columns
(computing fantasy points from a league's actual scoring settings is
FFA-063's job, not this provider's), and advanced/efficiency metrics
(``passing_epa``, ``racr``, ``dakota``, target/air-yards shares, etc.)
that are out of scope for a raw per-stat pass-through.

The current release also carries individual-level defensive stats
(``def_sacks``, ``def_interceptions``, ``def_tds``, etc.) and points
allowed is not present in this table at all. Neither is passed through
here: a Sleeper ``DEF`` roster slot represents a whole *team* defense, not
an individual player, so scoring it needs these per-player defensive rows
aggregated up to team+game plus a separate points-allowed data source --
out of scope for this provider, which returns one row per rostered
*player*. See ``scoring.py``'s module docstring for how this shows up in
``unsupported_scoring_keys``.

Invalid ``season``/``week``
-----------------------------

Per ``provider``'s documented discretion, this provider does not validate
``season``/``week`` inputs. A ``season``/``week`` combination absent from
nflverse's data (invalid, not yet played, or not yet published) simply
matches no rows and yields an empty DataFrame with the identity columns --
the same as any other "no data" case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pandas as pd

from fantasy_analyzer.players.crosswalk import gsis_to_sleeper_lookup
from fantasy_analyzer.players.nflverse_cache import (
    DEFAULT_CACHE_DIR,
    get_player_stats_cached,
)
from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.provider import PLAYER_WEEK_IDENTITY_COLUMNS

#: nflverse raw identity columns, in the order they map to
#: ``PLAYER_WEEK_IDENTITY_COLUMNS`` (excluding ``season``, ``week``, and
#: ``sleeper_player_id``, which are not sourced from a single raw column --
#: see the module docstring's column-mapping table).
_IDENTITY_SOURCE_COLUMNS = {
    "gsis_id": "player_id",
    "player_name": "player_display_name",
    "position": "position",
    "nfl_team": "team",
}

#: Raw nflverse per-stat columns passed through beyond the required identity
#: prefix. See the module docstring's "Additional stat columns" section for
#: what is deliberately excluded and why.
RAW_STAT_COLUMNS = [
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "sacks_suffered",
    "sack_fumbles_lost",
    "passing_2pt_conversions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "rushing_fumbles_lost",
    "rushing_2pt_conversions",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "receiving_fumbles_lost",
    "receiving_2pt_conversions",
    "fg_made_0_19",
    "fg_made_20_29",
    "fg_made_30_39",
    "fg_made_40_49",
    "fg_made_50_59",
    "fg_made_60_",
    "fg_missed",
    "pat_made",
    "pat_missed",
]


def normalize_player_stats(
    raw: pd.DataFrame,
    season: int,
    week: int,
    id_crosswalk: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Filter and reshape nflverse's raw stats table to one canonical week.

    Args:
        raw: nflverse's raw, unfiltered player-stats table for one season,
            as returned by ``NflverseClient.download_player_stats(season)``
            (or a cached copy of it) -- one row per observed player-week.
            ``season``/``week`` are still explicit filter arguments (not
            inferred from ``raw``) since a caller may pass any DataFrame
            with the right shape, e.g. a multi-season fixture in tests.
        season: The NFL season to filter to.
        week: The NFL week number to filter to.
        id_crosswalk: An optional Sleeper<->nflverse ID crosswalk, as
            returned by
            :func:`fantasy_analyzer.players.crosswalk.build_id_crosswalk`.
            When supplied, ``sleeper_player_id`` is populated for rows whose
            ``gsis_id`` matches a crosswalk entry, and left ``None``
            otherwise. Defaults to ``None``, which preserves the original
            behavior of leaving ``sleeper_player_id`` always ``None`` -- see
            the module docstring.

    Returns:
        A DataFrame whose columns begin with
        :data:`~fantasy_analyzer.players.provider.PLAYER_WEEK_IDENTITY_COLUMNS`,
        followed by :data:`RAW_STAT_COLUMNS` (only those present in
        ``raw``). Empty (same columns, zero rows) if no row in ``raw``
        matches ``season``/``week`` -- including when ``raw`` itself is
        missing the ``season``/``week`` columns entirely, which is treated
        as "no data" rather than an error.
    """
    if "season" in raw.columns and "week" in raw.columns:
        matched = raw[(raw["season"] == season) & (raw["week"] == week)]
    else:
        matched = raw.iloc[0:0]

    result = pd.DataFrame(index=matched.index)
    result["season"] = season
    result["week"] = week
    # Populated below (after gsis_id is assigned) only if id_crosswalk is
    # supplied -- otherwise this stays None, per the module docstring.
    result["sleeper_player_id"] = None

    for identity_column, source_column in _IDENTITY_SOURCE_COLUMNS.items():
        result[identity_column] = (
            matched[source_column] if source_column in matched.columns else None
        )

    if id_crosswalk is not None and not id_crosswalk.empty:
        lookup = gsis_to_sleeper_lookup(id_crosswalk)
        result["sleeper_player_id"] = result["gsis_id"].map(lookup)

    result = result[PLAYER_WEEK_IDENTITY_COLUMNS]

    for stat_column in RAW_STAT_COLUMNS:
        if stat_column in matched.columns:
            result[stat_column] = matched[stat_column]

    return result.reset_index(drop=True)


class NflverseWeeklyStatsProvider:
    """A :class:`PlayerStatsProvider` backed by nflverse's player-stats release.

    Satisfies ``PlayerStatsProvider`` structurally -- no inheritance -- by
    implementing ``weekly_stats(season, week) -> pd.DataFrame``. See the
    module docstring for the column mapping and stat-column choices.

    Each season's table is downloaded/loaded from cache at most once per
    provider instance -- on the first ``weekly_stats`` call for that
    season -- and reused in memory for every subsequent call on that same
    season; a different season triggers its own cache lookup/download the
    first time it is requested. Callers that want a fresh download
    mid-session should construct a new provider (or pass
    ``force_refresh=True``, which affects only each season's first load).
    """

    def __init__(
        self,
        client: Optional[NflverseClient] = None,
        cache_dir: Union[str, Path] = DEFAULT_CACHE_DIR,
        force_refresh: bool = False,
        id_crosswalk: Optional[pd.DataFrame] = None,
    ) -> None:
        self._client = client or NflverseClient()
        self._cache_dir = cache_dir
        self._force_refresh = force_refresh
        self._id_crosswalk = id_crosswalk
        self._raw_by_season: dict[int, pd.DataFrame] = {}

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        """Return nflverse's player statistics for ``season``/``week``.

        See ``PlayerStatsProvider.weekly_stats`` for the full return-shape
        contract (identity-column prefix, empty frame for no data, etc.),
        and this module's docstring for nflverse-specific column mapping.
        ``sleeper_player_id`` is populated only if this provider was
        constructed with an ``id_crosswalk`` -- see the module docstring's
        "``sleeper_player_id`` requires an optional crosswalk" section.
        """
        if season not in self._raw_by_season:
            self._raw_by_season[season] = get_player_stats_cached(
                self._client,
                season,
                self._cache_dir,
                force_refresh=self._force_refresh,
            )

        return normalize_player_stats(
            self._raw_by_season[season], season, week, id_crosswalk=self._id_crosswalk
        )
