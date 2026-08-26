"""League-wide composite player value rankings (FFA-073).

FFA-068's :func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`
already ranks every player in a league-season against every other player --
its ``value_rank`` is standard competition ranking on
``points_above_replacement`` -- but it does so on **one signal**, and that
signal is a season total. Everything that follows from that is a known,
documented limitation of a single-signal ranking:

- **It is volume-driven.** ``points_above_replacement`` is
  ``total_points - replacement_ppg * games_played``, so a seventeen-game
  compiler who is barely better than a waiver pickup outranks a nine-game
  elite producer whose per-game edge is three times as large. Both readings
  are legitimate -- one asks "who banked the most surplus points," the
  other "who was the best player" -- and FFA-068 answers only the first.
- **It is blind to shape.** A metronome and a boom/bust player with
  identical season totals get identical ranks, even though FFA-065 already
  measured the difference (``cv``, ``scoring_floor``/``scoring_ceiling``).
- **It does not regularize small samples.** A two-game cameo at +10 points
  per game above replacement is reported at face value, with no shrinkage
  toward the baseline that a two-game sample deserves.
- **It prices positional thinness exactly once.** Subtracting
  ``replacement_ppg`` embeds scarcity in the units, which is correct for a
  realized-points question but understates the draft-capital intuition that
  a league-winning TE is worth more than the same VORP compiled at a deep
  position.

This module adds a **configurable multi-signal blend** on top of that
output. It answers a different question from FFA-068's -- "given everything
this codebase already measured about this player, where does he rank in the
league on a blend I can tune?" -- and it deliberately keeps FFA-068's
single-signal answer available and unchanged alongside it.

This module **recomputes nothing**. It calls
:func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`
and
:func:`~fantasy_analyzer.players.player_value.build_position_scarcity_metrics`
and reads their output, exactly as ``player_value.py`` itself reads
FFA-065's output without recomputing it: no replacement level, no VORP, no
positional field size, no ``cv``, and no ``scoring_ceiling`` is derived
here. The two columns this module reads directly from ``performance_df``
(``cv`` and ``scoring_ceiling``) are FFA-065's own values, carried through
verbatim. It performs no network access and makes no provider-specific
assumptions.

Like every FFA-06x sibling, this module is designed to be called on a
``performance_df`` scoped to **one league-season at a time**: replacement
levels, scarcity ratios, and every z-score below are computed from whatever
player pool the caller passes in, so a frame spanning two leagues in the
same season would blend their pools into one baseline and one z-score
scale. That is not supported -- see FFA-068's identical note.

The composite: five components, one weighted blend
--------------------------------------------------------------------------

Every component is a **z-score across all qualifying players within a
season** -- not within position. For each component the mean and standard
deviation are taken over the players in that season for whom the component
is defined, and the standard deviation is the **population** standard
deviation (``ddof = 0``), matching ``performance.py``, ``consistency.py``
and ``power_rankings.py``: the players in the frame are not a sample of a
wider hypothetical league, they are the complete league.

Cross-position pooling is legal here, and this is the reason: four of the
five components are already **replacement-relative**, i.e. already
expressed in units of "better than a freely available player at the same
position." ``points_above_replacement``, ``ppg_above_replacement`` and
``scoring_ceiling - replacement_ppg`` all subtract the position's own
baseline before the pooling happens, and ``scarcity_ratio`` is a
dimensionless ratio. Only ``cv`` is not baseline-adjusted, and ``cv`` is
already normalized by the player's own scoring level (it is
``stdev_points / points_per_game``), so it too is comparable across a QB
and a TE. Pooling raw ``points_per_game`` across positions would be
indefensible -- a 20-ppg QB and a 20-ppg TE are not the same player -- and
this module never does that.

+-------------------+---------------------------------------------+---------------+
| Component column  | Definition                                  | Weight field  |
+===================+=============================================+===============+
| ``z_value``       | ``z(points_above_replacement)``             | ``value``     |
+-------------------+---------------------------------------------+---------------+
| ``z_rate``        | ``z(shrunk_ppg_above_replacement)``         | ``rate``      |
+-------------------+---------------------------------------------+---------------+
| ``z_reliability`` | ``z(-cv)`` -- lower volatility ranks higher |``reliability``|
+-------------------+---------------------------------------------+---------------+
| ``z_upside``      | ``z(scoring_ceiling - replacement_ppg)``    | ``upside``    |
+-------------------+---------------------------------------------+---------------+
| ``z_scarcity``    | ``z(scarcity_ratio)``, broadcast onto each  | ``scarcity``  |
|                   | player from his position's row              |               |
+-------------------+---------------------------------------------+---------------+

and

    ``ranking_score = sum(w_c * z_c) / sum(w_c)``

over the components ``c`` that are **available for that player** (see
"Missing components" below). The default weights --
:data:`DEFAULT_RANKING_WEIGHTS`, i.e. ``value 0.40, rate 0.25,
reliability 0.15, upside 0.10, scarcity 0.10`` -- sum to exactly 1.0, so
for a player with all five components the denominator is 1.0 and
``ranking_score`` is a plain weighted sum. Weights are **not required** to
sum to 1.0: they are renormalized by the denominator above, so
``RankingWeights(value=2.0, rate=1.0)`` is exactly
``RankingWeights(value=2/3, rate=1/3)``. Every weight must be non-negative
and they must not all be zero (:class:`RankingWeights` raises ``ValueError``
otherwise) -- a negative weight would silently invert a component's meaning,
and an all-zero weight vector has no defined normalization.

The three columns the components are built from that FFA-068 does not emit
-- ``cv``, ``scoring_ceiling``, and ``scarcity_ratio`` -- are carried into
the output frame **in their original (un-negated, un-shifted) form**, so a
reader can check ``z_reliability`` against ``cv`` and ``z_upside`` against
``scoring_ceiling - replacement_ppg`` without re-deriving anything.

Why these five, and why these defaults
--------------------------------------------------------------------------

The weights are an opinion, not a fitted model, and this module does not
pretend otherwise: nothing here was estimated from data, backtested, or
validated against a holdout. They are documented, named, and overridable
for exactly the reason ``power_rankings.py``'s three weights are:

- **value (0.40)** -- the largest single weight, because banked surplus
  points is the least assumption-laden thing this codebase measures, and
  because it is the one component that carries volume information at all.
- **rate (0.25)** -- the games-neutral companion to ``value``, shrunk (see
  below) so a tiny sample cannot dominate. Together, value and rate hold
  0.65 of the blend: the composite is still primarily a scoring-production
  ranking.
- **reliability (0.15)** -- week-to-week volatility relative to the
  player's own level. Third-largest because a fantasy manager starts a
  player one week at a time, so distribution shape has real decision value,
  but it is a second-order effect next to how much he scored.
- **upside (0.10)** -- the single best game above the position baseline.
  Small, because ``scoring_ceiling`` is a single observation and is the
  most sample-size-sensitive column FFA-065 emits (see that module's
  docstring).
- **scarcity (0.10)** -- see the honest accounting immediately below.

Scarcity is deliberately double-counted -- read this before using it
--------------------------------------------------------------------------

``scarcity`` is weighted **on by default at 0.10**, and that default
**double-counts positional thinness**. This is stated plainly rather than
buried, because it is the one place where this module's output is not a
pure measure of realized points:

Subtracting ``replacement_ppg`` already prices scarcity once. That is the
entire reason a TE scoring 11 ppg against a 6 ppg TE baseline can outrank a
QB scoring 22 ppg against a 19 ppg QB baseline: the thin position's low
baseline is what makes the TE's surplus large. ``z_scarcity`` then prices
the same thinness a **second** time, by adding a per-position bonus
proportional to how far the position's best player is above its own
replacement level. The visible effect is that elite players at thin
positions move up the board -- and, because ``scarcity_ratio`` is a
property of the *position*, so does every other player at that position,
including its replacement-level players.

That is a deliberate opinion about **draft-capital value** (what it costs
to acquire this kind of production, given how few sources of it exist)
rather than a measurement of realized points. If you want the undistorted
replacement-relative reading, pass ``RankingWeights(scarcity=0.0)``: the
scarcity component is then dropped from every player's blend, the surviving
weights renormalize, and ``components_used`` reports 4 instead of 5. This
default was an explicit product decision; the tradeoff is documented here
so no caller is surprised by it.

Small-sample shrinkage on the rate component
--------------------------------------------------------------------------

``ppg_above_replacement`` (FFA-068's rate VORP) is unregularized: a player
with two qualifying games and a +10.0 ppg edge is reported at +10.0, the
same as a sixteen-game player at +10.0, even though the two-game figure is
mostly noise. The rate component therefore uses a shrunk version:

    ``shrunk_ppg_above_replacement = n * ppg_above_replacement / (n + k)``

where ``n`` is ``games_played`` and ``k`` is ``rate_shrinkage_games``
(default :data:`DEFAULT_RATE_SHRINKAGE_GAMES`, 4.0). This is the standard
"add ``k`` games of prior" estimator, and the prior it shrinks toward is
**zero, i.e. exactly replacement level** -- the correct prior for a player
this league has barely observed, since replacement level is by definition
what the league could have had for free instead of him.

Worked example, ``n = 2``, ``ppg_above_replacement = +10.0``, ``k = 4``::

    2 * 10.0 / (2 + 4) = 20.0 / 6 = 3.3333...

so a two-game +10.0 cameo enters the blend as +3.33, while a sixteen-game
+10.0 season enters as ``16 * 10 / 20 = +8.0``, and the same player at
``n = 36`` (a full pooled two-season frame) would enter at ``+9.0``. The
shrinkage never changes a sign and never crosses zero: it is a positive
multiplier ``n / (n + k)`` in ``[0, 1)``.

``k`` is a parameter, not a constant, because the right prior strength
depends on the frame: for a single 17-week season 4 games is roughly a
quarter of the schedule, but a caller analyzing a 6-week playoff-only slice
may want less. ``k = 0`` disables shrinkage **exactly** -- the formula
degenerates to ``n * x / n = x``, the raw ``ppg_above_replacement`` -- so
there is no separate "off" switch to keep in sync. A negative
``rate_shrinkage_games`` raises ``ValueError`` (it would inflate small
samples, the exact opposite of the intent, and can divide by zero at
``n = -k``).

Missing components: dropped and renormalized, never zero-filled
--------------------------------------------------------------------------

Components are legitimately undefined for real players:

- ``cv`` is ``NaN`` below
  :data:`~fantasy_analyzer.players.performance.MIN_GAMES_FOR_DISPERSION`
  (2) qualifying games, and also when ``points_per_game <= 0``.
- ``scoring_ceiling`` is always defined under FFA-065's contract, but a
  hand-built frame may omit it.
- ``scarcity_ratio`` is ``NaN`` when the position's ``replacement_ppg`` is
  ``<= 0`` (a non-positive denominator has no percentage meaning -- see
  FFA-068).
- **Any** component whose population standard deviation over the season
  pool is 0, or which has fewer than two usable values in the pool, is
  undefined for *every* player in that season: a single-player frame, or a
  league where every player has the identical ``cv``, gives that component
  no scale to measure against. Such a component is set to ``NaN`` for the
  whole season rather than dividing by zero; the builder never raises and
  never emits ``inf``.

When a component is missing for a player, it is **dropped from that
player's blend and the surviving weights are renormalized to sum to 1.0**
(the ``/ sum(w_c)`` denominator above). It is *not* zero-filled. This is a
deliberate divergence from ``power_rankings.py``, which substitutes ``0.0``
for a zero-variance feature: zero on a z-scale is not "no information," it
is the specific claim "this player is exactly league average on this
component," and asserting a measurement nobody made would quietly drag
every affected player toward the middle of the board. Dropping the
component instead says only what is true -- we could not measure this --
and renormalizing keeps the composite on a comparable scale, so a player
scored on four components is still directly comparable to one scored on
five.

``components_used`` reports how many of the five components actually
entered a player's ``ranking_score``: a component counts only if it has a
usable z-score **and** a strictly positive weight. A zero-weighted
component contributes nothing to the numerator or the denominator, so it is
not "used" -- with ``RankingWeights(scarcity=0.0)`` a fully-observed player
reports ``components_used = 4``. Note the distinction between a component
that is *unused* and one that is used with a z-score of ``0.0``: the latter
counts, because "exactly league average" is a measurement.

A player with **zero** usable components (every component missing, or every
component with a usable z-score carrying zero weight) has
``ranking_score = NaN``, ``components_used = 0``, and sorts last. Because
:class:`RankingWeights` forbids an all-zero weight vector, this can only
happen when the data, not the configuration, is degenerate.

Ranks, ties, and percentile
--------------------------------------------------------------------------

- **league_rank** -- standard competition ("1224") ranking by **descending**
  ``ranking_score`` within ``season``, across all positions: the identical
  convention ``standings.py``'s ``scoring_rank``,
  ``position_strength.py``'s ``positional_rank`` and ``player_value.py``'s
  ``value_rank`` use. Tied players share a rank and the next distinct rank
  skips the number of tied players. Ties are judged on ``ranking_score``
  **rounded to 6 decimal places**, matching ``player_value.py``'s
  documented float-noise convention: 6 decimals is far below any meaningful
  resolution of a z-blend and far above the floating-point noise that
  ``(x - mean) / stdev`` arithmetic accumulates, so two players who are
  mathematically tied cannot be split by rounding. Display order within a
  tie is ascending ``sleeper_player_id``.
- **Players with ``NaN`` ranking_score** sort last within their season and
  receive ``NaN`` ``league_rank`` and ``NaN`` ``position_rank`` -- not a
  numeric rank. Assigning a rank to a player nobody could score would be a
  claim this module cannot support; ``NaN`` says exactly what happened. This
  is why the two rank columns are ``float64`` here while
  ``player_value.py``'s ``value_rank`` is ``int64`` (see "Column dtypes").
- **position_rank** -- the identical rule applied within
  ``(season, position)``: rank 1 is the best player at that position in
  that season by ``ranking_score``.
- **league_percentile** -- ``1 - (league_rank - 1) / n_ranked``, where
  ``n_ranked`` is the number of players in that season with a non-``NaN``
  ``ranking_score`` (unscored players are excluded from both the numerator
  and the denominator). The best player scores exactly ``1.0``; the worst
  scores ``1 / n_ranked``; the scale is therefore ``(0, 1]``, never 0.
  Tied players share a ``league_rank`` and so share the *higher* (more
  favorable) percentile of the tie group -- e.g. two players tied at rank 1
  in a 10-player league both score 1.0, and the next player, at rank 3,
  scores 0.8. Read it as "this player is at or above this fraction of the
  scored league," not as a rank-order quantile. ``NaN`` for an unscored
  player.

Two modes
--------------------------------------------------------------------------

``mode="retrospective"`` (the default) is everything described above: a
backward-looking ranking of what players actually did in the weeks the
caller's ``performance_df`` covers.

``mode="projected"`` **raises** :class:`NotImplementedError`. The parameter
and the ``projections_df`` seam ship now so that the public signature is
stable and a future ticket can fill in the branch without breaking callers.
What that branch will eventually do is specified here so it is not
re-litigated later:

1. Aggregate a :class:`~fantasy_analyzer.players.projections.ProjectionProvider`'s
   ``projections(season, week)`` output across the remaining weeks of the
   season into projected season totals per player (the same "call it per
   week and concatenate" pattern FFA-072's docstring describes for
   rest-of-season rankings), or accept an already-aggregated frame via
   ``projections_df``.
2. Run the **identical** pipeline on those projected totals: replacement
   level -> component z-scores -> weighted blend -> ranks. Nothing about
   the methodology above changes; only the source of ``games_played``,
   ``points_per_game`` and ``total_points`` changes.

This module deliberately does **not** invent the projection methodology
that step 1 requires -- how to combine weekly projections, how to handle
players a provider does not project, how to weight projected-future against
realized-past production. FFA-072 explicitly defers all of that, and
inventing it here would violate that ticket's stated boundary. Any ``mode``
value other than the two in :data:`RANKING_MODES` raises ``ValueError``.

Regular season vs. playoffs: this module is phase-agnostic
--------------------------------------------------------------------------

``performance_df`` (FFA-065's output) has no ``is_playoff`` column, and
neither does FFA-064's ``player_week_df`` beneath it, so this module makes
no phase distinction and cannot: every week that entered the input frame
enters the replacement baselines, the z-score pools, and the blend alike.

A caller who wants a phase-specific ranking must pre-filter
``player_week_df`` on ``week`` against the league's playoff boundary
(FFA-022, ``LeagueSettings.playoff_week_start``) **before** calling FFA-065,
so the frame passed here already reflects the desired phase -- the same
caller-filters-first pattern ``performance.py``, ``position_strength.py``,
``lineup_efficiency.py`` and ``player_value.py`` all document. Note that
including playoff weeks shifts the replacement baselines, every VORP, and
therefore every z-score in the pool together.

Rostered-only caveat
--------------------------------------------------------------------------

Inherited verbatim from FFA-068 and not restated in full here: FFA-064's
row universe is **rostered** players, so free agents are invisible to the
replacement computation, and in a position the league under-rosters the
baseline clamps to the worst rostered player and can overstate VORP. Every
component except ``z_reliability`` is built on that baseline, so the caveat
propagates into ``ranking_score`` unchanged -- see
:mod:`fantasy_analyzer.players.player_value`'s "Rostered-only caveat"
section for the full discussion and the direction of the bias.

Sample size
--------------------------------------------------------------------------

One league-season is 10-12 teams and roughly 150-200 rostered players over
about 17 weeks, and every z-score here is computed over that single pool.
The components are not independent (``value`` and ``rate`` are strongly
related by construction -- ``points_above_replacement`` is exactly
``games_played * ppg_above_replacement`` when ``total_points`` is
``points_per_game * games_played``, and with a constant ``games_played``
across the pool the two z-scores are *identical*), so ``ranking_score`` is
not five independent measurements of a player. It is a documented weighted
opinion over five correlated summaries of one small season. Differences of
a few hundredths in ``ranking_score``, or a handful of places in
``league_rank``, should not be read as meaningful.

Grouping key: ``(season, position)`` and ``season`` -- seasons never pooled
--------------------------------------------------------------------------

Like every sibling, seasons are never pooled: replacement levels and
scarcity come from FFA-068 (which groups on ``(season, position)``), and
every z-score, rank and percentile here is computed within one ``season``.
A multi-season ``performance_df`` produces independent per-season rankings
in one frame.

Missing values / edge cases
--------------------------------------------------------------------------

- **Empty ``performance_df``**: returns an empty DataFrame with
  :data:`LEAGUE_PLAYER_RANKING_COLUMNS` and the documented per-column
  dtypes, so an empty result never upcasts a later concat. The same is
  returned when no row in the frame is usable.
- **A frame missing a required column** (:data:`_REQUIRED_COLUMNS`: the six
  FFA-068 reads, plus ``cv`` and ``scoring_ceiling``): ``ValueError``
  naming every missing column. A wrong-shaped frame that silently returned
  an empty result would be indistinguishable from a genuinely empty league
  -- FFA-068's identical rule, extended to the two extra columns this
  module reads.
- **Rows FFA-068 skips** (missing ``season``/``sleeper_player_id``/
  ``position``, including the empty string, or missing
  ``games_played``/``points_per_game``/``total_points``) are absent from
  this frame too, because the value frame is this module's row universe.
- **Duplicate ``(season, sleeper_player_id)`` rows**: ``ValueError``,
  raised by FFA-068 and deliberately not caught -- a duplicate would
  corrupt the replacement level, the position means and every z-score pool.
- **``n + k == 0``** (``games_played = 0`` and ``rate_shrinkage_games = 0``):
  ``shrunk_ppg_above_replacement`` is ``NaN``, not a ``ZeroDivisionError``,
  and the rate component is dropped for that player. FFA-065 never emits a
  zero-game row, so this is reachable only from a hand-built frame.
- **``num_teams`` of ``None``/0**: passed straight through to FFA-068,
  which falls back to its documented worst-rostered baseline. No error.
- **Positions outside {QB, RB, WR, TE}** (K, DEF, IDP): treated like any
  other position, inheriting FFA-068's generic-position decision, including
  its IDP slot handling.
- **A single-player frame, or a season pool of one**: every component has
  fewer than two usable values, so every z-score is ``NaN``,
  ``ranking_score`` is ``NaN``, ``components_used`` is 0, and both rank
  columns are ``NaN``. No exception, no ``inf``.

Column dtypes
--------------------------------------------------------------------------

``season`` and ``components_used`` are plain ``int64`` (never undefined for
a row that exists). Every metric, z-score, score, rank and percentile
column is ``float64`` so undefined values are ``NaN`` and the dtype does
not vary with the data -- including ``games_played`` (preserved from the
input exactly, fractional values included) and **including
``league_rank``/``position_rank``**, which diverge from
``player_value.py``'s ``int64`` ``value_rank`` precisely because an
unscoreable player's rank is ``NaN`` here. The label columns
(``sleeper_player_id``, ``player_name``, ``position``, ``nfl_team``) are
``object`` and any missing label is restored to ``None`` explicitly, so the
representation does not depend on what the frame's other rows look like.
Test label columns with ``is None``; test value columns with ``pd.isna``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any, Optional

import pandas as pd

from fantasy_analyzer.players.player_value import (
    build_player_value_metrics,
    build_position_scarcity_metrics,
)

#: Column order for the DataFrame returned by
#: :func:`build_league_player_rankings`.
#:
#: The order is deliberate and reads left to right as the computation runs:
#: identity (``season`` .. ``nfl_team``), then the FFA-065/FFA-068 inputs the
#: components are built from in the order they are used (production, then
#: replacement context, then the rate/volume VORP pair, then the two
#: distribution columns and the position's scarcity), then the five
#: standardized components, then the blend's audit trail
#: (``components_used``, ``ranking_score``) and finally the three ranking
#: outputs. Every column to the right of ``nfl_team`` can be checked by hand
#: from the columns to its left.
LEAGUE_PLAYER_RANKING_COLUMNS = [
    "season",
    "sleeper_player_id",
    "player_name",
    "position",
    "nfl_team",
    "games_played",
    "points_per_game",
    "total_points",
    "replacement_ppg",
    "ppg_above_replacement",
    "shrunk_ppg_above_replacement",
    "points_above_replacement",
    "cv",
    "scoring_ceiling",
    "scarcity_ratio",
    "z_value",
    "z_rate",
    "z_reliability",
    "z_upside",
    "z_scarcity",
    "components_used",
    "ranking_score",
    "league_rank",
    "position_rank",
    "league_percentile",
]

#: The modes :func:`build_league_player_rankings` accepts. ``"projected"``
#: is a declared-but-unimplemented seam -- see the module docstring's "Two
#: modes" section.
RANKING_MODES = ("retrospective", "projected")

#: Default prior strength, in games, for the rate component's shrinkage
#: toward replacement level -- see "Small-sample shrinkage" in the module
#: docstring. ``0.0`` disables shrinkage exactly.
DEFAULT_RATE_SHRINKAGE_GAMES = 4.0

#: Metric/score columns cast to ``float64`` so undefined values are ``NaN``
#: and the dtype does not vary with the data -- see "Column dtypes" in the
#: module docstring. ``games_played`` lives here (input values are preserved
#: exactly, fractional values included), and so do ``league_rank`` and
#: ``position_rank``, which are ``NaN`` for an unscoreable player.
_FLOAT_COLUMNS = [
    "games_played",
    "points_per_game",
    "total_points",
    "replacement_ppg",
    "ppg_above_replacement",
    "shrunk_ppg_above_replacement",
    "points_above_replacement",
    "cv",
    "scoring_ceiling",
    "scarcity_ratio",
    "z_value",
    "z_rate",
    "z_reliability",
    "z_upside",
    "z_scarcity",
    "ranking_score",
    "league_rank",
    "position_rank",
    "league_percentile",
]

#: Columns cast to ``int64`` -- never undefined for a row that exists.
_INT_COLUMNS = ["season", "components_used"]

#: Player-identity label columns carried through from the value frame --
#: see "Column dtypes" in the module docstring.
_LABEL_COLUMNS = ["sleeper_player_id", "player_name", "position", "nfl_team"]

#: Columns a ``performance_df`` must contain for this module to mean
#: anything: the six FFA-068 requires, plus the two FFA-065 columns this
#: module reads directly for its reliability and upside components.
_REQUIRED_COLUMNS = [
    "season",
    "sleeper_player_id",
    "position",
    "games_played",
    "points_per_game",
    "total_points",
    "cv",
    "scoring_ceiling",
]


@dataclass(frozen=True)
class RankingWeights:
    """Blend weights for the five ranking components.

    See the module docstring's "The composite" and "Why these five, and why
    these defaults" sections for what each component measures and why the
    defaults are what they are, and its "Scarcity is deliberately
    double-counted" section before relying on the ``scarcity`` default.

    Weights do **not** need to sum to 1.0 -- they are renormalized by the
    sum of the weights actually used for each player -- but the defaults do,
    so a fully-observed player's ``ranking_score`` under the defaults is a
    plain weighted sum of his five z-scores.

    Attributes:
        value: Weight on ``z_value`` (season points above replacement).
        rate: Weight on ``z_rate`` (shrunk per-game points above
            replacement).
        reliability: Weight on ``z_reliability`` (``z(-cv)``; lower
            volatility ranks higher).
        upside: Weight on ``z_upside`` (best single game above the
            position's replacement level).
        scarcity: Weight on ``z_scarcity`` (the position's scarcity ratio).
            Set to ``0.0`` to recover the undistorted replacement-relative
            reading.

    Raises:
        ValueError: If any weight is negative or not a number, or if every
            weight is zero (no defined normalization).
    """

    value: float = 0.40
    rate: float = 0.25
    reliability: float = 0.15
    upside: float = 0.10
    scarcity: float = 0.10

    def __post_init__(self) -> None:
        for field_name in _COMPONENT_WEIGHT_FIELDS:
            weight = getattr(self, field_name)
            # ``not (weight >= 0)`` rather than ``weight < 0``: this also
            # rejects NaN, which would otherwise silently poison every
            # ranking_score in the frame.
            if not (weight >= 0):
                raise ValueError(
                    f"RankingWeights.{field_name} must be a non-negative "
                    f"number; got {weight!r}"
                )
        if self.total() == 0:
            raise ValueError(
                "RankingWeights must have at least one positive weight; "
                "an all-zero weight vector has no defined normalization"
            )

    def total(self) -> float:
        """The sum of all five weights (not necessarily 1.0)."""
        return math.fsum(
            getattr(self, field_name) for field_name in _COMPONENT_WEIGHT_FIELDS
        )


#: The five components, as ``(output z-score column, RankingWeights field,
#: internal raw-value key)`` triples, in the fixed order they are blended
#: and reported. One list so the weight fields, the emitted columns and the
#: blend can never drift apart.
_COMPONENTS = (
    ("z_value", "value", "value_raw"),
    ("z_rate", "rate", "rate_raw"),
    ("z_reliability", "reliability", "reliability_raw"),
    ("z_upside", "upside", "upside_raw"),
    ("z_scarcity", "scarcity", "scarcity_raw"),
)

#: The :class:`RankingWeights` field names, in component order.
_COMPONENT_WEIGHT_FIELDS = tuple(field for _, field, _ in _COMPONENTS)

#: Default blend weights -- see :class:`RankingWeights`.
DEFAULT_RANKING_WEIGHTS = RankingWeights()


def _is_missing(value: Any) -> bool:
    """True for ``None``, ``NaN``/``NA``, and the empty string.

    Mirrors ``player_value.py``'s helper of the same name (``pd.isna``
    alone does not catch ``""``); duplicated rather than imported because
    this codebase does not import private names across modules.
    """
    if isinstance(value, str):
        return value == ""
    return pd.isna(value)


def _empty_frame() -> pd.DataFrame:
    """An empty DataFrame with the documented per-column dtypes.

    A bare ``pd.DataFrame(columns=...)`` is all-``object`` dtype, which
    would violate the module's "Column dtypes" contract and upcast any
    concat with a non-empty frame -- the same reasoning as
    ``player_value.py``'s ``_empty_frame``.
    """
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype=(
                    "int64"
                    if column in _INT_COLUMNS
                    else "float64"
                    if column in _FLOAT_COLUMNS
                    else object
                )
            )
            for column in LEAGUE_PLAYER_RANKING_COLUMNS
        }
    )


def _require_columns(performance_df: pd.DataFrame) -> None:
    """Raise ``ValueError`` naming any required column the frame lacks.

    Checked here rather than left to FFA-068 so that ``cv`` and
    ``scoring_ceiling`` -- which this module reads and FFA-068 does not --
    are named in the same error, and so a wrong-shaped frame cannot
    silently produce a plausible empty result. See the module docstring's
    "Missing values / edge cases".
    """
    missing = [
        column for column in _REQUIRED_COLUMNS if column not in performance_df.columns
    ]
    if missing:
        raise ValueError(
            "performance_df is missing required column(s): "
            + ", ".join(missing)
            + "; expected a PLAYER_PERFORMANCE_COLUMNS-shaped frame as "
            "produced by build_player_performance_metrics (FFA-065)"
        )


def _shrunk_rate(
    ppg_above_replacement: float, games_played: float, shrinkage_games: float
) -> Optional[float]:
    """``n * x / (n + k)``: the rate VORP shrunk toward replacement level.

    See "Small-sample shrinkage on the rate component" in the module
    docstring, including the ``n = 2, x = 10, k = 4 -> 3.333...`` worked
    example and why ``k = 0`` degenerates to ``x`` exactly. Returns
    ``None`` (rendered ``NaN``) when ``n + k == 0``, which would otherwise
    be a ``ZeroDivisionError``.
    """
    denominator = games_played + shrinkage_games
    if denominator == 0:
        return None
    return games_played * ppg_above_replacement / denominator


def _dispersion_lookup(
    performance_df: pd.DataFrame,
) -> dict[tuple[int, str], dict[str, Optional[float]]]:
    """``(season, sleeper_player_id)`` -> that player's ``cv``/``scoring_ceiling``.

    The two FFA-065 columns this module reads that FFA-068 does not carry
    through. Values are taken verbatim; a missing value stays missing (it
    becomes an unavailable component, never a substituted number). Rows
    without a usable identity are skipped -- FFA-068 skips them too, so
    they can never be looked up.
    """
    lookup: dict[tuple[int, str], dict[str, Optional[float]]] = {}
    for row in performance_df.itertuples(index=False):
        season = getattr(row, "season", None)
        player_id = getattr(row, "sleeper_player_id", None)
        if _is_missing(season) or _is_missing(player_id):
            continue
        cv = getattr(row, "cv", None)
        ceiling = getattr(row, "scoring_ceiling", None)
        lookup[(int(season), str(player_id))] = {
            "cv": None if _is_missing(cv) else float(cv),
            "scoring_ceiling": None if _is_missing(ceiling) else float(ceiling),
        }
    return lookup


def _scarcity_lookup(
    scarcity_df: pd.DataFrame,
) -> dict[tuple[int, str], Optional[float]]:
    """``(season, position)`` -> that position's ``scarcity_ratio``.

    ``NaN`` ratios (a position whose ``replacement_ppg <= 0``; see FFA-068)
    are normalized to ``None`` so they follow the same
    unavailable-component path as any other missing value.
    """
    lookup: dict[tuple[int, str], Optional[float]] = {}
    for row in scarcity_df.itertuples(index=False):
        ratio = getattr(row, "scarcity_ratio", None)
        lookup[(int(row.season), str(row.position))] = (
            None if _is_missing(ratio) else float(ratio)
        )
    return lookup


def _population_zscores(values: list[Optional[float]]) -> list[Optional[float]]:
    """Population z-score a component's values, preserving position and gaps.

    ``(x - mean) / population_stdev``, computed over the **usable** values
    only (``None`` entries take no part in the mean or the standard
    deviation and come back as ``None``). Returns all-``None`` when fewer
    than two values are usable or the population standard deviation is 0 --
    the zero-variance rule from the module docstring's "Missing components"
    section: a component with no spread cannot rank anyone, and dividing by
    it would emit ``inf``/``NaN`` instead of saying so.
    """
    usable = [value for value in values if value is not None]
    if len(usable) < 2:
        return [None] * len(values)
    stdev = pstdev(usable)
    if stdev == 0:
        return [None] * len(values)
    mean = fmean(usable)
    return [None if value is None else (value - mean) / stdev for value in values]


def _blend(row: dict[str, Any], weights: RankingWeights) -> tuple[Optional[float], int]:
    """``(ranking_score, components_used)`` for one already-z-scored row.

    The weighted sum of the components that have both a usable z-score and
    a strictly positive weight, divided by the sum of those same weights --
    the drop-and-renormalize rule from the module docstring. Returns
    ``(None, 0)`` when no component qualifies.
    """
    terms: list[float] = []
    used_weights: list[float] = []
    for z_column, weight_field, _ in _COMPONENTS:
        weight = getattr(weights, weight_field)
        z_score = row[z_column]
        if z_score is None or weight <= 0:
            continue
        terms.append(weight * z_score)
        used_weights.append(weight)

    if not used_weights:
        return None, 0
    return math.fsum(terms) / math.fsum(used_weights), len(used_weights)


def _sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
    """Display order within a season: best score first, ``NaN`` last.

    Ties (and the whole unscored block) fall back to ascending
    ``sleeper_player_id``, a deterministic label order.
    """
    score = row["ranking_score"]
    if score is None:
        # 1 sorts after 0, so every unscored row lands after every scored
        # one regardless of score magnitude.
        return (1, 0.0, str(row["sleeper_player_id"]))
    return (0, -score, str(row["sleeper_player_id"]))


def _assign_competition_ranks(rows: list[dict[str, Any]], rank_column: str) -> None:
    """Assign standard competition ("1224") ranks in place over one group.

    ``rows`` must already be in the display order :func:`_sort_key` defines.
    Ties are judged on ``ranking_score`` rounded to six decimal places --
    ``player_value.py``'s documented float-noise convention -- so two
    mathematically equal blends cannot be split by rounding. Rows with no
    score get ``None`` (rendered ``NaN``): see the module docstring's
    "Ranks, ties, and percentile".
    """
    current_rank = 0
    previous_score = None
    for position, row in enumerate(rows, start=1):
        score = row["ranking_score"]
        if score is None:
            row[rank_column] = None
            continue
        rounded_score = round(score, 6)
        if rounded_score != previous_score:
            current_rank = position
            previous_score = rounded_score
        row[rank_column] = float(current_rank)


def build_league_player_rankings(
    performance_df: pd.DataFrame,
    roster_positions: list[str],
    num_teams: Optional[int],
    *,
    mode: str = "retrospective",
    weights: RankingWeights = DEFAULT_RANKING_WEIGHTS,
    rate_shrinkage_games: float = DEFAULT_RATE_SHRINKAGE_GAMES,
    projections_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Rank every player in a league-season on a weighted blend of five signals.

    Builds FFA-068's value and scarcity frames from ``performance_df``,
    standardizes five components across each season's player pool
    (season VORP, shrunk rate VORP, negated ``cv``, ceiling above
    replacement, and the position's scarcity ratio), blends them with
    ``weights``, and ranks the result league-wide and within position. See
    the module docstring for every formula, the drop-and-renormalize rule
    for missing components, the shrinkage estimator, the deliberate
    double-counting of positional scarcity, and the phase-agnostic and
    rostered-only caveats inherited from FFA-065/FFA-068.

    Args:
        performance_df: A
            :data:`~fantasy_analyzer.players.performance.PLAYER_PERFORMANCE_COLUMNS`-shaped
            DataFrame as produced by
            :func:`~fantasy_analyzer.players.performance.build_player_performance_metrics`.
            Must carry :data:`_REQUIRED_COLUMNS`; ``cv`` and
            ``scoring_ceiling`` are read from it directly, everything else
            comes from FFA-068. Expects one league-season at a time.
        roster_positions: The league's ordered roster-slot list (e.g.
            ``LeagueSnapshot.roster_positions``), passed through to FFA-068
            for the starter-cutoff replacement baseline.
        num_teams: The number of teams in the league (e.g.
            ``LeagueSettings.total_rosters``), passed through to FFA-068.
            ``None`` is legal and falls into FFA-068's documented
            worst-rostered baseline.
        mode: ``"retrospective"`` (default) ranks realized production.
            ``"projected"`` is a declared seam that raises
            ``NotImplementedError``; see the module docstring's "Two modes".
        weights: The blend weights. Need not sum to 1.0 (they are
            renormalized); the defaults do.
        rate_shrinkage_games: ``k`` in ``n * x / (n + k)``, the prior
            strength for the rate component, in games. ``0.0`` disables
            shrinkage exactly.
        projections_df: Reserved for ``mode="projected"``. Ignored in
            retrospective mode.

    Returns:
        A DataFrame with columns :data:`LEAGUE_PLAYER_RANKING_COLUMNS`, one
        row per player-season FFA-068 emits, sorted by ascending ``season``
        then descending ``ranking_score`` (unscored players last), ties
        broken by ascending ``sleeper_player_id``. Empty (with the same
        columns and dtypes) if the input is empty or no row is usable.

    Raises:
        ValueError: If ``mode`` is not in :data:`RANKING_MODES`, if
            ``rate_shrinkage_games`` is negative, if ``performance_df`` is
            missing a required column, or (from FFA-068) if it contains
            duplicate ``(season, sleeper_player_id)`` rows.
        NotImplementedError: If ``mode="projected"``.
    """
    if mode not in RANKING_MODES:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of {list(RANKING_MODES)}"
        )
    if not (rate_shrinkage_games >= 0):
        raise ValueError(
            "rate_shrinkage_games must be a non-negative number of games "
            f"(0.0 disables shrinkage); got {rate_shrinkage_games!r}"
        )
    if mode == "projected":
        raise NotImplementedError(
            "mode='projected' is a declared seam, not an implementation: it "
            "requires aggregating a ProjectionProvider's per-week "
            "projections (FFA-072, fantasy_analyzer.players.projections) "
            "into projected season totals, and FFA-072 explicitly defers "
            "that methodology. Use mode='retrospective'."
        )

    if performance_df.empty:
        return _empty_frame()

    _require_columns(performance_df)

    # FFA-068 owns every replacement, VORP and scarcity number below; this
    # module reads them and never recomputes them.
    value_df = build_player_value_metrics(performance_df, roster_positions, num_teams)
    if value_df.empty:
        return _empty_frame()
    scarcity_df = build_position_scarcity_metrics(
        performance_df, roster_positions, num_teams
    )

    dispersion = _dispersion_lookup(performance_df)
    scarcity = _scarcity_lookup(scarcity_df)

    rows: list[dict[str, Any]] = []
    for value_row in value_df.itertuples(index=False):
        season = int(value_row.season)
        player_id = value_row.sleeper_player_id
        measured = dispersion.get((season, str(player_id)), {})
        cv = measured.get("cv")
        ceiling = measured.get("scoring_ceiling")
        replacement_ppg = float(value_row.replacement_ppg)
        games_played = float(value_row.games_played)
        ppg_above_replacement = float(value_row.ppg_above_replacement)
        shrunk = _shrunk_rate(
            ppg_above_replacement, games_played, float(rate_shrinkage_games)
        )
        scarcity_ratio = scarcity.get((season, str(value_row.position)))

        rows.append(
            {
                "season": season,
                "sleeper_player_id": player_id,
                "player_name": value_row.player_name,
                "position": value_row.position,
                "nfl_team": value_row.nfl_team,
                "games_played": games_played,
                "points_per_game": float(value_row.points_per_game),
                "total_points": float(value_row.total_points),
                "replacement_ppg": replacement_ppg,
                "ppg_above_replacement": ppg_above_replacement,
                "shrunk_ppg_above_replacement": shrunk,
                "points_above_replacement": float(value_row.points_above_replacement),
                "cv": cv,
                "scoring_ceiling": ceiling,
                "scarcity_ratio": scarcity_ratio,
                # Raw component inputs, before standardization. Only
                # reliability and upside differ from an emitted column:
                # lower cv is better, so it is negated, and upside is
                # measured above the position's replacement level.
                "value_raw": float(value_row.points_above_replacement),
                "rate_raw": shrunk,
                "reliability_raw": None if cv is None else -cv,
                "upside_raw": None if ceiling is None else ceiling - replacement_ppg,
                "scarcity_raw": scarcity_ratio,
            }
        )

    by_season: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_season.setdefault(row["season"], []).append(row)

    ordered_rows: list[dict[str, Any]] = []
    for season in sorted(by_season):
        season_rows = by_season[season]

        # Every z-score is computed across the whole season pool, not
        # within position -- see "The composite" in the module docstring.
        for z_column, _, raw_key in _COMPONENTS:
            z_scores = _population_zscores([row[raw_key] for row in season_rows])
            for row, z_score in zip(season_rows, z_scores):
                row[z_column] = z_score

        for row in season_rows:
            score, components_used = _blend(row, weights)
            row["ranking_score"] = score
            row["components_used"] = components_used

        season_rows.sort(key=_sort_key)
        _assign_competition_ranks(season_rows, "league_rank")

        # league_percentile is relative to the players this season could
        # actually score -- unscored players are in neither the numerator
        # nor the denominator.
        n_ranked = sum(1 for row in season_rows if row["ranking_score"] is not None)
        for row in season_rows:
            rank = row["league_rank"]
            row["league_percentile"] = (
                None if rank is None else 1.0 - (rank - 1.0) / n_ranked
            )

        by_position: dict[str, list[dict[str, Any]]] = {}
        for row in season_rows:
            by_position.setdefault(str(row["position"]), []).append(row)
        for position_rows in by_position.values():
            # Already in display order: sorting the season preserved the
            # relative order of every subsequence.
            _assign_competition_ranks(position_rows, "position_rank")

        ordered_rows.extend(season_rows)

    result = pd.DataFrame(ordered_rows, columns=LEAGUE_PLAYER_RANKING_COLUMNS)
    for column in _INT_COLUMNS:
        result[column] = result[column].astype(int)
    for column in _FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    # Walk the raw lists and restore every missing label to ``None``
    # explicitly: pandas' string-dtype inference would otherwise turn a
    # ``None`` label into ``NaN`` depending on what the other rows contain
    # -- the same guard player_value.py documents.
    for label_column in _LABEL_COLUMNS:
        result[label_column] = pd.Series(
            [
                None if _is_missing(value) else value
                for value in result[label_column].tolist()
            ],
            dtype=object,
        )

    return result[LEAGUE_PLAYER_RANKING_COLUMNS]
