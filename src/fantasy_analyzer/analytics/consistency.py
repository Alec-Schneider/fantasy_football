"""Team consistency metrics from weekly scores (FFA-053).

Consumes FFA-050's
:func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
output and collapses each roster's weekly scores into one row describing the
**shape of that roster's own scoring distribution**: where it centers, how
much it moves, how low it sank, how high it reached, and how often it landed
far from its own normal week. This module performs no network access; it
operates entirely on an already-built ``weekly_scoring_ranks_df``.

Every metric here is *within-roster*. Nothing in this module compares one
roster's scores against another's -- that is what FFA-050's ``weekly_rank``
and FFA-051's all-play records are for. A roster that scores 70 points every
single week is maximally consistent by these metrics and also the worst team
in the league; ``mean_points`` is included precisely so that no consistency
column is ever read without its level.

Metric definitions
-------------------

Let ``x_1 ... x_n`` be the ``points`` values on that roster's rows in the
input -- one per week in which it has a defined score (see "Rows are
input-driven" below) -- and let ``k`` be ``boom_bust_threshold``
(:data:`BOOM_BUST_THRESHOLD_STDEVS` by default).

- **weeks_played** -- ``n``, the count of weeks with a defined score. The same
  denominator concept as ``all_play.py``'s ``weeks_played``, and the sample
  size behind every other column in the row. It is deliberately the first
  metric column: at ``n`` around 14 these are all small-sample statistics.
- **mean_points** -- ``(1/n) * sum(x_i)``. The arithmetic mean of the
  roster's weekly scores.
- **median_points** -- the middle value of the sorted scores for odd ``n``;
  the **arithmetic mean of the two middle values** for even ``n`` (the
  standard convention, and the one ``statistics.median`` and pandas'
  ``Series.median`` both use). For an even-week season the median is
  therefore generally not one of the roster's actual weekly scores. Reading
  it next to ``mean_points`` is the cheapest available skew check: a roster
  whose mean sits well above its median got there on a few spike weeks.
- **stdev_points** -- the **population** standard deviation
  ``sqrt( (1/n) * sum( (x_i - mean_points)^2 ) )``. See "Population, not
  sample, standard deviation" below -- this is a deliberate, non-default
  choice. Undefined (``NaN``) when ``n < 2``.
- **cv** -- the coefficient of variation, ``stdev_points / mean_points``: the
  roster's volatility expressed as a fraction of its own scoring level, so
  that a high-scoring team is not automatically called volatile. Undefined
  (``NaN``) when ``stdev_points`` is undefined or ``mean_points <= 0`` -- see
  "Coefficient of variation, 'where appropriate'" below.
- **scoring_floor** -- ``min(x_i)``, the roster's single worst week.
- **scoring_ceiling** -- ``max(x_i)``, the roster's single best week. Both are
  single observations, not estimated quantiles; they are the most
  sample-size-sensitive columns in the frame, since a longer season simply
  has more chances to produce an extreme.
- **boom_weeks** -- the count of weeks with
  ``x_i > mean_points + k * stdev_points``.
- **bust_weeks** -- the count of weeks with
  ``x_i < mean_points - k * stdev_points``.
- **boom_pct** / **bust_pct** -- ``boom_weeks / n`` and ``bust_weeks / n``.
  All four boom/bust columns are undefined (``NaN``) when ``n < 3``; see
  "Small samples" below.

Population, not sample, standard deviation
--------------------------------------------

``stdev_points`` uses ``ddof = 0`` (population variance: divide by ``n``),
**not** ``ddof = 1`` (sample variance: divide by ``n - 1``).

This is stated loudly because it is not the default anywhere a reader is
likely to check it: ``pandas.Series.std()`` and ``pandas.DataFrame.std()``
default to ``ddof = 1``, as does ``statistics.stdev``. A caller who
recomputes this column with ``df.groupby("roster_id")["points"].std()`` will
get a *different, larger* number and conclude this module is wrong. For a
14-week season the two differ by a factor of ``sqrt(14/13) ~ 1.038``, i.e.
about 4% -- large enough to change a close ordering, small enough to go
unnoticed.

The choice follows from what this frame describes. Bessel's correction
(``n - 1``) exists to make the variance an unbiased estimator of a wider
population's variance from a *sample* drawn out of it. There is no wider
population here: the weeks in the input are not a sample of a roster's
possible seasons, they are the complete and only set of weeks that roster
actually played. This module is a descriptive summary of a finished (or
in-progress) season, so the descriptive, population form is the right one.

Sample standard deviation would be defensible under a different reading --
"these 14 weeks are a sample of this manager's underlying week-to-week
scoring process, and I want to estimate that process's spread" -- which is a
genuinely reasonable thing to want and is the reading a *predictive* ticket
would take. FFA-053 is retrospective, so it takes the descriptive reading.
To avoid the silent-default trap in the implementation as well as in the
docs, the code calls ``statistics.pstdev``, whose name states the convention,
rather than passing ``ddof`` to a function that would otherwise do something
else.

Boom and bust: a self-referential threshold
----------------------------------------------

A **boom week** is one in which the roster scored more than ``k`` of its own
standard deviations above its own season mean; a **bust week** is one in
which it scored more than ``k`` of its own standard deviations below it. The
default ``k`` is :data:`BOOM_BUST_THRESHOLD_STDEVS` = ``1.0``.

**``k = 1.0`` is a chosen convention, not a standard.** AGENTS.md asks for
"boom/bust frequency" and specifies no threshold, and no threshold is
canonical in fantasy analysis. ``k = 1.0`` is picked because it is the
smallest round z-score that means anything, and because it leaves the metric
with useful resolution over a fantasy season: on realistic weekly scores a
14-week roster typically records two to four booms and two to four busts, so
``boom_pct`` actually separates rosters. A larger ``k`` (1.5, 2.0) would push
most rosters to zero booms over 14 weeks and turn the column into a
mostly-empty flag. ``k = 1.5`` or ``k = 2.0`` would be equally defensible
choices for a longer history; ``boom_bust_threshold`` is a parameter so that
a caller can make one without forking the metric, and any published number
should say which ``k`` produced it.

**Why self-referential rather than league-relative.** The obvious
alternative is a league-wide threshold -- "a boom is a week in the league's
top decile of scores", or "a boom is 130+ points". That would be a *scoring
strength* metric wearing a consistency label: a strong team would boom
constantly and a weak team never, and the column would tell you almost
exactly what FFA-050's ``weekly_rank`` and FFA-051's ``all_play_win_pct``
already tell you, only worse. Measuring against the roster's own baseline
instead answers the question consistency is actually about -- "how often does
this team blow up or implode *relative to its own normal week*" -- and lets a
mediocre, wildly swingy team and a mediocre, metronomic team look different,
which is the entire point of the ticket. It also makes the metric
scale-free, so it is comparable across leagues with different scoring
settings.

**Strict inequality**, not ``>=``. This matters at exactly one place, and it
is not a rounding nicety: for ``n = 2`` every observation sits *exactly* one
population standard deviation from the mean, so ``>=`` with ``k = 1.0`` would
label both weeks of every two-week roster as a boom and a bust
simultaneously. (Two-week rosters are excluded outright for a related reason;
see below.)

**What boom_pct does and does not distinguish.** Because the threshold is
measured in the roster's own standard deviations, ``boom_pct`` is a
*frequency* of self-relative outliers and carries no magnitude. A metronomic
roster averaging 100 with a standard deviation of 1.4 and a chaotic roster
averaging 100 with a standard deviation of 37 can both post one boom in four
weeks; the first boomed by 2 points and the second by 50. ``boom_pct`` says
they blow up equally often, ``stdev_points`` and ``cv`` say how hard, and
``scoring_ceiling`` says how high. The columns are meant to be read together
and this one is not a standalone volatility measure.

Small samples: when dispersion and boom/bust are undefined
-------------------------------------------------------------

Two different minimum week counts apply, for two different reasons.

**``weeks_played < 2`` -> ``stdev_points`` and ``cv`` are ``NaN``.** A single
observation has no spread. Under the population convention the arithmetic
would technically return ``0.0`` (the one score's deviation from its own mean
is zero), and that number is worse than useless: it would place a roster with
one loaded week at the very top of any "most consistent team" sort, tied with
a roster that genuinely scored the same total every week for a full season.
"No information" and "perfectly steady" are reported as different things.

**``weeks_played < 3`` -> ``boom_weeks``, ``bust_weeks``, ``boom_pct`` and
``bust_pct`` are ``NaN``.** This is a stronger requirement than dispersion's,
and it is not caution -- for ``n = 2`` the classification is provably
*independent of the data*. With two scores ``a < b``, the mean is
``(a + b) / 2`` and the population standard deviation is exactly
``(b - a) / 2``, so ``b - mean == stdev`` identically. Whether ``b`` counts
as a boom therefore reduces to whether ``k < 1``, for every possible pair of
scores: at ``k = 1.0`` a two-week roster always has zero booms and zero
busts, and at ``k = 0.5`` it always has exactly one of each. The column would
be a restatement of ``k``, not an observation about the team.

Floating point makes the same case empirically. Because ``b`` sits exactly on
the threshold, the comparison is decided by the last bits of the arithmetic:
over 20,000 random two-week pairs of realistic scores, roughly 30% were
classified as a boom or a bust purely by rounding noise. Emitting that would
be emitting an arbitrary number. Two-week rosters are not exotic -- filtering
this frame to ``is_playoff == True`` produces them routinely -- so this is
handled rather than warned about.

At ``n = 3`` the classification does depend on the data, and the module
computes it, but it stays coarse: since the deviations sum to zero, two
observations cannot both exceed ``+1`` standard deviation (that would force
the third below ``-2``, which the variance does not allow), so a three-week
roster can record at most one boom and at most one bust and ``boom_pct`` can
only take the values ``0`` or ``1/3``. Treat boom/bust columns below roughly
a full season of weeks as directional at best.

Even a **full** regular season is a small sample for this column, and the
resolution is worth knowing before anyone builds on it. Validated against a
live 2025 twelve-roster league (14 regular-season weeks each, 168
roster-weeks), ``boom_weeks`` spanned only 1-3 across the twelve rosters and
``bust_weeks`` only 1-4, with eight of the twelve rosters recording exactly
two busts. That is the expected behavior of a z-score threshold on
roughly-symmetric data -- most rosters land two to four booms per fourteen
weeks almost regardless of how volatile they are -- so a one-boom difference
between two rosters is noise, not a finding. Over the same league,
``stdev_points`` and ``cv`` separated the field far more usefully (``cv``
ranged from 0.131 to 0.251, a near-twofold spread). Read boom/bust as a
coarse shape descriptor and use the dispersion columns for ordering.

Coefficient of variation, "where appropriate"
-----------------------------------------------

AGENTS.md asks for a coefficient of variation "where appropriate", and the
qualifier is load-bearing: ``stdev / mean`` is only interpretable for
ratio-scale data with a positive mean. ``cv`` is therefore reported only when
``mean_points > 0``, and is ``NaN`` otherwise.

- ``mean_points == 0`` is a division by zero. It is reachable, if barely: a
  roster credited with ``0.0`` in every loaded week (an abandoned team, or a
  frame filtered down to weeks nobody's lineup scored) has a mean of zero and
  no meaningful relative volatility.
- ``mean_points < 0`` is essentially unreachable for a whole fantasy lineup,
  but if it occurred the ratio would come out negative -- an uninterpretable
  "volatility" -- so it is treated the same way rather than emitted.

``cv`` is a bare ratio, not a percentage: a roster averaging 100 with a
standard deviation of 15 has ``cv = 0.15``, not ``15.0``.

Rows are input-driven: a roster with no scored week is absent
---------------------------------------------------------------

Output rows come exclusively from rosters present in
``weekly_scoring_ranks_df``. A league roster that never appears there -- one
whose every week's score is missing, or a roster in ``teams_df`` that never
played -- gets **no row**, rather than a row of nulls. This follows
FFA-051's and FFA-052's established "zero games -> no row" precedent: a
distribution over zero observations is undefined, not empty-but-real, and
emitting it invites a reader to see a result in a roster that never played.

Every roster that does get a row therefore has ``weeks_played >= 1``, so
``mean_points``, ``median_points``, ``scoring_floor`` and ``scoring_ceiling``
are always defined; only the dispersion and boom/bust columns can be ``NaN``.

Why there is no ``teams_df`` parameter
----------------------------------------

``owner`` is read from the input frame's own ``owner`` column -- FFA-050
already resolved it from ``teams_df["display_name"]`` -- rather than being
re-resolved here. Combined with the input-driven row set above, that leaves
``teams_df`` with no role in this function, so it is not a parameter, exactly
as in ``all_play.py`` and ``head_to_head_matrix.py``.

A roster whose ``owner`` is unresolved in the input (``None``/``NaN``) stays
``None`` in the output rather than raising, consistent with FFA-050's own
contract. A roster's ``owner`` is read from the first row in which it has a
non-null value; ``owner`` is a per-roster label that FFA-050 resolves the
same way in every week, so this cannot disagree across weeks for a
well-formed input.

No rank column, and why
--------------------------

Unlike ``standings.py``, ``all_play.py`` and ``schedule_luck.py``, this frame
has **no rank column**, and rows are ordered by ascending ``roster_id`` --
a deterministic display order that asserts nothing.

Ranking requires a single "better" direction, and consistency does not have
one. Low ``stdev_points`` is good for a strong team (it protects a lead) and
bad for a weak one (it needs variance to steal a win); a high
``scoring_ceiling`` is good, a high ``boom_pct`` is neither. Any single
"consistency rank" would have to smuggle in a weighting of level against
spread, which is precisely the composite-score judgment call FFA-056's power
ranking model owns and is required to document. Emitting one here would be
the opaque score AGENTS.md's FFA-056 explicitly forbids, just under a
different column name. Callers who want an ordering should sort on the
specific column they mean.

Regular season vs. playoffs
------------------------------

This function computes a single **combined** distribution across every week
present in the input -- regular season and playoff alike. It applies no
``is_playoff`` filter and makes no phase distinction of its own, matching
FFA-040/FFA-042/FFA-050/FFA-051/FFA-052's established precedent.
``is_playoff`` is not read at all and is not carried into the output, since a
season-total row spans both phases and could not carry a single meaningful
value for it.

A caller wanting a phase-specific view should filter
``weekly_scoring_ranks_df`` on ``is_playoff`` **before** calling. Note that
the mean and standard deviation are then recomputed within the filtered
weeks, which is the intended meaning of a regular-season consistency profile
-- and note also that a typical playoff bracket leaves a roster with two or
three weeks, where per "Small samples" above most of this frame is ``NaN`` by
design.

Missing values / edge cases
----------------------------

- **Empty ``weekly_scoring_ranks_df``**: returns an empty DataFrame with
  :data:`CONSISTENCY_METRICS_COLUMNS`.
- **A row with missing ``points``**: FFA-050 never emits one (every row in
  its output has a real score), but if a hand-built input contains one it is
  skipped entirely -- it does not enter the distribution, does not count
  toward ``weeks_played``, and is never treated as ``0.0``. If that is true
  of every row, the result is an empty (but correctly-shaped) frame. Same
  "missing is not zero" rule as FFA-050, FFA-051 and ``reconciliation.py``.
- **A zero-variance roster** (``n >= 2``, every week identical): reports
  ``stdev_points = 0.0`` and ``cv = 0.0`` -- genuinely correct here, unlike
  the one-week case -- with ``scoring_floor == scoring_ceiling ==
  mean_points == median_points``. It records zero booms and zero busts with
  no special-casing: strict inequality against a threshold equal to the mean
  is false for every week.
- **Duplicate weekly scores** within a roster (the same points in two
  different weeks) need no special handling: ``median_points`` sorts and
  takes the middle position(s) of the multiset, and ``scoring_floor`` /
  ``scoring_ceiling`` are a plain min/max, all of which are well-defined with
  repeats. Nothing in this module deduplicates or ranks scores against each
  other, so there is no ties convention to apply.
- **Multiple seasons in one frame** are pooled into a single row per roster,
  inheriting ``all_play.py``'s behavior. This matters more here than it does
  there: pooling two seasons that were played at different scoring levels
  inflates ``stdev_points`` with the between-season shift and reports it as
  week-to-week volatility. Filter by ``season`` first for a per-season
  consistency profile.
- **Duplicate roster-weeks**: not validated here.
  :func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
  already raises on an input that would produce two rows for one
  ``(season, week, roster_id)``, so any frame it produces satisfies the
  uniqueness invariant this module relies on.

Column dtypes
--------------

Every metric column is ``float64`` and every undefined value is ``NaN`` --
including ``boom_weeks`` and ``bust_weeks``, which are whole numbers carried
as floats. They are cast explicitly so the dtype does not silently change
between calls depending on whether some roster happened to fall below the
minimum week count. ``weeks_played`` is a plain ``int64`` (it is never
undefined for a row that exists) and ``owner`` is ``object`` (so an
unresolved owner stays ``None``). Test undefined values with ``pd.isna``,
not ``is None``.
"""

