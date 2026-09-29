"""Season-long, week-by-week analysis for a single player (or every player).

A thin composition script over the existing package -- it defines no new
metrics and performs no normalization of its own. It wires together the
pieces Epic 7 already provides:

    SleeperClient                     (network access)
        -> load_league_snapshot       FFA-013
        -> derive_season_boundaries   FFA-022
        -> load_season_matchups       FFA-030
        -> build_robust_id_crosswalk  FFA-062 (DynastyProcess + Sleeper catalog)
        -> NflverseWeeklyStatsProvider FFA-061
        -> build_player_week_fact_table FFA-064   (week-by-week grain)
        -> build_player_analytics     FFA-071     (season grain + value)

Two modes:

``--player NAME``
    One player's full season: the season line (FFA-065), the
    replacement-level value line (FFA-068), and the week-by-week game log
    from the fact table (FFA-064).

no ``--player``
    The league-wide season leaderboard, so you can find the name/id to
    drill into.

Examples::

    # discover a league_id
    python scripts/player_analysis.py --username schneidbaby --list-leagues

    # season leaderboard, running backs only
    python scripts/player_analysis.py --league-id 123456 --position RB --top 20

    # one player, week by week
    python scripts/player_analysis.py --league-id 123456 --player "Josh Allen"

Network: hits Sleeper once per league/week and nflverse once per season.
Both are cached under ``.cache/`` (see ``sleeper/cache.py`` and
``players/nflverse_cache.py``), so repeat runs are cheap.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from fantasy_analyzer.league.season import derive_season_boundaries
from fantasy_analyzer.league.snapshot import load_league_snapshot
from fantasy_analyzer.matchups.loader import load_season_matchups
from fantasy_analyzer.players.crosswalk import build_robust_id_crosswalk
from fantasy_analyzer.players.lineup_efficiency import START_SLOT_ELIGIBILITY
from fantasy_analyzer.players.nflverse_provider import NflverseWeeklyStatsProvider
from fantasy_analyzer.players.performance import BOOM_BUST_THRESHOLD_STDEVS
from fantasy_analyzer.players.player_analytics import (
    PlayerAnalytics,
    build_player_analytics,
)
from fantasy_analyzer.players.player_week import (
    PLAYER_WEEK_COLUMNS,
    build_league_wide_player_week_fact_table,
    build_player_week_fact_table,
)
from fantasy_analyzer.sleeper.cache import get_players_cached
from fantasy_analyzer.sleeper.client import SleeperClient
from fantasy_analyzer.sleeper.exceptions import SleeperAPIError

#: Stat columns worth printing in a game log, per position. Any column not
#: present in the provider's output (or entirely empty for this player) is
#: dropped before printing, so a short list here is safe.
GAME_LOG_STATS_BY_POSITION = {
    "QB": [
        "completions",
        "attempts",
        "passing_yards",
        "passing_tds",
        "passing_interceptions",
        "carries",
        "rushing_yards",
        "rushing_tds",
    ],
    "RB": [
        "carries",
        "rushing_yards",
        "rushing_tds",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
    ],
    "WR": [
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "carries",
        "rushing_yards",
        "rushing_tds",
    ],
    "TE": ["targets", "receptions", "receiving_yards", "receiving_tds"],
    "K": [
        "fg_made_0_19",
        "fg_made_20_29",
        "fg_made_30_39",
        "fg_made_40_49",
        "fg_made_50_59",
        "fg_made_60_",
        "fg_missed",
        "pat_made",
        "pat_missed",
    ],
}


def fantasy_relevant_positions(roster_positions: list[str]) -> set[str]:
    """The player positions a league's roster slots can actually start.

    :func:`~fantasy_analyzer.players.player_week.build_league_wide_player_week_fact_table`
    pulls in every player the provider has stats for that week -- which,
    for a standard (non-IDP) league, includes a large number of positions
    no roster slot can ever start (offensive linemen, corners, long
    snappers, ...; nflverse tracks incidental stat categories for them, e.g.
    a lineman's fumble recovery). Those positions are real but irrelevant to
    a standard league's replacement-level computation, and worse: because
    real NFL rosters carry very few players at some of them (e.g. only a
    handful of true fullbacks league-wide), the resulting tiny comparison
    pool can produce wildly inflated VORP/scarcity numbers for whichever of
    those players happen to have recorded stats -- discovered directly while
    diagnosing a ranking-quality bug: several fullbacks with 1-3 points per
    game were outranking legitimate starters purely because ``FB`` had a
    6-player, near-zero-baseline pool.

    Args:
        roster_positions: The league's ordered roster-slot list (e.g.
            ``LeagueSnapshot.roster_positions``).

    Returns:
        The union, over every non-bench slot, of
        :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`'s
        eligible positions for that slot. A slot label not in that mapping
        (a raw IDP slot like ``DL``/``LB``/``DB`` some leagues use, or any
        other label this codebase has no bespoke eligibility rule for) is
        assumed to accept players of its own literal position label -- a
        permissive fallback so an IDP league still gets its own starting
        positions counted rather than silently excluded. ``BN``/``IR``
        contribute nothing (a bench slot starts no position).
    """
    positions: set[str] = set()
    for slot in roster_positions:
        if slot in ("BN", "IR"):
            continue
        eligible = START_SLOT_ELIGIBILITY.get(slot)
        if eligible:
            positions.update(eligible)
        else:
            positions.add(slot)
    return positions


def resolve_league_id(
    client: SleeperClient,
    username: Optional[str],
    league_id: Optional[str],
    season: int,
) -> str:
    """Resolve a ``league_id``, either passed directly or via a username.

    Args:
        client: A configured ``SleeperClient``.
        username: Sleeper username to look up leagues for. Ignored when
            ``league_id`` is given.
        league_id: An explicit Sleeper league_id, used as-is when present.
        season: Season year used for the username lookup.

    Returns:
        The resolved league_id.

    Raises:
        ValueError: If neither argument was supplied, the user has no
            leagues for ``season``, or the user has more than one (in which
            case the candidates are listed so the caller can pick one).
    """
    if league_id:
        return league_id
    if not username:
        raise ValueError("pass either --league-id or --username.")

    user = client.get_user(username)
    leagues = client.get_leagues(user_id=user["user_id"], season=season)
    if not leagues:
        raise ValueError(f"{username} has no leagues for season {season}.")
    if len(leagues) > 1:
        listing = "\n".join(
            f"  {league.get('league_id')}  {league.get('name')}" for league in leagues
        )
        raise ValueError(
            f"{username} has {len(leagues)} leagues in {season}; "
            f"re-run with --league-id:\n{listing}"
        )
    return leagues[0]["league_id"]


def list_leagues(client: SleeperClient, username: str, season: int) -> str:
    """Format a username's leagues for a season as a plain-text table."""
    user = client.get_user(username)
    leagues = client.get_leagues(user_id=user["user_id"], season=season)
    if not leagues:
        return f"No leagues found for {username} in {season}."
    rows = [
        {
            "league_id": league.get("league_id"),
            "name": league.get("name"),
            "status": league.get("status"),
        }
        for league in leagues
    ]
    return pd.DataFrame(rows).to_string(index=False)


def load_analytics(
    client: SleeperClient,
    league_id: str,
    total_weeks: int,
    phase: str,
    force_refresh_stats: bool = False,
    include_free_agents: bool = False,
) -> tuple[PlayerAnalytics, list[str]]:
    """Build a ``PlayerAnalytics`` for one league-season, filtered to ``phase``.

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league to analyze.
        total_weeks: Total weeks in the fantasy season (18 for 2025).
        phase: ``"regular"``, ``"playoffs"``, or ``"all"``. Applied by
            selecting weeks from the league's ``SeasonBoundaries`` before
            the fact table is built, per FFA-071's "callers pre-filter to
            the phase they want" contract.
        force_refresh_stats: Re-download the nflverse season table instead
            of reading the local cache. Also re-downloads DynastyProcess's ID
            crosswalk (see ``build_robust_id_crosswalk``) rather than reading
            its cache -- both are "get fresh data" in one flag.
        include_free_agents: If ``True``, build the fact table with
            :func:`~fantasy_analyzer.players.player_week.build_league_wide_player_week_fact_table`
            instead of the rostered-only
            :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`,
            so every player the provider has stats for that week is a
            candidate row -- not just players someone in this league
            rostered. This changes ``replacement_ppg`` and every VORP/rank
            built on it (FFA-068, FFA-073): the replacement baseline is then
            drawn from the true league-wide pool instead of clamping to this
            league's worst rostered player at a thin position. Default
            ``False`` preserves the original rostered-only behavior.

    Returns:
        ``(analytics, unsupported_scoring_keys)``. The second element is
        FFA-064's diagnostic: scoring rules the engine could not map to a
        stat column, meaning ``fantasy_points`` is missing those
        contributions. Empty when every rule was applied.

    Raises:
        ValueError: If ``phase`` selects no weeks (e.g. ``playoffs`` for a
            league whose settings define no playoff start).
    """
    snapshot = load_league_snapshot(client, league_id)
    boundaries = derive_season_boundaries(snapshot.league, total_weeks=total_weeks)

    weeks = load_season_matchups(
        client, league_id, boundaries, season=snapshot.league.season
    )
    if phase == "regular":
        weeks = [week for week in weeks if not week.is_playoff]
    elif phase == "playoffs":
        weeks = [week for week in weeks if week.is_playoff]
    if not weeks:
        raise ValueError(f"no {phase} weeks found for league {league_id}.")

    catalog = get_players_cached(client)
    provider = NflverseWeeklyStatsProvider(
        id_crosswalk=build_robust_id_crosswalk(
            catalog, force_refresh_ids=force_refresh_stats
        ),
        force_refresh=force_refresh_stats,
    )

    builder = (
        build_league_wide_player_week_fact_table
        if include_free_agents
        else build_player_week_fact_table
    )
    fact_table = builder(
        weeks=weeks,
        teams_df=snapshot.teams_df,
        players_df=snapshot.players_df,
        provider=provider,
        scoring_settings=snapshot.scoring_settings,
    )

    player_week_df = fact_table.player_week_df
    if include_free_agents:
        # See fantasy_relevant_positions's docstring: the league-wide fact
        # table otherwise pulls in every position nflverse tracks incidental
        # stats for (linemen, corners, long snappers, ...), and a handful of
        # them (fullback especially) have such a tiny real-NFL population
        # that their replacement-level baseline collapses to near zero,
        # inflating VORP/scarcity for anyone at that position who has any
        # recorded stat at all.
        allowed_positions = fantasy_relevant_positions(snapshot.roster_positions)
        player_week_df = player_week_df[
            player_week_df["position"].isin(allowed_positions)
        ]

    analytics = build_player_analytics(
        player_week_df,
        roster_positions=snapshot.roster_positions,
        num_teams=snapshot.league.total_rosters,
    )
    return analytics, fact_table.unsupported_scoring_keys


def find_player(season_df: pd.DataFrame, query: str) -> pd.Series:
    """Resolve a name or Sleeper player_id to exactly one season row.

    Matching is: exact ``sleeper_player_id`` first, then a case-insensitive
    substring match on ``player_name``.

    Args:
        season_df: ``PlayerAnalytics.player_season_df``.
        query: A player name (or fragment) or a Sleeper player_id.

    Returns:
        The single matching row.

    Raises:
        ValueError: If nothing matched, or if more than one player did (the
            candidates are listed so the caller can be more specific).
    """
    by_id = season_df[season_df["sleeper_player_id"].astype(str) == query]
    if len(by_id) == 1:
        return by_id.iloc[0]

    names = season_df["player_name"].fillna("")
    matches = season_df[names.str.contains(query, case=False, regex=False)]
    if matches.empty:
        raise ValueError(
            f"no rostered player matched {query!r}. "
            "Run without --player to see the leaderboard; note the fact "
            "table only covers players rostered in this league."
        )
    if len(matches) > 1:
        listing = "\n".join(
            f"  {row.sleeper_player_id:>8}  {row.player_name}  ({row.position})"
            for row in matches.itertuples()
        )
        raise ValueError(f"{query!r} matched {len(matches)} players:\n{listing}")
    return matches.iloc[0]


def build_game_log(
    weekly_df: pd.DataFrame, player_id: str, position: Optional[str]
) -> pd.DataFrame:
    """Build the printable week-by-week log for one player.

    Adds a ``played`` column using FFA-065's own rule -- a week counts as a
    game played only if at least one raw provider stat column is non-null,
    where "raw stat column" means any column that is neither in
    ``PLAYER_WEEK_COLUMNS`` nor ``fantasy_points``. This is evaluated over
    the full fact table's stat columns, not just the ones displayed, so
    ``played`` agrees exactly with the season row's ``games_played``.

    Args:
        weekly_df: ``PlayerAnalytics.player_weekly_df`` (FFA-064's fact
            table): one row per (week, roster, rostered player).
        player_id: The Sleeper player_id to filter to.
        position: The player's position, used only to choose which stat
            columns to display.

    Returns:
        A week-ordered frame with roster context, ``played``, the
        position's relevant stat columns (any that are entirely empty are
        dropped), and ``fantasy_points``. Empty if the player has no rows.
    """
    rows = weekly_df[weekly_df["sleeper_player_id"].astype(str) == str(player_id)]
    if rows.empty:
        return rows

    excluded = set(PLAYER_WEEK_COLUMNS) | {"fantasy_points"}
    stat_columns = [column for column in weekly_df.columns if column not in excluded]
    played = (
        rows[stat_columns].notna().any(axis=1)
        if stat_columns
        else pd.Series(False, index=rows.index)
    )

    context = [
        column
        for column in ["week", "fantasy_team", "nfl_team", "started"]
        if column in rows.columns
    ]
    stats = [
        column
        for column in GAME_LOG_STATS_BY_POSITION.get(str(position), [])
        if column in rows.columns and rows[column].notna().any()
    ]
    log = rows[context + stats + ["fantasy_points"]].assign(played=played)
    log = log[context + ["played"] + stats + ["fantasy_points"]]
    return log.sort_values("week").reset_index(drop=True)


def annotate_boom_bust(
    log: pd.DataFrame, season_row: pd.Series, threshold: float
) -> pd.DataFrame:
    """Tag each logged week ``BOOM``/``BUST``/``DNP``/``""`` using FFA-065's rule.

    Reuses ``performance.py``'s definition exactly -- strict inequality
    against ``points_per_game +/- threshold * stdev_points``, where those
    two values come from the player's own season row, and only over weeks
    that count as games played. This adds no new methodology; it only shows
    per-week which games produced the season row's
    ``boom_games``/``bust_games`` counts, so the flags in this column sum to
    exactly those two numbers.

    Args:
        log: The output of :func:`build_game_log`, including its ``played``
            column.
        season_row: That player's ``player_season_df`` row.
        threshold: Boom/bust threshold in the player's own standard
            deviations (the same value used to build ``season_row``).

    Returns:
        ``log`` with a trailing ``flag`` column; a non-played week is always
        ``DNP``, never a bust, since it contributed nothing to the season
        row. Returned unchanged when ``stdev_points`` is undefined (fewer
        than ``MIN_GAMES_FOR_DISPERSION`` qualifying games), since no
        threshold exists to compare against.
    """
    mean = season_row.get("points_per_game")
    stdev = season_row.get("stdev_points")
    if log.empty or pd.isna(mean) or pd.isna(stdev):
        return log

    high = mean + threshold * stdev
    low = mean - threshold * stdev

    def classify(points: float, played: bool) -> str:
        if not played:
            return "DNP"
        if points > high:
            return "BOOM"
        if points < low:
            return "BUST"
        return ""

    flags = [
        classify(points, played)
        for points, played in zip(log["fantasy_points"], log["played"])
    ]
    return log.assign(flag=flags)


def format_player_report(
    analytics: PlayerAnalytics, query: str, threshold: float
) -> str:
    """Format one player's whole-season report.

    Args:
        analytics: A built ``PlayerAnalytics`` for the league-season.
        query: Player name fragment or Sleeper player_id.
        threshold: Boom/bust threshold used for the per-week flags.

    Returns:
        A plain-text report: header, season line (FFA-065), value line
        (FFA-068), and the annotated game log (FFA-064).

    Raises:
        ValueError: Propagated from :func:`find_player` when the query does
            not resolve to exactly one player.
    """
    season_row = find_player(analytics.player_season_df, query)
    player_id = season_row["sleeper_player_id"]

    log = build_game_log(analytics.player_weekly_df, player_id, season_row["position"])
    log = annotate_boom_bust(log, season_row, threshold)

    season_line = season_row.drop(
        labels=["sleeper_player_id", "player_name", "position", "nfl_team"],
        errors="ignore",
    )

    value_df = analytics.player_value_df
    value_row = value_df[value_df["sleeper_player_id"] == player_id]
    value_line = (
        value_row.iloc[0][
            [
                "position_players",
                "position_mean_ppg",
                "ppg_above_position_average",
                "replacement_ppg",
                "ppg_above_replacement",
                "points_above_replacement",
                "value_rank",
            ]
        ]
        if not value_row.empty
        else None
    )

    teams = sorted(
        {
            str(team)
            for team in analytics.player_weekly_df.loc[
                analytics.player_weekly_df["sleeper_player_id"] == player_id,
                "fantasy_team",
            ].dropna()
        }
    )

    sections = [
        f"{season_row['player_name']} -- {season_row['position']} "
        f"({season_row['nfl_team']}) -- season {season_row['season']}",
        f"sleeper_player_id: {player_id}",
        f"rostered by: {', '.join(teams) if teams else '(unknown)'}",
        "",
        "Season line (FFA-065):",
        season_line.to_string(),
    ]
    if value_line is not None:
        sections += [
            "",
            f"Value vs. replacement (FFA-068), among {season_row['position']}s:",
            value_line.to_string(),
        ]
    sections += [
        "",
        f"Game log (flag = boom/bust at {threshold} of this player's own stdev):",
        log.to_string(index=False) if not log.empty else "  (no weeks)",
    ]
    return "\n".join(sections)


def format_leaderboard(
    analytics: PlayerAnalytics,
    position: Optional[str],
    min_games: int,
    top: int,
    sort_by: str,
) -> str:
    """Format the league-wide season leaderboard.

    Args:
        analytics: A built ``PlayerAnalytics`` for the league-season.
        position: Restrict to one position (e.g. ``"RB"``), or ``None``.
        min_games: Drop players with fewer qualifying games.
        top: Print at most this many rows.
        sort_by: Column to sort descending by, e.g. ``"total_points"``.

    Returns:
        A plain-text table, or a message when the filters match nothing.
    """
    frame = analytics.player_value_df
    if position:
        frame = frame[frame["position"].astype(str).str.upper() == position.upper()]
    frame = frame[frame["games_played"] >= min_games]
    if frame.empty:
        return "No players matched those filters."

    columns = [
        "player_name",
        "position",
        "nfl_team",
        "games_played",
        "total_points",
        "points_per_game",
        "replacement_ppg",
        "points_above_replacement",
        "value_rank",
    ]
    frame = frame.sort_values(sort_by, ascending=False).head(top)
    return frame[columns].to_string(index=False)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the script's argument parser."""
    parser = argparse.ArgumentParser(
        prog="player_analysis.py",
        description="Week-by-week and whole-season analysis for rostered players.",
    )
    parser.add_argument("--league-id", help="Sleeper league_id to analyze.")
    parser.add_argument("--username", help="Sleeper username (used to find a league).")
    parser.add_argument(
        "--season", type=int, default=2025, help="Season year (default: 2025)."
    )
    parser.add_argument(
        "--total-weeks",
        type=int,
        default=18,
        help="Total weeks in the fantasy season (default: 18).",
    )
    parser.add_argument(
        "--phase",
        choices=["regular", "playoffs", "all"],
        default="regular",
        help="Which weeks to include (default: regular).",
    )
    parser.add_argument("--player", help="Player name fragment or sleeper_player_id.")
    parser.add_argument("--position", help="Leaderboard: restrict to one position.")
    parser.add_argument(
        "--min-games",
        type=int,
        default=1,
        help="Leaderboard: minimum qualifying games (default: 1).",
    )
    parser.add_argument(
        "--top", type=int, default=25, help="Leaderboard: row limit (default: 25)."
    )
    parser.add_argument(
        "--sort-by",
        default="total_points",
        help="Leaderboard: sort column (default: total_points).",
    )
    parser.add_argument(
        "--boom-bust-threshold",
        type=float,
        default=BOOM_BUST_THRESHOLD_STDEVS,
        help=f"Boom/bust stdevs (default: {BOOM_BUST_THRESHOLD_STDEVS}).",
    )
    parser.add_argument(
        "--list-leagues",
        action="store_true",
        help="Just list --username's leagues for --season and exit.",
    )
    parser.add_argument(
        "--csv-dir",
        help="Also write player_weekly/player_season/player_value CSVs here.",
    )
    parser.add_argument(
        "--force-refresh-stats",
        action="store_true",
        help="Re-download the nflverse season table instead of using the cache.",
    )
    parser.add_argument(
        "--include-free-agents",
        action="store_true",
        help=(
            "Score every player the provider has stats for that week, not just "
            "players this league rostered -- changes replacement_ppg and every "
            "VORP/ranking built on it (see load_analytics's docstring)."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point.

    Returns:
        ``0`` on success; ``1`` if Sleeper failed or the arguments could not
        be resolved to a league or a single player.
    """
    args = build_arg_parser().parse_args(argv)
    client = SleeperClient()

    try:
        if args.list_leagues:
            if not args.username:
                raise ValueError("--list-leagues requires --username.")
            print(list_leagues(client, args.username, args.season))
            return 0

        league_id = resolve_league_id(
            client, args.username, args.league_id, args.season
        )
        analytics, unsupported = load_analytics(
            client,
            league_id,
            total_weeks=args.total_weeks,
            phase=args.phase,
            force_refresh_stats=args.force_refresh_stats,
            include_free_agents=args.include_free_agents,
        )

        if unsupported:
            print(
                "WARNING: fantasy_points omits these unmapped scoring rules: "
                + ", ".join(unsupported),
                file=sys.stderr,
            )

        if args.csv_dir:
            out = Path(args.csv_dir)
            out.mkdir(parents=True, exist_ok=True)
            analytics.player_weekly_df.to_csv(out / "player_weekly.csv", index=False)
            analytics.player_season_df.to_csv(out / "player_season.csv", index=False)
            analytics.player_value_df.to_csv(out / "player_value.csv", index=False)
            print(f"Wrote CSVs to {out}/", file=sys.stderr)

        if args.player:
            print(
                format_player_report(analytics, args.player, args.boom_bust_threshold)
            )
        else:
            print(
                format_leaderboard(
                    analytics,
                    position=args.position,
                    min_games=args.min_games,
                    top=args.top,
                    sort_by=args.sort_by,
                )
            )
    except (SleeperAPIError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
