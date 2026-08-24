"""nflverse-backed implementation of :class:`PlayerStatsProvider` (FFA-061).

This module normalizes nflverse's raw cumulative weekly player-stats table
(downloaded/cached via ``nflverse_client``/``nflverse_cache``) into the
canonical shape defined by ``fantasy_analyzer.players.provider``, and
exposes :class:`NflverseWeeklyStatsProvider`, a concrete provider that
satisfies :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`
structurally (see that module's docstring for why ``Protocol`` conformance
requires no inheritance).

Column mapping
--------------

nflverse's raw column names (verified against the live
``player_stats.csv.gz`` release asset as of this ticket) map to the
required identity columns as follows:

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
``nfl_team``      ``recent_team``
================  =====================================================

``sleeper_player_id`` is always ``None``
-----------------------------------------

nflverse has no notion of a Sleeper player id; mapping nflverse's
``gsis_id`` back to Sleeper's ``player_id`` is FFA-062's job (the
Sleeper<->nflverse ID crosswalk), out of scope for this ticket. Every row
this provider returns leaves ``sleeper_player_id`` as ``None`` -- exactly
the convention documented in ``provider``'s module docstring.

Additional stat columns
------------------------

Beyond the required identity prefix, this provider passes through a fixed,
documented subset of nflverse's raw per-stat columns (see
:data:`RAW_STAT_COLUMNS`): basic passing/rushing/receiving counting stats
likely to matter for a league's scoring rules. Deliberately excluded:
nflverse's own ``fantasy_points``/``fantasy_points_ppr`` columns (computing
fantasy points from a league's actual scoring settings is FFA-063's job,
not this provider's), and advanced/efficiency metrics (``passing_epa``,
``racr``, ``dakota``, target/air-yards shares, etc.) that are out of scope
for a raw per-stat pass-through.

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

from fantasy_analyzer.players.nflverse_cache import (
    DEFAULT_CACHE_PATH,
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
    "nfl_team": "recent_team",
}

#: Raw nflverse per-stat columns passed through beyond the required identity
#: prefix. See the module docstring's "Additional stat columns" section for
#: what is deliberately excluded and why.
RAW_STAT_COLUMNS = [
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "sacks",
    "sack_fumbles_lost",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "rushing_fumbles_lost",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "receiving_fumbles_lost",
]


def normalize_player_stats(raw: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """Filter and reshape nflverse's raw stats table to one canonical week.

    Args:
        raw: nflverse's raw, unfiltered player-stats table, as returned by
            ``NflverseClient.download_player_stats()`` (or a cached copy of
            it) -- one row per observed player-week across every
            season/week nflverse has published.
        season: The NFL season to filter to.
        week: The NFL week number to filter to.

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
    # No Sleeper<->nflverse crosswalk yet -- see the module docstring.
    result["sleeper_player_id"] = None

    for identity_column, source_column in _IDENTITY_SOURCE_COLUMNS.items():
        result[identity_column] = (
            matched[source_column] if source_column in matched.columns else None
        )

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

    The underlying cumulative table is downloaded/loaded from cache at most
    once per provider instance, on the first ``weekly_stats`` call, and
    reused in memory for every subsequent call on that instance -- callers
    that want a fresh download mid-session should construct a new provider
    (or pass ``force_refresh=True``, which affects only that first load).
    """

    def __init__(
        self,
        client: Optional[NflverseClient] = None,
        cache_path: Union[str, Path] = DEFAULT_CACHE_PATH,
        force_refresh: bool = False,
    ) -> None:
        self._client = client or NflverseClient()
        self._cache_path = cache_path
        self._force_refresh = force_refresh
        self._raw: Optional[pd.DataFrame] = None

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        """Return nflverse's player statistics for ``season``/``week``.

        See ``PlayerStatsProvider.weekly_stats`` for the full return-shape
        contract (identity-column prefix, empty frame for no data, etc.),
        and this module's docstring for nflverse-specific column mapping.
        """
        if self._raw is None:
            self._raw = get_player_stats_cached(
                self._client, self._cache_path, force_refresh=self._force_refresh
            )

        return normalize_player_stats(self._raw, season, week)
