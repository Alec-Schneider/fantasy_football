"""Reconcile the season matchup DataFrame against Sleeper's cumulative standings.

FFA-033's :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`
is derived entirely from paired per-week matchup entries (loader -> pairing ->
outcomes -> season matchup DataFrame), while FFA-020's
:func:`~fantasy_analyzer.analytics.standings.build_standings` passes through
Sleeper's own season-cumulative ``rosters_df`` counters unchanged. These are
two independently-derived views of the same underlying season, and they
should agree. This module is the trust check between them: it recomputes
per-roster ``wins``/``losses``/``ties``/``points_for``/``points_against``
directly from the matchup-level data and compares those derived totals
against Sleeper's own cumulative record, flagging any roster where they
disagree.

This module performs no network access; it operates entirely on
already-built ``season_matchup_df``/standings-shaped DataFrames.

Derived per-roster totals (:func:`derive_roster_totals`)
----------------------------------------------------------

Each row of ``season_matchup_df`` (see ``SEASON_MATCHUP_COLUMNS``) is
attributed to both ``roster_1_id`` and ``roster_2_id``:

- **points_for** / **points_against** -- ``points_1`` is added to
  ``roster_1_id``'s ``points_for`` and, if ``roster_2_id`` is present, to
  ``roster_2_id``'s ``points_against``. Symmetrically, ``points_2`` is added
  to ``roster_2_id``'s ``points_for`` and to ``roster_1_id``'s
  ``points_against``. A missing (``None``/``NaN``) points value contributes
  nothing rather than raising or being treated as ``0``.
- **wins** / **losses** -- if ``winner``/``loser`` are set on a row, the
  winning roster's ``wins`` and the losing roster's ``losses`` are each
  incremented by one.
- **ties** -- if ``is_tie`` is ``True``, both ``roster_1_id`` and
  ``roster_2_id`` (a tie always has both, per
  :mod:`~fantasy_analyzer.matchups.outcomes`) have ``ties`` incremented by
  one.
- **Bye rows** (``roster_2_id is None``, see
  :mod:`~fantasy_analyzer.matchups.pairing`) contribute only ``points_1`` to
  that roster's ``points_for``; there is no opponent, so no
  ``points_against``, and no ``winner``/``loser``/``is_tie`` is ever set on a
  bye row (see :mod:`~fantasy_analyzer.matchups.outcomes`), so no
  win/loss/tie is credited either. This assumes Sleeper's own cumulative
  ``fpts`` treats a bye week the same way -- the roster still scored points
  that week and Sleeper's cumulative total should include them, while
  ``fpts_against`` should not include a bye-week charge because there was no
  opponent to be scored against. This is an explicit assumption, not
  something verified against a live bye week in this codebase's fixtures.
- A roster that appears in **no** row of ``season_matchup_df`` is not present
  in :func:`derive_roster_totals`'s output at all (there is nothing to
  attribute to it). :func:`reconcile_matchups_to_standings` is responsible
  for treating that absence as "zero games" rather than "unknown" -- see
  below.

Regular season vs. playoffs
------------------------------

:func:`derive_roster_totals` makes **no** ``is_playoff`` distinction and
sums over every row it is given, regular season and playoff alike. This is
required, not optional: ``build_standings``'s module docstring documents
that Sleeper's own cumulative ``wins``/``losses``/``ties``/``fpts``/
``fpts_against`` roster counters mix regular-season and playoff games
indistinguishably. Reconciling against those counters therefore requires
summing *all* weeks of ``season_matchup_df``. Callers who pre-filter
``season_matchup_df`` to ``is_playoff == False`` before calling this module
will see spurious mismatches for any roster that played playoff games --
that is expected, not a bug in this module.

Reconciliation (:func:`reconcile_matchups_to_standings`)
------------------------------------------------------------

Compares :func:`derive_roster_totals`'s output against a
``build_standings``-shaped DataFrame (``STANDINGS_COLUMNS``), not against
raw ``rosters_df``. ``build_standings`` already exposes ``wins``/
``losses``/``ties``/``points_for``/``points_against`` under the exact same
names this module derives, which makes the comparison a direct column-name
match with no field-renaming translation layer (``rosters_df`` would
require mapping ``fpts``/``fpts_against`` to ``points_for``/
``points_against`` here too, duplicating logic ``build_standings`` already
owns). This also means any bug in ``build_standings``'s pass-through would
surface here as well, which is a feature, not a leak of scope: FFA-034 is
reconciling "the standings a caller would actually use" against matchup
data, not re-deriving a second copy of the raw-to-standings translation.

Tolerances
----------

- ``wins``, ``losses``, and ``ties`` are integer game counts -- there is no
  floating-point computation involved in deriving them, so any difference at
  all is a real discrepancy. :data:`WIN_LOSS_TIE_TOLERANCE` is ``0``
  (exact-match only).
- ``points_for`` and ``points_against`` are sums of floats, and summation
  order can differ between this module's row-by-row accumulation and
  whatever order/method produced Sleeper's own cumulative ``fpts``/
  ``fpts_against`` totals, which can introduce floating-point noise on the
  order of the machine epsilon. :data:`POINTS_TOLERANCE` (``1e-6``) absorbs
  that noise without masking a genuine data discrepancy -- a real missing or
  extra matchup would produce a difference many orders of magnitude larger
  than ``1e-6``.

Both tolerances are named module-level constants (also exposed as
``points_tolerance``/``win_loss_tie_tolerance`` parameters on
:func:`reconcile_matchups_to_standings`) rather than magic numbers, per
AGENTS.md's Definition of Done.

Missing values / edge cases
----------------------------

- **Empty ``season_matchup_df``**: :func:`derive_roster_totals` returns an
  empty DataFrame with the expected columns. Reconciled against a
  non-empty standings DataFrame, every roster present in standings falls
  into the "roster with no derived matchups" case below -- which correctly
  reports a mismatch if Sleeper's cumulative record is non-zero, rather than
  silently skipping reconciliation because there was no matchup data at all.
- **A roster with no matchups** (absent from :func:`derive_roster_totals`'s
  output but present in the standings DataFrame): its derived ``wins``/
  ``losses``/``ties``/``points_for``/``points_against`` are treated as
  ``0``/``0``/``0``/``0.0``/``0.0`` -- a roster that appears in zero
  matchup rows has, by definition, zero recorded games and zero recorded
  points, not an *unknown* value. This is a deliberate default, not a
  silent skip: if Sleeper's standings show a non-zero record for that
  roster, the comparison correctly reports a mismatch.
- **A roster present in the derived totals but absent from the standings
  DataFrame** (or vice versa, when it is the standings side that is
  missing a roster the matchup data has): the missing side's values are
  left as ``NaN`` rather than defaulted to ``0``, because there genuinely
  is no known Sleeper value to compare against. Every ``*_match`` flag for
  that roster is ``False`` (a comparison against an unknown value can never
  be considered "within tolerance"), which surfaces the roster mismatch
  itself as a discrepancy worth investigating, rather than hiding it.
- **Both inputs empty**: returns an empty DataFrame with
  ``RECONCILIATION_COLUMNS``.
"""

