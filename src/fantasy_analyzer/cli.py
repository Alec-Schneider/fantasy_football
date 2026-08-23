"""Command-line interface for inspecting a Sleeper league (FFA-024).

Per AGENTS.md's Epic 3 goal ("allow a simple local command to inspect a 2025
league before any UI exists"), this module is a thin CLI wrapper -- it
performs no normalization or analytics of its own. It composes the existing
``SleeperClient`` (network access), ``load_league_snapshot`` (FFA-013), and
``build_league_summary`` (FFA-023) into two subcommands:

- ``leagues <username> --season <year>`` -- resolve a Sleeper username to its
  leagues for a season (FFA-003), to discover a ``league_id``.
- ``summary <league_id> --total-weeks <n>`` -- print standings and scoring
  summary for a league (FFA-020/FFA-021/FFA-023).

Table formatting (``_format_leagues_table`` / ``_format_league_summary``) and
argument parsing (``build_arg_parser``) are pure functions, independently
testable without live HTTP. ``run_leagues``/``run_summary`` take an injected
``SleeperClient`` so tests can mock HTTP responses via ``requests_mock``
against the same sanitized fixtures used elsewhere in the test suite, per
AGENTS.md's "no live API dependency in unit tests" rule.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

import pandas as pd

from fantasy_analyzer.analytics.summary import LeagueSummaryView, build_league_summary
from fantasy_analyzer.league.snapshot import load_league_snapshot
from fantasy_analyzer.sleeper.client import SleeperClient
from fantasy_analyzer.sleeper.exceptions import SleeperAPIError


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the ``fantasy-analyzer`` argument parser.

    Returns:
        An ``argparse.ArgumentParser`` with two subcommands: ``leagues``
        (resolve a username's leagues for a season) and ``summary`` (print a
        league's standings and scoring summary).
    """
    parser = argparse.ArgumentParser(
        prog="fantasy-analyzer",
        description="Inspect a Sleeper fantasy football league from the command line.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    leagues_parser = subparsers.add_parser(
        "leagues", help="List a Sleeper user's leagues for a season."
    )
    leagues_parser.add_argument("username", help="Sleeper username.")
    leagues_parser.add_argument(
        "--season", type=int, required=True, help="Season year, e.g. 2025."
    )

    summary_parser = subparsers.add_parser(
        "summary", help="Print standings and scoring summary for a league."
    )
    summary_parser.add_argument("league_id", help="Sleeper league_id.")
    summary_parser.add_argument(
        "--total-weeks",
        type=int,
        required=True,
        help="Total weeks in the fantasy season (e.g. 18 for the 2025 NFL season).",
    )

    return parser


def _format_leagues_table(leagues: list[dict]) -> str:
    """Format raw Sleeper league dicts as a plain-text table.

    Args:
        leagues: Raw league dicts, as returned by ``SleeperClient.get_leagues``.

    Returns:
        A ``league_id``/``name``/``status`` table, or a friendly message if
        ``leagues`` is empty.
    """
    if not leagues:
        return "No leagues found."

    rows = [
        {
            "league_id": league.get("league_id"),
            "name": league.get("name"),
            "status": league.get("status"),
        }
        for league in leagues
    ]
    return pd.DataFrame(rows).to_string(index=False)


def _format_league_summary(view: LeagueSummaryView) -> str:
    """Format a ``LeagueSummaryView`` as plain-text sections.

    Args:
        view: The composed view returned by ``LeagueSummary.league_summary()``.

    Returns:
        League header/metadata, followed by the standings and scoring
        summary tables.
    """
    lines = [
        f"{view.name or '(unnamed league)'} -- season {view.season} ({view.status})",
        f"league_id: {view.league_id}",
        "",
        "Standings:",
        view.standings.to_string(index=False),
        "",
        "Scoring summary:",
        view.scoring_summary.to_string(index=False),
    ]
    return "\n".join(lines)


def run_leagues(client: SleeperClient, username: str, season: int) -> str:
    """Resolve ``username`` to its leagues for ``season`` and format as a table."""
    user = client.get_user(username)
    leagues = client.get_leagues(user_id=user["user_id"], season=season)
    return _format_leagues_table(leagues)


def run_summary(client: SleeperClient, league_id: str, total_weeks: int) -> str:
    """Build and format a league summary for ``league_id``."""
    snapshot = load_league_snapshot(client, league_id)
    summary = build_league_summary(snapshot, total_weeks=total_weeks)
    return _format_league_summary(summary.league_summary())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the ``fantasy-analyzer`` console script.

    Args:
        argv: Argument list to parse (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code: ``0`` on success, ``1`` if the Sleeper API call
        failed or the username/league could not be resolved.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    client = SleeperClient()

    try:
        if args.command == "leagues":
            output = run_leagues(client, args.username, args.season)
        else:
            output = run_summary(client, args.league_id, args.total_weeks)
    except (SleeperAPIError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
