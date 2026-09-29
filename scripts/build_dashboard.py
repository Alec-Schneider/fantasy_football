"""Build the season dashboard bundle consumed by the published Artifact page.

One JSON file, every league, every completed week. The Artifact page is
static HTML -- its CSP blocks outbound fetches, so it cannot reach Sleeper
or nflverse itself. Everything the page can ever show therefore has to be
in this bundle at publish time, and "refreshing" the dashboard means
re-running this script and republishing.

What this script is and is not
-------------------------------

It is a **composition** script, not an analytics one. Every number it emits
comes from an already-shipped, already-tested package function; the script's
only jobs are to call them in the right order, slice them per week, and
serialize. Specifically it reuses:

- ``load_league_snapshot`` (FFA-013) and the FFA-030..033 matchup chain, the
  same way ``cli.build_commentary_inputs`` does. It deliberately does *not*
  call ``build_commentary_inputs`` itself: that function also builds the
  player-week fact table, which is the most expensive step in the pipeline
  and which nothing on this page needs.
- ``build_standings_through_week`` (FFA-102) for per-week standings.
  ``build_standings`` cannot be used here -- it reads Sleeper's
  season-cumulative roster counters, so it always describes *now*, which
  would make every past week in the week picker show today's table.
- ``build_power_rankings`` (FFA-056) over the matchup frame truncated to
  ``week <= N``, which that function's own docstring names as the supported
  way to get an "as of week N" snapshot.
- ``league_week_recap_prompt`` (FFA-092) over ``build_league_week_context``
  (FFA-091), now supplied with genuinely historical ``standings_df`` and
  ``previous_standings_df`` thanks to FFA-102.
- The FFA-095..101 waiver pipeline, mirroring the three composition choices
  ``cli.build_free_agent_rankings`` documents as carrying most of the
  board's accuracy (robust crosswalk, league-wide replacement population,
  fitted shrinkage parameters). This script inlines that composition rather
  than calling ``build_free_agent_rankings`` for one reason: it needs the
  intermediate ``scored_weeks`` frame for defense-vs-position and for the
  roster projections, and that function does not return it. The three
  choices are reproduced exactly -- see ``_build_waiver_board``.

Commentary
-----------

This script does **not** call the Anthropic API. ``commentary/client.py``
can (``--generate``), but that needs ``ANTHROPIC_API_KEY`` and bills per
run. Instead this script writes each league-week's ready-to-paste *prompt*
into the bundle and, if a hand- or Claude-written recap exists at
``<out>/commentary/<slug>_week<N>.md``, folds that in as the rendered
commentary. The refresh workflow is "ask Claude in a session", so the
session that runs this script is also the thing that writes those files.

Known upstream defects this script filters around
--------------------------------------------------

Two measured free-agent defects are documented but not yet fixed in
``src/`` (they are tracked as FFA-103/FFA-104 in AGENTS.md):

1. *Teamless players rank.* Sleeper marks unsigned NFL free agents
   ``status: "Active"`` with ``team: None``, and ``DEFAULT_EXCLUDED_STATUSES``
   covers only ``{inactive, retired}``. Half a raw top-50 board can be
   players not on an NFL roster at all.
2. *No-prior players inherit the positional mean.* ``min_prior_games``
   guards a *thin* prior but not an *absent* one, so a player with zero data
   resolves to the positional mean, which sits above replacement -- giving a
   cluster of long-retired names an identical projection and a shared rank.

:data:`WAIVER_QUALITY_FILTER` applies the documented workaround (require an
NFL team, and require either real prior-season volume or snaps this season).
It is a display filter in one place, not a fix; remove it once those tickets
land.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from fantasy_analyzer.analytics.league_analytics import build_league_analytics
from fantasy_analyzer.analytics.power_rankings import build_power_rankings
from fantasy_analyzer.analytics.standings import build_standings_through_week
from fantasy_analyzer.commentary.context import build_league_week_context
from fantasy_analyzer.commentary.prompts import league_week_recap_prompt
from fantasy_analyzer.league.season import derive_season_boundaries
from fantasy_analyzer.league.snapshot import load_league_snapshot
from fantasy_analyzer.matchups.loader import load_season_matchups
from fantasy_analyzer.matchups.outcomes import derive_season_outcomes
from fantasy_analyzer.matchups.pairing import pair_season_matchups
from fantasy_analyzer.matchups.season_matchups import build_season_matchup_df
from fantasy_analyzer.players.crosswalk import build_robust_id_crosswalk
from fantasy_analyzer.players.free_agents import build_free_agent_pool
from fantasy_analyzer.players.nflverse_provider import NflverseWeeklyStatsProvider
from fantasy_analyzer.players.nflverse_schedule_cache import get_games_cached
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient
from fantasy_analyzer.players.opponent_strength import (
    add_matchup_context,
    build_defense_vs_position,
    bye_weeks,
    normalize_schedule,
    normalize_team,
)
from fantasy_analyzer.players.ros_backtest import build_scored_player_weeks
from fantasy_analyzer.players.ros_projection import (
    DEFAULT_N0,
    ShrinkageParameters,
    load_shrinkage_parameters,
)
from fantasy_analyzer.players.roster_fit import (
    build_add_drop_candidates,
    build_roster_projection_frame,
    optimal_lineup,
    starting_slots,
)
from fantasy_analyzer.players.waiver_rankings import (
    build_free_agent_ros_projections,
    build_waiver_wire_rankings,
)
from fantasy_analyzer.sleeper.cache import get_players_cached
from fantasy_analyzer.sleeper.client import SleeperClient

from draft_league_presets import LEAGUES

#: Default season this dashboard covers.
DEFAULT_SEASON = 2026

#: Fantasy weeks in the season, for ``derive_season_boundaries``.
DEFAULT_TOTAL_WEEKS = 18

#: NFL weeks a season's raw stats can occupy. Mirrors ``cli._NFL_SEASON_WEEKS``
#: -- over-fetching future weeks is harmless (a provider returns an empty
#: frame for a week with no data), and cutoff filtering happens downstream.
NFL_SEASON_WEEKS = range(1, 19)

#: Sleeper username whose team is highlighted as "my team".
DEFAULT_USERNAME = "schneidbaby"

#: Positions with no nflverse player-week rows at all, so no projection can
#: exist for them. ``optimal_lineup`` would silently treat such a slot as
#: empty, so both the lineup recommendation and the add/drop search exclude
#: them rather than pretend to rank them.
UNPROJECTABLE_POSITIONS = frozenset({"K", "DEF", "DST"})

#: Sleeper ``injury_status`` values meaning the player cannot be counted on to
#: play the coming week. ``build_add_drop_candidates``/``optimal_lineup``
#: (FFA-100) are projection-only and have no injury awareness -- that module's
#: own known-limitations note names ``bye_week`` as the column to
#: cross-reference and stops there -- so an unfiltered "optimal" lineup will
#: happily start a player who is Out. Measured on a real roster: Alec Pierce
#: (Out) and Rico Dowdle (Out) both placed in the recommended starting eleven.
#:
#: ``Questionable`` is deliberately absent: a questionable player usually
#: plays, so they stay startable and are merely flagged on the page.
UNAVAILABLE_INJURY_STATUSES = frozenset(
    {"Out", "IR", "PUP", "NA", "Doubtful", "Suspended", "DNR", "COV"}
)

#: How many ranked free agents to keep in the bundle per league.
DEFAULT_TOP_FREE_AGENTS = 40

#: How deep to rank before applying :data:`WAIVER_QUALITY_FILTER`. The filter
#: removes a large fraction of the raw board (measured: 31 of a raw top 50 in
#: one league), so the pre-filter cut has to be far deeper than the number of
#: rows actually wanted.
RAW_WAIVER_DEPTH = 600

#: Free agents to feed the add/drop search. ``build_add_drop_candidates``
#: solves one lineup per candidate, so this stays a shortlist by design.
ADD_DROP_CANDIDATES = 40


def _clean(value: Any) -> Any:
    """Coerce a pandas/numpy scalar into something ``json.dumps`` accepts."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _nfl_state(client: SleeperClient) -> Optional[dict]:
    """Fetch Sleeper's ``/state/nfl`` (current week / season phase), if reachable.

    ``SleeperClient`` exposes no typed accessor for this endpoint, so this
    reaches for its private request helper and degrades to ``None`` rather
    than failing the build -- the bundle's ``completed_weeks`` is what the
    page actually keys off; this is only used to label a week as in progress.
    """
    try:
        return client._get("/state/nfl")  # noqa: SLF001 -- no public accessor
    except Exception:  # pragma: no cover -- advisory field only
        return None


