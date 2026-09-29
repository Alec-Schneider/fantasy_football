"""Tests for as-of-week standings derived from matchups (FFA-102).

Every input here is a hand-built
:data:`~fantasy_analyzer.matchups.season_matchups.SEASON_MATCHUP_COLUMNS`
frame with small, round point totals, so each expected ``win_pct``/
``points_for``/``rank`` can be checked by hand arithmetic in the test's own
docstring -- per AGENTS.md's analytics-ticket requirement for a
hand-checkable toy example. No HTTP, no fixtures.
"""

import pandas as pd

from fantasy_analyzer.analytics import build_standings_through_week
from fantasy_analyzer.analytics.standings import STANDINGS_COLUMNS

_MATCHUP_COLUMNS = [
    "season",
    "week",
    "is_playoff",
    "matchup_id",
    "roster_1_id",
    "roster_2_id",
    "owner_1",
    "owner_2",
    "points_1",
    "points_2",
    "winner",
    "loser",
    "is_tie",
    "margin",
    "point_differential",
]


def _matchup(
    week: int,
    roster_1_id: int,
    roster_2_id,
    points_1,
    points_2,
    *,
    is_playoff: bool = False,
    matchup_id: int = 1,
) -> dict:
    """Build one matchup row, deriving winner/loser/tie the way the pipeline does."""
    if roster_2_id is None or points_1 is None or points_2 is None:
        winner = loser = None
        is_tie = False
        margin = None
    elif points_1 == points_2:
        winner = loser = None
        is_tie = True
        margin = 0.0
    elif points_1 > points_2:
        winner, loser, is_tie = roster_1_id, roster_2_id, False
        margin = points_1 - points_2
    else:
        winner, loser, is_tie = roster_2_id, roster_1_id, False
        margin = points_2 - points_1

    return {
        "season": 2026,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": f"owner{roster_1_id}",
        "owner_2": None if roster_2_id is None else f"owner{roster_2_id}",
        "points_1": points_1,
        "points_2": points_2,
        "winner": winner,
        "loser": loser,
        "is_tie": is_tie,
        "margin": margin,
        "point_differential": (
            None if points_1 is None or points_2 is None else points_1 - points_2
        ),
    }


def _matchups(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=_MATCHUP_COLUMNS)


def _teams_df(roster_ids: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "roster_id": roster_id,
                "owner_id": f"u{roster_id}",
                "display_name": f"owner{roster_id}",
                "team_name": f"Team {roster_id}",
            }
            for roster_id in roster_ids
        ],
        columns=["roster_id", "owner_id", "display_name", "team_name"],
    )


def test_toy_example_hand_computed() -> None:
    """Four teams, two weeks, computed by hand.

    Week 1: roster 1 beats 2, 100-90.  roster 3 beats 4, 120-80.
    Week 2: roster 1 beats 3, 110-100. roster 4 beats 2, 95-85.

    Roster 1: 2-0-0, PF 100+110=210, PA 90+100=190,  diff +20, win_pct 1.0
    Roster 3: 1-1-0, PF 120+100=220, PA 80+110=190,  diff +30, win_pct 0.5
    Roster 4: 1-1-0, PF  80+ 95=175, PA 120+85=205,  diff -30, win_pct 0.5
    Roster 2: 0-2-0, PF  90+ 85=175, PA 100+95=195,  diff -20, win_pct 0.0

    Ranking is win_pct desc, then points_for desc: roster 1 (1.0) is 1st.
    Rosters 3 and 4 both sit at 0.5, so points_for breaks the tie -- 220 >
    175, so roster 3 is 2nd and roster 4 is 3rd. Roster 2 is 4th.
    """
    matchups = _matchups(
        [
            _matchup(1, 1, 2, 100.0, 90.0),
            _matchup(1, 3, 4, 120.0, 80.0, matchup_id=2),
            _matchup(2, 1, 3, 110.0, 100.0),
            _matchup(2, 4, 2, 95.0, 85.0, matchup_id=2),
        ]
    )

    standings = build_standings_through_week(matchups, _teams_df([1, 2, 3, 4]), 2)

    assert list(standings.columns) == STANDINGS_COLUMNS
    assert standings["roster_id"].tolist() == [1, 3, 4, 2]
    assert standings["rank"].tolist() == [1, 2, 3, 4]
    assert standings["wins"].tolist() == [2, 1, 1, 0]
    assert standings["losses"].tolist() == [0, 1, 1, 2]
    assert standings["win_pct"].tolist() == [1.0, 0.5, 0.5, 0.0]
    assert standings["points_for"].tolist() == [210.0, 220.0, 175.0, 175.0]
    assert standings["points_against"].tolist() == [190.0, 190.0, 205.0, 195.0]
    assert standings["point_diff"].tolist() == [20.0, 30.0, -30.0, -20.0]
    assert standings["team_name"].tolist() == ["Team 1", "Team 3", "Team 4", "Team 2"]


