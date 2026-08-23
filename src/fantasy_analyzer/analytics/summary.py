"""Compose a ``LeagueSnapshot`` into a single league-summary entrypoint.

This module is pure composition (FFA-023): it wires together an already-built
:class:`~fantasy_analyzer.league.snapshot.LeagueSnapshot`,
:func:`~fantasy_analyzer.analytics.standings.build_standings`,
:func:`~fantasy_analyzer.analytics.standings.build_scoring_summary`, and
:func:`~fantasy_analyzer.league.season.derive_season_boundaries` into the
ergonomic ``analysis.league_summary()`` / ``analysis.standings()`` interface
described in AGENTS.md's "Core Domain Objects" / Epic 3 sections. It performs
no network access and introduces no new metric definitions of its own --
see ``analytics/standings.py`` and ``league/season.py`` for the metric
definitions, ranking rules, zero-games handling, and regular-season-vs-
playoff caveats this module inherits unchanged.

Per FFA-022's no-hardcoding rule, ``total_weeks`` (the season length) is not
assumed by this module -- callers must supply it explicitly, exactly as
:func:`~fantasy_analyzer.league.season.derive_season_boundaries` requires.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from fantasy_analyzer.analytics.standings import build_scoring_summary, build_standings
from fantasy_analyzer.league.season import SeasonBoundaries, derive_season_boundaries
from fantasy_analyzer.league.snapshot import LeagueSnapshot


@dataclass(frozen=True)
class LeagueSummaryView:
    """The single composed view returned by :meth:`LeagueSummary.league_summary`.

    A plain, explicit dataclass rather than an untyped dict, so callers get
    predictable attribute access and static typing while still being able to
    inspect every field. See :meth:`LeagueSummary.league_summary` for how
    each field is produced.

    Attributes:
        league_id: The league's immutable Sleeper ID.
        name: League display name (a label, not a key).
        season: Season year string, as sourced from Sleeper (e.g. ``"2025"``).
        status: League status (e.g. ``"in_season"``, ``"complete"``).
        standings: Output of
            :func:`~fantasy_analyzer.analytics.standings.build_standings`.
        scoring_summary: Output of
            :func:`~fantasy_analyzer.analytics.standings.build_scoring_summary`.
        season_boundaries: Output of
            :func:`~fantasy_analyzer.league.season.derive_season_boundaries`.
    """

    league_id: str | None
    name: str | None
    season: str | None
    status: str | None
    standings: pd.DataFrame
    scoring_summary: pd.DataFrame
    season_boundaries: SeasonBoundaries


@dataclass(frozen=True)
class LeagueSummary:
    """Thin composition service over a :class:`LeagueSnapshot`.

    ``LeagueSummary`` performs no network access and defines no new metrics
    -- it is a convenience layer that gives callers the
    ``analysis.league_summary()`` / ``analysis.standings()`` entrypoints
    described in AGENTS.md, backed entirely by the already-normalized
    ``snapshot``.

    Attributes:
        snapshot: The normalized ``LeagueSnapshot`` this summary is built
            from.
        total_weeks: The total number of weeks in the fantasy season, as
            supplied by the caller (e.g. ``18`` for the 2025 NFL season).
            Required, not defaulted -- see
            :func:`~fantasy_analyzer.league.season.derive_season_boundaries`
            for why this must not be hardcoded into library logic.
        season_boundaries: Computed once at construction via
            :func:`~fantasy_analyzer.league.season.derive_season_boundaries`
            using ``snapshot.league`` and ``total_weeks``.
    """

    snapshot: LeagueSnapshot
    total_weeks: int
    season_boundaries: SeasonBoundaries = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "season_boundaries",
            derive_season_boundaries(self.snapshot.league, self.total_weeks),
        )

    def standings(self) -> pd.DataFrame:
        """Return season-to-date standings for this league.

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.standings.build_standings` over
        ``self.snapshot.rosters_df`` / ``self.snapshot.teams_df``. See that
        function's docstring for metric definitions, the ranking rule, and
        the regular-season-vs-playoff caveat (Sleeper's roster counters are
        season-cumulative and cannot be split by phase without matchup-level
        data).
        """
        return build_standings(self.snapshot.rosters_df, self.snapshot.teams_df)

    def scoring_summary(self) -> pd.DataFrame:
        """Return season-to-date scoring-rate metrics for this league.

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.standings.build_scoring_summary`
        over ``self.snapshot.rosters_df`` / ``self.snapshot.teams_df``. See
        that function's docstring for metric definitions and why
        ``high_score``/``low_score`` are not included (no per-week matchup
        data exists yet).
        """
        return build_scoring_summary(self.snapshot.rosters_df, self.snapshot.teams_df)

    def league_summary(self) -> LeagueSummaryView:
        """Return the single composed league-summary view.

        Combines league metadata (from ``snapshot.league``), ``standings()``,
        ``scoring_summary()``, and ``season_boundaries`` into one
        :class:`LeagueSummaryView`. This is the one-call entrypoint AGENTS.md
        describes as ``analysis.league_summary()``.

        Returns:
            A :class:`LeagueSummaryView` with league metadata plus the three
            composed DataFrames/dataclass described above.
        """
        return LeagueSummaryView(
            league_id=self.snapshot.league.league_id,
            name=self.snapshot.league.name,
            season=self.snapshot.league.season,
            status=self.snapshot.league.status,
            standings=self.standings(),
            scoring_summary=self.scoring_summary(),
            season_boundaries=self.season_boundaries,
        )


def build_league_summary(snapshot: LeagueSnapshot, total_weeks: int) -> LeagueSummary:
    """Build a :class:`LeagueSummary` from an already-built ``LeagueSnapshot``.

    Pure composition function, consistent with
    :func:`~fantasy_analyzer.league.snapshot.build_league_snapshot`'s
    pattern: no network access, callers are responsible for constructing
    ``snapshot`` first (e.g. via
    :func:`~fantasy_analyzer.league.snapshot.load_league_snapshot` or
    :func:`~fantasy_analyzer.league.snapshot.build_league_snapshot`).

    Args:
        snapshot: A normalized ``LeagueSnapshot``.
        total_weeks: The total number of weeks in the fantasy season (e.g.
            ``18`` for the 2025 NFL season). Must be supplied explicitly by
            the caller -- see :class:`LeagueSummary`.

    Returns:
        A :class:`LeagueSummary` wrapping ``snapshot`` with its
        ``season_boundaries`` already computed.
    """
    return LeagueSummary(snapshot=snapshot, total_weeks=total_weeks)