from __future__ import annotations

from statistics import fmean, median, pstdev
from typing import Optional

import pandas as pd

#: Column order for the DataFrame returned by :func:`build_consistency_metrics`.
CONSISTENCY_METRICS_COLUMNS = [
    "roster_id",
    "owner",
    "weeks_played",
    "mean_points",
    "median_points",
    "stdev_points",
    "cv",
    "scoring_floor",
    "scoring_ceiling",
    "boom_weeks",
    "boom_pct",
    "bust_weeks",
    "bust_pct",
]

#: Default boom/bust threshold, in the roster's own standard deviations. A
#: chosen convention rather than a standard -- see the module docstring's
#: "Boom and bust: a self-referential threshold" section.
BOOM_BUST_THRESHOLD_STDEVS = 1.0

#: Fewest weeks for which ``stdev_points``/``cv`` are defined. One
#: observation has no spread; see "Small samples" in the module docstring.
MIN_WEEKS_FOR_DISPERSION = 2

#: Fewest weeks for which the boom/bust columns are defined. At two weeks the
#: classification is provably independent of the scores; see "Small samples"
#: in the module docstring.
MIN_WEEKS_FOR_BOOM_BUST = 3

#: Metric columns cast to ``float64`` so undefined values are ``NaN`` and the
#: dtype does not vary with the data -- see "Column dtypes" in the module
#: docstring.
_FLOAT_COLUMNS = [
    "mean_points",
    "median_points",
    "stdev_points",
    "cv",
    "scoring_floor",
    "scoring_ceiling",
    "boom_weeks",
    "boom_pct",
    "bust_weeks",
    "bust_pct",
]


