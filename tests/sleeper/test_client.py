"""Tests for SleeperClient HTTP plumbing and endpoint methods.

These tests never touch the live Sleeper API -- all HTTP calls are mocked
with requests_mock against sanitized fixture responses.
"""

import pytest
import requests
import requests_mock as requests_mock_lib

from fantasy_analyzer.sleeper import (
    SleeperClient,
    SleeperConnectionError,
    SleeperHTTPError,
    SleeperTimeoutError,
)


@pytest.fixture
def client() -> SleeperClient:
    return SleeperClient()


# -------------------------
# _get plumbing
# -------------------------


def test_get_returns_decoded_json(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/some/endpoint",
            json={"hello": "world"},
        )
        result = client._get("some/endpoint")

    assert result == {"hello": "world"}


def test_get_centralizes_url_construction(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/foo/bar", json={})
        client._get("/foo/bar")  # leading slash should be stripped
        client._get("foo/bar")

    assert m.call_count == 2
    for request in m.request_history:
        assert request.url == f"{SleeperClient.BASE_URL}/foo/bar"


def test_get_passes_query_params(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json={})
        client._get("players/nfl", params={"position": "QB"})

    assert m.last_request.qs == {"position": ["qb"]}


def test_get_reuses_session(client: SleeperClient) -> None:
    assert isinstance(client.session, requests.Session)


def test_get_raises_useful_error_on_4xx(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/missing", status_code=404)

        with pytest.raises(SleeperHTTPError) as exc_info:
            client._get("missing")

    assert exc_info.value.status_code == 404


def test_get_raises_useful_error_on_5xx(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/broken", status_code=500)

        with pytest.raises(SleeperHTTPError) as exc_info:
            client._get("broken")

    assert exc_info.value.status_code == 500


def test_get_raises_timeout_error(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/slow",
            exc=requests.exceptions.Timeout,
        )

        with pytest.raises(SleeperTimeoutError):
            client._get("slow")


def test_get_raises_connection_error(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/unreachable",
            exc=requests.exceptions.ConnectionError,
        )

        with pytest.raises(SleeperConnectionError):
            client._get("unreachable")


def test_client_uses_configured_timeout() -> None:
    client = SleeperClient(timeout=5)
    assert client.timeout == 5


# -------------------------
# Endpoint methods
# -------------------------


def test_get_user_returns_user(client: SleeperClient, load_sleeper_fixture) -> None:
    fixture = load_sleeper_fixture("user.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/user/testuser", json=fixture)
        user = client.get_user("testuser")

    assert user == fixture
    assert user["user_id"] == "123456789012345678"


def test_get_user_resolves_username_to_permanent_user_id(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """A mutable username should resolve to Sleeper's immutable user_id."""
    fixture = load_sleeper_fixture("user.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/user/testuser", json=fixture)
        user = client.get_user("testuser")

    assert isinstance(user["user_id"], str)
    assert user["user_id"] != ""
    # The username itself is just a mutable label -- it must not be used
    # as a stand-in for user_id anywhere downstream.
    assert user["user_id"] != user["username"]


def test_get_user_raises_for_missing_user(client: SleeperClient) -> None:
    """Sleeper returns HTTP 200 with a literal JSON ``null`` body for unknown
    usernames (not a 404), so ``get_user`` must treat that case explicitly.
    """
    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/user/doesnotexist",
            status_code=200,
            text="null",
            headers={"Content-Type": "application/json"},
        )

        with pytest.raises(ValueError, match="doesnotexist"):
            client.get_user("doesnotexist")


def test_get_leagues_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("leagues.json")

    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/user/123/leagues/nfl/2025",
            json=fixture,
        )
        leagues = client.get_leagues(user_id="123", season=2025)

    assert leagues == fixture


def test_get_leagues_for_2025_season_returns_league_list(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """2025 leagues for a user_id can be retrieved as a list of league dicts."""
    fixture = load_sleeper_fixture("leagues.json")

    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/user/123456789012345678/leagues/nfl/2025",
            json=fixture,
        )
        leagues = client.get_leagues(user_id="123456789012345678", season=2025)

    assert isinstance(leagues, list)
    assert len(leagues) > 0
    for league in leagues:
        assert isinstance(league, dict)
        assert league["season"] == "2025"
        assert "league_id" in league
        assert "name" in league


def test_get_league_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("league.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111", json=fixture)
        league = client.get_league("111")

    assert league == fixture


def test_get_rosters_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("rosters.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/rosters", json=fixture)
        rosters = client.get_rosters("111")

    assert rosters == fixture


def test_get_users_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("users.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/users", json=fixture)
        users = client.get_users("111")

    assert users == fixture


def test_get_matchups_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("matchups.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/matchups/3", json=fixture)
        matchups = client.get_matchups("111", week=3)

    assert matchups == fixture


def test_get_players_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("players.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json=fixture)
        players = client.get_players()

    assert players == fixture


def test_get_players_with_filters(client: SleeperClient) -> None:
    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/players/nfl", json={})
        client.get_players(position="QB", active=True)

    assert m.last_request.qs == {"position": ["qb"], "active": ["true"]}
