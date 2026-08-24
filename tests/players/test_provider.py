"""Tests for the provider-agnostic player-stats interface (FFA-060).

No concrete provider exists yet -- FFA-061 (nflverse) is a separate,
not-yet-implemented ticket -- so these tests exercise
:class:`~fantasy_analyzer.players.provider.PlayerStatsProvider` via a
trivial in-memory fake, standing in for FFA-061's real implementation. No
network access or nflverse dependency is used anywhere in this file.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    PLAYER_WEEK_IDENTITY_COLUMNS,
    PlayerStatsProvider,
    validate_player_week_columns,
)


class FakePlayerStatsProvider:
    """A minimal in-memory :class:`PlayerStatsProvider`.

    Holds a small, hand-built player-week table and serves
    ``weekly_stats(season, week)`` by filtering it -- exactly the shape a
    real provider (e.g. FFA-061's nflverse provider) must produce, with no
    real data source behind it. Deliberately does *not* inherit from
    anything: proving that plain structural conformance is enough is the
    point of using a ``Protocol`` (see the module docstring on
    ``fantasy_analyzer.players.provider``).
    """

    def __init__(self, rows: list[dict]) -> None:
        columns = PLAYER_WEEK_IDENTITY_COLUMNS + ["passing_yds"]
        self._df = pd.DataFrame(rows, columns=columns)

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        matches = self._df[(self._df["season"] == season) & (self._df["week"] == week)]
        return matches.reset_index(drop=True)


FAKE_ROWS = [
    {
        "season": 2025,
        "week": 1,
        "sleeper_player_id": "4984",
        "gsis_id": "00-0034857",
        "player_name": "Josh Allen",
        "position": "QB",
        "nfl_team": "BUF",
        "passing_yds": 245,
    },
    {
        "season": 2025,
        "week": 1,
        # No Sleeper<->nflverse crosswalk available yet (that's FFA-062) --
        # sleeper_player_id is legitimately None per the module docstring.
        "sleeper_player_id": None,
        "gsis_id": "00-0036355",
        "player_name": "Some Rookie",
        "position": "RB",
        "nfl_team": "SF",
        "passing_yds": 0,
    },
    {
        "season": 2025,
        "week": 2,
        "sleeper_player_id": "9001",
        "gsis_id": "00-0036900",
        "player_name": "Ja'Marr Chase",
        "position": "WR",
        "nfl_team": "CIN",
        "passing_yds": 0,
    },
]


@pytest.fixture
def fake_provider() -> FakePlayerStatsProvider:
    return FakePlayerStatsProvider(FAKE_ROWS)


def test_fake_provider_satisfies_the_protocol_structurally(
    fake_provider: FakePlayerStatsProvider,
) -> None:
    """A plain object with a matching method conforms, with no inheritance."""
    assert isinstance(fake_provider, PlayerStatsProvider)


def test_weekly_stats_returns_rows_for_the_requested_week_only(
    fake_provider: FakePlayerStatsProvider,
) -> None:
    result = fake_provider.weekly_stats(season=2025, week=1)

    assert len(result) == 2
    assert set(result["week"]) == {1}
    assert list(result["player_name"]) == ["Josh Allen", "Some Rookie"]


def test_weekly_stats_result_carries_the_required_identity_columns(
    fake_provider: FakePlayerStatsProvider,
) -> None:
    result = fake_provider.weekly_stats(season=2025, week=1)

    assert list(result.columns[: len(PLAYER_WEEK_IDENTITY_COLUMNS)]) == (
        PLAYER_WEEK_IDENTITY_COLUMNS
    )
    # Providers may add their own additional stat columns beyond the
    # required identity prefix.
    assert "passing_yds" in result.columns


def test_weekly_stats_allows_a_missing_sleeper_player_id(
    fake_provider: FakePlayerStatsProvider,
) -> None:
    """A provider with no ID crosswalk (FFA-062) may leave this unpopulated."""
    result = fake_provider.weekly_stats(season=2025, week=1)
    rookie = result[result["player_name"] == "Some Rookie"].iloc[0]

    assert pd.isna(rookie["sleeper_player_id"])
    assert rookie["gsis_id"] == "00-0036355"


def test_weekly_stats_for_a_week_with_no_data_returns_empty_frame(
    fake_provider: FakePlayerStatsProvider,
) -> None:
    """A week the provider has no data for is an expected outcome, not an error."""
    result = fake_provider.weekly_stats(season=2025, week=99)

    assert result.empty
    assert list(result.columns[: len(PLAYER_WEEK_IDENTITY_COLUMNS)]) == (
        PLAYER_WEEK_IDENTITY_COLUMNS
    )


def test_a_player_who_did_not_play_has_no_row(
    fake_provider: FakePlayerStatsProvider,
) -> None:
    """Absence of a row, not a None-filled sentinel row, marks "no data"."""
    result = fake_provider.weekly_stats(season=2025, week=2)

    assert "Josh Allen" not in set(result["player_name"])
    assert len(result) == 1


def test_validate_player_week_columns_accepts_a_conforming_frame(
    fake_provider: FakePlayerStatsProvider,
) -> None:
    result = fake_provider.weekly_stats(season=2025, week=1)

    validate_player_week_columns(result)  # does not raise


def test_validate_player_week_columns_rejects_a_missing_column() -> None:
    broken = pd.DataFrame(
        {column: [] for column in PLAYER_WEEK_IDENTITY_COLUMNS if column != "gsis_id"}
    )

    with pytest.raises(ValueError, match="gsis_id"):
        validate_player_week_columns(broken)


def test_validate_player_week_columns_rejects_out_of_order_columns() -> None:
    reordered = pd.DataFrame(
        columns=["week", "season"] + PLAYER_WEEK_IDENTITY_COLUMNS[2:]
    )

    with pytest.raises(ValueError, match="in order"):
        validate_player_week_columns(reordered)
