"""Tests for expected wins and schedule luck (FFA-052).

All tests operate on hand-built ``season_matchup_df``/``teams_df`` inputs --
no HTTP calls, no fixtures with opaque values -- so every expected-wins and
schedule-luck number can be verified by hand arithmetic from the scores
written in the test, per AGENTS.md's analytics-ticket requirement for a
hand-checkable toy example.

Unlike FFA-051's tests, these cannot shortcut the upstream frame: the whole
point of :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
is that it derives both the actual record and the all-play record from one
shared ``season_matchup_df``, so every test here builds real matchup rows and
exercises the full ``derive_roster_totals`` + ``build_weekly_scoring_ranks``
+ ``build_all_play_standings`` composition.
"""

import inspect

import pandas as pd
import pytest

from fantasy_analyzer.analytics import (
    SCHEDULE_LUCK_COLUMNS,
    build_schedule_luck,
)
from fantasy_analyzer.matchups.season_matchups import SEASON_MATCHUP_COLUMNS


def _game(
    roster_1_id: int,
    roster_2_id: int | None,
    points_1: float | None,
    points_2: float | None,
    week: int = 1,
    matchup_id: int | None = 1,
    is_playoff: bool = False,
    season: str = "2025",
) -> dict:
    """One ``SEASON_MATCHUP_COLUMNS`` row with outcome fields derived by hand.

    Mirrors :mod:`fantasy_analyzer.matchups.outcomes`' rules exactly: a
    matchup with a missing opponent or a missing score has no winner, no
    loser, no tie, and no margin. Pass ``roster_2_id=None`` for a bye.
    """
    winner: int | None = None
    loser: int | None = None
    is_tie = False
    margin: float | None = None
    point_differential: float | None = None

    if roster_2_id is not None and points_1 is not None and points_2 is not None:
        point_differential = points_1 - points_2
        margin = abs(point_differential)
        if points_1 > points_2:
            winner, loser = roster_1_id, roster_2_id
        elif points_1 < points_2:
            winner, loser = roster_2_id, roster_1_id
        else:
            is_tie = True

    return {
        "season": season,
        "week": week,
        "is_playoff": is_playoff,
        "matchup_id": matchup_id,
        "roster_1_id": roster_1_id,
        "roster_2_id": roster_2_id,
        "owner_1": None,
        "owner_2": None,
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


def _teams_df(names: dict[int, str | None]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "roster_id": roster_id,
                "owner_id": f"u{roster_id}",
                "display_name": name,
                "team_name": name,
            }
            for roster_id, name in names.items()
        ],
        columns=["roster_id", "owner_id", "display_name", "team_name"],
    )


def _empty_teams_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["roster_id", "owner_id", "display_name", "team_name"])


def _row(df: pd.DataFrame, roster_id: int) -> pd.Series:
    match = df.loc[df["roster_id"] == roster_id]
    assert len(match) == 1
    return match.iloc[0]


# --------------------------------------------------------------------------
# AGENTS.md's worked example
# --------------------------------------------------------------------------

#: Fixed per-roster weekly score for the eight-roster worked example. Every
#: roster scores exactly this every week, so the all-play field is identical
#: in all 14 weeks and the arithmetic below is checkable by hand.
_WORKED_EXAMPLE_POINTS = {
    2: 130.0,
    3: 120.0,
    1: 110.0,  # the subject roster -- 3rd of 8 every single week
    4: 100.0,
    5: 90.0,
    6: 80.0,
    7: 70.0,
    8: 60.0,
}

#: Roster 1's opponent each week: rosters 2 and 3 (which outscore it) six
#: times, then five weaker rosters eight times -> an actual record of 8-6.
_WORKED_EXAMPLE_OPPONENTS = [2, 3, 2, 3, 2, 3, 4, 5, 6, 7, 8, 4, 5, 6]


