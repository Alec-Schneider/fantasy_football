"""Rest-of-season projection backtesting (FFA-089).

This module is a **measuring stick, not a model**. It ships before any
projection so that every later claim about accuracy is made against a
harness that already exists, with baselines that were fixed before the
model that has to beat them was written.

AGENTS.md's analytics Definition of Done requires an explicit metric
definition, a hand-checkable toy example, tie handling, missing-value
handling, and explicit regular-season-versus-playoff behavior. All five are
addressed below and exercised in ``tests/players/test_ros_backtest.py``.

The question this harness scores
--------------------------------------------------------------------------

At a **cutoff week** ``w`` in a season, using only what was knowable by the
end of week ``w``, how well does a prediction rank and price what each
player will score **over the rest of that season**?

That is the waiver-wire question. It is deliberately *not* "how many points
will this player score next week" (a start/sit question, far noisier) and
not "how many points will this player score this season" (a draft question,
already answered before week 1).

The target: rest-of-season points *per game*
--------------------------------------------------------------------------

``ros_ppg`` is the mean of a player's ``fantasy_points`` over the weeks
strictly after ``w`` and at or before :data:`DEFAULT_SEASON_END_WEEK`, taken
over the weeks he actually has a row for::

    ros_ppg = sum(points in weeks w+1..end) / (number of those weeks played)

Per game, not total, for one reason: a season total conflates *how good a
player is* with *how many games he has left and whether he gets hurt*. A
waiver decision compares weekly starters, so the per-game rate is the
quantity being decided on. A caller who wants totals should multiply by a
separate availability estimate rather than have that risk silently baked
into the accuracy number.

**Regular season only.** Weeks after :data:`DEFAULT_SEASON_END_WEEK`
(default 17) are excluded from both the observed window and the target.
Fantasy playoffs in most leagues end at week 17, league playoff formats vary,
and NFL week 18 is a rest-week lottery that would add noise attributable to
scheduling rather than to the projection. A caller with a different league
calendar passes ``season_end_week``.

Why the row universe is "weeks played", not "weeks in the season"
--------------------------------------------------------------------------

nflverse emits a row for a player-week only when he recorded a stat. A
missing row therefore means "did not play or did not record a stat", which
this module treats as **absent, never as zero**. Averaging over weeks
*played* rather than weeks *elapsed* keeps an injury from being scored as
poor performance. This is the same convention ``performance.py`` uses for
``games_played``, and it matters more here than anywhere else in the
codebase: nflverse publishes an in-progress week incrementally, so on a
Tuesday a real starter can legitimately have no row yet. Reading that as a
zero would be the single most damaging failure mode a live waiver
recommendation could have.

The baselines
--------------------------------------------------------------------------

:data:`DEFAULT_BASELINES` are the predictions any model must beat to be
worth shipping. They are computed from the same evaluation frame, so a
model is compared on exactly the same player set:

``ppg_to_date``
    Mean points per game over weeks ``1..w``. This is **the bar.** Measured
    across 2016-2025 it reaches a rank correlation with ``ros_ppg`` of about
    0.71 for the full player population, and it plateaus by week 4 to 6 --
    more observed weeks add almost nothing after that.

``last3_ppg``
    Mean points per game over the last (at most) three weeks played at or
    before ``w``. Included precisely because it is the most common amateur
    heuristic ("he is hot") and it is measurably *worse* than
    ``ppg_to_date`` at every cutoff and position tested. Recency weighting
    applied to points destroys information; a model that wants recency
    should apply it to opportunity instead.

``prior_season_ppg``
    Mean points per game across the whole previous season, or ``NaN`` for a
    player with no previous season. Weak alone, but it carries most of the
    weight before week 4, which is exactly when a waiver decision is hardest.

``position_mean_ppg``
    The mean ``ros_ppg`` of every evaluated player at the same position --
    the null model. A prediction that cannot beat this has no player-level
    information in it at all. Note this baseline peeks at the target by
    construction; it is a floor to clear, never a candidate to ship.

Calibrate expectations to the population being scored
--------------------------------------------------------------------------

The ~0.71 figure above is the *full* player population. Restricted to
plausible waiver-wire candidates (see :func:`filter_to_waiver_population`),
every correlation drops by roughly 0.2, and ``ppg_to_date`` falls to about
0.51-0.59. That is not a broken harness; it is what happens when the
easy-to-rank established starters are conditioned away. **Judge a waiver
model against the waiver population, and treat r near 0.5 as competitive.**

Leakage
--------------------------------------------------------------------------

:func:`build_ros_evaluation_set` takes one season's scored player-weeks plus
an optional prior-season frame, and derives every observed feature from
weeks ``<= w`` only. It cannot see the future by construction. The
responsibility it does *not* discharge is model fitting:
:func:`run_ros_backtest` yields one result row per evaluated season, and any
parameter a model fits must be fit on seasons strictly earlier than the one
being scored. Splitting by season rather than by row is essential -- the
same player at week 3 and week 4 has near-identical features and a
near-identical target, so a random row split leaks badly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from fantasy_analyzer.players.scoring import calculate_fantasy_points

#: Last regular-season week included in either the observed window or the
#: rest-of-season target. See the module docstring for why week 18 is out.
DEFAULT_SEASON_END_WEEK = 17

#: Per-week usage/efficiency columns :func:`build_scored_player_weeks`
#: carries through onto its output when the input frame has them (FFA-098).
#:
#: Every one of these is *opportunity*, not production: how often the player
#: was thrown to or handed the ball, what share of his offense that was, and
#: how efficient the result was per play. They exist on the scored frame so
#: downstream consumers (notably
#: :func:`~fantasy_analyzer.players.waiver_rankings.build_waiver_wire_rankings`)
#: can show *why* a projection looks the way it does -- a one-game waiver
#: spike on two targets and a long touchdown and a one-game spike on eleven
#: targets are the same ``fantasy_points`` and completely different bets.
#: This is the concrete answer to the "touchdown trap" named in
#: :mod:`fantasy_analyzer.players.ros_projection`'s docstring: that module
#: prices a player on points, so a consumer needs the usage columns beside
#: the projection to see when the points were touchdown-driven.
#:
#: The first ten mirror
#: :data:`~fantasy_analyzer.players.nflverse_provider.OPPORTUNITY_COLUMNS`
#: exactly (asserted by a test, so the two cannot drift apart); ``targets``
#: and ``carries`` are raw volume counts this module has always carried.
#: nflverse's weekly player stats carry **no snap counts**, so no
#: snap-share column is available at any stage of this pipeline.
#: Per-week *context* columns :func:`build_scored_player_weeks` carries
#: through when present (FFA-099): which NFL team the player was on that
#: week, and which defense he faced.
#:
#: These are not stats and play no part in any projection. They exist so a
#: consumer can group realized points by the defense that allowed them --
#: the only way to build a defense-vs-position table from a player-week
#: frame. See :mod:`fantasy_analyzer.players.opponent_strength`.
#:
#: ``opponent_team`` is populated by nflverse only for **completed** weeks.
#: A future week's opponent comes from the schedule
#: (``nflverse_schedule_cache``), never from here.
CARRIED_CONTEXT_COLUMNS = ("team", "opponent_team")

CARRIED_OPPORTUNITY_COLUMNS = (
    "target_share",
    "air_yards_share",
    "wopr",
    "racr",
    "pacr",
    "receiving_air_yards",
    "passing_air_yards",
    "passing_epa",
    "rushing_epa",
    "receiving_epa",
    "targets",
    "carries",
)

#: Minimum weeks a player must have left (and have played) after the cutoff
#: to be scored. Below this the target is an average of one or two games,
#: which is noise rather than a rest-of-season rate.
DEFAULT_MIN_REMAINING_GAMES = 4

#: Minimum weeks a player must have played at or before the cutoff to be
#: scored. One game is enough to be a waiver candidate, so this is
#: deliberately permissive.
DEFAULT_MIN_GAMES_TO_DATE = 1

#: How many of the top-ranked predictions :func:`score_ros_predictions`
#: measures its hit rate over. Five is roughly the number of waiver claims a
#: manager realistically makes in a week.
DEFAULT_TOP_N = 5

#: Columns of the frame :func:`build_ros_evaluation_set` returns, in order.
ROS_EVALUATION_COLUMNS = [
    "season",
    "cutoff_week",
    "player_id",
    "player_name",
    "position",
    "games_to_date",
    "points_to_date",
    "ppg_to_date",
    "last3_ppg",
    "prior_season_ppg",
    "position_mean_ppg",
    "remaining_games",
    "ros_points",
    "ros_ppg",
]

#: Baseline prediction columns, in the order reports should present them.
#: See the module docstring's "The baselines" section for each one's
#: definition and why it is here.
DEFAULT_BASELINES = (
    "ppg_to_date",
    "last3_ppg",
    "prior_season_ppg",
    "position_mean_ppg",
)


@dataclass(frozen=True)
class RosEvaluationSet:
    """The output of :func:`build_ros_evaluation_set`: rows plus diagnostics.

    Mirrors :class:`~fantasy_analyzer.players.player_week.PlayerWeekFactTable`
    and :class:`~fantasy_analyzer.players.scoring.ScoringResult`: a caller
    must not be able to take the evaluation rows without also being handed
    (or deliberately ignoring) how many players were dropped to produce
    them. An accuracy number computed on a silently filtered population is
    not interpretable, and the ``min_remaining_games`` filter in particular
    removes injured players -- a selection effect worth seeing.

    Attributes:
        evaluation_df: Columns :data:`ROS_EVALUATION_COLUMNS`, one row per
            evaluated player. Sorted by descending ``ros_ppg`` then
            ``player_id``, so output is deterministic under ties.
        excluded_no_games_to_date: Players with a row after the cutoff but
            none at or before it -- unobservable at decision time.
        excluded_too_few_remaining: Players dropped by
            ``min_remaining_games``.
    """

    evaluation_df: pd.DataFrame
    excluded_no_games_to_date: int = 0
    excluded_too_few_remaining: int = 0


def build_scored_player_weeks(
    raw_seasons: Iterable[pd.DataFrame],
    scoring_settings: Mapping[str, float],
    *,
    player_id_column: str = "player_id",
) -> pd.DataFrame:
    """Score raw nflverse season tables into league-scored player-weeks.

    A convenience over
    :func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points` for
    the backtest's specific need: many seasons at once, with no league
    roster context. The full fact-table builders in
    :mod:`fantasy_analyzer.players.player_week` require a league's weekly
    rosters, which a multi-season historical backtest neither has nor wants
    -- the point is to score *every* player, rostered or not.

    Args:
        raw_seasons: Raw nflverse per-season tables, as returned by
            :func:`~fantasy_analyzer.players.nflverse_cache.get_player_stats_cached`.
            Concatenated; seasons may be passed in any order.
        scoring_settings: A Sleeper league's scoring settings, applied
            verbatim by ``calculate_fantasy_points``.
        player_id_column: The identifier column to carry through as
            ``player_id``. Defaults to nflverse's own ``player_id`` (a GSIS
            id); pass ``"sleeper_player_id"`` for a crosswalked frame.

    Returns:
        A DataFrame with ``season``, ``week``, ``player_id``,
        ``player_name``, ``position``, ``fantasy_points``, and every
        opportunity column present in the input. Regular-season rows only
        when a ``season_type`` column is present. Rows with no
        ``player_id`` are dropped: an unidentifiable player cannot be
        tracked across weeks, which is the whole basis of this analysis.
        Empty (same columns) if ``raw_seasons`` yields nothing usable.
    """
    frames = [frame for frame in raw_seasons if not frame.empty]
    if not frames:
        return pd.DataFrame(
            columns=[
                "season",
                "week",
                "player_id",
                "player_name",
                "position",
                "fantasy_points",
            ]
        )

    combined = pd.concat(frames, ignore_index=True)
    if "season_type" in combined.columns:
        combined = combined[combined["season_type"] == "REG"]

    scored = calculate_fantasy_points(combined, scoring_settings).points_df

    name_column = (
        "player_display_name"
        if "player_display_name" in scored.columns
        else "player_name"
    )
    result = pd.DataFrame(
        {
            "season": scored["season"],
            "week": scored["week"],
            "player_id": scored[player_id_column],
            "player_name": scored[name_column],
            "position": scored["position"],
            "fantasy_points": scored["fantasy_points"],
        }
    )
    for column in CARRIED_CONTEXT_COLUMNS + CARRIED_OPPORTUNITY_COLUMNS:
        if column in scored.columns:
            result[column] = scored[column].to_numpy()

    result = result[result["player_id"].notna()]
    return result.reset_index(drop=True)


def _majority_label(values: pd.Series) -> Optional[str]:
    """The most frequent non-null value, ties broken by first occurrence.

    A player's ``position`` can differ across rows (nflverse reclassifies,
    and a frame may span seasons). Same convention as ``performance.py``.
    """
    non_null = values.dropna()
    if non_null.empty:
        return None
    counts = non_null.value_counts()
    top = counts.max()
    for value in non_null:
        if counts[value] == top:
            return value
    return None


def _per_player_summary(weeks: pd.DataFrame) -> pd.DataFrame:
    """Collapse player-weeks to one row per player: games, points, labels."""
    grouped = weeks.groupby("player_id", sort=False)
    return pd.DataFrame(
        {
            "games": grouped["fantasy_points"].size(),
            "points": grouped["fantasy_points"].sum(),
            "player_name": grouped["player_name"].agg(_majority_label),
            "position": grouped["position"].agg(_majority_label),
        }
    )


def _last_n_ppg(weeks: pd.DataFrame, n: int) -> pd.Series:
    """Mean points over each player's last ``n`` weeks played, at most.

    A player with fewer than ``n`` weeks played averages over what he has;
    this is deliberately not ``NaN``, since a two-game sample is exactly the
    situation a waiver decision faces.
    """
    ordered = weeks.sort_values(["player_id", "week"], kind="stable")
    tail = ordered.groupby("player_id", sort=False).tail(n)
    return tail.groupby("player_id", sort=False)["fantasy_points"].mean()


def build_ros_evaluation_set(
    scored_weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    *,
    prior_season_weeks: Optional[pd.DataFrame] = None,
    min_remaining_games: int = DEFAULT_MIN_REMAINING_GAMES,
    min_games_to_date: int = DEFAULT_MIN_GAMES_TO_DATE,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
) -> RosEvaluationSet:
    """Build one season/cutoff-week evaluation frame: features and target.

    Every observed column is derived from weeks ``<= cutoff_week`` only, so
    the frame cannot leak the future. See the module docstring for the
    definition of ``ros_ppg`` and of each baseline.

    Args:
        scored_weeks: League-scored player-weeks, as returned by
            :func:`build_scored_player_weeks`. May span multiple seasons;
            rows outside ``season`` are ignored.
        season: The season to evaluate.
        cutoff_week: The last week whose results are knowable. Features come
            from weeks ``1..cutoff_week``; the target from
            ``cutoff_week+1..season_end_week``.
        prior_season_weeks: Scored player-weeks for earlier seasons, used
            only for ``prior_season_ppg`` (read from ``season - 1``).
            Defaults to ``None``, which leaves that column ``NaN``
            throughout -- a legitimate state, not an error, and the state
            every model must handle for a rookie.
        min_remaining_games: Drop players with fewer weeks played after the
            cutoff than this. See :data:`DEFAULT_MIN_REMAINING_GAMES`.
        min_games_to_date: Drop players with fewer weeks played at or before
            the cutoff than this.
        season_end_week: Last week counted, inclusive. See the module
            docstring on regular-season-versus-playoff behavior.

    Returns:
        A :class:`RosEvaluationSet`. Its ``evaluation_df`` is empty (with
        :data:`ROS_EVALUATION_COLUMNS`) when no player clears both filters --
        including when ``cutoff_week >= season_end_week``, where no week
        remains to be predicted. That is an expected outcome, not an error.

    Raises:
        ValueError: If ``cutoff_week`` is below 1.
    """
    if cutoff_week < 1:
        raise ValueError(f"cutoff_week must be >= 1; got {cutoff_week}.")

    this_season = scored_weeks[scored_weeks["season"] == season]
    observed = this_season[
        (this_season["week"] >= 1) & (this_season["week"] <= cutoff_week)
    ]
    future = this_season[
        (this_season["week"] > cutoff_week) & (this_season["week"] <= season_end_week)
    ]

    if observed.empty or future.empty:
        return RosEvaluationSet(evaluation_df=_empty_evaluation_frame())

    to_date = _per_player_summary(observed)
    rest = _per_player_summary(future)

    # An inner join is what "evaluable" means: a player needs observed
    # features AND a realized target. Count each side's losses separately so
    # the selection effect is visible rather than implied.
    merged = to_date.join(
        rest[["games", "points"]].rename(
            columns={"games": "remaining_games", "points": "ros_points"}
        ),
        how="inner",
    )
    excluded_no_games_to_date = int(len(rest.index.difference(to_date.index)))

    merged["ppg_to_date"] = merged["points"] / merged["games"]
    merged["ros_ppg"] = merged["ros_points"] / merged["remaining_games"]
    merged["last3_ppg"] = _last_n_ppg(observed, 3)

    merged["prior_season_ppg"] = np.nan
    if prior_season_weeks is not None and not prior_season_weeks.empty:
        prior = prior_season_weeks[prior_season_weeks["season"] == season - 1]
        if not prior.empty:
            prior_summary = _per_player_summary(prior)
            prior_ppg = prior_summary["points"] / prior_summary["games"]
            merged["prior_season_ppg"] = merged.index.map(prior_ppg)

    before = len(merged)
    merged = merged[merged["games"] >= min_games_to_date]
    merged = merged[merged["remaining_games"] >= min_remaining_games]
    excluded_too_few_remaining = before - len(merged)

    if merged.empty:
        return RosEvaluationSet(
            evaluation_df=_empty_evaluation_frame(),
            excluded_no_games_to_date=excluded_no_games_to_date,
            excluded_too_few_remaining=excluded_too_few_remaining,
        )

    # The null model. Computed after filtering so it is the mean of exactly
    # the population being scored.
    merged["position_mean_ppg"] = merged.groupby("position")["ros_ppg"].transform(
        "mean"
    )

    merged = merged.reset_index().rename(
        columns={"games": "games_to_date", "points": "points_to_date"}
    )
    merged["season"] = season
    merged["cutoff_week"] = cutoff_week

    evaluation_df = (
        merged[ROS_EVALUATION_COLUMNS]
        .sort_values(["ros_ppg", "player_id"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )
    return RosEvaluationSet(
        evaluation_df=evaluation_df,
        excluded_no_games_to_date=excluded_no_games_to_date,
        excluded_too_few_remaining=excluded_too_few_remaining,
    )


def _empty_evaluation_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=ROS_EVALUATION_COLUMNS)


#: Columns of the frame :func:`score_baselines` and :func:`run_ros_backtest`
#: return, in order.
ROS_METRIC_COLUMNS = [
    "season",
    "cutoff_week",
    "position",
    "prediction",
    "n",
    "mae",
    "rmse",
    "mean_error",
    "spearman",
    "top_n_hit_rate",
]


def _top_n_hit_rate(
    evaluation_df: pd.DataFrame, prediction_column: str, top_n: int
) -> float:
    """Fraction of the top-``n`` predicted players who are truly top-``n``.

    Ties are broken deterministically rather than statistically: within
    equal values, the lower ``player_id`` sorts first, on both the predicted
    and the actual side. A tie-aware definition (counting every player level
    with the nth) would make the denominator vary between the two sides and
    the metric incomparable across predictions, which is the one thing a
    ranking metric must not be.

    Returns ``NaN`` when there are fewer than ``top_n`` scored rows, since a
    hit rate over a partial slate is not comparable to a full one.
    """
    scored = evaluation_df[evaluation_df[prediction_column].notna()]
    if len(scored) < top_n or top_n < 1:
        return float("nan")

    predicted = set(
        scored.sort_values(
            [prediction_column, "player_id"], ascending=[False, True], kind="stable"
        )
        .head(top_n)["player_id"]
        .tolist()
    )
    actual = set(
        scored.sort_values(
            ["ros_ppg", "player_id"], ascending=[False, True], kind="stable"
        )
        .head(top_n)["player_id"]
        .tolist()
    )
    return len(predicted & actual) / top_n


def score_ros_predictions(
    evaluation_df: pd.DataFrame,
    prediction_column: str,
    *,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """Score one prediction column against ``ros_ppg``.

    Rows whose prediction is ``NaN`` are excluded rather than imputed -- a
    model that declines to predict a player should not be charged for him,
    and imputing a zero or a mean would silently flatter or punish it. ``n``
    reports how many rows actually survived, so a prediction that covers few
    players is visible as such rather than looking accurate.

    Metrics, all against ``ros_ppg``:

    - ``mae``: mean absolute error. The primary metric -- robust to the fat
      right tail of fantasy scoring.
    - ``rmse``: root mean squared error. Punishes missing a league-winner,
      which is arguably the real objective.
    - ``mean_error``: mean signed error (prediction minus actual), which
      catches systematic bias that ``mae`` hides.
    - ``spearman``: rank correlation, ties handled by average ranks --
      computed as Pearson over ranks, so no scipy dependency is needed. The
      metric that matches the decision, which is ordinal: a manager picks
      the best available player, not a points total.
    - ``top_n_hit_rate``: see :func:`_top_n_hit_rate`.

    Args:
        evaluation_df: A frame shaped like
            :data:`ROS_EVALUATION_COLUMNS`, carrying ``prediction_column``.
        prediction_column: The column holding the prediction to score.
        top_n: Slate size for the hit rate.

    Returns:
        A dict with keys ``prediction``, ``n``, ``mae``, ``rmse``,
        ``mean_error``, ``spearman``, ``top_n_hit_rate``. Every metric is
        ``NaN`` when ``n`` is 0; ``spearman`` is additionally ``NaN`` when
        fewer than two rows survive or either side has zero variance (every
        prediction identical, as the null model is within a position), since
        a correlation is undefined there.

    Raises:
        KeyError: If ``prediction_column`` is not in ``evaluation_df``.
    """
    if prediction_column not in evaluation_df.columns:
        raise KeyError(
            f"{prediction_column!r} is not a column of the evaluation frame."
        )

    scored = evaluation_df[
        evaluation_df[prediction_column].notna() & evaluation_df["ros_ppg"].notna()
    ]
    result = {"prediction": prediction_column, "n": len(scored)}
    if scored.empty:
        result.update(
            mae=float("nan"),
            rmse=float("nan"),
            mean_error=float("nan"),
            spearman=float("nan"),
            top_n_hit_rate=float("nan"),
        )
        return result

    error = scored[prediction_column] - scored["ros_ppg"]
    result["mae"] = float(error.abs().mean())
    result["rmse"] = float(np.sqrt((error**2).mean()))
    result["mean_error"] = float(error.mean())

    if len(scored) < 2 or scored[prediction_column].nunique() < 2:
        result["spearman"] = float("nan")
    else:
        # Spearman computed as Pearson over average ranks rather than via
        # pandas' method="spearman", which imports scipy. This package's
        # stack is requests + pandas (see draft_points_value.py, which fits
        # its curve in closed form for the same reason), and pandas' own
        # .rank() already implements the average-rank tie convention
        # Spearman requires -- so the dependency would buy nothing.
        result["spearman"] = float(
            scored[prediction_column]
            .rank(method="average")
            .corr(scored["ros_ppg"].rank(method="average"))
        )

    result["top_n_hit_rate"] = _top_n_hit_rate(scored, prediction_column, top_n)
    return result


def score_baselines(
    evaluation_set: RosEvaluationSet,
    *,
    predictions: Iterable[str] = DEFAULT_BASELINES,
    top_n: int = DEFAULT_TOP_N,
    by_position: bool = True,
) -> pd.DataFrame:
    """Score every prediction column over one evaluation set.

    Args:
        evaluation_set: As returned by :func:`build_ros_evaluation_set`,
            optionally with extra model-prediction columns already joined
            onto its ``evaluation_df``.
        predictions: Prediction column names to score. Defaults to
            :data:`DEFAULT_BASELINES`; pass a model's column alongside them
            to compare on identical rows.
        top_n: Slate size for the hit rate.
        by_position: When ``True`` (the default), emit one row per position
            *and* an ``"ALL"`` row pooling them. Per-position is the honest
            read for a waiver decision, which is made within a position;
            the pooled row is easier to track over time.

    Returns:
        A DataFrame with :data:`ROS_METRIC_COLUMNS`. Empty (same columns) if
        the evaluation frame is empty.
    """
    evaluation_df = evaluation_set.evaluation_df
    if evaluation_df.empty:
        return pd.DataFrame(columns=ROS_METRIC_COLUMNS)

    season = evaluation_df["season"].iloc[0]
    cutoff_week = evaluation_df["cutoff_week"].iloc[0]

    groups: list[tuple[str, pd.DataFrame]] = [("ALL", evaluation_df)]
    if by_position:
        groups.extend(
            (position, frame)
            for position, frame in evaluation_df.groupby("position", sort=True)
        )

    rows = []
    for position, frame in groups:
        for prediction_column in predictions:
            if prediction_column not in frame.columns:
                continue
            metrics = score_ros_predictions(frame, prediction_column, top_n=top_n)
            metrics.update(season=season, cutoff_week=cutoff_week, position=position)
            rows.append(metrics)

    return pd.DataFrame(rows, columns=ROS_METRIC_COLUMNS)


def filter_to_waiver_population(
    evaluation_set: RosEvaluationSet, *, quantile: float = 0.5
) -> RosEvaluationSet:
    """Restrict an evaluation set to plausible waiver-wire candidates.

    A proxy, and an explicitly imperfect one: it keeps players at or below
    the within-position ``quantile`` of ``ppg_to_date``, on the reasoning
    that a below-median scorer through the cutoff is the kind of player who
    is plausibly unrostered. It is *not* a reconstruction of who was
    actually available, which needs point-in-time ownership data this
    codebase does not yet ingest.

    Use it because accuracy on the full population badly overstates accuracy
    on the population a waiver tool actually serves -- conditioning away
    established starters removes most of the easy variance, and every
    correlation drops by roughly 0.2.

    Args:
        evaluation_set: As returned by :func:`build_ros_evaluation_set`.
        quantile: Within-position quantile of ``ppg_to_date`` to keep at or
            below. Defaults to the median.

    Returns:
        A new :class:`RosEvaluationSet` over the retained rows, with the
        original's exclusion counts carried through unchanged (they describe
        how the input was built, not this filter). ``position_mean_ppg`` is
        recomputed over the retained rows so the null model stays the null
        model *for this population*.

    Raises:
        ValueError: If ``quantile`` is outside ``[0, 1]``.
    """
    if not 0.0 <= quantile <= 1.0:
        raise ValueError(f"quantile must be in [0, 1]; got {quantile}.")

    evaluation_df = evaluation_set.evaluation_df
    if evaluation_df.empty:
        return evaluation_set

    cutoffs = evaluation_df.groupby("position")["ppg_to_date"].transform(
        lambda values: values.quantile(quantile)
    )
    retained = evaluation_df[evaluation_df["ppg_to_date"] <= cutoffs].copy()
    if not retained.empty:
        retained["position_mean_ppg"] = retained.groupby("position")[
            "ros_ppg"
        ].transform("mean")

    return RosEvaluationSet(
        evaluation_df=retained.reset_index(drop=True),
        excluded_no_games_to_date=evaluation_set.excluded_no_games_to_date,
        excluded_too_few_remaining=evaluation_set.excluded_too_few_remaining,
    )


def run_ros_backtest(
    scored_weeks: pd.DataFrame,
    seasons: Iterable[int],
    cutoff_weeks: Iterable[int],
    *,
    predictions: Iterable[str] = DEFAULT_BASELINES,
    waiver_population_only: bool = False,
    top_n: int = DEFAULT_TOP_N,
    by_position: bool = True,
    **evaluation_kwargs,
) -> pd.DataFrame:
    """Score every ``(season, cutoff_week)`` cell and stack the results.

    Rolling-origin by construction: each season is evaluated independently,
    and ``prior_season_ppg`` for season ``s`` is read from season ``s - 1``
    within ``scored_weeks``. A model fitting parameters must fit them on
    seasons strictly before the one being scored -- this function evaluates,
    it does not fit, so that obligation stays with the caller.

    Args:
        scored_weeks: League-scored player-weeks spanning every season in
            ``seasons``, plus each one's predecessor if
            ``prior_season_ppg`` is to be populated.
        seasons: Seasons to evaluate.
        cutoff_weeks: Cutoff weeks to evaluate within each season.
        predictions: Prediction columns to score.
        waiver_population_only: Restrict each cell to
            :func:`filter_to_waiver_population` before scoring.
        top_n: Slate size for the hit rate.
        by_position: Passed through to :func:`score_baselines`.
        **evaluation_kwargs: Forwarded to :func:`build_ros_evaluation_set`
            (``min_remaining_games``, ``season_end_week``, and so on).

    Returns:
        A DataFrame with :data:`ROS_METRIC_COLUMNS`, one row per
        ``(season, cutoff_week, position, prediction)``. Cells that produced
        no evaluable player contribute no rows; an entirely empty result is
        an empty frame with those columns, not an error.
    """
    results = []
    for season in seasons:
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
            metrics = score_baselines(
                evaluation_set,
                predictions=predictions,
                top_n=top_n,
                by_position=by_position,
            )
            if not metrics.empty:
                results.append(metrics)

    if not results:
        return pd.DataFrame(columns=ROS_METRIC_COLUMNS)
    return pd.concat(results, ignore_index=True)
