"""Tests for the league head-to-head matrix (FFA-041).

All tests operate on hand-built inputs -- no HTTP calls, no fixtures with
opaque values -- so every expected matrix cell can be verified by hand
arithmetic against the toy season described in ``_toy_rows``, per AGENTS.md's
analytics-ticket requirement for a hand-checkable toy example.

Two input styles are used deliberately:

- The main toy example runs real ``season_matchup_df`` rows through
  :func:`build_head_to_head_records` first, proving the matrix consumes
  FFA-040's actual output shape.
- Edge cases that FFA-040 cannot itself produce (an asymmetric,
  hand-filtered record set) build the head-to-head DataFrame directly via
  ``_h2h_df``/``_h2h_row``.
"""

import pandas as pd

from fantasy_analyzer.analytics import (
    HEAD_TO_HEAD_COLUMNS,
    HEAD_TO_HEAD_MATRIX_DIAGONAL,
    HEAD_TO_HEAD_MATRIX_NO_MEETING,
    HeadToHeadCell,
    build_head_to_head_matrix,
    build_head_to_head_records,
    format_head_to_head_matrix,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _matchup_row(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    winner: int | None,
    loser: int | None,
    is_tie: bool = False,
    is_playoff: bool = False,
    week: int = 1,
    matchup_id: int | None = 1,
    season: str = "2025",
    owner_1: str | None = None,
    owner_2: str | None = None,
) -> dict:
    margin = None
    point_differential = None
    if points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": owner_1,
        "owner_2": owner_2,
        "points_1": points_1,
        "points_2": points_2,
        "winner": winner,
        "loser": loser,
        "is_tie": is_tie,
        "margin": margin,
        "point_differential": point_differential,
    }


def _season_matchup_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=SEASON_MATCHUP_COLUMNS)
    return pd.DataFrame(rows, columns=SEASON_MATCHUP_COLUMNS)


def _teams_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["roster_id", "owner_id", "display_name", "team_name"]
    return pd.DataFrame(rows, columns=columns)


def _team_row(roster_id: int, name: str) -> dict:
    return {
        "roster_id": roster_id,
        "owner_id": f"u{roster_id}",
        "display_name": name,
        "team_name": name,
    }


def _h2h_row(
    roster_id: int,
    opponent_roster_id: int,
    meetings: int,
    wins: int,
    losses: int,
    ties: int = 0,
    owner: str | None = None,
    opponent_owner: str | None = None,
) -> dict:
    """Build one FFA-040-shaped head-to-head record row directly.

    Points columns are irrelevant to the matrix (which only reads
    meetings/wins/losses/ties plus the owner labels) but are filled in
    consistently so the row is a valid ``HEAD_TO_HEAD_COLUMNS`` row.
    """
    total_points = 100.0 * meetings
    total_opponent_points = 90.0 * meetings
    return {
        "roster_id": roster_id,
        "opponent_roster_id": opponent_roster_id,
        "owner": owner,
        "opponent_owner": opponent_owner,
        "meetings": meetings,
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "total_points": total_points,
        "total_opponent_points": total_opponent_points,
        "avg_points": total_points / meetings if meetings else 0.0,
        "avg_opponent_points": total_opponent_points / meetings if meetings else 0.0,
    }


def _h2h_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=HEAD_TO_HEAD_COLUMNS)
    return pd.DataFrame(rows, columns=HEAD_TO_HEAD_COLUMNS)


def _toy_rows() -> list[dict]:
    """Four rosters, five weeks; rosters 2 and 4 (and 3 and 4) never meet.

    Week 1: roster 1 (120.0) beats roster 2 (100.0).
    Week 2: roster 1 (90.0) ties roster 3 (90.0).
    Week 3: roster 2 (80.0) beats roster 1 (70.0) -- a rematch, with roster 1
        now on the ``roster_2_id`` side.
    Week 4: roster 2 (110.0) beats roster 3 (95.0).
    Week 5: roster 1 (100.0) beats roster 4 (50.0).

    Hand-computed raw matrix (rows = own roster, columns = opponent;
    ``W-L-T`` counts, ``.`` = never met, ``None`` on the diagonal):

              1        2        3        4
        1   None    1-1-0    0-0-1    1-0-0
        2  1-1-0     None    1-0-0      .
        3  0-0-1    0-1-0     None      .
        4  0-1-0      .        .       None

    Hand-computed display matrix (owners Alec/Mike/Joe/Sam; ``W-L`` unless
    the pair has ties, ``""`` for never met, ``"—"`` on the diagonal):

               Alec    Mike     Joe     Sam
        Alec     —      1-1    0-0-1    1-0
        Mike    1-1      —      1-0
        Joe    0-0-1    0-1      —
        Sam     0-1                      —
    """
    return [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=3,
            points_1=90.0,
            points_2=90.0,
            winner=None,
            loser=None,
            is_tie=True,
            week=2,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=1,
            points_1=80.0,
            points_2=70.0,
            winner=2,
            loser=1,
            week=3,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=2,
            roster_2_id=3,
            points_1=110.0,
            points_2=95.0,
            winner=2,
            loser=3,
            week=4,
            matchup_id=1,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=4,
            points_1=100.0,
            points_2=50.0,
            winner=1,
            loser=4,
            week=5,
            matchup_id=2,
        ),
    ]


