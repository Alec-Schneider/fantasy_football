"""Compose Epic 7's player and positional analytics into one interface (FFA-071).

This module is pure composition: it wires FFA-064 through FFA-070's
already-built, already-documented builders into the ergonomic
``analysis.player_weekly_df`` / ``analysis.player_season_df`` /
``analysis.position_summary_df`` / ``analysis.roster_efficiency_df`` /
``analysis.player_value_df`` interface AGENTS.md describes for Epic 7. It is
the Epic 7 analog of
:mod:`fantasy_analyzer.analytics.league_analytics` (Epic 6's
``LeagueAnalytics``) and follows the same shape: a frozen dataclass over
already-built inputs, thin accessors that delegate to the ``build_*``
functions, and a ``build_*`` factory.

It performs no network access and defines **no new metrics**. Every number it
returns is copied verbatim from one of the modules below; see
``players/player_week.py``, ``players/performance.py``,
``players/position_strength.py``, ``players/lineup_efficiency.py``,
``players/player_value.py``, ``players/matchup_contribution.py``, and
``players/lineup_tendencies.py`` for every metric definition and edge-case
rule this module inherits unchanged.

It lives in ``players/`` rather than ``analytics/`` because every builder it
composes does, and because AGENTS.md assigns "positional analysis and roster
efficiency" to the ``players`` package.

Inputs: the already-built fact table, not a provider or a snapshot
--------------------------------------------------------------------

:class:`PlayerAnalytics` takes ``player_week_df`` -- FFA-064's fact table,
i.e. :attr:`~fantasy_analyzer.players.player_week.PlayerWeekFactTable.player_week_df`
-- directly, mirroring ``LeagueAnalytics``' choice to take ``season_matchup_df``
rather than a ``SleeperClient``. Building the fact table is the step that needs
a :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider` (and
therefore possibly the network), so callers do that first, exactly as
:func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`
documents. Callers should also inspect that call's
``unsupported_scoring_keys`` before handing the frame here: this module
cannot see whether the league's scoring rules were fully applied, and every
frame below inherits whatever ``fantasy_points`` it is given.

The two remaining inputs are league structure, not data:

- ``roster_positions`` -- the league's ordered roster-slot list, e.g.
  ``LeagueSnapshot.roster_positions``. Required by FFA-067's optimizer and
  FFA-068's starter cutoff.
- ``num_teams`` -- the league's team count, e.g.
  ``LeagueSnapshot.league.total_rosters``. Required by FFA-068's starter
  cutoff. It is typed ``Optional[int]`` because ``total_rosters`` itself is
  optional; ``None`` is passed through unchanged and lands on
  ``player_value.py``'s documented worst-rostered baseline rather than
  raising here.

A :class:`~fantasy_analyzer.league.snapshot.LeagueSnapshot` is deliberately
*not* accepted in its place, for the reason ``league_analytics.py`` gives:
these two scalars are all the composed builders need, so requiring a snapshot
would drag league normalization into a composition layer AGENTS.md wants kept
separate from data access.

One further input is data rather than league structure, and is optional:

- ``season_matchup_df`` -- FFA-033's normalized matchup frame, i.e.
  :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`'s
  output. Only FFA-069's two frames
  (:attr:`~PlayerAnalytics.player_contribution_df` and
  :attr:`~PlayerAnalytics.positional_advantage_df`) read it; the other twelve
  never touch it. It therefore defaults to ``None``, following ``num_teams``'
  precedent for an optional constructor field, so that every caller who only
  wants player/position frames can still build this service from a fact table
  alone -- and so that every call site written before it existed stays valid.
  For the same reason it is declared **last**, after the two threshold
  fields: inserting it earlier would silently re-bind an existing positional
  call.

When ``season_matchup_df`` is ``None``, reading either FFA-069 frame raises
``ValueError`` naming the missing input. Returning an empty frame instead
would be worse than useless here: an empty frame is exactly what those
builders legitimately return when no roster-week qualifies, so a caller who
simply forgot the argument would get a plausible-looking "no contributions"
answer rather than an error. Nothing is partially computed either -- FFA-069
takes the recorded score, opponent, and result from ``season_matchup_df`` and
never recomputes them from ``player_week_df``, so without it there is no
subset of those columns this module could honestly fill in.

Attributes, not methods
-------------------------

Unlike ``LeagueAnalytics``' ``analysis.all_play()`` methods, every frame here
is exposed as an attribute -- ``analysis.player_value_df``, not
``analysis.player_value_df()`` -- because that is the interface FFA-071's
ticket text specifies. Two consequences:

- The boom/bust thresholds FFA-065 and FFA-066 accept cannot be per-call
  arguments (an attribute takes none), so they are **constructor fields**:
  ``player_boom_bust_threshold`` and ``position_boom_bust_threshold``, each
  defaulting to its own module's documented constant. A caller wanting two
  thresholds builds two instances, the same "construct a new instance from
  different inputs" pattern this package uses everywhere else.
- The one input frame keeps its conventional name, ``player_week_df``, as
  the constructor field (that is what every builder calls its parameter);
  :attr:`~PlayerAnalytics.player_weekly_df` is the ticket's name for the same
  frame and returns it unchanged, with no copy and no computation.

Eager ``player_season_df``, lazy everything else
--------------------------------------------------

``player_season_df`` (FFA-065) is computed **once**, at construction, in
``__post_init__`` -- the same pattern ``LeagueAnalytics`` uses for
``weekly_scoring_ranks_df``, and for the same reason: it requires a full scan
of ``player_week_df``, and it is the frame this module's own accessors reuse
(both :attr:`~PlayerAnalytics.player_value_df` and
:attr:`~PlayerAnalytics.position_scarcity_df` are built from it, never from a
private rebuild), so recomputing it per access would rescan the season
repeatedly for no reason. One consequence worth stating: a negative
``player_boom_bust_threshold`` raises ``ValueError`` from the *constructor*,
while a negative ``position_boom_bust_threshold`` raises only when
:attr:`~PlayerAnalytics.position_summary_df` is first read.

Every other frame is a **lazy, per-access** passthrough that calls its own
``build_*`` function on ``player_week_df``. Nothing is memoized, so reading
one of them twice does the work twice; assign it to a local if you need it
more than once. This includes one accepted, documented duplication:
:attr:`~PlayerAnalytics.roster_efficiency_df` internally rebuilds the weekly
lineup table that :attr:`~PlayerAnalytics.lineup_efficiency_df` also builds,
because ``build_roster_efficiency_metrics`` takes ``player_week_df`` (not a
pre-built weekly frame) precisely so its season totals cannot drift out of
sync with the weekly rows they aggregate -- exactly the reasoning
``league_analytics.py`` documents for not feeding its cached frame into
``build_schedule_luck``.

The tradeoff for the one eager frame is staleness, exactly as in
``LeagueAnalytics``: ``player_season_df`` reflects ``player_week_df`` as it
was at construction, mutating the input frame afterwards is not a supported
use case, and the dataclass is frozen -- the fix is to build a new
:class:`PlayerAnalytics`.

Which frames are exposed
---------------------------

FFA-071's ticket text lists five frames; this module exposes fourteen --
one per output of every dependency it composes:

- ``player_weekly_df`` -- FFA-064's fact table, unchanged.
- ``player_season_df`` -- FFA-065's per-player-season performance table.
- ``position_summary_df`` -- FFA-066's per-``(season, fantasy_team,
  position)`` strength table. "Position summary" is read as the team-position
  view, the only per-position frame FFA-066 produces.
- ``roster_efficiency_df`` -- FFA-067's per-``(season, roster_id)`` season
  table.
- ``lineup_efficiency_df`` -- FFA-067's per-``(season, week, roster_id)``
  weekly table.
- ``player_value_df`` -- FFA-068's per-player-season value/VORP table.
- ``position_scarcity_df`` -- FFA-068's per-``(season, position)`` scarcity
  table.

The last two extras follow ``league_analytics.py``'s precedent for including
``playoff_brackets()``/``final_placements()``: leaving half of a listed
dependency unreachable would make the composition layer incomplete relative
to its own dependency list.

FFA-069 (matchup player contribution) and FFA-070 (manager lineup
tendencies), the two remaining FFA-071 dependencies, have since shipped, and
each of their frames is one more accessor in exactly the same shape as the
others. FFA-070's five need nothing this class did not already hold:

- ``roster_construction_df`` -- per-``(season, fantasy_team, position)``
  distinct players, rostered player-weeks, and roster share.
- ``bench_allocation_df`` -- per-``(season, fantasy_team, position)`` benched
  player-weeks and bench share.
- ``flex_usage_df`` -- per-``(season, fantasy_team, position)`` FLEX-slot
  usage in the manager's actual lineup, from ``roster_positions``.
- ``start_sit_tendency_df`` -- per-``(season, roster_id)`` start/sit rates;
  FFA-067's roster-efficiency table plus two per-week rates. Grouped by
  ``roster_id``, not ``fantasy_team``, inherited from the wrapped function.
- ``positional_preference_df`` -- per-``(season, fantasy_team, position)``
  rollup of the rostered/started/benched views.

FFA-069's two need ``season_matchup_df`` and raise ``ValueError`` without it
(see the inputs section above):

- ``player_contribution_df`` -- one row per started player per roster-week of
  a paired matchup: his points, his share of his roster's recorded score, the
  matchup context, and his rank among that roster's starters.
- ``positional_advantage_df`` -- one row per ``(season, week, roster_id,
  position)``, comparing each side's started production at that position.

``matchup_contribution.py``'s third function, ``reconcile_matchup_points``,
is deliberately **not** exposed. It is a data-quality check -- do Sleeper's
recorded scores agree with this codebase's re-derived ones -- rather than an
analytics frame, and it belongs with the fact-table build step (whose
``unsupported_scoring_keys`` is the other half of the same question), not
alongside frames a caller reads to answer a league question. Callers who want
it hold both of its inputs already and call it directly.

Regular season vs. playoffs, and one league-season at a time
---------------------------------------------------------------

This module makes no phase distinction of its own and applies no week filter
anywhere. Every builder it composes is phase-agnostic for the same structural
reason -- FFA-064's ``player_week_df`` has no ``is_playoff`` column (see each
module's own "Regular season vs. playoffs" section) -- so a caller wanting a
phase-specific view must filter ``player_week_df`` on ``week`` against the
league's playoff-start boundary (FFA-022,
``LeagueSettings.playoff_week_start``) **before** constructing a
:class:`PlayerAnalytics`, and build a separate instance per phase.
``season_matchup_df`` *does* carry ``is_playoff`` (FFA-069 copies it onto
every output row), but this module still applies no filter to it: a caller
wanting a phase-specific FFA-069 view must filter both input frames on the
same boundary, since filtering only one would compare a full-season lineup
against a playoffs-only matchup set.

Filtering here instead would be strictly worse: ``player_season_df`` is
computed at construction and feeds the value frames, so a per-attribute phase
flag could silently mix a full-season replacement baseline with a
playoffs-only player.

For the same reason as ``player_value.py``, an instance is expected to cover
**one league-season**: seasons are never pooled by any builder (each groups
by ``season``), but the league-relative frames -- ``position_summary_df``'s
``positional_rank``, ``player_value_df``'s replacement levels and
``value_rank`` -- are only meaningful when the input frame contains one
league's players. ``roster_positions``/``num_teams`` are single scalars here,
which is the same assumption made explicit.

Missing values / edge cases
------------------------------

This module inherits every edge case from the functions it composes and adds
none of its own:

- **Empty ``player_week_df``**: ``player_season_df`` is empty (with its
  documented columns and dtypes), and every other frame returns its own
  empty, correctly-shaped frame -- see each ``build_*`` function's own
  "empty input" behavior. Note ``player_weekly_df`` returns the caller's
  empty frame as-is, whatever columns it happens to carry.
- **Empty ``season_matchup_df``**: an *empty* frame is a legitimate input,
  not a missing one -- FFA-069's builders return their own empty,
  correctly-shaped frames for it, and no ``ValueError`` is raised. Only
  ``None`` (the field never supplied) raises; see below.
- **Missing ``season_matchup_df``**: :attr:`~PlayerAnalytics.player_contribution_df`
  and :attr:`~PlayerAnalytics.positional_advantage_df` raise ``ValueError``
  when it is ``None``. Every other frame, including all five FFA-070
  tendencies, is unaffected and works exactly as it does when the field is
  supplied.
- **Rostered-only row universe**: FFA-064 builds rows from Sleeper's weekly
  rosters, so free agents are absent and FFA-068's replacement baseline is
  computed from rostered players only -- see ``player_value.py``'s
  "Rostered-only caveat". Nothing here widens that universe.
- **Unresolved player identity, small samples, ties, and non-positive
  denominators**: handled exactly as documented in the composed modules
  (``NaN`` dispersion/boom-bust columns below the minimum game counts,
  standard competition ranking for ``positional_rank``/``value_rank``,
  ``NaN`` ``cv``/``efficiency_pct``/``scarcity_ratio`` for non-positive
  denominators).
- **Contract violations propagate unchanged**: a negative boom/bust
  threshold, and the ``ValueError`` ``player_value.py`` raises for duplicate
  ``(season, sleeper_player_id)`` rows or a missing required column, are
  raised by the underlying builder, not caught here. The missing-input
  ``ValueError`` above is the one error this module raises itself, and it is
  a wiring error rather than a data error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from fantasy_analyzer.players.lineup_efficiency import (
    build_lineup_efficiency_metrics,
    build_roster_efficiency_metrics,
)
from fantasy_analyzer.players.lineup_tendencies import (
    build_bench_allocation_metrics,
    build_flex_usage_metrics,
    build_positional_preference_metrics,
    build_roster_construction_metrics,
    build_start_sit_tendency_metrics,
)
from fantasy_analyzer.players.matchup_contribution import (
    build_matchup_player_contributions,
    build_positional_matchup_advantage,
)
from fantasy_analyzer.players.performance import (
    BOOM_BUST_THRESHOLD_STDEVS as PLAYER_BOOM_BUST_THRESHOLD_STDEVS,
)
from fantasy_analyzer.players.performance import (
    build_player_performance_metrics,
)
from fantasy_analyzer.players.player_value import (
    build_player_value_metrics,
    build_position_scarcity_metrics,
)
from fantasy_analyzer.players.position_strength import (
    BOOM_BUST_THRESHOLD_STDEVS as POSITION_BOOM_BUST_THRESHOLD_STDEVS,
)
from fantasy_analyzer.players.position_strength import (
    build_position_strength_metrics,
)


@dataclass(frozen=True)
class PlayerAnalytics:
    """Thin composition service over a season's player-week fact table (FFA-071).

    ``PlayerAnalytics`` performs no network access and defines no new metrics
    -- it is a convenience layer giving callers the
    ``analysis.player_weekly_df`` / ``analysis.player_season_df`` /
    ``analysis.position_summary_df`` / ``analysis.roster_efficiency_df`` /
    ``analysis.player_value_df`` entrypoints AGENTS.md describes for Epic 7,
    backed entirely by FFA-064 through FFA-070. See the module docstring for
    the input rationale, why the frames are attributes rather than methods,
    the eager/lazy split, the extra frames exposed beyond the ticket's list
    (FFA-070's five tendencies, FFA-069's two matchup frames -- which require
    the optional ``season_matchup_df`` and raise ``ValueError`` without it --
    and the second output of each FFA-067/FFA-068 pair), and the
    phase-agnostic, one-league-season scope inherited from its inputs.

    Attributes:
        player_week_df: FFA-064's
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            fact table (plus provider raw-stat columns and ``fantasy_points``
            last), as produced by
            :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`.
            Expected to cover one league-season, already filtered to the
            phase of interest.
        roster_positions: The league's ordered roster-slot list, e.g.
            ``LeagueSnapshot.roster_positions``
            (``["QB", "RB", "RB", ..., "BN", "BN"]``).
        num_teams: The number of teams in the league, e.g.
            ``LeagueSettings.total_rosters``. ``None`` is allowed (that
            field is optional) and is passed through to FFA-068 unchanged.
        player_boom_bust_threshold: Threshold, in a player's own standard
            deviations, for :attr:`player_season_df`'s boom/bust columns.
            Defaults to
            :data:`~fantasy_analyzer.players.performance.BOOM_BUST_THRESHOLD_STDEVS`.
        position_boom_bust_threshold: Threshold, in a team-position's own
            standard deviations, for :attr:`position_summary_df`'s boom/bust
            columns. Defaults to
            :data:`~fantasy_analyzer.players.position_strength.BOOM_BUST_THRESHOLD_STDEVS`.
        season_matchup_df: FFA-033's
            :data:`~fantasy_analyzer.matchups.season_matchups.SEASON_MATCHUP_COLUMNS`-shaped
            frame for the same league-season and phase, as produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
            Optional, and declared last so existing positional calls keep
            working. Only :attr:`player_contribution_df` and
            :attr:`positional_advantage_df` read it, and only they raise when
            it is ``None``.
        player_season_df: FFA-065's full
            :data:`~fantasy_analyzer.players.performance.PLAYER_PERFORMANCE_COLUMNS`
            table, computed once at construction. See :attr:`player_value_df`
            and :attr:`position_scarcity_df` for the accessors that reuse it.

    Raises:
        ValueError: From the constructor, if ``player_boom_bust_threshold``
            is negative -- propagated unchanged from
            :func:`~fantasy_analyzer.players.performance.build_player_performance_metrics`.
    """

    player_week_df: pd.DataFrame
    roster_positions: list[str]
    num_teams: Optional[int]
    player_boom_bust_threshold: float = PLAYER_BOOM_BUST_THRESHOLD_STDEVS
    position_boom_bust_threshold: float = POSITION_BOOM_BUST_THRESHOLD_STDEVS
    season_matchup_df: Optional[pd.DataFrame] = None
    player_season_df: pd.DataFrame = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "player_season_df",
            build_player_performance_metrics(
                self.player_week_df,
                boom_bust_threshold=self.player_boom_bust_threshold,
            ),
        )

    @property
    def player_weekly_df(self) -> pd.DataFrame:
        """Return the player-week fact table this service was built from (FFA-064).

        The ticket's name for ``player_week_df``, returned unchanged: no
        copy, no computation, no filtering. See ``players/player_week.py``
        for the row universe (rostered players, starters and bench), the
        identity-enrichment order, and why a rostered player who did not
        play still gets a row.
        """
        return self.player_week_df

    @property
    def position_summary_df(self) -> pd.DataFrame:
        """Return per-team, per-position strength metrics (FFA-066).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.position_strength.build_position_strength_metrics`
        over ``player_week_df``, using ``position_boom_bust_threshold``.
        Rebuilt on every access -- see the module docstring's caching
        section. See ``position_strength.py`` for the metric definitions,
        why production uses started weeks while ``positional_depth`` uses
        all rostered weeks, the ``positional_rank`` and
        ``share_of_team_points`` conventions, and the minimum week counts
        below which a column is ``NaN``.
        """
        return build_position_strength_metrics(
            self.player_week_df,
            boom_bust_threshold=self.position_boom_bust_threshold,
        )

    @property
    def lineup_efficiency_df(self) -> pd.DataFrame:
        """Return per-roster-week lineup efficiency metrics (FFA-067).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.lineup_efficiency.build_lineup_efficiency_metrics`
        over ``player_week_df``/``roster_positions``. Not listed in FFA-071's
        ticket text -- see the module docstring's "Which frames are exposed".
        See ``lineup_efficiency.py`` for the optimal-lineup definition, the
        slot-eligibility table, the deterministic tie-breaking toward the
        manager's actual lineup, and the ``NaN`` ``efficiency_pct`` guard.
        """
        return build_lineup_efficiency_metrics(
            self.player_week_df, self.roster_positions
        )

    @property
    def roster_efficiency_df(self) -> pd.DataFrame:
        """Return per-roster-season roster efficiency metrics (FFA-067).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.lineup_efficiency.build_roster_efficiency_metrics`
        over ``player_week_df``/``roster_positions``. This deliberately does
        *not* reuse :attr:`lineup_efficiency_df`: that function takes the
        fact table and rebuilds the weekly rows itself so its season totals
        cannot drift from them -- see the module docstring's caching section.
        See ``lineup_efficiency.py`` for the aggregate definitions.
        """
        return build_roster_efficiency_metrics(
            self.player_week_df, self.roster_positions
        )

    @property
    def player_value_df(self) -> pd.DataFrame:
        """Return per-player-season replacement-level value metrics (FFA-068).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`
        over the eagerly built :attr:`player_season_df` (not an independent
        rebuild) plus ``roster_positions``/``num_teams``. See
        ``player_value.py`` for the replacement-level methodology (starter
        cutoff, flex-slot convention, clamping), the points-above-average and
        points-above-replacement formulas, the ``value_rank`` tie convention,
        and the rostered-only caveat.
        """
        return build_player_value_metrics(
            self.player_season_df, self.roster_positions, self.num_teams
        )

    @property
    def position_scarcity_df(self) -> pd.DataFrame:
        """Return per-position replacement and scarcity metrics (FFA-068).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.player_value.build_position_scarcity_metrics`
        over the eagerly built :attr:`player_season_df` plus
        ``roster_positions``/``num_teams``. Not listed in FFA-071's ticket
        text -- see the module docstring's "Which frames are exposed". See
        ``player_value.py`` for the ``scarcity_ratio`` definition and its
        ``NaN`` guard for non-positive replacement levels.
        """
        return build_position_scarcity_metrics(
            self.player_season_df, self.roster_positions, self.num_teams
        )

    @property
    def roster_construction_df(self) -> pd.DataFrame:
        """Return per-team, per-position roster construction metrics (FFA-070).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.lineup_tendencies.build_roster_construction_metrics`
        over ``player_week_df``. Rebuilt on every access -- see the module
        docstring's caching section. See ``lineup_tendencies.py`` for the
        definitions of ``distinct_players``, ``rostered_player_weeks`` and
        ``roster_share``, and for why a stash who never played still counts.
        """
        return build_roster_construction_metrics(self.player_week_df)

    @property
    def bench_allocation_df(self) -> pd.DataFrame:
        """Return per-team, per-position bench allocation metrics (FFA-070).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.lineup_tendencies.build_bench_allocation_metrics`
        over ``player_week_df``. See ``lineup_tendencies.py`` for the
        ``bench_weeks``/``bench_share`` definitions and why a position the
        team never benched gets no row at all.
        """
        return build_bench_allocation_metrics(self.player_week_df)

    @property
    def flex_usage_df(self) -> pd.DataFrame:
        """Return per-team, per-position FLEX-slot usage metrics (FFA-070).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.lineup_tendencies.build_flex_usage_metrics`
        over ``player_week_df``/``roster_positions``. See
        ``lineup_tendencies.py`` for the closed-form ``flex_starts`` formula,
        which slot names count as FLEX-type, the ``flex_usage_rank`` tie
        convention, and why a league with no FLEX-type slot yields an empty
        frame rather than an error.
        """
        return build_flex_usage_metrics(self.player_week_df, self.roster_positions)

    @property
    def start_sit_tendency_df(self) -> pd.DataFrame:
        """Return per-roster-season start/sit tendency metrics (FFA-070).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.lineup_tendencies.build_start_sit_tendency_metrics`
        over ``player_week_df``/``roster_positions``. Grouped by ``(season,
        roster_id)``, not ``fantasy_team``, because it wraps FFA-067's
        :attr:`roster_efficiency_df` unchanged and adds two per-week rates
        -- so it rebuilds that frame rather than reusing this class's
        accessor, for the reason :attr:`roster_efficiency_df` documents. See
        ``lineup_tendencies.py`` for the two rate definitions.
        """
        return build_start_sit_tendency_metrics(
            self.player_week_df, self.roster_positions
        )

    @property
    def positional_preference_df(self) -> pd.DataFrame:
        """Return per-team, per-position preference rollup metrics (FFA-070).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.lineup_tendencies.build_positional_preference_metrics`
        over ``player_week_df``. A rollup of the rostered, started and
        benched views onto one row per position a team ever carried -- see
        ``lineup_tendencies.py`` for the share definitions and why it is one
        shared accumulation rather than a merge of the other frames.
        """
        return build_positional_preference_metrics(self.player_week_df)

    @property
    def player_contribution_df(self) -> pd.DataFrame:
        """Return per-started-player matchup contribution metrics (FFA-069).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.matchup_contribution.build_matchup_player_contributions`
        over ``season_matchup_df``/``player_week_df``. See
        ``matchup_contribution.py`` for the started-players-in-paired-matchups
        row universe, why ``team_points``/``margin``/``result`` are taken from
        ``season_matchup_df`` rather than recomputed, the signed-margin
        convention, and the ``contribution_rank`` tie rule.

        Raises:
            ValueError: If this service was built without a
                ``season_matchup_df``. Nothing is returned in its place; see
                the module docstring's inputs section.
        """
        return build_matchup_player_contributions(
            self._require_season_matchup_df("player_contribution_df"),
            self.player_week_df,
        )

    @property
    def positional_advantage_df(self) -> pd.DataFrame:
        """Return per-roster-week, per-position matchup advantage metrics (FFA-069).

        Thin passthrough to
        :func:`~fantasy_analyzer.players.matchup_contribution.build_positional_matchup_advantage`
        over ``season_matchup_df``/``player_week_df``. See
        ``matchup_contribution.py`` for the ``positional_advantage``
        definition, why the row set is the union of positions started by
        either side, and the FLEX-attribution scope limit.
        ``matchup_contribution.py``'s third function,
        ``reconcile_matchup_points``, is intentionally not exposed here --
        see the module docstring's "Which frames are exposed".

        Raises:
            ValueError: If this service was built without a
                ``season_matchup_df``.
        """
        return build_positional_matchup_advantage(
            self._require_season_matchup_df("positional_advantage_df"),
            self.player_week_df,
        )

    def _require_season_matchup_df(self, attribute: str) -> pd.DataFrame:
        """Return ``season_matchup_df``, or raise naming the missing input.

        An empty frame is a valid input and is returned as-is; only ``None``
        -- the field never supplied -- raises.
        """
        if self.season_matchup_df is None:
            raise ValueError(
                f"{attribute} requires season_matchup_df, which was not "
                "provided; pass season_matchup_df to PlayerAnalytics "
                "(or build_player_analytics) to use the FFA-069 matchup "
                "contribution frames"
            )
        return self.season_matchup_df


def build_player_analytics(
    player_week_df: pd.DataFrame,
    roster_positions: list[str],
    num_teams: Optional[int],
    player_boom_bust_threshold: float = PLAYER_BOOM_BUST_THRESHOLD_STDEVS,
    position_boom_bust_threshold: float = POSITION_BOOM_BUST_THRESHOLD_STDEVS,
    season_matchup_df: Optional[pd.DataFrame] = None,
) -> PlayerAnalytics:
    """Build a :class:`PlayerAnalytics` from an already-built fact table.

    Pure composition function, consistent with
    :func:`~fantasy_analyzer.analytics.league_analytics.build_league_analytics`'s
    pattern: no network access, callers are responsible for building
    ``player_week_df`` first (see
    :func:`~fantasy_analyzer.players.player_week.build_player_week_fact_table`,
    and check its ``unsupported_scoring_keys``) and for pre-filtering it to
    the season phase they want.

    Args:
        player_week_df: FFA-064's
            :data:`~fantasy_analyzer.players.player_week.PLAYER_WEEK_COLUMNS`-shaped
            fact table for one league-season.
        roster_positions: The league's ordered roster-slot list, e.g.
            ``LeagueSnapshot.roster_positions``.
        num_teams: The number of teams in the league, e.g.
            ``LeagueSettings.total_rosters``; ``None`` is allowed.
        player_boom_bust_threshold: Threshold for the boom/bust columns of
            :attr:`~PlayerAnalytics.player_season_df`. Defaults to
            :data:`~fantasy_analyzer.players.performance.BOOM_BUST_THRESHOLD_STDEVS`.
        position_boom_bust_threshold: Threshold for the boom/bust columns of
            :attr:`~PlayerAnalytics.position_summary_df`. Defaults to
            :data:`~fantasy_analyzer.players.position_strength.BOOM_BUST_THRESHOLD_STDEVS`.
        season_matchup_df: FFA-033's
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`
            output for the same league-season and phase. Optional; required
            only by :attr:`~PlayerAnalytics.player_contribution_df` and
            :attr:`~PlayerAnalytics.positional_advantage_df`, which raise
            ``ValueError`` if it was omitted.

    Returns:
        A :class:`PlayerAnalytics` with its ``player_season_df`` already
        computed.
    """
    return PlayerAnalytics(
        player_week_df=player_week_df,
        roster_positions=roster_positions,
        num_teams=num_teams,
        player_boom_bust_threshold=player_boom_bust_threshold,
        position_boom_bust_threshold=position_boom_bust_threshold,
        season_matchup_df=season_matchup_df,
    )
