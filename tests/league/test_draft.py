"""Tests for draft pick normalization.

The composition core (:func:`build_normalized_draft_picks`) is tested
purely, on already-fetched raw Sleeper dicts -- no HTTP calls are made or
mocked here, per AGENTS.md's separation of data access from normalization.
The thin fetching wrapper (:func:`load_league_draft`) is exercised via
``requests_mock`` against sanitized fixture responses -- the live Sleeper
API is never contacted.
"""

import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.league import build_normalized_draft_picks, load_league_draft
from fantasy_analyzer.league.draft import NORMALIZED_DRAFT_PICK_COLUMNS
from fantasy_analyzer.league.teams import build_team_mapping
from fantasy_analyzer.sleeper import SleeperClient

# -------------------------
# build_normalized_draft_picks (pure core)
# -------------------------


def test_build_normalized_draft_picks_from_fixtures(load_sleeper_fixture) -> None:
    users = load_sleeper_fixture("users.json")
    rosters = load_sleeper_fixture("rosters.json")
    raw_picks = load_sleeper_fixture("draft_picks.json")
    teams_df = build_team_mapping(users, rosters)

    picks_df = build_normalized_draft_picks(
        raw_picks,
        teams_df,
        season=2025,
        league_id="111111111111111111",
        draft_id="999999999999999999",
    )

    assert list(picks_df.columns) == NORMALIZED_DRAFT_PICK_COLUMNS
    assert len(picks_df) == len(raw_picks)

    # Hand-check pick_no=1 -> roster_id=1 -> owner "123456789012345678" ->
    # team_name "The Testers" (fixture: users.json metadata.team_name).
    row = picks_df.loc[picks_df["pick_no"] == 1].iloc[0]
    assert row["season"] == 2025
    assert row["league_id"] == "111111111111111111"
    assert row["draft_id"] == "999999999999999999"
    assert row["round"] == 1
    assert row["draft_slot"] == 1
    assert row["roster_id"] == 1
    assert row["owner_id"] == "123456789012345678"
    assert row["team_name"] == "The Testers"
    assert row["sleeper_player_id"] == "1000"
    assert isinstance(row["sleeper_player_id"], str)
    assert row["player_name"] == "Test Playerone"
    assert row["position"] == "RB"
    assert row["nfl_team"] == "TST"
    assert row["is_keeper"] is None

    # pick_no=3 -> roster_id=2 -> owner "223456789012345678" -> team_name
    # falls back to display_name "Other User" (no metadata.team_name set).
    row3 = picks_df.loc[picks_df["pick_no"] == 3].iloc[0]
    assert row3["roster_id"] == 2
    assert row3["owner_id"] == "223456789012345678"
    assert row3["team_name"] == "Other User"
    assert row3["sleeper_player_id"] == "2001"
    assert row3["player_name"] == "Test Playerthree"
    assert row3["position"] == "QB"


def test_build_normalized_draft_picks_preserves_is_keeper_flag(
    load_sleeper_fixture,
) -> None:
    """A keeper pick's ``is_keeper=True`` must survive normalization as-is."""
    users = load_sleeper_fixture("users.json")
    rosters = load_sleeper_fixture("rosters.json")
    raw_picks = load_sleeper_fixture("draft_picks.json")
    teams_df = build_team_mapping(users, rosters)

    keeper_pick = dict(raw_picks[0])
    keeper_pick["is_keeper"] = True
    keeper_pick["pick_no"] = 99

    picks_df = build_normalized_draft_picks(
        [keeper_pick],
        teams_df,
        season=2025,
        league_id="111111111111111111",
        draft_id="999999999999999999",
    )

    assert bool(picks_df.iloc[0]["is_keeper"]) is True


def test_build_normalized_draft_picks_missing_metadata_falls_back_to_none() -> None:
    teams_df = build_team_mapping(
        users=[{"user_id": "u1", "display_name": "Alice", "metadata": {}}],
        rosters=[{"roster_id": 1, "owner_id": "u1"}],
    )
    raw_picks = [
        {
            "round": 1,
            "pick_no": 1,
            "draft_slot": 1,
            "roster_id": 1,
            "player_id": "9999",
            "is_keeper": None,
        }
    ]

    picks_df = build_normalized_draft_picks(
        raw_picks, teams_df, season=2025, league_id="1", draft_id="d1"
    )

    row = picks_df.iloc[0]
    assert row["player_name"] is None
    assert row["position"] is None
    assert row["nfl_team"] is None
    assert row["sleeper_player_id"] == "9999"


def test_build_normalized_draft_picks_raises_on_unknown_roster_id(
    load_sleeper_fixture,
) -> None:
    """A pick referencing a roster_id absent from teams_df must not be dropped."""
    users = load_sleeper_fixture("users.json")
    rosters = load_sleeper_fixture("rosters.json")
    teams_df = build_team_mapping(users, rosters)

    raw_picks = [
        {
            "round": 1,
            "pick_no": 1,
            "draft_slot": 1,
            "roster_id": 999,
            "player_id": "1000",
            "is_keeper": None,
            "metadata": {"first_name": "Test", "last_name": "Playerone"},
        }
    ]

    with pytest.raises(ValueError, match="999"):
        build_normalized_draft_picks(
            raw_picks, teams_df, season=2025, league_id="1", draft_id="d1"
        )


def test_build_normalized_draft_picks_empty_inputs_produce_empty_frame() -> None:
    teams_df = build_team_mapping(users=[], rosters=[])

    picks_df = build_normalized_draft_picks(
        [], teams_df, season=2025, league_id="1", draft_id="d1"
    )

    assert picks_df.empty
    assert list(picks_df.columns) == NORMALIZED_DRAFT_PICK_COLUMNS


# -------------------------
# load_league_draft (thin fetching wrapper)
# -------------------------


def test_load_league_draft_resolves_matching_draft_and_picks(
    load_sleeper_fixture,
) -> None:
    raw_league = load_sleeper_fixture("league.json")
    raw_drafts = load_sleeper_fixture("drafts.json")
    raw_picks = load_sleeper_fixture("draft_picks.json")

    league_id = raw_league["league_id"]
    draft_id = raw_league["draft_id"]
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}", json=raw_league)
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}/drafts", json=raw_drafts)
        m.get(f"{SleeperClient.BASE_URL}/draft/{draft_id}/picks", json=raw_picks)

        draft, picks = load_league_draft(client, league_id)

    assert draft["draft_id"] == draft_id
    assert picks == raw_picks


def test_load_league_draft_raises_when_league_has_no_draft_id() -> None:
    raw_league = {"league_id": "1", "draft_id": None}
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/1", json=raw_league)

        with pytest.raises(ValueError, match="no associated draft_id"):
            load_league_draft(client, "1")


def test_load_league_draft_raises_when_no_draft_matches(load_sleeper_fixture) -> None:
    raw_league = load_sleeper_fixture("league.json")
    league_id = raw_league["league_id"]
    client = SleeperClient()

    with requests_mock_lib.Mocker() as m:
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}", json=raw_league)
        # No draft in this list matches the league's draft_id.
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}/drafts", json=[])

        with pytest.raises(ValueError, match="No draft with draft_id"):
            load_league_draft(client, league_id)
