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
- The FFA-095..101 waiver pipeline, mirroring the four composition choices
  ``cli.build_free_agent_rankings`` documents as carrying most of the
  board's accuracy (robust crosswalk, league-wide replacement population,
  fitted shrinkage parameters, the FFA-111 usage model). This script inlines
  that composition rather than calling ``build_free_agent_rankings`` for one
  reason: it needs the intermediate ``scored_weeks`` frame for
  defense-vs-position and for the roster projections, and that function
  does not return it. The four choices are reproduced exactly -- see
  ``_build_waiver_board``. The
  crosswalk is additionally extended with verified name matches
  (``extend_crosswalk_with_name_matches``) once the season's stats are
  loaded, which recovers players the ID sources miss.

The player universe and the two projection models
--------------------------------------------------

Everything is valued over one population: ``build_player_universe``
(FFA-109) -- every rostered player whatever his status (so an Inactive
player in an IR slot is still on his manager's roster) plus every free
agent the package's pool rules admit. That universe is the replacement
population, the set the projections are built for, and the set the
full-universe valuation CSV covers.

Two models project it, and each position is projected by exactly one:

- ``QB``/``RB``/``WR``/``TE`` -- the waiver pipeline's skill-player model:
  the per-position blend of the opportunity-first usage model and the EB
  projection (FFA-111), with the fitted absent-prior line for a player with
  no games and no trusted prior (FFA-104). See "The skill-player model"
  below and ``docs/valuation-model.md``.
- ``K``/``DEF`` -- ``build_kicker_defense_projections`` (FFA-112), never the
  skill model. Its rest-of-season ``projected_ppg`` feeds the waiver board,
  the VORP and the moves; its market-adjusted ``week_projected_points``
  feeds the coming week's lineup call.

VORP for every position comes from the same
``player_value.build_player_value_metrics`` the skill board uses, over the
whole universe, so a kicker's replacement level is the league's last
starting kicker (one per team) and cross-position ranks share one basis.

Commentary
-----------

This script does **not** call the Anthropic API. ``commentary/client.py``
can (``--generate``), but that needs ``ANTHROPIC_API_KEY`` and bills per
run. Instead this script writes each league-week's ready-to-paste *prompt*
into the bundle and, if a hand- or Claude-written recap exists at
``<out>/commentary/<slug>_week<N>.md``, folds that in as the rendered
commentary. The refresh workflow is "ask Claude in a session", so the
session that runs this script is also the thing that writes those files.

The skill-player model
----------------------

The board and the universe projections (which the lineup call and the
valuation read) are built with the same three inputs, so a free agent's
projection on the board equals his row in the valuation:

- ``usage_parameters`` -- the fitted usage model
  (``load_usage_model_parameters``, ``.cache/nflverse``), refit by
  ``scripts/fit_usage_model.py``;
- ``scoring_settings`` -- the league's own, so the projected stat line and
  the absent-prior line are scored the way the league scores;
- ``usage`` -- snap counts and expected points for the season and the one
  before (``load_usage_player_weeks``).

A missing parameter file falls back to the EB projection alone, and a
missing snap/xFP cache to the separately fitted no-snap usage model; the
build prints which it used. Neither is silent, because both measurably
lose accuracy.

No display filter sits on top. The skill board used to drop players with
fewer than 4 prior-season games and no games this season, because FFA-104's
old fallback gave such a player the positional mean. The absent-prior line
replaces that fallback: on the week-4 boards (2026-09-30) the best-ranked
player that filter would have removed is 136th of 577 skill free agents in
NWC (180th once K/DEF are merged), 167th in New Wave and 140th in Zipline --
far below the 40 rows the page shows. (FFA-103, teamless free agents, is
fixed in the package: the free-agent half of the universe requires an NFL
team.)

Full-universe valuation
-----------------------

Besides the bundle, each league gets ``<out>/valuations/<slug>_week<N>.csv``
(``N`` = the week about to be played): every universe player with his
projection, VORP, overall and positional rank, rostered state, owner,
injury and bye. It is the complete "who is worth what" table the page only
samples, and is not rendered on the page.

When is a week final? (FFA-108)
--------------------------------

A week is published as complete only when *both* Sleeper and the NFL agree
it is over: every contested fantasy pairing has non-zero points on both
sides, **and** every NFL game scheduled that week has a final score in the
nflverse schedule cache (``completed_nfl_weeks``). The first test alone let
a week missing only its Monday night game through on 2026-09-21 -- every
fantasy team already had *some* points -- and published two wrong winners.

Availability (FFA-107)
-----------------------

Who can play, and for how long, is the package's
:mod:`fantasy_analyzer.players.availability` rule, not a local filter. The
lineup call is solved for the coming week with Out/IR/bye players excluded;
the add/drop search is scored over the rest of the fantasy regular season
with each player's per-week availability, so a player who is merely Out or
on bye *this* week is never offered as a free drop. IR-slot (``reserve``)
players are never proposed as drops -- they hold no bench spot.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
from draft_league_presets import LEAGUES

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
from fantasy_analyzer.players.availability import (
    LONG_TERM_INJURY_STATUSES,
    add_availability,
    normalize_injury_status,
)
from fantasy_analyzer.players.crosswalk import (
    build_robust_id_crosswalk,
    extend_crosswalk_with_name_matches,
)
from fantasy_analyzer.players.free_agents import (
    FREE_AGENT_POOL_COLUMNS,
    build_player_universe,
)
from fantasy_analyzer.players.kicker_defense import (
    KICKER_DEFENSE_POSITIONS,
    build_kicker_defense_projections,
)
from fantasy_analyzer.players.lineup_efficiency import START_SLOT_ELIGIBILITY
from fantasy_analyzer.players.nflverse_cache import get_player_stats_cached
from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.nflverse_provider import NflverseWeeklyStatsProvider
from fantasy_analyzer.players.nflverse_schedule_cache import get_games_cached
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient
from fantasy_analyzer.players.opponent_strength import (
    add_matchup_context,
    build_defense_vs_position,
    bye_weeks,
    completed_nfl_weeks,
    normalize_schedule,
    normalize_team,
    started_nfl_teams,
)
from fantasy_analyzer.players.player_value import build_player_value_metrics
from fantasy_analyzer.players.ros_backtest import build_scored_player_weeks
from fantasy_analyzer.players.ros_projection import (
    DEFAULT_N0,
    ShrinkageParameters,
    load_shrinkage_parameters,
)
from fantasy_analyzer.players.roster_fit import (
    POSITION_ALIASES,
    assign_lineup_slots,
    build_add_drop_candidates,
    build_roster_projection_frame,
    open_roster_spots,
    optimal_lineup,
    starting_slots,
)
from fantasy_analyzer.players.usage import load_usage_player_weeks
from fantasy_analyzer.players.usage_projection import (
    UsageModelParameters,
    load_usage_model_parameters,
)
from fantasy_analyzer.players.waiver_rankings import (
    build_free_agent_ros_projections,
    build_waiver_wire_rankings,
)
from fantasy_analyzer.sleeper.cache import get_players_cached
from fantasy_analyzer.sleeper.client import SleeperClient

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

#: Positions nflverse's player-week rows do not cover, so a projection for
#: them exists only if a dedicated source supplies one. A slot for such a
#: position is dropped from the solve only while *no* row at that position
#: carries a projection (:func:`unprojectable_positions`) -- ``optimal_lineup``
#: would otherwise read the slot as empty and understate the lineup total.
#: Once K/DEF projections are in the projection frame, their slots return
#: automatically.
UNPROJECTABLE_POSITIONS = frozenset({"K", "DEF", "DST"})

#: The usage-model explanation columns (``waiver_rankings``), shown as the
#: "why" behind a projection on the board and the lineup. Absent columns are
#: skipped by :func:`_records`, so the page degrades to fewer fields.
USAGE_EXPLANATION_COLUMNS = [
    "eb_projected_ppg",
    "usage_projected_ppg",
    "projection_model",
    "snap_share",
    "snap_share_last2",
    "xfp_per_game",
    "points_over_expected_per_game",
    "projected_targets_per_game",
    "projected_carries_per_game",
    "projected_pass_attempts_per_game",
]

#: Board context carried onto each add/drop move, so the page can flag a
#: candidate's injury and bye without a second lookup.
MOVE_CONTEXT_COLUMNS = ["board_rank", "injury_status", "bye_week"]

#: Positions projected by ``build_kicker_defense_projections`` and never by
#: the skill-player model. See the module docstring.
KDEF_POSITIONS = frozenset(KICKER_DEFENSE_POSITIONS)

#: The per-player column the coming week's lineup is solved on:
#: ``week_projected_points`` for K/DEF (market-adjusted, 0.0 on a bye),
#: ``projected_ppg`` for everyone else. The moves use ``projected_ppg``.
LINEUP_PPG_COLUMN = "lineup_ppg"

#: K and DEF free agents added to the move shortlist per position, on top of
#: the ``ADD_DROP_CANDIDATES`` skill players. A shortlist ranked on raw
#: ``projected_ppg`` alone would let a kicker crowd out a receiver, or the
#: reverse; a K/DEF move is scored as a swap for the rostered one
#: (``same_position_drop``), so a few suffice.
KDEF_MOVE_CANDIDATES = 3

#: K and DEF rows kept in the bundle's board beyond the top
#: ``--top-free-agents`` overall, so the page's K/DEF filter always has the
#: best few to show even though none rank near the top of the whole board.
KDEF_BOARD_ROWS = 5

#: Column order of the per-league valuation CSV (missing columns skipped).
VALUATION_COLUMNS = [
    "overall_rank",
    "position_rank",
    "player_id",
    "full_name",
    "position",
    "team",
    "status",
    "is_rostered",
    "roster_id",
    "owner",
    "owner_team_name",
    "injury_status",
    "injury_body_part",
    "bye_week",
    "projection_source",
    "projected_ppg",
    "week_projected_points",
    "replacement_ppg",
    "ppg_above_replacement",
    "points_above_replacement",
    "remaining_games",
    "projected_ros_points",
    "games_to_date",
    "ppg_to_date",
    "last3_ppg",
    "prior_season_ppg",
    "prior_season_games",
    "confidence_tier",
    "has_crosswalk",
    "targets_per_game",
    "carries_per_game",
    "target_share",
    *USAGE_EXPLANATION_COLUMNS,
]

#: How many ranked free agents to keep in the bundle per league.
DEFAULT_TOP_FREE_AGENTS = 40

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
        normalize_injury_status(
            (catalog.get(str(player_id)) or {}).get("injury_status")
        )
        for player_id in result["player_id"]
    ]
    result["injury_body_part"] = [
        (catalog.get(str(player_id)) or {}).get("injury_body_part")
        for player_id in result["player_id"]
    ]
    return result


