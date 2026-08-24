"""Normalize Sleeper playoff brackets and derive final placements (FFA-055).

Sleeper exposes a league's postseason as two independent bracket payloads --
the winners (championship) bracket and the losers (consolation) bracket, via
``SleeperClient.get_winners_bracket``/``get_losers_bracket``. Each payload is
a flat list of bracket matches:

.. code-block:: json

    {"r": 1, "m": 1, "t1": 1, "t2": 4, "w": 1, "l": 4}
    {"r": 2, "m": 3, "t1": 1, "t2": 2, "t1_from": {"w": 1},
     "t2_from": {"w": 2}, "w": 1, "l": 2, "p": 1}

This module turns those raw payloads into a normalized bracket DataFrame
(:func:`build_bracket_df`, :func:`build_playoff_brackets`) and, from it, the
league's final placement table (:func:`build_final_placements`). The pure
composition core performs no network access; :func:`load_playoff_brackets`
is the thin fetching wrapper around it, mirroring
:mod:`~fantasy_analyzer.matchups.loader`'s split.

Raw field mapping
------------------

- ``r`` -> ``round`` -- round number within the bracket.
- ``m`` -> ``match_id`` -- the match's own id, unique *within one bracket*
  only. A combined winners+losers frame must therefore be keyed by
  ``(bracket, match_id)``, never ``match_id`` alone.
- ``t1``/``t2`` -> ``roster_1_id``/``roster_2_id`` -- the two rosters in the
  match, or ``None`` when Sleeper has not filled the slot in yet.
- ``t1_from``/``t2_from`` -> ``roster_1_from``/``roster_2_from`` -- how an
  unfilled slot will be populated, rendered as a readable string:
  ``{"w": 1}`` -> ``"winner_of_match_1"``, ``{"l": 2}`` ->
  ``"loser_of_match_2"``. ``None`` when the match carries no such reference
  (typically a first-round match, whose participants are seeded directly).
  These references are **not** resolved into concrete roster ids by walking
  earlier rounds: once an earlier match has been played, its own ``w``/``l``
  states the same fact more directly, and Sleeper itself backfills ``t1``/
  ``t2`` at that point. Re-deriving it here would duplicate that with no new
  information.
- ``w``/``l`` -> ``winner_roster_id``/``loser_roster_id`` -- ``None`` for a
  match that has not been played yet, so a bracket can be normalized
  mid-tournament, not only once complete.
- ``p`` -> ``winner_placement``/``loser_placement`` -- see below.

Placement semantics
--------------------

Sleeper marks a placement-awarding match with a single ``p`` field: the
match's **winner** finishes in place ``p`` and its **loser** finishes in
place ``p + 1``. Rather than carry the opaque ``p`` through, this module
stores both sides explicitly as ``winner_placement`` (``p``) and
``loser_placement`` (``p + 1``), so no reader has to know Sleeper's raw
convention to interpret a row. Both are ``None`` on a match with no ``p``.

Crucially, **not every match awards a placement**. Most first-round and
semifinal matches only decide who advances, and carry no ``p`` at all.

Undetermined placements
------------------------

**A roster whose place is not explicitly awarded by a ``p``-bearing match
simply has no placement, and is absent from**
:func:`build_final_placements`'s **output.** No placement is ever inferred
for it.

This is normal, not a data error. Many real leagues bracket out only the
games their format cares about: the ``losers_bracket.json`` fixture in this
repository covers rosters 5-8 but has exactly one ``p``-bearing match
(``p: 5``, awarding places 5 and 6). The two round-1 losers there (rosters 6
and 8) never play a 7th/8th-place game, so the bracket data says nothing
about which of them finished 7th. Guessing -- from seed, regular-season
standings, or points -- would be inventing a result Sleeper never recorded.
Combining bracket placements with regular-season standings to fill those
gaps is deliberately out of scope for this module.

Data-integrity validation
--------------------------

Following :mod:`~fantasy_analyzer.matchups.pairing`'s precedent,
:func:`build_final_placements` raises ``ValueError`` when the bracket data
is self-contradictory in a way that has no correct interpretation: two
different placement-awarding matches crediting the **same roster** with two
**different** placements. Silently picking one would corrupt every
downstream consumer of the placement table.

What is deliberately *not* validated:

- **The same placement value awarded to two different rosters.** This looks
  contradictory but cannot be safely rejected: Sleeper's losers-bracket
  ``p`` numbering is only observed here (in ``losers_bracket.json``) to be
  league-absolute (``p: 5`` in an 8-team league whose winners bracket holds
  4 teams). If some league instead numbers its consolation bracket
  relatively (``p: 1`` meaning "best of the losers bracket"), rejecting
  duplicate placement values would raise on perfectly ordinary data. Callers
  needing certainty should check for duplicate ``placement`` values
  themselves.
- **The advancement chain.** Whether a match's ``t1``/``t2`` actually match
  the ``w``/``l`` of the earlier matches its ``t1_from``/``t2_from``
  reference is not cross-checked; this module normalizes what Sleeper
  reports rather than re-refereeing the bracket.

Rounds are not mapped to weeks
-------------------------------

A bracket match is played in some playoff week, but the raw bracket payload
carries no week number -- only ``r``. Round-to-week mapping is not derivable
from the bracket payload alone (it depends on the league's playoff
configuration, byes, and multi-week finals), so this module does not attempt
it and deliberately does not touch
:class:`~fantasy_analyzer.league.season.SeasonBoundaries`. Every row here is
postseason by construction, so there is no regular-season/playoff filtering
decision to make.

Missing values / edge cases
----------------------------

- **Empty or ``None`` raw bracket** (no losers bracket configured, playoffs
  not started, Sleeper returned ``null``): an empty DataFrame with the
  expected columns, not an error.
- **No placement-awarding matches at all**: :func:`build_final_placements`
  returns an empty DataFrame with the expected columns.
- **An unplayed placement match** (``p`` present but ``w``/``l`` not yet
  recorded) determines nothing and contributes no placement rows.
- Nullable bracket columns are held as ``dtype=object`` so a missing value
  is a real ``None`` rather than being upcast to ``NaN``; consumers may
  still use ``pd.notna`` freely.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from fantasy_analyzer.sleeper.client import SleeperClient

#: Bracket label for Sleeper's winners (championship) bracket.
WINNERS_BRACKET = "winners"

#: Bracket label for Sleeper's losers (consolation) bracket.
LOSERS_BRACKET = "losers"

#: Column order for the DataFrame returned by :func:`build_bracket_df` and
#: :func:`build_playoff_brackets`.
PLAYOFF_BRACKET_COLUMNS = [
    "bracket",
    "round",
    "match_id",
    "roster_1_id",
    "roster_2_id",
    "roster_1_from",
    "roster_2_from",
    "winner_roster_id",
    "loser_roster_id",
    "winner_placement",
    "loser_placement",
]

#: Bracket columns that are ``None`` whenever Sleeper has not recorded the
#: value yet, held as ``dtype=object`` so ``None`` survives DataFrame
#: construction -- see the module docstring's "Missing values" section.
_NULLABLE_BRACKET_COLUMNS = [
    "roster_1_id",
    "roster_2_id",
    "roster_1_from",
    "roster_2_from",
    "winner_roster_id",
    "loser_roster_id",
    "winner_placement",
    "loser_placement",
]

#: Column order for the DataFrame returned by :func:`build_final_placements`.
FINAL_PLACEMENT_COLUMNS = [
    "roster_id",
    "owner",
    "placement",
    "bracket",
    "match_id",
]


def _optional_int(value: object) -> Optional[int]:
    """Coerce a raw Sleeper value to ``int``, passing ``None`` through."""
    return None if value is None else int(value)


def _format_from(from_ref: Optional[dict]) -> Optional[str]:
    """Render a raw ``t1_from``/``t2_from`` reference as a readable string.

    ``{"w": 1}`` -> ``"winner_of_match_1"``; ``{"l": 2}`` ->
    ``"loser_of_match_2"``. Returns ``None`` when there is no reference, or
    when the reference uses a shape this module does not recognize (the
    concrete participants are still available from ``t1``/``t2`` once
    Sleeper fills them in, so an unknown shape is dropped rather than
    raised on).
    """
    if not from_ref:
        return None
    if from_ref.get("w") is not None:
        return f"winner_of_match_{int(from_ref['w'])}"
    if from_ref.get("l") is not None:
        return f"loser_of_match_{int(from_ref['l'])}"
    return None


def build_bracket_df(raw_bracket: Optional[list[dict]], bracket: str) -> pd.DataFrame:
    """Normalize one raw Sleeper bracket payload into a DataFrame.

    Pure normalization core: performs no network access and expects the
    caller to have already fetched the payload (e.g. via
    ``SleeperClient.get_winners_bracket``). See the module docstring for the
    raw-field mapping, the ``winner_placement``/``loser_placement`` (``p``
    and ``p + 1``) convention, and why ``roster_1_from``/``roster_2_from``
    references are not resolved to roster ids.

    Args:
        raw_bracket: Raw Sleeper bracket matches, exactly as returned by
            ``SleeperClient.get_winners_bracket``/``get_losers_bracket``.
            ``None`` or an empty list is treated as "no bracket".
        bracket: Label identifying which bracket this payload came from --
            :data:`WINNERS_BRACKET` or :data:`LOSERS_BRACKET`. Retained
            verbatim in the ``bracket`` column so a combined frame stays
            traceable to its source; treated as an opaque label and not
            validated.

    Returns:
        A DataFrame with columns :data:`PLAYOFF_BRACKET_COLUMNS`, one row
        per bracket match, sorted by ascending ``round`` then ``match_id``.
        ``roster_1_id``/``roster_2_id`` are ``None`` for an unfilled slot,
        ``winner_roster_id``/``loser_roster_id`` are ``None`` for an
        unplayed match, and ``winner_placement``/``loser_placement`` are
        ``None`` for a match that awards no final placement. Returns an
        empty DataFrame with the expected columns if ``raw_bracket`` is
        empty or ``None``.
    """
    if not raw_bracket:
        return pd.DataFrame(columns=PLAYOFF_BRACKET_COLUMNS)

    rows = []
    for match in raw_bracket:
        winner_placement = _optional_int(match.get("p"))
        rows.append(
            {
                "bracket": bracket,
                "round": int(match["r"]),
                "match_id": int(match["m"]),
                "roster_1_id": _optional_int(match.get("t1")),
                "roster_2_id": _optional_int(match.get("t2")),
                "roster_1_from": _format_from(match.get("t1_from")),
                "roster_2_from": _format_from(match.get("t2_from")),
                "winner_roster_id": _optional_int(match.get("w")),
                "loser_roster_id": _optional_int(match.get("l")),
                "winner_placement": winner_placement,
                # Sleeper records only ``p``; the loser of a placement match
                # takes the next place down. See the module docstring.
                "loser_placement": (
                    None if winner_placement is None else winner_placement + 1
                ),
            }
        )

    result = pd.DataFrame(rows, columns=PLAYOFF_BRACKET_COLUMNS)
    for column in _NULLABLE_BRACKET_COLUMNS:
        result[column] = pd.Series([row[column] for row in rows], dtype=object)

    return result.sort_values(by=["round", "match_id"]).reset_index(drop=True)


def build_playoff_brackets(
    winners_raw: Optional[list[dict]], losers_raw: Optional[list[dict]] = None
) -> pd.DataFrame:
    """Normalize both playoff brackets into one combined DataFrame.

    Pure composition core: performs no network access. The ``bracket``
    column distinguishes the two sources; note that ``match_id`` is unique
    only within a bracket, so downstream keys must use ``(bracket,
    match_id)``.

    Args:
        winners_raw: Raw winners-bracket matches, or ``None``/empty.
        losers_raw: Raw losers-bracket matches, or ``None``/empty (a league
            with no consolation bracket).

    Returns:
        A DataFrame with columns :data:`PLAYOFF_BRACKET_COLUMNS`: the
        winners bracket's rows (labelled :data:`WINNERS_BRACKET`) followed
        by the losers bracket's rows (labelled :data:`LOSERS_BRACKET`), each
        block sorted by ascending ``round`` then ``match_id``. Returns an
        empty DataFrame with the expected columns if both inputs are empty.
    """
    winners_df = build_bracket_df(winners_raw, WINNERS_BRACKET)
    losers_df = build_bracket_df(losers_raw, LOSERS_BRACKET)

    if winners_df.empty and losers_df.empty:
        return pd.DataFrame(columns=PLAYOFF_BRACKET_COLUMNS)
    if winners_df.empty:
        return losers_df
    if losers_df.empty:
        return winners_df

    combined = pd.concat([winners_df, losers_df], ignore_index=True)
    return combined[PLAYOFF_BRACKET_COLUMNS]


def build_final_placements(
    bracket_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Derive each roster's final placement from normalized bracket data.

    Every match with a ``winner_placement`` **and** a decided
    ``winner_roster_id``/``loser_roster_id`` awards two places: the winner
    finishes ``winner_placement``, the loser ``loser_placement``
    (``winner_placement + 1``). A roster that no such match credits a place
    to is absent from the output entirely -- see the module docstring's
    "Undetermined placements" section for why no placement is ever inferred.

    Args:
        bracket_df: A :data:`PLAYOFF_BRACKET_COLUMNS`-shaped DataFrame, as
            produced by :func:`build_bracket_df` or
            :func:`build_playoff_brackets`. May cover one bracket or both.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame (see
            :func:`~fantasy_analyzer.league.teams.build_team_mapping`) with
            at least ``["roster_id", "display_name"]``, used to resolve the
            ``owner`` label.

    Returns:
        A DataFrame with columns :data:`FINAL_PLACEMENT_COLUMNS`, one row
        per roster with a determined placement, sorted by ascending
        ``placement`` then ``roster_id``. ``bracket``/``match_id`` trace the
        placement back to the match that awarded it. Returns an empty
        DataFrame with the expected columns if ``bracket_df`` is empty or
        contains no decided placement-awarding match. A roster_id absent
        from ``teams_df`` (or an empty ``teams_df``) resolves to
        ``owner = None`` rather than raising.

    Raises:
        ValueError: If two placement-awarding matches credit the same
            roster with two different placements -- a self-contradictory
            bracket with no correct interpretation. See the module
            docstring's "Data-integrity validation" section for what is
            deliberately not validated.
    """
    if bracket_df.empty:
        return pd.DataFrame(columns=FINAL_PLACEMENT_COLUMNS)

    owner_by_roster = (
        teams_df.set_index("roster_id")["display_name"].to_dict()
        if not teams_df.empty
        else {}
    )

    placements: dict[int, dict] = {}

    for row in bracket_df.itertuples(index=False):
        if pd.isna(row.winner_placement):
            continue
        # An unplayed placement match determines nothing yet.
        if pd.isna(row.winner_roster_id) or pd.isna(row.loser_roster_id):
            continue

        awarded = (
            (int(row.winner_roster_id), int(row.winner_placement)),
            (int(row.loser_roster_id), int(row.loser_placement)),
        )
        for roster_id, placement in awarded:
            existing = placements.get(roster_id)
            if existing is not None:
                if existing["placement"] == placement:
                    # Same place awarded twice by consistent data: keep the
                    # first match as the traceable source rather than
                    # overwriting it.
                    continue
                raise ValueError(
                    f"roster_id {roster_id} is awarded conflicting final "
                    f"placements: {existing['placement']} (bracket "
                    f"{existing['bracket']!r} match {existing['match_id']}) "
                    f"and {placement} (bracket {row.bracket!r} match "
                    f"{int(row.match_id)})"
                )
            placements[roster_id] = {
                "placement": placement,
                "bracket": row.bracket,
                "match_id": int(row.match_id),
            }

    if not placements:
        return pd.DataFrame(columns=FINAL_PLACEMENT_COLUMNS)

    rows = [
        {"roster_id": roster_id, **values} for roster_id, values in placements.items()
    ]
    result = pd.DataFrame(rows)
    result = result.sort_values(by=["placement", "roster_id"]).reset_index(drop=True)
    # ``owner`` is assigned as an explicit ``dtype=object`` Series so an
    # unmapped roster stays ``None`` rather than being upcast to ``NaN`` by
    # pandas' string-dtype inference -- the same contract (and the same
    # reason) as ``season_matchups.py``'s ``owner_1``/``owner_2``.
    result["owner"] = pd.Series(
        [owner_by_roster.get(roster_id) for roster_id in result["roster_id"]],
        dtype=object,
    )
    return result[FINAL_PLACEMENT_COLUMNS]


def load_playoff_brackets(client: SleeperClient, league_id: str) -> pd.DataFrame:
    """Fetch and normalize both of a league's playoff brackets.

    Thin convenience wrapper around :func:`build_playoff_brackets` that
    calls ``SleeperClient.get_winners_bracket`` and
    ``SleeperClient.get_losers_bracket`` once each. Prefer
    :func:`build_playoff_brackets` directly when the raw payloads have
    already been fetched or when testing without network access.

    Args:
        client: A configured ``SleeperClient``.
        league_id: The Sleeper league ID to load brackets for.

    Returns:
        A combined :data:`PLAYOFF_BRACKET_COLUMNS`-shaped DataFrame, winners
        bracket first -- see :func:`build_playoff_brackets`.
    """
    return build_playoff_brackets(
        client.get_winners_bracket(league_id),
        client.get_losers_bracket(league_id),
    )