from __future__ import annotations

import pandas as pd

#: Column order for the DataFrame returned by :func:`derive_roster_totals`.
DERIVED_TOTALS_COLUMNS = [
    "roster_id",
    "wins",
    "losses",
    "ties",
    "points_for",
    "points_against",
]

#: Column order for the DataFrame returned by
#: :func:`reconcile_matchups_to_standings`.
RECONCILIATION_COLUMNS = [
    "roster_id",
    "derived_wins",
    "sleeper_wins",
    "wins_diff",
    "wins_match",
    "derived_losses",
    "sleeper_losses",
    "losses_diff",
    "losses_match",
    "derived_ties",
    "sleeper_ties",
    "ties_diff",
    "ties_match",
    "derived_points_for",
    "sleeper_points_for",
    "points_for_diff",
    "points_for_match",
    "derived_points_against",
    "sleeper_points_against",
    "points_against_diff",
    "points_against_match",
    "reconciled",
]

#: Exact-match tolerance for the integer ``wins``/``losses``/``ties`` game
#: counts -- see the module docstring's "Tolerances" section.
WIN_LOSS_TIE_TOLERANCE = 0

#: Absolute float tolerance for ``points_for``/``points_against`` -- absorbs
#: floating-point summation-order noise, not genuine data discrepancies. See
#: the module docstring's "Tolerances" section.
POINTS_TOLERANCE = 1e-6


def _roster_bucket(totals: dict, roster_id: int) -> dict:
    """Return (creating if absent) the running totals dict for ``roster_id``."""
    if roster_id not in totals:
        totals[roster_id] = {
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "points_for": 0.0,
            "points_against": 0.0,
        }
    return totals[roster_id]