def _toy_teams_df() -> pd.DataFrame:
    return _teams_df(
        [
            _team_row(1, "Alec"),
            _team_row(2, "Mike"),
            _team_row(3, "Joe"),
            _team_row(4, "Sam"),
        ]
    )


def _toy_head_to_head_df() -> pd.DataFrame:
    return build_head_to_head_records(_season_matchup_df(_toy_rows()), _toy_teams_df())


def test_toy_example_raw_matrix_hand_computed() -> None:
    """Every cell of the toy season's raw matrix matches ``_toy_rows``' table."""
    matrix = build_head_to_head_matrix(_toy_head_to_head_df())

    assert list(matrix.index) == [1, 2, 3, 4]
    assert list(matrix.columns) == [1, 2, 3, 4]
    assert matrix.index.name == "roster_id"
    assert matrix.columns.name == "opponent_roster_id"

    expected = {
        # (roster, opponent): (meetings, wins, losses, ties)
        (1, 2): (2, 1, 1, 0),
        (1, 3): (1, 0, 0, 1),
        (1, 4): (1, 1, 0, 0),
        (2, 1): (2, 1, 1, 0),
        (2, 3): (1, 1, 0, 0),
        (2, 4): (0, 0, 0, 0),
        (3, 1): (1, 0, 0, 1),
        (3, 2): (1, 0, 1, 0),
        (3, 4): (0, 0, 0, 0),
        (4, 1): (1, 0, 1, 0),
        (4, 2): (0, 0, 0, 0),
        (4, 3): (0, 0, 0, 0),
    }
    for (roster_id, opponent_roster_id), counts in expected.items():
        cell = matrix.loc[roster_id, opponent_roster_id]
        assert cell == HeadToHeadCell(
            roster_id=roster_id,
            opponent_roster_id=opponent_roster_id,
            meetings=counts[0],
            wins=counts[1],
            losses=counts[2],
            ties=counts[3],
        )


def test_toy_example_display_matrix_hand_computed() -> None:
    """The formatted toy matrix matches the display table in ``_toy_rows``."""
    display = format_head_to_head_matrix(_toy_head_to_head_df())

    assert list(display.index) == ["Alec", "Mike", "Joe", "Sam"]
    assert list(display.columns) == ["Alec", "Mike", "Joe", "Sam"]
    assert display.index.name == "owner"
    assert display.columns.name == "opponent_owner"

    assert list(display.loc["Alec"]) == ["—", "1-1", "0-0-1", "1-0"]
    assert list(display.loc["Mike"]) == ["1-1", "—", "1-0", ""]
    assert list(display.loc["Joe"]) == ["0-0-1", "0-1", "—", ""]
    assert list(display.loc["Sam"]) == ["0-1", "", "", "—"]


def test_diagonal_is_none_raw_and_sentinel_in_display() -> None:
    """A manager vs. themselves is ``None`` raw and the em-dash sentinel in
    the display matrix -- distinguishable from a genuine never-met pair.
    """
    head_to_head_df = _toy_head_to_head_df()
    matrix = build_head_to_head_matrix(head_to_head_df)
    display = format_head_to_head_matrix(head_to_head_df)

    for roster_id in matrix.index:
        assert matrix.loc[roster_id, roster_id] is None
    for owner in display.index:
        assert display.loc[owner, owner] == HEAD_TO_HEAD_MATRIX_DIAGONAL


def test_pair_that_never_met_is_zero_cell_not_none() -> None:
    """Rosters 2 and 4 never played: an explicit zeroed cell (so
    ``cell.meetings == 0`` is safe) rendering as the blank display sentinel.
    """
    head_to_head_df = _toy_head_to_head_df()
    matrix = build_head_to_head_matrix(head_to_head_df)
    display = format_head_to_head_matrix(head_to_head_df)

    cell = matrix.loc[2, 4]
    assert cell is not None
    assert cell.meetings == 0
    assert (cell.wins, cell.losses, cell.ties) == (0, 0, 0)
    assert cell.format_record() == HEAD_TO_HEAD_MATRIX_NO_MEETING
    assert display.loc["Mike", "Sam"] == HEAD_TO_HEAD_MATRIX_NO_MEETING


