"""Kicker and team-defense projections, so every starting slot is valued (FFA-112).

Every league this project follows starts one ``K`` and one ``DEF``, yet
until this module nothing projected either: the waiver board, the lineup
call and the add/drop search all excluded them. This module produces one
row per Sleeper ``K`` and ``DEF`` player, shaped like
:data:`~fantasy_analyzer.players.waiver_rankings.FREE_AGENT_PROJECTION_COLUMNS`
plus a handful of this-week columns, so the frame concatenates onto a
skill-player projection and drops into
:func:`~fantasy_analyzer.players.roster_fit.optimal_lineup` unchanged.

Points are the league's own
-----------------------------------------------------------------------------

Kicker weeks are scored with
:func:`~fantasy_analyzer.players.scoring.calculate_fantasy_points`, and
defense weeks with
:func:`~fantasy_analyzer.players.scoring.calculate_team_defense_points` on
:func:`~fantasy_analyzer.players.nflverse_defense.build_team_defense_weeks`.
Both were verified against Sleeper's own per-player points -- see
``docs/kicker-defense.md`` -- so the history the projection learns from is
the history the league actually scored.

The rest-of-season estimator
-----------------------------------------------------------------------------

Two-level empirical-Bayes shrinkage, per player::

    prior_resolved = (m * prior_ppg + k * positional_mean) / (m + k)
    w              = g / (g + n0)
    projected_ppg  = w * ppg_to_date + (1 - w) * prior_resolved

``g`` is games played this season through the cutoff, ``m`` games played
last season, ``positional_mean`` the mean ``ppg_to_date`` of every player
at the position with at least one game at the cutoff (knowable then; the
prior season's positional mean before any game is played). A player with no
prior season has ``m = 0``, so his prior *is* the positional mean.

``n0`` and ``k`` are fitted per position on 2016-2025 (see
:func:`fit_kicker_defense_parameters`) and come out large --
``n0 = 20, k = 50`` for kickers and ``n0 = 25, k = 50`` for defenses.
That is the finding, not a tuning accident: both positions are mostly
noise week to week. At week 3 a kicker's own season carries
``3 / 23 = 13%`` of the weight and a full prior season is itself shrunk
``50 / 67 = 75%`` toward the mean. A kicker who has averaged 14 in two
games with no prior season projects to ``(2 * 14 + 20 * 7.6) / 22 = 8.2``,
not 14 -- which is exactly the protection a waiver board needs against a
two-game hot streak topping the overall rankings.

Measured on held-out seasons (rolling origin: each season 2019-2025
projected with parameters fitted on the seasons before it, cutoffs weeks 3
and 4, rest-of-season points per game), the estimator beats the naive
season-to-date mean by a wide margin at both positions, beats the
positional mean for defenses, and **only ties the positional mean for
kickers**. For kickers, at this point in a season, there is essentially no
between-kicker signal beyond "the average kicker". The numbers are in
``docs/kicker-defense.md``; :func:`run_kicker_defense_backtest` reproduces
them.

The this-week projection
-----------------------------------------------------------------------------

::

    week_projected_points = projected_ppg + slope * (x - center)   (a game)
                          = 0.0                                    (a bye)

``x`` is the betting market's implied points for the kicker's *own* team,
or for a defense's *opponent*, from ``games.csv``'s ``spread_line``/
``total_line`` (via
:func:`~fantasy_analyzer.players.opponent_strength.normalize_schedule`).
``slope`` and ``center`` are fitted by least squares on earlier seasons'
residuals (next-week points minus ``projected_ppg``). When the week has no
line, the adjustment is zero.

Both adjustments were kept only because they measurably help out of sample
across cutoffs 3-12. For defenses the gain also shows at cutoffs 3-4 but
within noise there; for kickers it does not show at 3-4 at all (see the doc
for both figures). Home/away and a stats-based opponent-offense adjustment
were measured and dropped: home/away adds nothing once the implied total
(which already prices home field) is in, and the stats-based opponent
adjustment helped less than the market.

What this module does not do
-----------------------------------------------------------------------------

- No injury, weather, or kicker-competition signal. ``status`` is carried
  from the Sleeper catalog for the caller to filter on.
- No availability model: ``projected_ppg`` is a per-game rate, and
  ``remaining_games`` is the schedule-only count
  :mod:`~fantasy_analyzer.players.waiver_rankings` uses, so cross-position
  value comparisons stay on one basis.
- No yards-allowed scoring (no league here weights ``yds_allow_*``).

Regular season vs playoffs: every input is NFL regular-season data, and a
fantasy playoff week is simply a later ``upcoming_week``; nothing here
changes behavior at a league's playoff boundary.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from fantasy_analyzer.players.nflverse_defense import (
    FRANCHISE_CODE_ALIASES,
    TEAM_CODE_ALIASES,
    build_team_defense_weeks,
)
from fantasy_analyzer.players.opponent_strength import bye_weeks, normalize_schedule
from fantasy_analyzer.players.scoring import (
    calculate_fantasy_points,
    calculate_team_defense_points,
)
from fantasy_analyzer.players.waiver_rankings import (
    FREE_AGENT_PROJECTION_COLUMNS,
    OPPORTUNITY_SUMMARY_COLUMNS,
    confidence_tier,
)

#: The two positions this module projects.
KICKER_DEFENSE_POSITIONS = ("K", "DEF")

#: Last fantasy-relevant regular-season week, matching
#: :data:`fantasy_analyzer.players.ros_backtest.DEFAULT_SEASON_END_WEEK`.
DEFAULT_SEASON_END_WEEK = 17

#: Columns :func:`build_kicker_defense_projections` returns:
#: :data:`~fantasy_analyzer.players.waiver_rankings.FREE_AGENT_PROJECTION_COLUMNS`
#: (so the frame concatenates onto a skill-player projection) followed by
#: the this-week columns.
KICKER_DEFENSE_PROJECTION_COLUMNS = FREE_AGENT_PROJECTION_COLUMNS + [
    "week",
    "week_opponent",
    "week_is_home",
    "week_implied_points",
    "week_adjustment",
    "week_projected_points",
    "bye_week",
]

#: Columns of :func:`build_kicker_weeks` / :func:`build_defense_weeks`.
KICKER_DEFENSE_WEEK_COLUMNS = [
    "season",
    "week",
    "player_id",
    "player_name",
    "position",
    "team",
    "opponent",
    "fantasy_points",
]


@dataclass(frozen=True)
class KickerDefenseParameters:
    """Fitted constants of the kicker/defense projection.

    Attributes:
        n0: Position -> games of this season at which the season-to-date
            rate and the resolved prior carry equal weight.
        prior_games: Position -> the ``k`` shrinking last season's rate
            toward the positional mean.
        implied_total_slope: Position -> points of this-week adjustment per
            point of implied team total (own team for ``K``, opponent for
            ``DEF``). ``0.0`` disables the adjustment.
        implied_total_center: The implied total at which the adjustment is
            zero (the mean over the fitting rows).
    """

    n0: Mapping[str, float] = field(default_factory=dict)
    prior_games: Mapping[str, float] = field(default_factory=dict)
    implied_total_slope: Mapping[str, float] = field(default_factory=dict)
    implied_total_center: float = 22.0


#: Fitted on 2016-2025 regular seasons with the NWC league's 2026 scoring
#: (``fit_kicker_defense_parameters``: ``n0`` K 20 / DEF 25, ``k`` 50/50,
#: slopes K +0.130 / DEF -0.364 per implied point, center 22.77). The
#: other two leagues' settings land within one grid step (DEF ``n0`` 30,
#: an error difference under 0.001). Reproduce with
#: ``scripts/verify_special_teams_scoring.py --backtest``.
DEFAULT_KICKER_DEFENSE_PARAMETERS = KickerDefenseParameters(
    n0={"K": 20.0, "DEF": 25.0},
    prior_games={"K": 50.0, "DEF": 50.0},
    implied_total_slope={"K": 0.13, "DEF": -0.36},
    implied_total_center=22.8,
)

#: ``n0`` grid (games) searched by :func:`fit_kicker_defense_parameters`.
DEFAULT_N0_GRID = (4.0, 8.0, 12.0, 16.0, 20.0, 25.0, 30.0, 40.0, 50.0, 75.0)

#: Prior-shrinkage ``k`` grid (games) searched by
#: :func:`fit_kicker_defense_parameters`.
DEFAULT_PRIOR_GAMES_GRID = (0.0, 8.0, 17.0, 25.0, 35.0, 50.0, 75.0, 100.0, 250.0)


# ---------------------------------------------------------------------------
# Scored history
# ---------------------------------------------------------------------------


def _sleeper_team(team: object) -> Optional[str]:
    """nflverse team code (any era) -> Sleeper's current franchise code."""
    if team is None or (isinstance(team, float) and pd.isna(team)) or team == "":
        return None
    team = FRANCHISE_CODE_ALIASES.get(str(team), str(team))
    return TEAM_CODE_ALIASES.get(team, team)


