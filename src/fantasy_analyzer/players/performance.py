"""Season-level player performance metrics from the player-week fact table (FFA-065).

Consumes FFA-064's
:func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`
output (``PLAYER_WEEK_COLUMNS``-shaped, with provider raw-stat columns and a
``fantasy_points`` column) and collapses each player's weekly fantasy scores
into one row describing the **shape of that player's own scoring
distribution** for a season: where it centers, how much it moves, how low it
sank, how high it reached, and how often it landed far from its own normal
game. This is the player-level analog of FFA-053's
:mod:`fantasy_analyzer.analytics.consistency`, and this module deliberately
reuses that module's formulas (population standard deviation, a
self-referential mean +/- k*stdev boom/bust threshold, the same minimum
sample-size guards) wherever the underlying question is identical. It
diverges from that module in exactly the two places the player-level grain
demands a different answer -- what counts as a "game played" and what a
"player" identifies -- and both are documented in full below, because this
repository's convention is that the docstring is the actual specification,
not the code.

This module performs no network access; it operates entirely on an
already-built ``player_week_df``.

Metric definitions
-------------------

Let ``x_1 ... x_n`` be the ``fantasy_points`` values across a player's
qualifying games in a season (see "What counts as a game played" below), and
let ``k`` be ``boom_bust_threshold`` (:data:`BOOM_BUST_THRESHOLD_STDEVS` by
default).

- **games_played** -- ``n``, the count of weeks this module counts as a game
  the player actually played (see below). The sample size behind every other
  column, and deliberately the first metric column, for the same reason
  ``consistency.py``'s ``weeks_played`` is: at realistic ``n`` (an
  eight-to-nine-week RB2 workload, a seventeen-week iron-man QB1) these are
  small-sample statistics and the reader should see the denominator before
  the rest of the row.
- **total_points** -- ``sum(x_i)``, the player's season fantasy-point total
  over qualifying games. Included because ``points_per_game`` alone erases
  the difference between a player who was excellent in six games and one who
  was equally excellent in sixteen -- exactly the level-vs-volume ambiguity
  FFA-066/FFA-068 (positional strength, replacement value) will need to
  resolve, and this table should not force them to recompute it.
- **points_per_game** -- ``(1/n) * sum(x_i)``, the arithmetic mean.
  Deliberately named ``points_per_game`` rather than ``mean_points``
  (``consistency.py``'s name for the identical formula) because "points per
  game" is this ticket's own vocabulary in AGENTS.md and is the term every
  downstream fantasy consumer of this table expects.
- **median_points** -- the middle value of the sorted scores for odd ``n``;
  the arithmetic mean of the two middle values for even ``n`` (the standard
  convention; see ``consistency.py``'s identical note). Reading it next to
  ``points_per_game`` is a cheap skew check: a boom-or-bust player's mean
  sits well above his median.
- **stdev_points** -- the **population** standard deviation
  ``sqrt( (1/n) * sum( (x_i - points_per_game)^2 ) )``. Population, not
  sample, for the identical reason ``consistency.py`` gives: the games in
  the input are not a sample of a wider population of hypothetical seasons,
  they are the complete set of games this table counts as played. ``NaN``
  when ``n < MIN_GAMES_FOR_DISPERSION``.
- **cv** -- the coefficient of variation, ``stdev_points / points_per_game``:
  volatility expressed relative to the player's own scoring level, so a
  high-volume RB1 is not automatically called "volatile" just because his
  raw point swings are bigger in absolute terms than a low-volume handcuff's.
  ``NaN`` when ``stdev_points`` is undefined or ``points_per_game <= 0``.
- **scoring_floor** / **scoring_ceiling** -- ``min(x_i)`` / ``max(x_i)``, the
  player's single worst and best qualifying game. Single observations, not
  estimated quantiles, and the most sample-size-sensitive columns here.
- **boom_games** / **bust_games** -- counts of qualifying games with
  ``x_i > points_per_game + k * stdev_points`` /
  ``x_i < points_per_game - k * stdev_points``.
- **boom_pct** / **bust_pct** -- ``boom_games / n`` / ``bust_games / n``.
  ``NaN`` when ``n < MIN_GAMES_FOR_BOOM_BUST``.

Every formula, the population-vs-sample choice, the self-referential (not
league-relative) boom/bust convention, the strict-inequality rule, and the
``n < 2`` / ``n < 3`` small-sample proofs are identical in substance to
``consistency.py``'s -- see that module's docstring for the full derivations
(including the floating-point argument for why two-observation boom/bust
classification is provably data-independent). They are not repeated at that
depth here to avoid the two docstrings silently drifting out of sync; this
one restates only the parts that differ.

What counts as a "game played" -- the one place this ticket truly diverges
from ``consistency.py``
----------------------------------------------------------------------------

This is the central design decision of this module, so it is stated first
and plainly: **a week counts as a game played only if the player has at
least one non-null provider raw-stat value for that week; being merely
rostered is not enough.**

FFA-064's own row universe is *rostered* players, not *played* players: a
player who was on a roster during a bye week, or who was inactive, or whom
the provider simply had no data for, still gets a full row in
``player_week_df`` with every raw stat column ``NaN`` and
``fantasy_points = 0.0`` by construction (see
:mod:`fantasy_analyzer.players.player_week`'s module docstring). That is the
right design for a roster/lineup-context table -- FFA-067's future
roster-efficiency work needs to see "this bench spot held a rostered player
who scored zero" as distinct from "this bench spot was empty" -- but it is
the wrong denominator for *this* table's question, which is about a
player's own on-field production, independent of any one fantasy manager's
roster.

If this module instead treated every rostered player-week as a "game" the
way ``consistency.py`` treats every roster-week as a game (a defensible
reading at the team level, where every roster-week has a real, if sometimes
zero, matchup score), a player rostered for a full 17-week season who
actually played 10 of them would have his ``points_per_game`` diluted by
seven artificial zero-point "games" that describe his fantasy manager's roster
decisions, not his football. Worse, those artificial zeros would drag down
``scoring_floor`` toward (or to) zero for essentially every rostered player
in the league, since almost every player has at least one bye week, and
would inflate ``stdev_points``/``cv`` with variance that has nothing to do
with week-to-week performance volatility. The metric would stop answering
"how good and how consistent is this player when he plays" and start
answering "how much of the season was he on a roster and active," which is
a different, much less useful question.

The chosen rule -- at least one raw stat column non-null -- is deliberately
based on the *raw* stat columns (whatever the configured provider supplied,
e.g. nflverse's ``passing_yards``/``receptions``/...), not on
``fantasy_points``. ``fantasy_points`` cannot be used for this test: it is
``0.0`` for both "played and produced nothing fantasy-relevant" (a real,
countable game -- e.g. a WR targeted zero times but active and on the field)
and "did not play at all" (not a game). The raw stat columns do not have
that ambiguity: a provider that has *any* data for a player-week -- even a
row of real zeros -- is asserting the player was in its data for that week,
which this module treats as evidence of a played game; a provider with *no*
row for that player-week (surfaced here as every raw stat column being
``NaN``) is asserting nothing, which this module treats as no game.

This module identifies the raw stat columns generically, as every
``player_week_df`` column that is neither one of
:data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS` nor
``fantasy_points`` -- it does not hard-code a provider's specific column
names (e.g. nflverse's), matching FFA-064's own provider-agnostic column
handling. If a ``player_week_df`` has **zero** such columns (e.g. a
minimal hand-built test fixture with no stat columns at all), no week can
ever qualify as played under this rule, and every player is therefore
excluded from the output by decision "A player with zero qualifying games
gets no row" below -- a documented degenerate case, not a silent wrong
answer.

Started vs. bench weeks: both count, on purpose
-----------------------------------------------------

Every qualifying game -- whether the player was started or benched that
week -- is included in the distribution; ``started``/``bench`` are not
filtered on at all here.

This is a deliberate choice among two reasonable readings. Filtering to
started weeks only would answer "how did this player perform in the games
his fantasy manager actually used him," which is a real question but a
*manager*-relative one, closer to FFA-070's future lineup-tendency work than
to a player's own value. This module instead answers the roster-independent
question: "how good was this player, period" -- which is what FFA-066
(positional strength across a whole position, not just started slots),
FFA-068 (replacement-level value, which must compare a bench player's true
output against a starter's, not just compare started-week output to
started-week output) and FFA-069 (which player drove a specific win, which
requires knowing what a benched alternative would have scored) all need as
their foundation. A player who was correctly benched for a bad matchup and
still qualifies as a "game played" under the rule above (the provider has
real stats for him) contributes that real performance to his distribution
regardless of his manager's decision that week.

Grouping key: ``(season, sleeper_player_id)`` -- seasons are never pooled
------------------------------------------------------------------------------

Output rows are grouped by ``(season, sleeper_player_id)``, not by
``sleeper_player_id`` alone. ``consistency.py`` documents, as a known and
debatable caveat, that pooling multiple seasons of one roster into a single
row inflates its dispersion columns with the between-season level shift.
That tradeoff is more clearly wrong here and is not repeated as this
module's default: a player's per-season role, offense, and health status can
change completely from one year to the next (a rookie-year committee back
who becomes a workhorse; and 2025 is this project's only validated season
regardless), and a table meant to feed FFA-066/067/068's *season-relative*
positional and replacement-value analysis must not silently blend two
different players' worth of context under one player's name. A caller who
genuinely wants a multi-season career view should pre-aggregate this
table's own season rows, not get that behavior baked in unrequested.

``player_name``, ``position`` and ``nfl_team`` can vary row-to-row for one
``(season, sleeper_player_id)`` group (a midseason trade changes
``nfl_team``; a rare in-season position switch could change ``position``; a
name field could differ by formatting between the provider join and the
Sleeper-catalog fallback in different weeks -- see
``player_week.py``'s "Identity enrichment order"). Each label column is
resolved independently per player as the **most frequent non-null value
across every row for that player that season** (all rows, not only
qualifying-game rows, since even a bye week's row still carries the
Sleeper-catalog identity fallback and is legitimate label evidence), with
ties broken by which value appeared **first** in the input. This is a
"majority vote, stable on ties" rule, not FFA-064's own "last non-null wins"
convention for a single row's fallback chain -- a different problem
(resolving one row's missing field) than this one (resolving one label from
many rows that may disagree). A player traded once mid-season plays more
weeks for his final team than a single week's ambiguity would suggest only
in the minority of cases (a trade in the season's final couple of weeks);
this module accepts that a near-even season-long split can, by design, side
with whichever team he was on first, and does not attempt to weight recency.

A player who never has a qualifying game gets no row
-----------------------------------------------------------

A ``(season, sleeper_player_id)`` group whose every week fails the
"qualifying game" test above -- rostered all season but on bye or otherwise
never in the provider's data -- gets **no row** in the output, not a row of
``NaN``/zero metrics.

This intentionally follows ``consistency.py``'s "zero games -> no row"
precedent rather than ``player_week.py``'s "still gets a row" precedent, and
the two upstream modules are not in tension: they answer different
questions at different grains. ``player_week.py`` is a roster/lineup-context
log, where a rostered-but-inactive player is itself the fact worth
recording (an occupied bench spot). This module is a distribution summary
of on-field performance; a distribution over zero observations is
undefined, not "empty but real," and emitting a row of ``NaN`` metrics for a
player who never played would invite a reader to mistake "no data" for "we
looked and found nothing," and would pollute any later positional-average
computation (FFA-066) with a phantom row that must be filtered back out
before use. Leaving the row out entirely means every row this module does
emit has ``games_played >= 1``, so ``total_points``, ``points_per_game``,
``median_points``, ``scoring_floor`` and ``scoring_ceiling`` are always
defined; only the dispersion and boom/bust columns can be ``NaN``.

Boom and bust: reused, self-referential threshold
--------------------------------------------------------

Identical convention to ``consistency.py``: a boom game is one where the
player scored more than ``k`` of his own season standard deviations above
his own season mean; a bust game, more than ``k`` below. The default
``k`` is :data:`BOOM_BUST_THRESHOLD_STDEVS` = ``1.0``, for the identical
reasoning ``consistency.py`` gives (the smallest round z-score that keeps
useful resolution over a season's worth of games without pushing most
players to zero booms) -- not re-derived here. ``boom_bust_threshold`` is a
parameter for the same reason: no threshold is canonical, and a caller who
picks a different ``k`` should be able to without forking the metric.

Small samples: when dispersion and boom/bust are undefined
-------------------------------------------------------------

Two minimum game counts apply, both reused verbatim from ``consistency.py``
because the underlying proofs are about the arithmetic of ``n`` observations
and do not depend on whether those observations are roster-weeks or
player-games:

- ``games_played < MIN_GAMES_FOR_DISPERSION`` (2) -> ``stdev_points`` and
  ``cv`` are ``NaN``. A single game has no spread; reporting ``0.0`` would
  put a player with exactly one loaded game at the top of a "most
  consistent" sort, indistinguishable from a player who was genuinely
  steady across a full season.
- ``games_played < MIN_GAMES_FOR_BOOM_BUST`` (3) -> the four boom/bust
  columns are ``NaN``. At ``n = 2`` the classification is provably
  independent of the actual scores (the higher score sits at *exactly* one
  population standard deviation above the mean for every possible pair),
  so it would be a restatement of ``k``, not an observation about the
  player. See ``consistency.py``'s docstring for the full algebraic and
  floating-point argument; it applies here unchanged.

A note specific to this table's typical sample sizes: for a bye-week league
schedule (17 NFL weeks, one league-wide bye per team spread across the
season) a full-season "every game" player still tops out around
``games_played = 17``, and a committee back, a rookie who was inactive early,
or anyone who missed time to injury will have noticeably fewer qualifying
games than that. Treat ``boom_pct``/``bust_pct`` here with the same
"coarse shape descriptor, not a precise volatility measure" skepticism
``consistency.py`` documents for team-level boom/bust, and expect it to be
even coarser for part-season players.

Coefficient of variation, "where appropriate"
-----------------------------------------------

Same rule as ``consistency.py``: ``cv`` is reported only when
``points_per_game > 0``, and is ``NaN`` for a zero or negative mean (the
latter is unreachable for a real fantasy scoring system with no negative
per-category weights, but is guarded against anyway rather than emitted as
an uninterpretable negative ratio).

Regular season vs. playoffs: this table is phase-agnostic
------------------------------------------------------------

``player_week_df`` (FFA-064's output) has no ``is_playoff`` column at all --
unlike the matchup-derived analytics frames (``season_matchup_df``,
``weekly_scoring_ranks_df``), it is built directly from NFL weeks and a
league's rostered players, with no notion of that particular league's
playoff schedule. This module therefore makes no phase distinction of its
own and cannot: every week present in the input for a player enters the same
distribution, regular season and playoff weeks alike.

A caller wanting a phase-specific view (e.g. "how did this player perform
excluding playoff weeks") must pre-filter ``player_week_df`` on ``week``
against the calling league's playoff-start boundary (see FFA-022,
``LeagueSettings.playoff_week_start``) **before** calling this function --
the same caller-filters-first pattern ``consistency.py`` documents for
``is_playoff``. Note that filtering to only regular-season weeks will
usually leave *more* qualifying games than a matchup-based filter would for
the same player, since a bench player's team may still have provider data
for playoff weeks even if his own fantasy team was eliminated and stopped
using him.

Missing values / edge cases
----------------------------

- **Empty ``player_week_df``**: returns an empty DataFrame with
  :data:`PLAYER_PERFORMANCE_COLUMNS`.
- **A ``player_week_df`` with no raw stat columns at all** (every column is
  one of ``PLAYER_WEEK_COLUMNS`` or ``fantasy_points``): no week can ever
  qualify as played (see "What counts as a game played" above), so every
  player has zero qualifying games and the result is an empty (but
  correctly-shaped) frame -- not an error.
- **A row with a missing ``season`` or ``sleeper_player_id``**: FFA-064
  never emits one (``season`` is always a resolved ``int`` and
  ``sleeper_player_id`` is always the roster's own player id), but if a
  hand-built input contains one, that row cannot be assigned to a group and
  is skipped entirely, contributing to no player's distribution and no
  player's label resolution.
- **A qualifying game with a missing ``fantasy_points``**: not expected
  under FFA-064's contract (``fantasy_points`` is always a defined float,
  ``0.0`` at worst), so this module does not defend deeply against it; a row
  that is both "played" (has raw stat data) and has ``NaN``
  ``fantasy_points`` is skipped from that player's point distribution (it
  cannot be averaged, floored, or ceilinged) but still contributes to label
  resolution.
- **A zero-variance player** (``n >= 2``, identical score every qualifying
  game): reports ``stdev_points = 0.0`` and ``cv = 0.0`` (a genuine value,
  unlike the one-game case), with ``scoring_floor == scoring_ceiling ==
  points_per_game == median_points``, and zero booms/busts with no special
  casing -- strict inequality against a threshold equal to the mean is false
  for every game.
- **Duplicate weekly scores** within a player's season need no special
  handling: ``median_points`` sorts and takes the middle position(s) of the
  multiset, and ``scoring_floor``/``scoring_ceiling`` are a plain min/max,
  both well-defined with repeats.
- **Multiple players sharing a name**: irrelevant to this module, which
  groups by ``sleeper_player_id`` (an immutable Sleeper id), never by
  ``player_name``.

Column dtypes
--------------

Every metric column is ``float64`` and every undefined value is ``NaN``,
including ``boom_games`` and ``bust_games`` (whole numbers carried as
floats, cast explicitly so the dtype does not silently change between calls
depending on whether some player happened to fall below the minimum game
counts). ``games_played`` and ``season`` are plain ``int64`` (never
undefined for a row that exists). ``sleeper_player_id``, ``player_name``,
``position`` and ``nfl_team`` are ``object`` (a label may legitimately be
``None`` if a player was never resolved by either identity source -- see
``player_week.py``'s "Identity enrichment order"). Test undefined values
with ``pd.isna``, not ``is None``.
"""