def _upcoming_matchup(
    raw: list[dict],
    week: int,
    my_roster_id: Optional[int],
    teams_df: pd.DataFrame,
) -> Optional[dict]:
    """Resolve who ``my_roster_id`` faces in ``week``, from Sleeper's raw pairing.

    ``raw`` is the ``/matchups/<week>`` payload rather than the normalized
    season frame: that frame is built from completed weeks, and this is by
    definition the week not yet final. Before any game, every ``points`` is
    ``0.0`` and only the ``matchup_id`` grouping carries information; once
    a game has kicked off (a Thursday night game, say), ``points`` and
    ``opponent_points`` are Sleeper's live totals so far.
    """
    if my_roster_id is None:
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
        "points": _clean(mine.get("points")),
        "opponent_points": _clean(opponent.get("points")),
    }


def _live_player_points(
    raw: list[dict], my_roster_id: Optional[int]
) -> dict[str, float]:
    """``player_id -> points so far`` for ``my_roster_id`` in a raw week payload.

    Sleeper's live ``players_points``: final for a player whose game is
    over, partial for one in progress, ``0.0`` for one yet to play. Empty
    when the roster has no row.
    """
    mine = next(
        (row for row in raw if row.get("roster_id") == my_roster_id), None
    )
    if mine is None:
        return {}
    return {
        str(player_id): float(points)
        for player_id, points in (mine.get("players_points") or {}).items()
        if points is not None
    }