def build_kicker_weeks(
    raw_stats: pd.DataFrame, scoring_settings: Mapping[str, float]
) -> pd.DataFrame:
    """League-scored kicker weeks from nflverse's raw weekly table.

    Args:
        raw_stats: One or more seasons of nflverse's raw weekly player
            table. Only regular-season rows with ``position == "K"`` and a
            ``player_id`` are used.
        scoring_settings: The league's Sleeper scoring settings.

    Returns:
        :data:`KICKER_DEFENSE_WEEK_COLUMNS`, one row per kicker-game
        nflverse recorded; ``player_id`` is the GSIS id and ``team`` is in
        Sleeper's convention. A kicker with no kicking attempt in a game
        has no nflverse row and so no week here.
    """
    kicks = raw_stats
    if "season_type" in kicks.columns:
        kicks = kicks[kicks["season_type"] == "REG"]
    if "position" not in kicks.columns or "player_id" not in kicks.columns:
        return pd.DataFrame(columns=KICKER_DEFENSE_WEEK_COLUMNS)
    kicks = kicks[(kicks["position"] == "K") & kicks["player_id"].notna()]
    if kicks.empty:
        return pd.DataFrame(columns=KICKER_DEFENSE_WEEK_COLUMNS)
    scored = calculate_fantasy_points(kicks, scoring_settings).points_df
    name_column = (
        "player_display_name" if "player_display_name" in scored else "player_name"
    )
    return pd.DataFrame(
        {
            "season": scored["season"].astype(int),
            "week": scored["week"].astype(int),
            "player_id": scored["player_id"].astype(str),
            "player_name": scored[name_column],
            "position": "K",
            "team": scored["team"].map(_sleeper_team),
            "opponent": scored["opponent_team"].map(_sleeper_team)
            if "opponent_team" in scored
            else None,
            "fantasy_points": scored["fantasy_points"].astype(float),
        }
    )[KICKER_DEFENSE_WEEK_COLUMNS].reset_index(drop=True)