def test_ties_rendered_only_when_the_pair_has_them() -> None:
    """``W-L`` when a pair has no ties, ``W-L-T`` when it does -- per cell."""
    display = format_head_to_head_matrix(_toy_head_to_head_df())

    assert display.loc["Alec", "Mike"] == "1-1"  # 1-1-0, tie component hidden
    assert display.loc["Alec", "Joe"] == "0-0-1"  # one tie, shown


def test_tie_counts_survive_in_the_raw_matrix_even_when_hidden() -> None:
    """A tieless pair hides ``-0`` in display but still carries ``ties`` raw."""
    matrix = build_head_to_head_matrix(_toy_head_to_head_df())

    assert matrix.loc[1, 2].ties == 0
    assert matrix.loc[1, 3].ties == 1


def test_matrix_is_mirror_consistent_for_unfiltered_ffa040_output() -> None:
    """Cell [a][b] and cell [b][a] have swapped wins/losses and equal ties --
    a property of FFA-040's mirrored rows, verified here across all pairs.
    """
    matrix = build_head_to_head_matrix(_toy_head_to_head_df())

    for roster_id in matrix.index:
        for opponent_roster_id in matrix.columns:
            if roster_id == opponent_roster_id:
                continue
            cell = matrix.loc[roster_id, opponent_roster_id]
            mirror = matrix.loc[opponent_roster_id, roster_id]
            assert cell.wins == mirror.losses
            assert cell.losses == mirror.wins
            assert cell.ties == mirror.ties
            assert cell.meetings == mirror.meetings


def test_unresolved_owner_falls_back_to_roster_label() -> None:
    """Roster 2 has no ``teams_df`` row, so FFA-040 gives it ``owner=None``;
    the display axis labels it ``"Roster 2"`` rather than ``"None"``.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
        )
    ]
    head_to_head_df = build_head_to_head_records(
        _season_matchup_df(rows), _teams_df([_team_row(1, "Alec")])
    )

    display = format_head_to_head_matrix(head_to_head_df)

    assert list(display.index) == ["Alec", "Roster 2"]
    assert list(display.columns) == ["Alec", "Roster 2"]
    assert display.loc["Alec", "Roster 2"] == "1-0"
    assert display.loc["Roster 2", "Alec"] == "0-1"


def test_all_owners_unresolved_uses_roster_labels_throughout() -> None:
    """An empty ``teams_df`` upstream leaves every owner ``None``; the
    display matrix stays readable and roster-traceable.
    """
    head_to_head_df = build_head_to_head_records(
        _season_matchup_df(_toy_rows()), _teams_df([])
    )

    display = format_head_to_head_matrix(head_to_head_df)

    assert list(display.index) == ["Roster 1", "Roster 2", "Roster 3", "Roster 4"]


def test_duplicate_display_names_produce_duplicate_axis_labels() -> None:
    """Two managers sharing a display name are not disambiguated -- the
    documented collision caveat. The raw matrix stays unambiguous.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
        )
    ]
    teams_df = _teams_df([_team_row(1, "Alec"), _team_row(2, "Alec")])
    head_to_head_df = build_head_to_head_records(_season_matchup_df(rows), teams_df)

    display = format_head_to_head_matrix(head_to_head_df)
    matrix = build_head_to_head_matrix(head_to_head_df)

    assert list(display.index) == ["Alec", "Alec"]
    # The raw matrix is still keyed by roster_id and free of collisions.
    assert list(matrix.index) == [1, 2]
    assert matrix.loc[1, 2].wins == 1
    assert matrix.loc[2, 1].wins == 0


def test_empty_input_returns_empty_frames() -> None:
    """No records means no roster universe: an empty frame, not an error."""
    empty = _h2h_df([])

    matrix = build_head_to_head_matrix(empty)
    display = format_head_to_head_matrix(empty)

    assert matrix.empty
    assert list(matrix.columns) == []
    assert display.empty
    assert list(display.columns) == []