def _locked_player_ids(
    player_ids: Iterable[str],
    roster_frame: pd.DataFrame,
    catalog: dict,
    locked_teams: frozenset[str],
) -> set[str]:
    """The players in ``player_ids`` whose NFL team's game has kicked off.

    Team comes from the projection row when there is one, else the Sleeper
    catalog, compared through ``normalize_team`` (``locked_teams`` is in
    nflverse spelling, from ``started_nfl_teams``).
    """
    if not locked_teams:
        return set()
    teams = (
        dict(zip(roster_frame["player_id"].astype(str), roster_frame["team"]))
        if not roster_frame.empty
        else {}
    )
    return {
        player_id
        for player_id in player_ids
        if normalize_team(
            teams.get(player_id, (catalog.get(player_id) or {}).get("team"))
        )
        in locked_teams
    }


def _completed_weeks(
    season_matchup_df: pd.DataFrame, nfl_completed_weeks: Iterable[int]
) -> list[int]:
    """Return the fantasy weeks that are final on Sleeper *and* in the NFL.

    Two conditions, both required (FFA-108):

    1. Every contested matchup has non-null, non-zero points on both sides.
       Sleeper returns a full slate of rows for a future week with every
       ``points`` at ``0.0``, so presence of a row is not evidence a week
       was played.
    2. The week is in ``nfl_completed_weeks`` -- every NFL game scheduled
       that week has a final score
       (:func:`~fantasy_analyzer.players.opponent_strength.completed_nfl_weeks`).
       Condition 1 alone passes a week still waiting on Monday night,
       because every fantasy team already has *some* points by then.

    Fantasy week ``N`` is taken to be NFL week ``N``, which holds for every
    league this dashboard covers (all start in NFL week 1).
    """
    if season_matchup_df.empty:
        return []

    nfl_done = {int(week) for week in nfl_completed_weeks}
    complete: list[int] = []
    for week, group in season_matchup_df.groupby("week"):
        if int(week) not in nfl_done:
            continue
        contested = group[group["roster_2_id"].notna()]
        if contested.empty:
            continue
        points = pd.concat([contested["points_1"], contested["points_2"]])
        if points.notna().all() and points.gt(0).all():
            complete.append(int(week))
    return sorted(complete)


def unprojectable_positions(projections: pd.DataFrame) -> frozenset[str]:
    """The :data:`UNPROJECTABLE_POSITIONS` with no projected row in ``projections``.

    Only these are stripped from the lineup solve and the add/drop search.
    ``DST`` is read as ``DEF`` (``roster_fit.POSITION_ALIASES``), so a
    projection under either spelling brings the ``DEF`` slot back.
    """
    if projections.empty or "projected_ppg" not in projections.columns:
        return UNPROJECTABLE_POSITIONS
    projected = {
        POSITION_ALIASES.get(str(position), str(position))
        for position in projections.loc[
            projections["projected_ppg"].notna(), "position"
        ]
    }
    return frozenset(
        position
        for position in UNPROJECTABLE_POSITIONS
        if POSITION_ALIASES.get(position, position) not in projected
    )


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


def _projection_universe(
    skill_projections: pd.DataFrame,
    kdef_projections: pd.DataFrame,
    universe: pd.DataFrame,
) -> pd.DataFrame:
    """One projection row per universe player, each from exactly one model.

    ``QB``/``RB``/``WR``/``TE`` rows come from the skill model; ``K``/``DEF``
    rows come only from ``build_kicker_defense_projections`` -- any K/DEF
    row the skill model produced is discarded. ``kdef_projections`` covers
    the whole catalog, so it is cut to the universe's ids. Adds
    ``projection_source``, :data:`LINEUP_PPG_COLUMN`, and the universe's
    ``is_rostered``/``roster_id``, which the projection frames do not carry.

    A universe K/DEF with no row in ``kdef_projections`` (a rostered id the
    catalog does not know) simply has no projection row, the same outcome
    as a skill player the projection could not resolve.
    """
    ids = set(universe["player_id"].astype(str))

    skill = skill_projections[
        ~skill_projections["position"].isin(KDEF_POSITIONS)
    ].assign(projection_source="skill")
    skill[LINEUP_PPG_COLUMN] = skill["projected_ppg"]

    kdef = kdef_projections
    if not kdef.empty:
        kdef = kdef[kdef["player_id"].astype(str).isin(ids)].assign(
            projection_source="kicker_defense"
        )
        kdef[LINEUP_PPG_COLUMN] = kdef["week_projected_points"]

    frames = [frame for frame in (skill, kdef) if not frame.empty]
    if not frames:
        return skill.assign(is_rostered=pd.Series(dtype=bool), roster_id=None)
    combined = pd.concat(frames, ignore_index=True)
    combined["player_id"] = combined["player_id"].astype(str)

    state = universe[["player_id", "is_rostered", "roster_id"]].assign(
        player_id=universe["player_id"].astype(str)
    )
    combined = combined.merge(state, on="player_id", how="left")
    combined["is_rostered"] = combined["is_rostered"].fillna(False).astype(bool)
    return combined


