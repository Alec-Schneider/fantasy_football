"""Base HTTP client for the Sleeper API.

This module is responsible for raw Sleeper API communication only. It does
not perform any normalization or analytics -- see the ``league``,
``matchups``, and ``analytics`` packages for that.
"""

from __future__ import annotations

from typing import Optional

import requests

from fantasy_analyzer.sleeper.exceptions import (
    SleeperConnectionError,
    SleeperHTTPError,
    SleeperTimeoutError,
)


class SleeperClient:
    """A thin, reusable client around the public Sleeper HTTP API."""

    BASE_URL = "https://api.sleeper.app/v1"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, endpoint: str, params: Optional[dict] = None):
        """Issue a GET request against a Sleeper API endpoint.

        Centralizes URL construction, timeout handling, and HTTP error
        handling for all Sleeper API calls.
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.exceptions.Timeout as exc:
            raise SleeperTimeoutError(
                f"Sleeper API request to '{url}' timed out after {self.timeout}s."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise SleeperConnectionError(
                f"Failed to connect to Sleeper API at '{url}'."
            ) from exc

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise SleeperHTTPError(
                f"Sleeper API request to '{url}' failed with status "
                f"{response.status_code}.",
                status_code=response.status_code,
                response=response,
            ) from exc

        return response.json()

    # -------------------------
    # User
    # -------------------------

    def get_user(self, username_or_id: str) -> dict:
        """Get Sleeper user information."""
        user = self._get(f"user/{username_or_id}")

        if not user:
            raise ValueError(f"Sleeper user '{username_or_id}' was not found.")

        return user

    # -------------------------
    # Leagues
    # -------------------------

    def get_leagues(self, user_id: str, season: int, sport: str = "nfl") -> list[dict]:
        """Get all leagues for a user for a season."""
        return self._get(f"user/{user_id}/leagues/{sport}/{season}")

    def get_league(self, league_id: str) -> dict:
        """Get league settings and metadata."""
        return self._get(f"league/{league_id}")

    def get_rosters(self, league_id: str) -> list[dict]:
        """Get every roster in a league."""
        return self._get(f"league/{league_id}/rosters")

    def get_users(self, league_id: str) -> list[dict]:
        """Get every user/team owner in a league."""
        return self._get(f"league/{league_id}/users")

    # -------------------------
    # Matchups
    # -------------------------

    def get_matchups(self, league_id: str, week: int) -> list[dict]:
        """Get league matchups for a specific week."""
        return self._get(f"league/{league_id}/matchups/{week}")

    # -------------------------
    # Playoff brackets
    # -------------------------

    def get_winners_bracket(self, league_id: str) -> list[dict]:
        """Get the playoff winners bracket for a league."""
        return self._get(f"league/{league_id}/winners_bracket")

    def get_losers_bracket(self, league_id: str) -> list[dict]:
        """Get the playoff losers (consolation) bracket for a league."""
        return self._get(f"league/{league_id}/losers_bracket")

    # -------------------------
    # Transactions
    # -------------------------

    def get_transactions(self, league_id: str, week: int) -> list[dict]:
        """Get league transactions (trades, waivers, free agents) for a week."""
        return self._get(f"league/{league_id}/transactions/{week}")

    # -------------------------
    # Drafts
    # -------------------------

    def get_drafts(self, league_id: str) -> list[dict]:
        """Get all drafts for a league."""
        return self._get(f"league/{league_id}/drafts")

    def get_draft_picks(self, draft_id: str) -> list[dict]:
        """Get every pick made in a draft."""
        return self._get(f"draft/{draft_id}/picks")

    # -------------------------
    # Players
    # -------------------------

    def get_players(
        self, position: Optional[str] = None, active: Optional[bool] = None
    ) -> dict:
        """Get Sleeper's NFL player database.

        This endpoint returns a large response, so it should eventually be
        cached instead of downloaded repeatedly.
        """
        params = {}

        if position:
            params["position"] = position

        if active is not None:
            params["active"] = str(active).lower()

        return self._get("players/nfl", params=params or None)
