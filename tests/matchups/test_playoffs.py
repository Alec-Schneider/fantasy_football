"""Tests for playoff bracket normalization and final placements (FFA-055).

The normalization core (:func:`build_bracket_df`,
:func:`build_playoff_brackets`, :func:`build_final_placements`) is tested
purely, with no HTTP involved -- primarily against the repository's real
sanitized ``winners_bracket.json``/``losers_bracket.json`` fixtures, whose
expected placements are walked through by hand in
:func:`test_real_fixtures_final_placements_hand_checked`. Hand-built
brackets cover the mid-tournament and self-contradictory cases the real
fixtures do not contain. The thin fetching wrapper
(:func:`load_playoff_brackets`) is exercised via ``requests_mock`` against
those same fixtures -- the live Sleeper API is never contacted.
"""

import pandas as pd
import pytest
import requests_mock as requests_mock_lib

from fantasy_analyzer.matchups import (
    FINAL_PLACEMENT_COLUMNS,
    LOSERS_BRACKET,
    PLAYOFF_BRACKET_COLUMNS,
    WINNERS_BRACKET,
    build_bracket_df,
    build_final_placements,
    build_playoff_brackets,
    load_playoff_brackets,
)
from fantasy_analyzer.sleeper import SleeperClient


def _teams_df(rows: list[dict]) -> pd.DataFrame:
    columns = ["roster_id", "owner_id", "display_name", "team_name"]
    return pd.DataFrame(rows, columns=columns)


def _team_row(roster_id: int, display_name: str | None) -> dict:
    return {
        "roster_id": roster_id,
        "owner_id": f"user_{roster_id}",
        "display_name": display_name,
        "team_name": f"Team {roster_id}",
    }


def _row(df: pd.DataFrame, match_id: int) -> pd.Series:
    return df[df["match_id"] == match_id].iloc[0]


# -------------------------
# build_bracket_df
# -------------------------


def test_build_bracket_df_normalizes_real_winners_fixture(load_sleeper_fixture) -> None:
    """The 4 winners-bracket matches map onto the normalized columns."""
    raw = load_sleeper_fixture("winners_bracket.json")

    df = build_bracket_df(raw, WINNERS_BRACKET)

    assert list(df.columns) == PLAYOFF_BRACKET_COLUMNS
    assert len(df) == 4
    assert (df["bracket"] == WINNERS_BRACKET).all()
    assert list(df["round"]) == [1, 1, 2, 2]
    assert list(df["match_id"]) == [1, 2, 3, 4]

    # r1 m1: rosters 1 and 4, roster 1 won, no placement awarded.
    first = _row(df, 1)
    assert first["roster_1_id"] == 1
    assert first["roster_2_id"] == 4
    assert first["winner_roster_id"] == 1
    assert first["loser_roster_id"] == 4
    assert first["roster_1_from"] is None
    assert first["roster_2_from"] is None
    assert first["winner_placement"] is None
    assert first["loser_placement"] is None


def test_build_bracket_df_renders_from_references(load_sleeper_fixture) -> None:
    """``t1_from``/``t2_from`` become readable strings, not raw dicts."""
    df = build_bracket_df(load_sleeper_fixture("winners_bracket.json"), WINNERS_BRACKET)

    championship = _row(df, 3)
    assert championship["roster_1_from"] == "winner_of_match_1"
    assert championship["roster_2_from"] == "winner_of_match_2"

    third_place = _row(df, 4)
    assert third_place["roster_1_from"] == "loser_of_match_1"
    assert third_place["roster_2_from"] == "loser_of_match_2"


def test_build_bracket_df_expands_p_into_winner_and_loser_placements(
    load_sleeper_fixture,
) -> None:
    """Sleeper's single ``p`` becomes explicit ``p`` / ``p + 1`` columns."""
    df = build_bracket_df(load_sleeper_fixture("winners_bracket.json"), WINNERS_BRACKET)

    championship = _row(df, 3)  # "p": 1
    assert championship["winner_placement"] == 1
    assert championship["loser_placement"] == 2

    third_place = _row(df, 4)  # "p": 3
    assert third_place["winner_placement"] == 3
    assert third_place["loser_placement"] == 4


