"""Audit whether every Sleeper player is accounted for, in both directions (FFA-109).

A player can fall out of this codebase's player pipeline at four points,
and before this module each one did so silently:

1. **The free-agent rules.**
   :func:`~fantasy_analyzer.players.free_agents.build_free_agent_pool`
   drops a free agent at a position the league does not start, one Sleeper
   marks ``Inactive``/``Retired``, and (FFA-103) one with no NFL team.
2. **The roster population.** Rostered players are only safe if the
   population is built with
   :func:`~fantasy_analyzer.players.free_agents.build_player_universe`.
3. **The ID crosswalk.** A Sleeper player with no ``gsis_id`` can never be
   joined to an nflverse stat row, so he is never projected.
4. **The stats.** A mapped player with no nflverse row has nothing to
   project from.

This module measures all four. It is pure: catalog dict, roster dicts and
DataFrames in, DataFrame out; no network access. ``scripts/player_coverage_report.py``
runs it against the live leagues.

Forward audit: :func:`build_forward_coverage_audit`
--------------------------------------------------------------------------

One row per Sleeper player in scope -- every catalog player at
:data:`AUDIT_POSITIONS`, plus every rostered ``player_id`` in the league
whatever his position (and even if the catalog lacks him) -- with one
``coverage_reason``. The reasons, in precedence order (the first that
applies wins):

==================================  ======================================
``coverage_reason``                 Meaning
==================================  ======================================
``not_in_catalog``                  Rostered id with no Sleeper catalog
                                    entry. In the universe, with whatever
                                    the crosswalk knows.
``team_unit``                       A team defense (``DEF``). nflverse
                                    publishes no player rows for one, so no
                                    ``gsis_id`` or stats are expected; it
                                    is accounted for by its team code.
``position_not_started``            Free agent at a position the league
                                    has no starting slot for. Excluded.
``excluded_status``                 Free agent Sleeper marks ``Inactive``
                                    or ``Retired``. Excluded.
``no_nfl_team``                     Free agent with no NFL team (FFA-103).
                                    Excluded.
``no_crosswalk``                    In the universe but no ``gsis_id``:
                                    can never be projected.
``crosswalk_no_stats_any_season``   Mapped, but no nflverse row this
                                    season or last: nothing to project
                                    from (FFA-104's "absent prior").
``crosswalk_but_no_stats_yet``      Mapped, no row this season, rows last
                                    season: projected from the prior only.
``ok``                              Mapped, with at least one row this
                                    season.
==================================  ======================================

The first five describe *whether* a player is in the universe
(``in_universe`` is ``False`` exactly for the three free-agent exclusions);
the last four describe *how well* a universe player can be projected. A
rostered player is never given a free-agent exclusion reason -- rostered
players are in the universe regardless of status or team. The ``gsis_id``
and stats columns are filled for every row, excluded ones included, so an
excluded player with real production (e.g. a Sleeper-``Inactive`` free
agent who played last week) is visible rather than just counted.

"Stats" means nflverse player-week rows, regular season only when the
frame carries ``season_type``. nflverse emits a row only for a player who
recorded a statistic, so ``current_season_games`` counts weeks with a row,
not snaps.

Toy example (hand-checkable)
--------------------------------------------------------------------------

League starts ``QB`` only. Catalog: ``"1"`` QB SEA, on roster 1, mapped to
``G1`` with a 2026 row; ``"2"`` QB KC ``Inactive``, on roster 2's IR,
unmapped; ``"3"`` QB, no team, free agent; ``"4"`` QB CIN free agent,
mapped to ``G4`` with only a 2025 row; ``"SEA"`` DEF. For season 2026 the
reasons are ``"1"`` ``ok``, ``"2"`` ``no_crosswalk`` (rostered, so his
status does not exclude him), ``"3"`` ``no_nfl_team``, ``"4"``
``crosswalk_but_no_stats_yet``, ``"SEA"`` ``team_unit`` (not in the
universe, since the league starts no ``DEF``, but still a team unit).

Reverse audit: :func:`build_reverse_coverage_audit`
--------------------------------------------------------------------------

The other direction: every nflverse player at a fantasy position
(``QB``/``RB``/``WR``/``TE``/``K``, with ``FB`` counted as ``RB``) who has
at least one row in the season but whose ``gsis_id`` maps to no Sleeper
id. That is real production no Sleeper player -- rostered or free agent --
can ever be credited with. Each row sums the player's
league-scored ``fantasy_points`` and counts his *active* player-weeks
(at least one target, carry, pass attempt or kick attempt), and carries
``points_rank``, his rank by fantasy points among **all** fantasy-position
nflverse players that season (mapped or not; ties share the best rank), so
an unmapped top-100 scorer is one filter away.

Regular season vs. playoffs
--------------------------------------------------------------------------

Both audits read regular-season rows only when ``season_type`` is present,
matching :func:`~fantasy_analyzer.players.ros_backtest.build_scored_player_weeks`.
Neither is phase-aware beyond that: coverage is a property of ids, not of
fantasy weeks.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from fantasy_analyzer.players.crosswalk import (
    gsis_to_sleeper_lookup,
    sleeper_to_gsis_lookup,
    standardize_nflverse_identity,
)
from fantasy_analyzer.players.free_agents import (
    DEFAULT_EXCLUDED_STATUSES,
    build_player_universe,
    catalog_display_name,
    has_nfl_team,
    resolve_startable_positions,
)
from fantasy_analyzer.players.scoring import calculate_fantasy_points

#: Sleeper catalog positions the forward audit scans (rostered players at
#: any other position are added regardless).
AUDIT_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

#: Every ``coverage_reason`` value, in precedence order. See the module
#: docstring's table for each definition.
COVERAGE_REASONS = (
    "not_in_catalog",
    "team_unit",
    "position_not_started",
    "excluded_status",
    "no_nfl_team",
    "no_crosswalk",
    "crosswalk_no_stats_any_season",
    "crosswalk_but_no_stats_yet",
    "ok",
)

#: The reasons that keep a free agent out of the universe.
EXCLUDED_REASONS = frozenset({"position_not_started", "excluded_status", "no_nfl_team"})

#: Column order for :func:`build_forward_coverage_audit`.
FORWARD_AUDIT_COLUMNS = [
    "sleeper_player_id",
    "full_name",
    "position",
    "team",
    "status",
    "injury_status",
    "is_rostered",
    "roster_id",
    "in_universe",
    "gsis_id",
    "has_current_season_stats",
    "current_season_games",
    "has_prior_season_stats",
    "prior_season_games",
    "coverage_reason",
]

#: Column order for :func:`build_reverse_coverage_audit`.
REVERSE_AUDIT_COLUMNS = [
    "gsis_id",
    "player_name",
    "position",
    "nfl_team",
    "player_weeks",
    "active_player_weeks",
    "targets",
    "carries",
    "pass_attempts",
    "kick_attempts",
    "fantasy_points",
    "points_rank",
]

#: Kicking columns summed into ``kick_attempts``. Present in both the raw
#: nflverse shape and the provider's normalized one (``fg_att``/``pat_att``
#: exist only in the raw shape).
_KICK_COLUMNS = (
    "fg_made_0_19",
    "fg_made_20_29",
    "fg_made_30_39",
    "fg_made_40_49",
    "fg_made_50_59",
    "fg_made_60_",
    "fg_missed",
    "pat_made",
    "pat_missed",
)


def _regular_season(stats: pd.DataFrame) -> pd.DataFrame:
    """Standardized identity columns, regular-season rows only when labeled."""
    frame = standardize_nflverse_identity(stats)
    if "season_type" in frame.columns:
        frame = frame[frame["season_type"] == "REG"]
    return frame


def _games_by_gsis(frame: pd.DataFrame, season: int) -> dict[str, int]:
    """Distinct weeks with a row, per ``gsis_id``, in one season."""
    seasonal = frame[
        (pd.to_numeric(frame["season"], errors="coerce") == season)
        & frame["gsis_id"].notna()
    ]
    if seasonal.empty:
        return {}
    counts = seasonal.drop_duplicates(subset=["gsis_id", "week"]).groupby("gsis_id")
    return {str(gsis_id): int(size) for gsis_id, size in counts.size().items()}


def _coverage_reason(
    *,
    in_catalog: bool,
    position: object,
    is_rostered: bool,
    startable: bool,
    excluded_status: bool,
    has_team: bool,
    gsis_id: object,
    current_games: int,
    prior_games: int,
) -> str:
    """Apply the module docstring's precedence table to one player."""
    if not in_catalog:
        return "not_in_catalog"
    if position == "DEF":
        return "team_unit"
    if not is_rostered:
        if not startable:
            return "position_not_started"
        if excluded_status:
            return "excluded_status"
        if not has_team:
            return "no_nfl_team"
    if gsis_id is None:
        return "no_crosswalk"
    if current_games == 0 and prior_games == 0:
        return "crosswalk_no_stats_any_season"
    if current_games == 0:
        return "crosswalk_but_no_stats_yet"
    return "ok"