def _worked_example_rows() -> list[dict]:
    """Build AGENTS.md's example: 8 rosters, 14 weeks, roster 1 goes 8-6.

    Every roster scores its fixed ``_WORKED_EXAMPLE_POINTS`` value every
    week, so roster 1 (110.0) is the 3rd-highest scorer in all 14 weeks:

        beats 100, 90, 80, 70, 60  -> 5 all-play wins per week
        loses to 130, 120          -> 2 all-play losses per week

    Over 14 weeks that is 70-28-0 in 98 all-play games, so

        all_play_win_pct = 70 / 98 = 5 / 7 = 0.714285...
        expected_wins    = 5 / 7 * 14 = 10.0
        expected_losses  = 14 - 10.0  =  4.0

    Its actual schedule (``_WORKED_EXAMPLE_OPPONENTS``) hands it the two
    rosters that outscore it six times and weaker rosters eight times, for
    an actual record of 8-6, so

        schedule_luck = 8 - 10.0 = -2.0

    which is exactly AGENTS.md's worked example:

        Actual Record:     8-6
        Expected Record:  10.0-4.0
        Schedule Luck:    -2.0 wins

    The other seven rosters are paired off arbitrarily (in ascending
    ``roster_id`` order) each week so that all eight have a score in every
    week. Only the resulting field of scores affects roster 1's all-play
    rate; who the others played affects only their own records, which this
    arbitrary pairing leaves wildly lucky and unlucky (roster 7 is the 7th
    strongest scorer yet goes 12-2, for +10.0 luck). That is a feature for
    testing purposes -- it exercises the full range of the metric -- but the
    only hand-verified claim is roster 1's.
    """
    rows: list[dict] = []
    for week, opponent in enumerate(_WORKED_EXAMPLE_OPPONENTS, start=1):
        rows.append(
            _game(
                1,
                opponent,
                _WORKED_EXAMPLE_POINTS[1],
                _WORKED_EXAMPLE_POINTS[opponent],
                week=week,
                matchup_id=1,
            )
        )
        rest = [r for r in range(2, 9) if r != opponent]
        for index in range(0, len(rest), 2):
            left, right = rest[index], rest[index + 1]
            rows.append(
                _game(
                    left,
                    right,
                    _WORKED_EXAMPLE_POINTS[left],
                    _WORKED_EXAMPLE_POINTS[right],
                    week=week,
                    matchup_id=2 + index // 2,
                )
            )
    return rows


def test_agents_md_worked_example() -> None:
    """Reproduces AGENTS.md's example exactly: 8-6 actual, 10.0-4.0 expected,
    -2.0 schedule luck. See ``_worked_example_rows``' docstring for the full
    hand computation.
    """
    df = build_schedule_luck(
        _season_matchup_df(_worked_example_rows()),
        _teams_df({r: f"owner{r}" for r in range(1, 9)}),
    )

    row = _row(df, 1)
    assert row["games_played"] == 14
    assert (row["wins"], row["losses"], row["ties"]) == (8, 6, 0)
    assert row["win_pct"] == pytest.approx(8 / 14)
    assert row["all_play_games"] == 98  # 7 comparisons * 14 weeks
    assert row["all_play_win_pct"] == pytest.approx(5 / 7)
    assert row["expected_wins"] == pytest.approx(10.0)
    assert row["expected_losses"] == pytest.approx(4.0)
    assert row["schedule_luck"] == pytest.approx(-2.0)


