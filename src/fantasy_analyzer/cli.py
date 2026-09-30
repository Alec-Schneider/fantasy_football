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

It also wires up a ``commentary`` subcommand (FFA-093/FFA-094) over
``commentary/context.py`` (FFA-090/FFA-091), ``commentary/prompts.py``
(FFA-092), and ``commentary/client.py`` (FFA-094):

- ``commentary matchups <league_id> --week <n>`` -- print a ready-to-paste
  prompt for a week's matchups (combined by default, or one prompt per
  matchup with ``--per-matchup``).
- ``commentary recap <league_id> --week <n>`` -- print a ready-to-paste
  prompt for the league-wide weekly recap.

By default neither ``commentary`` subcommand calls an LLM -- they only print
prompt text to stdout. Passing ``--generate`` sends the prompt(s) to the
Claude API (``commentary/client.py``, requiring ``ANTHROPIC_API_KEY`` in the
environment) and prints the generated commentary instead.

It also wires up a ``free-agents`` subcommand (FFA-093) over
``players/free_agents.py`` (FFA-091), ``players/ros_backtest.py`` (FFA-089),
``players/ros_projection.py`` (FFA-090), and ``players/waiver_rankings.py``
(FFA-092):

- ``free-agents <league_id> --season <year> --week <n>`` -- rank a league's
  current free agents by projected rest-of-season points above replacement,
  as of after week ``n``.

