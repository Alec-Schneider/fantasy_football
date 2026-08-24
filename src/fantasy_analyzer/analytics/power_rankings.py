"""League power ranking model from a single season matchup frame (FFA-056).

Combines three already-built, already-documented metrics -- FFA-052's
``win_pct`` and ``all_play_win_pct`` (both via
:func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`) and
FFA-053's ``mean_points`` (via
:func:`~fantasy_analyzer.analytics.consistency.build_consistency_metrics`) --
into a single, explicit, weighted composite score describing **current team
strength**. This module performs no network access and computes nothing that
is not already defined elsewhere; every number in its output is either a
metric this package has already documented and tested, or a transparent,
named arithmetic combination of those metrics.

AGENTS.md requires that this ticket not "build an opaque score", and states
the model must document its included features, its weights or estimation
method, its scaling, its tie-breaking, and its interpretation. Each of those
is its own section below. The intermediate values (the raw features and
their z-scores) are also columns in the output, not just prose -- a reader
can recompute ``power_score`` from the row in front of them without opening
this file.

Included features, and why each earns its place
---------------------------------------------------

Three features enter the composite, each capturing a distinct thing a power
ranking should care about:

- **win_pct** (from ``build_schedule_luck``) -- what actually happened. A
  fantasy league is decided by its standings, and a power ranking that
  ignored results entirely would be measuring something other than the thing
  everyone is actually competing for.
- **all_play_win_pct** (from ``build_schedule_luck``) -- how often the
  roster would have beaten a randomly drawn league-mate that week,
  independent of who it actually played. This is the schedule-independent
  read on scoring strength, and the natural corrective for ``win_pct``: a
  team can win_pct = 1.000 by scoring well or by scoring adequately against a
  string of weak opponents, and only the second number tells the two apart.
- **mean_points** (from ``build_consistency_metrics``) -- the roster's
  average weekly score, in the league's own points. ``all_play_win_pct`` is
  a *rank*-based measure: it says how often a roster beat the field, but not
  by how much. Two rosters can both go undefeated in all-play comparisons
  while one wins every week by 40 points and the other by 2; ``mean_points``
  is what separates a dominant roster from a merely fortunate one at the top
  of a tight field, and is the one feature here expressed in the league's
  actual scoring units rather than a rate.

Two available metrics deliberately do **not** enter the composite, and the
omission is a design decision, not an oversight:

- **schedule_luck is excluded.** ``schedule_luck`` (FFA-052) is
  algebraically ``(win_pct - all_play_win_pct) * games_played`` --
  a deterministic linear function of two features already in the composite.
  Adding it as a third term would not add information; it would silently
  re-weight the ``win_pct`` vs. ``all_play_win_pct`` contrast a second time,
  and because ``win_pct`` already carries some of what makes a team "lucky",
  giving ``schedule_luck`` its own weight would double-count that contrast
  under a different name. The composite's ``win_pct``/``all_play_win_pct``
  split already *is* the intended way this model treats luck: a team's
  result counts, but is anchored by its schedule-independent scoring rate so
  a lucky record does not fully carry the score on its own.
- **Consistency (``stdev_points``/``cv``/boom-bust) is excluded.**
  ``consistency.py``'s own docstring states the reason directly: "Low
  ``stdev_points`` is good for a strong team ... and bad for a weak one ...
  Any single 'consistency rank' would have to smuggle in a weighting of
  level against spread, which is precisely the composite-score judgment call
  FFA-056's power ranking model owns." Volatility has no single sign of
  goodness -- it protects a lead for a strong team and is exactly what a
  weak team needs to steal an upset -- so there is no principled weight to
  give it without silently assuming which kind of team a roster is. Rather
  than pick an arbitrary sign, this model leaves volatility out and reports
  ``mean_points`` (level) without a variance adjustment.

Weights and estimation method
--------------------------------

The composite is an explicit weighted sum of three z-scored features, no
different in kind from a hand-computed spreadsheet formula::

    power_score = WIN_PCT_WEIGHT       * win_pct_z
                + ALL_PLAY_WIN_PCT_WEIGHT * all_play_win_pct_z
                + MEAN_POINTS_WEIGHT  * mean_points_z

with the module-level constants :data:`WIN_PCT_WEIGHT` = ``0.3``,
:data:`ALL_PLAY_WIN_PCT_WEIGHT` = ``0.5``, :data:`MEAN_POINTS_WEIGHT` =
``0.2`` (they sum to ``1.0``, so the composite sits on the same rough scale
as any one z-scored input).

The weights are a **documented judgment call**, not a fitted or otherwise
derived estimate -- there is no target variable to fit against; "team
strength" is the thing being defined, not predicted. The reasoning behind
the specific split:

- ``all_play_win_pct`` gets the plurality (``0.5``) because it is the most
  schedule-independent of the three signals and, per FFA-052's own
  validation, the more reliable read on scoring strength over a
  roughly-14-week sample.
- ``win_pct`` gets the next largest share (``0.3``) because actual results
  still matter -- a power ranking that ignored the standings entirely would
  not be describing this league -- but is weighted below the all-play rate
  specifically because a single season's ``win_pct`` is the more
  luck-exposed of the two rate columns (see FFA-052's ``schedule_luck``).
- ``mean_points`` gets the smallest share (``0.2``) because it is the
  feature most correlated with ``all_play_win_pct`` by construction (both
  are functions of the same weekly scores), so it is included to add the
  magnitude information ``all_play_win_pct`` cannot express on its own, not
  to independently double the weight already given to scoring.

A different, equally defensible analyst could argue for a more record-heavy
or a more points-heavy split; this is the same kind of judgment call
FFA-053 makes explicit for ``boom_bust_threshold``. The weights are named
module constants specifically so a future ticket can revisit them, or a
caller can recompute the composite by hand from the exposed z-score columns
using different weights, without needing to read this file.

Scaling: population z-scores, and the zero-variance rule
------------------------------------------------------------

``win_pct`` is a 0-1 rate, ``all_play_win_pct`` is a 0-1 rate over a
different (much larger) number of comparisons, and ``mean_points`` is in the
league's own scoring units (typically on the order of 100). Summing them
directly would let ``mean_points`` swamp the other two purely because of its
units. Each feature is therefore converted to a **z-score within the set of
rosters this call produces a row for** -- the same "how many standard
deviations from this league's own mean" transform ``consistency.py`` already
uses for the boom/bust threshold, applied here across rosters instead of
across weeks:

    z = (x - mean(x)) / population_stdev(x)

using the **population** standard deviation (``statistics.pstdev``, ``ddof =
0``), for the same reason ``consistency.py`` gives for its own choice: this
is a descriptive summary of the specific set of rosters in this call, not a
sample drawn from a larger population of hypothetical leagues.

**Zero-variance columns are handled explicitly, not by dividing by zero.**
If every roster in the row set has the identical value on a feature (most
plausible early in a season, when every 0-0 roster's ``win_pct`` is
undefined and drops out entirely -- see "Missing values / edge cases" -- but
mechanically possible on any feature, and always true when exactly one
roster has a row), that feature's z-score is ``0.0`` for every roster rather
than ``NaN`` or a ``ZeroDivisionError``. A column with no spread carries no
information to rank rosters against each other on, and ``0.0`` is the
neutral, no-signal value the weighted sum expects, so the other feature(s)
alone determine the ordering rather than the whole score blowing up.

Tie-breaking
-------------

``power_rank`` uses **standard competition ("1224") ranking**, the same
convention as every other rank column in this package: rosters with an
exactly equal ``power_score`` (exact float equality -- rosters that reach
the same z-scores through the same underlying feature values reach the same
float through the same arithmetic) share a rank, and the next distinct rank
skips the tied count. There is no secondary tiebreaker on the rank itself --
the same choice ``strength_of_schedule.py`` and ``schedule_luck.py`` make --
because any obvious candidate (``all_play_win_pct`` alone, ``mean_points``
alone) would be an arbitrary rule dressed up as a measurement, and a
composite built from a documented formula should let genuinely tied inputs
genuinely tie. Rows are *ordered* by descending ``power_score`` then
ascending ``roster_id``, but that ``roster_id`` order is display-only and is
not reflected in ``power_rank``.

Interpretation
----------------

``power_rank = 1`` is this model's highest composite score, i.e. its
best estimate of the *strongest team as of the games included in the input*
-- unlike ``strength_of_schedule.py``'s or ``schedule_luck.py``'s rank
columns, a higher rank number here is unambiguously worse, matching
``standings.py``'s and ``all_play.py``'s convention rather than theirs.

What this ranking is **not**:

- It is not a projection. Nothing here uses future schedule, injury status,
  or player-level data (Epic 7 is a separate, not-yet-built layer), so it
  makes no claim about what a roster will do in a future week.
- It is not validated as predictive, and this module does not attempt a
  backtest. It is a documented, transparent *descriptive* summary of the
  games in ``season_matchup_df`` -- the same retrospective posture every
  FFA-050 through FFA-054 metric it is built from already takes.
- It is not a replacement for reading the individual metrics. ``win_pct``,
  ``all_play_win_pct`` and ``mean_points`` are each still present as their
  own columns precisely so a reader can see *why* two rosters landed where
  they did rather than trusting a single number.

Because the function takes whatever weeks are in ``season_matchup_df``, the
same call naturally supports a rolling "as of week N" power ranking -- pass
a frame filtered to weeks ``<= N`` -- which is arguably the more common real
use of a power ranking than a single end-of-season figure. No special
parameter is needed for this; it falls out of the "caller filters the input"
design every module since FFA-052 already uses.

Playoff placement (FFA-055) is a listed dependency, and is deliberately excluded
-----------------------------------------------------------------------------------

FFA-055's :func:`~fantasy_analyzer.matchups.playoffs.build_final_placements`
is a listed dependency of this ticket, and this module does not call it, use
its output, or take a ``bracket_df``/placements parameter. That is a
deliberate decision, not an unmet dependency, for two independent reasons:

1. **A power ranking describes current strength; a final placement is an
   outcome of that strength (and of the playoff bracket's seeding and
   single-elimination variance) already having played out.** Feeding a
   playoff result into a "how strong is this team" score would be
   circular for any in-season or end-of-regular-season use, and even for a
   fully-complete season it would let one or two playoff games (which this
   package's own ``consistency.py`` documents as a two-or-three-week sample,
   the smallest and noisiest slice of a season) dominate a score built
   everywhere else from full-season rates.
2. **It is frequently unavailable, and unavailable non-uniformly.** Per
   ``playoffs.py``'s "Undetermined placements" section, a roster whose place
   is not explicitly awarded by a ``p``-bearing bracket match simply has no
   placement -- this is normal, not a data error, and it is common for a
   consolation bracket to leave several rosters' places undetermined (the
   repository's own ``losers_bracket.json`` fixture awards only one of
   several possible places). A feature that is silently missing for an
   arbitrary subset of rosters, worse yet concentrated among the rosters
   that missed the playoffs, cannot be folded into a composite score without
   either dropping those rosters from the ranking entirely or inventing a
   value for them -- both worse than the ``all_play_win_pct``/``win_pct``/
   ``mean_points`` features already used, none of which have this gap.

A future ticket building a *retrospective, whole-season* summary that
explicitly wants "how the season actually ended" is free to join
``build_final_placements``'s output onto this frame by ``roster_id`` -- nothing
here prevents that -- but that is a different, narrower question than the one
this power ranking answers, and is out of scope for FFA-056.

Regular season vs. playoffs
------------------------------

This function applies **no** ``is_playoff`` filter and makes no phase
distinction of its own, matching every module it is built from
(``build_schedule_luck``, ``build_consistency_metrics``) and the
established FFA-040 through FFA-054 precedent. ``is_playoff`` is not read
and is not carried into the output.

Filtering is the caller's job, exactly as it is for ``schedule_luck.py`` and
``strength_of_schedule.py``: pass ``season_matchup_df[season_matchup_df["is_playoff"]
== False]`` for the conventional meaning of a power ranking -- an in-season
read on regular-season strength. A playoff bracket is seeded, not scheduled,
so mixing playoff weeks into ``win_pct``/``all_play_win_pct``/``mean_points``
changes what those numbers describe (see ``schedule_luck.py`` and
``consistency.py``'s own notes on small playoff-week samples); this is a
generic feature of the frame this module is composed from, not something
specific to power rankings, so the responsibility stays with the caller
rather than being duplicated here.

Missing values / edge cases
------------------------------

- **Empty ``season_matchup_df``**: returns an empty DataFrame with
  :data:`POWER_RANKING_COLUMNS`.
- **A roster with zero decided games** (never played, bye-only, or every
  matchup undecided): ``build_schedule_luck`` emits no row for it, so it has
  no ``win_pct`` to combine with anything else and this module emits no row
  for it either. This is not a special case here; it is simply inherited
  from the "zero games -> no row" precedent every upstream metric this
  module composes already follows.
- **A zero-variance feature** (e.g. two rosters that split their two
  meetings by identical scores, or -- more generally -- any small,
  hand-built scenario where every roster in the row set shares a value on
  one or more columns): that feature's z-score is ``0.0`` for every roster
  under the zero-variance rule above, and the remaining feature(s) alone
  determine the ordering. Note that a genuinely single-roster row set cannot
  arise from real pipeline data: every decided game that gives one roster a
  ``win``/``loss``/``tie`` symmetrically gives its opponent one too (see
  ``derive_roster_totals``), so any roster with ``games_played > 0`` implies
  at least one other roster with ``games_played > 0`` as well. The
  zero-variance rule is exercised in practice by same-valued *pairs* (or
  larger groups) of rosters, not by a row set of size one.
- **Ties** in ``power_score`` share a rank under standard competition
  ranking; see "Tie-breaking" above.
- **Internal inconsistency propagated from upstream**: if
  ``season_matchup_df`` is self-contradictory in a way ``build_schedule_luck``
  already rejects (a decided game recorded with no points), the resulting
  ``ValueError`` propagates unchanged rather than being caught here.
- **Multiple seasons in one frame**: pooled into a single row per roster,
  inheriting that behavior from every upstream function. Filter by
  ``season`` first for a per-season power ranking.
"""

