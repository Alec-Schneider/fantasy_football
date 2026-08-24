"""Team-level positional strength metrics from the player-week fact table (FFA-066).

Consumes FFA-064's
:func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`
output (``PLAYER_WEEK_COLUMNS``-shaped, with provider raw-stat columns and a
``fantasy_points`` column) and collapses it into one row per ``(season,
fantasy_team, position)``: how much scoring a fantasy team actually got from
a position group, how that production ranks against the rest of the league
at the same position, what share of the team's total scoring the position
represents, how many rostered players actually contributed there, and how
volatile the position's week-to-week output was.

This is a *team*-level question, not a *player*-level one -- the individual
shape of one player's own scoring distribution is FFA-065's
:mod:`fantasy_analyzer.players.performance`, and this module deliberately
reuses that module's and FFA-053's :mod:`fantasy_analyzer.analytics.consistency`'s
formulas (population standard deviation, a self-referential mean +/- k*stdev
boom/bust threshold, the same style of minimum sample-size guards) wherever
the underlying question is identical. It diverges from both in the several
places the position-group, team-relative grain genuinely demands a different
answer, and every divergence is documented in full below, because this
repository's convention is that the docstring is the actual specification,
not the code.

This module performs no network access; it operates entirely on an
already-built ``player_week_df``.

Grouping key: ``(season, fantasy_team, position)`` -- seasons are never pooled
------------------------------------------------------------------------------

Output rows are grouped by ``(season, fantasy_team, position)``.
``fantasy_team`` is read directly from ``player_week_df``'s own
``fantasy_team`` column (already resolved by FFA-064 from ``teams_df``'s
``display_name``, the same resolved label ``weekly_scores.py`` and
``consistency.py`` use as ``owner``); this module does not re-resolve it
from a separate ``teams_df`` parameter, matching those modules' "no
``teams_df`` parameter" precedent.

``position`` is read directly from each row's own ``position`` value, **not**
resolved via ``performance.py``'s per-player-season majority vote. That
majority-vote resolution answers "what position does this player identify
as for the whole season," which is the right question for a player-identity
label; this module instead answers a team-week production question --
"which position group did this scoring actually land in, that week" -- and a
mid-season position reclassification (rare, but real: a practice-squad
tight end reclassified as a fullback, a Sleeper catalog correction) should
attribute each week's points to whichever position applied *that week*, not
retroactively to whichever position was more common across the whole
season. A player who genuinely switches positions while on one fantasy
team's roster can therefore contribute to two different position groups'
production, consistency and depth for that team-season; this is accepted
as correct, not a bug to special-case.

A row whose ``season``, ``fantasy_team``, or ``position`` is missing/null
cannot be assigned to any group and is skipped entirely -- it contributes to
no team's production, depth, or team-total denominator (see "Rows outside
{QB, RB, WR, TE} are not dropped" and "share_of_team_points" below for what
this means for the partition). ``sleeper_player_id`` missing on an otherwise
usable row is likewise skipped for the purposes of depth-counting (a
distinct-player count needs a player id) but such a row is not expected
under FFA-064's contract.

Like ``performance.py`` (and unlike ``consistency.py``'s pooled-season
default), seasons are never pooled: the key includes ``season`` explicitly,
so a multi-season ``player_week_df`` produces separate rows per season. A
caller who wants a multi-season view must pre-aggregate this table's own
season rows.

Started vs. all weeks: production/consistency use STARTED weeks only;
depth uses all rostered weeks
------------------------------------------------------------------------

This is the central design decision of this module, and it is the one place
this ticket deliberately reaches a **different** answer than FFA-065 did to
the "what counts" question -- because it is answering a different question.

``performance.py`` includes both started and benched games because it
describes a *player's own on-field production*, independent of any one
fantasy manager's roster decisions. This module instead describes a
*fantasy team's realized position strength* -- how much scoring a manager
actually extracted from a position group, given the lineup decisions that
manager actually made. Those are not the same question: a bench tight end
who quietly puts up 15 points a week the manager never started contributed
nothing to that team's realized position strength, however good he was as a
player. So:

- **Production and consistency columns** (``weeks_played``, ``total_points``,
  ``points_per_game``, ``median_points``, ``stdev_points``, ``cv``,
  ``scoring_floor``, ``scoring_ceiling``, ``boom_weeks``/``boom_pct``,
  ``bust_weeks``/``bust_pct``, and therefore ``positional_rank`` and
  ``share_of_team_points``, which are both derived from ``total_points``) are
  computed **only from rows where ``started`` is ``True``.**
- **Positional depth** (``positional_depth``) is computed from **every**
  rostered row, started or benched (see "Positional depth" below), because
  depth is a roster-construction question -- how many usable players did
  this team actually have at the position, regardless of whether the
  manager started them that particular week.

A "weekly position score" is the sum of ``fantasy_points`` across every
``started == True`` row that shares one ``(season, fantasy_team, position,
week)`` -- more than one player can be started at a position in the same
week (e.g. two starting running backs, or a FLEX-started wide receiver
alongside two starting wide receivers, all reporting ``position == "WR"``),
and their points are summed into a single weekly observation for that
position group, exactly as a team's actual realized scoring works.

Weeks with **zero** started players at a position are not zero-filled into
the weekly series -- they simply produce no observation that week, the same
"no qualifying game, no observation" rule ``performance.py`` applies at the
player grain (see that module's docstring). A team that started nobody at
tight end in week 7 (bye, or a streaming/zero-TE roster construction) has
that week silently absent from its TE series, not present as a ``0.0``
observation. This is a deliberate choice, not an oversight: zero-filling
every team's every week for every position the team never used would flood
``stdev_points``/``cv`` with variance that describes roster-construction
choices (does this team even carry a rosterable option at this position)
rather than week-to-week performance volatility once the position actually
took the field -- the identical reasoning ``performance.py`` gives for
excluding bye weeks from a player's own distribution, applied one level up.

A ``(season, fantasy_team, position)`` group with **zero** started weeks
gets **no row at all**, following ``consistency.py``'s and ``performance.py``'s
identical "a distribution over zero observations is undefined, not
empty-but-real" precedent. A team that rostered a tight end all season but
never once started him therefore gets no TE row for that team-season --
including no ``positional_depth`` value, even though a bench-only tight end
could in principle have real depth to report. This is a real limitation
(see "Positional depth" below), accepted deliberately to keep one row's
columns describing one coherent, always-jointly-defined set of production
facts rather than mixing "has production" and "has depth but no production"
rows with different partially-``NaN`` shapes.

Positional depth
-------------------

**Definition:** ``positional_depth`` is the count of **distinct**
``sleeper_player_id`` values rostered by that fantasy team, at that
position, in that season, with **at least one qualifying game** -- reusing
``performance.py``'s exact "game played" rule (at least one raw provider
stat column non-null for that player-week; see that module's "What counts
as a game played" section for the full rationale, reproduced functionally
here as :func:`_stat_columns` since that helper is private to
``performance.py`` and this module does not import another module's private
name). Both started and benched qualifying weeks count toward a player's
depth eligibility -- a rostered handcuff running back who only ever played
on the bench still represents real roster depth at the position, which is
exactly the roster-construction question this metric is for.

This chooses AGENTS.md's own suggested reading of "positional depth"
verbatim ("count of distinct rostered players at that position with at
least one qualifying game") over the alternative of simply counting every
rostered player id regardless of whether they ever actually took the field
(which would count a practice-squad stash who never played all season as
"depth," conflating roster hoarding with usable depth) or counting only
*started* players (which would collapse depth into a restatement of
``weeks_played`` and lose the distinction between "we started one running
back all year" and "we started one running back all year but had two
usable ones on the bench").

**Depth is scoped to a row that already has production.** Because a
position group with zero started weeks gets no row at all (see above),
``positional_depth`` is only ever reported for a team-position that the
team actually started at least once that season -- see the limitation
noted above. A future ticket wanting "bench-only depth for positions never
started" would need a different row-existence rule than this one.

positional_rank
------------------

**Definition:** within each ``(season, position)`` group, teams are ranked
by descending ``total_points`` (the started-weeks production total defined
above) using **standard competition ("1224") ranking** -- the identical
convention ``standings.py``'s ``scoring_rank``, ``scoring_summary.py``'s
``scoring_rank``, and ``weekly_scores.py``'s ``weekly_rank`` already use:
teams tied on ``total_points`` share a rank, and the next distinct rank
skips the number of tied teams. ``positional_rank = 1`` is the league's best
producer at that position that season.

Ranking is on **total production**, not ``points_per_game``, matching
``standings.py``'s own choice of cumulative ``points_for`` (not a per-game
rate) for ``scoring_rank`` -- see that module's "scoring_rank is based on
cumulative points_for, not points_per_game" comment. A team that started a
position for only six of fourteen weeks (e.g. a mid-season roster overhaul)
is ranked on what it actually produced over the season, not on a rate that
would let a small, hot sample outrank a full season of solid-but-unspectacular
production. A caller who wants a rate-based ranking can sort
``points_per_game`` directly; this frame does not compute a second rank
column for it, for the identical "no single 'better' direction to
smuggle in" reasoning ``consistency.py`` gives for having no rank column at
all -- production volume has one obvious "better" direction (more), so it
gets a rank column here where consistency does not.

Ranking is computed **only among teams with a row for that position** (see
above: a team with zero started weeks at a position has no row and does not
enter the ranking, rather than being ranked last with an implicit zero).
This mirrors ``weekly_scores.py``'s "field size... may be fewer than the
league size" behavior: the number of teams ranked at a position can
legitimately vary position to position (every team ranks at QB; only the
teams that ever started a kicker rank at K).

This function is designed to be called on a ``player_week_df`` scoped to one
league-season at a time, the same implicit assumption every other analytics
module in this codebase makes (``fantasy_team`` labels and scoring settings
are league-specific). Passing a frame that spans multiple leagues in the
same season would conflate their ``fantasy_team`` labels into one ranking
and is not supported.

share_of_team_points
------------------------

**Definition:** for a ``(season, fantasy_team, position)`` row,
``share_of_team_points = total_points / team_total_points``, where
``team_total_points`` is the sum of ``total_points`` across **every**
position row this module emits for that ``(season, fantasy_team)`` --
i.e. every position the team started at least once that season.

**Positions outside {QB, RB, WR, TE} are not dropped, and this is a
deliberate partition-correctness decision.** This module does not restrict
its output to the four skill positions AGENTS.md's "Analyze" list names
(QB/RB/WR/TE production). It computes and emits a row for **every** position
value present in the input (e.g. also K, DEF, in leagues that start them),
so that ``share_of_team_points`` is a genuine additive partition of a
team's *started, position-resolved* scoring: summing ``share_of_team_points``
across every row for one ``(season, fantasy_team)`` gives (approximately,
see below) ``1.0``. If this module instead restricted its output rows to
{QB, RB, WR, TE} but still divided by a team's *true* total (including
K/DEF), a team's four shares would sum to something like ``0.85``, and a
reader would not know from the table alone whether that ``0.15`` gap
represented kicker/defense scoring, a data problem, or a bug in the
computation. Keeping the row set generic and having the shares sum to
``~1.0`` by construction is more legible. A caller who wants strictly the
four AGENTS.md headline positions should filter the returned frame with
``position.isin(["QB", "RB", "WR", "TE"])`` after calling; the module itself
does not filter, since doing so would break the partition property.

("Approximately 1.0", not exactly, for two reasons, both edge cases: (1) a
row whose ``position`` could not be resolved (``None``/``NaN``) is excluded
from every group -- including the ``team_total_points`` denominator -- so
any started scoring from an unresolvable-position player is invisible to
this partition entirely, a documented gap rather than a silent
misattribution; (2) if any position's ``total_points`` is negative -- see
below -- the partition can sum to slightly more or less than ``1.0``, or
individual shares can fall outside ``[0, 1]``.)

**Negative-scoring positions can push a share outside [0, 1].** Most
Sleeper scoring settings have no category that can make a skill position's
``fantasy_points`` negative, but defense/special-teams scoring commonly
does (points allowed, yards allowed). If a team's DEF total is negative
enough to pull ``team_total_points`` below any single position's own total,
that position's share can legitimately exceed ``1.0``, and DEF's own share
can be negative. This is not clamped or special-cased -- it is the correct,
literal reading of "share of the team's total scoring," and clamping it
would hide a real signal (a defense that actively cost the team points).

``share_of_team_points`` is ``NaN`` when ``team_total_points <= 0``
(division by zero, or a team whose total started production that season
was zero or negative across every position it has a row for) -- the
identical "where appropriate" guard ``consistency.py``'s ``cv`` and
``performance.py``'s ``cv`` both apply to their own denominators.

Boom and bust: reused, self-referential threshold
--------------------------------------------------------

Identical convention to ``consistency.py`` and ``performance.py``: a boom
week is one where a team's position-group weekly score exceeded ``k`` of
that position group's own season standard deviations above its own season
mean; a bust week, more than ``k`` below. The default ``k`` is
:data:`BOOM_BUST_THRESHOLD_STDEVS` = ``1.0``, for the identical reasoning
those modules give -- not re-derived here. ``boom_bust_threshold`` is a
parameter for the same reason: no threshold is canonical.

Small samples: when dispersion and boom/bust are undefined
---------------------------------------------------------------

Two minimum week counts apply, reused verbatim (values, not code) from
``consistency.py`` because the underlying proofs are about the arithmetic
of ``n`` observations and do not depend on whether those observations are
roster-weeks, player-games, or team-position-weeks:

- ``weeks_played < MIN_WEEKS_FOR_DISPERSION`` (2) -> ``stdev_points`` and
  ``cv`` are ``NaN``.
- ``weeks_played < MIN_WEEKS_FOR_BOOM_BUST`` (3) -> the four boom/bust
  columns are ``NaN``. At ``n = 2`` the classification is provably
  independent of the actual scores; see ``consistency.py``'s docstring for
  the full algebraic and floating-point argument, which applies unchanged
  here.

These constants are named to match ``consistency.py``'s ``MIN_WEEKS_FOR_*``
convention (this module's unit of observation is a team-position-*week*,
the same grain consistency.py operates at) rather than ``performance.py``'s
``MIN_GAMES_FOR_*`` naming (that module's unit of observation is a
player-*game*).

A note on typical sample sizes here: because a "week" only counts when the
team actually started someone at the position (see above), a position a
team streams or platoons -- TE, K, and often the FLEX-eligible slots -- will
often have noticeably fewer qualifying weeks than the team's full regular
season, even before any small-sample guard is applied. Treat this frame's
boom/bust columns, and even its dispersion columns, with the same "coarse
shape descriptor" skepticism ``consistency.py`` documents, more so here than
at that module's full-season, always-scored roster grain.

Regular season vs. playoffs: this table is phase-agnostic
------------------------------------------------------------

``player_week_df`` (FFA-064's output) has no ``is_playoff`` column, the
identical situation ``performance.py`` documents. This module makes no
phase distinction of its own and cannot: every started week present in the
input for a team-position enters the same distribution, regular season and
playoff weeks alike, and ``positional_rank``/``share_of_team_points`` are
computed over that same combined-phase total.

A caller wanting a phase-specific view must pre-filter ``player_week_df`` on
``week`` against the calling league's playoff-start boundary (FFA-022,
``LeagueSettings.playoff_week_start``) **before** calling this function --
the same caller-filters-first pattern ``consistency.py`` and ``performance.py``
document.

Missing values / edge cases
----------------------------

- **Empty ``player_week_df``**: returns an empty DataFrame with
  :data:`POSITION_STRENGTH_COLUMNS`.
- **A ``player_week_df`` with no raw stat columns at all**: no player-week
  can ever satisfy the "qualifying game" test, so ``positional_depth`` is
  ``0`` for every row that is otherwise emitted (production/consistency do
  not depend on the stat columns at all, since they key off ``started`` and
  ``fantasy_points`` only, so rows are still emitted with real production
  metrics and ``positional_depth = 0``) -- a documented degenerate case, not
  an error.
- **A row with missing ``season``, ``fantasy_team``, or ``position``**: not
  expected under FFA-064's contract for ``season``, and only reachable for
  ``fantasy_team``/``position`` via FFA-064's own documented "unresolved
  roster/identity -> ``None``" fallbacks; such a row cannot be assigned to
  any group and is skipped entirely -- see "Grouping key" above.
- **A started row with missing ``fantasy_points``**: not expected under
  FFA-064's contract (always a defined float, ``0.0`` at worst); if present,
  skipped from the weekly production sum defensively, mirroring
  ``performance.py``'s identical handling.
- **A team with zero started weeks at a position**: no row at all (see
  "Started vs. all weeks" above), and the team does not enter that
  position's ``positional_rank`` field.
- **A zero-variance team-position** (``n >= 2``, identical weekly score every
  qualifying week): reports ``stdev_points = 0.0`` and ``cv = 0.0`` (when
  ``points_per_game > 0``), with ``scoring_floor == scoring_ceiling ==
  points_per_game == median_points``, and zero booms/busts -- identical
  handling to ``consistency.py``/``performance.py``.
- **Duplicate weekly scores** within a team-position's season need no
  special handling, identical to the two reference modules.

Column dtypes
--------------

``season`` and ``weeks_played`` are plain ``int64``. ``positional_rank`` and
``positional_depth`` are plain ``int64`` (always defined for a row that
exists: a row cannot exist without at least one started week, so it always
has a computable rank among its position's field, and depth is a count that
is ``0`` at worst, never undefined). ``fantasy_team`` and ``position`` are
``object``. Every other metric column is ``float64`` with undefined values
as ``NaN``, including ``boom_weeks``/``bust_weeks`` (whole numbers carried
as floats, cast explicitly so the dtype does not silently change between
calls). Test undefined values with ``pd.isna``, not ``is None``.
"""