from __future__ import annotations

import math
from statistics import fmean, median, pstdev
from typing import Any, Optional

import pandas as pd

from fantasy_analyzer.players.player_week import PLAYER_WEEK_COLUMNS

#: Column order for the DataFrame returned by
#: :func:`build_player_performance_metrics`.
PLAYER_PERFORMANCE_COLUMNS = [
    "season",
    "sleeper_player_id",
    "player_name",
    "position",
    "nfl_team",
    "games_played",
    "total_points",
    "points_per_game",
    "median_points",
    "stdev_points",
    "cv",
    "scoring_floor",
    "scoring_ceiling",
    "boom_games",
    "boom_pct",
    "bust_games",
    "bust_pct",
]

#: Default boom/bust threshold, in the player's own standard deviations.
#: Reuses ``consistency.py``'s convention and default value -- see the
#: module docstring's "Boom and bust" section.
BOOM_BUST_THRESHOLD_STDEVS = 1.0

#: Fewest qualifying games for which ``stdev_points``/``cv`` are defined. See
#: "Small samples" in the module docstring.
MIN_GAMES_FOR_DISPERSION = 2

#: Fewest qualifying games for which the boom/bust columns are defined. See
#: "Small samples" in the module docstring.
MIN_GAMES_FOR_BOOM_BUST = 3

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
    "boom_games",
    "boom_pct",
    "bust_games",
    "bust_pct",
]