def _records(frame: pd.DataFrame, columns: Optional[list[str]] = None) -> list[dict]:
    """Serialize a DataFrame to JSON-safe records, keeping only ``columns``.

    Columns absent from ``frame`` are skipped rather than raising, so an
    optional enrichment step (e.g. ``add_matchup_context``) that did not run
    degrades to fewer fields instead of failing the whole build.
    """
    if frame is None or frame.empty:
        return []
    if columns is not None:
        keep = [column for column in columns if column in frame.columns]
        frame = frame[keep]
    return json.loads(frame.to_json(orient="records"))


def WAIVER_QUALITY_FILTER(board: pd.DataFrame) -> pd.DataFrame:
    """Drop rows the two open free-agent defects would otherwise float to the top.

    Requires an NFL team (defect 1: unsigned players carry ``team: None`` and
    are not excluded by status), and requires either real prior-season volume
    or snaps already this season (defect 2: a player with no data at all
    inherits the positional mean, which sits above replacement). Kickers and
    defenses are dropped too -- nflverse publishes no player-week rows for
    them, so they have no projection to rank on.

    See the module docstring for the ticket references. This is a display
    filter, deliberately in one place, not a fix.
    """
    if board.empty:
        return board

    has_team = board["team"].notna() & (board["team"].astype(str).str.len() > 0)
    prior = pd.to_numeric(board.get("prior_season_games"), errors="coerce").fillna(0)
    current = pd.to_numeric(board.get("games_to_date"), errors="coerce").fillna(0)
    projectable = ~board["position"].isin(UNPROJECTABLE_POSITIONS)

    return board[has_team & projectable & ((prior >= 4) | (current > 0))].reset_index(
        drop=True
    )