from __future__ import annotations

from statistics import fmean, median, pstdev
from typing import Any, Optional

import pandas as pd

from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS

#: Column order for the DataFrame returned by
#: :func:`build_position_strength_metrics`.
POSITION_STRENGTH_COLUMNS = [
    "season",
    "fantasy_team",
    "position",
    "weeks_played",
    "total_points",
    "points_per_game",
    "median_points",
    "stdev_points",
    "cv",
    "scoring_floor",
    "scoring_ceiling",
    "boom_weeks",
    "boom_pct",
    "bust_weeks",
    "bust_pct",
    "positional_rank",
    "share_of_team_points",
    "positional_depth",
]

#: Default boom/bust threshold, in the team-position group's own standard
#: deviations. Reuses ``consistency.py``'s / ``performance.py``'s convention
#: and default value -- see the module docstring's "Boom and bust" section.
BOOM_BUST_THRESHOLD_STDEVS = 1.0

#: Fewest qualifying (started) weeks for which ``stdev_points``/``cv`` are
#: defined. See "Small samples" in the module docstring.
MIN_WEEKS_FOR_DISPERSION = 2

#: Fewest qualifying (started) weeks for which the boom/bust columns are
#: defined. See "Small samples" in the module docstring.
MIN_WEEKS_FOR_BOOM_BUST = 3