#: Player-identity label columns resolved by majority vote across a
#: player-season's rows -- see the module docstring's "Grouping key" section.
_LABEL_COLUMNS = ["player_name", "position", "nfl_team"]


def _stat_columns(player_week_df: pd.DataFrame) -> list[str]:
    """The raw provider stat columns present in ``player_week_df``.

    Every column that is neither one of ``PLAYER_WEEK_COLUMNS`` nor
    ``fantasy_points`` -- generic across providers, per the module
    docstring's "What counts as a game played" section.
    """
    excluded = set(PLAYER_WEEK_COLUMNS) | {"fantasy_points"}
    return [column for column in player_week_df.columns if column not in excluded]


def _majority_label(values: list[Any]) -> Optional[Any]:
    """The most frequent non-null value in ``values``, ties broken by first
    occurrence.

    See the module docstring's "Grouping key" section: this resolves one
    label (``player_name``/``position``/``nfl_team``) from many rows that
    may legitimately disagree (e.g. a midseason trade), and is a different
    problem from FFA-064's own per-row "provider first, Sleeper catalog
    fallback" resolution.
    """
    counts: dict[Any, int] = {}
    first_seen: dict[Any, int] = {}
    for index, value in enumerate(values):
        if pd.isna(value):
            continue
        if value not in counts:
            counts[value] = 0
            first_seen[value] = index
        counts[value] += 1

    if not counts:
        return None

    # Highest count wins; ties broken by earliest first occurrence (smallest
    # first_seen index), hence the negation for max().
    return max(counts, key=lambda value: (counts[value], -first_seen[value]))