def _add_injury_status(frame: pd.DataFrame, catalog: dict) -> pd.DataFrame:
    """Attach Sleeper's ``injury_status``/``injury_body_part`` to a player frame.

    The waiver pipeline's own schema
    (:data:`~fantasy_analyzer.players.waiver_rankings.WAIVER_WIRE_RANKING_COLUMNS`)
    carries no injury field, but a waiver board that silently recommends a
    player who is Out is worse than useless -- and the Sleeper catalog this
    build already holds in memory has it.
    """
    if frame.empty:
        return frame

    result = frame.copy()
    result["injury_status"] = [
        (catalog.get(str(player_id)) or {}).get("injury_status")
        for player_id in result["player_id"]
    ]
    result["injury_body_part"] = [
        (catalog.get(str(player_id)) or {}).get("injury_body_part")
        for player_id in result["player_id"]
    ]
    return result


def _upcoming_matchup(
    client: SleeperClient,
    league_id: str,
    week: int,
    my_roster_id: Optional[int],
    teams_df: pd.DataFrame,
) -> Optional[dict]:
    """Resolve who ``my_roster_id`` faces in ``week``, from Sleeper's raw pairing.

    Uses the raw ``/matchups/<week>`` payload rather than the normalized
    season frame: that frame is built from completed weeks, and this is by
    definition the week that has not been played, so every ``points`` here is
    still ``0.0`` and only the ``matchup_id`` grouping carries information.
    """
    if my_roster_id is None:
        return None

    try:
        raw = client.get_matchups(league_id, week)
    except Exception:  # pragma: no cover -- the page degrades without it
        return None

    mine = next(
        (row for row in raw if row.get("roster_id") == my_roster_id), None
    )
    if mine is None or mine.get("matchup_id") is None:
        return None

    opponent = next(
        (
            row
            for row in raw
            if row.get("matchup_id") == mine.get("matchup_id")
            and row.get("roster_id") != my_roster_id
        ),
        None,
    )
    if opponent is None:
        return {"week": week, "opponent_roster_id": None, "opponent": None}

    labels = teams_df.set_index("roster_id")
    opponent_id = opponent.get("roster_id")
    row = labels.loc[opponent_id] if opponent_id in labels.index else None

    return {
        "week": week,
        "opponent_roster_id": opponent_id,
        "opponent": _clean(row["display_name"]) if row is not None else None,
        "opponent_team_name": _clean(row["team_name"]) if row is not None else None,
    }


