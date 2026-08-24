"""Define the provider-agnostic weekly player-stats interface (FFA-060).

AGENTS.md's Epic 7 preamble is explicit that the analytics layer must not
depend directly on nflverse "or any other single provider" -- FFA-061's
nflverse ingestion, and any provider added after it, must be swappable
behind one seam. This module defines that seam: :class:`PlayerStatsProvider`,
the contract a provider implements to supply weekly player statistics, and
:data:`PLAYER_WEEK_IDENTITY_COLUMNS`, the provider-agnostic subset of
AGENTS.md's "Canonical Player-Week Dataset" that every provider's output
must carry.

This module implements no provider. FFA-061 (nflverse), FFA-062 (the
Sleeper<->nflverse ID crosswalk), and FFA-063 (league scoring) are deliberately
out of scope here; see "What this interface does *not* cover" below for
where each of those seams onto this one.

``Protocol``, not ``ABC``
--------------------------

Python offers two conventional ways to define "a provider must implement
this": an abstract base class (``abc.ABC`` + ``@abstractmethod``), which a
provider subclasses, or a :class:`typing.Protocol`, which a provider
satisfies structurally by simply having the right method signature.

This module uses ``Protocol`` (``@runtime_checkable``, so ``isinstance``
checks work for callers who want them). Two reasons:

1. **Ownership crosses roles.** Per AGENTS.md, this interface belongs to the
   Software Engineer role, but FFA-061's nflverse provider belongs to the
   Data Engineer role and lives in a different, not-yet-written module. An
   ``ABC`` would make that future module import *this* one and inherit from
   it just to satisfy the contract. A ``Protocol`` lets any object --
   including the fake used in this module's own tests, and any future real
   provider -- satisfy the interface just by having a matching
   ``weekly_stats`` method, with no import-time coupling in either
   direction.
2. **It matches the rest of the codebase.** No other module here uses
   ``abc.ABC``; the established pattern (``SleeperClient``,
   ``LeagueSnapshot``, ``MatchupHistory``, ...) is plain classes and
   dataclasses duck-typed by shape, not by inheritance. A ``Protocol`` is the
   ``typing``-checked version of that same convention.

Method shape: ``weekly_stats(season, week) -> pd.DataFrame``
---------------------------------------------------------------

One method, one week at a time, mirroring how Sleeper's own matchup
endpoints are fetched (see ``SleeperClient.get_matchups(league_id, week)``
and ``matchups.loader.load_season_matchups``, which loops weeks rather than
asking a client for a whole season in one call). A per-week call keeps a
provider's job small and cacheable one week at a time, and lets a season-
level loader (a future FFA-061 concern, not this one) decide how to loop
and cache weeks -- this interface does not prescribe that.

Return shape: a DataFrame, not a list of dataclasses
-------------------------------------------------------

AGENTS.md's Canonical Player-Week Dataset is a *table*, and every other
canonical dataset in this codebase (``SEASON_MATCHUP_COLUMNS``,
``HEAD_TO_HEAD_COLUMNS``, ...) is returned as a ``pandas.DataFrame`` with a
documented, ordered column list rather than a list of per-row objects. This
interface follows that precedent so a provider's output can be concatenated
across weeks and merged against other canonical frames (rosters, scoring
settings) without an extra conversion step.

What this interface requires: identity columns only
--------------------------------------------------------

:data:`PLAYER_WEEK_IDENTITY_COLUMNS` -- ``season``, ``week``,
``sleeper_player_id``, ``gsis_id``, ``player_name``, ``position``,
``nfl_team`` -- are the columns every provider's ``weekly_stats`` result
must carry, always in that order as a prefix. Per-stat columns
(``passing_yds``, ``receptions``, etc.) are deliberately **not** part of
this required list: AGENTS.md says its own Canonical Player-Week Dataset
"is not exhaustive," and different providers expose different stat
categories (or different names for the same category). Requiring a fixed
stat schema here would bake one provider's shape into a supposedly
provider-agnostic interface -- exactly what this ticket exists to avoid. A
provider is free to add any additional numeric columns after the identity
prefix; callers that need a specific stat should check for that column by
name rather than assume every provider supplies it.

``sleeper_player_id`` may be missing
------------------------------------------

A provider's *native* per-player identifier is whatever its own source
uses -- for the eventual nflverse provider, that is ``gsis_id``, not a
Sleeper ID. Mapping a provider's native ID back to Sleeper's
``player_id`` is FFA-062's job (the "Sleeper to nflverse ID crosswalk"), a
separate ticket this one must not implement. Consequently
``sleeper_player_id`` is part of the *required schema* (the column must
exist, so downstream joins can rely on it being present) but is not
required to be *populated*: a provider with no crosswalk available returns
``None`` for it, exactly as :func:`fantasy_analyzer.league.players.resolve_player`
returns ``None`` fields rather than raising for an ID it cannot resolve.
(Once that ``None`` lands in a DataFrame column it may surface as ``NaN``
depending on pandas' inferred dtype -- callers should check with
``pandas.isna()``, the convention already used elsewhere in this codebase,
rather than ``is None``.) The same convention applies to ``gsis_id`` for a
provider whose native ID is a Sleeper ID instead.

Missing values / edge cases
----------------------------

- **A week nflverse/the provider has no data for** (future season, bye
  week already past, data not yet published): ``weekly_stats`` returns an
  *empty* DataFrame with :data:`PLAYER_WEEK_IDENTITY_COLUMNS`, not an
  exception. A "no data yet" week is an expected, queryable outcome -- the
  same convention ``build_season_matchup_df`` uses for an empty
  ``outcomes`` list -- not an error condition.
- **A player the provider cannot identify at all** (no usable ID or name):
  is a provider concern, not one this interface enforces. A provider may
  choose to omit such a row or include it with only the fields it has;
  either is legal against this contract as long as the required columns
  exist.
- **A player who did not play that week**: simply has no row.
  ``weekly_stats`` is a fact table of observed player-weeks, not a roster
  cross-product -- there is no "player not found, fields None" row for
  this case (contrast with the per-ID ``resolve_player`` above, which is
  always asked about a *specific* ID and must answer for it). A caller
  checking whether a specific player produced no data that week does so by
  the absence of a matching ``(season, week, sleeper_player_id)`` row, not
  by a sentinel row.
- **Invalid ``season``/``week``** (e.g. negative, ``week=0``): this
  interface does not define a validation contract; a provider may raise or
  return empty at its own discretion, and this is left for FFA-061 to
  document against the concrete provider it introduces.

What this interface does *not* cover
------------------------------------------

- **FFA-061 (nflverse provider)**: no concrete provider is implemented
  here. See :class:`FakePlayerStatsProvider` in this module's tests for an
  in-memory stand-in used only to prove the interface is usable.
- **FFA-062 (ID crosswalk)**: resolving a provider's native ID to
  ``sleeper_player_id`` (or vice versa) is out of scope; see
  "``sleeper_player_id`` may be missing" above.
- **FFA-063 (league scoring)**: this interface returns raw per-stat
  counts, never a ``fantasy_points`` column -- turning those counts into
  points requires the league's own scoring settings, which a
  provider-agnostic interface must not assume.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

#: Columns every :meth:`PlayerStatsProvider.weekly_stats` result must carry,
#: in this order, as a prefix -- the provider-agnostic identity subset of
#: AGENTS.md's Canonical Player-Week Dataset. See the module docstring for
#: why per-stat columns (``passing_yds``, ``receptions``, etc.) are
#: deliberately excluded from this required list.
PLAYER_WEEK_IDENTITY_COLUMNS = [
    "season",
    "week",
    "sleeper_player_id",
    "gsis_id",
    "player_name",
    "position",
    "nfl_team",
]


@runtime_checkable
class PlayerStatsProvider(Protocol):
    """Structural interface for a source of weekly player statistics.

    Any object with a matching ``weekly_stats`` method satisfies this
    interface -- no inheritance required. See the module docstring for why
    a ``Protocol`` is used instead of an ``abc.ABC``, and for the full
    contract (required columns, missing-value conventions, regular season
    vs. playoff scope) a conforming ``weekly_stats`` implementation must
    honor.
    """

    def weekly_stats(self, season: int, week: int) -> pd.DataFrame:
        """Return one week's player statistics in the canonical shape.

        Args:
            season: The NFL season, e.g. ``2025``.
            week: The NFL week number within ``season``. This interface
                makes no regular-season-vs-playoff distinction of its own
                -- NFL weeks are a single continuous sequence, unlike
                Sleeper's fantasy-league ``matchup_id`` weeks -- a provider
                simply returns whatever player statistics exist for that
                week number.

        Returns:
            A DataFrame whose columns begin with
            :data:`PLAYER_WEEK_IDENTITY_COLUMNS`, in that order, optionally
            followed by any number of provider-specific per-stat columns
            (e.g. ``passing_yds``, ``receptions``). One row per observed
            player-week; a player who did not play that week has no row.
            An empty DataFrame (same columns, zero rows) if the provider
            has no data for ``season``/``week`` -- this is an expected
            outcome, not an error. See the module docstring's "Missing
            values / edge cases" for the full set of conventions,
            including that ``sleeper_player_id`` and ``gsis_id`` may
            individually be ``None`` per row.
        """
        ...


def validate_player_week_columns(stats: pd.DataFrame) -> None:
    """Check that ``stats`` carries the required player-week identity columns.

    A lightweight contract check for a :class:`PlayerStatsProvider`
    implementation (real or fake): confirms
    :data:`PLAYER_WEEK_IDENTITY_COLUMNS` are all present, in order, as a
    prefix of ``stats.columns``. It does not check row values -- individual
    identity fields (e.g. ``sleeper_player_id``) are legitimately ``None``
    per the module docstring, and any additional per-stat columns are
    provider-specific and unconstrained by this interface.

    Args:
        stats: A DataFrame as returned by
            :meth:`PlayerStatsProvider.weekly_stats`.

    Raises:
        ValueError: If any of :data:`PLAYER_WEEK_IDENTITY_COLUMNS` is
            missing, or the leading columns of ``stats`` are out of order.
    """
    actual_prefix = list(stats.columns[: len(PLAYER_WEEK_IDENTITY_COLUMNS)])
    if actual_prefix != PLAYER_WEEK_IDENTITY_COLUMNS:
        missing = [
            column
            for column in PLAYER_WEEK_IDENTITY_COLUMNS
            if column not in stats.columns
        ]
        if missing:
            raise ValueError(
                "Player-week stats DataFrame is missing required identity "
                f"column(s): {missing}."
            )
        raise ValueError(
            "Player-week stats DataFrame's leading columns must be "
            f"{PLAYER_WEEK_IDENTITY_COLUMNS} (in order); got {actual_prefix}."
        )
