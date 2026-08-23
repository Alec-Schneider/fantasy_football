"""Tests for team/owner normalization.

These tests operate on already-fetched raw Sleeper dicts -- no HTTP calls
are made or mocked here, per AGENTS.md's separation of data access from
normalization.
"""

from fantasy_analyzer.league import build_team_mapping


def test_build_team_mapping_resolves_owner_from_fixtures(load_sleeper_fixture) -> None:
    users = load_sleeper_fixture("users.json")
    rosters = load_sleeper_fixture("rosters.json")

    mapping = build_team_mapping(users, rosters)

    assert list(mapping.columns) == [
        "roster_id",
        "owner_id",
        "display_name",
        "team_name",
    ]
    assert len(mapping) == len(rosters)

    row = mapping.loc[mapping["roster_id"] == 1].iloc[0]
    assert row["owner_id"] == "123456789012345678"
    assert row["display_name"] == "Test User"
    # metadata.team_name is set for this user -> used as-is.
    assert row["team_name"] == "The Testers"


def test_build_team_mapping_falls_back_to_display_name_when_team_name_missing(
    load_sleeper_fixture,
) -> None:
    users = load_sleeper_fixture("users.json")
    rosters = load_sleeper_fixture("rosters.json")

    mapping = build_team_mapping(users, rosters)

    row = mapping.loc[mapping["roster_id"] == 2].iloc[0]
    # This user's metadata has no team_name -> falls back to display_name.
    assert row["owner_id"] == "223456789012345678"
    assert row["display_name"] == "Other User"
    assert row["team_name"] == "Other User"


def test_build_team_mapping_handles_roster_with_no_owner() -> None:
    users = [
        {
            "user_id": "u1",
            "display_name": "Alice",
            "metadata": {"team_name": "Alice's Army"},
        }
    ]
    rosters = [{"roster_id": 1, "owner_id": None}]

    mapping = build_team_mapping(users, rosters)

    row = mapping.iloc[0]
    assert row["roster_id"] == 1
    assert row["owner_id"] is None
    assert row["display_name"] is None
    assert row["team_name"] is None


def test_build_team_mapping_handles_owner_id_not_in_users() -> None:
    """An owner_id that doesn't match any league user must not crash."""
    users = [{"user_id": "u1", "display_name": "Alice", "metadata": {}}]
    rosters = [{"roster_id": 1, "owner_id": "orphaned-user-id"}]

    mapping = build_team_mapping(users, rosters)

    row = mapping.iloc[0]
    assert row["roster_id"] == 1
    assert row["owner_id"] == "orphaned-user-id"
    assert row["display_name"] is None
    assert row["team_name"] is None


def test_build_team_mapping_empty_inputs_produce_empty_frame() -> None:
    mapping = build_team_mapping(users=[], rosters=[])

    assert mapping.empty
    assert list(mapping.columns) == [
        "roster_id",
        "owner_id",
        "display_name",
        "team_name",
    ]


def test_build_team_mapping_uses_ids_not_names_as_join_key() -> None:
    """Display/team names must remain labels -- never the join key.

    Two users could theoretically share a display_name; the mapping must
    still resolve each roster to the correct owner via user_id/owner_id.
    """
    users = [
        {"user_id": "u1", "display_name": "Same Name", "metadata": {}},
        {"user_id": "u2", "display_name": "Same Name", "metadata": {}},
    ]
    rosters = [
        {"roster_id": 1, "owner_id": "u1"},
        {"roster_id": 2, "owner_id": "u2"},
    ]

    mapping = build_team_mapping(users, rosters)

    assert mapping.loc[mapping["roster_id"] == 1, "owner_id"].iloc[0] == "u1"
    assert mapping.loc[mapping["roster_id"] == 2, "owner_id"].iloc[0] == "u2"