def _value_players(
    projections: pd.DataFrame,
    season: int,
    roster_positions: list[str],
    num_teams: int,
) -> pd.DataFrame:
    """Replacement level, VORP and ranks for every projected universe player.

    Shapes ``projections`` exactly as
    ``waiver_rankings.build_waiver_wire_rankings`` does (remaining games,
    per-game rate, rest-of-season total) and hands it to the same
    ``player_value.build_player_value_metrics`` (FFA-068). Over the whole
    universe that puts each position's replacement at the league's last
    starter there -- ``1 x num_teams`` for ``K`` and ``DEF`` -- and a
    free agent's VORP here equals the one on the skill board.

    Adds ``replacement_ppg``, ``ppg_above_replacement``,
    ``points_above_replacement``, ``overall_rank`` and ``position_rank``.
    Ranks are standard competition ranks ("1224") on descending
    ``points_above_replacement`` judged at six decimals -- the rule
    ``waiver_rank`` uses -- so tied values share a rank. A player with no
    projection has ``NaN`` in all five.
    """
    result = projections.copy()
    for column in (
        "replacement_ppg",
        "ppg_above_replacement",
        "points_above_replacement",
    ):
        result[column] = float("nan")
    if result.empty:
        result["overall_rank"] = pd.Series(dtype="float64")
        result["position_rank"] = pd.Series(dtype="float64")
        return result

    performance_df = pd.DataFrame(
        {
            "season": season,
            "sleeper_player_id": result["player_id"].astype(str),
            "player_name": result["full_name"],
            "position": result["position"],
            "nfl_team": result["team"],
            "games_played": result["remaining_games"],
            "points_per_game": result["projected_ppg"],
            "total_points": result["projected_ros_points"],
        }
    )
    valid = (
        performance_df["points_per_game"].notna()
        & performance_df["total_points"].notna()
    )
    value_df = build_player_value_metrics(
        performance_df.loc[valid], roster_positions, num_teams
    )
    if not value_df.empty:
        lookup = value_df.set_index("sleeper_player_id")
        for column in (
            "replacement_ppg",
            "ppg_above_replacement",
            "points_above_replacement",
        ):
            result[column] = (
                result["player_id"].astype(str).map(lookup[column]).astype("float64")
            )

    key = result["points_above_replacement"].round(6)
    result["overall_rank"] = key.rank(method="min", ascending=False)
    result["position_rank"] = key.groupby(result["position"]).rank(
        method="min", ascending=False
    )
    return result


def _merge_kdef_board(board: pd.DataFrame, valued: pd.DataFrame) -> pd.DataFrame:
    """Add the K/DEF free agents to the skill board and rank the whole board.

    K/DEF rows come from ``valued`` (their own model, universe VORP), and
    their ``matchup_adjusted_ppg`` is the K/DEF model's own this-week
    ``week_projected_points`` rather than the skill board's
    defense-vs-position figure. ``board_rank`` is then assigned over the
    combined board on descending ``points_above_replacement`` (six
    decimals), then descending ``projected_ppg``, then ``player_id``; a row
    with no VORP sorts last. ``waiver_rank`` stays the skill pipeline's own
    and is ``NaN`` on K/DEF rows.
    """
    kdef = valued[
        valued["position"].isin(KDEF_POSITIONS) & ~valued["is_rostered"].astype(bool)
    ]
    if not kdef.empty:
        kdef = kdef.assign(matchup_adjusted_ppg=kdef["week_projected_points"])

    frames = [
        frame
        for frame in (board.drop(columns="board_rank", errors="ignore"), kdef)
        if not frame.empty
    ]
    if not frames:
        return board.assign(board_rank=pd.Series(dtype="int64"))
    combined = pd.concat(frames, ignore_index=True)
    combined["_value_key"] = pd.to_numeric(
        combined["points_above_replacement"], errors="coerce"
    ).round(6)
    combined = (
        combined.sort_values(
            ["_value_key", "projected_ppg", "player_id"],
            ascending=[False, False, True],
            na_position="last",
            kind="stable",
        )
        .drop(columns="_value_key")
        .reset_index(drop=True)
    )
    combined.insert(0, "board_rank", range(1, len(combined) + 1))
    return combined


def _board_rows(board: pd.DataFrame, top: int, per_kdef: int) -> pd.DataFrame:
    """The board rows the bundle carries: the top ``top`` overall, plus the
    best ``per_kdef`` K and DEF wherever they rank, in ``board_rank`` order.
    """
    if board.empty:
        return board
    extra = (
        board[board["position"].isin(KDEF_POSITIONS)]
        .sort_values("board_rank", kind="stable")
        .groupby("position", sort=False)
        .head(per_kdef)
    )
    rows = pd.concat([board.head(top), extra], ignore_index=True)
    return (
        rows.drop_duplicates(subset="player_id")
        .sort_values("board_rank", kind="stable")
        .reset_index(drop=True)
    )


def _valuation_table(
    valued: pd.DataFrame,
    catalog: dict,
    byes: dict,
    teams_df: pd.DataFrame,
) -> pd.DataFrame:
    """The per-league full-universe valuation CSV (see the module docstring).

    Adds injury (from the Sleeper catalog), bye week (from the NFL
    schedule), and the owning manager's display and team name. Sorted by
    ``overall_rank`` (unranked last), then position, then ``player_id``;
    columns follow :data:`VALUATION_COLUMNS`, skipping any absent.
    """
    if valued.empty:
        return pd.DataFrame(columns=VALUATION_COLUMNS)

    table = _add_injury_status(valued, catalog)
    table["bye_week"] = [byes.get(normalize_team(team)) for team in table["team"]]

    names = {
        int(row.roster_id): (row.display_name, row.team_name)
        for row in teams_df.itertuples(index=False)
        if pd.notna(row.roster_id)
    }

    def _owner(roster_id: Any, index: int) -> Optional[str]:
        if roster_id is None or pd.isna(roster_id):
            return None
        label = names.get(int(roster_id), (None, None))[index]
        return None if label is None or pd.isna(label) else label

    table["owner"] = [_owner(rid, 0) for rid in table["roster_id"]]
    table["owner_team_name"] = [_owner(rid, 1) for rid in table["roster_id"]]
    table = table.sort_values(
        ["overall_rank", "position", "player_id"],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)
    return table[[column for column in VALUATION_COLUMNS if column in table.columns]]