from __future__ import annotations

from statistics import fmean, pstdev

import pandas as pd

from fantasy_analyzer.analytics.consistency import build_consistency_metrics
from fantasy_analyzer.analytics.schedule_luck import build_schedule_luck
from fantasy_analyzer.analytics.weekly_scores import build_weekly_scoring_ranks

#: Column order for the DataFrame returned by :func:`build_power_rankings`.
POWER_RANKING_COLUMNS = [
    "roster_id",
    "owner",
    "games_played",
    "win_pct",
    "all_play_win_pct",
    "mean_points",
    "win_pct_z",
    "all_play_win_pct_z",
    "mean_points_z",
    "power_score",
    "power_rank",
]

#: Weight on the z-scored actual ``win_pct`` -- see the module docstring's
#: "Weights and estimation method" section for why this specific split.
WIN_PCT_WEIGHT = 0.3

#: Weight on the z-scored schedule-independent ``all_play_win_pct`` -- the
#: largest of the three weights, per the module docstring.
ALL_PLAY_WIN_PCT_WEIGHT = 0.5

#: Weight on the z-scored ``mean_points`` -- the smallest of the three
#: weights, per the module docstring.
MEAN_POINTS_WEIGHT = 0.2


def _population_zscores(values: dict[int, float]) -> dict[int, float]:
    """Population z-score each value in ``values``, keyed the same way.

    ``(x - mean) / population_stdev``. If every value is identical (a
    zero-variance column, including the trivial single-roster case), every
    z-score is ``0.0`` rather than a division by zero -- see the module
    docstring's "Scaling: population z-scores, and the zero-variance rule".
    """
    raw = list(values.values())
    mean = fmean(raw)
    stdev = pstdev(raw)
    if stdev == 0:
        return dict.fromkeys(values, 0.0)
    return {roster_id: (value - mean) / stdev for roster_id, value in values.items()}


