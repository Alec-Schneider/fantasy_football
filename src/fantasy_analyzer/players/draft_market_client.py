"""Thin HTTP clients for downloading forward-looking 2026 draft-market data.

FFA-075 needs two new, independent third-party sources on top of the
DynastyProcess ID crosswalk this codebase already downloads
(``id_crosswalk_client.py``, reused as-is here -- see
``draft_market.py``'s module docstring for why a *second* downloader for
that same asset would be wrong):

- **FantasyFootballCalculator (FFC)**'s public ADP API -- crowd-sourced
  average draft position, one JSON GET per (season, league size, scoring
  format).
- **DynastyProcess's** ``db_fpecr_latest.csv`` -- a scrape of FantasyPros'
  expert-consensus-rank (ECR) pages, republished by the same DynastyProcess
  GitHub repository ``id_crosswalk_client.py`` already depends on. This is
  a *second, distinct* CSV asset from that repository (not
  ``db_playerids.csv``), so it gets its own client class here rather than
  being bolted onto
  :class:`~fantasy_analyzer.players.id_crosswalk_client.PlayerIdCrosswalkClient`,
  which owns exactly one asset per this codebase's existing one-client-per-
  asset convention (``NflverseClient``, ``NflverseScheduleClient``,
  ``PlayerIdCrosswalkClient``).

Both clients follow ``id_crosswalk_client.py``/``nflverse_client.py``'s
established shape: a thin wrapper around one ``requests.Session.get`` call,
a 404 treated as "no data" (returns an empty ``DataFrame`` rather than
raising), and any other non-2xx response left to raise via
``response.raise_for_status()``. Neither client filters, renames, or
otherwise interprets the payload -- that is ``draft_market.py``'s job, kept
separate from network access per AGENTS.md's "Keep API/network code
isolated from calculations."
"""

from __future__ import annotations

import io

import pandas as pd
import requests


class FfcAdpClient:
    """A thin, reusable client around FantasyFootballCalculator's public ADP API."""

    #: One JSON GET per (scoring format, league size, season). FFC's API
    #: path segment is the scoring format itself (``half-ppr``, ``ppr``,
    #: ``standard``, ...); league size and season are query parameters.
    ADP_URL_TEMPLATE = "https://fantasyfootballcalculator.com/api/v1/adp/{scoring}"

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()

    def download_adp(
        self, season: int, teams: int = 12, scoring: str = "half-ppr"
    ) -> pd.DataFrame:
        """Download FFC's consensus ADP table for one season/format/league size.

        Args:
            season: The draft season, e.g. ``2026``.
            teams: League size FFC should compute ADP for. Defaults to
                ``12``, matching this project's primary development league
                (see AGENTS.md) -- ADP is a function of league size (a
                12-team league's "average draft position" is meaningfully
                different from a 10- or 14-team one's), so this is a real
                parameter, not a cosmetic one.
            scoring: FFC's scoring-format path segment, e.g.
                ``"half-ppr"``, ``"ppr"``, ``"standard"``. Defaults to
                ``"half-ppr"``.

        Returns:
            A DataFrame built directly from the response JSON's
            ``"players"`` array, with FFC's own raw field names (``name``,
            ``position``, ``team``, ``adp``, ``adp_formatted``,
            ``times_drafted``, ``high``, ``low``, ``stdev``, ``bye``,
            ``player_id``) -- no filtering, renaming, or column subsetting
            is applied here; see ``draft_market.py`` for that. An empty
            ``DataFrame`` (no columns) if FFC has no data for this request
            (a 404), or if the response's ``"players"`` array is empty --
            both are "no data yet", not an error.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx/non-404 HTTP response, exactly as
                raised by ``requests``.
        """
        url = self.ADP_URL_TEMPLATE.format(scoring=scoring)
        params = {"teams": teams, "year": season, "position": "all"}
        response = self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        payload = response.json()
        return pd.DataFrame(payload.get("players", []))


class FantasyProsEcrClient:
    """A thin, reusable client around DynastyProcess's FantasyPros-ECR export.

    See the module docstring for why this is a separate client from
    :class:`~fantasy_analyzer.players.id_crosswalk_client.PlayerIdCrosswalkClient`
    despite sharing a GitHub repository.
    """

    #: A single cumulative CSV covering every FantasyPros ranking page
    #: DynastyProcess scrapes (overall and per-position, redraft and
    #: dynasty, "best ball" variants, IDP, ...), distinguished by its own
    #: ``page_type`` column -- there is no per-page-type asset to download
    #: separately. See ``draft_market.py``'s ``FANTASYPROS_OVERALL_PAGE_TYPE``
    #: / ``FANTASYPROS_POSITION_PAGE_TYPES`` for the ``page_type`` values
    #: this codebase filters to.
    FPECR_URL = (
        "https://raw.githubusercontent.com/dynastyprocess/data/master/"
        "files/db_fpecr_latest.csv"
    )

    def __init__(self, timeout: int = 60):
        self.timeout = timeout
        self.session = requests.Session()

    def download_ecr(self) -> pd.DataFrame:
        """Download DynastyProcess's full FantasyPros expert-consensus-rank export.

        Returns every ``page_type`` DynastyProcess tracks in one table,
        with its own raw column names (``page_type``, ``player``, ``id``,
        ``pos``, ``team``, ``ecr``, ``sd``, ``best``, ``worst``, ``bye``,
        ``scrape_date``, ...) -- no filtering or renaming is applied here;
        see ``draft_market.py`` for that. This is a multi-thousand-row,
        multi-megabyte download; callers should prefer a disk-caching layer
        (``draft_market_cache.py``) rather than calling this repeatedly.

        Returns:
            An empty ``DataFrame`` (no columns) if the asset is unreachable
            via a 404 -- treated as "no data available", not an error,
            matching ``PlayerIdCrosswalkClient.download_player_ids``'s
            convention for the sibling asset in the same repository. Any
            other non-2xx response still raises.

        Raises:
            requests.exceptions.RequestException: On any connection,
                timeout, or non-2xx/non-404 HTTP response, exactly as
                raised by ``requests``.
        """
        response = self.session.get(self.FPECR_URL, timeout=self.timeout)
        if response.status_code == 404:
            return pd.DataFrame()
        response.raise_for_status()
        return pd.read_csv(io.BytesIO(response.content), low_memory=False)