def build_defense_weeks(
    raw_stats: pd.DataFrame,
    games: pd.DataFrame,
    season: int,
    scoring_settings: Mapping[str, float],
) -> pd.DataFrame:
    """League-scored team-defense weeks for one season.

    Args:
        raw_stats: nflverse's raw weekly table covering ``season``.
        games: nflverse's cumulative games table.
        season: The season to score.
        scoring_settings: The league's Sleeper scoring settings.

    Returns:
        :data:`KICKER_DEFENSE_WEEK_COLUMNS`, one row per team-game;
        ``player_id`` is the Sleeper ``DEF`` id (the team code).
    """
    team_weeks = build_team_defense_weeks(raw_stats, games, season)
    if team_weeks.empty:
        return pd.DataFrame(columns=KICKER_DEFENSE_WEEK_COLUMNS)
    scored = calculate_team_defense_points(team_weeks, scoring_settings).points_df
    return pd.DataFrame(
        {
            "season": scored["season"].astype(int),
            "week": scored["week"].astype(int),
            "player_id": scored["team"],
            "player_name": scored["team"],
            "position": "DEF",
            "team": scored["team"],
            "opponent": scored["opponent"],
            "fantasy_points": scored["fantasy_points"].astype(float),
        }
    )[KICKER_DEFENSE_WEEK_COLUMNS]


def build_team_week_schedule(games: pd.DataFrame, season: int) -> pd.DataFrame:
    """Team-week schedule with implied totals, in Sleeper team codes.

    A thin wrapper over
    :func:`~fantasy_analyzer.players.opponent_strength.normalize_schedule`
    that also folds historical franchise codes (``OAK``/``SD``/``STL``) so
    older seasons join against :func:`build_kicker_weeks` /
    :func:`build_defense_weeks`.

    Args:
        games: nflverse's cumulative games table.
        season: The season to extract.

    Returns:
        ``normalize_schedule``'s columns with ``team``/``opponent`` in
        Sleeper's convention.
    """
    schedule = normalize_schedule(games, season).copy()
    for column in ("team", "opponent"):
        schedule[column] = schedule[column].map(_sleeper_team)
    return schedule


# ---------------------------------------------------------------------------
# The estimator (pure)
# ---------------------------------------------------------------------------


def summarize_to_date(
    weeks: pd.DataFrame,
    season: int,
    cutoff_week: int,
    *,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
) -> pd.DataFrame:
    """Per-player season-to-date and prior-season summary at a cutoff.

    Args:
        weeks: :data:`KICKER_DEFENSE_WEEK_COLUMNS` rows for (at least)
            ``season`` and ``season - 1``, any positions.
        season: The season being projected.
        cutoff_week: Last week counted as played.
        season_end_week: Last week of the prior season that counts toward
            its per-game rate (weeks after it are ignored, as they are for
            ``ros_backtest``).

    Returns:
        A frame indexed by ``player_id`` with ``position``,
        ``games_to_date``, ``ppg_to_date``, ``last3_ppg``,
        ``prior_season_ppg`` and ``prior_season_games``, one row per player
        with a game this season (through the cutoff) or last season.
        ``ppg_to_date``/``last3_ppg`` are ``NaN`` with zero games, and
        ``prior_season_ppg`` is ``NaN`` with no prior season.
    """
    current = weeks[(weeks["season"] == season) & (weeks["week"] <= cutoff_week)]
    prior = weeks[(weeks["season"] == season - 1) & (weeks["week"] <= season_end_week)]
    by_player = current.groupby("player_id")["fantasy_points"]
    last3 = (
        current.sort_values(["player_id", "week"], kind="stable")
        .groupby("player_id")
        .tail(3)
        .groupby("player_id")["fantasy_points"]
        .mean()
    )
    prior_by_player = prior.groupby("player_id")["fantasy_points"]
    positions = (
        pd.concat([current, prior])
        .groupby("player_id")["position"]
        .agg(lambda values: values.mode().iat[0])
    )
    summary = pd.DataFrame({"position": positions})
    summary["games_to_date"] = by_player.size().reindex(summary.index).fillna(0.0)
    summary["ppg_to_date"] = by_player.mean()
    summary["last3_ppg"] = last3
    summary["prior_season_ppg"] = prior_by_player.mean()
    summary["prior_season_games"] = (
        prior_by_player.size().reindex(summary.index).fillna(0.0)
    )
    summary.index.name = "player_id"
    return summary.astype({"games_to_date": float, "prior_season_games": float})