def build_power_rankings(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row per roster of a documented, transparent power ranking.

    Composes :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
    (for ``win_pct`` and ``all_play_win_pct``) with
    :func:`~fantasy_analyzer.analytics.consistency.build_consistency_metrics`
    (for ``mean_points``), both built from the same ``season_matchup_df``,
    z-scores each of the three features across the roster set this call
    produces, and combines them into ``power_score`` using the named,
    documented weights :data:`WIN_PCT_WEIGHT`, :data:`ALL_PLAY_WIN_PCT_WEIGHT`
    and :data:`MEAN_POINTS_WEIGHT`. See the module docstring for why these
    three features (and no others -- notably not ``schedule_luck`` or any
    consistency/volatility metric, and not FFA-055's final placements) were
    chosen, the exact formula and scaling, the tie-breaking rule, the
    intended interpretation, and the regular-season-vs-playoff behavior.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
            Filter it to ``is_playoff == False`` *before* calling for the
            conventional regular-season power ranking, or to weeks ``<= N``
            for an "as of week N" snapshot; this function applies no phase
            or week filter of its own.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used to resolve the
            ``owner`` label (passed through to the upstream functions this
            module composes).

    Returns:
        A DataFrame with columns :data:`POWER_RANKING_COLUMNS`, one row per
        roster with at least one decided game in the input, sorted by
        descending ``power_score`` then ascending ``roster_id``.
        ``power_rank`` is 1-indexed standard competition ranking with ``1``
        the model's **strongest** roster. Returns an empty DataFrame with
        the expected columns if ``season_matchup_df`` is empty or no roster
        has a decided game. A roster whose ``owner`` is unresolved stays
        ``None`` rather than raising.

    Raises:
        ValueError: Propagated unchanged from
            :func:`~fantasy_analyzer.analytics.schedule_luck.build_schedule_luck`
            if the input is internally inconsistent (a decided game on a row
            with no points).
    """
    if season_matchup_df.empty:
        return pd.DataFrame(columns=POWER_RANKING_COLUMNS)

    # win_pct / all_play_win_pct: the row set for this whole function is
    # driven by this frame -- a roster absent here (zero decided games) has
    # no record to combine with anything else, and gets no row anywhere
    # downstream either.
    schedule_luck_df = build_schedule_luck(season_matchup_df, teams_df)
    if schedule_luck_df.empty:
        return pd.DataFrame(columns=POWER_RANKING_COLUMNS)

    # mean_points: built from the same season_matchup_df, so it describes
    # the same games. Every roster with a decided game necessarily has at
    # least one scored week (outcomes.py only sets a winner when both
    # sides' points are present), so every roster_id in schedule_luck_df is
    # guaranteed to resolve here for a well-formed input.
    consistency_df = build_consistency_metrics(
        build_weekly_scoring_ranks(season_matchup_df, teams_df)
    )
    mean_points_by_roster = consistency_df.set_index("roster_id")[
        "mean_points"
    ].to_dict()

    win_pct: dict[int, float] = {}
    all_play_win_pct: dict[int, float] = {}
    mean_points: dict[int, float] = {}
    games_played: dict[int, int] = {}
    owner_by_roster: dict[int, object] = {}

    for row in schedule_luck_df.itertuples(index=False):
        roster_id = int(row.roster_id)
        if roster_id not in mean_points_by_roster:
            # Cannot happen for a well-formed pipeline input -- see the
            # docstring note above -- guarded rather than silently emitting
            # a NaN feature into the composite.
            raise ValueError(
                f"roster_id {roster_id} has a decided-game record but no "
                "scored week in the consistency table -- season_matchup_df "
                "is internally inconsistent"
            )
        win_pct[roster_id] = float(row.win_pct)
        all_play_win_pct[roster_id] = float(row.all_play_win_pct)
        mean_points[roster_id] = float(mean_points_by_roster[roster_id])
        games_played[roster_id] = int(row.games_played)
        owner_by_roster[roster_id] = row.owner if pd.notna(row.owner) else None

    win_pct_z = _population_zscores(win_pct)
    all_play_win_pct_z = _population_zscores(all_play_win_pct)
    mean_points_z = _population_zscores(mean_points)

    rows = []
    for roster_id in win_pct:
        power_score = (
            WIN_PCT_WEIGHT * win_pct_z[roster_id]
            + ALL_PLAY_WIN_PCT_WEIGHT * all_play_win_pct_z[roster_id]
            + MEAN_POINTS_WEIGHT * mean_points_z[roster_id]
        )
        rows.append(
            {
                "roster_id": roster_id,
                "games_played": games_played[roster_id],
                "win_pct": win_pct[roster_id],
                "all_play_win_pct": all_play_win_pct[roster_id],
                "mean_points": mean_points[roster_id],
                "win_pct_z": win_pct_z[roster_id],
                "all_play_win_pct_z": all_play_win_pct_z[roster_id],
                "mean_points_z": mean_points_z[roster_id],
                "power_score": power_score,
            }
        )

    result = pd.DataFrame(rows)
    result = result.sort_values(
        by=["power_score", "roster_id"], ascending=[False, True]
    ).reset_index(drop=True)

    # Standard competition ("1224") ranking on power_score alone, strongest
    # first: tied rosters share a rank and the next distinct rank skips the
    # tied count. The roster_id sort above is display order only and is not
    # a rank tiebreak -- see the module docstring's "Tie-breaking" section.
    ranks = []
    current_rank = 0
    previous_key = None
    for position, key in enumerate(result["power_score"], start=1):
        if key != previous_key:
            current_rank = position
            previous_key = key
        ranks.append(current_rank)
    result["power_rank"] = ranks

    # ``owner`` is assigned as its own explicit ``dtype=object`` Series
    # rather than as a plain dict value inside ``rows``: pandas' newer
    # default string-dtype inference otherwise upcasts a column mixing real
    # owner names with ``None`` into a string dtype that silently turns
    # ``None`` into ``NaN``, breaking the documented "unresolved owner ->
    # ``None``" contract (see ``schedule_luck.py``/``all_play.py``'s
    # identical note).
    result["owner"] = pd.Series(
        [owner_by_roster[roster_id] for roster_id in result["roster_id"]],
        dtype=object,
    )
    return result[POWER_RANKING_COLUMNS]
