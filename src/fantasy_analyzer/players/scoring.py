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
``rush_yd``, ``rush_td``, ``rec``, ``rec_yd``, ``rec_td``, ``fum_lost``,
all present there) and the real scoring settings of this project's primary
development league (which additionally uses ``pass_2pt``/``rush_2pt``/
``rec_2pt`` and the tiered ``fgm_*``/``fgmiss``/``xpm``/``xpmiss`` kicker
categories -- see below), plus a small number of additional, unambiguous
Sleeper keys whose raw stat exists in
:data:`~fantasy_analyzer.players.nflverse_provider.RAW_STAT_COLUMNS`:

=============  =============================  ========================
Sleeper key    Raw stat column                Per
=============  =============================  ========================
``pass_yd``    ``passing_yards``              passing yard
``pass_td``    ``passing_tds``                passing touchdown
``pass_int``   ``passing_interceptions``      interception thrown
``pass_cmp``   ``completions``                completion
``pass_att``   ``attempts``                   pass attempt
``pass_sack``  ``sacks_suffered``             sack taken
``pass_2pt``   ``passing_2pt_conversions``    passing 2pt conversion
``rush_att``   ``carries``                    rush attempt
``rush_yd``    ``rushing_yards``              rushing yard
``rush_td``    ``rushing_tds``                rushing touchdown
``rush_2pt``   ``rushing_2pt_conversions``    rushing 2pt conversion
``rec``        ``receptions``                 reception
``rec_tgt``    ``targets``                    target
``rec_yd``     ``receiving_yards``            receiving yard
``rec_td``     ``receiving_tds``              receiving touchdown
``rec_2pt``    ``receiving_2pt_conversions``  receiving 2pt conversion
``fgm_0_19``   ``fg_made_0_19``               made FG, 0-19 yards
``fgm_20_29``  ``fg_made_20_29``              made FG, 20-29 yards
``fgm_30_39``  ``fg_made_30_39``              made FG, 30-39 yards
``fgm_40_49``  ``fg_made_40_49``              made FG, 40-49 yards
``xpm``        ``pat_made``                   made extra point
``fgm``        ``fg_made``                    made FG, any distance
``fgm_50_59``  ``fg_made_50_59``              made FG, 50-59 yards
``fgm_60p``    ``fg_made_60_``                made FG, 60+ yards
``st_td``      ``special_teams_tds``          return TD by a player
``fum_rec_td`` ``fumble_recovery_tds``        fumble-recovery TD
=============  =============================  ========================

Several keys don't fit the one-key-to-one-column shape of the table above
cleanly enough to render as a single row, so they're called out here
instead:

- ``fum_lost`` prefers nflverse's ``fumbles_lost_total`` and falls back to
  the sum of the three ``*_fumbles_lost`` columns (sack/rush/receiving)
  when that column is absent -- see :data:`PREFERRED_TOTAL_COLUMNS` and
  "Verified against Sleeper" below for why the total wins.
- ``fgm_50p`` sums ``fg_made_50_59`` and ``fg_made_60_`` -- nflverse splits
  a 50-59 and a 60+ band, Sleeper's ``fgm_50p`` merges both into one 50+
  tier. A league that instead scores the two bands separately uses
  ``fgm_50_59``/``fgm_60p`` (one column each).
- ``fgmiss`` (missed field goal, any distance -- Sleeper does not band
  this one in any league seen here) maps to ``fg_missed`` **plus**
  ``fg_blocked``: nflverse's ``fg_missed`` excludes blocked kicks
  (``fg_att == fg_made + fg_missed + fg_blocked`` on every kicker row
  2014-2026), and Sleeper charges a blocked kick as a miss.
- ``xpmiss`` likewise maps to ``pat_missed`` plus ``pat_blocked``.
- ``bonus_pass_yd_400``/``bonus_rush_yd_200``/``bonus_rec_yd_200`` are
  *threshold* bonuses, not linear rules: the weight is paid once when the
  week's yardage reaches the threshold. See
  :data:`SCORING_KEY_TO_THRESHOLD_BONUS`.

Verified against Sleeper (FFA-112)
-------------------------------------------------------------------------

