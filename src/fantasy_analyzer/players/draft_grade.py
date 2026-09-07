"""Pick-level draft value grading (FFA-078).

This module answers, for a single normalized draft pick, "was this a good
pick relative to what the market/board expected?" It joins FFA-077's
normalized draft picks
(:func:`fantasy_analyzer.league.draft.build_normalized_draft_picks`,
``NORMALIZED_DRAFT_PICK_COLUMNS``) onto a :func:`~fantasy_analyzer.players.
draft_board.build_draft_board` output (``DRAFT_BOARD_COLUMNS``) and computes
one number per pick: how many spots earlier or later than expected that
player was actually taken. It performs no network access and recomputes
nothing the board already computed -- ``vor``, ``tier``, ``draft_score``,
``position_rank`` and the two rank columns used for ``expected_pick`` are
all read verbatim from ``board_df``.

Metric definition -- ``expected_pick`` and ``pick_value``
--------------------------------------------------------------------------

For each pick, ``expected_pick`` is the board's own prediction of where this
player "should" have gone, using the same reasoning
``draft_board.py``'s own ``adp_delta`` documentation gives for preferring a
like-for-like population: prefer ``board.adp_pool_rank`` (the player's rank
within the narrower ADP-having pool) when it is defined, and fall back to
``board.draft_rank`` (the full-board rank) only when the player has no ADP
at all. ``expected_pick_source`` records which one was used --
``"adp_pool_rank"``, ``"draft_rank"``, or ``"unscored"`` when neither is
available (no board match, or matched but both ranks are ``NaN``).

    ``pick_value = expected_pick - pick_no``

Same sign convention as ``draft_board.py``'s ``adp_delta``: **positive**
means the player was taken *later* than expected (a bargain -- a steal, you
got him after the board said he'd typically be gone); **negative** means he
was taken *earlier* than expected (a reach). ``pick_value`` is ``NaN``
whenever ``expected_pick`` is ``NaN`` (``expected_pick_source ==
"unscored"``).

Worked toy example (hand-checked in tests)::

    pick_no=24, adp_pool_rank=10 -> expected_pick=10
        pick_value = 10 - 24 = -14   (reach: taken 14 spots early)

    pick_no=24, adp_pool_rank=40 -> expected_pick=40
        pick_value = 40 - 24 = +16   (steal: taken 16 spots late)

Keeper handling
--------------------------------------------------------------------------

A keeper's "cost" (its draft slot) is not a real market signal for that
season -- the player was not actually available to be drafted at market
value, so counting a keeper's ``pick_value``/``vor`` toward a manager's
draft grade would reward or punish a decision that was not really made this
year. For every pick where ``is_keeper is True`` (exactly ``True``, not a
missing/``None`` flag -- see "Missing values" below), this module forces
``pick_value = NaN`` and ``vor = NaN`` regardless of what the board join
produced, and sets ``excluded_reason = "keeper"``. The row itself is **not**
dropped -- it stays visible in the per-pick output, including its
(otherwise-computed) ``expected_pick``/``expected_pick_source``, so a reader
can still see what the player would have graded as. For every non-keeper
pick, ``excluded_reason`` is ``None``.

``excluded_reason`` and ``expected_pick_source`` are two independent flags
with different purposes: a pick can be ``expected_pick_source ==
"unscored"`` (the board could not score this player at all) while also
being a keeper, in which case both apply independently and
``excluded_reason`` is still set to ``"keeper"`` (though ``pick_value`` was
already ``NaN`` from being unscored). FFA-079 (``draft_report.py``) is the
consumer of this distinction: it filters on ``expected_pick_source !=
"unscored"`` for "was this pick scoreable at all" and independently on
``excluded_reason is None`` for "should this scoreable pick count toward a
team's grade." ``excluded_reason`` is designed to be extensible -- ``keeper``
is the only reason this ticket defines, but the column exists so a future
reason (e.g. a supplemental/rookie-only pick) can be added without a schema
change.

Ties
--------------------------------------------------------------------------

There is no ranking or competition-rank logic at this pick level -- every
pick's ``pick_value`` is computed independently of every other pick's, so
two picks landing on the identical ``pick_value`` require no special
handling here. (Ranking teams by their aggregate value, where a tie *does*
need a tie-break rule, is FFA-079's concern -- see ``draft_report.py``.)

Missing values
--------------------------------------------------------------------------

- **A pick whose player has no row in ``board_df`` at all** (left-join
  miss): ``expected_pick = NaN``, ``expected_pick_source = "unscored"``,
  ``pick_value = NaN``, ``vor``/``tier``/``draft_score``/``position_rank``
  all ``NaN``. The pick is **not** dropped from the output.
- **A pick whose player matches a board row, but both ``adp_pool_rank`` and
  ``draft_rank`` are ``NaN`` on that row** (the board itself could not
  score the player -- e.g. no ADP and no ECR): identical to the no-match
  case above, ``expected_pick_source = "unscored"``.
- **``is_keeper`` is ``None`` (unknown/non-keeper-league picks) or
  ``False``**: treated as a normal, non-excluded pick -- only an *exact*
  ``True`` triggers the keeper exclusion, so a caller who never populates
  ``is_keeper`` (a non-keeper league) never accidentally excludes anything.
- **``sleeper_player_id`` is ``None`` on the pick** (an empty/forfeited
  draft slot, if Sleeper ever emits one): cannot match any board row, so it
  is treated as unscored, exactly like a genuine no-match.

Regular season vs. playoffs
--------------------------------------------------------------------------

Not applicable. This is a draft-time metric computed once per draft, before
any games are played -- there is no regular-season/playoff distinction to
make, and this module never looks at weekly data.

Column dtypes
--------------------------------------------------------------------------

Every column inherited from ``NORMALIZED_DRAFT_PICK_COLUMNS`` is carried
through from ``picks_df`` unchanged (this module neither reads nor casts
its dtype -- see FFA-077 for that contract, including ``is_keeper``'s
``None``/``True``/``False`` convention). The six new numeric columns
(``expected_pick``, ``pick_value``, ``vor``, ``tier``, ``draft_score``,
``position_rank``) are ``float64``, so an undefined value is ``NaN``.
``expected_pick_source`` and ``excluded_reason`` are ``object`` (``str`` or
``None``).
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from fantasy_analyzer.league.draft import NORMALIZED_DRAFT_PICK_COLUMNS

#: Column order for the DataFrame returned by :func:`score_draft_picks`:
#: every ``NORMALIZED_DRAFT_PICK_COLUMNS`` field, then the board-derived
#: value-grading columns in the order they are computed.
SCORED_DRAFT_PICK_COLUMNS = NORMALIZED_DRAFT_PICK_COLUMNS + [
    "expected_pick",
    "expected_pick_source",
    "pick_value",
    "vor",
    "tier",
    "draft_score",
    "position_rank",
    "excluded_reason",
]

#: New columns this module adds that are always ``float64`` -- see the
#: module docstring's "Column dtypes".
_NEW_FLOAT_COLUMNS = [
    "expected_pick",
    "pick_value",
    "vor",
    "tier",
    "draft_score",
    "position_rank",
]

#: New columns this module adds that are always ``object`` (``str`` or
#: ``None``).
_NEW_OBJECT_COLUMNS = ["expected_pick_source", "excluded_reason"]

#: The board columns this module reads for one player, keyed by
#: ``sleeper_player_id``. Read-only lookup -- never recomputed.
_BOARD_LOOKUP_FIELDS = [
    "adp_pool_rank",
    "draft_rank",
    "vor",
    "tier",
    "draft_score",
    "position_rank",
]


def _is_missing(value: Any) -> bool:
    """True for ``None``, ``NaN``/``NA``, and the empty string.

    Duplicated from the identical helper in ``draft_board.py`` and
    ``player_rankings.py`` rather than imported -- this codebase does not
    import private names across modules.
    """
    if isinstance(value, str):
        return value == ""
    return pd.isna(value)


def _optional_float(value: Any) -> Optional[float]:
    """``float(value)`` unless ``value`` is missing, in which case ``None``."""
    return None if _is_missing(value) else float(value)


def _empty_result(picks_df: pd.DataFrame) -> pd.DataFrame:
    """A copy of ``picks_df`` (which has zero rows) with the new columns added.

    Preserves whatever dtype ``picks_df`` already carries for the
    ``NORMALIZED_DRAFT_PICK_COLUMNS`` fields (this module does not own that
    contract), and adds the new columns with the documented empty dtypes so
    downstream concatenation never upcasts unexpectedly.
    """
    result = picks_df.copy()
    for column in NORMALIZED_DRAFT_PICK_COLUMNS:
        if column not in result.columns:
            result[column] = pd.Series(dtype=object)
    for column in _NEW_FLOAT_COLUMNS:
        result[column] = pd.Series(dtype="float64")
    for column in _NEW_OBJECT_COLUMNS:
        result[column] = pd.Series(dtype=object)
    return result[SCORED_DRAFT_PICK_COLUMNS]


def _board_lookup(board_df: pd.DataFrame) -> dict[str, dict[str, Optional[float]]]:
    """``sleeper_player_id`` -> the board columns this module reads.

    ``None``/empty ``board_df`` yields an empty lookup (every pick is
    treated as unmatched -- the left-join-miss case in the module
    docstring). A row missing ``sleeper_player_id`` is skipped (cannot be
    looked up by any pick). A duplicate ``sleeper_player_id`` in
    ``board_df`` is not expected from a real :func:`build_draft_board`
    output (which raises on duplicates itself); the last row wins here
    rather than raising, since this module's job is to read the board, not
    re-validate it.
    """
    lookup: dict[str, dict[str, Optional[float]]] = {}
    if board_df is None or board_df.empty:
        return lookup
    for row in board_df.itertuples(index=False):
        player_id = getattr(row, "sleeper_player_id", None)
        if _is_missing(player_id):
            continue
        lookup[str(player_id)] = {
            field: _optional_float(getattr(row, field, None))
            for field in _BOARD_LOOKUP_FIELDS
        }
    return lookup


def score_draft_picks(picks_df: pd.DataFrame, board_df: pd.DataFrame) -> pd.DataFrame:
    """Grade every normalized draft pick against a draft board's expectations.

    Left-joins ``picks_df`` onto ``board_df`` on ``sleeper_player_id``: every
    row of ``picks_df`` produces exactly one output row (a pick with no
    board match is not dropped, just marked unscored). See the module
    docstring for the ``expected_pick``/``pick_value`` formulas, the keeper
    exclusion, and every missing-value case.

    Args:
        picks_df: A :data:`~fantasy_analyzer.league.draft.
            NORMALIZED_DRAFT_PICK_COLUMNS`-shaped frame, as produced by
            :func:`fantasy_analyzer.league.draft.build_normalized_draft_picks`.
        board_df: A :data:`~fantasy_analyzer.players.draft_board.
            DRAFT_BOARD_COLUMNS`-shaped frame, as produced by
            :func:`~fantasy_analyzer.players.draft_board.build_draft_board`.
            Read for ``sleeper_player_id``, ``adp_pool_rank``,
            ``draft_rank``, ``vor``, ``tier``, ``draft_score``, and
            ``position_rank``; not otherwise validated or recomputed.

    Returns:
        A DataFrame with columns :data:`SCORED_DRAFT_PICK_COLUMNS`, one row
        per row of ``picks_df``, in the same order. Empty (with the same
        columns) if ``picks_df`` is empty.
    """
    if picks_df.empty:
        return _empty_result(picks_df)

    board_lookup = _board_lookup(board_df)

    rows: list[dict[str, Any]] = []
    for pick in picks_df.itertuples(index=False):
        pick_dict = {
            column: getattr(pick, column) for column in NORMALIZED_DRAFT_PICK_COLUMNS
        }

        player_id = pick_dict["sleeper_player_id"]
        board_row = None if _is_missing(player_id) else board_lookup.get(str(player_id))

        adp_pool_rank = board_row["adp_pool_rank"] if board_row else None
        draft_rank = board_row["draft_rank"] if board_row else None

        if adp_pool_rank is not None:
            expected_pick: Optional[float] = adp_pool_rank
            expected_pick_source = "adp_pool_rank"
        elif draft_rank is not None:
            expected_pick = draft_rank
            expected_pick_source = "draft_rank"
        else:
            expected_pick = None
            expected_pick_source = "unscored"

        pick_no = pick_dict.get("pick_no")
        pick_value = (
            None
            if expected_pick is None or _is_missing(pick_no)
            else expected_pick - float(pick_no)
        )

        vor = board_row["vor"] if board_row else None
        tier = board_row["tier"] if board_row else None
        draft_score = board_row["draft_score"] if board_row else None
        position_rank = board_row["position_rank"] if board_row else None

        excluded_reason: Optional[str] = None
        if pick_dict.get("is_keeper") is True:
            pick_value = None
            vor = None
            excluded_reason = "keeper"

        pick_dict.update(
            {
                "expected_pick": expected_pick,
                "expected_pick_source": expected_pick_source,
                "pick_value": pick_value,
                "vor": vor,
                "tier": tier,
                "draft_score": draft_score,
                "position_rank": position_rank,
                "excluded_reason": excluded_reason,
            }
        )
        rows.append(pick_dict)

    result = pd.DataFrame(rows, columns=SCORED_DRAFT_PICK_COLUMNS)
    for column in _NEW_FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    for column in _NEW_OBJECT_COLUMNS:
        result[column] = pd.Series(
            [
                None if _is_missing(value) else value
                for value in result[column].tolist()
            ],
            dtype=object,
        )
    return result[SCORED_DRAFT_PICK_COLUMNS]
