"""Matchup player contribution analysis (FFA-069).

Joins FFA-033's canonical matchup dataset
(:func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`'s
``season_matchup_df``) with FFA-064's canonical player-week fact table
(:func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`'s
``player_week_df``) on ``(season, week, roster_id)`` and answers, for every
regular-season or playoff matchup a roster actually played, the four
questions AGENTS.md's ticket text lists: which players drove the win or
loss, how each position group compared to the opponent's, how much each
player contributed to the matchup margin, and who the best/worst starters
were.

It lives in ``players/`` rather than ``analytics/`` for the same reason
``player_analytics.py`` (FFA-071) gives: every builder it composes -- the
season matchup DataFrame and the player-week fact table -- already lives in
``matchups/``/``players/``, and AGENTS.md assigns "which players drove
specific matchup wins and losses" to the ``players`` package's Epic 7 scope
(alongside player value, positional strength, and roster efficiency), not to
``analytics/``'s team-standings-shaped scope.

This module performs no network access; it operates entirely on two
already-built DataFrames.

Row universe: started players in paired (non-bye) matchups, only
----------------------------------------------------------------------

Every builder here is scoped to the same row universe, for the same reason:

- **Bye rows are excluded entirely.** A bye (``roster_2_id`` is ``None``,
  per :mod:`~fantasy_analyzer.matchups.pairing`) has no opponent, so there is
  nothing to compare a position group or a player's score against -- the
  identical exclusion :mod:`~fantasy_analyzer.analytics.head_to_head`
  documents for the same structural reason.
- **Only ``started`` players are read from ``player_week_df``.** A benched
  player's points never entered that roster's recorded score for the week
  and could not have driven the matchup outcome (``lineup_efficiency.py``'s
  ``bench_points`` is explicitly "informational only" for the identical
  reason); this module's entire purpose is explaining a recorded matchup
  result, so bench production is out of scope here by design, not an
  oversight. A caller who wants to ask "would a bench player have changed
  the outcome" wants FFA-067's optimal-lineup machinery instead.
- **An incomplete matchup** (``roster_2_id`` present, but either side's
  ``points`` is missing -- see
  :mod:`~fantasy_analyzer.matchups.outcomes`'s "Incomplete matchups"
  section) is *not* excluded like a bye: it still has a real opponent, so
  position groups and player contributions are still reported. What is
  undefined is the *outcome*: ``result`` is ``None`` (not one of
  ``"win"``/``"loss"``/``"tie"``), and ``margin``/``share_of_team_points``
  are ``NaN`` wherever the missing points value would be needed -- see
  "Missing values / edge cases" below.
- **A roster-week with no ``started`` rows at all in ``player_week_df``**
  (the roster-week was never loaded into the fact table, or every player
  happened to be marked benched) produces no rows in either output table for
  that roster-week. This is indistinguishable, from the table alone, from
  "the matchup genuinely had no started players that week" -- a documented
  gap, not a silent wrong answer; see :func:`reconcile_matchup_points` for
  the tool this module provides to detect exactly this gap.

``team_points``/``opponent_points``/``margin``/``result``: read from
``season_matchup_df``, not recomputed from ``player_week_df``
----------------------------------------------------------------------

A roster's recorded matchup score (``points_1``/``points_2``), and
therefore ``margin`` and ``result``, are read directly from
``season_matchup_df`` -- the same values that already determined the
league's actual standings (FFA-034 reconciles those against Sleeper's own
cumulative record). This module does **not** recompute a roster's score by
summing ``player_week_df``'s started ``fantasy_points`` and treat that sum
as authoritative, because the two are independently derived (Sleeper's own
recorded score vs. this codebase's own scoring engine re-applied to
provider stats) and are expected to usually, but not always, agree exactly
-- see "Reconciliation" below for the documented check and its causes of
disagreement. Every per-player contribution and share in this module's
output is still computed from ``player_week_df``'s ``fantasy_points``; only
the roster-level ``team_points``/``opponent_points``/``margin``/``result``
denominators come from ``season_matchup_df``.

``margin`` here is **signed from the reporting roster's own perspective**
(``team_points - opponent_points``; positive means this roster outscored its
opponent that week) -- deliberately different from
``season_matchup_df.margin``, which is the unsigned magnitude of the
victory. This module needs a signed, per-roster value to state "how much did
this player contribute to *this roster's* margin," and reusing the field
name ``margin`` for the signed version (rather than the unsigned one) is
called out explicitly here to avoid confusion with the source column of the
same name.

Player matchup contribution (:func:`build_matchup_player_contributions`)
--------------------------------------------------------------------------

One row per ``(season, week, roster_id, sleeper_player_id)`` for every
started player in a paired matchup.

- **Contribution to margin.** Because ``margin = team_points -
  opponent_points = sum(own starters' points) - sum(opponent starters'
  points)``, and the choices at different positions/players never interact,
  a started player's own ``fantasy_points`` *is* his exact, linear
  contribution to his own roster's margin: increasing his score by ``x``
  increases the roster's margin by exactly ``x``, holding every other
  player fixed. This is the ticket's "player contribution to margin," made
  concrete without inventing a new formula -- ``fantasy_points`` already
  *is* that number. No separate "margin_contribution" column duplicates it.
- **share_of_team_points** -- ``fantasy_points / team_points``, the
  normalized companion view the ticket text also suggests: what fraction of
  the roster's *recorded* matchup score this player accounted for. ``NaN``
  when ``team_points`` is ``NaN`` or ``<= 0`` (see "Missing values" below).
  Because ``team_points`` comes from ``season_matchup_df`` while
  ``fantasy_points`` comes from ``player_week_df``, this share is not
  guaranteed to be exactly consistent across a roster-week's players (their
  shares need not sum to exactly ``1.0``) whenever the two sources disagree
  -- see "Reconciliation" below.
- **contribution_rank** -- the "best/worst starters" ranking the ticket
  asks for: standard competition ("1224") ranking within each ``(season,
  week, roster_id)`` group, by descending ``fantasy_points`` (``NaN``
  treated as ``0.0`` -- see "Missing values"), ties broken by ascending
  ``sleeper_player_id`` for a deterministic order. ``contribution_rank == 1``
  is that roster's best starter that week; the largest rank in the group is
  the worst. A caller answering "which players drove a win or loss" filters
  this frame to ``contribution_rank == 1`` and reads ``result`` alongside it
  -- the highest scorer on the winning side is this module's answer to "who
  drove the win," and the highest scorer on the *losing* side is "who
  outperformed the rest of a loss." This module does not add a separate
  boolean flag for that filter (e.g. ``is_top_contributor``); the existing
  ``contribution_rank``/``result`` pair already answers it directly, the
  same "a rank column is enough, no derived boolean" precedent
  ``player_value.py``'s ``value_rank`` and ``position_strength.py``'s
  ``positional_rank`` set.

  A season-average or "boom relative to usual" baseline (the ticket text's
  alternative suggestion) is deliberately not used here: FFA-069's stated
  dependencies are FFA-033 and FFA-064 only, and a season-average baseline
  would require FFA-065's ``performance_df`` as a third input this module
  does not otherwise need. Ranking within the matchup itself (this roster's
  own starters, that week) answers "who drove this result" without pulling
  in a whole season of context a reader may not have computed yet. A caller
  who wants the season-relative reading can join this frame's
  ``sleeper_player_id``/``season`` against
  :func:`~fantasy_analyzer.players.performance.build_player_performance_metrics`
  or :func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`
  directly; this module does not duplicate either.

Positional matchup advantage (:func:`build_positional_matchup_advantage`)
-----------------------------------------------------------------------------

One row per ``(season, week, roster_id, position)``, comparing a roster's
started production at a position group against its opponent's, that week.

- ``position`` is read directly from each started player's own
  ``player_week_df.position`` value -- **not** the Sleeper roster slot they
  were started in. FFA-064's fact table exposes no more granular
  slot-vs-player-position distinction than that (see that module's own
  schema), so a FLEX-started wide receiver is grouped under ``WR``, not
  under a separate ``FLEX`` bucket, the identical convention
  ``position_strength.py`` documents for the same underlying data. This is
  a deliberate scope limit, not an oversight: attributing a FLEX start to
  "the position it effectively displaced" would require a counterfactual
  the fact table cannot answer, and is explicitly out of scope for this
  ticket.
- **Row set per matchup**: the *union* of positions started by either side
  that week (a team that started nobody at ``TE`` still gets a ``TE`` row
  if its opponent did, with ``own_points = 0.0`` and ``own_starters = 0``),
  so the two teams' rows are always directly comparable position by
  position. This is a deliberate divergence from
  ``position_strength.py``'s "a team-position with zero started weeks gets
  no row at all" convention: that module is describing one team's own
  season-long production in isolation (where an always-absent position
  should not appear at all), while this module is explicitly a head-to-head
  comparison for one week, where "the opponent started two running backs
  and I started none" is exactly the signal a positional-advantage table
  exists to surface, not information to hide by omitting the row.
- **own_points** / **opponent_points** -- the sum of started
  ``fantasy_points`` at that position, for this roster and its opponent
  respectively, that week (``0.0`` if the side started nobody there).
  **own_starters** / **opponent_starters** -- how many started players each
  side had at the position, context for whether an advantage came from more
  bodies or better per-player production.
- **positional_advantage** -- ``own_points - opponent_points``: positive
  means this roster out-produced its opponent at that position that week.
  Summing ``positional_advantage`` across every position row for one
  ``(season, week, roster_id)`` reproduces that roster-week's signed
  ``margin`` exactly (both are partitions of the same
  ``sum(own started points) - sum(opponent started points)``, split by
  player identity in one table and by position in the other) -- subject to
  the same "started players with an unresolved position are excluded from
  every position row" caveat as any partition, see "Missing values" below.

Reconciliation (:func:`reconcile_matchup_points`)
-----------------------------------------------------

FFA-069's spec calls out an internal consistency check worth documenting
explicitly, in the spirit of
:mod:`~fantasy_analyzer.matchups.reconciliation` (FFA-034): a roster's
recorded matchup score (``season_matchup_df.points_1``/``points_2``) should
equal the sum of that roster-week's started players' ``fantasy_points`` in
``player_week_df``. :func:`reconcile_matchup_points` computes both sides,
per ``(season, week, roster_id)``, and flags any roster-week where they
disagree by more than :data:`MATCHUP_POINTS_TOLERANCE`.

Unlike FFA-034's reconciliation (two views of Sleeper's own cumulative
counters, expected to match up to floating-point noise), this comparison is
between **two independently-computed scores**: Sleeper's own recorded
matchup total, versus this codebase's own scoring engine (FFA-063)
re-applied to whatever provider stats FFA-064's fact table could resolve
for that roster-week. Disagreement here is a real, expected possibility,
not just floating-point noise, for reasons the tolerance cannot absorb:

- The league's scoring settings include a category
  :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points` could
  not map to a raw stat column (see that function's
  ``unsupported_scoring_keys``) -- this module cannot see that diagnostic
  itself and does not re-surface it; a caller who sees a reconciliation
  mismatch should check ``unsupported_scoring_keys`` from the
  ``player_week_df``-building step first.
- The provider had no stats for one of the roster's started players that
  week (FFA-064's ``player_week_df`` still gives that player a row with
  every stat ``NaN`` and ``fantasy_points`` computed as ``0.0`` from those
  -- see ``player_week.py``'s row-universe section -- which understates
  ``started_points`` relative to Sleeper's own recorded score whenever that
  player actually scored fantasy points Sleeper counted but the provider
  never captured).
- ``player_week_df`` simply was not built for that roster-week at all (see
  "Row universe" above): ``started_points`` is ``NaN``, not ``0.0``, for
  that case -- see "Missing values" below.

A caller should treat a mismatch as a data-quality signal to investigate
(which of the three causes above applies), not as evidence this module's
own arithmetic is wrong: :func:`build_matchup_player_contributions` and
:func:`build_positional_matchup_advantage` always use ``player_week_df``'s
own ``fantasy_points`` for the per-player/per-position breakdown and
``season_matchup_df``'s own recorded score for ``team_points``/``margin``/
``result`` -- exactly the two independent sources this function compares --
so a caller who wants the *breakdown* to sum back to the *recorded* score
exactly should check :func:`reconcile_matchup_points` first, rather than
assume it always holds.

Season type mismatch between the two input frames
------------------------------------------------------

``season_matchup_df.season`` and ``player_week_df.season`` are documented,
in their own respective modules, to carry ``season`` differently:
``matchups.season_matchups`` treats it as an opaque label carried through
unchanged from whatever Sleeper returned (in practice always ``str`` for a
live league, since Sleeper's API returns league season as a JSON string),
while ``players.player_week`` always normalizes it to ``int``. Every
roster-week join in this module keys on ``(season, week, roster_id)``
across both frames, so joining on the raw values would silently match
nothing whenever the two frames disagree on type -- exactly the case for
any real (non-hand-built) pair of inputs. Every internal join key in this
module therefore normalizes its season component with ``str(...)`` before
comparing; the ``season`` values in this module's *output* columns are
unaffected (still whatever ``season_matchup_df`` carried, cast to ``int``
at the end, per each builder's own column-dtype handling).

Missing values / edge cases
------------------------------

- **Empty ``season_matchup_df`` or empty ``player_week_df``**: all three
  builders return an empty DataFrame with their documented columns.
- **``NaN``/missing ``fantasy_points`` on a started row**: treated as
  ``0.0`` for every purpose (the player's own ``fantasy_points`` value in
  the output, ``share_of_team_points``'s numerator, ``contribution_rank``,
  and position sums) -- the identical convention
  ``lineup_efficiency.py`` documents for the same column. FFA-064 never
  emits one; a hand-built input should not corrupt a sum with a ``NaN``.
- **Missing ``season``/``week``/``roster_id`` on a ``player_week_df`` row**:
  the row cannot be assigned to a roster-week and is skipped entirely,
  mirroring ``lineup_efficiency.py``'s identical handling.
- **Missing ``position`` on a started row**: the player still gets a row in
  :func:`build_matchup_player_contributions` (his contribution to margin
  does not depend on a resolved position), but is excluded from
  :func:`build_positional_matchup_advantage` entirely -- a row cannot be
  assigned to a position group, mirroring ``position_strength.py``'s
  identical handling. This means the positional-advantage partition can
  legitimately sum to slightly less than the roster-week's total ``margin``
  when any started player's position is unresolved -- a documented gap, not
  a bug.
- **Duplicate ``sleeper_player_id`` within one roster-week** (should not
  occur in real data; ``player_week.py`` preserves duplicates defensively):
  this module keeps the first row per player id and ignores the rest,
  mirroring ``lineup_efficiency.py``'s identical deduplication, so a player
  is never double-counted in a team or position total.
- **``team_points``/``opponent_points`` missing** (an incomplete matchup,
  per ``outcomes.py``): ``share_of_team_points`` is ``NaN`` (undefined
  numerator-relative-to-unknown-denominator), ``margin`` is ``NaN``, and
  ``result`` is ``None`` -- see "Row universe" above. ``fantasy_points``
  itself is unaffected (it comes from ``player_week_df``, not the matchup
  row) and is still reported.
- **``team_points <= 0``** (a legitimately negative or zero recorded score
  -- rare, but not impossible with punitive scoring categories):
  ``share_of_team_points`` is ``NaN``, the identical "where appropriate"
  guard ``position_strength.py``'s ``share_of_team_points`` and
  ``consistency.py``'s ``cv`` apply to their own denominators.
- **Ties** (``season_matchup_df.is_tie == True``): ``result = "tie"`` for
  both rosters, ``margin`` can still be nonzero from *this* module's
  per-roster perspective only if ``team_points != opponent_points`` --
  which cannot happen for a true tie (``points_1 == points_2`` is exactly
  what ``is_tie`` means), so a tied roster-week's ``margin`` is always
  ``0.0`` here.
- **A roster-week absent from ``player_week_df``'s started rows**: produces
  no rows in either builder for that roster-week (see "Row universe"
  above); :func:`reconcile_matchup_points` reports ``started_points =
  NaN``, ``points_match = False`` for it, rather than assuming zero.

Regular season vs. playoffs: this module is phase-agnostic
------------------------------------------------------------

All three functions apply **no** ``is_playoff`` filter of their own --
``is_playoff`` is carried straight through from ``season_matchup_df`` onto
every emitted row, the same convention
:mod:`~fantasy_analyzer.analytics.power_rankings` documents ("functions
apply no ``is_playoff`` filter; callers filter ``season_matchup_df`` before
calling"). A caller wanting a regular-season-only or playoffs-only view
filters ``season_matchup_df`` (and, for consistency, ``player_week_df`` on
the same ``week`` boundary) before calling any function here.

Column dtypes
--------------

In :data:`PLAYER_CONTRIBUTION_COLUMNS`: ``season``/``week``/``roster_id``/
``opponent_roster_id``/``matchup_id``/``contribution_rank`` are ``int64``;
``is_playoff`` is ``bool``; ``fantasy_team``/``opponent_fantasy_team``/
``sleeper_player_id``/``player_name``/``position``/``result`` are
``object`` (``result`` may legitimately be ``None``); every points/share
column is ``float64`` with undefined values as ``NaN``. In
:data:`POSITIONAL_ADVANTAGE_COLUMNS`: the same identity columns (minus
``sleeper_player_id``/``player_name``/``result``), plus ``position`` as
``object``, ``own_starters``/``opponent_starters`` as ``int64``, and
``own_points``/``opponent_points``/``positional_advantage`` as ``float64``.
In :data:`RECONCILE_COLUMNS`: ``season``/``week``/``roster_id`` are
``int64``, ``fantasy_team`` is ``object``, ``matchup_points``/
``started_points``/``points_diff`` are ``float64`` (``NaN`` where
undefined), and ``points_match`` is ``bool``. Test undefined values with
``pd.isna``, not ``is None`` -- except label columns, which may be ``None``.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

#: Column order for the DataFrame returned by
#: :func:`build_matchup_player_contributions`.
PLAYER_CONTRIBUTION_COLUMNS = [
    "season",
    "week",
    "is_playoff",
    "matchup_id",
    "roster_id",
    "fantasy_team",
    "opponent_roster_id",
    "opponent_fantasy_team",
    "sleeper_player_id",
    "player_name",
    "position",
    "fantasy_points",
    "team_points",
    "opponent_points",
    "share_of_team_points",
    "margin",
    "result",
    "contribution_rank",
]

#: Column order for the DataFrame returned by
#: :func:`build_positional_matchup_advantage`.
POSITIONAL_ADVANTAGE_COLUMNS = [
    "season",
    "week",
    "is_playoff",
    "matchup_id",
    "roster_id",
    "fantasy_team",
    "opponent_roster_id",
    "opponent_fantasy_team",
    "position",
    "own_points",
    "own_starters",
    "opponent_points",
    "opponent_starters",
    "positional_advantage",
]

#: Column order for the DataFrame returned by
#: :func:`reconcile_matchup_points`.
RECONCILE_COLUMNS = [
    "season",
    "week",
    "roster_id",
    "fantasy_team",
    "matchup_points",
    "started_points",
    "points_diff",
    "points_match",
]

#: Absolute float tolerance for :func:`reconcile_matchup_points`'s
#: ``points_match`` comparison. Reuses
#: :mod:`~fantasy_analyzer.matchups.reconciliation`'s
#: ``POINTS_TOLERANCE`` value (``1e-6``) for the identical
#: floating-point-summation-order reasoning -- see that module's
#: "Tolerances" section -- under this module's own name, since a genuine
#: scoring-engine or missing-data discrepancy (see this module's
#: "Reconciliation" section) is many orders of magnitude larger than this.
MATCHUP_POINTS_TOLERANCE = 1e-6

_CONTRIBUTION_FLOAT_COLUMNS = [
    "fantasy_points",
    "team_points",
    "opponent_points",
    "share_of_team_points",
    "margin",
]

_ADVANTAGE_FLOAT_COLUMNS = ["own_points", "opponent_points", "positional_advantage"]

_RECONCILE_FLOAT_COLUMNS = ["matchup_points", "started_points", "points_diff"]


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _roster_week_context(season_matchup_df: pd.DataFrame) -> dict[tuple, dict]:
    """One context dict per ``(season, week, roster_id)`` from paired matchups.

    Expands each non-bye row of ``season_matchup_df`` into its two
    per-roster perspectives -- the same directional-expansion pattern
    :mod:`~fantasy_analyzer.analytics.head_to_head` uses -- carrying
    everything both builders below need: identity, the opponent's identity,
    the roster's own recorded score/opponent score, the signed ``margin``,
    and the per-roster ``result``. Bye rows (``roster_2_id`` is ``None``)
    are skipped entirely -- see the module docstring's "Row universe"
    section.
    """
    context: dict[tuple, dict] = {}
    for row in season_matchup_df.itertuples(index=False):
        if pd.isna(row.roster_2_id):
            continue

        season = row.season
        week = row.week
        is_playoff = bool(row.is_playoff) if pd.notna(row.is_playoff) else False
        matchup_id = row.matchup_id
        roster_1_id = int(row.roster_1_id)
        roster_2_id = int(row.roster_2_id)
        owner_1 = getattr(row, "owner_1", None)
        owner_2 = getattr(row, "owner_2", None)
        winner = int(row.winner) if pd.notna(row.winner) else None
        loser = int(row.loser) if pd.notna(row.loser) else None
        is_tie = bool(row.is_tie) if pd.notna(row.is_tie) else False
        points_1 = row.points_1 if pd.notna(row.points_1) else None
        points_2 = row.points_2 if pd.notna(row.points_2) else None

        perspectives = (
            (roster_1_id, owner_1, roster_2_id, owner_2, points_1, points_2),
            (roster_2_id, owner_2, roster_1_id, owner_1, points_2, points_1),
        )
        for (
            own_id,
            own_owner,
            opp_id,
            opp_owner,
            own_points,
            opp_points,
        ) in perspectives:
            if winner is not None and winner == own_id:
                result = "win"
            elif loser is not None and loser == own_id:
                result = "loss"
            elif is_tie:
                result = "tie"
            else:
                result = None

            margin = (
                own_points - opp_points
                if own_points is not None and opp_points is not None
                else None
            )

            # season is normalized to str for the key only (not the stored
            # value) so a roster-week matches regardless of whether the two
            # input frames' season columns are the same type -- see the
            # module docstring's "Season type mismatch" section.
            context[(str(season), week, own_id)] = {
                "season": season,
                "week": week,
                "is_playoff": is_playoff,
                "matchup_id": matchup_id,
                "roster_id": own_id,
                "fantasy_team": own_owner,
                "opponent_roster_id": opp_id,
                "opponent_fantasy_team": opp_owner,
                "team_points": own_points,
                "opponent_points": opp_points,
                "margin": margin,
                "result": result,
            }
    return context


def _started_rows_by_roster_week(
    player_week_df: pd.DataFrame,
) -> dict[tuple, list[dict]]:
    """Deduplicated started-player rows, grouped by ``(season, week, roster_id)``.

    Skips rows missing ``season``/``week``/``roster_id`` (ungroupable) and
    rows that are not ``started``. Keeps the first row per
    ``sleeper_player_id`` within a roster-week, mirroring
    ``lineup_efficiency.py``'s identical deduplication. ``fantasy_points`` is
    coerced to ``0.0`` when missing -- see the module docstring's "Missing
    values" section.
    """
    grouped: dict[tuple, list[dict]] = {}
    for row in player_week_df.itertuples(index=False):
        if (
            pd.isna(getattr(row, "season", None))
            or pd.isna(getattr(row, "week", None))
            or pd.isna(getattr(row, "roster_id", None))
        ):
            continue
        if not bool(getattr(row, "started", False)):
            continue

        # str(...) for the same reason as _roster_week_context's key.
        key = (str(row.season), row.week, int(row.roster_id))
        players = grouped.setdefault(key, [])

        player_id = getattr(row, "sleeper_player_id", None)
        if pd.notna(player_id) and any(
            p["sleeper_player_id"] == player_id for p in players
        ):
            continue

        points = getattr(row, "fantasy_points", None)
        players.append(
            {
                "sleeper_player_id": player_id,
                "player_name": getattr(row, "player_name", None),
                "position": getattr(row, "position", None),
                "fantasy_points": float(points) if pd.notna(points) else 0.0,
            }
        )
    return grouped


def _assign_contribution_ranks(players: list[dict]) -> None:
    """Assign ``contribution_rank`` in place, within one roster-week's players.

    Standard competition ("1224") ranking by descending ``fantasy_points``,
    ties broken by ascending ``sleeper_player_id`` for a deterministic
    order -- see the module docstring's "contribution_rank" section.
    """
    ordered = sorted(
        players,
        key=lambda p: (-p["fantasy_points"], str(p["sleeper_player_id"])),
    )
    current_rank = 0
    previous_points: Optional[float] = None
    for position, player in enumerate(ordered, start=1):
        if player["fantasy_points"] != previous_points:
            current_rank = position
            previous_points = player["fantasy_points"]
        player["contribution_rank"] = current_rank


def build_matchup_player_contributions(
    season_matchup_df: pd.DataFrame, player_week_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row per started player per roster-week of a paired matchup (FFA-069).

    For every roster that played a non-bye matchup that week, and had at
    least one started row in ``player_week_df``, computes each started
    player's own contribution to that roster's margin (his
    ``fantasy_points``, exact by linearity), his share of the roster's
    recorded score, the roster's matchup context (opponent, recorded
    score, signed margin, result), and his rank among that roster's
    starters that week. See the module docstring's "Player matchup
    contribution" section for the full metric definitions and rationale.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
            This function is phase-agnostic (see the module docstring);
            filter on ``is_playoff`` before calling for a phase-specific
            view.
        player_week_df: A
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            DataFrame, as produced by
            :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`.
            Only ``season``, ``week``, ``roster_id``, ``sleeper_player_id``,
            ``player_name``, ``position``, ``started``, and
            ``fantasy_points`` are read.

    Returns:
        A DataFrame with columns :data:`PLAYER_CONTRIBUTION_COLUMNS`, one
        row per started player in a paired roster-week, sorted by ascending
        ``season``, then ``week``, then ``roster_id``, then
        ``contribution_rank``. Returns an empty DataFrame with the expected
        columns if either input is empty or no roster-week qualifies.
    """
    if season_matchup_df.empty or player_week_df.empty:
        return _empty_frame(PLAYER_CONTRIBUTION_COLUMNS)

    context = _roster_week_context(season_matchup_df)
    started = _started_rows_by_roster_week(player_week_df)

    rows: list[dict] = []
    for key, ctx in context.items():
        players = started.get(key)
        if not players:
            continue

        players = [dict(p) for p in players]
        _assign_contribution_ranks(players)

        team_points = ctx["team_points"]
        for player in players:
            share = (
                player["fantasy_points"] / team_points
                if team_points is not None and team_points > 0
                else None
            )
            rows.append(
                {
                    "season": ctx["season"],
                    "week": ctx["week"],
                    "is_playoff": ctx["is_playoff"],
                    "matchup_id": ctx["matchup_id"],
                    "roster_id": ctx["roster_id"],
                    "fantasy_team": ctx["fantasy_team"],
                    "opponent_roster_id": ctx["opponent_roster_id"],
                    "opponent_fantasy_team": ctx["opponent_fantasy_team"],
                    "sleeper_player_id": player["sleeper_player_id"],
                    "player_name": player["player_name"],
                    "position": player["position"],
                    "fantasy_points": player["fantasy_points"],
                    "team_points": team_points,
                    "opponent_points": ctx["opponent_points"],
                    "share_of_team_points": share,
                    "margin": ctx["margin"],
                    "result": ctx["result"],
                    "contribution_rank": player["contribution_rank"],
                }
            )

    if not rows:
        return _empty_frame(PLAYER_CONTRIBUTION_COLUMNS)

    rows.sort(
        key=lambda r: (
            r["season"],
            r["week"],
            r["roster_id"],
            r["contribution_rank"],
            str(r["sleeper_player_id"]),
        )
    )

    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["week"] = result["week"].astype(int)
    result["roster_id"] = result["roster_id"].astype(int)
    result["opponent_roster_id"] = result["opponent_roster_id"].astype(int)
    result["matchup_id"] = result["matchup_id"].astype(int)
    result["contribution_rank"] = result["contribution_rank"].astype(int)
    result["is_playoff"] = result["is_playoff"].astype(bool)
    for column in _CONTRIBUTION_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    for label_column in (
        "fantasy_team",
        "opponent_fantasy_team",
        "sleeper_player_id",
        "player_name",
        "position",
        "result",
    ):
        result[label_column] = pd.Series(
            [
                None if pd.isna(value) else value
                for value in result[label_column].tolist()
            ],
            dtype=object,
        )

    return result[PLAYER_CONTRIBUTION_COLUMNS]