def _completed_weeks(season_matchup_df: pd.DataFrame) -> list[int]:
    """Return weeks whose every contested matchup has real scores on both sides.

    Sleeper returns a full slate of rows for a future week with every
    ``points`` at ``0.0``, so presence of a row is not evidence a week was
    played. A week counts as complete only when no contested pairing in it
    is still sitting at zero.
    """
    if season_matchup_df.empty:
        return []

    complete: list[int] = []
    for week, group in season_matchup_df.groupby("week"):
        contested = group[group["roster_2_id"].notna()]
        if contested.empty:
            continue
        points = pd.concat([contested["points_1"], contested["points_2"]])
        if points.notna().all() and points.gt(0).all():
            complete.append(int(week))
    return sorted(complete)


def _league_frames(client: SleeperClient, league_id: str, total_weeks: int):
    """Build a league's snapshot, season matchup frame, and analytics.

    The same normalization chain ``cli.build_commentary_inputs`` uses, minus
    the player-week fact table -- see the module docstring.
    """
    snapshot = load_league_snapshot(client, league_id)
    boundaries = derive_season_boundaries(snapshot.league, total_weeks=total_weeks)
    weeks = load_season_matchups(
        client, league_id, boundaries, season=snapshot.league.season
    )
    outcomes = derive_season_outcomes(pair_season_matchups(weeks))
    season_matchup_df = build_season_matchup_df(outcomes, snapshot.teams_df)
    analytics = build_league_analytics(season_matchup_df, snapshot.teams_df)
    return snapshot, season_matchup_df, analytics


def _week_payload(
    snapshot,
    season_matchup_df: pd.DataFrame,
    analytics,
    week: int,
    commentary_dir: Path,
    slug: str,
) -> dict:
    """Assemble one week's results, standings, power ranking and recap."""
    teams_df = snapshot.teams_df

    results = season_matchup_df[
        (season_matchup_df["week"] == week) & season_matchup_df["roster_2_id"].notna()
    ]

    standings = build_standings_through_week(season_matchup_df, teams_df, week)
    # Week 1 has no meaningful "previous" table: before a ball is snapped
    # every team is 0-0 and therefore tied at rank 1, which would render as
    # every manager but one "falling" up to eleven places. None leaves
    # rank_change null, which is the truth.
    previous_standings = (
        build_standings_through_week(season_matchup_df, teams_df, week - 1)
        if week > 1
        else None
    )

    # "As of week N" power ranking: the matchup frame truncated to weeks <= N
    # and to regular-season play, exactly as build_power_rankings' docstring
    # prescribes.
    through_week = season_matchup_df[
        (season_matchup_df["week"] <= week)
        & (~season_matchup_df["is_playoff"].fillna(False).astype(bool))
    ]
    power = build_power_rankings(through_week, teams_df)

    context = build_league_week_context(
        snapshot,
        analytics,
        standings,
        week,
        previous_standings_df=previous_standings,
    )
    prompt = league_week_recap_prompt(context)

    recap_path = commentary_dir / f"{slug}_week{week}.md"
    commentary = recap_path.read_text().strip() if recap_path.exists() else None

    return {
        "week": week,
        "results": _records(
            results,
            [
                "matchup_id",
                "roster_1_id",
                "roster_2_id",
                "owner_1",
                "owner_2",
                "points_1",
                "points_2",
                "winner",
                "loser",
                "is_tie",
                "margin",
            ],
        ),
        "standings": _records(standings),
        "power_rankings": _records(power),
        "commentary": commentary,
        "commentary_prompt": prompt,
    }


