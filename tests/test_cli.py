"""Tests for the ``fantasy-analyzer`` CLI (FFA-024).

All network access goes through ``SleeperClient``, so these tests mock HTTP
with ``requests_mock`` against the same sanitized fixtures used elsewhere in
the suite -- no live Sleeper dependency, per AGENTS.md.
"""

import json

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.cli import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    _load_usage_inputs,
    build_arg_parser,
    main,
    run_commentary_matchups,
    run_commentary_recap,
    run_free_agents,
    run_leagues,
    run_summary,
)
from fantasy_analyzer.players.provider import PLAYER_WEEK_IDENTITY_COLUMNS
from fantasy_analyzer.players.waiver_rankings import WAIVER_WIRE_RANKING_COLUMNS
from fantasy_analyzer.sleeper.client import SleeperClient


class FakeCommentaryClient:
    """A no-network ``CommentaryClient`` stand-in that echoes call count."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.calls: list[dict] = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        self.calls.append(kwargs)
        return f"GENERATED[{len(self.prompts)}]"


def _mock_league_endpoints(m: requests_mock_lib.Mocker, load_sleeper_fixture) -> None:
    m.get(
        f"{SleeperClient.BASE_URL}/league/111",
        json=load_sleeper_fixture("league.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/league/111/users",
        json=load_sleeper_fixture("users.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/league/111/rosters",
        json=load_sleeper_fixture("rosters.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/players/nfl",
        json=load_sleeper_fixture("players.json"),
    )


def _mock_matchup_endpoints(m: requests_mock_lib.Mocker, load_sleeper_fixture) -> None:
    """Mock the single week of matchups fetched with ``--total-weeks 1``.

    Fixture ``league.json`` sets ``playoff_week_start: 15``, so
    ``derive_season_boundaries(..., total_weeks=1)`` yields
    ``regular_season_weeks=[1]``/``playoff_weeks=[]`` -- exactly one
    ``/matchups/<week>`` call to mock.
    """
    m.get(
        f"{SleeperClient.BASE_URL}/league/111/matchups/1",
        json=load_sleeper_fixture("matchups.json"),
    )


class FakePlayerStatsProvider:
    """A minimal, no-network ``PlayerStatsProvider`` (mirrors ``test_player_week.py``).

    Always returns an empty, correctly-columned frame -- these CLI tests
    only assert on prompt structure/output shape, not on specific player
    stats, so no rows are needed.
    """

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        return pd.DataFrame(columns=PLAYER_WEEK_IDENTITY_COLUMNS)


# -------------------------
# Argument parsing
# -------------------------


def test_leagues_subcommand_parses_username_and_season() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["leagues", "schneidbaby", "--season", "2025"])

    assert args.command == "leagues"
    assert args.username == "schneidbaby"
    assert args.season == 2025


def test_summary_subcommand_parses_league_id_and_total_weeks() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["summary", "111", "--total-weeks", "18"])

    assert args.command == "summary"
    assert args.league_id == "111"
    assert args.total_weeks == 18


def test_parser_requires_a_subcommand() -> None:
    parser = build_arg_parser()
    try:
        parser.parse_args([])
        assert False, "expected SystemExit for a missing subcommand"
    except SystemExit:
        pass


# -------------------------
# run_leagues / run_summary
# -------------------------


def test_run_leagues_resolves_username_and_lists_leagues(load_sleeper_fixture) -> None:
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/user/schneidbaby",
            json=load_sleeper_fixture("user.json"),
        )
        m.get(
            f"{SleeperClient.BASE_URL}/user/123456789012345678/leagues/nfl/2025",
            json=load_sleeper_fixture("leagues.json"),
        )
        output = run_leagues(client, "schneidbaby", 2025)

    assert "league_id" in output
    assert "name" in output
    for league in load_sleeper_fixture("leagues.json"):
        assert league["name"] in output


def test_run_leagues_reports_no_leagues_found(load_sleeper_fixture) -> None:
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/user/schneidbaby",
            json=load_sleeper_fixture("user.json"),
        )
        m.get(
            f"{SleeperClient.BASE_URL}/user/123456789012345678/leagues/nfl/2025",
            json=[],
        )
        output = run_leagues(client, "schneidbaby", 2025)

    assert output == "No leagues found."


def test_run_summary_prints_league_metadata_and_tables(load_sleeper_fixture) -> None:
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        output = run_summary(client, "111", total_weeks=18)

    assert "Test League" in output
    assert "league_id: 111" in output
    assert "Standings:" in output
    assert "Scoring summary:" in output


# -------------------------
# main()
# -------------------------


def test_main_leagues_returns_zero_on_success(load_sleeper_fixture, capsys) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/user/schneidbaby",
            json=load_sleeper_fixture("user.json"),
        )
        m.get(
            f"{SleeperClient.BASE_URL}/user/123456789012345678/leagues/nfl/2025",
            json=load_sleeper_fixture("leagues.json"),
        )
        exit_code = main(["leagues", "schneidbaby", "--season", "2025"])

    assert exit_code == 0
    assert "league_id" in capsys.readouterr().out


def test_main_summary_returns_zero_on_success(load_sleeper_fixture, capsys) -> None:
    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        exit_code = main(["summary", "111", "--total-weeks", "18"])

    assert exit_code == 0
    assert "Standings:" in capsys.readouterr().out


def test_main_returns_one_and_prints_error_for_unknown_user(capsys) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/user/doesnotexist",
            status_code=200,
            text="null",
            headers={"Content-Type": "application/json"},
        )
        exit_code = main(["leagues", "doesnotexist", "--season", "2025"])

    assert exit_code == 1
    assert "Error" in capsys.readouterr().err


def test_main_returns_one_and_prints_error_on_http_failure(capsys) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/missing", status_code=404)
        exit_code = main(["summary", "missing", "--total-weeks", "18"])

    assert exit_code == 1
    assert "Error" in capsys.readouterr().err


# -------------------------
# commentary subcommand: argument parsing
# -------------------------


def test_commentary_matchups_subcommand_parses_args() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "commentary",
            "matchups",
            "111",
            "--week",
            "3",
            "--total-weeks",
            "18",
            "--tone",
            "straightforward",
            "--per-matchup",
            "--generate",
            "--model",
            "claude-sonnet-5",
            "--effort",
            "medium",
        ]
    )

    assert args.command == "commentary"
    assert args.commentary_command == "matchups"
    assert args.league_id == "111"
    assert args.week == 3
    assert args.total_weeks == 18
    assert args.tone == "straightforward"
    assert args.per_matchup is True
    assert args.generate is True
    assert args.model == "claude-sonnet-5"
    assert args.effort == "medium"


def test_commentary_matchups_subcommand_defaults_tone_and_per_matchup() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        ["commentary", "matchups", "111", "--week", "3", "--total-weeks", "18"]
    )

    assert args.tone == "witty"
    assert args.per_matchup is False
    assert args.generate is False
    assert args.model == DEFAULT_MODEL
    assert args.effort == DEFAULT_EFFORT


def test_commentary_recap_subcommand_parses_args() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "commentary",
            "recap",
            "111",
            "--week",
            "3",
            "--total-weeks",
            "1",
            "--generate",
            "--model",
            "claude-sonnet-5",
            "--effort",
            "medium",
        ]
    )

    assert args.command == "commentary"
    assert args.commentary_command == "recap"
    assert args.league_id == "111"
    assert args.week == 3
    assert args.total_weeks == 1
    assert args.tone == "witty"
    assert args.generate is True
    assert args.model == "claude-sonnet-5"
    assert args.effort == "medium"


def test_commentary_recap_subcommand_defaults_generate_false() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        ["commentary", "recap", "111", "--week", "3", "--total-weeks", "1"]
    )

    assert args.generate is False
    assert args.model == DEFAULT_MODEL
    assert args.effort == DEFAULT_EFFORT


def test_commentary_subcommand_requires_a_sub_subcommand() -> None:
    parser = build_arg_parser()
    try:
        parser.parse_args(["commentary"])
        assert False, "expected SystemExit for a missing commentary sub-subcommand"
    except SystemExit:
        pass


# -------------------------
# run_commentary_matchups / run_commentary_recap
# -------------------------


def test_run_commentary_matchups_prints_combined_prompt(load_sleeper_fixture) -> None:
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        output = run_commentary_matchups(
            client, "111", total_weeks=1, week=1, provider=FakePlayerStatsProvider()
        )

    assert "commentary writer" in output.lower()
    assert "```json" in output
    assert "Constraints:" in output
    # matchups.json pairs roster_1 vs roster_2 in matchup_id 1 for week 1.
    assert '"matchup_id": 1' in output


def test_run_commentary_matchups_per_matchup_prints_one_prompt_per_matchup(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        output = run_commentary_matchups(
            client,
            "111",
            total_weeks=1,
            week=1,
            per_matchup=True,
            provider=FakePlayerStatsProvider(),
        )

    # A single-matchup week still yields exactly one "role framing" block.
    assert output.lower().count("commentary writer") == 1


def test_run_commentary_matchups_no_matchups_for_week_returns_message(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        output = run_commentary_matchups(
            client, "111", total_weeks=1, week=2, provider=FakePlayerStatsProvider()
        )

    assert output == "No matchups found for week 2."


def test_run_commentary_recap_prints_recap_prompt(load_sleeper_fixture) -> None:
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        output = run_commentary_recap(
            client, "111", total_weeks=1, week=1, provider=FakePlayerStatsProvider()
        )

    assert "commentary writer" in output.lower()
    assert "league-wide" in output.lower()
    assert "```json" in output
    assert "Constraints:" in output


def test_main_commentary_matchups_returns_zero_on_success(
    load_sleeper_fixture, capsys, monkeypatch
) -> None:
    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        # ``main()`` builds a real provider when none is injected; patch the
        # nflverse-backed provider class so this test stays network-free
        # while still exercising the full ``main()`` dispatch path.
        monkeypatch.setattr(
            "fantasy_analyzer.cli.NflverseWeeklyStatsProvider",
            lambda **kwargs: FakePlayerStatsProvider(),
        )
        exit_code = main(
            ["commentary", "matchups", "111", "--week", "1", "--total-weeks", "1"]
        )

    assert exit_code == 0
    assert "```json" in capsys.readouterr().out


def test_main_commentary_recap_returns_zero_on_success(
    load_sleeper_fixture, capsys, monkeypatch
) -> None:
    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        monkeypatch.setattr(
            "fantasy_analyzer.cli.NflverseWeeklyStatsProvider",
            lambda **kwargs: FakePlayerStatsProvider(),
        )
        exit_code = main(
            ["commentary", "recap", "111", "--week", "1", "--total-weeks", "1"]
        )

    assert exit_code == 0
    assert "league-wide" in capsys.readouterr().out.lower()


# -------------------------
# --generate (FFA-094)
# -------------------------


def test_run_commentary_matchups_generate_returns_commentary_not_prompt(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()
    fake_commentary_client = FakeCommentaryClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        output = run_commentary_matchups(
            client,
            "111",
            total_weeks=1,
            week=1,
            provider=FakePlayerStatsProvider(),
            generate=True,
            commentary_client=fake_commentary_client,
        )

    assert output == "GENERATED[1]"
    assert len(fake_commentary_client.prompts) == 1
    assert "```json" in fake_commentary_client.prompts[0]
    assert fake_commentary_client.calls[0]["model"] == DEFAULT_MODEL
    assert fake_commentary_client.calls[0]["effort"] == DEFAULT_EFFORT


def test_run_commentary_matchups_generate_passes_model_and_effort_override(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()
    fake_commentary_client = FakeCommentaryClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        run_commentary_matchups(
            client,
            "111",
            total_weeks=1,
            week=1,
            provider=FakePlayerStatsProvider(),
            generate=True,
            model="claude-sonnet-5",
            effort="medium",
            commentary_client=fake_commentary_client,
        )

    assert fake_commentary_client.calls[0]["model"] == "claude-sonnet-5"
    assert fake_commentary_client.calls[0]["effort"] == "medium"


def test_run_commentary_matchups_generate_per_matchup_calls_once_per_prompt(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()
    fake_commentary_client = FakeCommentaryClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        output = run_commentary_matchups(
            client,
            "111",
            total_weeks=1,
            week=1,
            per_matchup=True,
            provider=FakePlayerStatsProvider(),
            generate=True,
            commentary_client=fake_commentary_client,
        )

    # Fixture week 1 has exactly one non-bye matchup.
    assert len(fake_commentary_client.prompts) == 1
    assert output == "GENERATED[1]"


def test_run_commentary_recap_generate_returns_commentary_not_prompt(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()
    fake_commentary_client = FakeCommentaryClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        output = run_commentary_recap(
            client,
            "111",
            total_weeks=1,
            week=1,
            provider=FakePlayerStatsProvider(),
            generate=True,
            commentary_client=fake_commentary_client,
        )

    assert output == "GENERATED[1]"
    assert "league-wide" in fake_commentary_client.prompts[0].lower()
    assert fake_commentary_client.calls[0]["model"] == DEFAULT_MODEL
    assert fake_commentary_client.calls[0]["effort"] == DEFAULT_EFFORT


def test_run_commentary_recap_generate_passes_model_and_effort_override(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()
    fake_commentary_client = FakeCommentaryClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        run_commentary_recap(
            client,
            "111",
            total_weeks=1,
            week=1,
            provider=FakePlayerStatsProvider(),
            generate=True,
            model="claude-sonnet-5",
            effort="medium",
            commentary_client=fake_commentary_client,
        )

    assert fake_commentary_client.calls[0]["model"] == "claude-sonnet-5"
    assert fake_commentary_client.calls[0]["effort"] == "medium"


def test_main_commentary_matchups_generate_returns_zero_on_success(
    load_sleeper_fixture, capsys, monkeypatch
) -> None:
    fake_commentary_client = FakeCommentaryClient()

    with requests_mock_lib.Mocker() as m:
        _mock_league_endpoints(m, load_sleeper_fixture)
        _mock_matchup_endpoints(m, load_sleeper_fixture)
        monkeypatch.setattr(
            "fantasy_analyzer.cli.NflverseWeeklyStatsProvider",
            lambda **kwargs: FakePlayerStatsProvider(),
        )
        monkeypatch.setattr(
            "fantasy_analyzer.cli.CommentaryClient",
            lambda **kwargs: fake_commentary_client,
        )
        exit_code = main(
            [
                "commentary",
                "matchups",
                "111",
                "--week",
                "1",
                "--total-weeks",
                "1",
                "--generate",
            ]
        )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "GENERATED[1]"


# -------------------------
# free-agents subcommand (FFA-093)
# -------------------------


class FakeWeeklyStatsProvider:
    """A minimal in-memory ``PlayerStatsProvider`` with real per-week rows.

    Mirrors ``tests/players/test_player_week.py``'s
    ``FakePlayerStatsProvider`` (rows keyed by ``(season, week)``), but for
    this module's stat vocabulary (``receptions``/``receiving_yards``).
    """

    def __init__(self, rows: list[dict]) -> None:
        stat_columns = ["receptions", "receiving_yards"]
        columns = PLAYER_WEEK_IDENTITY_COLUMNS + stat_columns
        self._df = pd.DataFrame(rows, columns=columns)

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        matches = self._df[(self._df["season"] == season) & (self._df["week"] == week)]
        return matches.reset_index(drop=True)


def _mock_free_agent_endpoints(
    m: requests_mock_lib.Mocker,
    load_sleeper_fixture,
    *,
    rosters: list[dict] = None,
    players: dict = None,
) -> None:
    """Mock ``league``/``users``/``rosters``/``players`` for free-agent tests.

    Defaults to the shared fixtures (``rosters.json``/``players.json``,
    where "1003" -- a WR with no ``gsis_id`` -- is the only free agent), but
    accepts overrides so individual tests can shape a specific free-agent
    population (e.g. an empty pool, or a free agent with a real crosswalk).
    """
    m.get(
        f"{SleeperClient.BASE_URL}/league/111", json=load_sleeper_fixture("league.json")
    )
    m.get(
        f"{SleeperClient.BASE_URL}/league/111/users",
        json=load_sleeper_fixture("users.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/league/111/rosters",
        json=rosters if rosters is not None else load_sleeper_fixture("rosters.json"),
    )
    m.get(
        f"{SleeperClient.BASE_URL}/players/nfl",
        json=players if players is not None else load_sleeper_fixture("players.json"),
    )


def test_free_agents_subcommand_parses_args() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "free-agents",
            "111",
            "--season",
            "2026",
            "--week",
            "3",
            "--position",
            "WR",
            "--top",
            "10",
            "--format",
            "json",
        ]
    )

    assert args.command == "free-agents"
    assert args.league_id == "111"
    assert args.season == 2026
    assert args.week == 3
    assert args.position == "WR"
    assert args.top == 10
    assert args.format == "json"


def test_free_agents_subcommand_defaults() -> None:
    parser = build_arg_parser()
    args = parser.parse_args(["free-agents", "111", "--season", "2026", "--week", "3"])

    assert args.position is None
    assert args.top == 25
    assert args.format == "text"


def _patch_get_players_cached(monkeypatch) -> None:
    """Bypass the real on-disk player-catalog cache in ``build_free_agent_rankings``.

    ``get_players_cached`` prefers an existing local cache file
    (``.cache/sleeper/players.json``) over a fresh HTTP call, which is
    exactly the wrong choice for a test that mocks the ``/players/nfl``
    endpoint with a small fixture -- without this patch, tests would
    silently read whatever real cache happens to exist in the working
    directory. Route straight to ``SleeperClient.get_players`` instead
    (still HTTP-mocked, never live).
    """
    monkeypatch.setattr(
        "fantasy_analyzer.cli.get_players_cached", lambda client: client.get_players()
    )


@pytest.fixture(autouse=True)
def _no_usage_caches(monkeypatch) -> None:
    """Keep ``build_free_agent_rankings`` off the real on-disk usage caches.

    ``_load_usage_inputs`` reads the fitted usage model and the snap/xFP
    caches under ``.cache/``; whatever happens to exist in the working
    directory must not change a test's ranking, the same reason
    :func:`_patch_get_players_cached` exists. The EB-only path is the default
    here; tests of the usage wiring opt in with their own stand-ins.
    """
    monkeypatch.setattr(
        "fantasy_analyzer.cli._load_usage_inputs", lambda season: (None, None)
    )


def test_free_agents_pass_the_usage_model_to_the_ranking(
    load_sleeper_fixture, monkeypatch
) -> None:
    """FFA-111: the usage model, the league's scoring and the snap frame all
    reach ``build_waiver_wire_rankings``."""
    _patch_get_players_cached(monkeypatch)
    usage_parameters, usage = object(), pd.DataFrame({"season": [2025]})
    seasons: list[int] = []
    captured: dict = {}

    def fake_load(season):
        seasons.append(season)
        return usage_parameters, usage

    def fake_rankings(*args, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame(columns=WAIVER_WIRE_RANKING_COLUMNS)

    monkeypatch.setattr("fantasy_analyzer.cli._load_usage_inputs", fake_load)
    monkeypatch.setattr(
        "fantasy_analyzer.cli.build_waiver_wire_rankings", fake_rankings
    )
    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(m, load_sleeper_fixture)
        run_free_agents(
            SleeperClient(),
            "111",
            season=2025,
            week=3,
            provider=FakeWeeklyStatsProvider([]),
        )

    assert seasons == [2025]
    assert captured["usage_parameters"] is usage_parameters
    assert captured["usage"] is usage
    league = load_sleeper_fixture("league.json")
    assert captured["scoring_settings"] == league["scoring_settings"]


def test_load_usage_inputs_falls_back_one_layer_at_a_time(monkeypatch) -> None:
    """No parameters -> EB alone; parameters but no snap cache -> no-snap model."""
    parameters = object()
    frame = pd.DataFrame({"season": [2025, 2026]})
    requested: list = []

    def load_frame(seasons):
        requested.append(list(seasons))
        return frame

    def missing_cache(seasons):
        raise FileNotFoundError("snap_counts_2026.csv")

    monkeypatch.setattr(
        "fantasy_analyzer.cli.load_usage_model_parameters", lambda: None
    )
    monkeypatch.setattr("fantasy_analyzer.cli.load_usage_player_weeks", load_frame)
    assert _load_usage_inputs(2026) == (None, None)
    assert requested == []

    monkeypatch.setattr(
        "fantasy_analyzer.cli.load_usage_model_parameters", lambda: parameters
    )
    loaded_parameters, loaded_frame = _load_usage_inputs(2026)
    assert loaded_parameters is parameters and loaded_frame is frame
    assert requested == [[2025, 2026]]

    monkeypatch.setattr("fantasy_analyzer.cli.load_usage_player_weeks", missing_cache)
    assert _load_usage_inputs(2026) == (parameters, None)


def test_run_free_agents_no_crosswalk_free_agent_returns_row_with_null_projection(
    load_sleeper_fixture, monkeypatch
) -> None:
    """The shared fixture's only free agent ("1003", WR) has no ``gsis_id``.

    Per FFA-091/092's "don't drop, null" convention, he still gets a row --
    with every projection column undefined -- rather than being silently
    excluded.
    """
    _patch_get_players_cached(monkeypatch)
    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(m, load_sleeper_fixture)
        output = run_free_agents(
            SleeperClient(),
            "111",
            season=2025,
            week=3,
            provider=FakeWeeklyStatsProvider([]),
        )

    assert "Free agents -- league 111, season 2025, through week 3" in output
    assert "1003" in output
    assert "Test Player Three" in output


def test_run_free_agents_position_filter_with_no_matches_returns_message(
    load_sleeper_fixture, monkeypatch
) -> None:
    _patch_get_players_cached(monkeypatch)
    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(m, load_sleeper_fixture)
        output = run_free_agents(
            SleeperClient(),
            "111",
            season=2025,
            week=3,
            position="RB",
            provider=FakeWeeklyStatsProvider([]),
        )

    assert "No free agents found at position RB." in output


def test_run_free_agents_empty_pool_returns_message(
    load_sleeper_fixture, monkeypatch
) -> None:
    _patch_get_players_cached(monkeypatch)
    # Every startable position (QB/RB/WR/TE/DEF/K) in the catalog is
    # rostered, leaving no free agents at all.
    rosters = [
        {
            "roster_id": 1,
            "owner_id": "123456789012345678",
            "players": ["1000", "1002", "1003"],
            "starters": ["1000", "1002", "1003"],
            "reserve": [],
            "settings": {
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "fpts": 0,
                "fpts_decimal": 0,
                "fpts_against": 0,
                "fpts_against_decimal": 0,
            },
        }
    ]
    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(m, load_sleeper_fixture, rosters=rosters)
        output = run_free_agents(
            SleeperClient(),
            "111",
            season=2025,
            week=3,
            provider=FakeWeeklyStatsProvider([]),
        )

    assert "No free agents found." in output


def test_run_free_agents_ranks_free_agent_with_crosswalk_by_vorp(
    load_sleeper_fixture, monkeypatch
) -> None:
    """A free agent with a real ``gsis_id`` gets a real projection/VORP row."""
    _patch_get_players_cached(monkeypatch)
    players = {
        "1000": {
            "player_id": "1000",
            "full_name": "Rostered QB",
            "position": "QB",
            "team": "SEA",
            "gsis_id": "00-1000",
        },
        "2000": {
            "player_id": "2000",
            "full_name": "Free Agent WR",
            "position": "WR",
            "team": "CIN",
            "gsis_id": "00-2000",
        },
    }
    rosters = [
        {
            "roster_id": 1,
            "owner_id": "123456789012345678",
            "players": ["1000"],
            "starters": ["1000"],
            "reserve": [],
            "settings": {
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "fpts": 0,
                "fpts_decimal": 0,
                "fpts_against": 0,
                "fpts_against_decimal": 0,
            },
        }
    ]
    weekly_rows = [
        {
            "season": 2025,
            "week": week,
            "sleeper_player_id": None,
            "gsis_id": "00-2000",
            "player_name": "Free Agent WR",
            "position": "WR",
            "nfl_team": "CIN",
            "receptions": 6,
            "receiving_yards": 80,
        }
        for week in (1, 2, 3)
    ]

    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(
            m, load_sleeper_fixture, rosters=rosters, players=players
        )
        output = run_free_agents(
            SleeperClient(),
            "111",
            season=2025,
            week=3,
            provider=FakeWeeklyStatsProvider(weekly_rows),
        )

    assert "Free Agent WR" in output
    assert "2000" in output


def test_run_free_agents_week_past_season_end_does_not_crash(
    load_sleeper_fixture, monkeypatch
) -> None:
    _patch_get_players_cached(monkeypatch)
    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(m, load_sleeper_fixture)
        output = run_free_agents(
            SleeperClient(),
            "111",
            season=2025,
            week=18,
            provider=FakeWeeklyStatsProvider([]),
        )

    assert "Free agents -- league 111, season 2025, through week 18" in output


def test_run_free_agents_json_format_is_valid_and_parseable(
    load_sleeper_fixture, monkeypatch
) -> None:
    _patch_get_players_cached(monkeypatch)
    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(m, load_sleeper_fixture)
        output = run_free_agents(
            SleeperClient(),
            "111",
            season=2025,
            week=3,
            format="json",
            provider=FakeWeeklyStatsProvider([]),
        )

    records = json.loads(output)
    assert isinstance(records, list)
    assert records
    assert records[0]["player_id"] == "1003"


def test_main_free_agents_returns_zero_on_success(
    load_sleeper_fixture, capsys, monkeypatch
) -> None:
    _patch_get_players_cached(monkeypatch)
    with requests_mock_lib.Mocker() as m:
        _mock_free_agent_endpoints(m, load_sleeper_fixture)
        monkeypatch.setattr(
            "fantasy_analyzer.cli.NflverseWeeklyStatsProvider",
            lambda **kwargs: FakeWeeklyStatsProvider([]),
        )
        exit_code = main(["free-agents", "111", "--season", "2025", "--week", "3"])

    assert exit_code == 0
    assert "Free agents" in capsys.readouterr().out