Table formatting (``_format_leagues_table`` / ``_format_league_summary`` /
``_format_free_agent_rankings``) and argument parsing (``build_arg_parser``)
are pure functions, independently testable without live HTTP.
``run_leagues``/``run_summary``/``run_commentary_matchups``/
``run_commentary_recap``/``run_free_agents`` take an injected
``SleeperClient`` so tests can mock HTTP responses via ``requests_mock``
against the same sanitized fixtures used elsewhere in the test suite, per
AGENTS.md's "no live API dependency in unit tests" rule. The two
``commentary`` runners and ``run_free_agents`` additionally take an
injectable ``provider``
(:class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`),
and the ``commentary`` runners also take a ``commentary_client``
(:class:`~fantasy_analyzer.commentary.client.CommentaryClient`), so tests can
supply in-memory fakes instead of the real nflverse-backed provider and the
real Anthropic-backed client -- see ``build_commentary_inputs`` and
``build_free_agent_rankings``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

import pandas as pd

from fantasy_analyzer.analytics.league_analytics import (
    LeagueAnalytics,
    build_league_analytics,
)
from fantasy_analyzer.analytics.standings import build_standings
from fantasy_analyzer.analytics.summary import LeagueSummaryView, build_league_summary
from fantasy_analyzer.commentary.client import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    CommentaryClient,
    CommentaryGenerationError,
)
from fantasy_analyzer.commentary.context import (
    build_league_week_context,
    build_matchup_context,
)
from fantasy_analyzer.commentary.prompts import (
    DEFAULT_TONE,
    combined_matchup_prompt,
    league_week_recap_prompt,
    weekly_matchup_prompt,
)
from fantasy_analyzer.league.season import derive_season_boundaries
from fantasy_analyzer.league.snapshot import LeagueSnapshot, load_league_snapshot
from fantasy_analyzer.matchups.loader import load_season_matchups
from fantasy_analyzer.matchups.outcomes import derive_season_outcomes
from fantasy_analyzer.matchups.pairing import pair_season_matchups
from fantasy_analyzer.matchups.season_matchups import build_season_matchup_df
from fantasy_analyzer.players.crosswalk import (
    build_id_crosswalk,
    build_robust_id_crosswalk,
)
from fantasy_analyzer.players.free_agents import build_free_agent_pool
from fantasy_analyzer.players.nflverse_provider import NflverseWeeklyStatsProvider
from fantasy_analyzer.players.player_week import build_player_week_fact_table
from fantasy_analyzer.players.provider import (
    PLAYER_WEEK_IDENTITY_COLUMNS,
    PlayerStatsProvider,
)
from fantasy_analyzer.players.ros_backtest import build_scored_player_weeks
from fantasy_analyzer.players.ros_projection import (
    DEFAULT_N0,
    ShrinkageParameters,
    load_shrinkage_parameters,
)
from fantasy_analyzer.players.usage import load_usage_player_weeks
from fantasy_analyzer.players.usage_projection import (
    UsageModelParameters,
    load_usage_model_parameters,
)
from fantasy_analyzer.players.waiver_rankings import build_waiver_wire_rankings
from fantasy_analyzer.sleeper.cache import get_players_cached
from fantasy_analyzer.sleeper.client import SleeperClient
from fantasy_analyzer.sleeper.exceptions import SleeperAPIError

#: NFL weeks a season's raw stats can occupy (1-18, the current NFL
#: regular-season length). ``run_free_agents``/``build_free_agent_rankings``
#: fetch every one of these for both the target season and its prior season
#: rather than tracking the "current NFL week" separately from the fantasy
#: cutoff week -- a real ``PlayerStatsProvider`` returns an empty frame for
#: a week with no data yet (see ``PlayerStatsProvider.weekly_stats``'s
#: contract), so over-fetching future weeks is harmless, and
#: ``build_free_agent_ros_projections``'s own ``cutoff_week`` filtering
#: (FFA-092) is what actually restricts "this season" to weeks already
#: played.
_NFL_SEASON_WEEKS = range(1, 19)


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

    commentary_parser = subparsers.add_parser(
        "commentary", help="Print an LLM-ready commentary prompt for a league week."
    )
    commentary_subparsers = commentary_parser.add_subparsers(
        dest="commentary_command", required=True
    )

    matchups_parser = commentary_subparsers.add_parser(
        "matchups", help="Print a prompt covering a week's matchups."
    )
    matchups_parser.add_argument("league_id", help="Sleeper league_id.")
    matchups_parser.add_argument(
        "--week", type=int, required=True, help="Week number to build the prompt for."
    )
    matchups_parser.add_argument(
        "--total-weeks",
        type=int,
        required=True,
        help="Total weeks in the fantasy season (e.g. 18 for the 2025 NFL season).",
    )
    matchups_parser.add_argument(
        "--tone",
        default=DEFAULT_TONE,
        help=(
            "Commentary tone, e.g. 'witty' or 'straightforward' "
            f"(default: {DEFAULT_TONE})."
        ),
    )
    matchups_parser.add_argument(
        "--per-matchup",
        action="store_true",
        help="Print one prompt per matchup instead of a single combined prompt.",
    )
    matchups_parser.add_argument(
        "--generate",
        action="store_true",
        help=(
            "Call the Claude API and print the generated commentary instead "
            "of the raw prompt (requires ANTHROPIC_API_KEY)."
        ),
    )
    matchups_parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Anthropic model ID for --generate (default: {DEFAULT_MODEL}).",
    )
    matchups_parser.add_argument(
        "--effort",
        default=DEFAULT_EFFORT,
        help=(
            "Anthropic output_config.effort for --generate, 'low' through "
            f"'max' (default: {DEFAULT_EFFORT})."
        ),
    )

    recap_parser = commentary_subparsers.add_parser(
        "recap", help="Print a prompt covering the league-wide weekly recap."
    )
    recap_parser.add_argument("league_id", help="Sleeper league_id.")
    recap_parser.add_argument(
        "--week", type=int, required=True, help="Week number to build the prompt for."
    )
    recap_parser.add_argument(
        "--total-weeks",
        type=int,
        required=True,
        help="Total weeks in the fantasy season (e.g. 18 for the 2025 NFL season).",
    )
    recap_parser.add_argument(
        "--tone",
        default=DEFAULT_TONE,
        help=(
            "Commentary tone, e.g. 'witty' or 'straightforward' "
            f"(default: {DEFAULT_TONE})."
        ),
    )
    recap_parser.add_argument(
        "--generate",
        action="store_true",
        help=(
            "Call the Claude API and print the generated commentary instead "
            "of the raw prompt (requires ANTHROPIC_API_KEY)."
        ),
    )
    recap_parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Anthropic model ID for --generate (default: {DEFAULT_MODEL}).",
    )
    recap_parser.add_argument(
        "--effort",
        default=DEFAULT_EFFORT,
        help=(
            "Anthropic output_config.effort for --generate, 'low' through "
            f"'max' (default: {DEFAULT_EFFORT})."
        ),
    )

    free_agents_parser = subparsers.add_parser(
        "free-agents",
        help="Rank a league's free agents by rest-of-season points above replacement.",
    )
    free_agents_parser.add_argument("league_id", help="Sleeper league_id.")
    free_agents_parser.add_argument(
        "--season",
        type=int,
        required=True,
        help="Season year to score nflverse data against, e.g. 2026.",
    )
    free_agents_parser.add_argument(
        "--week",
        type=int,
        required=True,
        help=(
            "Cutoff week: the last completed week, used to project rest of "
            "season from after this week."
        ),
    )
    free_agents_parser.add_argument(
        "--position",
        default=None,
        help="Filter to one position (e.g. WR). Omit to include every position.",
    )
    free_agents_parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of top-ranked free agents to print (default: 25).",
    )
    free_agents_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: a plain-text table, or JSON records (default: text).",
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


def _format_free_agent_rankings(
    rankings: pd.DataFrame,
    league_id: str,
    season: int,
    week: int,
    *,
    position: Optional[str] = None,
    format: str = "text",
) -> str:
    """Format a free-agent ranking DataFrame as text or JSON.

    Args:
        rankings: As returned by ``build_free_agent_rankings`` -- already
            filtered to ``position``/truncated to ``top``.
        league_id: The league the ranking was built for, for the header.
        season: The season scored, for the header.
        week: The cutoff week, for the header.
        position: The position filter applied, if any, for the header.
        format: ``"text"`` for a plain-text table, ``"json"`` for a
            structured JSON array of records. JSON is emitted with
            ``pandas.DataFrame.to_json(orient="records")`` (``NaN``/``None``
            serialize to ``null``, which is valid JSON, unlike
            ``json.dumps`` on a raw ``NaN`` float).

    Returns:
        The formatted string. For ``"text"``, a friendly "no free agents
        found" message (rather than an empty-table dump) when ``rankings``
        is empty.
    """
    if format == "json":
        return rankings.to_json(orient="records", indent=2)

    header = f"Free agents -- league {league_id}, season {season}, through week {week}"
    if position:
        header += f", position {position}"

    if rankings.empty:
        message = "No free agents found"
        if position:
            message += f" at position {position}"
        message += "."
        return f"{header}\n\n{message}"

    return f"{header}\n\n{rankings.to_string(index=False)}"


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


def build_commentary_inputs(
    client: SleeperClient,
    league_id: str,
    total_weeks: int,
    *,
    provider: Optional[PlayerStatsProvider] = None,
) -> tuple[LeagueSnapshot, pd.DataFrame, pd.DataFrame, pd.DataFrame, LeagueAnalytics]:
    """Build every input ``commentary/context.py``'s builders need for a league.

    Reuses the same normalization chain ``run_summary``/``scripts/player_analysis.py``
    already use -- ``load_league_snapshot`` (FFA-013), ``load_season_matchups``
    -> ``pair_season_matchups`` -> ``derive_season_outcomes`` ->
    ``build_season_matchup_df`` (FFA-030..033), and
    ``build_player_week_fact_table`` (FFA-064) -- rather than inventing a new
    fetch path. This is the one place in ``commentary``'s call graph allowed
    to touch the network (via ``client`` and, unless ``provider`` is
    supplied, a real ``NflverseWeeklyStatsProvider``); ``context.py``/
    ``prompts.py`` themselves stay pure.

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league to build commentary inputs for.
        total_weeks: Total weeks in the fantasy season (e.g. 18 for 2025),
            used to derive season boundaries.
        crosswalk: An optional pre-built Sleeper<->nflverse crosswalk
            (:data:`~fantasy_analyzer.players.crosswalk.CROSSWALK_COLUMNS`-shaped).
            Defaults to ``None``, in which case
            :func:`~fantasy_analyzer.players.crosswalk.build_robust_id_crosswalk`
            builds one -- which reads (and, on a cold cache, downloads)
            DynastyProcess's ID table. Inject one here to keep a test
            entirely offline, and to avoid rebuilding it per league when
            ranking several.
        provider: An optional
            :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`.
            Defaults to ``None``, in which case a real
            :class:`~fantasy_analyzer.players.nflverse_provider.NflverseWeeklyStatsProvider`
            is built from the Sleeper player catalog's own
            ``gsis_id``-based crosswalk
            (:func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk`).
            Tests should inject an in-memory fake here to avoid the nflverse
            network call.

    Returns:
        ``(snapshot, season_matchup_df, player_week_df, standings_df,
        analytics)`` -- exactly the inputs
        :func:`~fantasy_analyzer.commentary.context.build_matchup_context`
        and
        :func:`~fantasy_analyzer.commentary.context.build_league_week_context`
        need.
    """
    snapshot = load_league_snapshot(client, league_id)
    boundaries = derive_season_boundaries(snapshot.league, total_weeks=total_weeks)
    weeks = load_season_matchups(
        client, league_id, boundaries, season=snapshot.league.season
    )

    pairings = pair_season_matchups(weeks)
    outcomes = derive_season_outcomes(pairings)
    season_matchup_df = build_season_matchup_df(outcomes, snapshot.teams_df)

    if provider is None:
        catalog = get_players_cached(client)
        provider = NflverseWeeklyStatsProvider(id_crosswalk=build_id_crosswalk(catalog))

    fact_table = build_player_week_fact_table(
        weeks=weeks,
        teams_df=snapshot.teams_df,
        players_df=snapshot.players_df,
        provider=provider,
        scoring_settings=snapshot.scoring_settings,
    )

    standings_df = build_standings(snapshot.rosters_df, snapshot.teams_df)
    analytics = build_league_analytics(season_matchup_df, snapshot.teams_df)

    return (
        snapshot,
        season_matchup_df,
        fact_table.player_week_df,
        standings_df,
        analytics,
    )


def run_commentary_matchups(
    client: SleeperClient,
    league_id: str,
    total_weeks: int,
    week: int,
    *,
    tone: str = DEFAULT_TONE,
    per_matchup: bool = False,
    provider: Optional[PlayerStatsProvider] = None,
    generate: bool = False,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    commentary_client: Optional[CommentaryClient] = None,
) -> str:
    """Build and format a commentary prompt for a week's matchups (FFA-093/094).

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league to build the prompt for.
        total_weeks: Total weeks in the fantasy season.
        week: The week to build the prompt for.
        tone: A tone label passed through to the prompt template. Defaults
            to :data:`~fantasy_analyzer.commentary.prompts.DEFAULT_TONE`.
        per_matchup: If ``True``, print one prompt per matchup instead of a
            single combined prompt covering the whole week. Defaults to
            ``False``.
        provider: See :func:`build_commentary_inputs`.
        generate: If ``True``, send the prompt(s) to the Claude API via
            ``commentary_client`` and return the generated commentary text
            instead of the raw prompt(s). Defaults to ``False``.
        model: Anthropic model ID passed to ``commentary_client.generate``
            when ``generate`` is ``True``. Defaults to
            :data:`~fantasy_analyzer.commentary.client.DEFAULT_MODEL`.
        effort: Anthropic ``output_config.effort`` passed to
            ``commentary_client.generate`` when ``generate`` is ``True``.
            Defaults to
            :data:`~fantasy_analyzer.commentary.client.DEFAULT_EFFORT`.
        commentary_client: An optional
            :class:`~fantasy_analyzer.commentary.client.CommentaryClient`.
            Only used when ``generate`` is ``True``; defaults to a real
            client (requires ``ANTHROPIC_API_KEY``). Tests should inject a
            fake here.

    Returns:
        A single string: either one combined prompt/commentary, or each
        matchup's prompt/commentary joined with a blank line between them. A
        friendly message if ``week`` has no non-bye matchups.
    """
    snapshot, season_matchup_df, player_week_df, _, _ = build_commentary_inputs(
        client, league_id, total_weeks, provider=provider
    )
    contexts = build_matchup_context(snapshot, season_matchup_df, player_week_df, week)
    if not contexts:
        return f"No matchups found for week {week}."

    if per_matchup:
        prompts = [weekly_matchup_prompt(context, tone=tone) for context in contexts]
    else:
        prompts = [combined_matchup_prompt(contexts, tone=tone)]

    if not generate:
        return "\n\n".join(prompts)

    commentary_client = commentary_client or CommentaryClient()
    return "\n\n".join(
        commentary_client.generate(prompt, model=model, effort=effort)
        for prompt in prompts
    )


def run_commentary_recap(
    client: SleeperClient,
    league_id: str,
    total_weeks: int,
    week: int,
    *,
    tone: str = DEFAULT_TONE,
    provider: Optional[PlayerStatsProvider] = None,
    generate: bool = False,
    model: str = DEFAULT_MODEL,
    effort: str = DEFAULT_EFFORT,
    commentary_client: Optional[CommentaryClient] = None,
) -> str:
    """Build and format the league-wide weekly recap prompt (FFA-093/094).

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league to build the prompt for.
        total_weeks: Total weeks in the fantasy season.
        week: The week to build the recap prompt for.
        tone: A tone label passed through to the prompt template. Defaults
            to :data:`~fantasy_analyzer.commentary.prompts.DEFAULT_TONE`.
        provider: See :func:`build_commentary_inputs`.
        generate: If ``True``, send the prompt to the Claude API via
            ``commentary_client`` and return the generated commentary text
            instead of the raw prompt. Defaults to ``False``.
        model: Anthropic model ID passed to ``commentary_client.generate``
            when ``generate`` is ``True``. Defaults to
            :data:`~fantasy_analyzer.commentary.client.DEFAULT_MODEL`.
        effort: Anthropic ``output_config.effort`` passed to
            ``commentary_client.generate`` when ``generate`` is ``True``.
            Defaults to
            :data:`~fantasy_analyzer.commentary.client.DEFAULT_EFFORT`.
        commentary_client: An optional
            :class:`~fantasy_analyzer.commentary.client.CommentaryClient`.
            Only used when ``generate`` is ``True``; defaults to a real
            client (requires ``ANTHROPIC_API_KEY``). Tests should inject a
            fake here.

    Returns:
        The recap prompt string, or the generated commentary text if
        ``generate`` is ``True``.
    """
    snapshot, _, _, standings_df, analytics = build_commentary_inputs(
        client, league_id, total_weeks, provider=provider
    )
    context = build_league_week_context(snapshot, analytics, standings_df, week)
    prompt = league_week_recap_prompt(context, tone=tone)

    if not generate:
        return prompt

    commentary_client = commentary_client or CommentaryClient()
    return commentary_client.generate(prompt, model=model, effort=effort)


def _fetch_weekly_frames(
    provider: PlayerStatsProvider, season: int, weeks: Sequence[int]
) -> pd.DataFrame:
    """Concatenate a provider's per-week frames for ``season`` over ``weeks``.

    Skips (rather than errors on) any week the provider returns an empty
    frame for -- a future/unplayed week, per
    ``PlayerStatsProvider.weekly_stats``'s contract.

    Returns:
        A single concatenated DataFrame, or an empty
        :data:`~fantasy_analyzer.players.provider.PLAYER_WEEK_IDENTITY_COLUMNS`-shaped
        frame if every week is empty.
    """
    frames = [provider.weekly_stats(season, week) for week in weeks]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=PLAYER_WEEK_IDENTITY_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _load_usage_inputs(
    season: int,
) -> tuple[Optional[UsageModelParameters], Optional[pd.DataFrame]]:
    """The fitted usage model and the snap/xFP frame, from the local caches.

    Returns ``(usage_parameters, usage)``, the frame covering ``season`` and
    ``season - 1`` (the window the usage features read). No parameter file
    gives ``(None, None)`` -- the EB projection alone. Parameters but no
    snap/xFP cache gives ``(parameters, None)`` -- the separately fitted
    no-snap usage model. Never touches the network.
    """
    usage_parameters = load_usage_model_parameters()
    if usage_parameters is None:
        return None, None
    try:
        usage = load_usage_player_weeks([season - 1, season])
    except FileNotFoundError:
        return usage_parameters, None
    return usage_parameters, usage


def build_free_agent_rankings(
    client: SleeperClient,
    league_id: str,
    season: int,
    week: int,
    *,
    provider: Optional[PlayerStatsProvider] = None,
    crosswalk: Optional[pd.DataFrame] = None,
    position: Optional[str] = None,
    top: int = 25,
) -> pd.DataFrame:
    """Build a league's free-agent rest-of-season waiver-wire rankings (FFA-093).

    Composes the already-shipped FFA-091/089/090/092 pipeline over live
    Sleeper/nflverse inputs: the league snapshot (for ``roster_positions``/
    ``scoring_settings``/``total_rosters``), a Sleeper<->nflverse ID
    crosswalk, the current-state free-agent pool
    (:func:`~fantasy_analyzer.players.free_agents.build_free_agent_pool`),
    the league-scored weekly stats
    (:func:`~fantasy_analyzer.players.ros_backtest.build_scored_player_weeks`),
    and the waiver-wire ranking itself
    (:func:`~fantasy_analyzer.players.waiver_rankings.build_waiver_wire_rankings`).

    Four composition choices here carry most of the ranking's accuracy,
    and all four were originally made the other way:

    **Crosswalk (FFA-097).** Uses
    :func:`~fantasy_analyzer.players.crosswalk.build_robust_id_crosswalk`
    (DynastyProcess union), not the catalog-only
    :func:`~fantasy_analyzer.players.crosswalk.build_id_crosswalk`. The
    catalog-only version resolved 111 of 615 NFL-signed free agents in a
    measured 12-team league; the union resolves 520. An unresolved free
    agent gets no projection at all, so this is the difference between a
    waiver board and a sample of one.

    **Replacement population (FFA-095).** Passes the whole league --
    ``build_free_agent_pool`` with no rosters -- as
    ``replacement_population``, so the replacement level is the league's
    last startable player at each position rather than the wire's. See
    ``waiver_rankings.py``'s "Whom the replacement level is measured over"
    section for the distortion this removes.

    **Shrinkage parameters (FFA-101).** Loads a fitted
    :class:`~fantasy_analyzer.players.ros_projection.ShrinkageParameters`
    via
    :func:`~fantasy_analyzer.players.ros_projection.load_shrinkage_parameters`
    when one has been persisted (run ``scripts/fit_shrinkage_parameters.py``
    once to create it), falling back to the uniform, unfitted
    :data:`~fantasy_analyzer.players.ros_projection.DEFAULT_N0` otherwise.
    The fallback is directionally reasonable but measurably less accurate
    than the validated per-position values
    (``n0={RB: 2.0, WR: 2.0, TE: 2.5, QB: 4.0}``) reported in
    ``docs/ros-projection-accuracy.md``.

    **Projection model (FFA-111, FFA-104).** Passes the fitted usage model,
    the league's ``scoring_settings`` and the cached snap/xFP frame
    (:func:`_load_usage_inputs`), so ``projected_ppg`` is the per-position
    blend of the usage model and the EB projection, and a player with no
    games and no trusted prior gets the fitted absent-prior line scored in
    this league. Without the cached parameters it falls back to EB alone;
    without the snap/xFP caches, to the no-snap usage model. See
    ``docs/valuation-model.md``.

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league to rank free agents for.
        season: The season to score nflverse stats against.
        week: The cutoff week -- the last completed week; rest-of-season is
            projected from after this week. Passed through as
            ``cutoff_week`` to
            :func:`~fantasy_analyzer.players.waiver_rankings.build_waiver_wire_rankings`.
        provider: An optional
            :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`.
            Defaults to ``None``, in which case a real
            :class:`~fantasy_analyzer.players.nflverse_provider.NflverseWeeklyStatsProvider`
            is built from the Sleeper player catalog's own ``gsis_id``-based
            crosswalk, mirroring ``build_commentary_inputs``. Tests should
            inject an in-memory fake here to avoid the nflverse network
            call.
        position: An optional single-position filter (e.g. ``"WR"``),
            applied after ranking. Defaults to ``None`` (every position).
        top: Maximum number of rows to return, taken from the top of the
            ranking (already sorted by ascending ``waiver_rank``). Defaults
            to ``25``.

    Returns:
        A :data:`~fantasy_analyzer.players.waiver_rankings.WAIVER_WIRE_RANKING_COLUMNS`-
        shaped DataFrame, filtered to ``position`` (if given) and truncated to
        ``top`` rows. Empty (same columns) if the league has no free agents,
        or none at ``position``.
    """
    snapshot = load_league_snapshot(client, league_id)
    raw_rosters = client.get_rosters(league_id)
    catalog = get_players_cached(client)
    if crosswalk is None:
        crosswalk = build_robust_id_crosswalk(catalog)

    if provider is None:
        provider = NflverseWeeklyStatsProvider(id_crosswalk=crosswalk)

    free_agent_pool = build_free_agent_pool(
        raw_rosters, catalog, snapshot.roster_positions, crosswalk=crosswalk
    )
    # The same builder with no rosters yields every startable-position
    # player in the catalog, rostered included -- the population the
    # replacement level must be measured over (FFA-095). Only the free
    # agents above are ever returned.
    league_population = build_free_agent_pool(
        [], catalog, snapshot.roster_positions, crosswalk=crosswalk
    )

    current_season_raw = _fetch_weekly_frames(provider, season, _NFL_SEASON_WEEKS)
    prior_season_raw = _fetch_weekly_frames(provider, season - 1, _NFL_SEASON_WEEKS)

    scored_weeks = build_scored_player_weeks(
        [current_season_raw, prior_season_raw],
        snapshot.scoring_settings,
        player_id_column="gsis_id",
    )

    parameters = load_shrinkage_parameters() or ShrinkageParameters(
        n0_by_position={}, default_n0=DEFAULT_N0
    )
    usage_parameters, usage = _load_usage_inputs(season)

    rankings = build_waiver_wire_rankings(
        free_agent_pool,
        scored_weeks,
        season,
        week,
        snapshot.roster_positions,
        snapshot.league.total_rosters,
        parameters,
        replacement_population=league_population,
        usage_parameters=usage_parameters,
        scoring_settings=snapshot.scoring_settings,
        usage=usage,
    )

    if position:
        rankings = rankings[rankings["position"] == position].reset_index(drop=True)

    return rankings.head(top).reset_index(drop=True)


def run_free_agents(
    client: SleeperClient,
    league_id: str,
    season: int,
    week: int,
    *,
    position: Optional[str] = None,
    top: int = 25,
    format: str = "text",
    provider: Optional[PlayerStatsProvider] = None,
    crosswalk: Optional[pd.DataFrame] = None,
) -> str:
    """Build and format a league's free-agent waiver-wire rankings (FFA-093).

    See :func:`build_free_agent_rankings` for the pipeline, the four
    composition choices that carry its accuracy, and the injectable
    ``provider``/``crosswalk`` seams tests use to stay offline.
    """
    rankings = build_free_agent_rankings(
        client,
        league_id,
        season,
        week,
        provider=provider,
        crosswalk=crosswalk,
        position=position,
        top=top,
    )
    return _format_free_agent_rankings(
        rankings, league_id, season, week, position=position, format=format
    )


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
        elif args.command == "summary":
            output = run_summary(client, args.league_id, args.total_weeks)
        elif args.command == "free-agents":
            output = run_free_agents(
                client,
                args.league_id,
                args.season,
                args.week,
                position=args.position,
                top=args.top,
                format=args.format,
            )
        elif args.commentary_command == "matchups":
            output = run_commentary_matchups(
                client,
                args.league_id,
                args.total_weeks,
                args.week,
                tone=args.tone,
                per_matchup=args.per_matchup,
                generate=args.generate,
                model=args.model,
                effort=args.effort,
            )
        else:
            output = run_commentary_recap(
                client,
                args.league_id,
                args.total_weeks,
                args.week,
                tone=args.tone,
                generate=args.generate,
                model=args.model,
                effort=args.effort,
            )
    except (SleeperAPIError, ValueError, CommentaryGenerationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