def positional_means(
    summary: pd.DataFrame,
) -> dict[str, float]:
    """Positional mean ``ppg_to_date`` over players with a game at the cutoff.

    Falls back to the mean prior-season rate for a position with no game
    played yet (a week-0 cutoff), so the shrinkage target always exists.

    Args:
        summary: As returned by :func:`summarize_to_date`.

    Returns:
        ``position -> mean``. A position with neither current nor prior
        data is absent.
    """
    means: dict[str, float] = {}
    for position, frame in summary.groupby("position"):
        played = frame["ppg_to_date"].dropna()
        if not played.empty:
            means[position] = float(played.mean())
            continue
        prior = frame["prior_season_ppg"].dropna()
        if not prior.empty:
            means[position] = float(prior.mean())
    return means


def project_ppg(
    games_to_date: pd.Series,
    ppg_to_date: pd.Series,
    prior_season_ppg: pd.Series,
    prior_season_games: pd.Series,
    positional_mean: pd.Series,
    n0: pd.Series,
    prior_games: pd.Series,
) -> pd.DataFrame:
    """The two-level shrinkage of the module docstring, vectorized.

    Worked example (hand-checkable): ``g = 3`` games at 12.0 ppg, a
    ``m = 17``-game prior at 9.0, positional mean 8.0, ``n0 = 20``,
    ``k = 50``::

        prior_resolved = (17 * 9.0 + 50 * 8.0) / 67 = 8.2537
        w              = 3 / 23                    = 0.1304
        projected_ppg  = 0.1304 * 12 + 0.8696 * 8.2537 = 8.7424

    Args:
        games_to_date: ``g`` per player.
        ppg_to_date: Season-to-date rate (``NaN`` allowed when ``g = 0``).
        prior_season_ppg: Last season's rate (``NaN`` if none).
        prior_season_games: ``m`` per player (0 if none).
        positional_mean: The shrinkage target per player.
        n0: Per-player ``n0`` (the position's).
        prior_games: Per-player ``k`` (the position's).

    Returns:
        A frame with ``prior_resolved_ppg``, ``blend_weight`` and
        ``projected_ppg``, aligned to the inputs.
    """
    m = prior_season_games.fillna(0.0).astype(float)
    has_prior = prior_season_ppg.notna() & (m > 0)
    denominator = m + prior_games
    shrunk_prior = (
        m * prior_season_ppg.fillna(0.0) + prior_games * positional_mean
    ) / denominator.where(denominator > 0, 1.0)
    prior_resolved = shrunk_prior.where(has_prior, positional_mean)
    g = games_to_date.fillna(0.0).astype(float)
    weight = (g / (g + n0)).where(g > 0, 0.0)
    projected = weight * ppg_to_date.fillna(0.0) + (1.0 - weight) * prior_resolved
    return pd.DataFrame(
        {
            "prior_resolved_ppg": prior_resolved,
            "blend_weight": weight,
            "projected_ppg": projected,
        }
    )


def _project_summary(
    summary: pd.DataFrame, parameters: KickerDefenseParameters
) -> pd.DataFrame:
    """Attach the projection columns to a :func:`summarize_to_date` frame."""
    means = positional_means(summary)
    positional_mean = summary["position"].map(means).astype(float)
    n0 = summary["position"].map(parameters.n0).astype(float)
    prior_games = summary["position"].map(parameters.prior_games).astype(float)
    projected = project_ppg(
        summary["games_to_date"],
        summary["ppg_to_date"],
        summary["prior_season_ppg"],
        summary["prior_season_games"],
        positional_mean,
        n0.fillna(0.0),
        prior_games.fillna(0.0),
    )
    return summary.join(projected).assign(positional_mean=positional_mean)


def implied_points_for(
    position: str, team: Optional[str], schedule_week: pd.DataFrame
) -> tuple[Optional[str], Optional[bool], float]:
    """The implied-points input to the this-week adjustment.

    Args:
        position: ``"K"`` (uses the team's own implied total) or ``"DEF"``
            (uses the opponent's).
        team: The player's Sleeper team code.
        schedule_week: :func:`build_team_week_schedule` rows for one week.

    Returns:
        ``(opponent, is_home, implied_points)``. ``(None, None, NaN)`` when
        the team has no game that week (a bye) or no team at all;
        ``implied_points`` is ``NaN`` when the game has no betting line.
    """
    if team is None or schedule_week.empty:
        return None, None, float("nan")
    rows = schedule_week[schedule_week["team"] == team]
    if rows.empty:
        return None, None, float("nan")
    row = rows.iloc[0]
    if position == "K":
        implied = row["implied_team_total"]
    else:
        opponent_rows = schedule_week[schedule_week["team"] == row["opponent"]]
        implied = (
            opponent_rows.iloc[0]["implied_team_total"]
            if not opponent_rows.empty
            else float("nan")
        )
    return row["opponent"], bool(row["is_home"]), float(implied)