def test_build_bracket_df_labels_losers_bracket(load_sleeper_fixture) -> None:
    df = build_bracket_df(load_sleeper_fixture("losers_bracket.json"), LOSERS_BRACKET)

    assert (df["bracket"] == LOSERS_BRACKET).all()
    assert len(df) == 3
    consolation_final = _row(df, 3)  # "p": 5
    assert consolation_final["winner_placement"] == 5
    assert consolation_final["loser_placement"] == 6


def test_build_bracket_df_handles_unplayed_match() -> None:
    """A scheduled-but-unplayed match has no winner, loser, or participants."""
    raw = [{"r": 2, "m": 3, "t1_from": {"w": 1}, "t2_from": {"w": 2}, "p": 1}]

    df = build_bracket_df(raw, WINNERS_BRACKET)

    match = _row(df, 3)
    assert match["roster_1_id"] is None
    assert match["roster_2_id"] is None
    assert match["winner_roster_id"] is None
    assert match["loser_roster_id"] is None
    assert match["roster_1_from"] == "winner_of_match_1"
    assert match["winner_placement"] == 1


def test_build_bracket_df_preserves_none_alongside_present_values() -> None:
    """Mixing played and unplayed matches keeps ``None`` as ``None``."""
    raw = [
        {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
        {"r": 2, "m": 2, "t1_from": {"w": 1}},
    ]

    df = build_bracket_df(raw, WINNERS_BRACKET)

    assert _row(df, 1)["winner_roster_id"] == 1
    assert _row(df, 2)["winner_roster_id"] is None
    assert _row(df, 2)["roster_2_from"] is None


def test_build_bracket_df_sorts_by_round_then_match() -> None:
    raw = [
        {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},
        {"r": 1, "m": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
        {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
    ]

    df = build_bracket_df(raw, WINNERS_BRACKET)

    assert list(df["round"]) == [1, 1, 2]
    assert list(df["match_id"]) == [1, 2, 3]


def test_build_bracket_df_empty_and_none_return_shaped_frame() -> None:
    for raw in ([], None):
        df = build_bracket_df(raw, LOSERS_BRACKET)
        assert df.empty
        assert list(df.columns) == PLAYOFF_BRACKET_COLUMNS


# -------------------------
# build_playoff_brackets
# -------------------------


def test_build_playoff_brackets_combines_both_fixtures(load_sleeper_fixture) -> None:
    df = build_playoff_brackets(
        load_sleeper_fixture("winners_bracket.json"),
        load_sleeper_fixture("losers_bracket.json"),
    )

    assert list(df.columns) == PLAYOFF_BRACKET_COLUMNS
    assert len(df) == 7
    assert list(df["bracket"]) == [WINNERS_BRACKET] * 4 + [LOSERS_BRACKET] * 3
    # match_id is unique only within a bracket -- both brackets have an m=1.
    assert list(df[df["match_id"] == 1]["bracket"]) == [WINNERS_BRACKET, LOSERS_BRACKET]


def test_build_playoff_brackets_without_losers_bracket(load_sleeper_fixture) -> None:
    """A league with no consolation bracket still normalizes cleanly."""
    df = build_playoff_brackets(load_sleeper_fixture("winners_bracket.json"))

    assert len(df) == 4
    assert (df["bracket"] == WINNERS_BRACKET).all()


def test_build_playoff_brackets_both_empty_returns_shaped_frame() -> None:
    df = build_playoff_brackets([], [])

    assert df.empty
    assert list(df.columns) == PLAYOFF_BRACKET_COLUMNS


# -------------------------
# build_final_placements
# -------------------------


def test_real_fixtures_final_placements_hand_checked(load_sleeper_fixture) -> None:
    """Hand-walk of the repository's real 8-team bracket fixtures.

    Winners bracket:
      m1 (r1): 1 beats 4.  m2 (r1): 2 beats 3.  -- no ``p``, no places.
      m3 (r2, p=1): 1 beats 2  -> place 1 = roster 1, place 2 = roster 2.
      m4 (r2, p=3): 3 beats 4  -> place 3 = roster 3, place 4 = roster 4.

    Losers bracket:
      m1 (r1): 5 beats 8.  m2 (r1): 7 beats 6.  -- no ``p``, no places.
      m3 (r2, p=5): 7 beats 5  -> place 5 = roster 7, place 6 = roster 5.

    Rosters 6 and 8 (the losers-bracket round-1 losers) never play a
    7th/8th-place game, so the bracket determines nothing about them and
    they must be absent from the output entirely.
    """
    bracket_df = build_playoff_brackets(
        load_sleeper_fixture("winners_bracket.json"),
        load_sleeper_fixture("losers_bracket.json"),
    )
    teams_df = _teams_df([_team_row(roster_id, None) for roster_id in range(1, 9)])

    df = build_final_placements(bracket_df, teams_df)

    assert list(df.columns) == FINAL_PLACEMENT_COLUMNS
    assert list(df["placement"]) == [1, 2, 3, 4, 5, 6]
    assert list(df["roster_id"]) == [1, 2, 3, 4, 7, 5]
    assert 6 not in set(df["roster_id"])
    assert 8 not in set(df["roster_id"])


def test_final_placements_trace_back_to_awarding_match(load_sleeper_fixture) -> None:
    bracket_df = build_playoff_brackets(
        load_sleeper_fixture("winners_bracket.json"),
        load_sleeper_fixture("losers_bracket.json"),
    )

    df = build_final_placements(bracket_df, _teams_df([]))
    by_placement = df.set_index("placement")

    assert by_placement.loc[1, "bracket"] == WINNERS_BRACKET
    assert by_placement.loc[1, "match_id"] == 3
    assert by_placement.loc[4, "match_id"] == 4
    assert by_placement.loc[5, "bracket"] == LOSERS_BRACKET
    assert by_placement.loc[6, "match_id"] == 3


def test_final_placements_resolve_owner_labels(load_sleeper_fixture) -> None:
    bracket_df = build_bracket_df(
        load_sleeper_fixture("winners_bracket.json"), WINNERS_BRACKET
    )
    teams_df = _teams_df([_team_row(1, "Alec"), _team_row(2, "Mike")])

    df = build_final_placements(bracket_df, teams_df)
    by_roster = df.set_index("roster_id")

    assert by_roster.loc[1, "owner"] == "Alec"
    assert by_roster.loc[2, "owner"] == "Mike"


def test_final_placements_unmapped_roster_owner_is_none(load_sleeper_fixture) -> None:
    """Roster 3 has no teams_df row -- owner stays ``None``, no crash."""
    bracket_df = build_bracket_df(
        load_sleeper_fixture("winners_bracket.json"), WINNERS_BRACKET
    )
    teams_df = _teams_df([_team_row(1, "Alec")])

    df = build_final_placements(bracket_df, teams_df)
    by_roster = df.set_index("roster_id")

    assert by_roster.loc[1, "owner"] == "Alec"
    assert by_roster.loc[3, "owner"] is None


def test_final_placements_empty_teams_df(load_sleeper_fixture) -> None:
    bracket_df = build_bracket_df(
        load_sleeper_fixture("winners_bracket.json"), WINNERS_BRACKET
    )

    df = build_final_placements(bracket_df, _teams_df([]))

    assert list(df["placement"]) == [1, 2, 3, 4]
    assert df["owner"].isna().all()


def test_final_placements_skip_unplayed_placement_match() -> None:
    """A mid-tournament bracket: the final is scheduled but not yet played.

    m1/m2 are played but award no place; m3 carries ``p: 1`` yet has no
    ``w``/``l`` -- so nothing is determined and the output is empty.
    """
    raw = [
        {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
        {"r": 1, "m": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
        {"r": 2, "m": 3, "t1": 1, "t2": 2, "t1_from": {"w": 1}, "p": 1},
    ]

    df = build_final_placements(build_bracket_df(raw, WINNERS_BRACKET), _teams_df([]))

    assert df.empty
    assert list(df.columns) == FINAL_PLACEMENT_COLUMNS


def test_final_placements_partially_played_bracket_keeps_decided_places() -> None:
    """The third-place game is done but the final is not -- places 3/4 only."""
    raw = [
        {"r": 2, "m": 3, "t1": 1, "t2": 2, "p": 1},
        {"r": 2, "m": 4, "t1": 4, "t2": 3, "w": 3, "l": 4, "p": 3},
    ]

    df = build_final_placements(build_bracket_df(raw, WINNERS_BRACKET), _teams_df([]))

    assert list(df["placement"]) == [3, 4]
    assert list(df["roster_id"]) == [3, 4]


def test_final_placements_no_placement_awarding_matches() -> None:
    """A bracket that only decides advancement determines no final places."""
    raw = [
        {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
        {"r": 1, "m": 2, "t1": 2, "t2": 3, "w": 2, "l": 3},
    ]

    df = build_final_placements(build_bracket_df(raw, WINNERS_BRACKET), _teams_df([]))

    assert df.empty
    assert list(df.columns) == FINAL_PLACEMENT_COLUMNS


def test_final_placements_empty_bracket_df() -> None:
    df = build_final_placements(build_bracket_df([], WINNERS_BRACKET), _teams_df([]))

    assert df.empty
    assert list(df.columns) == FINAL_PLACEMENT_COLUMNS


def test_final_placements_raise_on_conflicting_placements() -> None:
    """Roster 2 is credited both 2nd (m3 loser) and 3rd (m4 winner)."""
    raw = [
        {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},
        {"r": 2, "m": 4, "t1": 2, "t2": 4, "w": 2, "l": 4, "p": 3},
    ]
    bracket_df = build_bracket_df(raw, WINNERS_BRACKET)

    with pytest.raises(ValueError, match="conflicting final placements"):
        build_final_placements(bracket_df, _teams_df([]))


def test_final_placements_conflict_detected_across_brackets() -> None:
    """The same roster placed by both brackets is still a conflict."""
    winners = [{"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1}]
    losers = [{"r": 2, "m": 3, "t1": 2, "t2": 5, "w": 2, "l": 5, "p": 5}]
    bracket_df = build_playoff_brackets(winners, losers)

    with pytest.raises(ValueError, match="roster_id 2"):
        build_final_placements(bracket_df, _teams_df([]))


def test_final_placements_allow_repeated_identical_assignment() -> None:
    """Duplicated but consistent data is deduped, keeping the first match."""
    raw = [
        {"r": 2, "m": 3, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},
        {"r": 3, "m": 4, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1},
    ]

    df = build_final_placements(build_bracket_df(raw, WINNERS_BRACKET), _teams_df([]))

    assert list(df["placement"]) == [1, 2]
    assert list(df["match_id"]) == [3, 3]


# -------------------------
# load_playoff_brackets (fetching wrapper)
# -------------------------


def test_load_playoff_brackets_fetches_both_endpoints(load_sleeper_fixture) -> None:
    client = SleeperClient()
    league_id = "9999"

    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/league/{league_id}/winners_bracket",
            json=load_sleeper_fixture("winners_bracket.json"),
        )
        m.get(
            f"{SleeperClient.BASE_URL}/league/{league_id}/losers_bracket",
            json=load_sleeper_fixture("losers_bracket.json"),
        )

        df = load_playoff_brackets(client, league_id)

    assert m.call_count == 2
    assert len(df) == 7
    assert set(df["bracket"]) == {WINNERS_BRACKET, LOSERS_BRACKET}


def test_load_playoff_brackets_handles_empty_losers_bracket(
    load_sleeper_fixture,
) -> None:
    client = SleeperClient()
    league_id = "9999"

    with requests_mock_lib.Mocker() as m:
        m.get(
            f"{SleeperClient.BASE_URL}/league/{league_id}/winners_bracket",
            json=load_sleeper_fixture("winners_bracket.json"),
        )
        m.get(f"{SleeperClient.BASE_URL}/league/{league_id}/losers_bracket", json=[])

        df = load_playoff_brackets(client, league_id)

    assert len(df) == 4
    assert (df["bracket"] == WINNERS_BRACKET).all()
