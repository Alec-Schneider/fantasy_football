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

Metric definition -- ``expected_pick`` (informational) and ``pick_value``
--------------------------------------------------------------------------

``expected_pick`` is the board's own prediction of where the drafted player
"should" have gone, using the same reasoning ``draft_board.py``'s own
``adp_delta`` documentation gives for preferring a like-for-like population:
prefer ``board.adp_pool_rank`` (the player's rank within the narrower
ADP-having pool) when it is defined, and fall back to ``board.draft_rank``
(the full-board rank) only when the player has no ADP at all.
``expected_pick_source`` records which one was used -- ``"adp_pool_rank"``,
``"draft_rank"``, or ``"unscored"`` when neither is available (no board
match, or matched but both ranks are ``NaN``). This pair is carried through
unchanged from the original design and is still useful, human-readable
context ("the board had him around pick 23; he actually went pick 45") --
but as of this revision it no longer drives ``pick_value`` (see below).

**``pick_value`` is a value-scale quantity, not a rank-scale one.** An
earlier version of this module computed ``pick_value = expected_pick -
pick_no`` -- a straight subtraction of two pick *positions*. That has two
compounding problems, one of them a plain sign bug:

1. **Wrong sign.** ``expected_pick - pick_no`` is *positive* when
   ``pick_no < expected_pick`` -- i.e. the player was actually taken
   *earlier* (a lower pick number) than his predicted slot. That is a
   reach by definition, yet the old code (and its own docstring/tests)
   labeled positive values "steal." A player predicted to go around pick 3
   who instead falls to pick 15 -- the canonical steal -- produced
   ``3 - 15 = -12``, a *negative* number, under the old formula. This was
   backwards for every pick, in both directions, for as long as the module
   existed; see the toy example below, which replaces the old (incorrectly
   labeled) one.
2. **Wrong scale.** Even with the sign corrected, diffing raw pick
   *positions* commits exactly the error ``draft_board.py``'s own module
   docstring calls out and works around for ``adp``/``ecr``: "rank is an
   *ordinal* scale ... the gap between rank 1 and rank 2 is enormous in
   true fantasy value; the gap between rank 150 and rank 151 is
   negligible." A 20-pick swing among the flat, bunched-together
   replacement-level talent of round 15 is not remotely the same real
   event as a 20-pick swing in round 2, but a raw rank diff scores them
   identically -- which is exactly why late-round "reaches"/"steals"
   dominated ``avg_pick_value`` and made the grades feel like they valued
   the end of the draft far too much.

The fix reuses the board's own value scale (``draft_score``, already
log-shaped via ``draft_board.py``'s ``-ln(rank)`` transform) instead of
inventing a second curve:

    ``expected_value_at_pick = value_curve(pick_no)``
    ``pick_value = draft_score(player taken) - expected_value_at_pick``

where ``value_curve`` is built once per call from every ``(draft_rank,
draft_score)`` pair present in ``board_df`` (sorted ascending by
``draft_rank``, duplicate ranks -- which only occur among tied players who
share an identical ``draft_score`` by construction -- collapsed to one
point) and queried by linear interpolation between the two bracketing
ranks, clamped to the first/last point outside the observed range. Always
the **full-board** (``draft_rank``) population, never the narrower
ADP-only pool: ``pick_no`` is a real, physical draft-pick number spanning
every pick in the actual draft (some of whom may have no ADP at all), so it
lives on the same numeric scale as ``draft_rank``, not the ~233-player ADP
pool -- an entirely different question from which population best predicts
*a specific player's* expected slot (``expected_pick``'s job, unchanged
above). ``value_curve`` is looked up by ``pick_no``, not by
``expected_pick`` -- this module no longer diffs two pick positions at
all.

