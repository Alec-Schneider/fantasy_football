"""Per-team draft grades and deterministic talking points (FFA-079, FFA-080).

This module is the aggregation layer on top of FFA-078's pick-level grades
(:func:`~fantasy_analyzer.players.draft_grade.score_draft_picks`,
``SCORED_DRAFT_PICK_COLUMNS``). It answers two questions, one per public
function:

- :func:`build_team_draft_grades` (FFA-079) -- "how did each team's draft
  go, on a single letter grade and rank, relative to the other teams in
  *this* draft?"
- :func:`build_draft_talking_points` (FFA-080) -- "what are the structured,
  hand-checkable facts an agent could turn into commentary about each
  team's draft?" No prose is generated here -- every output is a number, a
  rank, a name, or a small dict, by design (see that function's docstring).

Both functions operate on a single league's single draft at a time (the
same scoping convention every FFA-06x/07x sibling in this package uses):
every z-score, rank, and threshold below is computed from the population of
teams present in the ``scored_picks_df``/``team_grades_df`` passed in, so a
frame spanning two drafts would blend their team pools into one z-score
population and one rank order. That is not supported.

Metric definition -- the "scoreable, non-excluded" filter
--------------------------------------------------------------------------

Both functions repeatedly need "does this pick count toward a team's
number," and the answer is the same two-part filter throughout this module:

    ``expected_pick_source != "unscored"`` (the board could score the
    player at all) **and** ``excluded_reason is None`` (nothing -- e.g.
    being a keeper -- disqualifies the pick from counting toward value).

A pick that fails either half is excluded from ``total_vor``,
``avg_pick_value``, ``best_pick``/``worst_pick``, and (in
:func:`build_draft_talking_points`) ``reach_count``/``value_count``, but is
still counted in ``unscored_pick_count``/``keeper_pick_count`` and in the
roster-construction figures (``most_drafted_position``,
``position_counts``), which intentionally look at *every* pick a team made,
scoreable or not, keeper or not -- see that function's docstring for why.

Team draft grade -- two z-scored components blended into ``overall_z``
--------------------------------------------------------------------------

For each team, over its scoreable, non-excluded picks:

- ``total_vor`` = sum of ``vor``. ``NaN`` if the team has zero such picks
  (not ``0.0`` -- a team with no data cannot be said to be "exactly
  replacement level"; that would be a claim this module cannot support).
- ``avg_pick_value`` = mean of ``pick_value``. Same ``NaN``-if-empty rule.

Both are then **population z-scored** (``ddof=0``) across every team in
this draft, using the identical drop-and-renormalize convention
:func:`~fantasy_analyzer.players.draft_board.build_draft_board`'s
``_population_zscores`` documents (reimplemented locally rather than
imported -- this codebase does not import private names across modules): a
team with ``total_vor = NaN`` takes no part in that z-score's mean/stdev and
comes back ``NaN``; the whole z-score is ``NaN`` for every team if fewer
than two teams have a usable value, or if the population has zero variance.

    ``overall_z = weights.vor * z(total_vor) + weights.value * z(avg_pick_value)``

blended with the identical drop-and-renormalize weighted-average rule
``draft_board.py``'s ``_weighted_blend`` documents (also reimplemented
locally): a team missing one of the two z-scores is blended on whichever it
has; a team missing both gets ``overall_z = NaN``.

``grade_letter`` is read off fixed thresholds on ``overall_z``:

+------------------+--------+
| ``overall_z``    | Letter |
+==================+========+
| ``>= 1.5``       | A+     |
+------------------+--------+
| ``>= 1.0``       | A      |
+------------------+--------+
| ``>= 0.5``       | B+     |
+------------------+--------+
| ``>= 0.0``       | B      |
+------------------+--------+
| ``>= -0.5``      | C+     |
+------------------+--------+
| ``>= -1.0``      | C      |
+------------------+--------+
| ``>= -1.5``      | D      |
+------------------+--------+
| ``< -1.5``       | F      |
+------------------+--------+

``NaN`` -> ``grade_letter = None`` -- a team with no scoreable data cannot
be graded, and reporting a fabricated "F" would be a claim this module has
no basis for.

``draft_rank`` is standard competition ("1224") ranking on ``overall_z``
descending (best team first), the identical convention
``draft_board.py``'s ``_assign_competition_ranks`` uses (rounded to 6
decimal places before comparing, so two mathematically-tied z-blends cannot
be split by floating-point noise). Ties share a rank and the next distinct
rank skips the tied count (e.g. two teams tied for best get ``draft_rank``
1, 1 and the next team gets 3, not 2). The underlying sort order used to
assign that rank (not the rank number itself, which ties share) breaks ties
by ascending ``roster_id``, for a deterministic display order. Teams with
``overall_z = NaN`` get ``draft_rank = NaN`` and sort after every ranked
team.

Toy example (hand-checked in tests)
--------------------------------------------------------------------------

Four teams, ``total_vor = [40, 20, 10, -10]``: mean 15, population variance
``mean((x-15)^2) = (625+25+25+625)/4 = 325``, stdev ``sqrt(325) ~= 18.0278``,
so ``z(total_vor) ~= [1.3868, 0.2774, -0.2774, -1.3868]``. See
``test_draft_report.py`` for the analogous hand-built ``avg_pick_value``
example and the fully worked ``overall_z``/``grade_letter``/``draft_rank``
arithmetic.

Talking points (FFA-080) -- structured facts, not prose
--------------------------------------------------------------------------

:func:`build_draft_talking_points` produces one row per team of plain data
-- numbers, ranks, names, and a JSON-able ``dict`` -- with no generated
sentences. This is a deliberate scope boundary: turning these facts into
commentary is a later, non-code ticket's job, and baking prose in here would
make that ticket's output depend on wording choices made in this one.

- ``total_vor_rank``/``avg_pick_value_rank`` are computed **fresh** here
  (standard competition rank, descending, ``NaN`` sorts last) --
  ``team_grades_df`` (FFA-079's own output) only ranks on the *blended*
  ``overall_z``, not on either raw component individually, so this function
  does not reuse an existing column.
- ``most_drafted_position``/``position_counts`` are computed over **all**
  of a team's picks (including keepers and unscored picks) -- this is a
  roster-construction question ("what did this team's draft board look
  like"), not a value-grading one, so the scoreable/non-excluded filter
  does not apply here. Ties for "most drafted" are broken by picking the
  alphabetically-first position name (e.g. a team with 3 RB and 3 WR picks
  reports ``"RB"``) -- an arbitrary but fully deterministic rule, chosen
  only so the output never depends on iteration order. ``position_counts``
  groups a missing/``NaN`` position under the key ``"UNKNOWN"``.
- ``reach_count``/``value_count`` use the scoreable, non-excluded filter
  (this *is* a value-grading question) and a threshold parameterized by
  ``num_teams`` -- one full round of the draft -- rather than a hardcoded
  12: ``threshold = num_teams``, so for a 12-team league
  ``|pick_value| > 12`` reads as "taken more than a full round earlier/later
  than expected." ``reach_count`` counts picks with ``pick_value <
  -threshold``; ``value_count`` counts picks with ``pick_value >
  threshold``. A pick exactly at the threshold (``pick_value == threshold``
  or ``== -threshold``) counts as neither -- the definition is strictly
  "beyond" one round, not "at least" one round.

Regular season vs. playoffs
--------------------------------------------------------------------------

Not applicable. Like FFA-078, this is a draft-time metric computed once per
draft, before any games are played -- there is no regular-season/playoff
distinction to make.

Missing values / edge cases
--------------------------------------------------------------------------

- **Empty ``scored_picks_df``**: :func:`build_team_draft_grades` returns an
  empty frame with :data:`TEAM_DRAFT_GRADE_COLUMNS` and the documented
  per-column dtypes.
- **Empty ``team_grades_df``**: :func:`build_draft_talking_points` returns
  an empty frame with :data:`DRAFT_TALKING_POINT_COLUMNS`.
- **A team with zero scoreable, non-excluded picks** (every pick unscored,
  every pick a keeper, or some mix of the two): ``total_vor``,
  ``avg_pick_value``, ``overall_z`` are all ``NaN``; ``grade_letter`` is
  ``None``; ``draft_rank`` is ``NaN``; ``best_pick_*``/``worst_pick_*`` are
  all ``None``/``NaN``. This team is correctly **excluded** from the
  z-score population (not zero-filled), so it cannot drag every other
  team's z-score toward it.
- **A single-team draft** (or any z-scored quantity with fewer than two
  usable values across the whole draft): the identical zero-variance guard
  ``draft_board.py`` documents -- that z-score is ``None``/``NaN`` for
  *every* team, so with one team ``overall_z`` is always ``NaN`` and
  ``grade_letter`` is always ``None``.
- **Ties in ``pick_value`` for ``best_pick``/``worst_pick``**: broken by
  earliest ``pick_no`` (ascending), for a deterministic, hand-checkable
  choice among otherwise-equal picks.
- **Ties in ``overall_z``/``total_vor``/``avg_pick_value`` for ranking**:
  standard competition ranking throughout this module -- tied values share
  a rank, and the next distinct rank skips the tied count (e.g. 1, 1, 3).

Column dtypes
--------------------------------------------------------------------------

``roster_id`` and the label columns (``team_name``, ``best_pick_player``,
``worst_pick_player``, ``grade_letter``, ``most_drafted_position``) are
``object``, with missing values represented as ``None``. ``position_counts``
is ``object`` holding a plain ``dict``. ``unscored_pick_count``,
``keeper_pick_count``, ``reach_count``, ``value_count``, and ``num_teams``
are ``int64`` (always defined for a row that exists -- these are counts,
never undefined). Every other numeric column (``total_vor``,
``avg_pick_value``, the ``*_z``/``overall_z`` columns, every
``best_pick_*``/``worst_pick_*`` numeric field, both rank columns) is
``float64``, so an undefined value is ``NaN``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any, Optional

import pandas as pd

#: Column order for :func:`build_team_draft_grades`'s return value.
TEAM_DRAFT_GRADE_COLUMNS = [
    "roster_id",
    "team_name",
    "total_vor",
    "avg_pick_value",
    "unscored_pick_count",
    "keeper_pick_count",
    "best_pick_player",
    "best_pick_round",
    "best_pick_pick_no",
    "best_pick_value",
    "worst_pick_player",
    "worst_pick_round",
    "worst_pick_pick_no",
    "worst_pick_value",
    "total_vor_z",
    "avg_pick_value_z",
    "overall_z",
    "grade_letter",
    "draft_rank",
]

#: Column order for :func:`build_draft_talking_points`'s return value.
DRAFT_TALKING_POINT_COLUMNS = [
    "roster_id",
    "team_name",
    "grade_letter",
    "draft_rank",
    "num_teams",
    "total_vor",
    "total_vor_rank",
    "avg_pick_value",
    "avg_pick_value_rank",
    "best_pick_player",
    "best_pick_round",
    "best_pick_value",
    "worst_pick_player",
    "worst_pick_round",
    "worst_pick_value",
    "most_drafted_position",
    "position_counts",
    "reach_count",
    "value_count",
    "unscored_pick_count",
]

_GRADE_FLOAT_COLUMNS = [
    "total_vor",
    "avg_pick_value",
    "best_pick_round",
    "best_pick_pick_no",
    "best_pick_value",
    "worst_pick_round",
    "worst_pick_pick_no",
    "worst_pick_value",
    "total_vor_z",
    "avg_pick_value_z",
    "overall_z",
    "draft_rank",
]

_GRADE_INT_COLUMNS = ["unscored_pick_count", "keeper_pick_count"]

_GRADE_LABEL_COLUMNS = [
    "team_name",
    "best_pick_player",
    "worst_pick_player",
    "grade_letter",
]

_TALKING_POINT_FLOAT_COLUMNS = [
    "draft_rank",
    "total_vor",
    "total_vor_rank",
    "avg_pick_value",
    "avg_pick_value_rank",
    "best_pick_round",
    "best_pick_value",
    "worst_pick_round",
    "worst_pick_value",
]

_TALKING_POINT_INT_COLUMNS = [
    "num_teams",
    "reach_count",
    "value_count",
    "unscored_pick_count",
]

_TALKING_POINT_LABEL_COLUMNS = [
    "team_name",
    "grade_letter",
    "best_pick_player",
    "worst_pick_player",
    "most_drafted_position",
]


@dataclass(frozen=True)
class DraftGradeWeights:
    """Blend weights for :func:`build_team_draft_grades`'s ``overall_z``.

    Mirrors :class:`~fantasy_analyzer.players.draft_board.DraftBoardWeights`'s
    validation pattern exactly. Weights do **not** need to sum to 1.0 (the
    blend is renormalized by whichever weights were actually usable for a
    given team), but the defaults do.

    Attributes:
        vor: Weight on ``z(total_vor)`` -- the season-aggregate value
            signal.
        value: Weight on ``z(avg_pick_value)`` -- the rate/efficiency
            signal.

    Raises:
        ValueError: If either weight is negative or not a number, or if
            both are zero (no defined normalization).
    """

    vor: float = 0.5
    value: float = 0.5

    def __post_init__(self) -> None:
        for field_name in ("vor", "value"):
            weight = getattr(self, field_name)
            if not (weight >= 0):
                raise ValueError(
                    f"DraftGradeWeights.{field_name} must be a non-negative "
                    f"number; got {weight!r}"
                )
        if self.vor + self.value <= 0:
            raise ValueError(
                "DraftGradeWeights.vor and .value cannot both be zero; the "
                "blend would have no defined normalization"
            )


#: Default blend weights -- see :class:`DraftGradeWeights`.
DEFAULT_DRAFT_GRADE_WEIGHTS = DraftGradeWeights()

#: ``overall_z`` thresholds -> letter grade, checked highest-first. See the
#: module docstring's "Team draft grade" table.
_GRADE_THRESHOLDS = (
    (1.5, "A+"),
    (1.0, "A"),
    (0.5, "B+"),
    (0.0, "B"),
    (-0.5, "C+"),
    (-1.0, "C"),
    (-1.5, "D"),
)


def _is_missing(value: Any) -> bool:
    """True for ``None``, ``NaN``/``NA``, and the empty string.

    Duplicated from the identical helper in ``draft_board.py`` and
    ``draft_grade.py`` rather than imported -- this codebase does not
    import private names across modules.
    """
    if isinstance(value, str):
        return value == ""
    return pd.isna(value)


def _optional_float(value: Any) -> Optional[float]:
    """``float(value)`` unless ``value`` is missing, in which case ``None``."""
    return None if _is_missing(value) else float(value)


def _population_zscores(values: list[Optional[float]]) -> list[Optional[float]]:
    """Population z-score a list, preserving position and ``None`` gaps.

    Identical convention to ``draft_board.py``'s helper of the same name:
    ``None`` entries take no part in the mean/stdev and come back as
    ``None``; returns all-``None`` when fewer than two values are usable or
    the population standard deviation is 0.
    """
    usable = [value for value in values if value is not None]
    if len(usable) < 2:
        return [None] * len(values)
    stdev = pstdev(usable)
    if stdev == 0:
        return [None] * len(values)
    mean = fmean(usable)
    return [None if value is None else (value - mean) / stdev for value in values]


def _weighted_blend(
    components: list[tuple[Optional[float], float]],
) -> Optional[float]:
    """Drop-and-renormalize weighted average of ``[(value, weight), ...]``.

    Identical convention to ``draft_board.py``'s helper of the same name.
    Returns ``None`` when no component has both a usable value and a
    strictly positive weight.
    """
    terms: list[float] = []
    used_weights: list[float] = []
    for value, weight in components:
        if value is None or weight <= 0:
            continue
        terms.append(weight * value)
        used_weights.append(weight)
    if not used_weights:
        return None
    return math.fsum(terms) / math.fsum(used_weights)


def _grade_letter(overall_z: Optional[float]) -> Optional[str]:
    """The letter grade for an ``overall_z``, or ``None`` if it is ``None``."""
    if overall_z is None:
        return None
    for threshold, letter in _GRADE_THRESHOLDS:
        if overall_z >= threshold:
            return letter
    return "F"


def _sort_key(
    row: dict[str, Any], score_key: str, tie_key: str
) -> tuple[int, float, str]:
    """Display/rank order: best score first, ``None`` last, ties by ``tie_key``."""
    score = row[score_key]
    if score is None:
        return (1, 0.0, str(row[tie_key]))
    return (0, -score, str(row[tie_key]))


def _assign_competition_ranks(
    rows: list[dict[str, Any]], score_key: str, rank_key: str
) -> None:
    """Standard competition ("1224") ranks in place, best score first.

    ``rows`` must already be sorted descending by ``score_key`` (``None``
    last). Ties are judged on the score rounded to 6 decimal places -- the
    same float-noise convention ``draft_board.py`` uses.
    """
    current_rank = 0
    previous_score: Optional[float] = None
    for position, row in enumerate(rows, start=1):
        score = row[score_key]
        if score is None:
            row[rank_key] = None
            continue
        rounded = round(score, 6)
        if rounded != previous_score:
            current_rank = position
            previous_score = rounded
        row[rank_key] = float(current_rank)


def _is_scoreable_non_excluded(pick: dict[str, Any]) -> bool:
    """True for a pick that counts toward a team's value grade.

    See the module docstring's "Metric definition -- the 'scoreable,
    non-excluded' filter" section.
    """
    return (
        pick["expected_pick_source"] != "unscored" and pick["excluded_reason"] is None
    )


def _empty_team_grades_frame() -> pd.DataFrame:
    """An empty DataFrame with :data:`TEAM_DRAFT_GRADE_COLUMNS` and their dtypes."""
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype=(
                    "int64"
                    if column in _GRADE_INT_COLUMNS
                    else "float64"
                    if column in _GRADE_FLOAT_COLUMNS
                    else object
                )
            )
            for column in TEAM_DRAFT_GRADE_COLUMNS
        }
    )


def build_team_draft_grades(
    scored_picks_df: pd.DataFrame,
    *,
    weights: DraftGradeWeights = DEFAULT_DRAFT_GRADE_WEIGHTS,
) -> pd.DataFrame:
    """Grade every team's draft on a blended, z-scored ``overall_z``.

    One row per ``(roster_id, team_name)`` present in ``scored_picks_df``,
    even a team all of whose picks are unscored or keepers (it still gets a
    row, with every value column ``NaN``/``None``). See the module
    docstring for the full metric definition, the ``overall_z`` formula,
    the grade-letter thresholds, and the standard-competition ranking
    convention.

    Args:
        scored_picks_df: A :data:`~fantasy_analyzer.players.draft_grade.
            SCORED_DRAFT_PICK_COLUMNS`-shaped frame, as produced by
            :func:`~fantasy_analyzer.players.draft_grade.score_draft_picks`,
            scoped to a single league's single draft.
        weights: The blend weights for ``overall_z``. See
            :class:`DraftGradeWeights`.

    Returns:
        A DataFrame with columns :data:`TEAM_DRAFT_GRADE_COLUMNS`, sorted by
        ascending ``draft_rank`` (unscored teams last), ties broken by
        ascending ``roster_id``. Empty (with the same columns/dtypes) if
        ``scored_picks_df`` is empty.
    """
    if scored_picks_df.empty:
        return _empty_team_grades_frame()

    teams: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    team_order: list[tuple[Any, Any]] = []
    for pick in scored_picks_df.itertuples(index=False):
        roster_id = getattr(pick, "roster_id", None)
        team_name = getattr(pick, "team_name", None)
        key = (roster_id, team_name)
        if key not in teams:
            teams[key] = []
            team_order.append(key)
        teams[key].append(
            {
                "expected_pick_source": getattr(pick, "expected_pick_source", None),
                "excluded_reason": getattr(pick, "excluded_reason", None),
                "vor": _optional_float(getattr(pick, "vor", None)),
                "pick_value": _optional_float(getattr(pick, "pick_value", None)),
                "player_name": getattr(pick, "player_name", None),
                "round": getattr(pick, "round", None),
                "pick_no": getattr(pick, "pick_no", None),
            }
        )

    team_rows: list[dict[str, Any]] = []
    for roster_id, team_name in team_order:
        picks = teams[(roster_id, team_name)]
        scoreable = [pick for pick in picks if _is_scoreable_non_excluded(pick)]

        if scoreable:
            vor_values = [pick["vor"] for pick in scoreable if pick["vor"] is not None]
            total_vor: Optional[float] = (
                math.fsum(vor_values) if vor_values else None
            )
            value_values = [
                pick["pick_value"]
                for pick in scoreable
                if pick["pick_value"] is not None
            ]
            avg_pick_value: Optional[float] = (
                fmean(value_values) if value_values else None
            )
        else:
            total_vor = None
            avg_pick_value = None

        comparable = [pick for pick in scoreable if pick["pick_value"] is not None]
        if comparable:
            best = min(
                comparable, key=lambda pick: (-pick["pick_value"], pick["pick_no"])
            )
            worst = min(
                comparable, key=lambda pick: (pick["pick_value"], pick["pick_no"])
            )
        else:
            best = None
            worst = None

        team_rows.append(
            {
                "roster_id": roster_id,
                "team_name": team_name,
                "total_vor": total_vor,
                "avg_pick_value": avg_pick_value,
                "unscored_pick_count": sum(
                    1 for pick in picks if pick["expected_pick_source"] == "unscored"
                ),
                "keeper_pick_count": sum(
                    1 for pick in picks if pick["excluded_reason"] == "keeper"
                ),
                "best_pick_player": best["player_name"] if best else None,
                "best_pick_round": _optional_float(best["round"]) if best else None,
                "best_pick_pick_no": _optional_float(best["pick_no"]) if best else None,
                "best_pick_value": best["pick_value"] if best else None,
                "worst_pick_player": worst["player_name"] if worst else None,
                "worst_pick_round": (
                    _optional_float(worst["round"]) if worst else None
                ),
                "worst_pick_pick_no": (
                    _optional_float(worst["pick_no"]) if worst else None
                ),
                "worst_pick_value": worst["pick_value"] if worst else None,
            }
        )

    total_vor_z_list = _population_zscores([row["total_vor"] for row in team_rows])
    avg_pick_value_z_list = _population_zscores(
        [row["avg_pick_value"] for row in team_rows]
    )
    for row, total_vor_z, avg_pick_value_z in zip(
        team_rows, total_vor_z_list, avg_pick_value_z_list
    ):
        row["total_vor_z"] = total_vor_z
        row["avg_pick_value_z"] = avg_pick_value_z
        overall_z = _weighted_blend(
            [(total_vor_z, weights.vor), (avg_pick_value_z, weights.value)]
        )
        row["overall_z"] = overall_z
        row["grade_letter"] = _grade_letter(overall_z)

    team_rows.sort(key=lambda row: _sort_key(row, "overall_z", "roster_id"))
    _assign_competition_ranks(team_rows, "overall_z", "draft_rank")

    result = pd.DataFrame(team_rows, columns=TEAM_DRAFT_GRADE_COLUMNS)
    for column in _GRADE_INT_COLUMNS:
        result[column] = result[column].astype(int)
    for column in _GRADE_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    for column in _GRADE_LABEL_COLUMNS:
        result[column] = pd.Series(
            [
                None if _is_missing(value) else value
                for value in result[column].tolist()
            ],
            dtype=object,
        )
    return result[TEAM_DRAFT_GRADE_COLUMNS]


def _empty_talking_points_frame() -> pd.DataFrame:
    """An empty DataFrame with :data:`DRAFT_TALKING_POINT_COLUMNS` and their dtypes."""
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype=(
                    "int64"
                    if column in _TALKING_POINT_INT_COLUMNS
                    else "float64"
                    if column in _TALKING_POINT_FLOAT_COLUMNS
                    else object
                )
            )
            for column in DRAFT_TALKING_POINT_COLUMNS
        }
    )


def build_draft_talking_points(
    team_grades_df: pd.DataFrame, scored_picks_df: pd.DataFrame
) -> pd.DataFrame:
    """Structured, hand-checkable facts about each team's draft.

    One row per team in ``team_grades_df``. Every field is a plain fact
    (number, rank, name, or a small JSON-able dict) -- no prose is
    generated. See the module docstring's "Talking points" section for the
    ``most_drafted_position`` tie-break rule and the ``reach_count``/
    ``value_count`` threshold definition.

    Args:
        team_grades_df: FFA-079's own output --
            :data:`TEAM_DRAFT_GRADE_COLUMNS`-shaped, as produced by
            :func:`build_team_draft_grades`.
        scored_picks_df: The same :data:`~fantasy_analyzer.players.
            draft_grade.SCORED_DRAFT_PICK_COLUMNS`-shaped frame
            ``team_grades_df`` was built from, read here for
            ``roster_id``/``position``/``expected_pick_source``/
            ``excluded_reason``/``pick_value``.

    Returns:
        A DataFrame with columns :data:`DRAFT_TALKING_POINT_COLUMNS`, one
        row per row of ``team_grades_df``, in the same order. Empty (with
        the same columns) if ``team_grades_df`` is empty.
    """
    if team_grades_df.empty:
        return _empty_talking_points_frame()

    num_teams = len(team_grades_df)

    rows: list[dict[str, Any]] = []
    for grade in team_grades_df.itertuples(index=False):
        rows.append(
            {
                "roster_id": grade.roster_id,
                "team_name": grade.team_name,
                "grade_letter": grade.grade_letter,
                "draft_rank": _optional_float(grade.draft_rank),
                "num_teams": num_teams,
                "total_vor": _optional_float(grade.total_vor),
                "avg_pick_value": _optional_float(grade.avg_pick_value),
                "best_pick_player": grade.best_pick_player,
                "best_pick_round": _optional_float(grade.best_pick_round),
                "best_pick_value": _optional_float(grade.best_pick_value),
                "worst_pick_player": grade.worst_pick_player,
                "worst_pick_round": _optional_float(grade.worst_pick_round),
                "worst_pick_value": _optional_float(grade.worst_pick_value),
                "unscored_pick_count": int(grade.unscored_pick_count),
            }
        )

    # total_vor_rank / avg_pick_value_rank: computed fresh here (FFA-079
    # only ranks on the blended overall_z), standard competition ranking,
    # descending, NaN sorts last. Sorting builds new lists of the *same*
    # dict objects, so mutating in place via _assign_competition_ranks
    # writes the rank straight onto each team's row.
    by_total_vor = sorted(
        rows, key=lambda row: _sort_key(row, "total_vor", "roster_id")
    )
    _assign_competition_ranks(by_total_vor, "total_vor", "total_vor_rank")
    by_avg_pick_value = sorted(
        rows, key=lambda row: _sort_key(row, "avg_pick_value", "roster_id")
    )
    _assign_competition_ranks(
        by_avg_pick_value, "avg_pick_value", "avg_pick_value_rank"
    )

    picks_by_roster: dict[Any, list[Any]] = {}
    for pick in scored_picks_df.itertuples(index=False):
        picks_by_roster.setdefault(getattr(pick, "roster_id", None), []).append(pick)

    threshold = num_teams
    for row in rows:
        picks = picks_by_roster.get(row["roster_id"], [])

        position_counts: dict[str, int] = {}
        for pick in picks:
            position = getattr(pick, "position", None)
            key = "UNKNOWN" if _is_missing(position) else str(position)
            position_counts[key] = position_counts.get(key, 0) + 1

        if position_counts:
            max_count = max(position_counts.values())
            most_drafted_position = min(
                position
                for position, count in position_counts.items()
                if count == max_count
            )
        else:
            most_drafted_position = None

        reach_count = 0
        value_count = 0
        for pick in picks:
            source = getattr(pick, "expected_pick_source", None)
            excluded = getattr(pick, "excluded_reason", None)
            if source == "unscored" or excluded is not None:
                continue
            pick_value = _optional_float(getattr(pick, "pick_value", None))
            if pick_value is None:
                continue
            if pick_value < -threshold:
                reach_count += 1
            elif pick_value > threshold:
                value_count += 1

        row["most_drafted_position"] = most_drafted_position
        row["position_counts"] = position_counts
        row["reach_count"] = reach_count
        row["value_count"] = value_count

    result = pd.DataFrame(rows, columns=DRAFT_TALKING_POINT_COLUMNS)
    for column in _TALKING_POINT_INT_COLUMNS:
        result[column] = result[column].astype(int)
    for column in _TALKING_POINT_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    for column in _TALKING_POINT_LABEL_COLUMNS:
        result[column] = pd.Series(
            [
                None if _is_missing(value) else value
                for value in result[column].tolist()
            ],
            dtype=object,
        )
    return result[DRAFT_TALKING_POINT_COLUMNS]