def test_week_argument_truncates_history() -> None:
    """Asking for week 1 must ignore week 2 entirely.

    After week 1 only, roster 1 is 1-0 with 100 PF and roster 2 is 0-1 with
    90 PF -- the week-2 result that levels them is not yet counted.
    """
    matchups = _matchups(
        [
            _matchup(1, 1, 2, 100.0, 90.0),
            _matchup(2, 1, 2, 50.0, 200.0),
        ]
    )

    standings = build_standings_through_week(matchups, _teams_df([1, 2]), 1)

    assert standings["roster_id"].tolist() == [1, 2]
    assert standings["wins"].tolist() == [1, 0]
    assert standings["points_for"].tolist() == [100.0, 90.0]

    # And week 2 flips it: roster 2 is 1-1 with 290 PF, roster 1 is 1-1 with
    # 150 PF, so points_for breaks the tie in roster 2's favour.
    later = build_standings_through_week(matchups, _teams_df([1, 2]), 2)
    assert later["roster_id"].tolist() == [2, 1]
    assert later["win_pct"].tolist() == [0.5, 0.5]
    assert later["points_for"].tolist() == [290.0, 150.0]


def test_ties_are_counted_and_scored_as_half_a_win() -> None:
    """A tie gives each side 0.5 of a win.

    Roster 1: 1 win (week 1) + 1 tie (week 2) over 2 games ->
    (1 + 0.5 * 1) / 2 = 0.75.  Roster 2: 1 loss + 1 tie -> (0 + 0.5) / 2 = 0.25.
    """
    matchups = _matchups(
        [
            _matchup(1, 1, 2, 100.0, 90.0),
            _matchup(2, 1, 2, 95.0, 95.0),
        ]
    )

    standings = build_standings_through_week(matchups, _teams_df([1, 2]), 2)

    assert standings["ties"].tolist() == [1, 1]
    assert standings["wins"].tolist() == [1, 0]
    assert standings["losses"].tolist() == [0, 1]
    assert standings["win_pct"].tolist() == [0.75, 0.25]


def test_identical_records_and_points_share_a_rank() -> None:
    """Two teams tied on both keys share rank 1, and the next rank skips to 3.

    Rosters 1 and 3 each go 1-0 with exactly 100.0 points for and 90.0
    against, so neither the win_pct nor the points_for tiebreak separates
    them -- standard competition ("1224") ranking applies.
    """
    matchups = _matchups(
        [
            _matchup(1, 1, 2, 100.0, 90.0),
            _matchup(1, 3, 4, 100.0, 90.0, matchup_id=2),
        ]
    )

    standings = build_standings_through_week(matchups, _teams_df([1, 2, 3, 4]), 1)

    assert standings["rank"].tolist() == [1, 1, 3, 3]


def test_playoff_matchups_excluded_by_default_and_included_on_request() -> None:
    """``include_playoffs`` is the explicit regular-season/playoff switch.

    Roster 1 wins a regular-season game and loses a playoff game. By
    default it reads 1-0 (100 PF); with ``include_playoffs=True`` it reads
    1-1 (100 + 60 = 160 PF).
    """
    matchups = _matchups(
        [
            _matchup(1, 1, 2, 100.0, 90.0),
            _matchup(2, 1, 2, 60.0, 130.0, is_playoff=True),
        ]
    )
    teams_df = _teams_df([1, 2])

    regular = build_standings_through_week(matchups, teams_df, 2)
    assert regular.set_index("roster_id").loc[1, "wins"] == 1
    assert regular.set_index("roster_id").loc[1, "losses"] == 0
    assert regular.set_index("roster_id").loc[1, "points_for"] == 100.0

    with_playoffs = build_standings_through_week(
        matchups, teams_df, 2, include_playoffs=True
    )
    assert with_playoffs.set_index("roster_id").loc[1, "wins"] == 1
    assert with_playoffs.set_index("roster_id").loc[1, "losses"] == 1
    assert with_playoffs.set_index("roster_id").loc[1, "points_for"] == 160.0


