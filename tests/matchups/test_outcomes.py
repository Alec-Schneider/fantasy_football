"""Tests for deriving winner/loser/tie/margin matchup outcomes (FFA-032).

All tests operate on the pure, no-network :func:`derive_matchup_outcome` /
:func:`derive_season_outcomes` functions directly against hand-built
``MatchupPairing`` values, so the expected winner/margin/differential
numbers can be verified by hand arithmetic per AGENTS.md's analytics-ticket
requirement for a hand-checkable toy example.
"""

from fantasy_analyzer.matchups import (
    MatchupOutcome,
    MatchupPairing,
    derive_matchup_outcome,
    derive_season_outcomes,
)


def _pairing(
    roster_1_id: int = 1,
    roster_2_id: int | None = 2,
    points_1: float | None = 100.0,
    points_2: float | None = 90.0,
    matchup_id: int | None = 1,
    week: int = 1,
    is_playoff: bool = False,
    season: str | None = "2025",
) -> MatchupPairing:
    return MatchupPairing(
        season=season,
        week=week,
        is_playoff=is_playoff,
        matchup_id=matchup_id,
        roster_1_id=roster_1_id,
        roster_2_id=roster_2_id,
        points_1=points_1,
        points_2=points_2,
    )


# -------------------------
# derive_matchup_outcome
# -------------------------


def test_roster_1_wins_toy_example_hand_computed() -> None:
    """Toy example checked by hand: roster 1 scores 123.45, roster 2 110.2.

    point_differential = 123.45 - 110.2 = 13.25
    margin              = abs(13.25)     = 13.25
    """
    pairing = _pairing(roster_1_id=1, roster_2_id=2, points_1=123.45, points_2=110.2)

    outcome = derive_matchup_outcome(pairing)

    assert outcome.winner_roster_id == 1
    assert outcome.loser_roster_id == 2
    assert outcome.is_tie is False
    assert outcome.margin == 13.25
    assert outcome.point_differential == 13.25


def test_roster_2_wins_toy_example_hand_computed() -> None:
    """roster 2 scores more: point_differential is negative, margin stays positive.

    point_differential = 90.0 - 110.0 = -20.0
    margin              = abs(-20.0)   = 20.0
    """
    pairing = _pairing(roster_1_id=1, roster_2_id=2, points_1=90.0, points_2=110.0)

    outcome = derive_matchup_outcome(pairing)

    assert outcome.winner_roster_id == 2
    assert outcome.loser_roster_id == 1
    assert outcome.is_tie is False
    assert outcome.margin == 20.0
    assert outcome.point_differential == -20.0


def test_tie_has_no_winner_or_loser() -> None:
    """Equal points: is_tie True, winner/loser both None, margin 0.0."""
    pairing = _pairing(roster_1_id=1, roster_2_id=2, points_1=100.0, points_2=100.0)

    outcome = derive_matchup_outcome(pairing)

    assert outcome.is_tie is True
    assert outcome.winner_roster_id is None
    assert outcome.loser_roster_id is None
    assert outcome.margin == 0.0
    assert outcome.point_differential == 0.0


def test_playoff_and_season_metadata_are_carried_through() -> None:
    pairing = _pairing(week=16, is_playoff=True, season="2025")

    outcome = derive_matchup_outcome(pairing)

    assert outcome.week == 16
    assert outcome.is_playoff is True
    assert outcome.season == "2025"


def test_pairing_fields_are_carried_through_unchanged() -> None:
    pairing = _pairing(
        roster_1_id=3, roster_2_id=7, points_1=88.8, points_2=77.7, matchup_id=42
    )

    outcome = derive_matchup_outcome(pairing)

    assert outcome.matchup_id == 42
    assert outcome.roster_1_id == 3
    assert outcome.roster_2_id == 7
    assert outcome.points_1 == 88.8
    assert outcome.points_2 == 77.7


def test_bye_entry_has_no_outcome() -> None:
    """A bye (no roster_2_id) has nothing to compare against."""
    pairing = _pairing(roster_1_id=7, roster_2_id=None, points_1=55.5, points_2=None)

    outcome = derive_matchup_outcome(pairing)

    assert outcome.winner_roster_id is None
    assert outcome.loser_roster_id is None
    assert outcome.is_tie is False
    assert outcome.margin is None
    assert outcome.point_differential is None


def test_incomplete_matchup_id_with_only_one_roster_has_no_outcome() -> None:
    """A non-null matchup_id missing its second roster is treated like a bye."""
    pairing = _pairing(
        roster_1_id=3, roster_2_id=None, points_1=88.0, points_2=None, matchup_id=4
    )

    outcome = derive_matchup_outcome(pairing)

    assert outcome.matchup_id == 4
    assert outcome.winner_roster_id is None
    assert outcome.loser_roster_id is None
    assert outcome.margin is None
    assert outcome.point_differential is None


def test_missing_points_produces_no_outcome_even_with_both_rosters_present() -> None:
    """Both rosters known, but one side's points are missing (unloaded week)."""
    pairing = _pairing(roster_1_id=1, roster_2_id=2, points_1=None, points_2=90.0)

    outcome = derive_matchup_outcome(pairing)

    assert outcome.winner_roster_id is None
    assert outcome.loser_roster_id is None
    assert outcome.is_tie is False
    assert outcome.margin is None
    assert outcome.point_differential is None


def test_derive_matchup_outcome_returns_matchup_outcome_instance() -> None:
    assert isinstance(derive_matchup_outcome(_pairing()), MatchupOutcome)


def test_real_matchups_fixture_produces_expected_winner(load_sleeper_fixture) -> None:
    """Integration check against the shared Sleeper matchups fixture.

    Fixture has roster 1 at 123.45 points and roster 2 at 110.2 points, so
    roster 1 should win by a margin of 13.25.
    """
    from fantasy_analyzer.matchups import WeekMatchups, pair_week_matchups

    raw = load_sleeper_fixture("matchups.json")
    week = WeekMatchups(season="2025", week=1, is_playoff=False, matchups=raw)
    [pairing] = pair_week_matchups(week)

    outcome = derive_matchup_outcome(pairing)

    assert outcome.winner_roster_id == 1
    assert outcome.loser_roster_id == 2
    assert outcome.margin == 13.25
    assert outcome.point_differential == 13.25


# -------------------------
# derive_season_outcomes
# -------------------------


def test_derive_season_outcomes_preserves_order() -> None:
    pairings = [
        _pairing(roster_1_id=1, roster_2_id=2, points_1=100.0, points_2=90.0, week=1),
        _pairing(roster_1_id=1, roster_2_id=3, points_1=80.0, points_2=95.0, week=2),
    ]

    outcomes = derive_season_outcomes(pairings)

    assert [(o.week, o.winner_roster_id) for o in outcomes] == [(1, 1), (2, 3)]


def test_derive_season_outcomes_handles_empty_list() -> None:
    assert derive_season_outcomes([]) == []
