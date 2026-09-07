"""Normalize Sleeper draft picks into a stable, join-only DataFrame.

This module joins the raw ``get_drafts()`` / ``get_draft_picks()`` responses
from :class:`fantasy_analyzer.sleeper.client.SleeperClient` onto the team
mapping produced by :func:`fantasy_analyzer.league.teams.build_team_mapping`
(itself joined on the immutable ``roster_id``), so downstream code never
needs to re-derive who picked whom from raw Sleeper draft-pick dicts. It
performs no network access -- callers are responsible for fetching the raw
draft and pick data first (see :func:`load_league_draft` for a thin
fetching wrapper).
"""

from __future__ import annotations

import pandas as pd

from fantasy_analyzer.sleeper.client import SleeperClient

#: Column order for the DataFrame returned by :func:`build_normalized_draft_picks`.
NORMALIZED_DRAFT_PICK_COLUMNS = [
    "season",
    "league_id",
    "draft_id",
    "round",
    "pick_no",
    "draft_slot",
    "roster_id",
    "owner_id",
    "team_name",
    "sleeper_player_id",
    "player_name",
    "position",
    "nfl_team",
    "is_keeper",
]


def load_league_draft(client: SleeperClient, league_id: str) -> tuple[dict, list[dict]]:
    """Fetch a league's raw draft and its raw picks in one call.

    Resolves ``draft_id`` from ``SleeperClient.get_league(league_id)``,
    finds the matching draft object in ``SleeperClient.get_drafts(league_id)``
    (which returns a list of drafts), and fetches its picks via
    ``SleeperClient.get_draft_picks(draft_id)``. Performs live network
    access -- prefer :func:`build_normalized_draft_picks` directly when the
    raw data has already been fetched or when testing without network
    access.

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league ID whose draft should be fetched.

    Returns:
        A ``(raw_draft, raw_picks)`` tuple: the raw draft dict as returned
        by ``get_drafts()`` for this league's ``draft_id``, and the raw list
        of pick dicts as returned by ``get_draft_picks()``.

    Raises:
        ValueError: If the league has no associated ``draft_id``, or if no
            draft in ``get_drafts(league_id)`` matches that ``draft_id``.
    """
    league = client.get_league(league_id)
    draft_id = league.get("draft_id")

    if not draft_id:
        raise ValueError(f"League '{league_id}' has no associated draft_id.")

    drafts = client.get_drafts(league_id)
    raw_draft = next(
        (draft for draft in drafts if draft.get("draft_id") == draft_id), None
    )

    if raw_draft is None:
        raise ValueError(
            f"No draft with draft_id '{draft_id}' found in league '{league_id}'."
        )

    raw_picks = client.get_draft_picks(draft_id)

    return raw_draft, raw_picks


def build_normalized_draft_picks(
    raw_picks: list[dict],
    teams_df: pd.DataFrame,
    *,
    season: int,
    league_id: str,
    draft_id: str,
) -> pd.DataFrame:
    """Normalize raw Sleeper draft picks into a stable, per-pick DataFrame.

    Joins each pick's ``roster_id`` onto ``teams_df`` (the output of
    :func:`fantasy_analyzer.league.teams.build_team_mapping`) to attach
    ``owner_id`` and ``team_name``. Performs no network access.

    Args:
        raw_picks: Raw pick dicts as returned by
            ``SleeperClient.get_draft_picks(draft_id)``. Each is expected to
            have ``round``, ``pick_no``, ``draft_slot``, ``roster_id``,
            ``player_id``, ``is_keeper``, and an optional ``metadata`` dict
            carrying ``first_name``, ``last_name``, ``position``, ``team``.
        teams_df: The roster-to-owner mapping produced by
            ``build_team_mapping()``, with columns ``["roster_id",
            "owner_id", "display_name", "team_name"]``.
        season: The season year to stamp onto every row.
        league_id: The Sleeper league ID to stamp onto every row.
        draft_id: The Sleeper draft ID to stamp onto every row.

    Returns:
        A DataFrame with one row per pick and columns
        :data:`NORMALIZED_DRAFT_PICK_COLUMNS`. ``sleeper_player_id`` is
        coerced to ``str`` to match this codebase's join-key convention
        (see ``players/draft_board.py``). ``is_keeper`` is preserved as-is
        (``None``/``True``/``False``) rather than coerced to ``False``, so
        callers can distinguish "not a keeper league" from "not flagged as
        a keeper."

    Raises:
        ValueError: If a pick's ``roster_id`` has no matching row in
            ``teams_df`` -- silently dropping a team's picks would corrupt
            downstream draft-value analysis.
    """
    roster_lookup = teams_df.set_index("roster_id")[["owner_id", "team_name"]].to_dict(
        orient="index"
    )

    rows = []
    for pick in raw_picks:
        roster_id = pick.get("roster_id")
        team = roster_lookup.get(roster_id)

        if team is None:
            raise ValueError(
                f"Draft pick references roster_id {roster_id!r}, which has no "
                "matching row in teams_df."
            )

        metadata = pick.get("metadata") or {}
        first_name = metadata.get("first_name")
        last_name = metadata.get("last_name")
        player_name = (
            f"{first_name} {last_name}".strip() if first_name or last_name else None
        )

        player_id = pick.get("player_id")

        rows.append(
            {
                "season": season,
                "league_id": league_id,
                "draft_id": draft_id,
                "round": pick.get("round"),
                "pick_no": pick.get("pick_no"),
                "draft_slot": pick.get("draft_slot"),
                "roster_id": roster_id,
                "owner_id": team["owner_id"],
                "team_name": team["team_name"],
                "sleeper_player_id": str(player_id) if player_id is not None else None,
                "player_name": player_name,
                "position": metadata.get("position"),
                "nfl_team": metadata.get("team"),
                "is_keeper": pick.get("is_keeper"),
            }
        )

    return pd.DataFrame(rows, columns=NORMALIZED_DRAFT_PICK_COLUMNS)
