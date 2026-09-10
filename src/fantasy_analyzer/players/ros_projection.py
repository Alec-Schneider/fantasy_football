"""Empirical-Bayes rest-of-season points projection (FFA-090).

The first concrete forward-looking player model in this codebase. It answers
the question :mod:`fantasy_analyzer.players.ros_backtest` scores: at a cutoff
week, what will each player average over the rest of the season?

It deliberately produces just one more *prediction column* on that module's
evaluation frame, so the model is measured by the same harness, on the same
rows, as the baselines it must beat. There is no separate scoring path a
favourable number could come from.

The estimator
--------------------------------------------------------------------------

One idea, applied per player::

    projected_ppg = w * observed_ppg + (1 - w) * prior_ppg
    w             = games_played / (games_played + n0)

``observed_ppg`` is season-to-date points per game through the cutoff.
``prior_ppg`` is the player's previous-season points per game, falling back
to a positional baseline when he has none. ``n0`` is the shrinkage constant,
expressed in games: it is *the number of observed games at which the season
so far and the prior carry equal weight*. Small ``n0`` trusts the current
season quickly; large ``n0`` holds onto the prior.

This is ordinary empirical-Bayes shrinkage, and the functional form matters
more than it might look. A per-week lookup table of weights would fit the
same data and generalize worse, because it would learn a separate number for
each cutoff from a decade of seasons rather than one number describing how
fast evidence accumulates. It also handles unequal games for free: two
players at week 6 who have played six and two games get different weights,
which a per-week table cannot express.

Why ``n0`` is fitted rather than chosen
--------------------------------------------------------------------------

:func:`fit_shrinkage` grid-searches ``n0`` per position, minimizing mean
absolute error against realized rest-of-season points per game over a set of
**fit seasons**. Two properties are non-negotiable and are enforced by the
API rather than by convention:

- The seasons used to fit must not include the season being scored.
  :func:`fit_shrinkage` takes its seasons explicitly, and
  :func:`run_shrinkage_backtest` fits on strictly earlier seasons for each
  evaluated season (a rolling origin).
- Fitting per position is necessary, not decoration. Running backs, wide
  receivers, tight ends and quarterbacks have visibly different
  ``n0`` values, because their week-to-week scoring has different variance
  relative to their between-player spread.

What the prior is, and why the fallback matters
--------------------------------------------------------------------------

``prior_ppg`` prefers the player's own previous-season points per game. A
player who has none -- a rookie, or anyone who missed the previous season --
gets the **positional mean of observed points per game among evaluated
players at that cutoff**. That fallback is computed from data knowable at
the cutoff, never from the target, so it introduces no leakage.

The fallback is doing real work rather than filling a hole. Players with no
prior season are exactly the waiver-wire population this epic exists to
serve, and assigning them a zero prior (the obvious shortcut) would shrink
every rookie toward zero and systematically bury the breakouts a waiver tool
is supposed to find.

What this module does *not* do
--------------------------------------------------------------------------

- **No opportunity-first reconstruction.** Projecting volume and applying a
  regressed efficiency rate is a separate, larger step; this module blends in
  points space. See "Where this goes next" below.
- **No availability model.** ``projected_ppg`` is a per-game rate. It says
  nothing about how many games the player will actually play, and multiplying
  it into a season total without an injury model would be wrong.
- **No opponent adjustment**, no depth-chart or injury signal, no market
  consensus.

Where this goes next
--------------------------------------------------------------------------

The measured findings behind this epic say the largest remaining gain is
opportunity-first: project volume (targets for receivers, carries for backs,
rushing volume for quarterbacks), then apply an efficiency rate regressed
hard toward the positional mean, and score the resulting stat line through
:mod:`fantasy_analyzer.players.scoring`. Touchdown rate in particular is the
least stable input measured, and is the central waiver trap -- a player whose
season-to-date scoring is touchdown-driven is being priced on the least
repeatable thing he did. This module prices him on points, so it inherits
that trap; the next one should not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from fantasy_analyzer.players.ros_backtest import (
    DEFAULT_BASELINES,
    RosEvaluationSet,
    build_ros_evaluation_set,
    filter_to_waiver_population,
    score_baselines,
)

#: The column :func:`add_ros_projection` writes onto an evaluation frame.
PROJECTION_COLUMN = "projected_ppg"

#: ``n0`` values :func:`fit_shrinkage` searches, in games. The range spans
#: "trust the current season almost immediately" (0.5) through "hold the
#: prior until midseason" (12). Half-game resolution below 6 because that is
#: where the fitted values land and where the error surface is steepest.
DEFAULT_N0_GRID = (
    0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 8.0, 10.0, 12.0,
)

#: ``n0`` used for a position with no fitted value -- an unseen position, or
#: one with too little data to fit. Sits mid-grid deliberately: with no
#: evidence about how fast this position's evidence accumulates, weighting
#: the season and the prior equally at three games is the neutral choice.
DEFAULT_N0 = 3.0


@dataclass(frozen=True)
class ShrinkageParameters:
    """Fitted shrinkage constants, in games, per position.

    Attributes:
        n0_by_position: Position -> fitted ``n0``. A position absent here
            falls back to ``default_n0``.
        default_n0: Fallback for an unfitted position.
        fit_seasons: The seasons the fit used, sorted. Carried so a caller
            can assert a scored season was not among them -- the one
            property that makes a reported accuracy number honest.
        fit_mae: Position -> the mean absolute error achieved at the chosen
            ``n0``. Reportable alongside any projection this produces.
    """

    n0_by_position: Mapping[str, float]
    default_n0: float = DEFAULT_N0
    fit_seasons: tuple[int, ...] = ()
    fit_mae: Mapping[str, float] = None  # type: ignore[assignment]

    def n0_for(self, position: Optional[str]) -> float:
        """Return the shrinkage constant for ``position``.

        Args:
            position: A position label, or ``None`` for an unlabeled player.

        Returns:
            The fitted ``n0``, or :attr:`default_n0` when the position was
            never fitted.
        """
        if position is None:
            return self.default_n0
        return self.n0_by_position.get(position, self.default_n0)


def _prior_with_fallback(evaluation_df: pd.DataFrame) -> pd.Series:
    """Prior points per game, backfilled with the positional observed mean.

    See the module docstring on why the fallback is the positional mean of
    ``ppg_to_date`` (knowable at the cutoff, so no leakage) rather than zero.
    """
    positional_mean = evaluation_df.groupby("position")["ppg_to_date"].transform(
        "mean"
    )
    prior = evaluation_df["prior_season_ppg"]
    return prior.where(prior.notna(), positional_mean)


def project_ppg(
    evaluation_df: pd.DataFrame, parameters: ShrinkageParameters
) -> pd.Series:
    """Compute the shrunk rest-of-season projection for each row.

    Args:
        evaluation_df: A frame shaped like
            :data:`~fantasy_analyzer.players.ros_backtest.ROS_EVALUATION_COLUMNS`.
        parameters: Fitted shrinkage constants.

    Returns:
        A float Series aligned to ``evaluation_df``'s index, holding
        ``w * ppg_to_date + (1 - w) * prior`` per row. Never ``NaN`` for a
        row with a non-null ``ppg_to_date``: the prior always resolves, via
        the positional fallback if necessary.
    """
    if evaluation_df.empty:
        return pd.Series(dtype=float)

    n0 = evaluation_df["position"].map(parameters.n0_for).astype(float)
    games = evaluation_df["games_to_date"].astype(float)
    weight = games / (games + n0)
    return weight * evaluation_df["ppg_to_date"] + (1 - weight) * _prior_with_fallback(
        evaluation_df
    )


def add_ros_projection(
    evaluation_set: RosEvaluationSet,
    parameters: ShrinkageParameters,
    *,
    column: str = PROJECTION_COLUMN,
) -> RosEvaluationSet:
    """Return ``evaluation_set`` with a projection column added.

    The projection becomes just another prediction column, so
    :func:`~fantasy_analyzer.players.ros_backtest.score_baselines` scores it
    against the baselines on identical rows.

    Args:
        evaluation_set: As returned by
            :func:`~fantasy_analyzer.players.ros_backtest.build_ros_evaluation_set`.
        parameters: Fitted shrinkage constants.
        column: Name for the projection column.

    Returns:
        A new :class:`~fantasy_analyzer.players.ros_backtest.RosEvaluationSet`
        carrying ``column``. An empty input is returned unchanged.
    """
    evaluation_df = evaluation_set.evaluation_df
    if evaluation_df.empty:
        return evaluation_set

    updated = evaluation_df.copy()
    updated[column] = project_ppg(updated, parameters)
    return RosEvaluationSet(
        evaluation_df=updated,
        excluded_no_games_to_date=evaluation_set.excluded_no_games_to_date,
        excluded_too_few_remaining=evaluation_set.excluded_too_few_remaining,
    )


def fit_shrinkage(
    scored_weeks: pd.DataFrame,
    fit_seasons: Sequence[int],
    cutoff_weeks: Sequence[int],
    *,
    n0_grid: Sequence[float] = DEFAULT_N0_GRID,
    positions: Optional[Iterable[str]] = None,
    min_rows: int = 30,
    default_n0: float = DEFAULT_N0,
    **evaluation_kwargs,
) -> ShrinkageParameters:
    """Fit ``n0`` per position by grid search, minimizing mean absolute error.

    Pools every ``(fit_season, cutoff_week)`` cell into one error surface per
    position and takes the ``n0`` with the lowest MAE. Pooling across cutoffs
    is the point: ``n0`` describes how fast evidence accumulates, which is a
    property of the position, not of the calendar. The ``games / (games +
    n0)`` form already produces a different weight at each cutoff.

    Ties on the grid resolve to the **smallest** ``n0``, which is the less
    aggressive assumption: it holds less of the prior.

    Args:
        scored_weeks: League-scored player-weeks, as returned by
            :func:`~fantasy_analyzer.players.ros_backtest.build_scored_player_weeks`,
            spanning every fit season and its predecessor.
        fit_seasons: Seasons to fit on. **Must not contain a season this
            parameter set will later be used to score.**
        cutoff_weeks: Cutoff weeks to pool over.
        n0_grid: Candidate values, in games.
        positions: Positions to fit. Defaults to every position present.
        min_rows: Minimum pooled rows required to fit a position; below this
            the position is left to ``default_n0`` rather than fitted on a
            sample too small to mean anything.
        default_n0: Fallback for positions that are unfitted or too sparse.
        **evaluation_kwargs: Forwarded to
            :func:`~fantasy_analyzer.players.ros_backtest.build_ros_evaluation_set`.

    Returns:
        A :class:`ShrinkageParameters` carrying the fitted values, the
        seasons used, and the MAE achieved per position. With no usable rows
        at all, every position falls back to ``default_n0`` and
        ``n0_by_position`` is empty -- an expected outcome for a caller with
        too little history, not an error.

    Raises:
        ValueError: If ``n0_grid`` is empty, or any candidate is not
            positive (``n0 = 0`` would ignore the prior entirely and make the
            weight undefined for a player with no games).
    """
    if not len(n0_grid):
        raise ValueError("n0_grid must not be empty.")
    if any(candidate <= 0 for candidate in n0_grid):
        raise ValueError(f"every n0 candidate must be positive; got {list(n0_grid)}.")

    pooled = []
    for season in fit_seasons:
        for cutoff_week in cutoff_weeks:
            evaluation_set = build_ros_evaluation_set(
                scored_weeks,
                season,
                cutoff_week,
                prior_season_weeks=scored_weeks,
                **evaluation_kwargs,
            )
            if not evaluation_set.evaluation_df.empty:
                frame = evaluation_set.evaluation_df.copy()
                frame["prior_resolved"] = _prior_with_fallback(frame)
                pooled.append(frame)

    if not pooled:
        return ShrinkageParameters(
            n0_by_position={},
            default_n0=default_n0,
            fit_seasons=tuple(sorted(fit_seasons)),
            fit_mae={},
        )

    rows = pd.concat(pooled, ignore_index=True)
    if positions is None:
        positions = sorted(rows["position"].dropna().unique())

    n0_by_position: dict[str, float] = {}
    fit_mae: dict[str, float] = {}
    for position in positions:
        subset = rows[rows["position"] == position]
        if len(subset) < min_rows:
            continue

        games = subset["games_to_date"].astype(float).to_numpy()
        observed = subset["ppg_to_date"].to_numpy()
        prior = subset["prior_resolved"].to_numpy()
        actual = subset["ros_ppg"].to_numpy()

        best_n0, best_mae = None, np.inf
        for candidate in n0_grid:
            weight = games / (games + candidate)
            predicted = weight * observed + (1 - weight) * prior
            mae = float(np.nanmean(np.abs(predicted - actual)))
            if mae < best_mae:
                best_n0, best_mae = float(candidate), mae

        if best_n0 is not None:
            n0_by_position[position] = best_n0
            fit_mae[position] = best_mae

    return ShrinkageParameters(
        n0_by_position=n0_by_position,
        default_n0=default_n0,
        fit_seasons=tuple(sorted(fit_seasons)),
        fit_mae=fit_mae,
    )


def run_shrinkage_backtest(
    scored_weeks: pd.DataFrame,
    seasons: Sequence[int],
    cutoff_weeks: Sequence[int],
    *,
    min_fit_seasons: int = 3,
    waiver_population_only: bool = False,
    predictions: Iterable[str] = DEFAULT_BASELINES,
    by_position: bool = True,
    **evaluation_kwargs,
) -> pd.DataFrame:
    """Rolling-origin backtest of the projection against the baselines.

    For each season in ``seasons``, fits ``n0`` on every *earlier* season
    available and scores the resulting projection on that season alone. A
    season with fewer than ``min_fit_seasons`` predecessors is skipped rather
    than fitted on a thin history, so the reported numbers are never
    flattered by a degenerate fit.

    This is the function whose output decides whether the model ships. If it
    does not beat ``ppg_to_date`` on rank correlation and top-N hit rate,
    that is a real finding, and the right response is to report it.

    Args:
        scored_weeks: League-scored player-weeks spanning every season.
        seasons: Seasons to evaluate, in order.
        cutoff_weeks: Cutoff weeks within each season.
        min_fit_seasons: Minimum earlier seasons required to evaluate one.
        waiver_population_only: Restrict each cell to
            :func:`~fantasy_analyzer.players.ros_backtest.filter_to_waiver_population`.
            The honest setting for judging a waiver tool.
        predictions: Baseline columns to score alongside the projection.
        by_position: Passed through to
            :func:`~fantasy_analyzer.players.ros_backtest.score_baselines`.
        **evaluation_kwargs: Forwarded to
            :func:`~fantasy_analyzer.players.ros_backtest.build_ros_evaluation_set`.

    Returns:
        A DataFrame with
        :data:`~fantasy_analyzer.players.ros_backtest.ROS_METRIC_COLUMNS`,
        carrying one row per ``(season, cutoff_week, position, prediction)``
        for every baseline plus :data:`PROJECTION_COLUMN`. Empty (same
        columns) if no season had enough history.
    """
    from fantasy_analyzer.players.ros_backtest import ROS_METRIC_COLUMNS

    ordered = sorted(seasons)
    results = []

    for season in ordered:
        fit_seasons = [candidate for candidate in ordered if candidate < season]
        if len(fit_seasons) < min_fit_seasons:
            continue

        parameters = fit_shrinkage(
            scored_weeks, fit_seasons, cutoff_weeks, **evaluation_kwargs
        )
        for cutoff_week in cutoff_weeks:
            evaluation_set = build_ros_evaluation_set(
                scored_weeks,
                season,
                cutoff_week,
                prior_season_weeks=scored_weeks,
                **evaluation_kwargs,
            )
            if waiver_population_only:
                evaluation_set = filter_to_waiver_population(evaluation_set)
            evaluation_set = add_ros_projection(evaluation_set, parameters)

            metrics = score_baselines(
                evaluation_set,
                predictions=list(predictions) + [PROJECTION_COLUMN],
                by_position=by_position,
            )
            if not metrics.empty:
                results.append(metrics)

    if not results:
        return pd.DataFrame(columns=ROS_METRIC_COLUMNS)
    return pd.concat(results, ignore_index=True)