#: Metric columns cast to ``float64`` so undefined values are ``NaN`` and the
#: dtype does not vary with the data -- see "Column dtypes" in the module
#: docstring.
_FLOAT_COLUMNS = [
    "total_points",
    "points_per_game",
    "median_points",
    "stdev_points",
    "cv",
    "scoring_floor",
    "scoring_ceiling",
    "boom_weeks",
    "boom_pct",
    "bust_weeks",
    "bust_pct",
    "share_of_team_points",
]


def _stat_columns(player_week_df: pd.DataFrame) -> list[str]:
    """The raw provider stat columns present in ``player_week_df``.

    Every column that is neither one of ``PLAYER_WEEK_COLUMNS`` nor
    ``fantasy_points``, functionally identical to ``performance.py``'s
    private helper of the same name and purpose (not imported, since it is
    private to that module -- see the module docstring's "Positional depth"
    section).
    """
    excluded = set(PLAYER_WEEK_COLUMNS) | {"fantasy_points"}
    return [column for column in player_week_df.columns if column not in excluded]


def _summarize_group(points: list[float], boom_bust_threshold: float) -> dict:
    """Summarize one team-position's qualifying-week production series.

    Applies the exact definitions in the module docstring: population
    standard deviation, a mean-relative boom/bust threshold measured in that
    standard deviation, and the ``MIN_WEEKS_FOR_DISPERSION`` /
    ``MIN_WEEKS_FOR_BOOM_BUST`` minimums below which the corresponding
    columns are ``None`` (rendered as ``NaN`` in the returned frame).
    """
    weeks_played = len(points)
    points_per_game = fmean(points)

    stdev_points: Optional[float] = (
        pstdev(points) if weeks_played >= MIN_WEEKS_FOR_DISPERSION else None
    )

    cv: Optional[float] = (
        stdev_points / points_per_game
        if stdev_points is not None and points_per_game > 0
        else None
    )

    boom_weeks: Optional[int] = None
    bust_weeks: Optional[int] = None
    boom_pct: Optional[float] = None
    bust_pct: Optional[float] = None

    if weeks_played >= MIN_WEEKS_FOR_BOOM_BUST and stdev_points is not None:
        boom_threshold = points_per_game + boom_bust_threshold * stdev_points
        bust_threshold = points_per_game - boom_bust_threshold * stdev_points
        # Strict inequality: with ``>=`` a zero-variance group would have
        # every week counted as both a boom and a bust.
        boom_weeks = sum(1 for value in points if value > boom_threshold)
        bust_weeks = sum(1 for value in points if value < bust_threshold)
        boom_pct = boom_weeks / weeks_played
        bust_pct = bust_weeks / weeks_played

    return {
        "weeks_played": weeks_played,
        "total_points": sum(points),
        "points_per_game": points_per_game,
        "median_points": median(points),
        "stdev_points": stdev_points,
        "cv": cv,
        "scoring_floor": min(points),
        "scoring_ceiling": max(points),
        "boom_weeks": boom_weeks,
        "boom_pct": boom_pct,
        "bust_weeks": bust_weeks,
        "bust_pct": bust_pct,
    }


