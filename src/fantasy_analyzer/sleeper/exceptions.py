"""Exceptions raised by the Sleeper API client."""

from __future__ import annotations

import requests


class SleeperAPIError(Exception):
    """Base exception for errors raised by :class:`SleeperClient`."""


class SleeperHTTPError(SleeperAPIError):
    """A Sleeper API request failed with a 4xx or 5xx HTTP status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: requests.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class SleeperTimeoutError(SleeperAPIError):
    """A Sleeper API request timed out."""


class SleeperConnectionError(SleeperAPIError):
    """A Sleeper API request failed to connect."""