def test_worked_example_sign_convention_and_extremes() -> None:
    """Negative luck = under-performed its scoring (AGENTS.md's roster 1).

    Roster 2 outscores everyone every week, so it goes 14-0 with an
    ``all_play_win_pct`` of 1.0 -- exactly the record it deserved, luck 0.0.
    Roster 8 is outscored by everyone every week: 0-14, ``all_play_win_pct``
    0.0, luck 0.0. Neither extreme can be lucky or unlucky, which is a
    property of the metric worth pinning down.

    On the positive side, the arbitrary pairing of the other rosters left
    roster 7 (7th of 8 in scoring every week, ``all_play_win_pct`` 1/7) with
    a 12-2 record against an expected 2.0-12.0: ``+10.0`` wins of luck, the
    luckiest roster in the frame and the opposite sign to roster 1's.
    """
    df = build_schedule_luck(
        _season_matchup_df(_worked_example_rows()),
        _teams_df({r: f"owner{r}" for r in range(1, 9)}),
    )

    best = _row(df, 2)
    assert (best["wins"], best["losses"]) == (14, 0)
    assert best["all_play_win_pct"] == pytest.approx(1.0)
    assert best["expected_wins"] == pytest.approx(14.0)
    assert best["schedule_luck"] == pytest.approx(0.0)

    worst = _row(df, 8)
    assert (worst["wins"], worst["losses"]) == (0, 14)
    assert worst["all_play_win_pct"] == pytest.approx(0.0)
    assert worst["expected_wins"] == pytest.approx(0.0)
    assert worst["schedule_luck"] == pytest.approx(0.0)

    luckiest = _row(df, 7)
    assert (luckiest["wins"], luckiest["losses"]) == (12, 2)
    assert luckiest["all_play_win_pct"] == pytest.approx(1 / 7)
    assert luckiest["expected_wins"] == pytest.approx(2.0)
    assert luckiest["schedule_luck"] == pytest.approx(10.0)
    assert luckiest["schedule_luck_rank"] == 1
    assert df["roster_id"].iloc[0] == 7

    # Rosters 1, 4 and 6 all landed on -2.0 and share rank 5 ("1224"); the
    # unluckiest roster (3, at -6.0) sorts last.
    assert list(df["roster_id"])[-1] == 3
    assert _row(df, 3)["schedule_luck"] == pytest.approx(-6.0)
    assert [_row(df, r)["schedule_luck_rank"] for r in (1, 4, 6)] == [5, 5, 5]
    assert _row(df, 3)["schedule_luck_rank"] == 8


def test_league_wide_schedule_luck_sums_to_zero_when_everyone_plays() -> None:
    """Every win one roster's schedule gives it is a win another's takes away.

    With all eight rosters playing all 14 weeks, total actual wins (56) and
    total expected wins (14 weeks * sum of the eight all-play rates, which is
    (7+6+5+4+3+2+1+0)/7 = 4 per week) are both 56, so the luck column sums to
    zero. This is only guaranteed when no roster misses a week -- see the
    module docstring.
    """
    df = build_schedule_luck(
        _season_matchup_df(_worked_example_rows()),
        _teams_df({r: f"owner{r}" for r in range(1, 9)}),
    )

    assert df["wins"].sum() == 56
    assert df["expected_wins"].sum() == pytest.approx(56.0)
    assert df["schedule_luck"].sum() == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Independent hand-built scenario, including a tie
# --------------------------------------------------------------------------


def _tie_scenario_rows() -> list[dict]:
    """Four rosters, two weeks, with a real tie in week 1.

    Week 1: roster 1 100.0 tie roster 2 100.0; roster 3 90.0 beat roster 4
    80.0. Week 1 field = 100, 100, 90, 80.
        roster 1: ties 100, beats 90 and 80  -> 2-0-1
        roster 2: ties 100, beats 90 and 80  -> 2-0-1
        roster 3: loses to both 100s, beats 80 -> 1-2-0
        roster 4: loses to all three          -> 0-3-0

    Week 2: roster 1 120.0 beat roster 3 110.0; roster 2 70.0 beat roster 4
    60.0. Week 2 field = 120, 110, 70, 60.
        roster 1: 3-0-0
        roster 3: 2-1-0
        roster 2: 1-2-0
        roster 4: 0-3-0

    Season all-play, actual record, and luck (games_played = 2 for all four):
        roster 1: all-play 5-0-1 of 6 -> 5.5/6 = 0.91666...
                  actual 1-0-1 -> wins+0.5*ties = 1.5, win_pct 0.75
                  expected 1.83333, luck 1.5 - 1.83333 = -0.33333
        roster 2: all-play 3-2-1 of 6 -> 3.5/6 = 0.58333...
                  actual 1-0-1 -> 1.5, win_pct 0.75
                  expected 1.16666, luck 1.5 - 1.16666 = +0.33333
        roster 3: all-play 3-3-0 of 6 -> 0.5
                  actual 1-1-0 -> 1.0, win_pct 0.5
                  expected 1.0, luck 0.0
        roster 4: all-play 0-6-0 of 6 -> 0.0
                  actual 0-2-0 -> 0.0, win_pct 0.0
                  expected 0.0, luck 0.0

    Rosters 1 and 2 have identical actual records but very different scoring
    strength, which is the entire point of the metric: roster 2's tie and win
    came against a weak field, roster 1's against a strong one.
    """
    return [
        _game(1, 2, 100.0, 100.0, week=1, matchup_id=1),
        _game(3, 4, 90.0, 80.0, week=1, matchup_id=2),
        _game(1, 3, 120.0, 110.0, week=2, matchup_id=1),
        _game(2, 4, 70.0, 60.0, week=2, matchup_id=2),
    ]


