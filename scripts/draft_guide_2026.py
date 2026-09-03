"""Build a 2026 snake-draft guide for one draft slot in a 12-team half-PPR league.

Thin composition script. It defines no new metrics: it calls FFA-075's
market pool (FantasyFootballCalculator ADP + FantasyPros ECR, joined to
Sleeper IDs) and FFA-076's :func:`build_draft_board` (market-as-base blend
with the FFA-073 2025 retrospective value score as a conservative
adjustment), then reports the board through the lens of one specific set of
snake-draft picks.

The 2025 retrospective component is deliberately a minority weight and is
dropped entirely for K/DEF -- see ``draft_board``'s module docstring. A
rookie with no 2025 row is ranked on market consensus alone with no penalty.

Example::

    .venv/bin/python scripts/draft_guide_2026.py \\
        --prior-csv scripts/output/draft2026/NWC_FFL_2025_prior.csv \\
        --slot 5 --teams 12 --rounds 16 \\
        --out-dir scripts/output/draft2026

Network: hits FantasyFootballCalculator and DynastyProcess once each, both
cached under ``.cache/``. Pass ``--no-market-refresh`` to force cache-only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from fantasy_analyzer.players.draft_board import (
    build_draft_board,
    build_pick_availability_table,
)
from fantasy_analyzer.players.draft_market_cache import (
    get_draft_market_player_pool_cached,
)

#: Positions worth streaming rather than rostering early. They are hidden
#: from a pick's target list until :data:`STREAM_POSITION_LAST_ROUNDS` rounds
#: remain, because they are always available and otherwise crowd out the
#: positions the pick is actually deciding between.
STREAM_POSITIONS = frozenset({"K", "DEF"})

#: How many trailing rounds show :data:`STREAM_POSITIONS`.
STREAM_POSITION_LAST_ROUNDS = 3

#: Columns carried into the human-facing board CSV, in report order.
GUIDE_REPORT_COLUMNS = [
    "draft_rank",
    "player_name",
    "position",
    "nfl_team",
    "bye_week",
    "position_rank",
    "tier",
    "adp",
    "ecr",
    "adp_pool_rank",
    "adp_delta",
    "vor",
    "draft_score",
    "market_score",
    "prior_ranking_score",
    "prior_league_rank",
    "components_used",
    "sleeper_player_id",
]


def snake_picks(slot: int, teams: int, rounds: int) -> list[int]:
    """Return the overall pick numbers for one slot in a snake draft.

    Odd rounds run 1..teams, even rounds run teams..1, so a slot's picks
    alternate between two gap sizes.

    Args:
        slot: The 1-indexed draft slot (1..teams).
        teams: Number of teams in the draft.
        rounds: Number of rounds in the draft.

    Returns:
        Overall pick numbers in ascending round order.

    Raises:
        ValueError: If any argument is out of range.
    """
    if teams < 1:
        raise ValueError(f"teams must be >= 1; got {teams!r}")
    if not (1 <= slot <= teams):
        raise ValueError(f"slot must be in 1..{teams}; got {slot!r}")
    if rounds < 1:
        raise ValueError(f"rounds must be >= 1; got {rounds!r}")

    picks: list[int] = []
    for rnd in range(1, rounds + 1):
        offset = slot if rnd % 2 == 1 else (teams - slot + 1)
        picks.append((rnd - 1) * teams + offset)
    return picks


def load_prior(prior_csv: Optional[Path]) -> Optional[pd.DataFrame]:
    """Load the FFA-073 retrospective ranking CSV, if one was supplied.

    Args:
        prior_csv: Path to a ``composite_ranking_report.py`` CSV, or ``None``.

    Returns:
        The frame with ``sleeper_player_id`` as ``str``, or ``None`` when no
        path was given.

    Raises:
        FileNotFoundError: If the path was given but does not exist.
        ValueError: If the CSV lacks ``sleeper_player_id`` -- an older CSV
            written before that column was added to the report.
    """
    if prior_csv is None:
        return None
    if not prior_csv.exists():
        raise FileNotFoundError(f"Prior ranking CSV not found: {prior_csv}")

    prior = pd.read_csv(prior_csv)
    if "sleeper_player_id" not in prior.columns:
        raise ValueError(
            f"{prior_csv} has no 'sleeper_player_id' column. Regenerate it "
            "with scripts/composite_ranking_report.py -- the board joins on "
            "the Sleeper ID, never on player_name."
        )
    prior["sleeper_player_id"] = prior["sleeper_player_id"].astype(str)
    return prior


def summarize_pick(
    board: pd.DataFrame,
    availability: pd.DataFrame,
    pick: int,
    *,
    per_position: int = 3,
    min_probability: float = 0.30,
    exclude_positions: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Rank the best realistic targets at one pick, grouped by position.

    A player's ``expected_vor`` is ``vor * P(available at this pick)``,
    which trades raw value against the chance he is already gone. Results
    are then taken ``per_position`` at a time rather than as one flat list,
    because a flat list collapses onto whichever position happens to have
    the steepest replacement curve and stops being actionable -- you only
    start one TE, so the 4th-best available TE is not a real option.

    Players below ``min_probability`` are dropped as unrealistic rather
    than shown with a near-zero expected value.

    Args:
        board: A :func:`build_draft_board` frame.
        availability: A :func:`build_pick_availability_table` frame whose
            columns cover ``pick``.
        pick: The overall pick number to summarize.
        per_position: How many players to keep per position.
        min_probability: Minimum availability probability to include.
        exclude_positions: Positions to omit entirely from this pick's list.

    Returns:
        Rows sorted by descending ``expected_vor``, at most
        ``per_position`` per position, with added ``p_available`` and
        ``expected_vor`` columns. Empty if ``pick`` has no column.
    """
    col = f"prob_available_pick_{pick}"
    if col not in availability.columns:
        return board.head(0).assign(p_available=[], expected_vor=[])

    merged = board.merge(
        availability[["sleeper_player_id", col]], on="sleeper_player_id", how="left"
    )
    merged = merged.rename(columns={col: "p_available"})
    merged = merged[merged["vor"].notna() & merged["p_available"].notna()]
    merged = merged[merged["p_available"] >= min_probability]
    if exclude_positions:
        merged = merged[~merged["position"].isin(exclude_positions)]
    merged["expected_vor"] = merged["vor"] * merged["p_available"]
    kept = (
        merged.sort_values("expected_vor", ascending=False)
        .groupby("position", group_keys=False)
        .head(per_position)
    )
    return kept.sort_values("expected_vor", ascending=False)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="draft_guide_2026.py",
        description=(
            "Build a 2026 snake-draft guide for one draft slot in a "
            "12-team half-PPR league."
        ),
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--scoring", default="half-ppr")
    parser.add_argument(
        "--prior-csv",
        type=Path,
        default=None,
        help="FFA-073 retrospective ranking CSV. Omitted => pure-market board.",
    )
    parser.add_argument(
        "--roster-positions",
        default=None,
        help=(
            "Comma-separated Sleeper roster_positions list for the VOR "
            "replacement baseline (e.g. 'QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,"
            "BN,BN,BN,BN,BN'). Omitted => the default 1-QB/2-RB/2-WR/1-TE/"
            "1-FLEX/K/DEF 12-team board. Must match --teams for a sensible "
            "replacement level in a league whose lineup differs from that "
            "default (extra FLEX, different team count, etc.)."
        ),
    )
    parser.add_argument(
        "--exclude-id",
        action="append",
        default=[],
        help="Sleeper player_id to remove from the board (keepers). Repeatable.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("scripts/output"))
    parser.add_argument("--out-prefix", default="draft_guide")
    parser.add_argument(
        "--no-market-refresh",
        action="store_true",
        help="Use only cached market data; do not re-fetch.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    market = get_draft_market_player_pool_cached(
        args.season,
        teams=args.teams,
        scoring=args.scoring,
        force_refresh=not args.no_market_refresh,
    )
    prior = load_prior(args.prior_csv)

    roster_positions = (
        [slot.strip() for slot in args.roster_positions.split(",") if slot.strip()]
        if args.roster_positions
        else None
    )
    board = build_draft_board(
        market, prior, num_teams=args.teams, roster_positions=roster_positions
    )

    if args.exclude_id:
        excluded = {str(pid) for pid in args.exclude_id}
        gone = board[board["sleeper_player_id"].isin(excluded)]
        for _, row in gone.iterrows():
            print(f"  excluded (keeper): {row['player_name']} ({row['position']})")
        board = board[~board["sleeper_player_id"].isin(excluded)].copy()

    picks = snake_picks(args.slot, args.teams, args.rounds)
    availability = build_pick_availability_table(board, picks)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.out_prefix}_{args.season}_slot{args.slot}of{args.teams}"

    board_path = args.out_dir / f"{stem}_board.csv"
    board[GUIDE_REPORT_COLUMNS].to_csv(board_path, index=False)

    avail_path = args.out_dir / f"{stem}_availability.csv"
    availability.to_csv(avail_path, index=False)

    print(f"Board:        {len(board)} players -> {board_path}")
    print(f"Availability: {len(availability)} players -> {avail_path}")
    print(f"Picks (slot {args.slot} of {args.teams}): {picks}")

    for rnd, pick in enumerate(picks, start=1):
        rounds_left = len(picks) - rnd + 1
        hidden = (
            frozenset()
            if rounds_left <= STREAM_POSITION_LAST_ROUNDS
            else STREAM_POSITIONS
        )
        targets = summarize_pick(board, availability, pick, exclude_positions=hidden)
        print(f"\n--- Round {rnd}, pick {pick} ---")
        if targets.empty:
            print("  (no realistic scored targets)")
            continue
        for _, row in targets.iterrows():
            bye = "" if pd.isna(row["bye_week"]) else f" bye{int(row['bye_week'])}"
            print(
                f"  {row['position']:<4} {row['player_name']:<24}"
                f" adp={row['adp']:>6.1f} vor={row['vor']:>6.2f}"
                f" p={row['p_available']:>5.2f} exp={row['expected_vor']:>6.2f}{bye}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