def derive_roster_totals(season_matchup_df: pd.DataFrame) -> pd.DataFrame:
    """Derive per-roster wins/losses/ties/points_for/points_against.

    Sums every row of ``season_matchup_df`` -- regular season and playoff
    alike -- attributing points and win/loss/tie credit to both
    ``roster_1_id`` and ``roster_2_id``. See the module docstring's "Derived
    per-roster totals" section for the exact per-field logic, the bye-row
    assumption, and why playoff rows must not be filtered out.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.

    Returns:
        A DataFrame with columns ``["roster_id", "wins", "losses", "ties",
        "points_for", "points_against"]``, one row per roster that appears
        in at least one row of ``season_matchup_df``. A roster with zero
        matchup rows is simply absent from the output -- see
        :func:`reconcile_matchups_to_standings` for how that absence is
        interpreted downstream. Returns an empty DataFrame with the expected
        columns if ``season_matchup_df`` is empty.
    """
    if season_matchup_df.empty:
        return pd.DataFrame(columns=DERIVED_TOTALS_COLUMNS)

    totals: dict = {}

    for row in season_matchup_df.itertuples(index=False):
        # A DataFrame assembled from multiple rows where some rows have a
        # real int roster_2_id/winner/loser and others have None (byes,
        # ties) gets those columns upcast to float64, silently turning
        # ``None`` into ``NaN`` rather than leaving it as ``None`` -- unlike
        # the single-row cases exercised in season_matchups.py's own tests.
        # Normalizing with pd.notna()/int() here (rather than ``is not
        # None``) makes this function correct regardless of whether the
        # caller's DataFrame happens to have object or float dtype for
        # these columns.
        roster_1_id = int(row.roster_1_id)
        roster_2_id = int(row.roster_2_id) if pd.notna(row.roster_2_id) else None
        winner = int(row.winner) if pd.notna(row.winner) else None
        loser = int(row.loser) if pd.notna(row.loser) else None
        points_1 = row.points_1
        points_2 = row.points_2

        roster_1_totals = _roster_bucket(totals, roster_1_id)

        if pd.notna(points_1):
            roster_1_totals["points_for"] += points_1
            if roster_2_id is not None:
                _roster_bucket(totals, roster_2_id)["points_against"] += points_1

        if roster_2_id is not None and pd.notna(points_2):
            roster_2_totals = _roster_bucket(totals, roster_2_id)
            roster_2_totals["points_for"] += points_2
            roster_1_totals["points_against"] += points_2

        if winner is not None and loser is not None:
            _roster_bucket(totals, winner)["wins"] += 1
            _roster_bucket(totals, loser)["losses"] += 1
        elif row.is_tie:
            roster_1_totals["ties"] += 1
            if roster_2_id is not None:
                _roster_bucket(totals, roster_2_id)["ties"] += 1

    rows = [{"roster_id": roster_id, **values} for roster_id, values in totals.items()]
    return pd.DataFrame(rows, columns=DERIVED_TOTALS_COLUMNS)


def _diff(derived: float, sleeper: float):
    """Return ``derived - sleeper``, or ``None`` if either side is unknown."""
    if pd.isna(derived) or pd.isna(sleeper):
        return None
    return derived - sleeper


def _tolerance_match(derived: float, sleeper: float, tolerance: float) -> bool:
    """Absolute-tolerance comparison; ``False`` if either side is unknown.

    Shared by both the ``wins``/``losses``/``ties`` comparisons (called with
    ``tolerance=win_loss_tie_tolerance``, ``0`` by default -- an exact-match
    comparison) and the ``points_for``/``points_against`` comparisons
    (called with ``tolerance=points_tolerance``). See the module
    docstring's "Tolerances" section.
    """
    if pd.isna(derived) or pd.isna(sleeper):
        return False
    return abs(derived - sleeper) <= tolerance


