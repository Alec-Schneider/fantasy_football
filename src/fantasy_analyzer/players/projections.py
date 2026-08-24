"""Define the provider-agnostic projection/ranking interface (FFA-072).

AGENTS.md lists six future capabilities under this ticket -- projections,
rest-of-season rankings, waiver recommendations, trade values, start/sit
recommendations, and opponent adjustments -- and is explicit that "vendor-
specific logic" must not be implemented yet. This module is the seam those
six features will eventually sit behind: :class:`ProjectionProvider`, the
contract a projection vendor implements to supply forward-looking player
projections, and :data:`PROJECTION_IDENTITY_COLUMNS`, the provider-agnostic
columns every conforming provider's output must carry.

This module implements no vendor, no ranking methodology, and no trade-value
math. See "What this interface does *not* cover" below for exactly what is
and is not in scope, and how each of the six future capabilities would
eventually consume this seam.

Parallels ``players/provider.py`` (FFA-060) deliberately
-------------------------------------------------------------

FFA-060 already solved "how does this codebase define a provider-agnostic
data seam" for weekly player *statistics*. This ticket is the same problem
for player *projections*, so this module mirrors ``provider.py``'s shape --
``Protocol``, DataFrame return type, an identity-column prefix constant, a
``validate_*_columns`` helper -- rather than inventing a second convention.
Differences from ``provider.py`` are called out explicitly below; anything
not called out follows the same reasoning documented there.

``Protocol``, not ``ABC``
--------------------------

Same reasoning as ``provider.py``: ownership of this interface crosses
roles (it is filed under Data Engineer here, same as FFA-060), no other
module in this codebase uses ``abc.ABC``, and a ``Protocol``
(``@runtime_checkable``) lets any object -- including this module's own
test fake and any future real vendor adapter -- satisfy the contract
structurally, with no import-time coupling to this module.

Method shape: ``projections(season, week) -> pd.DataFrame``
----------------------------------------------------------------

One method, scoped exactly like :meth:`PlayerStatsProvider.weekly_stats`:
one season/week at a time. This is a deliberately small surface for a
six-item goal list; the alternative -- one method per goal (``ros_rankings``,
``waiver_recommendations``, ``trade_values``, ``start_sit_recommendations``,
``opponent_adjustments``) -- would require this ticket to invent the
methodology each of those represents (how are weekly projections combined
into a ranking? what makes a trade "fair"? what makes a start/sit
"recommended"?), which AGENTS.md explicitly says not to do yet. Every one
of those five concepts, at the level this codebase can currently define
it, reduces to "some future function of one or more weeks of
``projections()`` output plus other already-canonical inputs (rosters,
:mod:`fantasy_analyzer.players.player_value`, free-agent lists)":

- **Rest-of-season rankings**: a future function would call
  ``projections(season, week)`` for each remaining week of the season and
  aggregate per player -- the aggregation rule (sum? weighted by games
  remaining? regressed toward season-long value?) is future methodology,
  not defined here.
- **Waiver recommendations**: a future function would compare
  ``projections()`` for rostered players against unrostered players (a
  roster join this interface does not perform) plus positional need.
- **Trade values**: a future function would combine (rest-of-season)
  projections with realized value (FFA-068's
  :func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`)
  -- how to weight projected-future vs. realized-past value is future
  methodology.
- **Start/sit recommendations**: a future function would compare
  ``projections()`` rows for players on one manager's roster for a single
  ``week``, plausibly reusing FFA-067's
  :mod:`fantasy_analyzer.players.lineup_efficiency` optimizer, but with
  projected rather than realized points -- not implemented here.
- **Opponent adjustments**: a provider *may* choose to publish an
  opponent-context column (e.g., an ``opponent_nfl_team`` or
  ``opponent_position_rank_allowed`` column) as one of the unconstrained
  additional columns described below; this interface neither requires nor
  forbids that, and defines no methodology for how such a column should be
  used to adjust a projection.

None of the above is implemented by this ticket. This module defines only
the one method every one of those future functions would need as an input:
a single week's raw projection rows.

Return shape: a DataFrame, not a list of dataclasses
-------------------------------------------------------

Same reasoning as ``provider.py``: every canonical dataset in this codebase
is a ``pandas.DataFrame`` with a documented, ordered column list, so a
provider's output can be concatenated across weeks (the mechanism the
"rest-of-season" bullet above depends on) and merged against other
canonical frames without an extra conversion step.

What this interface requires: identity columns only
--------------------------------------------------------

:data:`PROJECTION_IDENTITY_COLUMNS` -- ``season``, ``week``, ``source``,
``sleeper_player_id``, ``gsis_id``, ``player_name``, ``position``,
``nfl_team`` -- are the columns every provider's ``projections`` result must
carry, always in that order as a prefix. As with
:data:`~fantasy_analyzer.players.provider.PLAYER_WEEK_IDENTITY_COLUMNS`, no
projection *value* column (e.g. a ``projected_points`` or
``projected_passing_yds``) is required: different vendors project different
things (a single fantasy-points number, per-stat-category projections,
floor/ceiling ranges, confidence intervals), and AGENTS.md says not to bake
vendor-specific logic into this interface yet. A provider is free to add any
additional columns after the identity prefix; callers that need a specific
projection value should check for that column by name rather than assume
every provider supplies it. Turning a per-stat-category projection into a
league-scored ``projected_fantasy_points`` is future work analogous to
FFA-063's :mod:`fantasy_analyzer.players.scoring`, not this interface's job.

``source``: the one column this list adds beyond ``PLAYER_WEEK_IDENTITY_COLUMNS``
------------------------------------------------------------------------------------

Weekly *statistics* (FFA-060) describe an observed, objective fact -- there
is exactly one true value for "how many receiving yards did this player have
in week 3." A *projection* is inherently a methodology's opinion about the
future, and a caller may reasonably want projections from more than one
vendor/model side by side (to compare, average, or pick a preferred source).
``source`` -- a short provider/methodology label such as ``"nflverse"`` or
a future vendor's name -- lets rows from different providers coexist in one
concatenated frame without colliding on ``(season, week, sleeper_player_id)``,
and lets a caller filter or group by it. It is placed immediately after
``season``/``week`` (and before the player-identity columns) because, like
``season``/``week``, it is a dimension of *which row this is describing*
rather than *who the row is about*. A single-vendor caller that does not
care about this distinction may simply pass the same constant ``source``
value for every row it returns.

``sleeper_player_id`` may be missing
------------------------------------------

Identical convention to ``provider.py``: a provider's native per-player
identifier is whatever its own source uses. Mapping that native ID to
``sleeper_player_id`` (FFA-062's crosswalk) is not this interface's job, so
``sleeper_player_id`` is part of the required *schema* (the column must
exist) but not required to be *populated* -- a provider with no crosswalk
available returns ``None`` for it, checked with ``pandas.isna()`` per the
same convention used throughout this codebase. The same applies to
``gsis_id`` for a provider whose native ID is a Sleeper ID instead.

Missing values / edge cases
----------------------------

- **A season/week the provider has no projections for** (too far in the
  future for the vendor's model horizon, before the vendor has published
  that week, or a past week no longer relevant): ``projections`` returns an
  *empty* DataFrame with :data:`PROJECTION_IDENTITY_COLUMNS`, not an
  exception -- the same "no data yet is an expected outcome" convention
  ``weekly_stats`` uses.
- **A player the provider projects zero involvement for, or cannot
  identify**: a provider concern, not one this interface enforces. A
  provider may omit such a row, or include it with only the fields it has;
  either is legal as long as the required columns exist.
- **A player with no projection row for a requested week**: has no row.
  Like ``weekly_stats``, this is a fact table of published projections, not
  a roster cross-product -- a caller checking whether a specific player was
  projected that week does so by the absence of a matching
  ``(season, week, source, sleeper_player_id)`` row, not a sentinel row.
- **Invalid ``season``/``week``**: this interface does not define a
  validation contract; a provider may raise or return empty at its own
  discretion, left for whichever future ticket introduces the first
  concrete provider to document.

What this interface does *not* cover
------------------------------------------

- **No concrete provider**: no vendor integration is implemented here. See
  :class:`FakeProjectionProvider` in this module's tests for an in-memory
  stand-in used only to prove the interface is usable.
- **No ranking methodology**: "rest-of-season rankings" is not implemented;
  see the "Method shape" section above for how a future ticket would build
  one on top of ``projections()``.
- **No waiver-recommendation logic**: comparing rostered vs. unrostered
  projected value is not implemented here.
- **No trade-value math**: combining projected and realized value into a
  single trade-value number is not implemented here.
- **No start/sit recommendation logic**: comparing teammates' projections
  for a single week/roster is not implemented here.
- **No opponent-adjustment methodology**: this interface neither requires
  nor computes an opponent-adjusted projection; see the "source" bullet
  above for the one optional column hook a provider may use.
- **No league scoring**: like ``weekly_stats``, this interface never
  requires a ``fantasy_points``-shaped column; turning raw projected stats
  into league-scored points is FFA-063's :mod:`fantasy_analyzer.players.scoring`
  concern, reused by a future consumer, not reimplemented here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

#: Columns every :meth:`ProjectionProvider.projections` result must carry,
#: in this order, as a prefix -- the provider-agnostic identity subset every
#: projection provider's output must share. See the module docstring for why
#: no projection *value* column is part of this required list, and for why
#: ``source`` is included here even though it has no analog in
#: :data:`~fantasy_analyzer.players.provider.PLAYER_WEEK_IDENTITY_COLUMNS`.
PROJECTION_IDENTITY_COLUMNS = [
    "season",
    "week",
    "source",
    "sleeper_player_id",
    "gsis_id",
    "player_name",
    "position",
    "nfl_team",
]


@runtime_checkable
class ProjectionProvider(Protocol):
    """Structural interface for a source of forward-looking player projections.

    Any object with a matching ``projections`` method satisfies this
    interface -- no inheritance required. See the module docstring for why
    a ``Protocol`` is used instead of an ``abc.ABC``, why the method surface
    is a single per-week lookup rather than one method per AGENTS.md goal,
    and for the full contract (required columns, missing-value conventions)
    a conforming ``projections`` implementation must honor.
    """

    def projections(self, season: int, week: int) -> pd.DataFrame:
        """Return one week's player projections in the canonical shape.

        Args:
            season: The NFL season, e.g. ``2025``.
            week: The NFL week number within ``season``. As with
                :meth:`~fantasy_analyzer.players.provider.PlayerStatsProvider.weekly_stats`,
                this interface makes no regular-season-vs-playoff
                distinction of its own; a provider simply returns whatever
                projections it has published for that week number.

        Returns:
            A DataFrame whose columns begin with
            :data:`PROJECTION_IDENTITY_COLUMNS`, in that order, optionally
            followed by any number of provider-specific projection columns
            (e.g. ``projected_points``, ``projected_passing_yds``, a
            floor/ceiling range). One row per published player projection;
            a player the provider does not project that week has no row.
            An empty DataFrame (same columns, zero rows) if the provider has
            no projections for ``season``/``week`` -- an expected outcome,
            not an error. See the module docstring's "Missing values /
            edge cases" for the full set of conventions, including that
            ``sleeper_player_id`` and ``gsis_id`` may individually be
            ``None`` per row.
        """
        ...


def validate_projection_columns(projections: pd.DataFrame) -> None:
    """Check that ``projections`` carries the required identity columns.

    A lightweight contract check for a :class:`ProjectionProvider`
    implementation (real or fake): confirms
    :data:`PROJECTION_IDENTITY_COLUMNS` are all present, in order, as a
    prefix of ``projections.columns``. It does not check row values --
    individual identity fields (e.g. ``sleeper_player_id``) are legitimately
    ``None`` per the module docstring, and any additional projection-value
    columns are provider-specific and unconstrained by this interface.

    Args:
        projections: A DataFrame as returned by
            :meth:`ProjectionProvider.projections`.

    Raises:
        ValueError: If any of :data:`PROJECTION_IDENTITY_COLUMNS` is
            missing, or the leading columns of ``projections`` are out of
            order.
    """
    actual_prefix = list(projections.columns[: len(PROJECTION_IDENTITY_COLUMNS)])
    if actual_prefix != PROJECTION_IDENTITY_COLUMNS:
        missing = [
            column
            for column in PROJECTION_IDENTITY_COLUMNS
            if column not in projections.columns
        ]
        if missing:
            raise ValueError(
                "Projection DataFrame is missing required identity "
                f"column(s): {missing}."
            )
        raise ValueError(
            "Projection DataFrame's leading columns must be "
            f"{PROJECTION_IDENTITY_COLUMNS} (in order); got {actual_prefix}."
        )
