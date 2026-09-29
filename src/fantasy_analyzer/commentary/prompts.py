"""Turn commentary context dataclasses into ready-to-paste LLM prompt text (FFA-092).

This module is pure formatting: it computes **no** new data of its own. Every
function here takes a dataclass already built by
:mod:`fantasy_analyzer.commentary.context` (:class:`MatchupContext` or
:class:`LeagueWeekContext`) and renders it into a single prompt string with a
fixed three-part structure:

1. **Role/goal framing** -- who the model is (a fantasy football commentary
   writer) and what it should produce.
2. **Data block** -- the context dataclass serialized compactly as JSON
   (:func:`dataclasses.asdict` + :func:`json.dumps`), not hand-written prose.
   The model does the writing; this module only hands it structured facts.
3. **Constraints** -- tone, an approximate length, which teams/managers must
   be named, and an explicit "don't invent stats not present in the data
   above" guardrail.

No network access happens here, and no field is ever paraphrased or
recomputed -- consistent with ``context.py``'s "pure aggregation" contract
and AGENTS.md's "analytics functions must be deterministic and testable
without live HTTP" rule (this module has no HTTP dependency to begin with).

Tone
----

:data:`TONE_DESCRIPTIONS` maps each supported ``tone`` string to a short
constraint sentence appended to the prompt. Two tones are supported to
start: ``"witty"`` (sharp, funny, a little mean, still accurate) and
``"straightforward"`` (plain, factual, no jokes). Both ``tone`` and
``max_words`` are real parameters on every function below -- never
hardcoded -- so a league that wants less snark, or a shorter recap, can ask
for it without touching this module.

Two matchup-prompt shapes
--------------------------

Per the design doc's "one prompt per matchup, or a combined prompt covering
all matchups in a week" note, both shapes are provided:

- :func:`weekly_matchup_prompt` -- one prompt for a single
  :class:`~fantasy_analyzer.commentary.context.MatchupContext`.
- :func:`combined_matchup_prompt` -- one prompt covering every matchup in a
  week, given a ``list[MatchupContext]`` (typically
  :func:`~fantasy_analyzer.commentary.context.build_matchup_context`'s
  return value).
"""

from __future__ import annotations

import dataclasses
import json

from fantasy_analyzer.commentary.context import LeagueWeekContext, MatchupContext

#: Supported ``tone`` values and the constraint sentence each adds to the
#: prompt. ``"witty"`` is the default across every function in this module;
#: ``"straightforward"`` is the plain-language alternative. Any other tone
#: string is passed straight through to the same sentence template with no
#: further validation -- this module deliberately does not hardcode an
#: exhaustive tone list, so a caller can ask for e.g. ``"deadpan"`` and get
#: a reasonable framing sentence even though it isn't pre-described here.
TONE_DESCRIPTIONS: dict[str, str] = {
    "witty": (
        "Witty and a little irreverent -- sharp one-liners and light "
        "trash talk are welcome, but every joke must be grounded in the "
        "data above."
    ),
    "straightforward": (
        "Straightforward and factual -- plain language, no jokes, no "
        "editorializing beyond what the data above supports."
    ),
}

#: Default tone for every prompt function in this module.
DEFAULT_TONE = "witty"

#: Default approximate word-count ceiling for a single matchup writeup.
DEFAULT_MATCHUP_MAX_WORDS = 150

#: Default approximate word-count ceiling for the combined weekly-matchups
#: prompt (covers multiple matchups, so allotted more room per matchup).
DEFAULT_COMBINED_MAX_WORDS = 120

#: Default approximate word-count ceiling for the league-wide recap.
DEFAULT_RECAP_MAX_WORDS = 400


def _tone_sentence(tone: str) -> str:
    """Resolve ``tone`` to its constraint sentence, defaulting gracefully.

    Args:
        tone: A tone label, e.g. ``"witty"`` or ``"straightforward"``.

    Returns:
        :data:`TONE_DESCRIPTIONS[tone]` if known, otherwise a generic
        sentence naming ``tone`` verbatim (see the module docstring's tone
        note -- unknown tones are not rejected).
    """
    return TONE_DESCRIPTIONS.get(tone, f"Tone: {tone}.")


def _data_block(payload: object) -> str:
    """Serialize a dataclass (or list of dataclasses) as a JSON code block."""
    as_dict = (
        dataclasses.asdict(payload)
        if dataclasses.is_dataclass(payload)
        else [dataclasses.asdict(item) for item in payload]
    )
    return json.dumps(as_dict, indent=2, default=str)


def _constraints(tone: str, max_words: int, *, named_entities: str) -> str:
    """Build the shared constraints section used by every prompt function.

    Args:
        tone: A tone label; resolved via :func:`_tone_sentence`.
        max_words: Approximate word-count ceiling to instruct the model
            with.
        named_entities: A short phrase describing which teams/managers must
            be called out by name (varies per prompt -- e.g. "both
            managers" for a single matchup, "every manager" for a recap).
    """
    return "\n".join(
        [
            "Constraints:",
            f"- {_tone_sentence(tone)}",
            f"- Keep it to roughly {max_words} words or fewer.",
            f"- Call out {named_entities} by name at least once.",
            "- Do not invent stats, players, or scores that are not present "
            "in the data above -- if something isn't in the data, don't "
            "claim it happened.",
            "- Write ready-to-publish prose, not a bulleted recap of the data block.",
        ]
    )


