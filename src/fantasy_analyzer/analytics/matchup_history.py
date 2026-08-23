"""Compose Epic 5's matchup analytics into one query interface (FFA-043).

This module is pure composition: it wires together FFA-040's
:func:`~fantasy_analyzer.analytics.head_to_head.build_head_to_head_records`,
FFA-041's
:func:`~fantasy_analyzer.analytics.head_to_head_matrix.build_head_to_head_matrix`
/
:func:`~fantasy_analyzer.analytics.head_to_head_matrix.format_head_to_head_matrix`,
and FFA-042's
:func:`~fantasy_analyzer.analytics.rivalries.build_rivalry_records` into the
ergonomic ``analysis.head_to_head(team_a, team_b)`` /
``analysis.head_to_head_matrix()`` interface AGENTS.md describes for Epic 5.
It is the Epic 5 analog of :mod:`fantasy_analyzer.analytics.summary`
(Epic 3's ``LeagueSummary``), and follows the same shape: a frozen dataclass
over already-built inputs, thin methods, and a ``build_*`` factory.

It performs no network access and defines **no new metrics**. Every number
it returns is copied verbatim from one of the three modules above; see
``analytics/head_to_head.py``, ``analytics/head_to_head_matrix.py``, and
``analytics/rivalries.py`` for the metric definitions and for every
edge-case rule (bye rows excluded, a missing-points meeting counted as a
meeting but not scored, unmapped owner -> ``None``, zero meetings -> no row)
that this module inherits unchanged.

Inputs: the two DataFrames, not a ``LeagueSnapshot``
-----------------------------------------------------

:class:`MatchupHistory` takes ``season_matchup_df`` and ``teams_df``
directly, mirroring ``build_head_to_head_records``' and
``build_rivalry_records``' own signatures, rather than taking a
``LeagueSnapshot`` or a ``SleeperClient``. Those two frames are exactly and
only what the underlying functions need; accepting a snapshot would add a
dependency on league normalization that this service never uses, and
accepting a client would drag network access into an analytics composition
layer that AGENTS.md wants kept separate from data access.

There is deliberately no network-fetching ``load_matchup_history``
counterpart to :func:`build_matchup_history` (unlike
:func:`~fantasy_analyzer.league.snapshot.load_league_snapshot`). Producing a
``season_matchup_df`` from Sleeper is a multi-step pipeline in its own right
(``load_season_matchups`` -> ``pair_week_matchups`` -> ``derive_season_outcomes``
-> ``build_season_matchup_df``, each already loadable on its own), so a
"trivially composing" wrapper of the kind ``load_league_snapshot`` provides
does not exist here.

Eager records, lazy matrix
---------------------------

``head_to_head_df`` and ``rivalry_df`` are both computed **once**, at
construction, in ``__post_init__`` -- the same pattern ``LeagueSummary``
uses for ``season_boundaries``. Each requires a full scan of
``season_matchup_df``, and both :meth:`MatchupHistory.head_to_head` and
:meth:`MatchupHistory.head_to_head_matrix` read from them, so recomputing
per call would rescan the season on every single pair lookup.

The tradeoff is staleness: the cached frames reflect ``season_matchup_df``
as it was at construction. Mutating the input frame afterwards is not a
supported use case -- the dataclass is frozen, exactly as ``LeagueSummary``
is -- and the fix is to build a new :class:`MatchupHistory`.

The matrices, by contrast, are rebuilt per call
(:meth:`~MatchupHistory.head_to_head_matrix` /
:meth:`~MatchupHistory.formatted_head_to_head_matrix`), since they are cheap
reshapes of the already-cached ``head_to_head_df`` and not every caller
wants them. This matches ``LeagueSummary.standings()`` being a per-call
passthrough.

Lookup key: ``roster_id``, not owner name
-------------------------------------------

AGENTS.md's example interface says ``head_to_head(team_a, team_b)`` without
saying what a "team" is. Per its Data Modeling Guidelines ("internally
prefer immutable IDs... usernames and display names may change and should be
treated as labels, not primary keys"), and to match every other function in
this pipeline, ``team_a``/``team_b`` are **``roster_id`` integers**. Owner
display names are not accepted as a lookup key: they are mutable, and
nothing in Sleeper prevents two managers from sharing one, so a name-keyed
lookup could silently resolve to the wrong roster. Owner labels are still
*returned* on the result (and on the formatted matrix) for display.

Both raw frames are exposed
----------------------------

``head_to_head_df`` and ``rivalry_df`` are public attributes, not private
caches: a caller asking about the whole league ("who has the best record
against everyone", "which rivalry was the closest") wants the full tables,
not one pair at a time, and they are already computed. This mirrors
``LeagueSummary`` exposing its precomputed ``season_boundaries`` directly.

Regular season vs. playoffs
------------------------------

This module inherits its inputs' scope exactly: FFA-040 and FFA-042 both
combine **all** ``season_matchup_df`` rows, regular season and playoff
alike, into a single combined record, so every result here is a combined
all-games result and makes no ``is_playoff`` distinction of its own.
Splitting by season phase is FFA-044's job and is deliberately not built in.
A caller who wants a phase-specific view today should filter
``season_matchup_df`` on ``is_playoff`` *before* constructing a
:class:`MatchupHistory`. Note that :class:`RivalryGame` carries
``is_playoff``, so a reported extremum's phase is still visible.

Missing values / edge cases
----------------------------

- **Two rosters that never met** (including ``team_a == team_b``, since no
  roster plays itself): :meth:`~MatchupHistory.head_to_head` returns
  ``None``. This is a normal, expected outcome -- FFA-040/FFA-042 emit no
  zero-meetings row -- not an error, so it is not raised.
- **Empty ``season_matchup_df``**: ``head_to_head_df`` and ``rivalry_df``
  are empty (with their documented columns), the matrices are empty, and
  every lookup returns ``None``.
- **Unmapped owner**: ``owner``/``opponent_owner`` are ``None``, as in the
  underlying frames.
- **A meeting with missing points**: counted in ``meetings`` but not in
  ``scored_meetings``, and excluded from every margin statistic, so
  ``avg_margin`` may be ``NaN`` while ``meetings >= 1``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from fantasy_analyzer.analytics.head_to_head import build_head_to_head_records
from fantasy_analyzer.analytics.head_to_head_matrix import (
    build_head_to_head_matrix,
    format_head_to_head_matrix,
)
from fantasy_analyzer.analytics.rivalries import RivalryGame, build_rivalry_records


@dataclass(frozen=True)
class HeadToHeadHistory:
    """One ordered pair's combined head-to-head record and rivalry stats.

    The single-pair result of :meth:`MatchupHistory.head_to_head`. A caller
    asking "what is my history against this manager" plausibly wants both
    halves of the answer -- the record (FFA-040) *and* the shape of the
    games behind it (FFA-042) -- so both are packed into one object rather
    than requiring two lookups against two frames.

    The fields are flattened scalars rather than the two source rows, so
    attribute access is typed and pandas-free (``history.wins``, not
    ``history.record["wins"]``). The tradeoff is that the column names are
    restated here, a third place they must stay in sync with; every value is
    nonetheless copied verbatim from the corresponding source row and this
    class defines no metric of its own.

    Attributes:
        roster_id: The perspective roster (``team_a`` in the lookup).
        opponent_roster_id: The opponent roster (``team_b``).
        owner: ``roster_id``'s owner display label, or ``None`` if unmapped.
        opponent_owner: ``opponent_roster_id``'s owner label, or ``None``.
        meetings: Times the pair met, per FFA-040. Always ``>= 1``.
        wins: ``roster_id``'s wins over ``opponent_roster_id``.
        losses: ``roster_id``'s losses to ``opponent_roster_id``.
        ties: Ties between the two.
        total_points: ``roster_id``'s points summed over the meetings.
        total_opponent_points: The opponent's points over the same meetings.
        avg_points: ``total_points / meetings``.
        avg_opponent_points: ``total_opponent_points / meetings``.
        scored_meetings: Meetings with both scores present, per FFA-042 --
            the honest sample size behind the margin statistics. May be less
            than ``meetings``.
        avg_margin: Mean *absolute* margin of the scored meetings; ``NaN``
            when ``scored_meetings == 0``.
        closest_game: The scored meeting with the smallest margin, or
            ``None`` if there is none.
        largest_win: ``roster_id``'s widest win, or ``None`` if it never won.
        largest_loss: Its widest loss, or ``None`` if it never lost.
        highest_scoring_matchup: The meeting with the highest combined
            score, or ``None`` if there is no scored meeting.
    """

    roster_id: int
    opponent_roster_id: int
    owner: Optional[str]
    opponent_owner: Optional[str]
    meetings: int
    wins: int
    losses: int
    ties: int
    total_points: float
    total_opponent_points: float
    avg_points: float
    avg_opponent_points: float
    scored_meetings: int
    avg_margin: float
    closest_game: Optional[RivalryGame]
    largest_win: Optional[RivalryGame]
    largest_loss: Optional[RivalryGame]
    highest_scoring_matchup: Optional[RivalryGame]


def _pair_row(df: pd.DataFrame, roster_id: int, opponent_roster_id: int) -> pd.Series:
    """Return the single row of ``df`` for an ordered pair, or an empty Series.

    Both FFA-040's and FFA-042's outputs carry at most one row per ordered
    ``(roster_id, opponent_roster_id)`` pair, so the match is unique when it
    exists. An absent pair yields an empty ``Series``, which the caller
    tests with ``.empty``.
    """
    match = df.loc[
        (df["roster_id"] == roster_id)
        & (df["opponent_roster_id"] == opponent_roster_id)
    ]
    if match.empty:
        return pd.Series(dtype=object)
    return match.iloc[0]


@dataclass(frozen=True)
class MatchupHistory:
    """Thin composition service over a season's normalized matchups.

    ``MatchupHistory`` performs no network access and defines no new metrics
    -- it is a convenience layer giving callers the
    ``analysis.head_to_head(team_a, team_b)`` /
    ``analysis.head_to_head_matrix()`` entrypoints AGENTS.md describes,
    backed entirely by FFA-040/FFA-041/FFA-042. See the module docstring for
    the input rationale, the eager-records caching tradeoff, why lookups are
    keyed by ``roster_id``, and the combined regular-season-plus-playoff
    scope inherited from its inputs.

    Attributes:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used to resolve owner
            labels.
        head_to_head_df: FFA-040's full ``HEAD_TO_HEAD_COLUMNS`` table for
            every ordered pair that met, computed once at construction.
        rivalry_df: FFA-042's full ``RIVALRY_COLUMNS`` table for the same
            pairs, computed once at construction.
    """

    season_matchup_df: pd.DataFrame
    teams_df: pd.DataFrame
    head_to_head_df: pd.DataFrame = field(init=False)
    rivalry_df: pd.DataFrame = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "head_to_head_df",
            build_head_to_head_records(self.season_matchup_df, self.teams_df),
        )
        object.__setattr__(
            self,
            "rivalry_df",
            build_rivalry_records(self.season_matchup_df, self.teams_df),
        )

    def head_to_head(self, team_a: int, team_b: int) -> Optional[HeadToHeadHistory]:
        """Return ``team_a``'s combined history against ``team_b``.

        Looks up the ordered pair in both the cached ``head_to_head_df``
        (FFA-040) and ``rivalry_df`` (FFA-042) and packs the two into a
        single :class:`HeadToHeadHistory`. Every value is copied verbatim
        from those frames; no metric is recomputed here.

        Args:
            team_a: The perspective roster's ``roster_id``. Owner display
                names are deliberately not accepted -- see the module
                docstring's "Lookup key".
            team_b: The opponent roster's ``roster_id``.

        Returns:
            A :class:`HeadToHeadHistory` from ``team_a``'s perspective, or
            ``None`` if the two rosters never met (which includes
            ``team_a == team_b``, and any roster id absent from the season).
            Never met is a normal result, not an error, so nothing is
            raised.
        """
        record = _pair_row(self.head_to_head_df, team_a, team_b)
        if record.empty:
            return None

        # Both frames are built here, in ``__post_init__``, from the same
        # ``season_matchup_df`` under identical pairing rules (byes excluded,
        # one row per ordered pair that met at least once), so a pair present
        # in one is always present in the other.
        rivalry = _pair_row(self.rivalry_df, team_a, team_b)

        return HeadToHeadHistory(
            roster_id=int(record["roster_id"]),
            opponent_roster_id=int(record["opponent_roster_id"]),
            owner=record["owner"],
            opponent_owner=record["opponent_owner"],
            meetings=int(record["meetings"]),
            wins=int(record["wins"]),
            losses=int(record["losses"]),
            ties=int(record["ties"]),
            total_points=float(record["total_points"]),
            total_opponent_points=float(record["total_opponent_points"]),
            avg_points=float(record["avg_points"]),
            avg_opponent_points=float(record["avg_opponent_points"]),
            scored_meetings=int(rivalry["scored_meetings"]),
            avg_margin=float(rivalry["avg_margin"]),
            closest_game=rivalry["closest_game"],
            largest_win=rivalry["largest_win"],
            largest_loss=rivalry["largest_loss"],
            highest_scoring_matchup=rivalry["highest_scoring_matchup"],
        )

    def head_to_head_matrix(self) -> pd.DataFrame:
        """Return the roster-by-roster matrix of raw head-to-head cells.

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.head_to_head_matrix.build_head_to_head_matrix`
        over the cached ``head_to_head_df``. See that function's docstring
        for the ``roster_id`` axes, the ``None`` diagonal, and the zeroed
        :class:`~fantasy_analyzer.analytics.head_to_head_matrix.HeadToHeadCell`
        used for a pair that never met.
        """
        return build_head_to_head_matrix(self.head_to_head_df)

    def formatted_head_to_head_matrix(self) -> pd.DataFrame:
        """Return the owner-labeled ``"W-L"`` display matrix.

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.head_to_head_matrix.format_head_to_head_matrix`
        over the cached ``head_to_head_df``. This representation is lossy and
        its axis labels can collide on duplicate display names -- use
        :meth:`head_to_head_matrix` for anything programmatic.
        """
        return format_head_to_head_matrix(self.head_to_head_df)


def build_matchup_history(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame
) -> MatchupHistory:
    """Build a :class:`MatchupHistory` from an already-built season of matchups.

    Pure composition function, consistent with
    :func:`~fantasy_analyzer.analytics.summary.build_league_summary`'s
    pattern: no network access, callers are responsible for building
    ``season_matchup_df`` first (see
    :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`).

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame of
            the season's matchups.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``.

    Returns:
        A :class:`MatchupHistory` with its ``head_to_head_df`` and
        ``rivalry_df`` already computed.
    """
    return MatchupHistory(season_matchup_df=season_matchup_df, teams_df=teams_df)
