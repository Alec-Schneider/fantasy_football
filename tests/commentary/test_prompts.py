"""Tests for the commentary prompt templates (FFA-092).

These tests build small, hand-constructed :class:`MatchupContext`/
:class:`LeagueWeekContext` dataclasses directly (no ``build_*`` context
builders, no HTTP), and assert on the prompt text's *structural* markers --
role framing present, a data block present with the right facts embedded,
constraints present, and that ``tone`` actually changes the wording --
rather than asserting an exact full-string match, per the ticket's guidance.
"""

from __future__ import annotations

import json

import pytest

from fantasy_analyzer.commentary.context import (
    AllPlayWeekRecord,
    HeadToHead,
    LeagueWeekContext,
    MatchupContext,
    ScheduleLuckOutliers,
    Streak,
    TeamWeekSummary,
    WeeklyScoringLeaderboard,
)
from fantasy_analyzer.commentary.prompts import (
    combined_matchup_prompt,
    league_week_recap_prompt,
    weekly_matchup_prompt,
)


def _team(roster_id: int, owner: str, points: float) -> TeamWeekSummary:
    return TeamWeekSummary(
        roster_id=roster_id,
        owner=owner,
        points=points,
        projected_points=None,
        all_play=AllPlayWeekRecord(wins=2, losses=1, ties=0, win_pct=0.667, rank=1),
    )


def _matchup_context(week: int = 3) -> MatchupContext:
    return MatchupContext(
        season="2025",
        week=week,
        is_playoff=False,
        matchup_id=31,
        team_1=_team(1, "Alice", 100.0),
        team_2=_team(2, "Bob", 95.0),
        margin=5.0,
        winner_roster_id=1,
        loser_roster_id=2,
        is_tie=False,
        head_to_head=HeadToHead(
            meetings=2,
            roster_1_wins=1,
            roster_1_losses=1,
            ties=0,
            last_meeting_season="2025",
            last_meeting_week=2,
            last_meeting_winner_roster_id=2,
        ),
        streak=Streak(
            holder_roster_id=None,
            length=0,
            snapped_this_week=False,
            is_revenge_game=True,
        ),
    )


def _league_week_context(week: int = 3) -> LeagueWeekContext:
    return LeagueWeekContext(
        season="2025",
        week=week,
        standings=[],
        power_ranking_deltas=[],
        weekly_leaderboard=WeeklyScoringLeaderboard(
            highest_score=None,
            lowest_score=None,
            biggest_blowout=None,
            closest_game=None,
        ),
        schedule_luck_outliers=ScheduleLuckOutliers(luckiest=None, unluckiest=None),
    )


# --------------------------------------------------------------------------
# weekly_matchup_prompt
# --------------------------------------------------------------------------


def test_weekly_matchup_prompt_has_role_framing_data_block_and_constraints() -> None:
    prompt = weekly_matchup_prompt(_matchup_context())

    assert "commentary writer" in prompt.lower()
    assert "Alice" in prompt and "Bob" in prompt
    assert "```json" in prompt
    assert "Constraints:" in prompt
    assert "don't invent" in prompt.lower() or "do not invent" in prompt.lower()


def test_weekly_matchup_prompt_data_block_is_valid_json_matching_context() -> None:
    context = _matchup_context()
    prompt = weekly_matchup_prompt(context)

    block = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    payload = json.loads(block)

    assert payload["week"] == 3
    assert payload["team_1"]["owner"] == "Alice"
    assert payload["team_1"]["points"] == pytest.approx(100.0)
    assert payload["margin"] == pytest.approx(5.0)


def test_weekly_matchup_prompt_tone_changes_constraint_wording() -> None:
    witty = weekly_matchup_prompt(_matchup_context(), tone="witty")
    straightforward = weekly_matchup_prompt(_matchup_context(), tone="straightforward")

    assert witty != straightforward
    assert "witty" in witty.lower() or "irreverent" in witty.lower()
    assert "straightforward" in straightforward.lower()
    assert "joke" in straightforward.lower()


def test_weekly_matchup_prompt_max_words_is_reflected_in_constraints() -> None:
    prompt = weekly_matchup_prompt(_matchup_context(), max_words=42)
    assert "42" in prompt


# --------------------------------------------------------------------------
# combined_matchup_prompt
# --------------------------------------------------------------------------


def test_combined_matchup_prompt_covers_every_matchup() -> None:
    contexts = [
        _matchup_context(week=3),
        MatchupContext(
            season="2025",
            week=3,
            is_playoff=False,
            matchup_id=32,
            team_1=_team(3, "Cara", 80.0),
            team_2=_team(4, "Dan", 90.0),
            margin=10.0,
            winner_roster_id=4,
            loser_roster_id=3,
            is_tie=False,
            head_to_head=HeadToHead(
                meetings=0,
                roster_1_wins=0,
                roster_1_losses=0,
                ties=0,
                last_meeting_season=None,
                last_meeting_week=None,
                last_meeting_winner_roster_id=None,
            ),
            streak=Streak(
                holder_roster_id=None,
                length=0,
                snapped_this_week=False,
                is_revenge_game=False,
            ),
        ),
    ]
    prompt = combined_matchup_prompt(contexts)

    assert "week 3" in prompt
    assert "```json" in prompt
    block = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    payload = json.loads(block)
    assert len(payload) == 2
    assert {row["matchup_id"] for row in payload} == {31, 32}
    assert "Constraints:" in prompt


def test_combined_matchup_prompt_empty_list_does_not_raise() -> None:
    prompt = combined_matchup_prompt([])
    assert "```json" in prompt
    block = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(block) == []


def test_combined_matchup_prompt_tone_changes_constraint_wording() -> None:
    witty = combined_matchup_prompt([_matchup_context()], tone="witty")
    straightforward = combined_matchup_prompt(
        [_matchup_context()], tone="straightforward"
    )
    assert witty != straightforward


# --------------------------------------------------------------------------
# league_week_recap_prompt
# --------------------------------------------------------------------------


def test_league_week_recap_prompt_has_role_framing_data_block_and_constraints() -> None:
    prompt = league_week_recap_prompt(_league_week_context())

    assert "commentary writer" in prompt.lower()
    assert "league-wide" in prompt.lower()
    assert "```json" in prompt
    assert "Constraints:" in prompt
    assert "week 3" in prompt


def test_league_week_recap_prompt_data_block_matches_context() -> None:
    context = _league_week_context(week=5)
    prompt = league_week_recap_prompt(context)

    block = prompt.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    payload = json.loads(block)
    assert payload["week"] == 5
    assert payload["season"] == "2025"


def test_league_week_recap_prompt_tone_changes_constraint_wording() -> None:
    witty = league_week_recap_prompt(_league_week_context(), tone="witty")
    straightforward = league_week_recap_prompt(
        _league_week_context(), tone="straightforward"
    )
    assert witty != straightforward
    assert "joke" in straightforward.lower()