def test_tie_scenario_hand_computed() -> None:
    """Verifies every number hand-computed in ``_tie_scenario_rows``' docstring."""
    df = build_schedule_luck(
        _season_matchup_df(_tie_scenario_rows()),
        _teams_df({1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"}),
    )

    assert list(df.columns) == SCHEDULE_LUCK_COLUMNS
    assert len(df) == 4

    expected = {
        # roster_id: (wins, losses, ties, win_pct, all_play_pct, exp_w, luck)
        1: (1, 0, 1, 0.75, 5.5 / 6, 2 * 5.5 / 6, 1.5 - 2 * 5.5 / 6),
        2: (1, 0, 1, 0.75, 3.5 / 6, 2 * 3.5 / 6, 1.5 - 2 * 3.5 / 6),
        3: (1, 1, 0, 0.5, 0.5, 1.0, 0.0),
        4: (0, 2, 0, 0.0, 0.0, 0.0, 0.0),
    }
    for roster_id, (w, x, t, pct, ap_pct, exp_w, luck) in expected.items():
        row = _row(df, roster_id)
        assert row["games_played"] == 2
        assert (row["wins"], row["losses"], row["ties"]) == (w, x, t)
        assert row["win_pct"] == pytest.approx(pct)
        assert row["all_play_games"] == 6
        assert row["all_play_win_pct"] == pytest.approx(ap_pct)
        assert row["expected_wins"] == pytest.approx(exp_w)
        assert row["expected_losses"] == pytest.approx(2 - exp_w)
        assert row["schedule_luck"] == pytest.approx(luck)

    assert _row(df, 2)["schedule_luck"] == pytest.approx(1 / 3)
    assert _row(df, 1)["schedule_luck"] == pytest.approx(-1 / 3)


def test_actual_side_gives_a_tie_half_credit() -> None:
    """The actual side of the subtraction is ``wins + 0.5 * ties``, matching
    the half-credit convention baked into ``all_play_win_pct``.

    Roster 1 in the tie scenario is 1-0-1 with ``expected_wins = 1.8333``. A
    raw-``wins`` convention would report ``1 - 1.8333 = -0.8333``; the
    half-credit convention reports ``1.5 - 1.8333 = -0.3333``. The identity
    ``schedule_luck == (win_pct - all_play_win_pct) * games_played`` holds
    only under half credit, and is asserted here for every roster.
    """
    df = build_schedule_luck(
        _season_matchup_df(_tie_scenario_rows()),
        _teams_df({1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"}),
    )

    row = _row(df, 1)
    assert row["schedule_luck"] == pytest.approx(-1 / 3)
    assert row["schedule_luck"] != pytest.approx(1 - row["expected_wins"])

    for _, r in df.iterrows():
        assert r["schedule_luck"] == pytest.approx(
            (r["win_pct"] - r["all_play_win_pct"]) * r["games_played"]
        )


def test_expected_wins_and_losses_sum_to_games_played() -> None:
    """``expected_losses = games_played - expected_wins``, so the expected
    record always adds up to the season length -- exactly, in floating point.
    """
    df = build_schedule_luck(
        _season_matchup_df(_worked_example_rows()),
        _teams_df({r: f"owner{r}" for r in range(1, 9)}),
    )

    for _, row in df.iterrows():
        assert row["expected_wins"] + row["expected_losses"] == row["games_played"]


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def test_rank_one_is_the_luckiest_and_ties_share_a_rank() -> None:
    """Standard competition ("1224") ranking on ``schedule_luck`` descending.

    In the tie scenario the luck values are roster 2 = +0.3333, roster 3 =
    0.0, roster 4 = 0.0, roster 1 = -0.3333, so rosters 3 and 4 share rank 2
    and the next rank skips to 4. Rows are ordered by descending luck then
    ascending ``roster_id``.
    """
    df = build_schedule_luck(
        _season_matchup_df(_tie_scenario_rows()),
        _teams_df({1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"}),
    )

    assert list(df["roster_id"]) == [2, 3, 4, 1]
    assert list(df["schedule_luck_rank"]) == [1, 2, 2, 4]
    assert _row(df, 2)["schedule_luck_rank"] == 1  # luckiest, not "best"


def test_all_play_rank_is_carried_through_unchanged() -> None:
    """``all_play_rank`` keeps ``build_all_play_standings``' numbering rather
    than being recomputed: in the tie scenario the all-play order is roster 1
    (0.9166), roster 2 (0.5833), roster 3 (0.5), roster 4 (0.0).
    """
    df = build_schedule_luck(
        _season_matchup_df(_tie_scenario_rows()),
        _teams_df({1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"}),
    )

    assert _row(df, 1)["all_play_rank"] == 1
    assert _row(df, 2)["all_play_rank"] == 2
    assert _row(df, 3)["all_play_rank"] == 3
    assert _row(df, 4)["all_play_rank"] == 4


# --------------------------------------------------------------------------
# Games played: decisions, not weeks
# --------------------------------------------------------------------------


def test_bye_week_does_not_count_toward_games_played() -> None:
    """A bye is a real score (so it feeds ``all_play_win_pct``) but not a
    decision (so it does not add an expected win).

    Week 1: roster 1 120.0 beat roster 2 100.0; roster 3 has a bye at 110.0.
        all-play week 1: roster 1 2-0, roster 3 1-1, roster 2 0-2.
    Week 2: roster 1 60.0 lost to roster 2 90.0; roster 3 has a bye at 80.0.
        all-play week 2: roster 2 2-0, roster 3 1-1, roster 1 0-2.

    Roster 3 has ``weeks_played = 2`` on the all-play side and an
    ``all_play_win_pct`` of 2/4 = 0.5, but zero decided games, so it is
    dropped entirely. Rosters 1 and 2 each played 2 decided games and their
    all-play rates include roster 3's bye scores: both are 2-2 of 4 = 0.5,
    expected 1.0 win each, actual 1-1 -> luck 0.0 each.
    """
    rows = [
        _game(1, 2, 120.0, 100.0, week=1, matchup_id=1),
        _game(3, None, 110.0, None, week=1, matchup_id=None),
        _game(1, 2, 60.0, 90.0, week=2, matchup_id=1),
        _game(3, None, 80.0, None, week=2, matchup_id=None),
    ]
    df = build_schedule_luck(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike", 3: "Joe"})
    )

    assert sorted(df["roster_id"]) == [1, 2]
    for roster_id in (1, 2):
        row = _row(df, roster_id)
        assert row["games_played"] == 2
        assert row["all_play_games"] == 4  # 2 comparisons * 2 weeks
        assert row["all_play_win_pct"] == pytest.approx(0.5)
        assert row["expected_wins"] == pytest.approx(1.0)
        assert row["schedule_luck"] == pytest.approx(0.0)


def test_partial_bye_roster_uses_decisions_as_the_denominator() -> None:
    """A roster with two decided games and one bye gets
    ``expected_wins = all_play_win_pct * 2``, not ``* 3`` -- there was no
    opponent to beat in the bye week.

    Roster 1: week 1 beat roster 2 (120 vs 100), week 2 bye at 130.0, week 3
    beat roster 2 (140 vs 90). Roster 2 plays weeks 1 and 3 only.
        week 1 field 120, 100 -> roster 1 1-0
        week 2 field 130 only -> no comparisons at all (field size 1)
        week 3 field 140, 90  -> roster 1 1-0
    Roster 1's all-play is 2-0 of 2 = 1.0, and with 2 decided games its
    expected record is 2.0-0.0 against an actual 2-0: luck 0.0. Had the bye
    counted as a game, expected wins would have been 3.0 and the roster would
    have been reported as 1.0 wins unlucky for a week it could not have won.
    """
    rows = [
        _game(1, 2, 120.0, 100.0, week=1, matchup_id=1),
        _game(1, None, 130.0, None, week=2, matchup_id=None),
        _game(1, 2, 140.0, 90.0, week=3, matchup_id=1),
    ]
    df = build_schedule_luck(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    row = _row(df, 1)
    assert row["games_played"] == 2
    assert row["all_play_games"] == 2
    assert row["all_play_win_pct"] == pytest.approx(1.0)
    assert row["expected_wins"] == pytest.approx(2.0)
    assert row["expected_losses"] == pytest.approx(0.0)
    assert row["schedule_luck"] == pytest.approx(0.0)


def test_bye_only_roster_is_absent_but_still_shapes_other_rosters_rates() -> None:
    """A bye-only roster has ``weeks_played > 0`` but zero decisions: no row.

    Its score is still part of the week's comparison field, so it is excluded
    from the output, not from the league. Week 1: roster 1 100.0 beat roster 2
    90.0, roster 3 bye at 200.0. Roster 1's all-play is 1-1 (it loses to
    roster 3's bye score), not 1-0.
    """
    rows = [
        _game(1, 2, 100.0, 90.0, week=1, matchup_id=1),
        _game(3, None, 200.0, None, week=1, matchup_id=None),
    ]
    df = build_schedule_luck(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike", 3: "Joe"})
    )

    assert sorted(df["roster_id"]) == [1, 2]
    row = _row(df, 1)
    assert row["all_play_games"] == 2
    assert row["all_play_win_pct"] == pytest.approx(0.5)
    # 1 actual win against 0.5 expected: the schedule spared it roster 3.
    assert row["expected_wins"] == pytest.approx(0.5)
    assert row["schedule_luck"] == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Regular season vs. playoffs -- the phase-consistency guarantee
# --------------------------------------------------------------------------


def _mixed_phase_rows() -> list[dict]:
    """Four rosters: two regular-season weeks and one playoff week.

    Week 1 (regular): roster 1 120.0 beat roster 2 100.0; roster 3 110.0 beat
        roster 4 90.0. Field 120, 110, 100, 90 -> r1 3-0, r3 2-1, r2 1-2,
        r4 0-3.
    Week 2 (regular): roster 1 130.0 beat roster 3 90.0; roster 2 80.0 beat
        roster 4 70.0. Field 130, 90, 80, 70 -> r1 3-0, r3 2-1, r2 1-2,
        r4 0-3.
    Week 3 (playoff): roster 2 140.0 beat roster 1 50.0; roster 3 130.0 beat
        roster 4 120.0. Field 140, 130, 120, 50 -> r2 3-0, r3 2-1, r4 1-2,
        r1 0-3.

    Regular season only (2 decided games each, 6 all-play games each):
        r1: 2-0 actual, all-play 6-0 = 1.0     -> expected 2.0, luck  0.0
        r2: 1-1 actual, all-play 2-4 = 1/3     -> expected 0.6667, luck +0.3333
        r3: 1-1 actual, all-play 4-2 = 2/3     -> expected 1.3333, luck -0.3333
        r4: 0-2 actual, all-play 0-6 = 0.0     -> expected 0.0, luck  0.0

    All three weeks combined (3 decided games each, 9 all-play games each):
        r1: 2-1 actual, all-play 6-3 = 2/3     -> expected 2.0, luck  0.0
        r2: 2-1 actual, all-play 5-4 = 5/9     -> expected 1.6667, luck +0.3333
        r3: 2-1 actual, all-play 6-3 = 2/3     -> expected 2.0, luck  0.0
        r4: 0-3 actual, all-play 1-8 = 1/9     -> expected 0.3333, luck -0.3333
    """
    return [
        _game(1, 2, 120.0, 100.0, week=1, matchup_id=1),
        _game(3, 4, 110.0, 90.0, week=1, matchup_id=2),
        _game(1, 3, 130.0, 90.0, week=2, matchup_id=1),
        _game(2, 4, 80.0, 70.0, week=2, matchup_id=2),
        _game(1, 2, 50.0, 140.0, week=3, matchup_id=1, is_playoff=True),
        _game(3, 4, 130.0, 120.0, week=3, matchup_id=2, is_playoff=True),
    ]


def test_playoff_and_regular_season_weeks_are_combined_by_default() -> None:
    """No phase filter of its own: an unfiltered frame yields one combined
    result spanning both phases. See ``_mixed_phase_rows``' docstring.
    """
    teams = _teams_df({1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"})
    df = build_schedule_luck(_season_matchup_df(_mixed_phase_rows()), teams)

    assert "is_playoff" not in df.columns
    for roster_id in (1, 2, 3, 4):
        row = _row(df, roster_id)
        assert row["games_played"] == 3
        assert row["all_play_games"] == 9

    assert _row(df, 1)["all_play_win_pct"] == pytest.approx(2 / 3)
    assert _row(df, 1)["expected_wins"] == pytest.approx(2.0)
    assert _row(df, 1)["schedule_luck"] == pytest.approx(0.0)
    assert _row(df, 2)["schedule_luck"] == pytest.approx(1 / 3)
    assert _row(df, 3)["schedule_luck"] == pytest.approx(0.0)
    assert _row(df, 4)["schedule_luck"] == pytest.approx(-1 / 3)


def test_caller_filtering_the_input_keeps_both_halves_phase_consistent() -> None:
    """The documented regular-season-only call: filter ``season_matchup_df``
    on ``is_playoff`` *before* calling.

    Because both the actual record and the all-play rate are rebuilt from the
    filtered frame, the two halves cover the same two weeks -- ``games_played
    == 2`` and ``all_play_games == 6`` (3 comparisons * 2 weeks) for every
    roster -- rather than comparing a 2-game record against a 3-week scoring
    rate. See ``_mixed_phase_rows``' docstring for the hand computation.
    """
    teams = _teams_df({1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam"})
    frame = _season_matchup_df(_mixed_phase_rows())

    regular = build_schedule_luck(frame.loc[~frame["is_playoff"]], teams)

    for roster_id in (1, 2, 3, 4):
        row = _row(regular, roster_id)
        assert row["games_played"] == 2
        assert row["all_play_games"] == 6

    assert _row(regular, 1)["all_play_win_pct"] == pytest.approx(1.0)
    assert _row(regular, 1)["expected_wins"] == pytest.approx(2.0)
    assert _row(regular, 1)["schedule_luck"] == pytest.approx(0.0)
    assert _row(regular, 2)["expected_wins"] == pytest.approx(2 / 3)
    assert _row(regular, 2)["schedule_luck"] == pytest.approx(1 / 3)
    assert _row(regular, 3)["expected_wins"] == pytest.approx(4 / 3)
    assert _row(regular, 3)["schedule_luck"] == pytest.approx(-1 / 3)
    assert _row(regular, 4)["schedule_luck"] == pytest.approx(0.0)

    # The playoff week really is excluded: roster 3's combined luck is 0.0 but
    # its regular-season luck is negative, so the filter changed the answer.
    combined = build_schedule_luck(frame, teams)
    assert _row(combined, 3)["schedule_luck"] != pytest.approx(
        _row(regular, 3)["schedule_luck"]
    )


def test_playoff_only_filter_drops_rosters_that_never_played_a_playoff_game() -> None:
    """Filtering to ``is_playoff == True`` is the common way to produce a
    zero-games roster: an eliminated roster simply has no row.

    Only rosters 1-4's week-3 games are playoff games here; roster 5, which
    played a regular-season week only, disappears rather than appearing with
    a 0.0-0.0 expected record.
    """
    teams = _teams_df({1: "Alec", 2: "Mike", 3: "Joe", 4: "Sam", 5: "Pat"})
    rows = _mixed_phase_rows() + [_game(5, None, 95.0, None, week=1, matchup_id=None)]
    frame = _season_matchup_df(rows)

    playoffs = build_schedule_luck(frame.loc[frame["is_playoff"]], teams)

    assert sorted(playoffs["roster_id"]) == [1, 2, 3, 4]
    for roster_id in (1, 2, 3, 4):
        assert _row(playoffs, roster_id)["games_played"] == 1


def test_no_parameter_accepts_a_separately_built_table() -> None:
    """Structural guard for the design decision in the module docstring: the
    only inputs are ``season_matchup_df`` and ``teams_df``.

    If a future change added an ``all_play_df``/``standings_df`` parameter, a
    caller could once again supply two independently-filtered views of
    different game sets and get a silently meaningless luck number. This test
    fails if that door is reopened.
    """
    parameters = list(inspect.signature(build_schedule_luck).parameters)
    assert parameters == ["season_matchup_df", "teams_df"]


# --------------------------------------------------------------------------
# Missing values / edge cases
# --------------------------------------------------------------------------


def test_roster_with_no_matchup_rows_is_absent() -> None:
    """Rows are input-driven: a roster in ``teams_df`` that never appears in
    ``season_matchup_df`` gets no row, not an all-zero one.
    """
    rows = [_game(1, 2, 100.0, 90.0)]
    df = build_schedule_luck(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike", 3: "Joe"})
    )

    assert sorted(df["roster_id"]) == [1, 2]


def test_matchup_with_missing_points_yields_no_decision_and_no_rows() -> None:
    """A matchup with no loaded scores produces no winner, no loser and no
    all-play observation, so neither roster has a decided game and neither
    appears -- a missing score is never treated as ``0.0``.
    """
    rows = [_game(1, 2, None, None, week=1)]
    df = build_schedule_luck(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    assert df.empty
    assert list(df.columns) == SCHEDULE_LUCK_COLUMNS


def test_frame_of_byes_only_returns_empty_frame_with_columns() -> None:
    """Every roster is dropped by the zero-decisions rule; the result is an
    empty but correctly-shaped frame rather than a columnless one.
    """
    rows = [
        _game(1, None, 100.0, None, week=1, matchup_id=None),
        _game(2, None, 90.0, None, week=1, matchup_id=None),
    ]
    df = build_schedule_luck(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    assert df.empty
    assert list(df.columns) == SCHEDULE_LUCK_COLUMNS


def test_empty_input_returns_empty_frame_with_columns() -> None:
    df = build_schedule_luck(_season_matchup_df([]), _teams_df({1: "Alec"}))

    assert df.empty
    assert list(df.columns) == SCHEDULE_LUCK_COLUMNS


def test_decided_game_without_a_score_raises() -> None:
    """An internally inconsistent frame -- a recorded winner on a row with no
    points -- has a decided game but no measurable scoring strength, so it
    raises rather than guessing an ``all_play_win_pct``.

    This cannot come out of the real pipeline (``outcomes.py`` only sets
    ``winner``/``loser`` when both sides' points are present); it guards a
    hand-built or corrupted frame.
    """
    row = _game(1, 2, None, None, week=1)
    row["winner"] = 1
    row["loser"] = 2
    df = _season_matchup_df([row])

    with pytest.raises(ValueError, match="no all-play record"):
        build_schedule_luck(df, _teams_df({1: "Alec", 2: "Mike"}))


def test_owner_is_resolved_from_teams_df_and_unmapped_stays_none() -> None:
    """``owner`` comes from ``teams_df["display_name"]`` via FFA-050; a roster
    with no mapping stays ``None`` rather than becoming ``NaN`` or raising.
    """
    rows = [_game(1, 2, 100.0, 90.0)]
    df = build_schedule_luck(_season_matchup_df(rows), _teams_df({1: "Alec"}))

    assert _row(df, 1)["owner"] == "Alec"
    assert _row(df, 2)["owner"] is None


def test_empty_teams_df_resolves_every_owner_to_none() -> None:
    rows = [_game(1, 2, 100.0, 90.0)]
    df = build_schedule_luck(_season_matchup_df(rows), _empty_teams_df())

    assert list(df["owner"]) == [None, None]
    assert _row(df, 1)["expected_wins"] == pytest.approx(1.0)


def test_multiple_seasons_are_compared_within_season_but_summed_across() -> None:
    """``(season, week)`` is the all-play grouping key (inherited from
    FFA-051), so a 2024 score never beats a 2025 one, while the actual record
    and the season totals sum across both seasons.

    2024 week 1: roster 1 100.0 beat roster 2 90.0.
    2025 week 1: roster 1 60.0 lost to roster 2 70.0.
    Each roster: 2 decided games, 2 all-play games, 1-1 both ways -> luck 0.0.
    """
    rows = [
        _game(1, 2, 100.0, 90.0, week=1, season="2024"),
        _game(1, 2, 60.0, 70.0, week=1, season="2025"),
    ]
    df = build_schedule_luck(
        _season_matchup_df(rows), _teams_df({1: "Alec", 2: "Mike"})
    )

    for roster_id in (1, 2):
        row = _row(df, roster_id)
        assert row["games_played"] == 2
        assert row["all_play_games"] == 2
        assert row["all_play_win_pct"] == pytest.approx(0.5)
        assert row["schedule_luck"] == pytest.approx(0.0)