def _summarize_player(points: list[float], boom_bust_threshold: float) -> dict:
    """Summarize one player-season's qualifying-game fantasy points.

    Applies the exact definitions in the module docstring: population
    standard deviation, a mean-relative boom/bust threshold measured in that
    standard deviation, and the ``MIN_GAMES_FOR_DISPERSION`` /
    ``MIN_GAMES_FOR_BOOM_BUST`` minimums below which the corresponding
    columns are ``None`` (rendered as ``NaN`` in the returned frame).
    """
    games_played = len(points)
    points_per_game = fmean(points)

    # Population standard deviation (ddof = 0), reusing consistency.py's
    # choice and reasoning -- see the module docstring.
    stdev_points: Optional[float] = (
        pstdev(points) if games_played >= MIN_GAMES_FOR_DISPERSION else None
    )

    cv: Optional[float] = (
        stdev_points / points_per_game
        if stdev_points is not None and points_per_game > 0
        else None
    )

    boom_games: Optional[int] = None
    bust_games: Optional[int] = None
    boom_pct: Optional[float] = None
    bust_pct: Optional[float] = None

    if games_played >= MIN_GAMES_FOR_BOOM_BUST and stdev_points is not None:
        boom_threshold = points_per_game + boom_bust_threshold * stdev_points
        bust_threshold = points_per_game - boom_bust_threshold * stdev_points
        # Strict inequality: with ``>=`` a zero-variance player would have
        # every game counted as both a boom and a bust.
        boom_games = sum(1 for value in points if value > boom_threshold)
        bust_games = sum(1 for value in points if value < bust_threshold)
        boom_pct = boom_games / games_played
        bust_pct = bust_games / games_played

    return {
        "games_played": games_played,
        "total_points": math.fsum(points),
        "points_per_game": points_per_game,
        "median_points": median(points),
        "stdev_points": stdev_points,
        "cv": cv,
        "scoring_floor": min(points),
        "scoring_ceiling": max(points),
        "boom_games": boom_games,
        "boom_pct": boom_pct,
        "bust_games": bust_games,
        "bust_pct": bust_pct,
    }