def reconcile_matchups_to_standings(
    season_matchup_df: pd.DataFrame,
    standings_df: pd.DataFrame,
    *,
    win_loss_tie_tolerance: float = WIN_LOSS_TIE_TOLERANCE,
    points_tolerance: float = POINTS_TOLERANCE,
) -> pd.DataFrame:
    """Reconcile matchup-derived per-roster totals against Sleeper's standings.

    Derives per-roster ``wins``/``losses``/``ties``/``points_for``/
    ``points_against`` from ``season_matchup_df`` via
    :func:`derive_roster_totals`, then compares them against
    ``standings_df``'s Sleeper-sourced cumulative values, roster by roster.
    See the module docstring for the choice of ``standings_df`` (rather than
    raw ``rosters_df``) as the comparison target, the documented tolerances,
    and the missing-roster/missing-data edge cases.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame
            covering the *entire* season (regular season and playoffs) --
            see the module docstring for why playoff weeks must not be
            pre-filtered out.
        standings_df: A ``STANDINGS_COLUMNS``-shaped DataFrame, as produced
            by :func:`~fantasy_analyzer.analytics.standings.build_standings`.
        win_loss_tie_tolerance: Exact-match tolerance for ``wins``/
            ``losses``/``ties``. Defaults to :data:`WIN_LOSS_TIE_TOLERANCE`
            (``0``).
        points_tolerance: Absolute float tolerance for ``points_for``/
            ``points_against``. Defaults to :data:`POINTS_TOLERANCE`.

    Returns:
        A DataFrame with columns ``RECONCILIATION_COLUMNS``: one row per
        roster appearing in either input, each with its derived value,
        Sleeper value, difference (``derived - sleeper``, ``None`` if either
        side is unknown), and a ``*_match`` boolean for each of ``wins``/
        ``losses``/``ties``/``points_for``/``points_against``, plus an
        overall ``reconciled`` boolean (``True`` only if every metric
        matches). Rows are sorted by ascending ``roster_id``. Returns an
        empty DataFrame with the expected columns if both inputs are empty.
    """
    derived = derive_roster_totals(season_matchup_df)

    if derived.empty and standings_df.empty:
        return pd.DataFrame(columns=RECONCILIATION_COLUMNS)

    derived_renamed = derived.rename(
        columns={
            "wins": "derived_wins",
            "losses": "derived_losses",
            "ties": "derived_ties",
            "points_for": "derived_points_for",
            "points_against": "derived_points_against",
        }
    )

    sleeper_columns = [
        "roster_id",
        "sleeper_wins",
        "sleeper_losses",
        "sleeper_ties",
        "sleeper_points_for",
        "sleeper_points_against",
    ]
    if standings_df.empty:
        sleeper_renamed = pd.DataFrame(columns=sleeper_columns)
    else:
        sleeper_renamed = standings_df[
            ["roster_id", "wins", "losses", "ties", "points_for", "points_against"]
        ].rename(
            columns={
                "wins": "sleeper_wins",
                "losses": "sleeper_losses",
                "ties": "sleeper_ties",
                "points_for": "sleeper_points_for",
                "points_against": "sleeper_points_against",
            }
        )

    merged = derived_renamed.merge(sleeper_renamed, on="roster_id", how="outer")

    # A roster absent from the derived side has zero matchup rows attributed
    # to it -- by definition zero games/points, not an unknown value. See
    # the module docstring's "Missing values / edge cases" section.
    merged["derived_wins"] = merged["derived_wins"].fillna(0)
    merged["derived_losses"] = merged["derived_losses"].fillna(0)
    merged["derived_ties"] = merged["derived_ties"].fillna(0)
    merged["derived_points_for"] = merged["derived_points_for"].fillna(0.0)
    merged["derived_points_against"] = merged["derived_points_against"].fillna(0.0)
    # Sleeper-side NaNs (a roster missing from standings_df) are deliberately
    # left as NaN -- there is no known true value to default to, so the
    # match flags below correctly report a mismatch rather than assuming
    # agreement.

    merged["wins_diff"] = merged.apply(
        lambda r: _diff(r["derived_wins"], r["sleeper_wins"]), axis=1
    )
    merged["wins_match"] = merged.apply(
        lambda r: _tolerance_match(
            r["derived_wins"], r["sleeper_wins"], win_loss_tie_tolerance
        ),
        axis=1,
    )
    merged["losses_diff"] = merged.apply(
        lambda r: _diff(r["derived_losses"], r["sleeper_losses"]), axis=1
    )
    merged["losses_match"] = merged.apply(
        lambda r: _tolerance_match(
            r["derived_losses"], r["sleeper_losses"], win_loss_tie_tolerance
        ),
        axis=1,
    )
    merged["ties_diff"] = merged.apply(
        lambda r: _diff(r["derived_ties"], r["sleeper_ties"]), axis=1
    )
    merged["ties_match"] = merged.apply(
        lambda r: _tolerance_match(
            r["derived_ties"], r["sleeper_ties"], win_loss_tie_tolerance
        ),
        axis=1,
    )
    merged["points_for_diff"] = merged.apply(
        lambda r: _diff(r["derived_points_for"], r["sleeper_points_for"]), axis=1
    )
    merged["points_for_match"] = merged.apply(
        lambda r: _tolerance_match(
            r["derived_points_for"], r["sleeper_points_for"], points_tolerance
        ),
        axis=1,
    )
    merged["points_against_diff"] = merged.apply(
        lambda r: _diff(r["derived_points_against"], r["sleeper_points_against"]),
        axis=1,
    )
    merged["points_against_match"] = merged.apply(
        lambda r: _tolerance_match(
            r["derived_points_against"],
            r["sleeper_points_against"],
            points_tolerance,
        ),
        axis=1,
    )

    merged["reconciled"] = (
        merged["wins_match"]
        & merged["losses_match"]
        & merged["ties_match"]
        & merged["points_for_match"]
        & merged["points_against_match"]
    )

    merged = merged.sort_values(by="roster_id").reset_index(drop=True)

    return merged[RECONCILIATION_COLUMNS]