def _build_waiver_board(
    snapshot,
    universe: pd.DataFrame,
    kdef_projections: pd.DataFrame,
    catalog: dict,
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    parameters: ShrinkageParameters,
    schedule: pd.DataFrame,
    usage_parameters: Optional[UsageModelParameters] = None,
    usage: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rank free agents, and return ``(board, valued_universe)``.

    The skill board mirrors ``cli.build_free_agent_rankings``'s three
    accuracy-critical composition choices (robust crosswalk, league-wide
    replacement population, fitted shrinkage parameters), with the player
    universe (FFA-109) as that population, then layers FFA-099's
    opponent/defense-vs-position context on top. K/DEF free agents are then
    merged in from their own model (:func:`_merge_kdef_board`).

    ``usage_parameters``, the league's ``scoring_settings`` and ``usage``
    switch on the FFA-111 usage blend and FFA-104's absent-prior line. They
    are passed to *both* the board and the universe projection, so the two
    agree; ``None`` for both keeps the EB projection alone.

    ``valued_universe`` -- every universe player's projection plus VORP -- is
    returned alongside because the lineup needs *rostered* players'
    projections, and the valuation CSV needs everyone's.
    """
    roster_positions = snapshot.roster_positions
    num_teams = snapshot.league.total_rosters

    skill_universe = universe[~universe["position"].isin(KDEF_POSITIONS)]
    population = skill_universe[FREE_AGENT_POOL_COLUMNS].reset_index(drop=True)
    free_agent_pool = skill_universe.loc[
        ~skill_universe["is_rostered"].astype(bool), FREE_AGENT_POOL_COLUMNS
    ].reset_index(drop=True)

    board = build_waiver_wire_rankings(
        free_agent_pool,
        scored_weeks,
        season,
        cutoff_week,
        roster_positions,
        num_teams,
        parameters,
        replacement_population=population,
        usage_parameters=usage_parameters,
        scoring_settings=snapshot.scoring_settings,
        usage=usage,
    )

    if not board.empty and not schedule.empty:
        defense_vs_position = build_defense_vs_position(
            scored_weeks, season, through_week=cutoff_week
        )
        # ``add_matchup_context`` takes the *cutoff* week and builds context
        # for ``week + 1`` itself -- passing the upcoming week here would
        # describe the week after the one being planned for.
        board = add_matchup_context(
            board,
            schedule,
            defense_vs_position,
            week=cutoff_week,
            season_end_week=DEFAULT_TOTAL_WEEKS,
        )
    board = board.assign(projection_source="skill")

    skill_projections = build_free_agent_ros_projections(
        population,
        scored_weeks,
        season,
        cutoff_week,
        parameters,
        usage_parameters=usage_parameters,
        scoring_settings=snapshot.scoring_settings,
        usage=usage,
    )
    valued = _value_players(
        _projection_universe(skill_projections, kdef_projections, universe),
        season,
        roster_positions,
        num_teams,
    )

    # ``board_rank`` is what the page shows: assigned after the K/DEF merge,
    # so it ranks every position on one basis. ``waiver_rank`` stays the
    # skill pipeline's own output.
    board = _merge_kdef_board(board, valued)
    board = _add_injury_status(board, catalog)
    return board, valued


def _replacement_levels(projections: pd.DataFrame) -> dict[str, float]:
    """Position -> replacement ppg, as the board and the valuation measure it.

    Read from :func:`_value_players`' ``replacement_ppg`` (FFA-068's
    last-starter baseline over the universe, ``num_teams = total_rosters``),
    which is constant within a position. Used as the moves' streaming-level
    fill: what a manager can stream off the wire for a slot nobody on the
    roster can fill. Empty if the frame carries no replacement levels.
    """
    if projections.empty or "replacement_ppg" not in projections.columns:
        return {}
    levels = (
        projections.dropna(subset=["replacement_ppg"])
        .groupby("position")["replacement_ppg"]
        .first()
    )
    return {
        POSITION_ALIASES.get(str(position), str(position)): float(value)
        for position, value in levels.items()
    }


def _rank_moves(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge separately scored add/drop frames into one ranked list.

    Uses ``build_add_drop_candidates``'s own ordering -- descending
    ``net_lineup_gain``, then ``starting_ppg_gain``, then projection, then
    ``player_id``, gains compared at nine decimals -- and renumbers
    ``add_drop_rank`` over the union.
    """
    if not frames:
        return pd.DataFrame()
    moves = pd.concat(frames, ignore_index=True)
    moves["_net"] = moves["net_lineup_gain"].astype("float64").round(9)
    moves["_gain"] = moves["starting_ppg_gain"].astype("float64").round(9)
    moves = (
        moves.sort_values(
            ["_net", "_gain", "projected_ppg", "player_id"],
            ascending=[False, False, False, True],
            kind="stable",
        )
        .drop(columns=["_net", "_gain"])
        .reset_index(drop=True)
    )
    moves["add_drop_rank"] = range(1, len(moves) + 1)
    return moves


def _fill_unprojected_slots(
    placed: list[tuple[str, Optional[str]]],
    roster_frame: pd.DataFrame,
    currently_starting: set[str],
) -> list[tuple[str, Optional[str]]]:
    """Put an available but unprojected player into each slot the solve left empty.

    Display only: ``optimal_lineup`` ignores a player with no projection, so
    a rookie kicker missing from the ID crosswalk leaves the ``K`` slot empty
    and the page would otherwise tell the manager to bench his only kicker.
    A filler adds nothing to ``projected_points``. Players already in the
    manager's lineup are preferred, then ``player_id`` order.
    """
    taken = {pid for _, pid in placed if pid is not None}
    pool = roster_frame[
        roster_frame["available"]
        & roster_frame[LINEUP_PPG_COLUMN].isna()
        & ~roster_frame["player_id"].isin(taken)
    ]
    pool = sorted(
        zip(pool["player_id"], pool["position"]),
        key=lambda item: (item[0] not in currently_starting, item[0]),
    )

    filled: list[tuple[str, Optional[str]]] = []
    for slot, pid in placed:
        if pid is None:
            eligible = START_SLOT_ELIGIBILITY.get(slot, ())
            for candidate, position in pool:
                label = POSITION_ALIASES.get(str(position), str(position))
                if candidate not in taken and label in eligible:
                    pid = candidate
                    taken.add(candidate)
                    break
        filled.append((slot, pid))
    return filled


