"""Compose Epic 6's advanced league analytics into one query interface (FFA-057).

This module is pure composition: it wires together FFA-050 through FFA-056's
already-built, already-documented metric builders into the ergonomic
``analysis.all_play()`` / ``analysis.schedule_luck()`` / ``analysis.consistency()``
/ ``analysis.strength_of_schedule()`` / ``analysis.power_rankings()`` interface
AGENTS.md describes for Epic 6. It is the Epic 6 analog of
:mod:`fantasy_analyzer.analytics.matchup_history` (Epic 5's ``MatchupHistory``)
and :mod:`fantasy_analyzer.analytics.summary` (Epic 3's ``LeagueSummary``), and
follows the same shape: a frozen dataclass over already-built inputs, thin
methods that delegate to the ``build_*`` functions, and a ``build_*`` factory.

It performs no network access and defines **no new metrics**. Every number it
returns is copied verbatim from one of the modules below; see
``analytics/weekly_scores.py``, ``analytics/all_play.py``,
``analytics/schedule_luck.py``, ``analytics/consistency.py``,
``analytics/strength_of_schedule.py``, ``analytics/power_rankings.py``, and
``matchups/playoffs.py`` for every metric definition and edge-case rule this
module inherits unchanged.

Inputs: the season frames, not a ``LeagueSnapshot`` -- plus optional raw brackets
-------------------------------------------------------------------------------

:class:`LeagueAnalytics` takes ``season_matchup_df`` and ``teams_df`` directly,
mirroring ``MatchupHistory``'s own choice: those two frames are exactly and
only what ``build_weekly_scoring_ranks``, ``build_schedule_luck``,
``build_strength_of_schedule`` and ``build_power_rankings`` need, so accepting
a ``LeagueSnapshot`` or a ``SleeperClient`` would drag league-normalization or
network concerns into a composition layer that AGENTS.md wants kept separate
from data access.

FFA-055's playoff-bracket builders are a genuine mismatch with the rest: they
consume *raw* Sleeper bracket payloads (``winners_raw``/``losers_raw``), not
``season_matchup_df``. Rather than silently drop them (FFA-057 lists FFA-055 as
a dependency) or force a fake ``season_matchup_df``-shaped input onto them,
:class:`LeagueAnalytics` accepts them as two additional, **optional**
constructor fields -- ``winners_bracket_raw``/``losers_bracket_raw`` -- that
default to ``None``. A caller building analytics before or during the playoffs
(or for a league with no bracket data loaded) simply omits them;
``build_playoff_brackets(None, None)`` already returns an empty, correctly
shaped frame, so no special-casing is needed here.

Eager weekly scoring ranks, lazy everything else
--------------------------------------------------

``weekly_scoring_ranks_df`` is computed **once**, at construction, in
``__post_init__`` -- the same pattern ``MatchupHistory`` uses for
``head_to_head_df``/``rivalry_df``. It requires a full scan of
``season_matchup_df``, and it is the one frame this module's own methods
(:meth:`~LeagueAnalytics.all_play`, :meth:`~LeagueAnalytics.consistency`)
actually reuse, so recomputing it on every call would rescan the season twice
over for no reason.

Every other method is a **lazy, per-call** passthrough:

- :meth:`~LeagueAnalytics.schedule_luck`,
  :meth:`~LeagueAnalytics.strength_of_schedule`, and
  :meth:`~LeagueAnalytics.power_rankings` each call their own ``build_*``
  function directly on ``season_matchup_df``/``teams_df`` rather than reusing
  the cached ``weekly_scoring_ranks_df``. This is not an inconsistency: none of
  ``build_schedule_luck``, ``build_strength_of_schedule``, or
  ``build_power_rankings`` accepts a pre-built weekly-scoring-ranks frame as a
  parameter in the first place. Each is deliberately a single-
  ``season_matchup_df``-input function precisely so that its internal halves
  (actual record vs. all-play rate, in ``schedule_luck.py``'s case; opponent
  strength vs. opponent list, in ``strength_of_schedule.py``'s) cannot drift
  out of sync -- see those modules'
  own "must cover the same games" sections. Handing in this module's cached
  frame instead would either be impossible (wrong signature) or would
  reintroduce exactly the phase-mismatch bug those modules were structured to
  prevent. Each of these three methods therefore does its own internal
  ``build_weekly_scoring_ranks`` rescan, which is accepted, documented
  duplicate work rather than a shortcut worth breaking encapsulation for.
- :meth:`~LeagueAnalytics.playoff_brackets` and
  :meth:`~LeagueAnalytics.final_placements` are likewise rebuilt per call, from
  the (small, already-in-memory) raw bracket payloads, matching
  ``MatchupHistory.head_to_head_matrix``'s reasoning: cheap, and not every
  caller wants them.

The tradeoff for the one cached frame is staleness, exactly as in
``MatchupHistory``: ``weekly_scoring_ranks_df`` reflects ``season_matchup_df``
as it was at construction, mutating the input frames afterwards is not a
supported use case, and the dataclass is frozen -- the fix is to build a new
:class:`LeagueAnalytics`.

Why ``playoff_brackets()``/``final_placements()`` are included
------------------------------------------------------------------

AGENTS.md's example interface for FFA-057 lists ``all_play()``,
``schedule_luck()``, ``consistency()``, ``strength_of_schedule()``, and
``power_rankings()``, but not a bracket/placement accessor -- yet FFA-057
explicitly depends on FFA-055. Both accessors are included here for
completeness: a caller assembling one "advanced league analytics" object for a
season plausibly wants the normalized playoff outcome alongside the other
Epic 6 metrics, and leaving FFA-055 unreachable from this service would make
the composition layer incomplete relative to its own documented dependency
list. Note ``power_rankings()`` itself deliberately does **not** consume
``final_placements()`` as a feature -- see ``power_rankings.py``'s own
"Playoff placement (FFA-055) is a listed dependency, and is deliberately
excluded" section -- so no dependency is forced between the two methods here
either; they are independent accessors on the same service.

Regular season vs. playoffs
------------------------------

This module makes no phase distinction of its own and applies no ``is_playoff``
filter anywhere. Every Epic 6 builder it composes computes a single **combined**
result over whatever rows of ``season_matchup_df`` it is given (see each
module's own "Regular season vs. playoffs" section), and several of them
(``schedule_luck.py``, ``strength_of_schedule.py``, ``power_rankings.py``)
structurally require deriving every internal comparison from that same single
frame. Re-filtering inside this module would therefore either duplicate a rule
those functions already enforce or, worse, silently violate their
same-games invariant.

Exactly as :class:`~fantasy_analyzer.analytics.matchup_history.MatchupHistory`
already does, a caller who wants a phase-specific view (most commonly
regular-season-only, since a seeded playoff bracket is not "a schedule" in the
sense these metrics measure) should filter ``season_matchup_df`` to
``is_playoff == False`` *before* constructing a :class:`LeagueAnalytics`, and
build a separate instance for a separate phase. This is deliberately not
exposed as a per-method boolean parameter: doing so per-method would only
recreate, one flag at a time, exactly the "construct a new instance from a
pre-filtered frame" pattern this whole package already uses everywhere else.

Missing values / edge cases
----------------------------

This module inherits every edge case from the functions it composes and adds
none of its own:

- **Empty ``season_matchup_df``**: ``weekly_scoring_ranks_df`` is empty (with
  its documented columns), and every method that derives from it or from
  ``season_matchup_df`` directly returns its own empty, correctly-shaped
  frame -- see each ``build_*`` function's own "empty input" behavior.
- **No bracket data supplied** (``winners_bracket_raw``/``losers_bracket_raw``
  both ``None``, the default): :meth:`~LeagueAnalytics.playoff_brackets`
  returns an empty frame and :meth:`~LeagueAnalytics.final_placements`
  therefore does too, exactly as
  :func:`~fantasy_analyzer.matchups.playoffs.build_playoff_brackets` and
  :func:`~fantasy_analyzer.matchups.playoffs.build_final_placements` already
  specify for empty input.
- **Unmapped owners, zero-games rosters, and internally inconsistent
  brackets/frames**: handled exactly as documented in the composed module,
  including ``ValueError`` propagating unchanged from ``build_schedule_luck``
  (via ``strength_of_schedule``/``power_rankings``) or ``build_final_placements``
  for a self-contradictory input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from fantasy_analyzer.analytics.all_play import build_all_play_standings
from fantasy_analyzer.analytics.consistency import (
    BOOM_BUST_THRESHOLD_STDEVS,
    build_consistency_metrics,
)
from fantasy_analyzer.analytics.power_rankings import build_power_rankings
from fantasy_analyzer.analytics.schedule_luck import build_schedule_luck
from fantasy_analyzer.analytics.strength_of_schedule import build_strength_of_schedule
from fantasy_analyzer.analytics.weekly_scores import build_weekly_scoring_ranks
from fantasy_analyzer.matchups.playoffs import (
    build_final_placements,
    build_playoff_brackets,
)


@dataclass(frozen=True)
class LeagueAnalytics:
    """Thin composition service over a season's normalized matchups (FFA-057).

    ``LeagueAnalytics`` performs no network access and defines no new metrics
    -- it is a convenience layer giving callers the ``analysis.all_play()`` /
    ``analysis.schedule_luck()`` / ``analysis.consistency()`` /
    ``analysis.strength_of_schedule()`` / ``analysis.power_rankings()``
    entrypoints AGENTS.md describes for Epic 6, backed entirely by FFA-050
    through FFA-056. See the module docstring for the input rationale (including
    the optional raw playoff-bracket fields), the eager/lazy caching split, why
    ``playoff_brackets()``/``final_placements()`` are included despite not being
    in AGENTS.md's example list, and the combined regular-season-plus-playoff
    scope inherited from its inputs.

    Attributes:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used to resolve owner
            labels.
        winners_bracket_raw: Raw Sleeper winners-bracket matches, exactly as
            returned by ``SleeperClient.get_winners_bracket``, or ``None`` if
            not (yet) available. Defaults to ``None``.
        losers_bracket_raw: Raw Sleeper losers-bracket matches, or ``None``.
            Defaults to ``None``.
        weekly_scoring_ranks_df: FFA-050's full ``WEEKLY_SCORING_RANK_COLUMNS``
            table, computed once at construction. See
            :meth:`~LeagueAnalytics.all_play` and
            :meth:`~LeagueAnalytics.consistency` for the methods that reuse it.
    """

    season_matchup_df: pd.DataFrame
    teams_df: pd.DataFrame
    winners_bracket_raw: Optional[list[dict]] = None
    losers_bracket_raw: Optional[list[dict]] = None
    weekly_scoring_ranks_df: pd.DataFrame = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "weekly_scoring_ranks_df",
            build_weekly_scoring_ranks(self.season_matchup_df, self.teams_df),
        )

    def all_play(self) -> pd.DataFrame:
        """Return season-long all-play standings (FFA-051).

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.all_play.build_all_play_standings`
        over the cached ``weekly_scoring_ranks_df``. See that function's
        docstring for the metric definitions, the varying-field-size caveat,
        and the zero-comparison/missing-value rules.
        """
        return build_all_play_standings(self.weekly_scoring_ranks_df)

    def schedule_luck(self) -> pd.DataFrame:
        """Return expected wins and schedule luck (FFA-052).

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
        over ``season_matchup_df``/``teams_df``. This is deliberately *not*
        built from the cached ``weekly_scoring_ranks_df`` -- see the module
        docstring's "Eager weekly scoring ranks, lazy everything else" section
        for why that function's own single-frame design must be preserved.
        See ``schedule_luck.py`` for the exact expected-wins/schedule-luck
        formulas, the sign convention (positive = lucky), and the
        games-played-is-decisions-not-weeks rule.
        """
        return build_schedule_luck(self.season_matchup_df, self.teams_df)

    def consistency(
        self, boom_bust_threshold: float = BOOM_BUST_THRESHOLD_STDEVS
    ) -> pd.DataFrame:
        """Return team consistency metrics (FFA-053).

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.consistency.build_consistency_metrics`
        over the cached ``weekly_scoring_ranks_df``. See that function's
        docstring for the metric definitions, the population-standard-deviation
        choice, and the minimum week counts below which a column is ``NaN``.

        Args:
            boom_bust_threshold: How many of a roster's own standard
                deviations a week must exceed to count as a boom or a bust.
                Defaults to
                :data:`~fantasy_analyzer.analytics.consistency.BOOM_BUST_THRESHOLD_STDEVS`.
        """
        return build_consistency_metrics(
            self.weekly_scoring_ranks_df, boom_bust_threshold=boom_bust_threshold
        )

    def strength_of_schedule(self) -> pd.DataFrame:
        """Return average faced-opponent strength (FFA-054).

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.strength_of_schedule.build_strength_of_schedule`
        over ``season_matchup_df``/``teams_df``. Not built from the cached
        ``weekly_scoring_ranks_df`` -- see the module docstring's caching
        section. See ``strength_of_schedule.py`` for the two opponent-strength
        measures reported, the rank-1-is-toughest convention, and the
        bye-versus-unresolvable-opponent distinction.
        """
        return build_strength_of_schedule(self.season_matchup_df, self.teams_df)

    def power_rankings(self) -> pd.DataFrame:
        """Return the documented, transparent power ranking model (FFA-056).

        Thin passthrough to
        :func:`~fantasy_analyzer.analytics.power_rankings.build_power_rankings`
        over ``season_matchup_df``/``teams_df``. Not built from the cached
        ``weekly_scoring_ranks_df`` -- see the module docstring's caching
        section. See ``power_rankings.py`` for the included features, weights,
        z-score scaling, and why ``schedule_luck``, consistency metrics, and
        FFA-055's final placements are deliberately excluded from the
        composite.
        """
        return build_power_rankings(self.season_matchup_df, self.teams_df)

    def playoff_brackets(self) -> pd.DataFrame:
        """Return the normalized combined playoff bracket (FFA-055).

        Thin passthrough to
        :func:`~fantasy_analyzer.matchups.playoffs.build_playoff_brackets` over
        ``winners_bracket_raw``/``losers_bracket_raw``. Returns an empty,
        correctly-shaped frame if neither was supplied at construction. See
        ``matchups/playoffs.py`` for the raw-field mapping and the
        ``winner_placement``/``loser_placement`` convention.
        """
        return build_playoff_brackets(self.winners_bracket_raw, self.losers_bracket_raw)

    def final_placements(self) -> pd.DataFrame:
        """Return each roster's final placement (FFA-055).

        Thin passthrough to
        :func:`~fantasy_analyzer.matchups.playoffs.build_final_placements`,
        built from this service's own :meth:`~LeagueAnalytics.playoff_brackets`
        (not re-fetched or independently derived) and ``teams_df``. See
        ``matchups/playoffs.py`` for why an undetermined placement is never
        inferred, and for the data-integrity ``ValueError`` this can raise.
        """
        return build_final_placements(self.playoff_brackets(), self.teams_df)


def build_league_analytics(
    season_matchup_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    winners_bracket_raw: Optional[list[dict]] = None,
    losers_bracket_raw: Optional[list[dict]] = None,
) -> LeagueAnalytics:
    """Build a :class:`LeagueAnalytics` from already-built season inputs.

    Pure composition function, consistent with
    :func:`~fantasy_analyzer.analytics.matchup_history.build_matchup_history`'s
    pattern: no network access, callers are responsible for building
    ``season_matchup_df`` first (see
    :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`)
    and for fetching any raw playoff-bracket payloads themselves (see
    :func:`~fantasy_analyzer.matchups.playoffs.load_playoff_brackets`).

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame of
            the season's matchups.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``.
        winners_bracket_raw: Raw Sleeper winners-bracket matches, or ``None``
            if not available. Defaults to ``None``.
        losers_bracket_raw: Raw Sleeper losers-bracket matches, or ``None``.
            Defaults to ``None``.

    Returns:
        A :class:`LeagueAnalytics` with its ``weekly_scoring_ranks_df``
        already computed.
    """
    return LeagueAnalytics(
        season_matchup_df=season_matchup_df,
        teams_df=teams_df,
        winners_bracket_raw=winners_bracket_raw,
        losers_bracket_raw=losers_bracket_raw,
    )
