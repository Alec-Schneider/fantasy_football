"""Calculate fantasy points from a league's own Sleeper scoring rules (FFA-063).

FFA-060/061's :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`
interface returns raw per-stat *counts* -- ``passing_yards``, ``receptions``,
``rushing_tds``, and so on -- and its module docstring is explicit that it
must never compute a ``fantasy_points`` column itself, because doing so
would require assuming one league's scoring rules inside a
provider-agnostic interface. This module is that next, separate step: it
takes a provider's raw-stats DataFrame (currently
:func:`fantasy_analyzer.players.nflverse_provider.normalize_player_stats`'s
output, shaped as ``PLAYER_WEEK_IDENTITY_COLUMNS`` + ``RAW_STAT_COLUMNS``)
and a league's actual ``scoring_settings`` dict (from
:attr:`fantasy_analyzer.league.settings.LeagueSettings.scoring_settings`)
and produces a ``fantasy_points`` column derived from both.

Why one generic formula covers both "per-event" and "per-unit" categories
---------------------------------------------------------------------------

Sleeper's ``scoring_settings`` values are already expressed in the unit
each category is scored in: ``pass_td: 4`` means "4 points per touchdown
*event*" (the underlying stat, ``passing_tds``, is itself a count of
events), while ``pass_yd: 0.04`` means "0.04 points per *yard*" (the
underlying stat, ``passing_yards``, is itself a continuous quantity). In
both cases the arithmetic to turn a raw stat into points is identical:

.. code-block:: text

    points_from_category = raw_stat_value * scoring_weight

There is no separate "flat" vs. "per-unit" formula to implement --
Sleeper's weight already encodes which one applies. This module therefore
uses one rule shape (:class:`_ScoringRule`) for every supported category;
see :data:`SCORING_KEY_TO_STAT_COLUMNS` for the full mapping.

Mapping table: Sleeper scoring key -> raw stat column(s)
---------------------------------------------------------

Grounded against ``tests/fixtures/sleeper/league.json``'s real
``scoring_settings`` block (``pass_yd``, ``pass_td``, ``pass_int``,
``rush_yd``, ``rush_td``, ``rec``, ``rec_yd``, ``rec_td``, ``fum_lost``, all
present there) plus a small number of additional, unambiguous Sleeper keys
whose raw stat exists in
:data:`~fantasy_analyzer.players.nflverse_provider.RAW_STAT_COLUMNS`:

=============  =====================  ===================================
Sleeper key    Raw stat column(s)     Meaning
=============  =====================  ===================================
``pass_yd``    ``passing_yards``      Points per passing yard
``pass_td``    ``passing_tds``        Points per passing touchdown
``pass_int``   ``interceptions``      Points per interception thrown
``pass_cmp``   ``completions``        Points per completion
``pass_att``   ``attempts``           Points per pass attempt
``pass_sack``  ``sacks``              Points per sack taken
``rush_att``   ``carries``            Points per rush attempt
``rush_yd``    ``rushing_yards``      Points per rushing yard
``rush_td``    ``rushing_tds``        Points per rushing touchdown
``rec``        ``receptions``         Points per reception
``rec_tgt``    ``targets``            Points per target
``rec_yd``     ``receiving_yards``    Points per receiving yard
``rec_td``     ``receiving_tds``      Points per receiving touchdown
``fum_lost``   sum of the three       Points per fumble lost, summed
               ``*_fumbles_lost``     across every fumble-lost column
               columns (sack/rush/    nflverse breaks out by play type --
               receiving)             Sleeper scores it the same either way
=============  =====================  ===================================

Deliberately **not** mapped (surfaced as unsupported, never guessed at):

- ``pass_2pt`` / ``rush_2pt`` / ``rec_2pt`` (two-point conversions): no
  two-point-conversion count exists in
  :data:`~fantasy_analyzer.players.nflverse_provider.RAW_STAT_COLUMNS`.
- ``fum`` (total fumbles, lost or not): nflverse's raw columns only expose
  fumbles *lost* per play type (``sack_fumbles_lost``,
  ``rushing_fumbles_lost``, ``receiving_fumbles_lost``); there is no "total
  fumbles" count to sum.
- ``bonus_rec_te`` (a TE-only reception bonus) and any other
  position-conditional or yardage-*tier* bonus category (e.g.
  ``bonus_rush_yd_100``): these require conditional logic beyond "multiply
  a raw stat by a weight" -- a TE bonus must apply only when
  ``position == "TE"``, and a yardage-tier bonus is a step function, not a
  linear one. Implementing either with this module's flat
  raw-stat-times-weight shape would silently produce a plausible-looking
  but wrong number for any league that uses them. Rather than risk that,
  both categories are left unmapped and therefore always surfaced via
  :attr:`ScoringResult.unsupported_scoring_keys` -- a documented gap, not a
  silent zero.
- Any IDP/defense/kicker scoring category: this provider's raw stat
  columns are offensive skill-position counting stats only (see
  ``RAW_STAT_COLUMNS``'s own docstring); no defensive or kicking raw stats
  exist to map from.

Unsupported-key policy: surfaced, not silently dropped or raised
-------------------------------------------------------------------

A league's ``scoring_settings`` may legitimately contain a key this module
has no mapping for -- either one of the deliberately-excluded categories
above, or a category this module has simply never seen (a future Sleeper
scoring option, an IDP league, a custom bonus). Per AGENTS.md's "unsupported
scoring fields are surfaced clearly" acceptance criterion, and mirroring
:func:`fantasy_analyzer.league.players.resolve_player`'s "return ``None``
rather than raise for what it cannot resolve" convention,
:func:`calculate_fantasy_points` does **not** raise for an unmapped key. It
simply excludes that key's weight from the points calculation (contributing
zero) and returns every unmapped key, sorted, as
:attr:`ScoringResult.unsupported_scoring_keys` on the result. A caller that
wants a hard failure for an unsupported league (e.g. an IDP league whose
scores would otherwise be silently wrong) can check that list itself and
raise/warn as its own use case demands; this module does not make that
policy choice on the caller's behalf.

Missing values: an absent or ``NaN`` stat contributes zero, not ``NaN``
---------------------------------------------------------------------------

Two distinct "missing" cases can reach this function, and both are treated
as "this category contributed zero points for this row" rather than
propagating ``NaN`` into ``fantasy_points``:

- **A mapped stat column is entirely absent from ``stats.columns``** (e.g.
  a caller passes a stats frame missing ``interceptions`` and the league
  scores ``pass_int``): treated as zero for every row, same as "the
  provider had nothing to say about this stat."
- **A mapped stat column exists but a specific row's value is ``NaN``**
  (e.g. ``normalize_player_stats``' "Some Rookie" case, where identity
  fields and stats alike may be missing for a poorly-identified player):
  that row's contribution from that category is treated as zero via
  ``.fillna(0)``, not propagated as ``NaN`` through arithmetic (which would
  silently turn the row's entire ``fantasy_points`` into ``NaN``).

This mirrors the "absence means zero contribution, not an error" spirit
used elsewhere in this codebase (e.g. a bye week simply has no matchup row)
rather than inventing a new convention.

Ties
-----

No special tie-breaking logic exists or is needed here: each row's
``fantasy_points`` is computed independently from that row's own raw stats
and the same ``scoring_settings`` dict, so two rows with identical inputs
necessarily produce identical, exactly-equal output (floating-point
arithmetic on the same operands in the same order). Tie handling for
*rankings built on top of* ``fantasy_points`` (e.g. "who had the highest
score this week") is a downstream analytics concern (FFA-050 and friends),
not this module's.

Regular season vs. playoffs: not this module's concern
-----------------------------------------------------------

:func:`calculate_fantasy_points` has no notion of season phase at all. It
operates on whatever rows of ``stats`` it is given -- one row is one
player's one NFL week -- and computes the same formula regardless of
whether that week falls in the regular season or the playoffs for any
particular league. This is deliberate: NFL weeks are numbered from a single
continuous season-long sequence, while "is this a playoff week" is a
per-*league* fact derived from that league's ``playoff_week_start`` (see
``matchups/playoffs.py``'s ``build_playoff_brackets``/
``build_bracket_df``, and ``LeagueSettings.playoff_week_start`` in
``league/settings.py``). Mixing that distinction into a pure
stats-to-points calculation would couple this module to a specific league's
schedule for no benefit -- the fantasy-point *math* for a given player-week
is identical either way. Any regular-season-vs-playoff filtering of the
rows fed into this function, or of the resulting ``fantasy_points`` values,
is the caller's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

#: Sleeper scoring-settings key -> the raw stat column(s), from
#: :data:`~fantasy_analyzer.players.nflverse_provider.RAW_STAT_COLUMNS`,
#: summed and multiplied by that key's weight to compute its contribution
#: to ``fantasy_points``. See the module docstring's mapping table for the
#: full rationale, including which real Sleeper keys are deliberately
#: excluded and why.
SCORING_KEY_TO_STAT_COLUMNS: dict[str, tuple[str, ...]] = {
    "pass_yd": ("passing_yards",),
    "pass_td": ("passing_tds",),
    "pass_int": ("interceptions",),
    "pass_cmp": ("completions",),
    "pass_att": ("attempts",),
    "pass_sack": ("sacks",),
    "rush_att": ("carries",),
    "rush_yd": ("rushing_yards",),
    "rush_td": ("rushing_tds",),
    "rec": ("receptions",),
    "rec_tgt": ("targets",),
    "rec_yd": ("receiving_yards",),
    "rec_td": ("receiving_tds",),
    "fum_lost": (
        "sack_fumbles_lost",
        "rushing_fumbles_lost",
        "receiving_fumbles_lost",
    ),
}


@dataclass(frozen=True)
class ScoringResult:
    """The output of :func:`calculate_fantasy_points`: points plus diagnostics.

    A plain DataFrame return would have nowhere to carry which
    ``scoring_settings`` keys this engine could not apply, and silently
    dropping that information would violate AGENTS.md's "unsupported
    scoring fields are surfaced clearly" acceptance criterion for this
    ticket. This dataclass pairs the two together so a caller cannot get
    ``points_df`` without also being handed (or deliberately ignoring)
    ``unsupported_scoring_keys``.

    Attributes:
        points_df: ``stats`` (all original columns preserved, in their
            original order) with one additional ``fantasy_points`` column
            (``float``) appended.
        unsupported_scoring_keys: The ``scoring_settings`` keys that had no
            entry in :data:`SCORING_KEY_TO_STAT_COLUMNS` and therefore
            contributed nothing to ``fantasy_points`` -- sorted for
            deterministic output. Empty if every key in ``scoring_settings``
            was applied.
    """

    points_df: pd.DataFrame
    unsupported_scoring_keys: list[str]


def calculate_fantasy_points(
    stats: pd.DataFrame, scoring_settings: Mapping[str, float]
) -> ScoringResult:
    """Compute per-row ``fantasy_points`` from raw stats and league scoring rules.

    For each row, ``fantasy_points`` is the sum, over every
    ``scoring_settings`` key this module recognizes (see
    :data:`SCORING_KEY_TO_STAT_COLUMNS`), of that key's raw stat column(s)
    (summed together, if more than one applies, e.g. ``fum_lost``)
    multiplied by that key's weight. See the module docstring for the full
    per-category mapping, the missing-value convention (absent/``NaN``
    stat -> zero contribution, never ``NaN`` propagation), and why this is
    phase-agnostic (no regular-season/playoff distinction).

    Args:
        stats: A raw per-stat DataFrame shaped like a
            :class:`~fantasy_analyzer.players.provider.PlayerStatsProvider`
            result (``PLAYER_WEEK_IDENTITY_COLUMNS`` + provider-specific
            stat columns, e.g.
            :data:`~fantasy_analyzer.players.nflverse_provider.RAW_STAT_COLUMNS`).
            Only the stat columns actually referenced by
            ``scoring_settings`` need be present; any others are ignored.
            An empty DataFrame is a legal input and yields an empty result.
        scoring_settings: A league's Sleeper scoring category -> point
            value mapping, e.g.
            ``LeagueSettings.scoring_settings``. Not mutated.

    Returns:
        A :class:`ScoringResult` pairing the points-augmented DataFrame
        with the list of ``scoring_settings`` keys this engine could not
        apply.
    """
    points_df = stats.copy()
    fantasy_points = pd.Series(0.0, index=stats.index, dtype=float)

    unsupported_scoring_keys: list[str] = []
    for key, weight in scoring_settings.items():
        stat_columns = SCORING_KEY_TO_STAT_COLUMNS.get(key)
        if stat_columns is None:
            unsupported_scoring_keys.append(key)
            continue
        for stat_column in stat_columns:
            if stat_column not in stats.columns:
                # Mapped category, but this stats frame doesn't carry the
                # column at all -- treated as zero for every row, per the
                # module docstring's missing-value convention.
                continue
            fantasy_points = (
                fantasy_points + stats[stat_column].fillna(0).astype(float) * weight
            )

    points_df["fantasy_points"] = fantasy_points

    return ScoringResult(
        points_df=points_df,
        unsupported_scoring_keys=sorted(unsupported_scoring_keys),
    )