# ---------------------------------------------------------------------------
# Fitting and backtesting
# ---------------------------------------------------------------------------


def _evaluation_rows(
    weeks: pd.DataFrame,
    schedules: Mapping[int, pd.DataFrame],
    seasons: Iterable[int],
    cutoffs: Iterable[int],
    season_end_week: int,
) -> pd.DataFrame:
    """One row per (season, cutoff, player): summary + ROS and next-week targets."""
    frames = []
    for season in seasons:
        season_weeks = weeks[weeks["season"] == season]
        schedule = schedules.get(season, pd.DataFrame())
        for cutoff in cutoffs:
            summary = summarize_to_date(
                weeks, season, cutoff, season_end_week=season_end_week
            )
            summary = summary[summary["games_to_date"] > 0]
            if summary.empty:
                continue
            summary = summary.copy()
            summary["positional_mean"] = summary["position"].map(
                positional_means(summary)
            )
            rest = season_weeks[
                (season_weeks["week"] > cutoff)
                & (season_weeks["week"] <= season_end_week)
            ].groupby("player_id")["fantasy_points"]
            summary["ros_ppg"] = rest.mean()
            summary["ros_games"] = rest.size().reindex(summary.index).fillna(0)
            next_week = season_weeks[season_weeks["week"] == cutoff + 1].set_index(
                "player_id"
            )
            summary["next_points"] = next_week["fantasy_points"]
            to_date = season_weeks[season_weeks["week"] <= cutoff]
            team_now = (
                to_date.sort_values("week", kind="stable")
                .groupby("player_id")["team"]
                .last()
            )
            week_schedule = (
                schedule[schedule["week"] == cutoff + 1]
                if not schedule.empty
                else schedule
            )
            implied = [
                implied_points_for(position, team_now.get(player_id), week_schedule)[2]
                for player_id, position in summary["position"].items()
            ]
            summary["implied_points"] = implied
            summary["season"] = season
            summary["cutoff"] = cutoff
            frames.append(summary.reset_index())
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _shrinkage_projection(
    rows: pd.DataFrame, n0: float, prior_games: float
) -> pd.Series:
    count = len(rows)
    return project_ppg(
        rows["games_to_date"],
        rows["ppg_to_date"],
        rows["prior_season_ppg"],
        rows["prior_season_games"],
        rows["positional_mean"],
        pd.Series(n0, index=rows.index, dtype=float)
        if count
        else pd.Series(dtype=float),
        pd.Series(prior_games, index=rows.index, dtype=float)
        if count
        else pd.Series(dtype=float),
    )["projected_ppg"]


def fit_kicker_defense_parameters(
    weeks: pd.DataFrame,
    schedules: Mapping[int, pd.DataFrame],
    seasons: Sequence[int],
    *,
    ros_cutoffs: Sequence[int] = (3, 4),
    slope_cutoffs: Sequence[int] = tuple(range(3, 13)),
    n0_grid: Sequence[float] = DEFAULT_N0_GRID,
    prior_games_grid: Sequence[float] = DEFAULT_PRIOR_GAMES_GRID,
    min_remaining_games: int = 4,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
) -> KickerDefenseParameters:
    """Fit ``n0``, ``k`` and the implied-total slope per position.

    ``(n0, k)`` minimize mean absolute error of ``projected_ppg`` against
    realized rest-of-season points per game at ``ros_cutoffs`` (players
    with at least ``min_remaining_games`` remaining). The slope is the
    least-squares slope of next-week residual (points minus
    ``projected_ppg``) on the centered implied points, over
    ``slope_cutoffs`` rows that have a line. Only ``seasons`` are used, so
    a caller backtesting season ``S`` passes seasons before ``S``.

    Args:
        weeks: Scored :data:`KICKER_DEFENSE_WEEK_COLUMNS` rows covering
            ``seasons`` and each season before them.
        schedules: Season -> :func:`build_team_week_schedule`.
        seasons: The fitting seasons.
        ros_cutoffs: Cutoff weeks for the ``(n0, k)`` fit.
        slope_cutoffs: Cutoff weeks for the slope fit.
        n0_grid: Candidate ``n0`` values.
        prior_games_grid: Candidate ``k`` values.
        min_remaining_games: Minimum rest-of-season games to be scored.
        season_end_week: Last fantasy week.

    Returns:
        A :class:`KickerDefenseParameters` covering every position present.
    """
    cutoffs = sorted(set(ros_cutoffs) | set(slope_cutoffs))
    rows = _evaluation_rows(weeks, schedules, seasons, cutoffs, season_end_week)
    n0: dict[str, float] = {}
    prior_games: dict[str, float] = {}
    slope: dict[str, float] = {}
    if rows.empty:
        return KickerDefenseParameters(n0, prior_games, slope)
    with_line = rows[rows["implied_points"].notna()]
    center = float(with_line["implied_points"].mean()) if not with_line.empty else 22.0
    for position, frame in rows.groupby("position"):
        ros = frame[
            frame["cutoff"].isin(ros_cutoffs)
            & (frame["ros_games"] >= min_remaining_games)
        ]
        best: Optional[tuple[float, float, float]] = None
        for candidate_n0, candidate_k in itertools.product(n0_grid, prior_games_grid):
            error = float(
                (_shrinkage_projection(ros, candidate_n0, candidate_k) - ros["ros_ppg"])
                .abs()
                .mean()
            )
            if best is None or error < best[0]:
                best = (error, candidate_n0, candidate_k)
        if best is None or pd.isna(best[0]):
            continue
        n0[position], prior_games[position] = best[1], best[2]
        weekly = frame[
            frame["cutoff"].isin(slope_cutoffs)
            & frame["next_points"].notna()
            & frame["implied_points"].notna()
        ]
        if len(weekly) >= 2:
            base = _shrinkage_projection(weekly, best[1], best[2])
            residual = weekly["next_points"] - base
            x = weekly["implied_points"] - center
            slope[position] = (
                float(np.polyfit(x, residual, 1)[0]) if x.var() > 0 else 0.0
            )
        else:
            slope[position] = 0.0
    return KickerDefenseParameters(n0, prior_games, slope, center)