def _assign_positional_ranks(rows: list[dict]) -> None:
    """Assign ``positional_rank`` in place within each ``(season, position)`` group.

    Standard competition ("1224") ranking by descending ``total_points``,
    the identical convention ``standings.py``'s ``scoring_rank`` and
    ``weekly_scores.py``'s ``weekly_rank`` use -- see the module docstring's
    "positional_rank" section.
    """
    groups: dict[tuple[int, Any], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["season"], row["position"]), []).append(row)

    for group_rows in groups.values():
        ordered = sorted(
            group_rows,
            key=lambda row: (-row["total_points"], str(row["fantasy_team"])),
        )
        current_rank = 0
        previous_points = None
        for position, row in enumerate(ordered, start=1):
            if row["total_points"] != previous_points:
                current_rank = position
                previous_points = row["total_points"]
            row["positional_rank"] = current_rank


def build_position_strength_metrics(
    player_week_df: pd.DataFrame,
    boom_bust_threshold: float = BOOM_BUST_THRESHOLD_STDEVS,
) -> pd.DataFrame:
    """Build one row per ``(season, fantasy_team, position)`` describing that
    team's realized production, depth, and consistency at the position.

    Collapses each team-position's qualifying (started) weekly fantasy
    scores into volume (``total_points``), center (``points_per_game``,
    ``median_points``), spread (``stdev_points``, ``cv``), extremes
    (``scoring_floor``, ``scoring_ceiling``), self-relative outlier
    frequency (``boom_weeks``/``boom_pct``, ``bust_weeks``/``bust_pct``),
    league-relative standing (``positional_rank``), the position's share of
    that team's total realized scoring (``share_of_team_points``), and a
    roster-construction depth count (``positional_depth``). See the module
    docstring for the exact formulas, why production/consistency use
    started weeks only while depth uses all rostered weeks, the
    ``positional_rank`` and ``share_of_team_points`` definitions (including
    why positions outside QB/RB/WR/TE are not dropped), the boom/bust
    convention, and the minimum week counts below which columns are
    ``NaN``.

    Args:
        player_week_df: A
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            DataFrame (plus provider raw-stat columns and ``fantasy_points``
            last), as produced by
            :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`.
            Every column other than ``PLAYER_WEEK_COLUMNS`` and
            ``fantasy_points`` is treated as a raw provider stat column for
            the depth "game played" test. This function is phase-agnostic
            (see the module docstring) and expects to be scoped to one
            league-season; filter on ``week`` against a league's
            playoff-start boundary before calling for a phase-specific view.
        boom_bust_threshold: How many of a team-position's own standard
            deviations a week must exceed to count as a boom or a bust.
            Defaults to :data:`BOOM_BUST_THRESHOLD_STDEVS` (``1.0``), a
            documented convention rather than a standard.

    Returns:
        A DataFrame with columns :data:`POSITION_STRENGTH_COLUMNS`, one row
        per ``(season, fantasy_team, position)`` with at least one started
        qualifying week in the input, sorted by ascending ``season``, then
        ``fantasy_team``, then ``position``. ``stdev_points`` and ``cv`` are
        ``NaN`` for a team-position with fewer than
        :data:`MIN_WEEKS_FOR_DISPERSION` qualifying weeks, and the four
        boom/bust columns are ``NaN`` for fewer than
        :data:`MIN_WEEKS_FOR_BOOM_BUST`; ``cv`` is also ``NaN`` when
        ``points_per_game <= 0``, and ``share_of_team_points`` is ``NaN``
        when the team's total across every position row is ``<= 0``.
        Returns an empty DataFrame with the expected columns if the input is
        empty or no team-position has a qualifying started week.

    Raises:
        ValueError: If ``boom_bust_threshold`` is negative, which would make
            the boom and bust bands overlap and let a single week count as
            both.
    """
    if boom_bust_threshold < 0:
        raise ValueError(
            "boom_bust_threshold must be non-negative, got "
            f"{boom_bust_threshold!r} -- a negative threshold would put the "
            "boom band below the bust band and classify weeks as both"
        )

    if player_week_df.empty:
        return pd.DataFrame(columns=POSITION_STRENGTH_COLUMNS)

    stat_columns = _stat_columns(player_week_df)

    # A row satisfies the depth "qualifying game" test only if at least one
    # raw stat column is non-null -- reused verbatim from performance.py's
    # rule. With no stat columns at all (a degenerate input), no row can
    # ever qualify and every group's positional_depth is 0.
    if stat_columns:
        played_mask = player_week_df[stat_columns].notna().any(axis=1)
    else:
        played_mask = pd.Series(False, index=player_week_df.index)

    # weekly_totals[(season, fantasy_team, position, week)] = summed
    # fantasy_points across every started row sharing that key -- the
    # "weekly position score" defined in the module docstring.
    weekly_totals: dict[tuple, float] = {}
    # depth_players[(season, fantasy_team, position)] = set of distinct
    # sleeper_player_id with >= 1 qualifying game, started or benched.
    depth_players: dict[tuple, set] = {}

    for row, played in zip(
        player_week_df.itertuples(index=False), played_mask, strict=True
    ):
        if (
            pd.isna(row.season)
            or pd.isna(getattr(row, "fantasy_team", None))
            or pd.isna(getattr(row, "position", None))
        ):
            # Cannot be assigned to a group -- see the module docstring's
            # "Grouping key" section.
            continue

        season = int(row.season)
        fantasy_team = row.fantasy_team
        position = row.position
        group_key = (season, fantasy_team, position)

        if played and pd.notna(getattr(row, "sleeper_player_id", None)):
            depth_players.setdefault(group_key, set()).add(row.sleeper_player_id)

        if not bool(row.started):
            continue

        points = row.fantasy_points
        if pd.isna(points):
            # Not expected under FFA-064's contract; skipped defensively
            # rather than corrupting the weekly total with a NaN.
            continue

        week_key = group_key + (row.week,)
        weekly_totals[week_key] = weekly_totals.get(week_key, 0.0) + float(points)

    # Fold weekly_totals into per-(season, fantasy_team, position) lists of
    # qualifying weekly scores.
    group_weeks: dict[tuple, list[float]] = {}
    for (season, fantasy_team, position, _week), value in weekly_totals.items():
        group_weeks.setdefault((season, fantasy_team, position), []).append(value)

    if not group_weeks:
        # No team-position has a single started, qualifying week -- see the
        # module docstring's "Started vs. all weeks" section.
        return pd.DataFrame(columns=POSITION_STRENGTH_COLUMNS)

    rows: list[dict] = []
    for (season, fantasy_team, position), points in group_weeks.items():
        summary = _summarize_group(points, boom_bust_threshold)
        summary["season"] = season
        summary["fantasy_team"] = fantasy_team
        summary["position"] = position
        summary["positional_depth"] = len(
            depth_players.get((season, fantasy_team, position), set())
        )
        rows.append(summary)

    # share_of_team_points: total_points for this row divided by the sum of
    # total_points across every row this module emits for the same
    # (season, fantasy_team) -- see the module docstring's
    # "share_of_team_points" section. Positions with no row (never started)
    # are not part of either side of this ratio.
    team_totals: dict[tuple[int, Any], float] = {}
    for row in rows:
        key = (row["season"], row["fantasy_team"])
        team_totals[key] = team_totals.get(key, 0.0) + row["total_points"]

    for row in rows:
        team_total = team_totals[(row["season"], row["fantasy_team"])]
        row["share_of_team_points"] = (
            row["total_points"] / team_total if team_total > 0 else None
        )

    _assign_positional_ranks(rows)

    rows.sort(
        key=lambda row: (
            row["season"],
            str(row["fantasy_team"]),
            str(row["position"]),
        )
    )

    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["weeks_played"] = result["weeks_played"].astype(int)
    result["positional_rank"] = result["positional_rank"].astype(int)
    result["positional_depth"] = result["positional_depth"].astype(int)
    for column in _FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    # Assigned as explicit object-dtype Series, mirroring performance.py's
    # and consistency.py's identical handling: pandas' string-dtype
    # inference would otherwise upcast a column mixing real labels with
    # ``None`` into a dtype that silently turns ``None`` into ``NaN``.
    for label_column in ("fantasy_team", "position"):
        result[label_column] = pd.Series(result[label_column].tolist(), dtype=object)

    return result[POSITION_STRENGTH_COLUMNS]