def weekly_matchup_prompt(
    context: MatchupContext,
    *,
    tone: str = DEFAULT_TONE,
    max_words: int = DEFAULT_MATCHUP_MAX_WORDS,
) -> str:
    """Build a prompt asking an LLM to write commentary for one matchup.

    Args:
        context: A single matchup's context, as produced by
            :func:`~fantasy_analyzer.commentary.context.build_matchup_context`.
        tone: A tone label (see :data:`TONE_DESCRIPTIONS`). Defaults to
            :data:`DEFAULT_TONE`.
        max_words: Approximate word-count ceiling for the writeup. Defaults
            to :data:`DEFAULT_MATCHUP_MAX_WORDS`.

    Returns:
        A single prompt string: role/goal framing, the matchup's data as a
        JSON block, and explicit constraints. Ready to paste into an LLM
        chat, or to hand a future ``client.py`` (FFA-094, out of scope
        here).
    """
    owner_1 = context.team_1.owner or f"roster {context.team_1.roster_id}"
    owner_2 = context.team_2.owner or f"roster {context.team_2.roster_id}"

    intro = (
        "You are a witty fantasy football commentary writer producing a "
        f"recap of a single week {context.week} fantasy football matchup "
        f"between {owner_1} and {owner_2}. Using only the structured data "
        "below, write a short, entertaining recap of this matchup."
    )

    return "\n\n".join(
        [
            intro,
            "Matchup data (JSON):\n```json\n" + _data_block(context) + "\n```",
            _constraints(tone, max_words, named_entities="both managers"),
        ]
    )


def combined_matchup_prompt(
    contexts: list[MatchupContext],
    *,
    tone: str = DEFAULT_TONE,
    max_words: int = DEFAULT_COMBINED_MAX_WORDS,
) -> str:
    """Build a single prompt covering every matchup in a week.

    Args:
        contexts: All of a week's matchup contexts, typically
            :func:`~fantasy_analyzer.commentary.context.build_matchup_context`'s
            return value.
        tone: A tone label (see :data:`TONE_DESCRIPTIONS`). Defaults to
            :data:`DEFAULT_TONE`.
        max_words: Approximate word-count ceiling *per matchup* -- the
            model is asked to write roughly this many words for each
            matchup in the list. Defaults to
            :data:`DEFAULT_COMBINED_MAX_WORDS`.

    Returns:
        A single prompt string covering all of ``contexts`` at once. If
        ``contexts`` is empty, the data block is an empty JSON array and
        the framing still explains the (lack of) matchups -- callers
        should typically check for an empty list before calling this and
        skip prompt generation entirely, but this function does not raise.
    """
    week = contexts[0].week if contexts else None
    week_label = f"week {week}" if week is not None else "this week"

    intro = (
        "You are a witty fantasy football commentary writer producing a "
        f"recap of every fantasy football matchup in {week_label}. Using "
        "only the structured data below (one entry per matchup), write a "
        "short recap of each matchup, covering all of them in one piece."
    )

    return "\n\n".join(
        [
            intro,
            "Matchups data (JSON list):\n```json\n" + _data_block(contexts) + "\n```",
            _constraints(tone, max_words, named_entities="every pair of managers"),
        ]
    )


def league_week_recap_prompt(
    context: LeagueWeekContext,
    *,
    tone: str = DEFAULT_TONE,
    max_words: int = DEFAULT_RECAP_MAX_WORDS,
) -> str:
    """Build a prompt asking an LLM to write a league-wide weekly recap.

    Args:
        context: The league-wide weekly context, as produced by
            :func:`~fantasy_analyzer.commentary.context.build_league_week_context`.
        tone: A tone label (see :data:`TONE_DESCRIPTIONS`). Defaults to
            :data:`DEFAULT_TONE`.
        max_words: Approximate word-count ceiling for the recap. Defaults
            to :data:`DEFAULT_RECAP_MAX_WORDS`.

    Returns:
        A single prompt string: role/goal framing, the league-week data as
        a JSON block, and explicit constraints.
    """
    week_label = f"week {context.week}" if context.week is not None else "this week"

    intro = (
        "You are a witty fantasy football commentary writer producing a "
        f"league-wide recap of {week_label}, covering standings movement, "
        "power rankings, the week's scoring leaderboard, and schedule-luck "
        "outliers. Using only the structured data below, write a short "
        "recap covering the league as a whole."
    )

    return "\n\n".join(
        [
            intro,
            "League-week data (JSON):\n```json\n" + _data_block(context) + "\n```",
            _constraints(tone, max_words, named_entities="every manager mentioned"),
        ]
    )