#: Methods :func:`run_kicker_defense_backtest` scores.
BACKTEST_METHODS = (
    "shrinkage",
    "shrinkage_plus_implied",
    "season_to_date",
    "positional_mean",
)


def run_kicker_defense_backtest(
    weeks: pd.DataFrame,
    schedules: Mapping[int, pd.DataFrame],
    evaluation_seasons: Sequence[int],
    *,
    first_fit_season: int = 2016,
    cutoffs: Sequence[int] = (3, 4),
    min_remaining_games: int = 4,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
    **fit_kwargs: object,
) -> pd.DataFrame:
    """Rolling-origin backtest: fit on earlier seasons, score the held-out one.

    For each season ``S`` in ``evaluation_seasons``, parameters are fitted
    on ``first_fit_season .. S - 1`` only, then every player with a game
    by each cutoff in ``cutoffs`` is scored on two horizons:

    - ``"ros"`` -- rest-of-season points per game (players with at least
      ``min_remaining_games`` remaining), and
    - ``"next_week"`` -- points in week ``cutoff + 1`` (players who played).

    Args:
        weeks: Scored :data:`KICKER_DEFENSE_WEEK_COLUMNS` rows for every
            season involved plus the season before ``first_fit_season``.
        schedules: Season -> :func:`build_team_week_schedule`.
        evaluation_seasons: Held-out seasons.
        first_fit_season: Earliest fitting season.
        cutoffs: Evaluation cutoff weeks.
        min_remaining_games: ROS eligibility floor.
        season_end_week: Last fantasy week.
        **fit_kwargs: Passed to :func:`fit_kicker_defense_parameters`.

    Returns:
        One row per ``(season, position, horizon, method)`` with ``n`` and
        ``mae``. Pool seasons with an ``n``-weighted mean. ``ros`` has no
        ``shrinkage_plus_implied`` row: the adjustment is a this-week one.
    """
    results = []
    for season in evaluation_seasons:
        parameters = fit_kicker_defense_parameters(
            weeks,
            schedules,
            list(range(first_fit_season, season)),
            min_remaining_games=min_remaining_games,
            season_end_week=season_end_week,
            **fit_kwargs,  # type: ignore[arg-type]
        )
        rows = _evaluation_rows(weeks, schedules, [season], cutoffs, season_end_week)
        for position, frame in rows.groupby("position"):
            if position not in parameters.n0:
                continue
            base = _shrinkage_projection(
                frame, parameters.n0[position], parameters.prior_games[position]
            )
            adjustment = parameters.implied_total_slope.get(position, 0.0) * (
                frame["implied_points"] - parameters.implied_total_center
            ).fillna(0.0)
            predictions = {
                "shrinkage": base,
                "shrinkage_plus_implied": base + adjustment,
                "season_to_date": frame["ppg_to_date"],
                "positional_mean": frame["positional_mean"],
            }
            targets = {
                "ros": (frame["ros_ppg"], frame["ros_games"] >= min_remaining_games),
                "next_week": (frame["next_points"], frame["next_points"].notna()),
            }
            for horizon, (target, mask) in targets.items():
                for method, prediction in predictions.items():
                    if horizon == "ros" and method == "shrinkage_plus_implied":
                        continue
                    error = (prediction[mask] - target[mask]).abs()
                    results.append(
                        {
                            "season": season,
                            "position": position,
                            "horizon": horizon,
                            "method": method,
                            "n": int(mask.sum()),
                            "mae": float(error.mean()) if len(error) else np.nan,
                        }
                    )
    return pd.DataFrame(
        results, columns=["season", "position", "horizon", "method", "n", "mae"]
    )


# ---------------------------------------------------------------------------
# Identity: Sleeper kickers -> nflverse GSIS ids
# ---------------------------------------------------------------------------

_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def normalize_player_name(name: object) -> str:
    """Lower-case ASCII name without punctuation or generational suffixes.

    ``"Ka'imi Fairbairn"`` -> ``"kaimi fairbairn"``; ``"Joey Slye Jr."`` ->
    ``"joey slye"``. Non-strings normalize to ``""``.
    """
    if not isinstance(name, str):
        return ""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[^a-z ]", "", ascii_name.lower().replace("-", " "))
    return " ".join(token for token in cleaned.split() if token not in _NAME_SUFFIXES)


