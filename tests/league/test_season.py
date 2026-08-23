"""Tests for regular-season and playoff week boundary derivation.

These tests operate on already-normalized :class:`LeagueSettings` instances
-- no HTTP calls are made or mocked here, per AGENTS.md's separation of
data access from normalization.
"""

from fantasy_analyzer.league import (
    LeagueSettings,
    SeasonBoundaries,
    derive_season_boundaries,
    is_playoff_week,
    normalize_league_settings,
)


def _settings(playoff_week_start: int | None) -> LeagueSettings:
    return LeagueSettings(
        league_id="1",
        name="Test League",
        season="2025",
        season_type="regular",
        status="in_season",
        total_rosters=10,
        playoff_week_start=playoff_week_start,
    )


def test_derive_season_boundaries_from_fixture(load_sleeper_fixture) -> None:
    """Cross-checked by hand: fixture's playoff_week_start is 15.

    For an 18-week season, weeks 1-14 are regular season and weeks 15-18
    are playoffs.
    """
    raw_league = load_sleeper_fixture("league.json")
    settings = normalize_league_settings(raw_league)
    assert settings.playoff_week_start == 15

    boundaries = derive_season_boundaries(settings, total_weeks=18)

    assert isinstance(boundaries, SeasonBoundaries)
    assert boundaries.regular_season_weeks == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
    ]
    assert boundaries.playoff_weeks == [15, 16, 17, 18]
    assert boundaries.playoff_week_start == 15
    assert boundaries.total_weeks == 18


def test_derive_season_boundaries_normal_case_is_playoff_week() -> None:
    settings = _settings(playoff_week_start=15)
    boundaries = derive_season_boundaries(settings, total_weeks=18)

    assert is_playoff_week(14, boundaries) is False
    assert is_playoff_week(15, boundaries) is True
    assert is_playoff_week(18, boundaries) is True


def test_derive_season_boundaries_missing_playoff_week_start() -> None:
    """A missing/None playoff_week_start must not crash.

    With no reliable signal for where the postseason begins, the entire
    season is treated as regular season and playoff_weeks is empty.
    """
    settings = _settings(playoff_week_start=None)

    boundaries = derive_season_boundaries(settings, total_weeks=18)

    assert boundaries.regular_season_weeks == list(range(1, 19))
    assert boundaries.playoff_weeks == []
    assert boundaries.playoff_week_start is None
    assert all(not is_playoff_week(w, boundaries) for w in range(1, 19))


def test_derive_season_boundaries_playoff_week_start_at_total_weeks() -> None:
    """playoff_week_start equal to total_weeks yields a single playoff week."""
    settings = _settings(playoff_week_start=18)

    boundaries = derive_season_boundaries(settings, total_weeks=18)

    assert boundaries.regular_season_weeks == list(range(1, 18))
    assert boundaries.playoff_weeks == [18]


def test_derive_season_boundaries_playoff_week_start_beyond_total_weeks() -> None:
    """A misconfigured league where playoffs start after the season ends.

    playoff_weeks must be empty rather than raising.
    """
    settings = _settings(playoff_week_start=20)

    boundaries = derive_season_boundaries(settings, total_weeks=18)

    assert boundaries.regular_season_weeks == list(range(1, 19))
    assert boundaries.playoff_weeks == []


def test_derive_season_boundaries_playoff_week_start_of_one() -> None:
    """Degenerate case: the entire season is 'playoffs'.

    regular_season_weeks is empty rather than raising.
    """
    settings = _settings(playoff_week_start=1)

    boundaries = derive_season_boundaries(settings, total_weeks=18)

    assert boundaries.regular_season_weeks == []
    assert boundaries.playoff_weeks == list(range(1, 19))


def test_is_playoff_week_out_of_range_week_is_false() -> None:
    settings = _settings(playoff_week_start=15)
    boundaries = derive_season_boundaries(settings, total_weeks=18)

    assert is_playoff_week(0, boundaries) is False
    assert is_playoff_week(19, boundaries) is False
