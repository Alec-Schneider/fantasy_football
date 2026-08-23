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


def test_get_league_surfaces_metadata(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """League metadata needed for a LeagueSnapshot is present in the response."""
    fixture = load_sleeper_fixture("league.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111", json=fixture)
        league = client.get_league("111")

    assert league["name"] == "Test League"
    assert league["season"] == "2025"
    assert league["status"] == "in_season"
    assert league["total_rosters"] == 10


def test_get_league_surfaces_rules_settings(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """The league's ``settings`` block (waivers, playoffs, etc.) is present."""
    fixture = load_sleeper_fixture("league.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111", json=fixture)
        league = client.get_league("111")

    settings = league["settings"]
    assert settings["num_teams"] == 10
    assert settings["playoff_teams"] == 6
    assert settings["playoff_week_start"] == 15
    assert "waiver_type" in settings
    assert "trade_deadline" in settings


def test_get_league_surfaces_scoring_settings(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """The league's ``scoring_settings`` block is present with real categories."""
    fixture = load_sleeper_fixture("league.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111", json=fixture)
        league = client.get_league("111")

    scoring_settings = league["scoring_settings"]
    assert scoring_settings["pass_td"] == 4
    assert scoring_settings["rec"] == 0.5
    assert scoring_settings["rush_td"] == 6
    assert scoring_settings["fum_lost"] == -2


def test_get_league_surfaces_roster_positions(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """The league's ``roster_positions`` list (starting slots + bench) is present."""
    fixture = load_sleeper_fixture("league.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111", json=fixture)
        league = client.get_league("111")

    roster_positions = league["roster_positions"]
    assert isinstance(roster_positions, list)
    assert roster_positions.count("QB") == 1
    assert roster_positions.count("BN") == 6
    assert "FLEX" in roster_positions


def test_get_rosters_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("rosters.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/rosters", json=fixture)
        rosters = client.get_rosters("111")

    assert rosters == fixture


def test_get_rosters_surfaces_roster_settings_and_owner_id(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """Each roster exposes its owner_id (for linking to users) and record."""
    fixture = load_sleeper_fixture("rosters.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/rosters", json=fixture)
        rosters = client.get_rosters("111")

    for roster in rosters:
        assert "roster_id" in roster
        assert "owner_id" in roster
        assert "players" in roster
        assert "starters" in roster
        record = roster["settings"]
        assert {"wins", "losses", "ties"} <= record.keys()


def test_get_users_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("users.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/users", json=fixture)
        users = client.get_users("111")

    assert users == fixture


def test_get_users_surfaces_owner_display_fields(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """Each league user exposes the fields needed to label a roster's owner."""
    fixture = load_sleeper_fixture("users.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/users", json=fixture)
        users = client.get_users("111")

    for user in users:
        assert "user_id" in user
        assert "display_name" in user


def test_roster_owner_id_links_to_league_user_id(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """Roster owner_id values must resolve to a league user's user_id."""
    rosters_fixture = load_sleeper_fixture("rosters.json")
    users_fixture = load_sleeper_fixture("users.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/rosters", json=rosters_fixture)
        m.get(f"{SleeperClient.BASE_URL}/league/111/users", json=users_fixture)
        rosters = client.get_rosters("111")
        users = client.get_users("111")

    user_ids = {user["user_id"] for user in users}
    for roster in rosters:
        assert roster["owner_id"] in user_ids


def test_get_matchups_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("matchups.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/matchups/3", json=fixture)
        matchups = client.get_matchups("111", week=3)

    assert matchups == fixture


def test_get_winners_bracket_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("winners_bracket.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/winners_bracket", json=fixture)
        bracket = client.get_winners_bracket("111")

    assert bracket == fixture


def test_get_winners_bracket_surfaces_matchup_structure(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """Bracket matchups expose round, matchup id, and participant roster ids."""
    fixture = load_sleeper_fixture("winners_bracket.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/winners_bracket", json=fixture)
        bracket = client.get_winners_bracket("111")

    for matchup in bracket:
        assert {"r", "m", "t1", "t2"} <= matchup.keys()

    # The championship game carries a placement marker.
    championship = [m_ for m_ in bracket if m_.get("p") == 1]
    assert len(championship) == 1


def test_get_losers_bracket_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("losers_bracket.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/losers_bracket", json=fixture)
        bracket = client.get_losers_bracket("111")

    assert bracket == fixture


def test_get_transactions_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("transactions.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/transactions/3", json=fixture)
        transactions = client.get_transactions("111", week=3)

    assert transactions == fixture


def test_get_transactions_covers_representative_types(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """Waiver, free-agent, and trade transactions all parse from the fixture."""
    fixture = load_sleeper_fixture("transactions.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/transactions/3", json=fixture)
        transactions = client.get_transactions("111", week=3)

    types = {txn["type"] for txn in transactions}
    assert types == {"waiver", "free_agent", "trade"}

    for txn in transactions:
        assert "transaction_id" in txn
        assert "roster_ids" in txn
        assert "status" in txn

    # A free-agent add may have no corresponding drop.
    free_agent = next(t for t in transactions if t["type"] == "free_agent")
    assert free_agent["drops"] is None


def test_get_drafts_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("drafts.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/drafts", json=fixture)
        drafts = client.get_drafts("111")

    assert drafts == fixture


def test_get_drafts_surfaces_draft_metadata(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """Each draft exposes its id, type, status, and slot-to-roster mapping."""
    fixture = load_sleeper_fixture("drafts.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/111/drafts", json=fixture)
        drafts = client.get_drafts("111")

    for draft in drafts:
        assert "draft_id" in draft
        assert draft["type"] == "snake"
        assert draft["status"] == "complete"
        assert "slot_to_roster_id" in draft


def test_get_draft_picks_hits_expected_endpoint(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    fixture = load_sleeper_fixture("draft_picks.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/draft/999/picks", json=fixture)
        picks = client.get_draft_picks("999")

    assert picks == fixture


def test_get_draft_picks_surfaces_pick_details(
    client: SleeperClient, load_sleeper_fixture
) -> None:
    """Each pick links a player_id to a roster_id with round/pick ordering."""
    fixture = load_sleeper_fixture("draft_picks.json")

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/draft/999/picks", json=fixture)
        picks = client.get_draft_picks("999")

    pick_numbers = [pick["pick_no"] for pick in picks]
    assert pick_numbers == sorted(pick_numbers)

    for pick in picks:
        assert "round" in pick
        assert "player_id" in pick
        assert "roster_id" in pick
        assert "picked_by" in pick


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