def resolve_kicker_gsis_ids(
    player_catalog: Mapping[str, Mapping[str, object]],
    kicker_weeks: pd.DataFrame,
    crosswalk: Optional[pd.DataFrame] = None,
) -> dict[str, str]:
    """Map every Sleeper ``K`` to an nflverse GSIS id.

    Uses ``crosswalk`` (``sleeper_player_id``/``gsis_id``, e.g.
    :func:`~fantasy_analyzer.players.crosswalk.build_robust_id_crosswalk`)
    first, then falls back to a normalized-name match against the kickers
    in ``kicker_weeks``. The fallback exists because rookie kickers are
    routinely missing from both crosswalk sources -- measured 2026-09-29,
    Green Bay's starter Trey Smack had no ``gsis_id`` in either, so all
    three of his weeks were unscoreable without it. A name that matches
    more than one GSIS id resolves only if exactly one of them played for
    the catalog team; otherwise it is left unresolved.

    Args:
        player_catalog: Sleeper's player catalog.
        kicker_weeks: :func:`build_kicker_weeks` rows (any seasons).
        crosswalk: Optional id crosswalk.

    Returns:
        ``sleeper_player_id -> gsis_id`` for every resolvable kicker.
    """
    kickers = {
        player_id: entry
        for player_id, entry in player_catalog.items()
        if entry.get("position") == "K"
    }
    resolved: dict[str, str] = {}
    if crosswalk is not None and not crosswalk.empty:
        mapped = crosswalk.dropna(subset=["sleeper_player_id", "gsis_id"])
        lookup = dict(
            zip(mapped["sleeper_player_id"].astype(str), mapped["gsis_id"].astype(str))
        )
        resolved = {
            player_id: lookup[player_id] for player_id in kickers if player_id in lookup
        }
    if kicker_weeks.empty:
        return resolved
    names = kicker_weeks.assign(
        name_key=kicker_weeks["player_name"].map(normalize_player_name)
    )
    by_name = names.groupby("name_key")["player_id"].unique()
    teams_by_gsis = names.groupby("player_id")["team"].unique()
    for player_id, entry in kickers.items():
        if player_id in resolved:
            continue
        full_name = entry.get("full_name") or _first_last(entry)
        candidates = list(by_name.get(normalize_player_name(full_name), []))
        if len(candidates) > 1:
            candidates = [
                gsis
                for gsis in candidates
                if entry.get("team") in set(teams_by_gsis.get(gsis, []))
            ]
        if len(candidates) == 1:
            resolved[player_id] = str(candidates[0])
    return resolved


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def _first_last(entry: Mapping[str, object]) -> str:
    """``"first last"`` from a catalog entry, blanks and ``None`` skipped."""
    parts = (entry.get("first_name"), entry.get("last_name"))
    return " ".join(str(part) for part in parts if part).strip()


def _catalog_rows(
    player_catalog: Mapping[str, Mapping[str, object]],
    include_player_ids: Iterable[str],
) -> list[dict]:
    """Catalog K/DEF entries on an NFL team, plus any explicitly requested."""
    wanted = {str(player_id) for player_id in include_player_ids}
    rows = []
    for player_id, entry in player_catalog.items():
        position = entry.get("position")
        if position not in KICKER_DEFENSE_POSITIONS:
            continue
        if not entry.get("team") and player_id not in wanted:
            continue
        first_last = _first_last(entry)
        if position == "DEF":
            # Sleeper's DEF entries carry no full_name: "Seattle" + "Seahawks".
            full_name = first_last or player_id
        else:
            full_name = entry.get("full_name") or first_last
        rows.append(
            {
                "player_id": str(player_id),
                "full_name": full_name,
                "position": position,
                "team": entry.get("team") or None,
                "status": entry.get("status"),
            }
        )
    return sorted(rows, key=lambda row: (row["position"], row["player_id"]))