def _summarize_roster(
    roster_id: int, points: list[float], boom_bust_threshold: float
) -> dict:
    """Summarize one roster's weekly scores into a consistency-metrics row.

    Applies the exact definitions in the module docstring: population
    standard deviation, a mean-relative boom/bust threshold measured in that
    standard deviation, and the ``MIN_WEEKS_FOR_DISPERSION`` /
    ``MIN_WEEKS_FOR_BOOM_BUST`` minimums below which the corresponding
    columns are ``None`` (rendered as ``NaN`` in the returned frame).
    """
    weeks_played = len(points)
    mean_points = fmean(points)

    # Population standard deviation (ddof = 0). ``pstdev`` is used rather than
    # ``pandas.Series.std()``/``statistics.stdev`` because those default to
    # the sample form -- see the module docstring.
    stdev_points: Optional[float] = (
        pstdev(points) if weeks_played >= MIN_WEEKS_FOR_DISPERSION else None
    )

    # "Where appropriate": a non-positive mean makes stdev/mean either a
    # division by zero or an uninterpretable negative ratio.
    cv: Optional[float] = (
        stdev_points / mean_points
        if stdev_points is not None and mean_points > 0
        else None
    )

    boom_weeks: Optional[int] = None
    bust_weeks: Optional[int] = None
    boom_pct: Optional[float] = None
    bust_pct: Optional[float] = None

    if weeks_played >= MIN_WEEKS_FOR_BOOM_BUST and stdev_points is not None:
        boom_threshold = mean_points + boom_bust_threshold * stdev_points
        bust_threshold = mean_points - boom_bust_threshold * stdev_points
        # Strict inequality: with ``>=`` a zero-variance roster would have
        # every week counted as both a boom and a bust.
        boom_weeks = sum(1 for value in points if value > boom_threshold)
        bust_weeks = sum(1 for value in points if value < bust_threshold)
        boom_pct = boom_weeks / weeks_played
        bust_pct = bust_weeks / weeks_played

    return {
        "roster_id": roster_id,
        "weeks_played": weeks_played,
        "mean_points": mean_points,
        "median_points": median(points),
        "stdev_points": stdev_points,
        "cv": cv,
        "scoring_floor": min(points),
        "scoring_ceiling": max(points),
        "boom_weeks": boom_weeks,
        "boom_pct": boom_pct,
        "bust_weeks": bust_weeks,
        "bust_pct": bust_pct,
    }