def build_forward_coverage_audit(
    player_catalog: dict,
    raw_rosters: list[dict],
    roster_positions: list[str],
    crosswalk: pd.DataFrame,
    nflverse_stats: pd.DataFrame,
    season: int,
) -> pd.DataFrame:
    """Explain, for every Sleeper player in scope, whether and how he is covered.

    See the module docstring's "Forward audit" section for the scope, the
    ``coverage_reason`` definitions and precedence, and a toy example.

    Args:
        player_catalog: The raw Sleeper player catalog dict.
        raw_rosters: One league's raw roster dicts
            (``SleeperClient.get_rosters(league_id)``).
        roster_positions: That league's roster-slot list.
        crosswalk: A
            :data:`~fantasy_analyzer.players.crosswalk.CROSSWALK_COLUMNS`-shaped
            crosswalk (e.g. from
            :func:`~fantasy_analyzer.players.crosswalk.build_robust_id_crosswalk`).
        nflverse_stats: nflverse player-week stats covering ``season`` and
            ``season - 1``, raw or provider-normalized shape. Other seasons
            are ignored.
        season: The current season. ``season - 1`` is the prior.

    Returns:
        A DataFrame with columns :data:`FORWARD_AUDIT_COLUMNS`, one row per
        player: catalog players in catalog iteration order, then rostered
        ids missing from the catalog in sorted order. ``roster_id`` is
        nullable ``Int64``; the game counts are ``int``; ``gsis_id`` is
        ``None`` when unmapped.
    """
    universe = build_player_universe(
        raw_rosters, player_catalog, roster_positions, crosswalk=crosswalk
    )
    universe_by_id = universe.set_index("player_id", drop=False)
    rostered = universe[universe["is_rostered"]]
    roster_of = dict(zip(rostered["player_id"], rostered["roster_id"]))

    startable_positions = resolve_startable_positions(roster_positions)
    gsis_by_sleeper_id = (
        sleeper_to_gsis_lookup(crosswalk)
        if crosswalk is not None and not crosswalk.empty
        else {}
    )

    stats = _regular_season(nflverse_stats) if nflverse_stats is not None else None
    current = _games_by_gsis(stats, season) if stats is not None else {}
    prior = _games_by_gsis(stats, season - 1) if stats is not None else {}

    scope: list[str] = [
        player_id
        for player_id, player in player_catalog.items()
        if isinstance(player, dict)
        and (player.get("position") in AUDIT_POSITIONS or player_id in roster_of)
    ]
    uncataloged = sorted(set(roster_of) - set(scope))

    rows = []
    for player_id in scope + uncataloged:
        player = player_catalog.get(player_id)
        in_catalog = isinstance(player, dict)
        player = player if in_catalog else {}
        in_universe = player_id in universe_by_id.index
        known = universe_by_id.loc[player_id] if in_universe else None

        gsis_id = gsis_by_sleeper_id.get(player_id)
        if gsis_id is None and known is not None and isinstance(known["gsis_id"], str):
            gsis_id = known["gsis_id"]
        position = player.get("position") if in_catalog else known["position"]
        is_rostered = player_id in roster_of
        current_games = current.get(str(gsis_id), 0) if gsis_id else 0
        prior_games = prior.get(str(gsis_id), 0) if gsis_id else 0

        reason = _coverage_reason(
            in_catalog=in_catalog,
            position=position,
            is_rostered=is_rostered,
            startable=position in startable_positions,
            excluded_status=isinstance(player.get("status"), str)
            and player["status"].strip().lower() in DEFAULT_EXCLUDED_STATUSES,
            has_team=has_nfl_team(player_id, player),
            gsis_id=gsis_id,
            current_games=current_games,
            prior_games=prior_games,
        )

        rows.append(
            {
                "sleeper_player_id": player_id,
                "full_name": (
                    catalog_display_name(player) if in_catalog else known["full_name"]
                ),
                "position": position,
                "team": player.get("team") if in_catalog else known["team"],
                "status": player.get("status"),
                "injury_status": player.get("injury_status"),
                "is_rostered": is_rostered,
                "roster_id": roster_of.get(player_id),
                "in_universe": in_universe,
                "gsis_id": gsis_id,
                "has_current_season_stats": current_games > 0,
                "current_season_games": current_games,
                "has_prior_season_stats": prior_games > 0,
                "prior_season_games": prior_games,
                "coverage_reason": reason,
            }
        )

    audit = pd.DataFrame(rows, columns=FORWARD_AUDIT_COLUMNS)
    for column in (
        "is_rostered",
        "in_universe",
        "has_current_season_stats",
        "has_prior_season_stats",
    ):
        audit[column] = audit[column].astype(bool)
    for column in ("current_season_games", "prior_season_games"):
        audit[column] = audit[column].astype("int64")
    audit["roster_id"] = audit["roster_id"].astype("Int64")
    return audit