def build_kicker_defense_projections(
    player_catalog: Mapping[str, Mapping[str, object]],
    scoring_settings: Mapping[str, float],
    season: int,
    cutoff_week: int,
    upcoming_week: int,
    raw_stats_by_season: Mapping[int, pd.DataFrame],
    games: pd.DataFrame,
    *,
    crosswalk: Optional[pd.DataFrame] = None,
    parameters: KickerDefenseParameters = DEFAULT_KICKER_DEFENSE_PARAMETERS,
    season_end_week: int = DEFAULT_SEASON_END_WEEK,
    include_player_ids: Iterable[str] = (),
) -> pd.DataFrame:
    """Project every Sleeper ``K`` and ``DEF``: rest of season and this week.

    See the module docstring for the estimator, the this-week adjustment,
    and the backtest behind both.

    Args:
        player_catalog: Sleeper's player catalog (``get_players_cached``).
        scoring_settings: The league's Sleeper scoring settings.
        season: The season being projected.
        cutoff_week: Last completed week; weeks after it are ignored even
            if ``raw_stats_by_season`` has them.
        upcoming_week: The week ``week_projected_points`` is for.
        raw_stats_by_season: Season -> nflverse raw weekly table. Needs
            ``season`` and ``season - 1`` (a missing prior season just means
            every prior is the positional mean).
        games: nflverse's cumulative games table (``games.csv``).
        crosswalk: Optional Sleeper<->GSIS crosswalk for kickers (see
            :func:`resolve_kicker_gsis_ids`).
        parameters: Fitted constants; defaults to
            :data:`DEFAULT_KICKER_DEFENSE_PARAMETERS`.
        season_end_week: Last fantasy week (sets ``remaining_games``).
        include_player_ids: Sleeper ids to include even without an NFL team
            (e.g. a rostered kicker who was released). Every other catalog
            ``K``/``DEF`` is included only when it has a ``team``.

    Returns:
        :data:`KICKER_DEFENSE_PROJECTION_COLUMNS`, one row per player,
        sorted by position then ``week_projected_points`` descending.
        ``week_projected_points`` is ``0.0`` on a bye or with no NFL team.
        A kicker with no resolvable GSIS id still gets a row: his
        projection is the positional mean and ``has_crosswalk`` is
        ``False``.
    """
    kicker_frames, defense_frames = [], []
    for stats_season in (season - 1, season):
        raw = raw_stats_by_season.get(stats_season)
        if raw is None or raw.empty:
            continue
        kicker_frames.append(build_kicker_weeks(raw, scoring_settings))
        defense_frames.append(
            build_defense_weeks(raw, games, stats_season, scoring_settings)
        )
    kicker_weeks = (
        pd.concat(kicker_frames, ignore_index=True)
        if kicker_frames
        else pd.DataFrame(columns=KICKER_DEFENSE_WEEK_COLUMNS)
    )
    defense_weeks = (
        pd.concat(defense_frames, ignore_index=True)
        if defense_frames
        else pd.DataFrame(columns=KICKER_DEFENSE_WEEK_COLUMNS)
    )
    weeks = pd.concat([kicker_weeks, defense_weeks], ignore_index=True)
    weeks = weeks[
        (weeks["season"] < season)
        | ((weeks["season"] == season) & (weeks["week"] <= cutoff_week))
    ]

    summary = summarize_to_date(
        weeks, season, cutoff_week, season_end_week=season_end_week
    )
    projected = _project_summary(summary, parameters)
    means = positional_means(summary)

    gsis_of = resolve_kicker_gsis_ids(player_catalog, kicker_weeks, crosswalk)
    schedule = build_team_week_schedule(games, season)
    schedule_week = schedule[schedule["week"] == upcoming_week]
    byes = bye_weeks(schedule, season_end_week)
    remaining_games = float(max(season_end_week - cutoff_week, 0))

    rows = []
    for base in _catalog_rows(player_catalog, include_player_ids):
        position = base["position"]
        if position == "K":
            gsis_id = gsis_of.get(base["player_id"])
            history_id = gsis_id
        else:
            gsis_id = None
            history_id = base["player_id"]
        row = dict(base)
        row["gsis_id"] = gsis_id
        row["has_crosswalk"] = history_id is not None
        if history_id is not None and history_id in projected.index:
            source = projected.loc[history_id]
            for column in (
                "games_to_date",
                "ppg_to_date",
                "last3_ppg",
                "prior_season_ppg",
                "prior_season_games",
                "prior_resolved_ppg",
                "blend_weight",
                "projected_ppg",
            ):
                row[column] = float(source[column])
        else:
            mean = means.get(position, float("nan"))
            row.update(
                games_to_date=0.0,
                ppg_to_date=float("nan"),
                last3_ppg=float("nan"),
                prior_season_ppg=float("nan"),
                prior_season_games=0.0,
                prior_resolved_ppg=mean,
                blend_weight=0.0,
                projected_ppg=mean,
            )
        row["confidence_tier"] = confidence_tier(row["games_to_date"])
        row["remaining_games"] = remaining_games
        row["projected_ros_points"] = row["projected_ppg"] * remaining_games
        for column in OPPORTUNITY_SUMMARY_COLUMNS:
            row[column] = float("nan")

        opponent, is_home, implied = implied_points_for(
            position, base["team"], schedule_week
        )
        row["week"] = upcoming_week
        row["week_opponent"] = opponent
        row["week_is_home"] = is_home
        row["week_implied_points"] = implied
        if opponent is None:
            row["week_adjustment"] = 0.0
            row["week_projected_points"] = 0.0
        else:
            slope = parameters.implied_total_slope.get(position, 0.0)
            adjustment = (
                slope * (implied - parameters.implied_total_center)
                if not pd.isna(implied)
                else 0.0
            )
            row["week_adjustment"] = adjustment
            row["week_projected_points"] = row["projected_ppg"] + adjustment
        row["bye_week"] = byes.get(base["team"]) if base["team"] else None
        rows.append(row)

    result = pd.DataFrame(rows, columns=KICKER_DEFENSE_PROJECTION_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(
        ["position", "week_projected_points", "player_id"],
        ascending=[True, False, True],
        kind="stable",
    ).reset_index(drop=True)