def _build_lineup(
    roster_positions: list[str],
    my_roster: dict,
    population_projections: pd.DataFrame,
    board: pd.DataFrame,
    catalog: dict,
    byes: dict,
    upcoming_week: int,
    season_end_week: int,
    locked_teams: frozenset[str] = frozenset(),
    live_points: Optional[dict[str, float]] = None,
) -> dict:
    """Recommend a starting lineup and the best add/drop moves for one roster.

    Pure given its inputs (no network), so it is tested directly.

    - **Lineup**: the coming week only. Availability is the package rule
      (``add_availability``): Out, IR, suspended and bye-week players are
      never started; Questionable players are, and are flagged.
    - **Moves**: scored over ``[upcoming_week, season_end_week]`` with each
      player's per-week availability (``build_add_drop_candidates``'s
      horizon), so a player merely Out or on bye this week is not a free
      drop. IR-slot players are never the drop, and an open roster spot
      means no drop at all. Free agents with a long-term status (IR, PUP,
      ...) are left off the shortlist: they are stashes, and the four-week
      absence the package assumes is a lower bound that would overrate a
      season-ending injury.
    - **K/DEF**: the lineup is solved on :data:`LINEUP_PPG_COLUMN` --
      the K/DEF model's this-week ``week_projected_points`` for kickers and
      defenses, ``projected_ppg`` for everyone else (a frame without the
      column is solved on ``projected_ppg``). A slot for a position with no
      projection anywhere in ``population_projections`` is dropped
      (:func:`unprojectable_positions`) rather than read as empty. The move
      shortlist is the top :data:`ADD_DROP_CANDIDATES` skill players plus
      the top :data:`KDEF_MOVE_CANDIDATES` per K/DEF, by ``projected_ppg``.
    - **Streaming fill**: the moves score a slot nobody on the roster can
      fill that week at the position's replacement level
      (:func:`_replacement_levels`, ``roster_fit``'s ``empty_slot_values``),
      so a backup is worth only his margin over a waiver streamer.
    - **Game locks**: ``locked_teams`` (``started_nfl_teams``) are the NFL
      teams whose game this week has kicked off, which Sleeper locks. A
      locked player in the manager's current lineup keeps his slot and
      scores his ``live_points`` (Sleeper's ``players_points``), added to
      ``projected_points`` as ``locked_points``; the solve fills only the
      other slots. A locked bench player is unavailable this week. In the
      moves, a locked player is never the drop and a locked free agent is
      never the add (Sleeper allows neither), and a K/DEF swap is not
      offered while every rostered K (or DEF) is locked -- it would
      otherwise fall back to a roster-wide drop and carry two kickers.
      Known approximation: the moves' horizon evaluator has one slot list
      for every week, so in the coming week alone it may bench a locked
      starter for an add. That error is bounded by one week of the horizon
      and needs an add projected above a locked starter he could replace.
    """
    player_ids = [str(pid) for pid in (my_roster.get("players") or [])]
    starters_now = {str(pid) for pid in (my_roster.get("starters") or [])}
    reserve = {str(pid) for pid in (my_roster.get("reserve") or [])}
    spots = open_roster_spots(my_roster, roster_positions)
    live_points = live_points or {}

    excluded = unprojectable_positions(population_projections)
    lineup_slots = [slot for slot in roster_positions if slot not in excluded]
    slot_labels = starting_slots(lineup_slots)
    horizon = {
        "from_week": upcoming_week,
        "through_week": max(upcoming_week, season_end_week),
    }

    roster_frame = build_roster_projection_frame(
        player_ids, population_projections, id_column="player_id"
    )
    if not roster_frame.empty:
        roster_frame = roster_frame[
            ~roster_frame["position"].isin(excluded)
        ].reset_index(drop=True)

    if roster_frame.empty:
        return {
            "projected_slots": slot_labels,
            "slot_order": [],
            "recommended_starters": [],
            "bench": [],
            "unavailable": [],
            "projected_points": None,
            "add_drop": [],
            "excluded_positions": sorted(excluded),
            "open_roster_spots": spots,
            "horizon": horizon,
            "streaming_values": _replacement_levels(population_projections),
            "locked_teams": sorted(locked_teams),
            "locked_points": None,
        }

    roster_frame["player_id"] = roster_frame["player_id"].astype(str)
    if LINEUP_PPG_COLUMN not in roster_frame.columns:
        roster_frame[LINEUP_PPG_COLUMN] = roster_frame["projected_ppg"]
    roster_frame = _add_injury_status(roster_frame, catalog)
    roster_frame["bye_week"] = [
        byes.get(normalize_team(team)) for team in roster_frame["team"]
    ]
    roster_frame = add_availability(roster_frame, upcoming_week)

    # Game locks. Sleeper's ``starters`` list is aligned with the league's
    # startable slots, so a locked starter's index *is* his slot.
    locked = _locked_player_ids(player_ids, roster_frame, catalog, locked_teams)
    all_slots = starting_slots(roster_positions)
    sleeper_starters = [str(pid) for pid in (my_roster.get("starters") or [])]
    fixed = {
        index: pid
        for index, pid in enumerate(sleeper_starters[: len(all_slots)])
        if pid in locked and all_slots[index] not in excluded
    }
    roster_frame["locked"] = roster_frame["player_id"].isin(locked)
    roster_frame["actual_points"] = [
        live_points.get(pid, float("nan")) if pid in locked else float("nan")
        for pid in roster_frame["player_id"]
    ]
    locked_bench = roster_frame["locked"] & ~roster_frame["player_id"].isin(
        set(fixed.values())
    )
    roster_frame.loc[locked_bench, "available"] = False
    roster_frame.loc[locked_bench, "unavailable_reason"] = "Locked"
    roster_frame["unavailable"] = ~roster_frame["available"]
    roster_frame["in_reserve"] = roster_frame["player_id"].isin(reserve)

    # ``optimal_lineup`` honors the ``available`` column written above; the
    # solve fills only the slots no locked starter holds.
    free_slots = [
        slot
        for index, slot in enumerate(all_slots)
        if index not in fixed and slot not in excluded
    ]
    solve_frame = roster_frame[~roster_frame["locked"]]
    solution = optimal_lineup(solve_frame, free_slots, ppg_column=LINEUP_PPG_COLUMN)
    free_placed = iter(
        _fill_unprojected_slots(
            assign_lineup_slots(
                solve_frame,
                solution.starters,
                free_slots,
                ppg_column=LINEUP_PPG_COLUMN,
            ),
            solve_frame,
            starters_now,
        )
    )
    placed = [
        (slot, fixed[index]) if index in fixed else next(free_placed)
        for index, slot in enumerate(all_slots)
        if slot not in excluded
    ]
    locked_points = (
        math.fsum(live_points.get(pid, 0.0) for pid in fixed.values())
        if fixed
        else None
    )
    slot_of = {pid: slot for slot, pid in placed if pid is not None}
    slot_rank = {pid: index for index, (_, pid) in enumerate(placed) if pid}

    roster_frame = roster_frame.assign(
        recommended_start=roster_frame["player_id"].isin(slot_of),
        currently_starting=roster_frame["player_id"].isin(starters_now),
        projection_missing=roster_frame[LINEUP_PPG_COLUMN].isna(),
        slot=[slot_of.get(pid) for pid in roster_frame["player_id"]],
    )
    roster_frame = roster_frame.sort_values(
        by=["recommended_start", LINEUP_PPG_COLUMN], ascending=[False, False]
    ).reset_index(drop=True)

    roster_columns = [
        "player_id",
        "full_name",
        "position",
        "team",
        "slot",
        "injury_status",
        "injury_body_part",
        "bye_week",
        "on_bye",
        "available",
        "unavailable",
        "unavailable_reason",
        "in_reserve",
        "projection_missing",
        "projection_source",
        "projected_ppg",
        LINEUP_PPG_COLUMN,
        "week_opponent",
        "games_to_date",
        "ppg_to_date",
        "last3_ppg",
        "confidence_tier",
        "targets_per_game",
        "carries_per_game",
        "target_share",
        *USAGE_EXPLANATION_COLUMNS,
        "recommended_start",
        "currently_starting",
        "locked",
        "actual_points",
    ]

    candidates = board
    if not candidates.empty and "injury_status" in candidates.columns:
        candidates = candidates[
            ~candidates["injury_status"].isin(LONG_TERM_INJURY_STATUSES)
        ]
    if not candidates.empty and locked_teams:
        candidates = candidates[
            [normalize_team(team) not in locked_teams for team in candidates["team"]]
        ]
        # A K/DEF move is a like-for-like swap; with every rostered one
        # locked there is nothing to swap out until the lock clears.
        held_kdef = roster_frame[roster_frame["position"].isin(KDEF_POSITIONS)]
        blocked = {
            position
            for position, group in held_kdef.groupby("position")
            if group["locked"].all()
        }
        candidates = candidates[~candidates["position"].isin(blocked)]
    if not candidates.empty:
        candidates = candidates[~candidates["position"].isin(excluded)].sort_values(
            by="projected_ppg", ascending=False, kind="stable"
        )
        is_kdef = candidates["position"].isin(KDEF_POSITIONS)
        candidates = pd.concat(
            [
                candidates[~is_kdef].head(ADD_DROP_CANDIDATES),
                candidates[is_kdef].groupby("position").head(KDEF_MOVE_CANDIDATES),
            ],
            ignore_index=True,
        )

    streaming = _replacement_levels(population_projections)
    add_drop = pd.DataFrame()
    if not candidates.empty:
        # Skill players take the roster-wide cheapest drop; a K or DEF is
        # scored as a swap for the rostered one (``same_position_drop``) --
        # otherwise "carry a second kicker, drop a bench RB" wins on a full
        # week of bye coverage, which is not a move anyone should make.
        is_kdef = candidates["position"].isin(KDEF_POSITIONS)
        scored = [
            build_add_drop_candidates(
                roster_frame,
                group,
                lineup_slots,
                max_candidates=len(group),
                week=upcoming_week,
                season_end_week=season_end_week,
                reserve_player_ids=reserve | locked,
                open_roster_spots=spots,
                same_position_drop=like_for_like,
                empty_slot_values=streaming or None,
            )
            for group, like_for_like in (
                (candidates[~is_kdef], False),
                (candidates[is_kdef], True),
            )
            if not group.empty
        ]
        add_drop = _rank_moves([frame for frame in scored if not frame.empty])
        context = [c for c in MOVE_CONTEXT_COLUMNS if c in candidates.columns]
        if not add_drop.empty and context:
            extra = candidates[["player_id", *context]].assign(
                player_id=candidates["player_id"].astype(str)
            )
            add_drop = add_drop.merge(extra, on="player_id", how="left")

    # A locked starter holds his slot whatever his (possibly stale) injury
    # status says, so starters are read off the placement, not ``available``.
    starters = roster_frame[roster_frame["recommended_start"]]
    starters = starters.assign(
        _slot_rank=starters["player_id"].map(slot_rank)
    ).sort_values("_slot_rank", kind="stable")
    sitting = roster_frame[~roster_frame["recommended_start"]]

    return {
        "projected_slots": slot_labels,
        "slot_order": [{"slot": slot, "player_id": pid} for slot, pid in placed],
        "recommended_starters": _records(starters, roster_columns),
        "bench": _records(sitting[sitting["available"]], roster_columns),
        "unavailable": _records(sitting[~sitting["available"]], roster_columns),
        "projected_points": _clean(
            solution.points_per_game + (locked_points or 0.0)
        ),
        "add_drop": _records(add_drop),
        "excluded_positions": sorted(excluded),
        "open_roster_spots": spots,
        "horizon": horizon,
        "streaming_values": streaming,
        "locked_teams": sorted(locked_teams),
        "locked_points": _clean(locked_points),
    }