def test_bye_and_unscored_rows_contribute_nothing() -> None:
    """A bye (no opponent) and an unscored week add neither record nor points.

    Roster 1 plays a real game in week 1 (wins 100-90), takes a bye in week
    2, and has an unscored week 3. Only week 1 counts: 1-0, 100 PF, 90 PA.
    Crediting the bye's 105 points would push PF to 205 against an
    unchanged PA -- the inflation the module docstring rules out.
    """
    matchups = _matchups(
        [
            _matchup(1, 1, 2, 100.0, 90.0),
            _matchup(2, 1, None, 105.0, None),
            _matchup(3, 1, 2, None, None, matchup_id=3),
        ]
    )

    standings = build_standings_through_week(matchups, _teams_df([1, 2]), 3)
    roster_1 = standings.set_index("roster_id").loc[1]

    assert roster_1["wins"] == 1
    assert roster_1["losses"] == 0
    assert roster_1["points_for"] == 100.0
    assert roster_1["points_against"] == 90.0


def test_team_with_no_completed_games_still_appears_at_zero() -> None:
    """A roster absent from the matchup frame is reported 0-0-0, not dropped.

    Roster 3 is in ``teams_df`` but has no matchup rows -- the league's
    third team before its first game. It must still occupy a row, at the
    bottom (win_pct 0.0, points_for 0.0).
    """
    matchups = _matchups([_matchup(1, 1, 2, 100.0, 90.0)])

    standings = build_standings_through_week(matchups, _teams_df([1, 2, 3]), 1)

    assert len(standings) == 3
    assert set(standings["roster_id"]) == {1, 2, 3}
    roster_3 = standings.set_index("roster_id").loc[3]
    assert roster_3["wins"] == 0
    assert roster_3["losses"] == 0
    assert roster_3["win_pct"] == 0.0
    assert roster_3["points_for"] == 0.0
    assert roster_3["display_name"] == "owner3"


def test_week_zero_returns_an_all_zero_league() -> None:
    """Week 0 precedes every matchup: everyone 0-0-0, nobody dropped."""
    matchups = _matchups([_matchup(1, 1, 2, 100.0, 90.0)])

    standings = build_standings_through_week(matchups, _teams_df([1, 2]), 0)

    assert len(standings) == 2
    assert standings["wins"].tolist() == [0, 0]
    assert standings["points_for"].tolist() == [0.0, 0.0]
    assert standings["rank"].tolist() == [1, 1]


def test_empty_teams_df_returns_empty_shaped_frame() -> None:
    """No teams means an empty frame that still carries the expected columns."""
    empty_teams = pd.DataFrame(
        columns=["roster_id", "owner_id", "display_name", "team_name"]
    )

    standings = build_standings_through_week(
        _matchups([_matchup(1, 1, 2, 100.0, 90.0)]), empty_teams, 1
    )

    assert standings.empty
    assert list(standings.columns) == STANDINGS_COLUMNS


def test_empty_matchup_frame_returns_all_zero_league() -> None:
    """An empty season frame is the pre-season case, not an error."""
    standings = build_standings_through_week(
        pd.DataFrame(columns=_MATCHUP_COLUMNS), _teams_df([1, 2]), 5
    )

    assert len(standings) == 2
    assert standings["wins"].tolist() == [0, 0]
    assert list(standings.columns) == STANDINGS_COLUMNS


def test_matches_build_standings_shape_for_the_same_league() -> None:
    """The as-of-week frame is a drop-in for ``build_standings`` consumers.

    Same columns, same dtypes-of-interest, same ordering rule -- so the
    commentary/context builders that take a ``standings_df`` accept either.
    """
    matchups = _matchups(
        [
            _matchup(1, 1, 2, 100.0, 90.0),
            _matchup(2, 1, 2, 110.0, 105.0),
        ]
    )

    standings = build_standings_through_week(matchups, _teams_df([1, 2]), 2)

    assert list(standings.columns) == STANDINGS_COLUMNS
    assert standings["rank"].is_monotonic_increasing
    assert standings["win_pct"].is_monotonic_decreasing