def build_reverse_coverage_audit(
    nflverse_stats: pd.DataFrame,
    crosswalk: pd.DataFrame,
    season: int,
    scoring_settings: Mapping[str, float],
) -> pd.DataFrame:
    """List nflverse players with production that maps to no Sleeper id.

    See the module docstring's "Reverse audit" section.

    Args:
        nflverse_stats: nflverse player-week stats, raw or
            provider-normalized shape. Only ``season`` is read.
        crosswalk: A
            :data:`~fantasy_analyzer.players.crosswalk.CROSSWALK_COLUMNS`-shaped
            crosswalk.
        season: The season to audit.
        scoring_settings: A league's Sleeper scoring settings, applied via
            :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`
            -- so kickers score, which nflverse's own ``fantasy_points``
            columns do not do.

    Returns:
        A DataFrame with columns :data:`REVERSE_AUDIT_COLUMNS`, one row per
        unmapped fantasy-position nflverse player with at least one row in
        ``season``; name/position/team from his latest row, ``position`` in
        Sleeper's vocabulary. ``fantasy_points`` sums every row, active or
        not. Sorted by ``fantasy_points`` descending, then ``gsis_id``.
        Empty (same columns) when everything maps. Rows with no
        ``gsis_id`` (nflverse's team placeholder rows) are ignored.
    """
    empty = pd.DataFrame(columns=REVERSE_AUDIT_COLUMNS)
    if nflverse_stats is None or nflverse_stats.empty:
        return empty

    frame = _regular_season(nflverse_stats)
    frame = frame[
        (pd.to_numeric(frame["season"], errors="coerce") == season)
        & frame["gsis_id"].notna()
        & frame["fantasy_position"].apply(lambda value: isinstance(value, str))
    ]
    if frame.empty:
        return empty

    frame = calculate_fantasy_points(frame, scoring_settings).points_df

    def _column(name: str) -> pd.Series:
        if name not in frame.columns:
            return pd.Series(0.0, index=frame.index)
        return pd.to_numeric(frame[name], errors="coerce").fillna(0.0)

    frame = frame.assign(
        _targets=_column("targets"),
        _carries=_column("carries"),
        _pass_attempts=_column("attempts"),
        _kick_attempts=sum(
            (_column(name) for name in _KICK_COLUMNS),
            start=pd.Series(0.0, index=frame.index),
        ),
    )
    frame["_active"] = (
        frame[["_targets", "_carries", "_pass_attempts", "_kick_attempts"]].sum(axis=1)
        > 0
    )
    frame["gsis_id"] = frame["gsis_id"].astype(str)
    frame["_week"] = pd.to_numeric(frame["week"], errors="coerce")

    totals = frame.groupby("gsis_id").agg(
        player_weeks=("_week", "nunique"),
        active_player_weeks=("_active", "sum"),
        targets=("_targets", "sum"),
        carries=("_carries", "sum"),
        pass_attempts=("_pass_attempts", "sum"),
        kick_attempts=("_kick_attempts", "sum"),
        fantasy_points=("fantasy_points", "sum"),
    )
    totals["points_rank"] = (
        totals["fantasy_points"].rank(method="min", ascending=False).astype("int64")
    )

    latest = frame.sort_values("_week", kind="mergesort").drop_duplicates(
        subset="gsis_id", keep="last"
    )
    identity = latest.set_index("gsis_id")[
        ["player_name", "fantasy_position", "nfl_team"]
    ].rename(columns={"fantasy_position": "position"})
    totals = totals.join(identity)

    mapped = (
        set(gsis_to_sleeper_lookup(crosswalk))
        if crosswalk is not None and not crosswalk.empty
        else set()
    )
    unmapped = totals[~totals.index.isin(mapped)].reset_index()
    if unmapped.empty:
        return empty

    unmapped = unmapped.sort_values(
        ["fantasy_points", "gsis_id"], ascending=[False, True], kind="mergesort"
    )
    for column in ("player_weeks", "active_player_weeks"):
        unmapped[column] = unmapped[column].astype("int64")
    return unmapped[REVERSE_AUDIT_COLUMNS].reset_index(drop=True)