Sign convention: **positive** means the drafted player's own value
(``draft_score``) exceeds what the board typically expects from whoever
goes at that exact pick slot -- a bargain, a steal. **Negative** means the
player taken was worth less than the slot's going rate -- a reach.
``expected_value_at_pick`` is reported alongside ``pick_value`` (the same
audit-trail convention ``draft_board.py`` uses for ``adp_pool_rank``
alongside ``adp_delta``) so this computation never needs to be re-derived
to be checked by hand. ``pick_value`` is ``NaN`` whenever
``expected_pick_source == "unscored"`` (the player itself has no usable
``draft_score``), ``pick_no`` is missing, or ``board_df`` has no usable
``(draft_rank, draft_score)`` pairs at all (an empty/degenerate curve).

Worked toy example (hand-checked in tests) -- a five-point value curve,
linear for hand-checkability (``draft_score`` need not be linear in rank in
real boards; this module makes no assumption about its shape beyond
"whatever the board computed"), rank 1..5 -> ``draft_score``
3.0, 2.0, 1.0, 0.0, -1.0::

    Pick 3 actually used on a player whose own draft_score is 1.5:
        expected_value_at_pick = value_curve(3) = 1.0   (exact rank match)
        pick_value = 1.5 - 1.0 = +0.5                    (steal)

    Pick 2 actually used on a player whose own draft_score is 0.0:
        expected_value_at_pick = value_curve(2) = 2.0
        pick_value = 0.0 - 2.0 = -2.0                    (reach)

    Pick 2 on the curve above, but with ranks 1 and 3 the only ones
    present (rank 2 was skipped by a tie at rank 1 -- competition ranking
    never assigns it to anyone): value_curve(2) interpolates halfway
    between rank 1's 3.0 and rank 3's 1.0 -> 2.0, unchanged from the exact
    case above. Interpolation across a rank gap left by a tie is a
    deliberate, expected part of this design, not an edge case to special
    -case.

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
Ties *within the value curve itself* (two players sharing a ``draft_rank``,
hence an identical ``draft_score``) collapse to one curve point, per the
value-curve description above -- not a per-pick concern, a one-time step in
building the shared curve.

Missing values
--------------------------------------------------------------------------

- **A pick whose player has no row in ``board_df`` at all** (left-join
  miss): ``expected_pick = NaN``, ``expected_pick_source = "unscored"``,
  ``pick_value = NaN``, ``vor``/``tier``/``draft_score``/``position_rank``
  all ``NaN``. The pick is **not** dropped from the output.
  ``expected_value_at_pick`` is a partial exception: it depends only on
  ``pick_no`` and the shared value curve, not on this pick's own player,
  so it is still populated (a real, defined "what a pick at this slot is
  typically worth" figure) even though nothing is known about who was
  actually taken -- only ``pick_value`` (which also needs this player's
  own ``draft_score``) collapses to ``NaN``.
- **A pick whose player matches a board row, but both ``adp_pool_rank`` and
  ``draft_rank`` are ``NaN`` on that row** (the board itself could not
  score the player -- e.g. no ADP and no ECR): identical to the no-match
  case above, ``expected_pick_source = "unscored"``, and (since a player
  with no ``draft_rank`` also has no ``draft_score`` in every real board)
  ``pick_value = NaN`` too, while ``expected_value_at_pick`` is still
  populated for the same reason.
- **``board_df`` has no usable ``(draft_rank, draft_score)`` pairs at all**
  (an empty or fully-degenerate board): the value curve is empty, so
  ``expected_value_at_pick`` and ``pick_value`` are ``NaN`` for every pick,
  even one whose own player is otherwise fully scored. This is a distinct
  failure mode from "this player is unscored" -- ``expected_pick_source``
  is computed independently and is unaffected -- and is unreachable against
  a real :func:`~fantasy_analyzer.players.draft_board.build_draft_board`
  output with at least one scored player, only reachable from a degenerate
  hand-built test frame.
- **``pick_no`` is missing on the pick itself**: ``expected_value_at_pick``
  and ``pick_value`` are both ``NaN`` -- there is no pick number to look up
  on the curve. (``expected_pick``/``expected_pick_source`` are unaffected,
  since they describe the *player*, not the pick number.)
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
``None``/``True``/``False`` convention). The seven new numeric columns
(``expected_pick``, ``expected_value_at_pick``, ``pick_value``, ``vor``,
``tier``, ``draft_score``, ``position_rank``) are ``float64``, so an
undefined value is ``NaN``. ``expected_pick_source`` and
``excluded_reason`` are ``object`` (``str`` or ``None``).
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
    "expected_value_at_pick",
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
    "expected_value_at_pick",
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