def _build_waiver_board(
    snapshot,
    raw_rosters: list[dict],
    catalog: dict,
    crosswalk: pd.DataFrame,
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    upcoming_week: int,
    parameters: ShrinkageParameters,
    schedule: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank free agents, and return ``(board, league_population_projections)``.

    Mirrors ``cli.build_free_agent_rankings``'s three accuracy-critical
    composition choices (robust crosswalk, league-wide replacement
    population, fitted shrinkage parameters), then layers FFA-099's
    opponent/defense-vs-position context on top. The league-wide projection
    frame is returned alongside the board because the lineup recommendation
    needs projections for *rostered* players, who by definition never appear
    on a waiver board.
    """
    roster_positions = snapshot.roster_positions

    free_agent_pool = build_free_agent_pool(
        raw_rosters, catalog, roster_positions, crosswalk=crosswalk
    )
    # No rosters => every startable-position player in the catalog. This is
    # the population replacement level must be measured over (FFA-095), and
    # also the only frame that carries projections for rostered players.
    league_population = build_free_agent_pool(
        [], catalog, roster_positions, crosswalk=crosswalk
    )

    board = build_waiver_wire_rankings(
        free_agent_pool,
        scored_weeks,
        season,
        cutoff_week,
        roster_positions,
        snapshot.league.total_rosters,
        parameters,
        replacement_population=league_population,
    ).head(RAW_WAIVER_DEPTH)

    board = WAIVER_QUALITY_FILTER(board)

    # Re-rank after filtering. The raw ``waiver_rank`` is computed over the
    # unfiltered board, so once WAIVER_QUALITY_FILTER removes the teamless
    # and no-prior rows it leaves gaps (1, 2, 6, 7, 9...) that read as
    # missing players rather than as removed noise. Keep both: ``board_rank``
    # is what the page shows, ``waiver_rank`` stays as the underlying
    # pipeline's own output.
    board = board.reset_index(drop=True)
    board.insert(0, "board_rank", range(1, len(board) + 1))

    if not board.empty and not schedule.empty:
        defense_vs_position = build_defense_vs_position(
            scored_weeks, season, through_week=cutoff_week
        )
        # ``add_matchup_context`` takes the *cutoff* week and builds context
        # for ``week + 1`` itself -- passing ``upcoming_week`` here would
        # describe the week after the one being planned for.
        board = add_matchup_context(
            board,
            schedule,
            defense_vs_position,
            week=cutoff_week,
            season_end_week=DEFAULT_TOTAL_WEEKS,
        )

    board = _add_injury_status(board, catalog)

    population_projections = build_free_agent_ros_projections(
        league_population, scored_weeks, season, cutoff_week, parameters
    )

    return board, population_projections


def _build_lineup(
    snapshot,
    my_roster: dict,
    population_projections: pd.DataFrame,
    board: pd.DataFrame,
    catalog: dict,
    byes: dict,
    upcoming_week: int,
) -> dict:
    """Recommend a starting lineup and the best add/drop moves for one roster.

    Kickers and defenses are excluded from both the slot list and the
    candidate pool: nflverse publishes no player-week rows for them, so they
    have no projection, and ``optimal_lineup`` would read an unprojectable
    player as an empty slot and understate the lineup total.
    """
    player_ids = [str(pid) for pid in (my_roster.get("players") or [])]
    starters_now = [str(pid) for pid in (my_roster.get("starters") or [])]

    roster_frame = build_roster_projection_frame(
        player_ids, population_projections, id_column="player_id"
    )
    if not roster_frame.empty:
        roster_frame = roster_frame[
            ~roster_frame["position"].isin(UNPROJECTABLE_POSITIONS)
        ].reset_index(drop=True)

    lineup_slots = [
        slot
        for slot in snapshot.roster_positions
        if slot not in UNPROJECTABLE_POSITIONS
    ]

    slot_labels = starting_slots(lineup_slots)

    if roster_frame.empty:
        return {
            "projected_slots": slot_labels,
            "recommended_starters": [],
            "bench": [],
            "unavailable": [],
            "projected_points": None,
            "add_drop": [],
            "excluded_positions": sorted(UNPROJECTABLE_POSITIONS),
        }

    roster_frame = _add_injury_status(roster_frame, catalog)
    roster_frame["bye_week"] = [
        byes.get(normalize_team(team)) for team in roster_frame["team"]
    ]
    roster_frame["on_bye"] = roster_frame["bye_week"] == upcoming_week
    roster_frame["unavailable"] = (
        roster_frame["injury_status"].isin(UNAVAILABLE_INJURY_STATUSES)
        | roster_frame["on_bye"]
    )

    # Solve the lineup over available players only. Feeding the whole roster
    # in would start an Out player or one on a bye -- see
    # UNAVAILABLE_INJURY_STATUSES.
    available = roster_frame[~roster_frame["unavailable"]].reset_index(drop=True)
    solution = optimal_lineup(available, lineup_slots)
    recommended = set(solution.starters)

    roster_frame = roster_frame.assign(
        recommended_start=roster_frame["player_id"].isin(recommended),
        currently_starting=roster_frame["player_id"].isin(starters_now),
    )
    roster_frame = roster_frame.sort_values(
        by=["recommended_start", "projected_ppg"], ascending=[False, False]
    ).reset_index(drop=True)

    roster_columns = [
        "player_id",
        "full_name",
        "position",
        "team",
        "injury_status",
        "injury_body_part",
        "bye_week",
        "on_bye",
        "unavailable",
        "projected_ppg",
        "games_to_date",
        "ppg_to_date",
        "confidence_tier",
        "recommended_start",
        "currently_starting",
    ]

    # Add/drop is a "what should I do right now" question, so an unavailable
    # candidate cannot answer it -- an Out player adds nothing to this week's
    # lineup. They stay on the free-agent board (flagged), where the question
    # is rest-of-season value rather than this week's start.
    candidates = board
    if not candidates.empty and "injury_status" in candidates.columns:
        candidates = candidates[
            ~candidates["injury_status"].isin(UNAVAILABLE_INJURY_STATUSES)
        ]
    if not candidates.empty:
        candidates = candidates.sort_values(
            by="projected_ppg", ascending=False
        ).head(ADD_DROP_CANDIDATES)

    add_drop = pd.DataFrame()
    if not candidates.empty:
        add_drop = build_add_drop_candidates(
            available, candidates, lineup_slots, max_candidates=ADD_DROP_CANDIDATES
        )

    startable = roster_frame[~roster_frame["unavailable"]]

    return {
        "projected_slots": slot_labels,
        "recommended_starters": _records(
            startable[startable["recommended_start"]], roster_columns
        ),
        "bench": _records(
            startable[~startable["recommended_start"]], roster_columns
        ),
        "unavailable": _records(
            roster_frame[roster_frame["unavailable"]], roster_columns
        ),
        "projected_points": _clean(solution.points_per_game),
        "add_drop": _records(add_drop),
        "excluded_positions": sorted(UNPROJECTABLE_POSITIONS),
    }


def build_bundle(
    season: int,
    total_weeks: int,
    username: str,
    out_dir: Path,
    top_free_agents: int,
    league_slugs: list[str],
) -> dict:
    """Build the whole dashboard bundle for every requested league."""
    client = SleeperClient()
    catalog = get_players_cached(client)
    crosswalk = build_robust_id_crosswalk(catalog)
    provider = NflverseWeeklyStatsProvider(id_crosswalk=crosswalk)
    parameters = load_shrinkage_parameters() or ShrinkageParameters(
        n0_by_position={}, default_n0=DEFAULT_N0
    )

    user = client.get_user(username)
    nfl_state = _nfl_state(client)

    # Raw weekly stats are season-wide and league-independent, so fetch each
    # season once and re-score per league (scoring settings differ: half-PPR
    # vs full PPR).
    def _raw(target_season: int) -> pd.DataFrame:
        frames = [
            provider.weekly_stats(target_season, week) for week in NFL_SEASON_WEEKS
        ]
        frames = [frame for frame in frames if not frame.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    current_raw = _raw(season)
    prior_raw = _raw(season - 1)

    games = get_games_cached(NflverseScheduleClient())
    schedule = normalize_schedule(games, season) if games is not None else pd.DataFrame()
    byes = bye_weeks(schedule, DEFAULT_TOTAL_WEEKS) if not schedule.empty else {}

    commentary_dir = out_dir / "commentary"
    commentary_dir.mkdir(parents=True, exist_ok=True)

    leagues: list[dict] = []
    for slug in league_slugs:
        preset = LEAGUES[slug]
        league_id = preset["league_id"]
        print(f"[{slug}] league {league_id}", flush=True)

        snapshot, season_matchup_df, analytics = _league_frames(
            client, league_id, total_weeks
        )
        completed = _completed_weeks(season_matchup_df)
        upcoming = (max(completed) + 1) if completed else 1
        cutoff = max(completed) if completed else 0
        print(f"[{slug}]   completed weeks {completed}, upcoming {upcoming}", flush=True)

        weeks_payload = [
            _week_payload(
                snapshot, season_matchup_df, analytics, week, commentary_dir, slug
            )
            for week in completed
        ]

        raw_rosters = client.get_rosters(league_id)
        my_roster = next(
            (r for r in raw_rosters if r.get("owner_id") == user["user_id"]), None
        )

        # Who the highlighted team plays in the week being planned for. Sleeper
        # publishes the pairing well before the week is played (with every
        # ``points`` at 0.0), so this is available even though ``upcoming`` is
        # by definition not in ``completed_weeks``.
        upcoming_matchup = _upcoming_matchup(
            client,
            league_id,
            upcoming,
            my_roster.get("roster_id") if my_roster else None,
            snapshot.teams_df,
        )

        scored_weeks = build_scored_player_weeks(
            [current_raw, prior_raw],
            snapshot.scoring_settings,
            player_id_column="gsis_id",
        )

        print(f"[{slug}]   ranking free agents (cutoff week {cutoff})", flush=True)
        board, population_projections = _build_waiver_board(
            snapshot,
            raw_rosters,
            catalog,
            crosswalk,
            scored_weeks,
            season,
            cutoff,
            upcoming,
            parameters,
            schedule,
        )

        lineup = (
            _build_lineup(
                snapshot,
                my_roster,
                population_projections,
                board,
                catalog,
                byes,
                upcoming,
            )
            if my_roster
            else None
        )

        board_columns = [
            "board_rank",
            "waiver_rank",
            "player_id",
            "full_name",
            "position",
            "team",
            "injury_status",
            "injury_body_part",
            "projected_ppg",
            "matchup_adjusted_ppg",
            "points_above_replacement",
            "ppg_above_replacement",
            "games_to_date",
            "ppg_to_date",
            "last3_ppg",
            "prior_season_ppg",
            "prior_season_games",
            "confidence_tier",
            "targets_per_game",
            "carries_per_game",
            "target_share",
            "wopr",
            "week_opponent",
            "week_is_home",
            "week_dvp_multiplier",
            "bye_week",
            "remaining_schedule_multiplier",
            "remaining_games_scheduled",
            "schedule_adjusted_ros_points",
        ]

        leagues.append(
            {
                "slug": slug,
                "name": snapshot.league.name,
                "short_name": preset["short_title"],
                "league_id": league_id,
                "scoring_label": preset["scoring_label"],
                "total_rosters": snapshot.league.total_rosters,
                "roster_positions": snapshot.roster_positions,
                "my_roster_id": my_roster.get("roster_id") if my_roster else None,
                "completed_weeks": completed,
                "upcoming_week": upcoming,
                "upcoming_matchup": upcoming_matchup,
                "teams": _records(
                    snapshot.teams_df,
                    ["roster_id", "owner_id", "display_name", "team_name"],
                ),
                "weeks": weeks_payload,
                "free_agents": {
                    "cutoff_week": cutoff,
                    "for_week": upcoming,
                    "rows": _records(board.head(top_free_agents), board_columns),
                },
                "lineup": lineup,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season,
        "username": username,
        "user_id": user["user_id"],
        "nfl_state": nfl_state,
        "leagues": leagues,
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Build the dashboard bundle and write it to disk."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--season", type=int, default=DEFAULT_SEASON)
    parser.add_argument("--total-weeks", type=int, default=DEFAULT_TOTAL_WEEKS)
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument(
        "--out-dir", type=Path, default=Path("scripts/output/dashboard")
    )
    parser.add_argument("--top-free-agents", type=int, default=DEFAULT_TOP_FREE_AGENTS)
    parser.add_argument(
        "--leagues",
        nargs="*",
        default=list(LEAGUES),
        help="League slugs to include (default: every preset league).",
    )
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle(
        season=args.season,
        total_weeks=args.total_weeks,
        username=args.username,
        out_dir=args.out_dir,
        top_free_agents=args.top_free_agents,
        league_slugs=list(args.leagues),
    )

    bundle_path = args.out_dir / "bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2))
    size_kb = bundle_path.stat().st_size / 1024
    print(f"\nwrote {bundle_path} ({size_kb:.0f} KB)")

    for league in bundle["leagues"]:
        missing = [
            week["week"] for week in league["weeks"] if not week.get("commentary")
        ]
        if missing:
            print(
                f"  {league['slug']}: no commentary yet for weeks {missing} "
                f"-- write {args.out_dir}/commentary/{league['slug']}_week<N>.md"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
