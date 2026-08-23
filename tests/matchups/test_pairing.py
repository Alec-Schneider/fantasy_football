"""Tests for pairing weekly Sleeper matchup entries by matchup_id.

All tests operate on the pure, no-network :func:`pair_week_matchups` /
:func:`pair_season_matchups` functions directly against ``WeekMatchups``
values -- there is no HTTP-fetching wrapper to mock here (see
``pairing.py``'s module docstring).
"""

import pytest

from fantasy_analyzer.matchups import (
    MatchupPairing,
    WeekMatchups,
    pair_season_matchups,
    pair_week_matchups,
)


def _week(matchups: list[dict], week: int = 1, is_playoff: bool = False, season="2025"):
    return WeekMatchups(
        season=season, week=week, is_playoff=is_playoff, matchups=matchups
    )


# -------------------------
# pair_week_matchups
# -------------------------


def test_pairs_two_entries_sharing_a_matchup_id() -> None:
    """Toy example checked by hand: rosters 1 and 2 share matchup_id 1."""
    week = _week(
        [
            {"roster_id": 1, "matchup_id": 1, "points": 123.45},
            {"roster_id": 2, "matchup_id": 1, "points": 110.2},
        ]
    )

    pairings = pair_week_matchups(week)

    assert pairings == [
        MatchupPairing(
            season="2025",
            week=1,
            is_playoff=False,
            matchup_id=1,
            roster_1_id=1,
            roster_2_id=2,
            points_1=123.45,
            points_2=110.2,
        )
    ]


def test_pairing_is_ordered_by_ascending_roster_id_regardless_of_entry_order() -> None:
    """Roster 5's entry appears before roster 3's, but pairing puts 3 first."""
    week = _week(
        [
            {"roster_id": 5, "matchup_id": 9, "points": 50.0},
            {"roster_id": 3, "matchup_id": 9, "points": 60.0},
        ]
    )

    [pairing] = pair_week_matchups(week)

    assert (pairing.roster_1_id, pairing.roster_2_id) == (3, 5)
    assert (pairing.points_1, pairing.points_2) == (60.0, 50.0)


def test_multiple_matchups_in_a_week_are_all_paired() -> None:
    week = _week(
        [
            {"roster_id": 1, "matchup_id": 1, "points": 100.0},
            {"roster_id": 2, "matchup_id": 1, "points": 90.0},
            {"roster_id": 3, "matchup_id": 2, "points": 80.0},
            {"roster_id": 4, "matchup_id": 2, "points": 70.0},
        ]
    )

    pairings = pair_week_matchups(week)

    assert [(p.roster_1_id, p.roster_2_id) for p in pairings] == [(1, 2), (3, 4)]


def test_playoff_and_season_metadata_are_carried_through() -> None:
    week = _week(
        [
            {"roster_id": 1, "matchup_id": 1, "points": 100.0},
            {"roster_id": 2, "matchup_id": 1, "points": 90.0},
        ],
        week=16,
        is_playoff=True,
        season="2025",
    )

    [pairing] = pair_week_matchups(week)

    assert pairing.week == 16
    assert pairing.is_playoff is True
    assert pairing.season == "2025"


def test_bye_entry_with_null_matchup_id_is_unpaired() -> None:
    week = _week([{"roster_id": 7, "matchup_id": None, "points": 55.5}])

    [pairing] = pair_week_matchups(week)

    assert pairing.matchup_id is None
    assert pairing.roster_1_id == 7
    assert pairing.roster_2_id is None
    assert pairing.points_1 == 55.5
    assert pairing.points_2 is None


def test_multiple_byes_in_the_same_week_are_not_paired_with_each_other() -> None:
    week = _week(
        [
            {"roster_id": 7, "matchup_id": None, "points": 55.5},
            {"roster_id": 9, "matchup_id": None, "points": 61.0},
        ]
    )

    pairings = pair_week_matchups(week)

    assert len(pairings) == 2
    assert all(p.roster_2_id is None for p in pairings)
    assert [p.roster_1_id for p in pairings] == [7, 9]


def test_matchup_id_with_only_one_entry_is_incomplete_but_unpaired() -> None:
    """A non-null matchup_id missing its second roster stays unpaired,
    preserving the real matchup_id rather than discarding it."""
    week = _week([{"roster_id": 3, "matchup_id": 4, "points": 88.0}])

    [pairing] = pair_week_matchups(week)

    assert pairing.matchup_id == 4
    assert pairing.roster_1_id == 3
    assert pairing.roster_2_id is None
    assert pairing.points_2 is None


def test_matchup_id_with_more_than_two_entries_raises() -> None:
    week = _week(
        [
            {"roster_id": 1, "matchup_id": 1, "points": 100.0},
            {"roster_id": 2, "matchup_id": 1, "points": 90.0},
            {"roster_id": 3, "matchup_id": 1, "points": 80.0},
        ]
    )

    with pytest.raises(ValueError, match="matchup_id 1"):
        pair_week_matchups(week)


def test_missing_points_key_defaults_to_none() -> None:
    week = _week(
        [
            {"roster_id": 1, "matchup_id": 1},
            {"roster_id": 2, "matchup_id": 1, "points": 90.0},
        ]
    )

    [pairing] = pair_week_matchups(week)

    assert pairing.points_1 is None
    assert pairing.points_2 == 90.0


def test_empty_week_produces_no_pairings() -> None:
    assert pair_week_matchups(_week([])) == []


def test_real_matchups_fixture_pairs_the_two_rosters(load_sleeper_fixture) -> None:
    raw = load_sleeper_fixture("matchups.json")
    week = _week(raw)

    [pairing] = pair_week_matchups(week)

    assert (pairing.roster_1_id, pairing.roster_2_id) == (1, 2)
    assert (pairing.points_1, pairing.points_2) == (123.45, 110.2)


# -------------------------
# pair_season_matchups
# -------------------------


def test_pair_season_matchups_preserves_week_order() -> None:
    weeks = [
        _week(
            [
                {"roster_id": 1, "matchup_id": 1, "points": 100.0},
                {"roster_id": 2, "matchup_id": 1, "points": 90.0},
            ],
            week=1,
        ),
        _week(
            [
                {"roster_id": 1, "matchup_id": 1, "points": 95.0},
                {"roster_id": 3, "matchup_id": 1, "points": 85.0},
            ],
            week=2,
        ),
    ]

    pairings = pair_season_matchups(weeks)

    assert [(p.week, p.roster_1_id, p.roster_2_id) for p in pairings] == [
        (1, 1, 2),
        (2, 1, 3),
    ]


def test_pair_season_matchups_handles_empty_weeks() -> None:
    weeks = [_week([], week=1), _week([], week=2)]

    assert pair_season_matchups(weeks) == []
