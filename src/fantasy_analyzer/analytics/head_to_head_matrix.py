"""Reshape head-to-head records into a manager-by-manager matrix (FFA-041).

Consumes FFA-040's
:func:`~fantasy_analyzer.analytics.head_to_head.build_head_to_head_records`
output and pivots it into the grid AGENTS.md describes::

            Alec   Mike   Joe
    Alec      —     3-2   2-0
    Mike     2-3     —    1-2
    Joe      0-2    2-1    —

This module performs no network access and defines **no new metrics**. Every
win/loss/tie count in a cell is copied verbatim from the head-to-head record
row for that ordered pair -- this is a pure reshaping/rendering layer. All of
FFA-040's documented rules (bye rows excluded, a missing-points meeting
counted as a meeting but not as a win/loss/tie, unmapped owner -> ``None``)
are inherited unchanged; see
:mod:`fantasy_analyzer.analytics.head_to_head` for those definitions.

Input
-----

:func:`build_head_to_head_matrix` takes the already-built
``head_to_head_df`` as its **sole** input rather than re-deriving records
from ``season_matchup_df``/``teams_df``. FFA-040 already owns the
"aggregate meetings into records" question, including all of its edge-case
rules; recomputing them here would duplicate that logic and risk the two
implementations drifting. This ticket is only about reshaping.

The consequence is that this module's output is only as complete as its
input: a pair of rosters that FFA-040 emitted no row for is treated as
"never met" (see "Pairs that never met" below), and a roster with no rows at
all is simply absent from the matrix.

Two representations: raw cells and formatted strings
-----------------------------------------------------

A DataFrame whose cells are formatted strings like ``"3-2"`` is what a human
wants to read, but it throws away the underlying counts -- a caller wanting
"how many times did A beat B" would have to parse the string back apart.
Conversely a matrix of raw counts is awkward to print. Rather than pick one,
this module provides both, with the raw form as the primitive:

- :func:`build_head_to_head_matrix` returns the **programmatic** matrix:
  an ``object``-dtype DataFrame whose cells are :class:`HeadToHeadCell`
  instances (or ``None`` on the diagonal), indexed by ``roster_id`` on both
  axes.
- :func:`format_head_to_head_matrix` returns the **display** matrix: the
  same grid rendered as strings, with owner display names on both axes.

The tradeoff is that the display matrix is lossy by construction and is not
meant to be parsed; anything programmatic should read the raw matrix. The
display matrix is also not round-trippable back into counts, and its axis
labels are not guaranteed unique (see "Axis labels" below).

Axis labels and roster-id traceability
----------------------------------------

The raw matrix is indexed by ``roster_id`` on both axes (``index.name =
"roster_id"``, ``columns.name = "opponent_roster_id"``), never by owner
name. ``roster_id`` is the immutable key per AGENTS.md's data-modeling
guidelines, so the raw matrix stays joinable and lookup-safe.

The display matrix substitutes owner labels, taken from the ``owner`` /
``opponent_owner`` columns of the input (which FFA-040 resolved from
``teams_df["display_name"]``). A roster whose owner is unresolved
(``None``/``NaN``, e.g. an orphaned roster or an empty ``teams_df``) is
labeled ``"Roster {roster_id}"`` rather than ``"None"``, so the axis is
still readable and still traceable back to the roster.

Display names are labels, not keys, and nothing in Sleeper prevents two
managers from sharing one. Two rosters with the same ``display_name``
therefore produce **duplicate axis labels** in the display matrix, which
makes ``.loc[label]`` on it return multiple rows. This module deliberately
does not de-duplicate or mangle the labels (neither ``teams.py`` nor
``head_to_head.py`` does anything about name collisions today, and inventing
a disambiguation scheme here would be inconsistent with them). Callers that
need unambiguous lookup should use the raw matrix, which is keyed by
``roster_id`` and cannot collide.

Universe of managers
--------------------

Both axes are the sorted union of the ``roster_id`` and
``opponent_roster_id`` values present in the input.

For FFA-040's unfiltered output the union is redundant: that function emits
mirrored rows for every meeting, so every roster appearing as an
``opponent_roster_id`` necessarily also appears as a ``roster_id``. There is
no "winner-only"/"loser-only" roster to rescue. The union is used anyway
because it is correct for a hand-filtered input too (e.g. a caller who
sliced the records down to one manager's rows still gets that manager's
opponents on both axes).

A roster that never met anyone at all (e.g. a roster whose every week was a
bye) has no head-to-head row and so does not appear in the matrix. Adding
the full league roster universe from ``teams_df`` is out of scope here.

Diagonal
--------

A manager's record against themselves is meaningless. In the raw matrix the
diagonal cell is ``None`` (not a zeroed :class:`HeadToHeadCell`, so it is
distinguishable from a pair that genuinely never met); in the display matrix
it is :data:`HEAD_TO_HEAD_MATRIX_DIAGONAL`.

Pairs that never met
--------------------

Two rosters that both appear in the matrix but have no head-to-head row for
their ordered pair (e.g. a 4-roster input where rosters 2 and 4 never
played) get an explicit zeroed :class:`HeadToHeadCell` -- ``meetings = wins
= losses = ties = 0`` -- rather than ``None``. Reading
``cell.meetings == 0`` is then a well-defined check that never has to
guard against ``None``, and the ``None`` sentinel is reserved exclusively
for the diagonal. In the display matrix such a cell renders as
:data:`HEAD_TO_HEAD_MATRIX_NO_MEETING` (the empty string) so that a
never-played pair reads as blank rather than as a misleading ``"0-0"``.

Note that FFA-040 never emits a ``meetings = 0`` row; these zero cells are
materialized here, by this module, purely to fill the grid.

Record formatting and ties
---------------------------

A cell with no ties renders as ``"W-L"`` (matching AGENTS.md's example
output); a cell with at least one tie renders as ``"W-L-T"``. The rule is
per-cell, so a league with sporadic ties will show mixed widths in one grid
(e.g. ``"3-2"`` next to ``"1-1-1"``). That is the accepted tradeoff for
keeping each cell's rendering a function of that cell alone and never
silently dropping a tie. Tie counts are always present in the raw matrix
regardless of how the display matrix renders them.

A meeting with an unresolved outcome (FFA-040's missing-points rule) is
counted in ``meetings`` but in none of ``wins``/``losses``/``ties``, so
``wins + losses + ties`` can be less than ``meetings``. The displayed
``W-L``/``W-L-T`` record therefore does not necessarily account for every
meeting; ``meetings`` is carried on the raw cell for callers who need it.

Regular season vs. playoffs
-----------------------------

This module inherits FFA-040's scope exactly: its input already combines
regular-season and playoff meetings into a single record, so the matrix is
a **combined** all-games matrix and makes no ``is_playoff`` distinction of
its own. It deliberately does not re-introduce a phase filter -- splitting
head-to-head results by season phase is FFA-044's job. A caller who wants a
phase-specific matrix today should filter ``season_matchup_df`` before
calling ``build_head_to_head_records`` and pass the result here.

Missing values / edge cases
----------------------------

- **Empty ``head_to_head_df``**: both functions return an empty DataFrame
  with no rows and no columns (there is no roster universe to build axes
  from).
- **Diagonal**: ``None`` (raw) / :data:`HEAD_TO_HEAD_MATRIX_DIAGONAL`
  (display), as above.
- **Pair that never met**: zeroed cell (raw) / ``""`` (display), as above.
- **Unresolved owner**: ``"Roster {roster_id}"`` display label.
- **Asymmetric input**: if a hand-filtered input contains ``(1, 2)`` but not
  its mirror ``(2, 1)``, the matrix is not mirror-consistent -- cell
  ``[2][1]`` is a zeroed "never met" cell. Mirror consistency is a property
  of FFA-040's unfiltered output, not something this module enforces.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

#: Display-matrix cell for the meaningless "manager vs. themselves" diagonal.
#: The em dash matches AGENTS.md's example grid.
HEAD_TO_HEAD_MATRIX_DIAGONAL = "—"

#: Display-matrix cell for a pair of managers that never met.
HEAD_TO_HEAD_MATRIX_NO_MEETING = ""


@dataclass(frozen=True)
class HeadToHeadCell:
    """One ordered ``(roster_id, opponent_roster_id)`` cell of the raw matrix.

    A frozen dataclass rather than a tuple or dict so cells are typed,
    self-describing, and hashable. Counts are copied verbatim from the
    corresponding FFA-040 head-to-head record row and carry that module's
    semantics unchanged.

    Attributes:
        roster_id: The row (own) roster.
        opponent_roster_id: The column (opponent) roster.
        meetings: Number of times the pair met. ``0`` for a pair that never
            met -- see the module docstring's "Pairs that never met".
        wins: Wins by ``roster_id`` over ``opponent_roster_id``.
        losses: Losses by ``roster_id`` to ``opponent_roster_id``.
        ties: Ties between the two.
    """

    roster_id: int
    opponent_roster_id: int
    meetings: int
    wins: int
    losses: int
    ties: int

    def format_record(self) -> str:
        """Render this cell as ``"W-L"``, or ``"W-L-T"`` if it has any ties.

        Returns :data:`HEAD_TO_HEAD_MATRIX_NO_MEETING` for a cell with zero
        meetings. See the module docstring's "Record formatting and ties"
        for why the tie component is conditional and per-cell.
        """
        if self.meetings == 0:
            return HEAD_TO_HEAD_MATRIX_NO_MEETING
        if self.ties:
            return f"{self.wins}-{self.losses}-{self.ties}"
        return f"{self.wins}-{self.losses}"


def _roster_universe(head_to_head_df: pd.DataFrame) -> list[int]:
    """Return the sorted union of roster ids on either side of the input.

    See the module docstring's "Universe of managers" for why the union is
    taken even though FFA-040's mirrored output makes it redundant.
    """
    roster_ids = set(head_to_head_df["roster_id"]) | set(
        head_to_head_df["opponent_roster_id"]
    )
    return sorted(int(roster_id) for roster_id in roster_ids)


def _owner_labels(head_to_head_df: pd.DataFrame, roster_ids: list[int]) -> list[str]:
    """Map each roster id to its display label for the display matrix axes.

    Owners are read from both the ``roster_id``/``owner`` and the
    ``opponent_roster_id``/``opponent_owner`` column pairs (either side may
    be the one that carries a given roster's label). An unresolved owner
    falls back to ``"Roster {roster_id}"`` -- see the module docstring's
    "Axis labels and roster-id traceability".
    """
    owner_by_roster: dict[int, str] = {}
    column_pairs = (("roster_id", "owner"), ("opponent_roster_id", "opponent_owner"))
    for roster_column, owner_column in column_pairs:
        for roster_id, owner in zip(
            head_to_head_df[roster_column], head_to_head_df[owner_column]
        ):
            if owner is not None and pd.notna(owner):
                owner_by_roster[int(roster_id)] = str(owner)

    return [
        owner_by_roster.get(roster_id, f"Roster {roster_id}")
        for roster_id in roster_ids
    ]


def build_head_to_head_matrix(head_to_head_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot head-to-head records into a roster-by-roster matrix of raw cells.

    Reshapes FFA-040's one-row-per-ordered-pair output into a square grid
    where ``matrix.loc[a, b]`` is roster ``a``'s :class:`HeadToHeadCell`
    against roster ``b``. Defines no new metrics -- every count is copied
    from the corresponding input row. See the module docstring for the
    diagonal/never-met sentinels, the roster universe rule, and the
    combined regular-season-plus-playoff scope inherited from FFA-040.

    Args:
        head_to_head_df: A ``HEAD_TO_HEAD_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.analytics.head_to_head.build_head_to_head_records`.

    Returns:
        An ``object``-dtype DataFrame indexed by ``roster_id`` (ascending)
        on both axes, with ``index.name = "roster_id"`` and
        ``columns.name = "opponent_roster_id"``. Each off-diagonal cell is a
        :class:`HeadToHeadCell` -- zeroed (``meetings = 0``) for a pair with
        no row in the input. Each diagonal cell is ``None``. Returns an
        empty DataFrame (no rows, no columns) if ``head_to_head_df`` is
        empty.
    """
    if head_to_head_df.empty:
        return pd.DataFrame()

    roster_ids = _roster_universe(head_to_head_df)

    cells_by_pair: dict[tuple[int, int], HeadToHeadCell] = {}
    for row in head_to_head_df.itertuples(index=False):
        roster_id = int(row.roster_id)
        opponent_roster_id = int(row.opponent_roster_id)
        cells_by_pair[(roster_id, opponent_roster_id)] = HeadToHeadCell(
            roster_id=roster_id,
            opponent_roster_id=opponent_roster_id,
            meetings=int(row.meetings),
            wins=int(row.wins),
            losses=int(row.losses),
            ties=int(row.ties),
        )

    grid = []
    for roster_id in roster_ids:
        grid_row: list[HeadToHeadCell | None] = []
        for opponent_roster_id in roster_ids:
            if roster_id == opponent_roster_id:
                # The diagonal is meaningless; None keeps it distinguishable
                # from a genuine zero-meetings pair.
                grid_row.append(None)
                continue
            grid_row.append(
                cells_by_pair.get(
                    (roster_id, opponent_roster_id),
                    HeadToHeadCell(
                        roster_id=roster_id,
                        opponent_roster_id=opponent_roster_id,
                        meetings=0,
                        wins=0,
                        losses=0,
                        ties=0,
                    ),
                )
            )
        grid.append(grid_row)

    matrix = pd.DataFrame(grid, index=roster_ids, columns=roster_ids, dtype=object)
    matrix.index.name = "roster_id"
    matrix.columns.name = "opponent_roster_id"
    return matrix


def format_head_to_head_matrix(head_to_head_df: pd.DataFrame) -> pd.DataFrame:
    """Render the head-to-head matrix as owner-labeled ``"W-L"`` strings.

    The human-readable counterpart to :func:`build_head_to_head_matrix`,
    producing the grid shape shown in AGENTS.md. This representation is
    lossy (counts become strings) and its axis labels can collide -- use the
    raw matrix for anything programmatic. See the module docstring's "Two
    representations", "Axis labels and roster-id traceability", and "Record
    formatting and ties" sections.

    Args:
        head_to_head_df: A ``HEAD_TO_HEAD_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.analytics.head_to_head.build_head_to_head_records`.
            The raw matrix is rebuilt internally from it.

    Returns:
        A DataFrame of strings in the same roster order as
        :func:`build_head_to_head_matrix`, with both axes relabeled to owner
        display names (``"Roster {roster_id}"`` when an owner is
        unresolved). Cells are ``"W-L"``, or ``"W-L-T"`` when that pair has
        ties, :data:`HEAD_TO_HEAD_MATRIX_NO_MEETING` for a pair that never
        met, and :data:`HEAD_TO_HEAD_MATRIX_DIAGONAL` on the diagonal.
        Returns an empty DataFrame if ``head_to_head_df`` is empty.
    """
    matrix = build_head_to_head_matrix(head_to_head_df)
    if matrix.empty:
        return matrix

    roster_ids = [int(roster_id) for roster_id in matrix.index]
    formatted = pd.DataFrame(
        [
            [
                HEAD_TO_HEAD_MATRIX_DIAGONAL if cell is None else cell.format_record()
                for cell in matrix.loc[roster_id]
            ]
            for roster_id in roster_ids
        ],
        index=_owner_labels(head_to_head_df, roster_ids),
        columns=_owner_labels(head_to_head_df, roster_ids),
        dtype=object,
    )
    formatted.index.name = "owner"
    formatted.columns.name = "opponent_owner"
    return formatted