def build_player_performance_metrics(
    player_week_df: pd.DataFrame,
    boom_bust_threshold: float = BOOM_BUST_THRESHOLD_STDEVS,
) -> pd.DataFrame:
    """Build one row per player-season describing his fantasy scoring distribution.

    Collapses each ``(season, sleeper_player_id)``'s qualifying-game
    ``fantasy_points`` into volume (``total_points``), center
    (``points_per_game``, ``median_points``), spread (``stdev_points``,
    ``cv``), extremes (``scoring_floor``, ``scoring_ceiling``) and
    self-relative outlier frequency (``boom_games``/``boom_pct``,
    ``bust_games``/``bust_pct``). See the module docstring for the exact
    formulas, the "what counts as a game played" rule (the key place this
    diverges from FFA-053's team-level consistency metrics), why started and
    benched games are both included, why seasons are never pooled, how
    ``player_name``/``position``/``nfl_team`` are resolved when they vary
    row-to-row, why a player with zero qualifying games gets no row, the
    boom/bust convention, and the minimum game counts below which columns
    are ``NaN``.

    Args:
        player_week_df: A
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            DataFrame (plus provider raw-stat columns and ``fantasy_points``
            last), as produced by
            :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`.
            Every column other than ``PLAYER_WEEK_COLUMNS`` and
            ``fantasy_points`` is treated as a raw provider stat column for
            the "game played" test. This function is phase-agnostic (see the
            module docstring); filter on ``week`` against a league's
            playoff-start boundary before calling for a phase-specific view.
        boom_bust_threshold: How many of a player's own standard deviations a
            game must exceed to count as a boom or a bust. Defaults to
            :data:`BOOM_BUST_THRESHOLD_STDEVS` (``1.0``), a documented
            convention rather than a standard -- see
            ``consistency.py``'s identical parameter.

    Returns:
        A DataFrame with columns :data:`PLAYER_PERFORMANCE_COLUMNS`, one row
        per ``(season, sleeper_player_id)`` with at least one qualifying
        game in the input, sorted by ascending ``season`` then
        ``sleeper_player_id`` (a deterministic display order; this frame has
        no rank column, matching ``consistency.py``'s "no single 'better'
        direction" reasoning). ``stdev_points`` and ``cv`` are ``NaN`` for a
        player with fewer than :data:`MIN_GAMES_FOR_DISPERSION` qualifying
        games, and the four boom/bust columns are ``NaN`` for a player with
        fewer than :data:`MIN_GAMES_FOR_BOOM_BUST`; ``cv`` is also ``NaN``
        when ``points_per_game <= 0``. Returns an empty DataFrame with the
        expected columns if the input is empty or no player has a
        qualifying game.

    Raises:
        ValueError: If ``boom_bust_threshold`` is negative, which would make
            the boom and bust bands overlap and let a single game count as
            both.
    """
    if boom_bust_threshold < 0:
        raise ValueError(
            "boom_bust_threshold must be non-negative, got "
            f"{boom_bust_threshold!r} -- a negative threshold would put the "
            "boom band below the bust band and classify games as both"
        )

    if player_week_df.empty:
        return pd.DataFrame(columns=PLAYER_PERFORMANCE_COLUMNS)

    stat_columns = _stat_columns(player_week_df)

    # A row "played" a game only if at least one raw stat column is
    # non-null -- see the module docstring's "What counts as a game played"
    # section. With no stat columns at all (a degenerate input), no row can
    # ever qualify.
    if stat_columns:
        played_mask = player_week_df[stat_columns].notna().any(axis=1)
    else:
        played_mask = pd.Series(False, index=player_week_df.index)

    groups: dict[tuple[int, Any], dict[str, list]] = {}

    for row, played in zip(
        player_week_df.itertuples(index=False), played_mask, strict=True
    ):
        if pd.isna(row.season) or pd.isna(row.sleeper_player_id):
            # Cannot be assigned to a group; see the module docstring's
            # "Missing values / edge cases" section.
            continue

        key = (int(row.season), row.sleeper_player_id)
        bucket = groups.setdefault(
            key,
            {"points": [], "player_name": [], "position": [], "nfl_team": []},
        )
        # Label evidence is collected from every row, played or not -- even
        # a bye week's row carries a legitimate identity fallback.
        bucket["player_name"].append(getattr(row, "player_name", None))
        bucket["position"].append(getattr(row, "position", None))
        bucket["nfl_team"].append(getattr(row, "nfl_team", None))

        if not played:
            continue

        points = row.fantasy_points
        if pd.isna(points):
            # Not expected under FFA-064's contract; skipped defensively
            # rather than corrupting the distribution with a NaN.
            continue
        bucket["points"].append(float(points))

    rows: list[dict] = []
    for (season, player_id), bucket in sorted(
        groups.items(), key=lambda item: (item[0][0], str(item[0][1]))
    ):
        points = bucket["points"]
        if not points:
            # No qualifying game -> no row at all, see the module
            # docstring's "A player who never has a qualifying game" section.
            continue

        summary = _summarize_player(points, boom_bust_threshold)
        summary["season"] = season
        summary["sleeper_player_id"] = player_id
        for label_column in _LABEL_COLUMNS:
            summary[label_column] = _majority_label(bucket[label_column])
        rows.append(summary)

    if not rows:
        return pd.DataFrame(columns=PLAYER_PERFORMANCE_COLUMNS)

    result = pd.DataFrame(rows)
    result["season"] = result["season"].astype(int)
    result["games_played"] = result["games_played"].astype(int)
    # Cast explicitly so an undefined value is always NaN in a float64
    # column -- see the module docstring's "Column dtypes".
    for column in _FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    # Assigned as explicit object-dtype Series, mirroring consistency.py's
    # ``owner`` handling: pandas' string-dtype inference would otherwise
    # upcast a column mixing real labels with ``None`` into a dtype that
    # silently turns ``None`` into ``NaN``.
    result["sleeper_player_id"] = pd.Series(
        result["sleeper_player_id"].tolist(), dtype=object
    )
    for label_column in _LABEL_COLUMNS:
        result[label_column] = pd.Series(
            result[label_column].tolist(), dtype=object
        )

    return result[PLAYER_PERFORMANCE_COLUMNS]