def build_consistency_metrics(
    weekly_scoring_ranks_df: pd.DataFrame,
    boom_bust_threshold: float = BOOM_BUST_THRESHOLD_STDEVS,
) -> pd.DataFrame:
    """Build one row per roster describing its weekly scoring distribution.

    Collapses each roster's weekly ``points`` into center (``mean_points``,
    ``median_points``), spread (``stdev_points``, ``cv``), extremes
    (``scoring_floor``, ``scoring_ceiling``) and self-relative outlier
    frequency (``boom_weeks``/``boom_pct``, ``bust_weeks``/``bust_pct``). See
    the module docstring for the exact formulas, the population-standard-
    deviation choice, the boom/bust threshold convention, the minimum week
    counts below which columns are ``NaN``, why there is no rank column, and
    the combined regular-season-plus-playoff behavior.

    Args:
        weekly_scoring_ranks_df: A
            :data:`~fantasy_analyzer.analytics.weekly_scores.WEEKLY_SCORING_RANK_COLUMNS`-shaped
            DataFrame, as produced by
            :func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`.
            Only ``roster_id``, ``points`` and ``owner`` are read; ``season``,
            ``week``, ``is_playoff`` and ``weekly_rank`` are ignored. Filter
            it on ``is_playoff`` before calling for a phase-specific view.
        boom_bust_threshold: How many of a roster's own standard deviations a
            week must exceed to count as a boom or a bust. Defaults to
            :data:`BOOM_BUST_THRESHOLD_STDEVS` (``1.0``), a documented
            convention rather than a standard.

    Returns:
        A DataFrame with columns :data:`CONSISTENCY_METRICS_COLUMNS`, one row
        per roster that has at least one scored week in the input, sorted by
        ascending ``roster_id`` (a display order; this frame has no rank
        column by design). ``stdev_points`` and ``cv`` are ``NaN`` for a
        roster with fewer than :data:`MIN_WEEKS_FOR_DISPERSION` weeks, and
        the four boom/bust columns are ``NaN`` for a roster with fewer than
        :data:`MIN_WEEKS_FOR_BOOM_BUST`; ``cv`` is also ``NaN`` when
        ``mean_points <= 0``. Returns an empty DataFrame with the expected
        columns if the input is empty or contains no row with a defined
        score. A roster whose ``owner`` is unresolved in the input stays
        ``None`` rather than raising.

    Raises:
        ValueError: If ``boom_bust_threshold`` is negative, which would make
            the boom and bust bands overlap and let a single week count as
            both.
    """
    if boom_bust_threshold < 0:
        raise ValueError(
            "boom_bust_threshold must be non-negative, got "
            f"{boom_bust_threshold!r} -- a negative threshold would put the "
            "boom band below the bust band and classify weeks as both"
        )

    if weekly_scoring_ranks_df.empty:
        return pd.DataFrame(columns=CONSISTENCY_METRICS_COLUMNS)

    scores: dict[int, list[float]] = {}
    owners: dict[int, Optional[str]] = {}

    for row in weekly_scoring_ranks_df.itertuples(index=False):
        # FFA-050 never emits a missing score, but a hand-built input might:
        # such a week has no defined score, so it is left out of the
        # distribution entirely rather than treated as 0.0.
        if pd.isna(row.points):
            continue

        roster_id = int(row.roster_id)
        scores.setdefault(roster_id, []).append(float(row.points))

        owners.setdefault(roster_id, None)
        if owners[roster_id] is None and pd.notna(row.owner):
            owners[roster_id] = row.owner

    # Every observation may have been skipped (e.g. a frame of missing
    # scores): return an empty, correctly-shaped frame rather than letting
    # pd.DataFrame([]) build a columnless frame.
    if not scores:
        return pd.DataFrame(columns=CONSISTENCY_METRICS_COLUMNS)

    # Rows are emitted in ascending roster_id order -- deterministic display
    # order only; see the module docstring's "No rank column" section.
    result = pd.DataFrame(
        [
            _summarize_roster(roster_id, points, boom_bust_threshold)
            for roster_id, points in sorted(scores.items())
        ]
    )

    result["weeks_played"] = result["weeks_played"].astype(int)
    # Cast explicitly so an undefined value is always NaN in a float64 column,
    # rather than None in an object column whenever every roster cleared the
    # minimum week counts -- see the module docstring's "Column dtypes".
    for column in _FLOAT_COLUMNS:
        result[column] = result[column].astype(float)

    # ``owner`` is assigned as its own explicit ``dtype=object`` Series rather
    # than as a plain dict value inside the rows: pandas' newer default
    # string-dtype inference otherwise upcasts a column mixing real owner
    # names with ``None`` into a string dtype that silently turns ``None``
    # into ``NaN``, breaking the documented "unresolved owner -> ``None``"
    # contract (see ``all_play.py``/``weekly_scores.py``'s identical note).
    result["owner"] = pd.Series(
        [owners[roster_id] for roster_id in result["roster_id"]],
        dtype=object,
    )
    return result[CONSISTENCY_METRICS_COLUMNS]
