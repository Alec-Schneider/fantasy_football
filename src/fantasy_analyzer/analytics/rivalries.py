"""Build per-rivalry margin and scoring statistics (FFA-042).

Extends FFA-040's manager-vs-manager head-to-head work from aggregate
win/loss counts to the *shape* of a rivalry: how lopsided its games tend to
be, which meeting was the nail-biter, which was the blowout in each
direction, and which was the shootout. This module performs no network
access; it operates entirely on an already-built ``season_matchup_df``.

Input: per-game rows, not FFA-040's aggregate
----------------------------------------------

Unlike FFA-041 (the head-to-head matrix), which consumes
:func:`~fantasy_analyzer.analytics.head_to_head.build_head_to_head_records`'s
output because it only *reshapes* counts, this module takes FFA-033's
per-game ``season_matchup_df`` directly -- the same
``(season_matchup_df, teams_df)`` signature shape as
``build_head_to_head_records``.

That difference is forced by the metrics. FFA-040's output is an aggregate:
one row per ordered pair carrying ``meetings``/``wins``/``losses``/``ties``
and points *sums*. "Closest game", "largest win", "largest loss", and
"highest scoring matchup" are all per-game extrema, and an extremum cannot
be recovered from a sum and a count. Even ``avg_margin`` cannot: FFA-040
carries ``total_points`` and ``total_opponent_points``, whose difference is
the *net* points differential over the rivalry (in which a 30-point win and
a 30-point loss cancel to zero), not the average absolute margin. So the
per-game rows are required.

Nothing here recomputes an outcome. ``margin`` and ``winner``/``loser``/
``is_tie`` are read straight off ``season_matchup_df``, where
:mod:`~fantasy_analyzer.matchups.outcomes` already defined them; this module
only selects and averages.

Row shape: ordered, directional pairs
---------------------------------------

As in FFA-040, every meeting between two rosters produces **two** rows --
one from each roster's perspective (``roster_id`` vs.
``opponent_roster_id``) -- rather than a single row per unordered pair.

The same rationale applies, and applies more strongly here: "largest win"
and "largest loss" are inherently perspective-dependent (A's largest win
over B *is* B's largest loss to A), so a single unordered row would have to
either carry both directions' fields or make every caller work out which
side it is looking from. Keeping the directional shape also means this
frame joins 1:1 to FFA-040's on ``(roster_id, opponent_roster_id)``.

Which games qualify
-------------------

For an ordered pair, the candidate games are the ``season_matchup_df`` rows
where the two rosters actually met (``{roster_1_id, roster_2_id} ==
{roster_id, opponent_roster_id}``). Of those:

- **Bye rows** (``roster_2_id`` is ``None``) are excluded before pairing,
  exactly as in FFA-040 -- a bye has no opponent and cannot be part of any
  rivalry.
- **Missing-points rows** (either side's points ``None``/``NaN``, e.g. an
  unloaded week) count toward ``meetings`` (the pair did meet) but are
  excluded from every margin and scoring statistic. Per ``outcomes.py``
  such a row has ``margin``/``point_differential`` ``None`` and no
  winner/loser: it has no defined margin and no defined combined score, so
  it is not a candidate for the average, the extrema, or the highest-scoring
  game. A missing score is **never** treated as ``0.0``. (A row with a
  missing ``margin`` is excluded on the same grounds; ``outcomes.py``
  always sets points and margin together, so this only ever bites a
  hand-built frame.)

Rows surviving both rules are this module's *scored meetings*, counted in
``scored_meetings``. ``scored_meetings <= meetings`` always.

Metric definitions
-------------------

Let ``G`` be the scored meetings of an ordered pair ``(roster_id,
opponent_roster_id)``, each with a non-negative ``margin`` -- taken verbatim
from ``season_matchup_df["margin"]``, which ``outcomes.py`` already defined
as ``abs(points_1 - points_2)`` and ``0.0`` for a tie, and which this module
does not recompute -- and a ``combined_points`` of ``points_1 + points_2``
(the one derived quantity here, since no upstream column carries it).

- **meetings** -- count of qualifying rows, scored or not. Identical in
  definition to FFA-040's ``meetings``, so the two frames agree row-for-row.
- **scored_meetings** -- ``len(G)``; the denominator of ``avg_margin`` and
  the candidate pool for all four game-reference columns. Carried
  explicitly because it is the honest sample size for the margin
  statistics, which ``meetings`` overstates when a week is unloaded.
- **avg_margin** -- ``sum(g.margin for g in G) / len(G)``, the mean
  *absolute* margin of the rivalry's scored games. Ties contribute
  ``0.0`` (a tie is a real, maximally close game, not a missing one).
  ``NaN`` when ``len(G) == 0``. Note this is a magnitude, so it is
  identical for both perspectives of a pair and says nothing about who won;
  ``largest_win``/``largest_loss`` carry the direction.
- **closest_game** -- the ``g in G`` minimizing ``g.margin``. Ties (margin
  ``0.0``) are eligible and always win this field outright.
- **largest_win** -- the ``g in G`` with ``winner == roster_id`` maximizing
  ``g.margin``.
- **largest_loss** -- the ``g in G`` with ``loser == roster_id`` maximizing
  ``g.margin``.
- **highest_scoring_matchup** -- the ``g in G`` maximizing
  ``g.combined_points`` (``points_1 + points_2``). Deliberately the combined
  total, not either side's own score: the ticket asks for the highest
  scoring *matchup*, so a 150-40 blowout (190) outranks a 100-95 game (195)
  only if its total is genuinely larger -- here it does not.

Margin sign convention
-----------------------

``margin`` stays exactly what ``outcomes.py`` made it: a **non-negative
magnitude**, "how much the game was decided by", never signed from
``roster_id``'s perspective. Direction is not lost, because it is encoded
structurally -- a game shows up under ``largest_win`` or under
``largest_loss``, and every :class:`RivalryGame` carries both ``points`` and
``opponent_points``. Signing the margin as well would encode the same
information twice and invite sign-flip bugs at the mirror row.

(``point_differential``, the signed quantity from ``roster_1_id``'s
perspective, is deliberately not surfaced here: its sign is relative to the
source row's arbitrary ``roster_1``/``roster_2`` ordering, not to
``roster_id``, so it would mean the opposite thing in the two mirrored rows
of the same game.)

Value ties within a metric
---------------------------

Two games in a rivalry can share the same margin (or the same combined
score) -- e.g. two identical 10.0-point wins. The extremum is then broken
deterministically by **first occurrence in ``season_matchup_df`` row
order**, which for a pipeline-built frame is chronological (the loader
emits weeks in ascending order and ``build_season_matchup_df`` preserves
input order). The earliest such game is reported. No secondary numeric
tiebreak is applied, and the choice is never arbitrary across runs.

No qualifying game
-------------------

Each of the four game-reference columns is resolved **independently**; a
missing candidate pool empties that field only, and never drops the row or
fails the others:

- A rivalry whose scored games are all ties has ``closest_game`` and
  ``highest_scoring_matchup`` populated, ``avg_margin = 0.0``, and both
  ``largest_win`` and ``largest_loss`` ``None``.
- A rivalry that ``roster_id`` has never won has ``largest_win = None``
  while ``largest_loss`` is populated (and vice versa) -- the common case
  for a one-sided rivalry.
- A rivalry with meetings but **no** scored meetings (every meeting missing
  points) still gets a row -- the pair did meet -- with ``meetings >= 1``,
  ``scored_meetings = 0``, ``avg_margin = NaN``, and all four
  game-reference columns ``None``.
- A pair that never met gets **no row at all**, matching FFA-040's "zero
  meetings -> no row" rule. There is no ``meetings = 0`` row.

Regular season vs. playoffs
------------------------------

This function combines **all** ``season_matchup_df`` rows -- regular season
and playoff alike -- into a single combined rivalry record, exactly as
FFA-040 does. It makes **no** ``is_playoff`` distinction and applies no
phase filter, so a playoff meeting is as eligible to be a rivalry's
``closest_game`` as any regular-season week. Splitting rivalry statistics by
season phase is deferred to FFA-044. Each :class:`RivalryGame` does carry
``is_playoff``, so a caller can at least see which phase a reported extremum
came from without re-joining.

Owner resolution
-----------------

``owner``/``opponent_owner`` are resolved from ``teams_df["display_name"]``
by ``roster_id``, the same lookup-by-dict pattern ``head_to_head.py`` and
``season_matchups.py`` use. A roster absent from ``teams_df`` (or an empty
``teams_df``) resolves to ``None`` rather than raising.

Missing values / edge cases
----------------------------

- **Empty ``season_matchup_df``**: returns an empty DataFrame with
  :data:`RIVALRY_COLUMNS`.
- **All-bye ``season_matchup_df``**: no pairs exist; returns the same empty,
  correctly-shaped frame.
- **Missing points**: excluded from all margin/scoring statistics, never
  treated as ``0.0``, as documented above.
- **Undefined ``avg_margin``**: ``NaN``, keeping the column numeric and
  aggregatable. The four game-reference columns are ``object``-dtype and use
  ``None`` (a :class:`RivalryGame` or nothing), as does ``owner``.
- **Unmapped owner**: ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_rivalry_records`.
RIVALRY_COLUMNS = [
    "roster_id",
    "opponent_roster_id",
    "owner",
    "opponent_owner",
    "meetings",
    "scored_meetings",
    "avg_margin",
    "closest_game",
    "largest_win",
    "largest_loss",
    "highest_scoring_matchup",
]


@dataclass(frozen=True)
class RivalryGame:
    """One specific meeting, referenced by a rivalry's margin/scoring extrema.

    A frozen dataclass rather than a bare ``float`` so that "closest game"
    answers *which* game as well as *by how much* -- a bare margin loses the
    week, the season, and the two scores, which is most of what makes the
    answer readable. The same shape is reused for all four game-reference
    columns (``closest_game``, ``largest_win``, ``largest_loss``,
    ``highest_scoring_matchup``) rather than defining four ad hoc shapes, so
    a caller can render any of them with one code path; each column just
    differs in which game it selected and by which key.

    Every field is copied verbatim from the source ``season_matchup_df``
    row, re-expressed from ``roster_id``'s perspective (``points`` is always
    ``roster_id``'s own score, whether that roster was ``roster_1`` or
    ``roster_2`` in the source row). Only scored meetings -- both sides'
    points present -- are ever represented, so ``points``,
    ``opponent_points``, ``margin``, and ``combined_points`` are always
    real floats, never ``None``.

    Attributes:
        season: Season label from the source row, or ``None`` if unset.
        week: Week number of the meeting.
        is_playoff: Whether the meeting fell in a playoff week. Carried so a
            caller can tell a playoff extremum from a regular-season one;
            this module itself does not filter on it (see the module
            docstring's "Regular season vs. playoffs").
        matchup_id: The raw Sleeper ``matchup_id``, or ``None`` if unset;
            together with ``season``/``week`` this identifies the game.
        roster_id: The perspective roster -- the owner of the rivalry row
            this game is reported on.
        opponent_roster_id: The other roster in the meeting.
        points: ``roster_id``'s points in this meeting.
        opponent_points: ``opponent_roster_id``'s points in this meeting.
        margin: ``abs(points - opponent_points)``, non-negative, ``0.0`` for
            a tie. Never signed -- see the module docstring's "Margin sign
            convention".
        combined_points: ``points + opponent_points``, the matchup's total
            scoring. Identical for both mirrored perspectives.
    """

    season: Optional[str]
    week: int
    is_playoff: bool
    matchup_id: Optional[int]
    roster_id: int
    opponent_roster_id: int
    points: float
    opponent_points: float
    margin: float
    combined_points: float


def _pair_bucket(buckets: dict, roster_id: int, opponent_roster_id: int) -> dict:
    """Return (creating if absent) the running state for one ordered pair."""
    key = (roster_id, opponent_roster_id)
    if key not in buckets:
        buckets[key] = {
            "meetings": 0,
            # Scored meetings, in source-row order, so that extremum ties
            # resolve to the earliest game -- see the module docstring's
            # "Value ties within a metric".
            "games": [],
            "won_games": [],
            "lost_games": [],
        }
    return buckets[key]


def build_rivalry_records(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build per-rivalry margin and scoring statistics for each ordered pair.

    Scans every non-bye row of ``season_matchup_df`` -- regular season and
    playoff alike -- and summarizes each ordered ``(roster_id,
    opponent_roster_id)`` rivalry by its average margin plus its closest,
    most lopsided (each direction), and highest scoring meeting. See the
    module docstring for the exact metric definitions, the
    non-negative-margin convention, the bye/missing-points exclusions, the
    deterministic tiebreak for equal extrema, and why playoff rows are not
    filtered out.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used to resolve
            ``owner``/``opponent_owner`` labels.

    Returns:
        A DataFrame with columns :data:`RIVALRY_COLUMNS`, one row per
        ordered pair of rosters that met at least once, sorted by ascending
        ``roster_id`` then ascending ``opponent_roster_id``. The
        ``closest_game``/``largest_win``/``largest_loss``/
        ``highest_scoring_matchup`` columns hold :class:`RivalryGame`
        instances, or ``None`` where that field has no qualifying game;
        ``avg_margin`` is ``NaN`` when the pair has no scored meeting.
        Returns an empty DataFrame with the expected columns if
        ``season_matchup_df`` is empty or contains only bye rows. A
        roster_id absent from ``teams_df`` (or an empty ``teams_df``)
        resolves to ``owner``/``opponent_owner = None`` rather than raising.
    """
    if season_matchup_df.empty:
        return pd.DataFrame(columns=RIVALRY_COLUMNS)

    owner_by_roster = (
        teams_df.set_index("roster_id")["display_name"].to_dict()
        if not teams_df.empty
        else {}
    )

    buckets: dict = {}

    for row in season_matchup_df.itertuples(index=False):
        # Bye rows have no opponent and cannot belong to a rivalry -- see
        # the module docstring's "Which games qualify".
        if pd.isna(row.roster_2_id):
            continue

        roster_1_id = int(row.roster_1_id)
        roster_2_id = int(row.roster_2_id)
        winner = int(row.winner) if pd.notna(row.winner) else None
        loser = int(row.loser) if pd.notna(row.loser) else None

        # Both perspectives of the same meeting, mirrored -- see "Row
        # shape". Each side sees its own score as ``points``.
        perspectives = (
            (roster_1_id, roster_2_id, row.points_1, row.points_2),
            (roster_2_id, roster_1_id, row.points_2, row.points_1),
        )
        for own_id, opp_id, own_points, opp_points in perspectives:
            bucket = _pair_bucket(buckets, own_id, opp_id)
            bucket["meetings"] += 1

            # A meeting with either score missing has no defined margin and
            # no defined combined score (outcomes.py leaves ``margin``
            # ``None``), so it counts as a meeting but is not a candidate
            # for any statistic below. Missing is never read as 0.0. The
            # ``margin`` check is redundant for a pipeline-built frame --
            # outcomes.py sets points and margin together -- but keeps a
            # hand-built or partially-populated frame from producing a
            # ``NaN`` margin here.
            if pd.isna(own_points) or pd.isna(opp_points) or pd.isna(row.margin):
                continue

            own_points = float(own_points)
            opp_points = float(opp_points)
            game = RivalryGame(
                season=row.season if pd.notna(row.season) else None,
                week=int(row.week),
                is_playoff=bool(row.is_playoff),
                matchup_id=int(row.matchup_id) if pd.notna(row.matchup_id) else None,
                roster_id=own_id,
                opponent_roster_id=opp_id,
                points=own_points,
                opponent_points=opp_points,
                # Read straight off the source row rather than recomputed
                # from the two scores, so ``outcomes.py`` stays the single
                # definition of what a margin is.
                margin=float(row.margin),
                combined_points=own_points + opp_points,
            )
            bucket["games"].append(game)

            # Bucket by outcome using the already-derived winner/loser
            # columns rather than re-comparing scores, so this module stays
            # consistent with outcomes.py's definitions (and with FFA-040,
            # which reads the same columns). A tie lands in neither bucket.
            if winner is not None and winner == own_id:
                bucket["won_games"].append(game)
            elif loser is not None and loser == own_id:
                bucket["lost_games"].append(game)

    # A non-empty frame made entirely of bye rows yields no pairs; return an
    # empty, correctly-shaped frame rather than a columnless one.
    if not buckets:
        return pd.DataFrame(columns=RIVALRY_COLUMNS)

    rows = []
    for (roster_id, opponent_roster_id), state in buckets.items():
        games: list[RivalryGame] = state["games"]
        won_games: list[RivalryGame] = state["won_games"]
        lost_games: list[RivalryGame] = state["lost_games"]

        # ``min``/``max`` return the *first* extremal element, which is
        # exactly the documented "earliest game wins a tie" rule given that
        # ``games`` is in source-row order.
        rows.append(
            {
                "roster_id": roster_id,
                "opponent_roster_id": opponent_roster_id,
                "meetings": state["meetings"],
                "scored_meetings": len(games),
                "avg_margin": (
                    sum(game.margin for game in games) / len(games)
                    if games
                    else float("nan")
                ),
                "closest_game": (
                    min(games, key=lambda game: game.margin) if games else None
                ),
                "largest_win": (
                    max(won_games, key=lambda game: game.margin) if won_games else None
                ),
                "largest_loss": (
                    max(lost_games, key=lambda game: game.margin)
                    if lost_games
                    else None
                ),
                "highest_scoring_matchup": (
                    max(games, key=lambda game: game.combined_points) if games else None
                ),
            }
        )

    result = pd.DataFrame(rows)
    result = result.sort_values(by=["roster_id", "opponent_roster_id"]).reset_index(
        drop=True
    )

    # ``owner``/``opponent_owner`` are assigned as explicit ``dtype=object``
    # Series for the same reason ``head_to_head.py`` does it: pandas' string
    # dtype inference would otherwise turn an unmapped ``None`` into ``NaN``
    # and break the documented "unmapped owner -> None" contract.
    result["owner"] = pd.Series(
        [owner_by_roster.get(roster_id) for roster_id in result["roster_id"]],
        dtype=object,
    )
    result["opponent_owner"] = pd.Series(
        [
            owner_by_roster.get(opponent_roster_id)
            for opponent_roster_id in result["opponent_roster_id"]
        ],
        dtype=object,
    )
    return result[RIVALRY_COLUMNS]