Every mapping in this module was checked against Sleeper's own computed
points -- the ``players_points`` map in the raw matchup payload
(``SleeperClient.get_matchups``), which carries Sleeper's figure for every
rostered player, starters and bench alike -- for the 2025 regular season
and 2026 weeks 1-3 of three real 12/10-team leagues with three different
scoring configurations (``scripts/verify_special_teams_scoring.py``).
What that settled, change by change:

- ``fgm_50_59``/``fgm_60p`` were **unmapped** before FFA-112, so every
  50+ yard field goal in a league using the split bands scored zero. This
  one gap accounted for 45 of the 66 kicker mismatches in 2025.
- ``fgmiss``/``xpmiss`` + blocked: the other 21 were all +1 (the engine
  one point *above* Sleeper), each a row with ``fg_blocked`` or
  ``pat_blocked`` = 1.
- ``fum_lost``: every +1/+2 skill-position mismatch involving a fumble
  was a fumble lost outside the rush/reception/sack categories (a muffed
  return, a fumble after a change of possession), which
  ``fumbles_lost_total`` counts and the three scrimmage columns do not.
  ``fumbles_lost_total`` is never *below* that three-column sum (0 rows in
  any season 2014-2026), so the change only ever adds fumbles the old
  mapping missed.
- ``st_td``: the six-point misses on punt/kick returners were all rows
  with ``special_teams_tds`` = 1. Sleeper pays ``st_td`` to the
  individual returner; the team ``DEF`` separately receives
  ``def_st_td`` (see :func:`calculate_team_defense_points`).
- ``fum_rec_td``: an offensive player recovering a fumble in the end
  zone (``fumble_recovery_tds`` = 1) was six points short.
- The threshold bonuses: the one league that uses them was short by the
  bonus on its 400-yard passers and 200-yard rushers/receivers. With them
  mapped, 65 of that league's 66 remaining 2025 skill mismatches are
  explained exactly by 50+ yard touchdowns (play-by-play count).

Two kinds of residual remain and are expected: the ``*_td_50p``
touchdown-length bonuses (below), and single-row disagreements between
nflverse's stat feed and Sleeper's.

Deliberately **not** mapped (surfaced as unsupported, never guessed at):

- ``fum`` (total fumbles, lost or not): weighted zero in every league
  checked, so no mapping could be verified. nflverse's current release
  does carry ``fumbles_total``; mapping it is a one-line change once a
  league that weights ``fum`` is available to check against.
- ``pass_td_50p``/``rush_td_50p``/``rec_td_50p`` (a bonus per touchdown of
  50+ yards): the *length* of each touchdown is a play-by-play fact that
  nflverse's weekly table does not carry (``receiving_40`` counts 40+ yard
  *receptions*, not touchdowns). These are the dominant residual in the
  one league that weights them (+1 point per 50+ yard TD, Sleeper above
  this engine).
- ``bonus_rec_te`` (a TE-only reception bonus), ``bonus_rush_rec_yd_200``,
  the lower yardage tiers (``bonus_rush_yd_100``, ``bonus_pass_yd_300``,
  ...), and any other position-conditional or tiered bonus: a TE bonus
  must apply only when ``position == "TE"``, and Sleeper's lower yardage
  tiers are bands (100-199), not open thresholds. None is weighted in any
  league checked, so none could be verified; each is surfaced via
  :attr:`ScoringResult.unsupported_scoring_keys` -- a documented gap, not a
  silent zero.
- ``fgmiss_0_19`` ... ``fgmiss_50p`` (per-distance misses): not weighted
  in any league checked. nflverse carries ``fg_missed_<band>`` columns,
  but it is unverified whether Sleeper puts a *blocked* kick into a
  distance band, and a blocked kick is exactly where ``fgmiss`` needed
  correcting.
- Any team-``DEF`` scoring category (``sack``, ``int``, ``fum_rec``,
  ``safe``, ``blk_kick``, ``def_st_td``, ``pts_allow_*``, etc.): a
  Sleeper ``DEF`` slot is a whole team unit, not one of the per-player rows
  this function scores, so these keys are always reported as unsupported
  *here*. They are scored by :func:`calculate_team_defense_points`, which
  takes a team-week frame from
  :func:`fantasy_analyzer.players.nflverse_defense.build_team_defense_weeks`
  instead.

