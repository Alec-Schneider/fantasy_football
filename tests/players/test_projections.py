"""Tests for the provider-agnostic projection/ranking interface (FFA-072).

No concrete provider exists yet -- vendor integration is deliberately out of
scope for this ticket -- so these tests exercise
:class:`~fantasy_analyzer.players.projections.ProjectionProvider` via a
trivial in-memory fake, the projection analog of ``test_provider.py``'s
``FakePlayerStatsProvider``. No network access or vendor dependency is used
anywhere in this file.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fantasy_analyzer.players import (
    PROJECTION_IDENTITY_COLUMNS,
    ProjectionProvider,
    validate_projection_columns,
)


class FakeProjectionProvider:
    """A minimal in-memory :class:`ProjectionProvider`.

    Holds a small, hand-built projection table and serves
    ``projections(season, week)`` by filtering it -- exactly the shape a
    real future vendor provider must produce, with no real data source
    behind it. Deliberately does *not* inherit from anything: proving that
    plain structural conformance is enough is the point of using a
    ``Protocol`` (see the module docstring on
    ``fantasy_analyzer.players.projections``).
    """

    def __init__(self, rows: list[dict]) -> None:
        columns = PROJECTION_IDENTITY_COLUMNS + ["projected_points"]
        self._df = pd.DataFrame(rows, columns=columns)

    def projections(self, season: int, week: int) -> pd.DataFrame:
        matches = self._df[(self._df["season"] == season) & (self._df["week"] == week)]
        return matches.reset_index(drop=True)


FAKE_ROWS = [
    {
        "season": 2025,
        "week": 1,
        "source": "fake-vendor",
        "sleeper_player_id": "4984",
        "gsis_id": "00-0034857",
        "player_name": "Josh Allen",
        "position": "QB",
        "nfl_team": "BUF",
        "projected_points": 24.5,
    },
    {
        "season": 2025,
        "week": 1,
        "source": "fake-vendor",
        # No Sleeper<->nflverse crosswalk available yet (that's FFA-062) --
        # sleeper_player_id is legitimately None per the module docstring.
        "sleeper_player_id": None,
        "gsis_id": "00-0036355",
        "player_name": "Some Rookie",
        "position": "RB",
        "nfl_team": "SF",
        "projected_points": 6.1,
    },
    {
        "season": 2025,
        "week": 2,
        "source": "fake-vendor",
        "sleeper_player_id": "9001",
        "gsis_id": "00-0036900",
        "player_name": "Ja'Marr Chase",
        "position": "WR",
        "nfl_team": "CIN",
        "projected_points": 17.8,
    },
]


@pytest.fixture
def fake_provider() -> FakeProjectionProvider:
    return FakeProjectionProvider(FAKE_ROWS)


def test_fake_provider_satisfies_the_protocol_structurally(
    fake_provider: FakeProjectionProvider,
) -> None:
    """A plain object with a matching method conforms, with no inheritance."""
    assert isinstance(fake_provider, ProjectionProvider)


def test_projections_returns_rows_for_the_requested_week_only(
    fake_provider: FakeProjectionProvider,
) -> None:
    result = fake_provider.projections(season=2025, week=1)

    assert len(result) == 2
    assert set(result["week"]) == {1}
    assert list(result["player_name"]) == ["Josh Allen", "Some Rookie"]


def test_projections_result_carries_the_required_identity_columns(
    fake_provider: FakeProjectionProvider,
) -> None:
    result = fake_provider.projections(season=2025, week=1)

    assert list(result.columns[: len(PROJECTION_IDENTITY_COLUMNS)]) == (
        PROJECTION_IDENTITY_COLUMNS
    )
    # Providers may add their own additional projection-value columns beyond
    # the required identity prefix.
    assert "projected_points" in result.columns


def test_projections_allows_a_missing_sleeper_player_id(
    fake_provider: FakeProjectionProvider,
) -> None:
    """A provider with no ID crosswalk (FFA-062) may leave this unpopulated."""
    result = fake_provider.projections(season=2025, week=1)
    rookie = result[result["player_name"] == "Some Rookie"].iloc[0]

    assert pd.isna(rookie["sleeper_player_id"])
    assert rookie["gsis_id"] == "00-0036355"


def test_projections_for_a_week_with_no_data_returns_empty_frame(
    fake_provider: FakeProjectionProvider,
) -> None:
    """A week the provider has no projections for is an expected outcome, not
    an error."""
    result = fake_provider.projections(season=2025, week=99)

    assert result.empty
    assert list(result.columns[: len(PROJECTION_IDENTITY_COLUMNS)]) == (
        PROJECTION_IDENTITY_COLUMNS
    )


def test_a_player_with_no_projection_has_no_row(
    fake_provider: FakeProjectionProvider,
) -> None:
    """Absence of a row, not a None-filled sentinel row, marks "not projected"."""
    result = fake_provider.projections(season=2025, week=2)

    assert "Josh Allen" not in set(result["player_name"])
    assert len(result) == 1


def test_projections_carry_a_source_label(
    fake_provider: FakeProjectionProvider,
) -> None:
    """``source`` distinguishes rows from different vendors/methodologies."""
    result = fake_provider.projections(season=2025, week=1)

    assert set(result["source"]) == {"fake-vendor"}


def test_validate_projection_columns_accepts_a_conforming_frame(
    fake_provider: FakeProjectionProvider,
) -> None:
    result = fake_provider.projections(season=2025, week=1)

    validate_projection_columns(result)  # does not raise


def test_validate_projection_columns_rejects_a_missing_column() -> None:
    broken = pd.DataFrame(
        {column: [] for column in PROJECTION_IDENTITY_COLUMNS if column != "gsis_id"}
    )

    with pytest.raises(ValueError, match="gsis_id"):
        validate_projection_columns(broken)


def test_validate_projection_columns_rejects_out_of_order_columns() -> None:
    reordered = pd.DataFrame(
        columns=["week", "season"] + PROJECTION_IDENTITY_COLUMNS[2:]
    )

    with pytest.raises(ValueError, match="in order"):
        validate_projection_columns(reordered)