def _build_value_curve(board_df: pd.DataFrame) -> list[tuple[float, float]]:
    """Sorted, deduplicated ``(draft_rank, draft_score)`` points from ``board_df``.

    See the module docstring's "``pick_value`` is a value-scale quantity"
    section. Always built from ``draft_rank`` (the full-board population,
    the same numeric scale as a real ``pick_no``), never
    ``adp_pool_rank``. Rows missing either ``draft_rank`` or
    ``draft_score`` are skipped -- they cannot contribute a curve point.
    Duplicate ranks (tied players) collapse to a single point; this is
    always safe because standard competition ranking only ties players who
    already share an identical (rounded) ``draft_score``, so no averaging
    or precedence rule is needed. Returns ``[]`` for an empty/degenerate
    ``board_df``.
    """
    points: dict[float, float] = {}
    if board_df is None or board_df.empty:
        return []
    for row in board_df.itertuples(index=False):
        rank = _optional_float(getattr(row, "draft_rank", None))
        score = _optional_float(getattr(row, "draft_score", None))
        if rank is None or score is None:
            continue
        points[rank] = score
    return sorted(points.items())


def _interpolate_curve(
    curve: list[tuple[float, float]], x: float
) -> Optional[float]:
    """Linear interpolation of ``curve`` (sorted ``(rank, value)`` pairs) at ``x``.

    Clamped to the first/last point's value outside the observed range
    (the same clamp-to-worst convention ``player_value.py``'s replacement
    rank uses). Returns ``None`` for an empty curve.
    """
    if not curve:
        return None
    if x <= curve[0][0]:
        return curve[0][1]
    if x >= curve[-1][0]:
        return curve[-1][1]
    for (rank_lo, value_lo), (rank_hi, value_hi) in zip(curve, curve[1:]):
        if rank_lo <= x <= rank_hi:
            if rank_hi == rank_lo:
                return value_lo
            fraction = (x - rank_lo) / (rank_hi - rank_lo)
            return value_lo + fraction * (value_hi - value_lo)
    return curve[-1][1]


def score_draft_picks(picks_df: pd.DataFrame, board_df: pd.DataFrame) -> pd.DataFrame:
    """Grade every normalized draft pick against a draft board's expectations.

    Left-joins ``picks_df`` onto ``board_df`` on ``sleeper_player_id``: every
    row of ``picks_df`` produces exactly one output row (a pick with no
    board match is not dropped, just marked unscored). See the module
    docstring for the ``expected_pick``/``expected_value_at_pick``/
    ``pick_value`` formulas, the keeper exclusion, and every missing-value
    case.

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
    value_curve = _build_value_curve(board_df)

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

        vor = board_row["vor"] if board_row else None
        tier = board_row["tier"] if board_row else None
        draft_score = board_row["draft_score"] if board_row else None
        position_rank = board_row["position_rank"] if board_row else None

        pick_no = pick_dict.get("pick_no")
        expected_value_at_pick = (
            None
            if _is_missing(pick_no)
            else _interpolate_curve(value_curve, float(pick_no))
        )
        pick_value = (
            None
            if draft_score is None or expected_value_at_pick is None
            else draft_score - expected_value_at_pick
        )

        excluded_reason: Optional[str] = None
        if pick_dict.get("is_keeper") is True:
            pick_value = None
            vor = None
            excluded_reason = "keeper"

        pick_dict.update(
            {
                "expected_pick": expected_pick,
                "expected_pick_source": expected_pick_source,
                "expected_value_at_pick": expected_value_at_pick,
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
