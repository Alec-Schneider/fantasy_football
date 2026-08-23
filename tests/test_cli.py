"""Tests for the ``fantasy-analyzer`` CLI (FFA-024).

All network access goes through ``SleeperClient``, so these tests mock HTTP
with ``requests_mock`` against the same sanitized fixtures used elsewhere in
the suite -- no live Sleeper dependency, per AGENTS.md.
"""

import requests_mock as requests_mock_lib

from fantasy_analyzer.cli import (
    build_arg_parser,
    main,
    run_leagues,
    run_summary,
)
from fantasy_analyzer.sleeper.client import SleeperClient


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