``fgm_0_19``/``fgm_50p`` were **not** possible against the pre-migration
``player_stats`` release nflverse used to publish (see
``nflverse_client``'s docstring for that migration) -- it carried no
kicking columns at all. They became mappable once the client was
repointed at the current ``stats_player_week`` release, which does.

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

import math
import re
from dataclasses import dataclass
from typing import Mapping, Optional

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
    "pass_int": ("passing_interceptions",),
    "pass_cmp": ("completions",),
    "pass_att": ("attempts",),
    "pass_sack": ("sacks_suffered",),
    "pass_2pt": ("passing_2pt_conversions",),
    "rush_att": ("carries",),
    "rush_yd": ("rushing_yards",),
    "rush_td": ("rushing_tds",),
    "rush_2pt": ("rushing_2pt_conversions",),
    "rec": ("receptions",),
    "rec_tgt": ("targets",),
    "rec_yd": ("receiving_yards",),
    "rec_td": ("receiving_tds",),
    "rec_2pt": ("receiving_2pt_conversions",),
    "fum_lost": (
        "sack_fumbles_lost",
        "rushing_fumbles_lost",
        "receiving_fumbles_lost",
    ),
    "fgm_0_19": ("fg_made_0_19",),
    "fgm_20_29": ("fg_made_20_29",),
    "fgm_30_39": ("fg_made_30_39",),
    "fgm_40_49": ("fg_made_40_49",),
    "fgm_50p": ("fg_made_50_59", "fg_made_60_"),
    "fgm_50_59": ("fg_made_50_59",),
    "fgm_60p": ("fg_made_60_",),
    "fgm": ("fg_made",),
    # Blocked kicks are misses to Sleeper; nflverse counts them separately.
    "fgmiss": ("fg_missed", "fg_blocked"),
    "xpm": ("pat_made",),
    "xpmiss": ("pat_missed", "pat_blocked"),
    "st_td": ("special_teams_tds",),
    "fum_rec_td": ("fumble_recovery_tds",),
}

#: Scoring key -> a single nflverse column that, when present in ``stats``,
#: replaces the component sum in :data:`SCORING_KEY_TO_STAT_COLUMNS` for
#: every row where it is non-null. ``fumbles_lost_total`` also counts
#: return fumbles, which Sleeper charges and the three scrimmage columns
#: miss (see the module docstring's "Verified against Sleeper" section).
#: A frame without the column (e.g. ``nflverse_provider``'s normalized
#: output, or an older fixture) keeps the original component-sum behavior.
PREFERRED_TOTAL_COLUMNS: dict[str, str] = {
    "fum_lost": "fumbles_lost_total",
}

