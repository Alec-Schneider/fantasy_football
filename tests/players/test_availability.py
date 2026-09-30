"""Tests for injury/bye availability (FFA-107).

Every case mirrors a line of the module docstring's worked example or its
status table, so the expected values are checkable by reading the rule.
"""

from __future__ import annotations

import pandas as pd

from fantasy_analyzer.players.availability import (
    AVAILABILITY_COLUMNS,
    DEFAULT_INJURY_WEEKS_OUT,
    FLAGGED_INJURY_STATUSES,
    LONG_TERM_INJURY_STATUSES,
    UNAVAILABLE_INJURY_STATUSES,
    add_availability,
    injury_weeks_out,
    is_available,
    normalize_injury_status,
    unavailable_weeks,
)

#: Every injury_status value in the 2026-09-29 Sleeper catalog.
LIVE_CATALOG_STATUSES = {
    None,
    "Questionable",
    "IR",
    "Out",
    "NA",
    "PUP",
    "Sus",
    "COV",
    "DNR",
    "",
}


def test_unavailable_statuses_cover_the_live_catalog() -> None:
    """Every live status except healthy/Questionable rules a player out.

    ``Sus`` is the regression case: the dashboard's old constant carried
    only ``Suspended``, so a suspended player would have been started.
    """
    ruled_out = {
        status
        for status in LIVE_CATALOG_STATUSES
        if normalize_injury_status(status) in UNAVAILABLE_INJURY_STATUSES
    }
    assert ruled_out == {"IR", "Out", "NA", "PUP", "Sus", "COV", "DNR"}
    assert {"Sus", "Suspended", "Doubtful"} <= UNAVAILABLE_INJURY_STATUSES
    assert "Questionable" not in UNAVAILABLE_INJURY_STATUSES
    assert "Questionable" in FLAGGED_INJURY_STATUSES


def test_long_term_statuses_are_the_multi_week_ones() -> None:
    assert LONG_TERM_INJURY_STATUSES == {
        status for status, weeks in DEFAULT_INJURY_WEEKS_OUT.items() if weeks > 1
    }
    assert "Out" not in LONG_TERM_INJURY_STATUSES
    assert {"IR", "PUP", "NA", "Sus"} <= LONG_TERM_INJURY_STATUSES


def test_normalize_injury_status_missing_values() -> None:
    assert normalize_injury_status(None) is None
    assert normalize_injury_status(float("nan")) is None
    assert normalize_injury_status("") is None
    assert normalize_injury_status("  ") is None
    assert normalize_injury_status(" Out ") == "Out"


def test_injury_weeks_out() -> None:
    assert injury_weeks_out("Out") == 1
    assert injury_weeks_out("IR") == 4
    assert injury_weeks_out("Questionable") == 0
    assert injury_weeks_out(None) == 0
    # Unknown strings are not evidence of absence.
    assert injury_weeks_out("Probable") == 0
    assert injury_weeks_out("IR", weeks_out={"IR": 14}) == 14


def test_is_available_worked_example() -> None:
    """The module docstring's example, at current_week = 4."""
    # Out with a week-9 bye: misses 4 and 9 only.
    out = [w for w in range(4, 15) if not is_available("Out", 9, w, current_week=4)]
    assert out == [4, 9]
    # IR with a week-6 bye: misses 4-7; the bye falls inside that.
    ir = [w for w in range(4, 15) if not is_available("IR", 6, w, current_week=4)]
    assert ir == [4, 5, 6, 7]
    # Questionable, no bye: misses nothing.
    assert all(
        is_available("Questionable", None, w, current_week=4) for w in range(4, 15)
    )


def test_injury_never_rules_out_a_past_week() -> None:
    assert is_available("Out", None, 3, current_week=4)


def test_bye_week_types() -> None:
    """Byes arrive as ints, floats, NaN or None depending on the frame."""
    assert not is_available(None, 9.0, 9, current_week=4)
    assert is_available(None, float("nan"), 9, current_week=4)
    assert is_available(None, None, 9, current_week=4)


def test_unavailable_weeks() -> None:
    assert unavailable_weeks("Out", 9, range(4, 15), current_week=4) == {4, 9}
    assert unavailable_weeks(None, None, range(4, 15), current_week=4) == frozenset()


def test_add_availability_columns_and_reasons() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b", "c", "d", "e"],
            "injury_status": ["Out", None, "Questionable", "IR", "Sus"],
            "bye_week": [None, 4, None, 4, None],
        }
    )
    result = add_availability(frame, 4)

    assert list(result.columns[-3:]) == AVAILABILITY_COLUMNS
    assert list(result["available"]) == [False, False, True, False, False]
    assert list(result["on_bye"]) == [False, True, False, True, False]
    # Injury wins over the bye when both apply.
    assert list(result["unavailable_reason"]) == ["Out", "Bye", None, "IR", "Sus"]
    assert result["available"].dtype == bool


def test_add_availability_without_optional_columns() -> None:
    result = add_availability(pd.DataFrame({"player_id": ["a"]}), 4)
    assert bool(result.loc[0, "available"]) is True
    assert result.loc[0, "unavailable_reason"] is None


def test_add_availability_empty_frame() -> None:
    result = add_availability(pd.DataFrame({"player_id": []}), 4)
    assert result.empty
    assert set(AVAILABILITY_COLUMNS) <= set(result.columns)