def build_positional_matchup_advantage(
    season_matchup_df: pd.DataFrame, player_week_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row per ``(season, week, roster_id, position)`` comparison (FFA-069).

    For every roster that played a non-bye matchup that week, compares its
    started production at each position (from the union of positions
    started by either side that week) against its opponent's. See the
    module docstring's "Positional matchup advantage" section for the full
    definitions, the FLEX-attribution scope limit, and why a
    never-started-at-that-position side still gets a zero row here (unlike
    ``position_strength.py``'s season-long convention).

    Args:
        season_matchup_df: Same contract as
            :func:`build_matchup_player_contributions`.
        player_week_df: Same contract as
            :func:`build_matchup_player_contributions`.

    Returns:
        A DataFrame with columns :data:`POSITIONAL_ADVANTAGE_COLUMNS`, one
        row per ``(season, week, roster_id, position)`` with at least one
        started player at the position on either side of the matchup,
        sorted by ascending ``season``, then ``week``, then ``roster_id``,
        then ``position``. Returns an empty DataFrame with the expected
        columns if either input is empty or no roster-week qualifies.
    """
    if season_matchup_df.empty or player_week_df.empty:
        return _empty_frame(POSITIONAL_ADVANTAGE_COLUMNS)

    context = _roster_week_context(season_matchup_df)
    started = _started_rows_by_roster_week(player_week_df)

    # position_sums[(season, week, roster_id)][position] = (points, count),
    # built only from started players with a resolvable position -- see the
    # module docstring's "Missing values" section.
    position_sums: dict[tuple, dict[Any, tuple]] = {}
    for key, players in started.items():
        sums: dict[Any, tuple] = {}
        for player in players:
            position = player["position"]
            if pd.isna(position):
                continue
            points, count = sums.get(position, (0.0, 0))
            sums[position] = (points + player["fantasy_points"], count + 1)
        if sums:
            position_sums[key] = sums

    rows: list[dict] = []
    for key, ctx in context.items():
        opp_key = (str(ctx["season"]), ctx["week"], ctx["opponent_roster_id"])
        own_sums = position_sums.get(key, {})
        opp_sums = position_sums.get(opp_key, {})
        if not own_sums and not opp_sums:
            continue

        positions = set(own_sums) | set(opp_sums)
        for position in positions:
            own_points, own_starters = own_sums.get(position, (0.0, 0))
            opp_points, opp_starters = opp_sums.get(position, (0.0, 0))
            rows.append(
                {
                    "season": ctx["season"],
                    "week": ctx["week"],
                    "is_playoff": ctx["is_playoff"],
                    "matchup_id": ctx["matchup_id"],
                    "roster_id": ctx["roster_id"],
                    "fantasy_team": ctx["fantasy_team"],
                    "opponent_roster_id": ctx["opponent_roster_id"],
                    "opponent_fantasy_team": ctx["opponent_fantasy_team"],
                    "position": position,
                    "own_points": own_points,
                    "own_starters": own_starters,
                    "opponent_points": opp_points,
                    "opponent_starters": opp_starters,
                    "positional_advantage": own_points - opp_points,
                }
            )

    if not rows:
        return _empty_frame(POSITIONAL_ADVANTAGE_COLUMNS)

    rows.sort(
        key=lambda r: (
            r["season"],
            r["week"],
            r["roster_id"],
            str(r["position"]),
        )
    )

    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["week"] = result["week"].astype(int)
    result["roster_id"] = result["roster_id"].astype(int)
    result["opponent_roster_id"] = result["opponent_roster_id"].astype(int)
    result["matchup_id"] = result["matchup_id"].astype(int)
    result["own_starters"] = result["own_starters"].astype(int)
    result["opponent_starters"] = result["opponent_starters"].astype(int)
    result["is_playoff"] = result["is_playoff"].astype(bool)
    for column in _ADVANTAGE_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    for label_column in ("fantasy_team", "opponent_fantasy_team", "position"):
        result[label_column] = pd.Series(
            [
                None if pd.isna(value) else value
                for value in result[label_column].tolist()
            ],
            dtype=object,
        )

    return result[POSITIONAL_ADVANTAGE_COLUMNS]


def reconcile_matchup_points(
    season_matchup_df: pd.DataFrame,
    player_week_df: pd.DataFrame,
    *,
    points_tolerance: float = MATCHUP_POINTS_TOLERANCE,
) -> pd.DataFrame:
    """Compare each roster-week's recorded score against its started player total.

    Per ``(season, week, roster_id)``, compares ``season_matchup_df``'s
    recorded ``points_1``/``points_2`` against the sum of that roster-week's
    started players' ``fantasy_points`` in ``player_week_df``. See the
    module docstring's "Reconciliation" section for why a mismatch is a
    real, expected possibility here (not just floating-point noise) and
    what it can indicate.

    Args:
        season_matchup_df: Same contract as
            :func:`build_matchup_player_contributions`. Bye rows contribute
            no roster-week to this comparison (see the module docstring's
            "Row universe" section); an incomplete matchup's missing side
            contributes ``matchup_points = NaN`` for that roster.
        player_week_df: Same contract as
            :func:`build_matchup_player_contributions`.
        points_tolerance: Absolute float tolerance for ``points_match``.
            Defaults to :data:`MATCHUP_POINTS_TOLERANCE`.

    Returns:
        A DataFrame with columns :data:`RECONCILE_COLUMNS`, one row per
        roster-week that appears in a non-bye ``season_matchup_df`` row,
        sorted by ascending ``season``, then ``week``, then ``roster_id``.
        ``started_points`` is ``NaN`` (and ``points_match`` is ``False``)
        for a roster-week with no started rows in ``player_week_df`` at all
        -- see the module docstring's "Missing values" section for why that
        case is left unknown rather than defaulted to ``0.0``. Returns an
        empty DataFrame with the expected columns if ``season_matchup_df``
        is empty.
    """
    if season_matchup_df.empty:
        return _empty_frame(RECONCILE_COLUMNS)

    context = _roster_week_context(season_matchup_df)
    if not context:
        return _empty_frame(RECONCILE_COLUMNS)

    started = _started_rows_by_roster_week(player_week_df)

    rows: list[dict] = []
    for key, ctx in context.items():
        players = started.get(key)
        started_points = (
            math.fsum(p["fantasy_points"] for p in players)
            if players is not None
            else None
        )
        matchup_points = ctx["team_points"]

        if matchup_points is None or started_points is None:
            diff = None
            match = False
        else:
            diff = matchup_points - started_points
            match = abs(diff) <= points_tolerance

        rows.append(
            {
                "season": ctx["season"],
                "week": ctx["week"],
                "roster_id": ctx["roster_id"],
                "fantasy_team": ctx["fantasy_team"],
                "matchup_points": matchup_points,
                "started_points": started_points,
                "points_diff": diff,
                "points_match": match,
            }
        )

    rows.sort(key=lambda r: (r["season"], r["week"], r["roster_id"]))

    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["week"] = result["week"].astype(int)
    result["roster_id"] = result["roster_id"].astype(int)
    result["points_match"] = result["points_match"].astype(bool)
    for column in _RECONCILE_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    result["fantasy_team"] = pd.Series(
        [
            None if pd.isna(value) else value
            for value in result["fantasy_team"].tolist()
        ],
        dtype=object,
    )

    return result[RECONCILE_COLUMNS]