#: Threshold bonus key -> ``(stat columns summed, threshold)``. The key's
#: weight is paid once per row whose summed stat is ``>= threshold``. Only
#: the open-ended top tiers verified against Sleeper are listed; see the
#: module docstring for why the lower (banded) tiers are not.
SCORING_KEY_TO_THRESHOLD_BONUS: dict[str, tuple[tuple[str, ...], float]] = {
    "bonus_pass_yd_400": (("passing_yards",), 400.0),
    "bonus_rush_yd_200": (("rushing_yards",), 200.0),
    "bonus_rec_yd_200": (("receiving_yards",), 200.0),
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
        if key in SCORING_KEY_TO_THRESHOLD_BONUS:
            columns, threshold = SCORING_KEY_TO_THRESHOLD_BONUS[key]
            reached = _summed_columns(stats, columns) >= threshold
            fantasy_points = fantasy_points + reached.astype(float) * weight
            continue
        stat_columns = SCORING_KEY_TO_STAT_COLUMNS.get(key)
        if stat_columns is None:
            unsupported_scoring_keys.append(key)
            continue
        # Mapped category; a column absent from ``stats`` contributes zero
        # for every row, per the module docstring's missing-value
        # convention.
        category_total = _summed_columns(stats, stat_columns)
        preferred = PREFERRED_TOTAL_COLUMNS.get(key)
        if preferred is not None and preferred in stats.columns:
            total = pd.to_numeric(stats[preferred], errors="coerce").astype(float)
            category_total = total.where(total.notna(), category_total)
        fantasy_points = fantasy_points + category_total * weight

    points_df["fantasy_points"] = fantasy_points

    return ScoringResult(
        points_df=points_df,
        unsupported_scoring_keys=sorted(unsupported_scoring_keys),
    )


def _summed_columns(stats: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    """Row-wise sum of ``columns``; absent columns and ``NaN`` cells count as 0."""
    total = pd.Series(0.0, index=stats.index, dtype=float)
    for column in columns:
        if column in stats.columns:
            total = total + pd.to_numeric(stats[column], errors="coerce").fillna(
                0
            ).astype(float)
    return total


# ---------------------------------------------------------------------------
# Team defense / special teams (FFA-112)
# ---------------------------------------------------------------------------

#: Sleeper team-``DEF`` scoring key -> column(s) of
#: :func:`fantasy_analyzer.players.nflverse_defense.build_team_defense_weeks`'s
#: output, summed and multiplied by the key's weight. Every row was
#: verified against Sleeper's own ``DEF`` points; the evidence that settled
#: each one -- above all the near-duplicate keys -- is in
#: :func:`calculate_team_defense_points`'s docstring and in
#: ``docs/kicker-defense.md``.
TEAM_DEFENSE_KEY_TO_STAT_COLUMNS: dict[str, tuple[str, ...]] = {
    "sack": ("sacks",),
    "int": ("interceptions",),
    "fum_rec": ("fumble_recoveries",),
    "def_st_fum_rec": ("st_fumble_recoveries",),
    "ff": ("forced_fumbles",),
    "def_st_ff": ("st_forced_fumbles",),
    "def_td": ("def_tds",),
    "def_st_td": ("st_tds",),
    "safe": ("safeties",),
    "blk_kick": ("blocked_kicks",),
}

#: The column :func:`calculate_team_defense_points` bins into the
#: ``pts_allow_*`` tiers -- Sleeper's points-allowed definition, not the
#: raw opponent score. See ``build_team_defense_weeks``.
TEAM_DEFENSE_POINTS_ALLOWED_COLUMN = "def_points_allowed"

#: Keys Sleeper pays to an *individual* special-teams player and never to
#: the team ``DEF`` (verified: a team-week with a special-teams forced
#: fumble scores zero for it in a league weighting ``st_ff`` at 1 and
#: ``def_st_ff`` at 0). Not reported as unsupported for a ``DEF`` row.
TEAM_DEFENSE_NOT_APPLICABLE_KEYS = frozenset({"st_td", "st_ff", "st_fum_rec"})

_POINTS_ALLOWED_TIER = re.compile(r"^pts_allow_(\d+)(?:_(\d+)|(p))?$")

#: Individual-defender and other team-defense keys that a ``DEF`` scoring
#: pass should *report* as unsupported when weighted, as opposed to
#: offensive/kicking keys that simply do not apply to a team unit.
_TEAM_DEFENSE_FAMILY = re.compile(
    r"^(def_|pts_allow|yds_allow|sack|int$|int_|fum_rec$|fum_ret|ff$|safe$|"
    r"blk_kick|qb_hit|tkl|pass_def)"
)


def points_allowed_tier(key: str) -> Optional[tuple[float, float]]:
    """Parse a Sleeper ``pts_allow_*`` tier key into inclusive bounds.

    ``pts_allow_0`` is ``(0, 0)``, ``pts_allow_7_13`` is ``(7, 13)`` and
    ``pts_allow_35p`` is ``(35, inf)``. A bare ``pts_allow`` (a per-point
    rule, not a tier) or any other key returns ``None``.

    Args:
        key: A Sleeper scoring-settings key.

    Returns:
        ``(low, high)`` inclusive bounds, or ``None`` if ``key`` is not a
        tier key.
    """
    match = _POINTS_ALLOWED_TIER.match(key)
    if match is None:
        return None
    low = float(match.group(1))
    if match.group(3):
        return (low, math.inf)
    if match.group(2) is not None:
        return (low, float(match.group(2)))
    return (low, low)


def calculate_team_defense_points(
    team_defense: pd.DataFrame, scoring_settings: Mapping[str, float]
) -> ScoringResult:
    """Score team ``DEF`` rows with a league's Sleeper scoring settings.

    ``fantasy_points`` is the sum of each linear key in
    :data:`TEAM_DEFENSE_KEY_TO_STAT_COLUMNS` times its weight, plus the
    weight of the one ``pts_allow_*`` tier whose inclusive bounds (see
    :func:`points_allowed_tier`) contain the row's
    :data:`TEAM_DEFENSE_POINTS_ALLOWED_COLUMN`.

    What the Sleeper oracle settled (2025 regular season + 2026 weeks 1-3,
    three leagues, play-by-play used to classify every play):

    - ``pts_allow_*`` bins the opponent's score **minus 6 per defensive
      touchdown the opponent scored and minus 2 per safety it scored**.
      Subtracting 7 (the try as well), or also removing special-teams
      return touchdowns, both match Sleeper measurably less often.
    - A special-teams fumble recovery is paid once at ``def_st_fum_rec``
      (1 in every league), never at ``fum_rec`` (2), and never twice.
    - A special-teams return touchdown is paid once at ``def_st_td``, not
      additionally at ``st_td``; a defensive return touchdown (including a
      fumble return) at ``def_td``.
    - A special-teams forced fumble earns the ``DEF`` nothing from ``st_ff``
      (see :data:`TEAM_DEFENSE_NOT_APPLICABLE_KEYS`).
    - ``blk_kick`` counts blocked punts, field goals **and** extra points.

    Missing values follow :func:`calculate_fantasy_points`: an absent
    column or ``NaN`` cell contributes zero, and a ``NaN`` points-allowed
    value falls in no tier. The function is phase-agnostic (no regular
    season/playoff distinction), for the same reason.

    Args:
        team_defense: One row per team-game, carrying the columns named in
            :data:`TEAM_DEFENSE_KEY_TO_STAT_COLUMNS` and
            :data:`TEAM_DEFENSE_POINTS_ALLOWED_COLUMN` -- as produced by
            :func:`fantasy_analyzer.players.nflverse_defense.build_team_defense_weeks`.
        scoring_settings: A league's full Sleeper scoring settings. Keys
            that only apply to individual players (passing, receiving,
            kicking, ``st_*``) are ignored rather than reported.

    Returns:
        A :class:`ScoringResult` whose ``unsupported_scoring_keys`` lists
        the team-defense-family keys (e.g. ``yds_allow_*``, ``def_2pt``)
        this function could not apply.
    """
    points_df = team_defense.copy()
    fantasy_points = pd.Series(0.0, index=team_defense.index, dtype=float)
    if TEAM_DEFENSE_POINTS_ALLOWED_COLUMN in team_defense.columns:
        allowed = pd.to_numeric(
            team_defense[TEAM_DEFENSE_POINTS_ALLOWED_COLUMN], errors="coerce"
        )
    else:
        allowed = pd.Series(float("nan"), index=team_defense.index)

    unsupported: list[str] = []
    for key, weight in scoring_settings.items():
        if key in TEAM_DEFENSE_KEY_TO_STAT_COLUMNS:
            columns = TEAM_DEFENSE_KEY_TO_STAT_COLUMNS[key]
            category_total = _summed_columns(team_defense, columns)
            fantasy_points = fantasy_points + category_total * weight
            continue
        tier = points_allowed_tier(key)
        if tier is not None:
            in_tier = (allowed >= tier[0]) & (allowed <= tier[1])
            fantasy_points = fantasy_points + in_tier.astype(float) * weight
            continue
        if key in TEAM_DEFENSE_NOT_APPLICABLE_KEYS:
            continue
        if _TEAM_DEFENSE_FAMILY.match(key):
            unsupported.append(key)

    points_df["fantasy_points"] = fantasy_points
    return ScoringResult(
        points_df=points_df, unsupported_scoring_keys=sorted(unsupported)
    )