def test_regular_season_and_playoff_meetings_are_combined() -> None:
    """The matrix inherits FFA-040's combined scope: a regular-season win and
    a playoff loss between the same pair make one ``1-1`` cell, not two
    matrices. Phase splitting is FFA-044's job.
    """
    rows = [
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=120.0,
            points_2=100.0,
            winner=1,
            loser=2,
            week=1,
            is_playoff=False,
        ),
        _matchup_row(
            roster_1_id=1,
            roster_2_id=2,
            points_1=90.0,
            points_2=110.0,
            winner=2,
            loser=1,
            week=16,
            is_playoff=True,
        ),
    ]
    head_to_head_df = build_head_to_head_records(
        _season_matchup_df(rows),
        _teams_df([_team_row(1, "Alec"), _team_row(2, "Mike")]),
    )

    display = format_head_to_head_matrix(head_to_head_df)

    assert display.loc["Alec", "Mike"] == "1-1"
    assert build_head_to_head_matrix(head_to_head_df).loc[1, 2].meetings == 2


def test_unresolved_outcome_leaves_record_short_of_meetings() -> None:
    """FFA-040 counts a missing-points meeting in ``meetings`` but in none of
    wins/losses/ties, so the rendered record can total fewer games than
    ``meetings``. The raw cell keeps ``meetings`` for callers who need it.
    """
    head_to_head_df = _h2h_df(
        [
            _h2h_row(
                1, 2, meetings=2, wins=1, losses=0, owner="Alec", opponent_owner="Mike"
            ),
            _h2h_row(
                2, 1, meetings=2, wins=0, losses=1, owner="Mike", opponent_owner="Alec"
            ),
        ]
    )

    matrix = build_head_to_head_matrix(head_to_head_df)
    display = format_head_to_head_matrix(head_to_head_df)

    cell = matrix.loc[1, 2]
    assert cell.meetings == 2
    assert cell.wins + cell.losses + cell.ties == 1
    assert display.loc["Alec", "Mike"] == "1-0"


def test_asymmetric_hand_filtered_input_is_not_mirrored() -> None:
    """A caller who filters the records to one direction gets a matrix whose
    mirror cell reads as "never met" -- mirror consistency is a property of
    FFA-040's unfiltered output, not something this module invents.
    """
    head_to_head_df = _h2h_df(
        [
            _h2h_row(
                1, 2, meetings=1, wins=1, losses=0, owner="Alec", opponent_owner="Mike"
            )
        ]
    )

    matrix = build_head_to_head_matrix(head_to_head_df)

    assert list(matrix.index) == [1, 2]
    assert matrix.loc[1, 2].wins == 1
    assert matrix.loc[2, 1].meetings == 0


def test_roster_appearing_only_as_opponent_is_still_on_both_axes() -> None:
    """The roster universe is the union of both id columns, so a roster that
    a filtered input only ever lists as an opponent still gets its own row.
    """
    head_to_head_df = _h2h_df(
        [
            _h2h_row(
                1, 2, meetings=1, wins=1, losses=0, owner="Alec", opponent_owner="Mike"
            ),
            _h2h_row(
                1, 3, meetings=1, wins=0, losses=1, owner="Alec", opponent_owner="Joe"
            ),
        ]
    )

    matrix = build_head_to_head_matrix(head_to_head_df)
    display = format_head_to_head_matrix(head_to_head_df)

    assert list(matrix.index) == [1, 2, 3]
    assert list(display.index) == ["Alec", "Mike", "Joe"]
    assert matrix.loc[3, 2].meetings == 0


def test_axes_are_sorted_ascending_by_roster_id() -> None:
    """Row/column order is ascending ``roster_id`` regardless of input order."""
    head_to_head_df = _h2h_df(
        [
            _h2h_row(7, 3, meetings=1, wins=1, losses=0),
            _h2h_row(3, 7, meetings=1, wins=0, losses=1),
            _h2h_row(5, 3, meetings=1, wins=1, losses=0),
            _h2h_row(3, 5, meetings=1, wins=0, losses=1),
        ]
    )

    matrix = build_head_to_head_matrix(head_to_head_df)

    assert list(matrix.index) == [3, 5, 7]
    assert list(matrix.columns) == [3, 5, 7]


def test_format_record_is_independent_of_other_cells() -> None:
    """The tie rule is per-cell, so a cell's rendering never depends on
    whether some other pair in the league tied.
    """
    tieless = HeadToHeadCell(
        roster_id=1, opponent_roster_id=2, meetings=5, wins=3, losses=2, ties=0
    )
    tied = HeadToHeadCell(
        roster_id=1, opponent_roster_id=3, meetings=3, wins=1, losses=1, ties=1
    )
    never_met = HeadToHeadCell(
        roster_id=1, opponent_roster_id=4, meetings=0, wins=0, losses=0, ties=0
    )

    assert tieless.format_record() == "3-2"
    assert tied.format_record() == "1-1-1"
    assert never_met.format_record() == HEAD_TO_HEAD_MATRIX_NO_MEETING