def _load_usage_inputs(
    season: int,
) -> tuple[Optional[UsageModelParameters], Optional[pd.DataFrame]]:
    """The fitted usage model and the snap/xFP frame, from the local caches.

    Returns ``(usage_parameters, usage)``. The frame covers ``season`` and
    ``season - 1`` -- the window the usage features read. Either half may
    be ``None`` (see the module docstring's "The skill-player model" for
    what each fallback costs); the build prints which model it is using so
    a degraded run is visible.
    """
    usage_parameters = load_usage_model_parameters()
    if usage_parameters is None:
        print(
            "usage model: no fitted parameters (run scripts/fit_usage_model.py) "
            "-- skill players projected by EB alone",
            flush=True,
        )
        return None, None

    try:
        usage = load_usage_player_weeks([season - 1, season])
    except FileNotFoundError as error:
        print(
            f"usage model: fitted, but no snap/xFP cache ({error}) "
            "-- using the no-snap model",
            flush=True,
        )
        return usage_parameters, None

    current = usage[usage["season"] == season]
    through = int(current["week"].max()) if not current.empty else None
    print(
        f"usage model: fitted; snap/xFP rows {len(usage)} "
        f"({season} through week {through})",
        flush=True,
    )
    return usage_parameters, usage


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
    usage_parameters, usage = _load_usage_inputs(season)

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

    # Verified name matches for players the two ID sources miss (a rookie
    # kicker with no Sleeper id in DynastyProcess, for one). Only adds rows.
    crosswalk = extend_crosswalk_with_name_matches(
        crosswalk, catalog, pd.concat([current_raw, prior_raw], ignore_index=True)
    )

    # The K/DEF model reads nflverse's *raw* weekly table (GSIS ``player_id``,
    # ``season_type``), not the provider-normalized frames above.
    nflverse_client = NflverseClient()
    raw_stats_by_season = {
        stats_season: get_player_stats_cached(nflverse_client, stats_season)
        for stats_season in (season - 1, season)
    }

    games = get_games_cached(NflverseScheduleClient())
    schedule = (
        normalize_schedule(games, season) if games is not None else pd.DataFrame()
    )
    byes = bye_weeks(schedule, DEFAULT_TOTAL_WEEKS) if not schedule.empty else {}
    # FFA-108: a fantasy week is final only once every NFL game in it is. A
    # missing or stale schedule cache therefore holds weeks back rather than
    # publishing partial scores -- refresh it (docs/dashboard.md, step 1).
    nfl_completed = completed_nfl_weeks(games, season) if games is not None else []
    print(f"NFL weeks final in the schedule cache: {nfl_completed}", flush=True)
    now = datetime.now(timezone.utc)

    commentary_dir = out_dir / "commentary"
    commentary_dir.mkdir(parents=True, exist_ok=True)
    valuations_dir = out_dir / "valuations"
    valuations_dir.mkdir(parents=True, exist_ok=True)

    leagues: list[dict] = []
    for slug in league_slugs:
        preset = LEAGUES[slug]
        league_id = preset["league_id"]
        print(f"[{slug}] league {league_id}", flush=True)

        snapshot, season_matchup_df, analytics = _league_frames(
            client, league_id, total_weeks
        )
        completed = _completed_weeks(season_matchup_df, nfl_completed)
        upcoming = (max(completed) + 1) if completed else 1
        cutoff = max(completed) if completed else 0
        boundaries = derive_season_boundaries(snapshot.league, total_weeks=total_weeks)
        season_end_week = (
            boundaries.regular_season_weeks[-1]
            if boundaries.regular_season_weeks
            else total_weeks
        )
        print(
            f"[{slug}]   completed weeks {completed}, upcoming {upcoming}",
            flush=True,
        )

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
        my_roster_id = my_roster.get("roster_id") if my_roster else None
        try:
            upcoming_raw = client.get_matchups(league_id, upcoming)
        except Exception:  # pragma: no cover -- the page degrades without it
            upcoming_raw = []
        upcoming_matchup = _upcoming_matchup(
            upcoming_raw, upcoming, my_roster_id, snapshot.teams_df
        )

        # Teams whose game this week has already kicked off (a Thursday
        # night game, say): Sleeper has locked their players.
        locked_teams = (
            started_nfl_teams(games, season, upcoming, now)
            if games is not None
            else frozenset()
        )
        print(
            f"[{slug}]   week {upcoming} games kicked off: "
            f"{sorted(locked_teams) or 'none'}",
            flush=True,
        )

        scored_weeks = build_scored_player_weeks(
            [current_raw, prior_raw],
            snapshot.scoring_settings,
            player_id_column="gsis_id",
        )

        universe = build_player_universe(
            raw_rosters, catalog, snapshot.roster_positions, crosswalk=crosswalk
        )
        # Every rostered K/DEF gets a projection row, even one the catalog
        # shows without an NFL team.
        rostered_kdef = universe.loc[
            universe["is_rostered"] & universe["position"].isin(KDEF_POSITIONS),
            "player_id",
        ].astype(str)
        kdef_projections = build_kicker_defense_projections(
            catalog,
            snapshot.scoring_settings,
            season,
            cutoff,
            upcoming,
            raw_stats_by_season,
            games if games is not None else pd.DataFrame(),
            crosswalk=crosswalk,
            include_player_ids=list(rostered_kdef),
        )

        print(f"[{slug}]   ranking free agents (cutoff week {cutoff})", flush=True)
        board, valued = _build_waiver_board(
            snapshot,
            universe,
            kdef_projections,
            catalog,
            scored_weeks,
            season,
            cutoff,
            parameters,
            schedule,
            usage_parameters=usage_parameters,
            usage=usage,
        )

        valuation = _valuation_table(valued, catalog, byes, snapshot.teams_df)
        valuation_path = valuations_dir / f"{slug}_week{upcoming}.csv"
        valuation.to_csv(valuation_path, index=False)
        rostered_count = int(valuation["is_rostered"].sum()) if len(valuation) else 0
        print(
            f"[{slug}]   valuation: {len(valuation)} players "
            f"({rostered_count} rostered) -> {valuation_path}",
            flush=True,
        )

        lineup = (
            _build_lineup(
                snapshot.roster_positions,
                my_roster,
                valued,
                board,
                catalog,
                byes,
                upcoming,
                season_end_week,
                locked_teams=locked_teams,
                live_points=_live_player_points(upcoming_raw, my_roster_id),
            )
            if my_roster
            else None
        )
        if not board.empty:
            board = board.assign(
                week_locked=[
                    normalize_team(team) in locked_teams for team in board["team"]
                ]
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
            "projection_source",
            "projected_ppg",
            "matchup_adjusted_ppg",
            "week_projected_points",
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
            "week_locked",
            *USAGE_EXPLANATION_COLUMNS,
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
                "regular_season_end_week": season_end_week,
                "upcoming_matchup": upcoming_matchup,
                "teams": _records(
                    snapshot.teams_df,
                    ["roster_id", "owner_id", "display_name", "team_name"],
                ),
                "weeks": weeks_payload,
                "free_agents": {
                    "cutoff_week": cutoff,
                    "for_week": upcoming,
                    "rows": _records(
                        _board_rows(board, top_free_agents, KDEF_BOARD_ROWS),
                        board_columns,
                    ),
                },
                "valuation": {
                    "file": f"valuations/{valuation_path.name}",
                    "players": len(valuation),
                    "rostered": rostered_count,
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
        "nfl_completed_weeks": nfl_completed,
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
