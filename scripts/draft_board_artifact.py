"""Render a 2026 draft-board artifact page for one league and one draft slot.

Presentation layer only. Every number on the page comes from
:func:`fantasy_analyzer.players.draft_board.build_draft_board` (FFA-076)
and :func:`~fantasy_analyzer.players.draft_board.build_pick_availability_table`,
fed by FFA-075's cached market pool and the FFA-073 2025 retrospective
ranking CSV -- exactly the inputs ``scripts/draft_guide_2026.py`` uses. No
metric is defined or re-weighted here.

The page is the same shape as the NWC FFL board documented in
``docs/draft-board-2026.md``: your picks, targets at each turn, the
positional value cliffs, market value/reach tables, and the full board.
It is written as a standalone HTML file suitable for publishing as an
Artifact.

Example::

    .venv/bin/python scripts/draft_board_artifact.py \\
        --league zipline --slot 10 --top-per-position 30

    .venv/bin/python scripts/draft_board_artifact.py \\
        --league new-wave --slot 3 --top-per-position 30 --slot-provisional

Any league not in :data:`LEAGUES` can be rendered by passing the same
settings explicitly (``--teams``, ``--rounds``, ``--scoring``,
``--roster-positions``, ``--prior-csv``, ``--league-title``).

Network: hits FantasyFootballCalculator and FantasyPros/DynastyProcess once
each, both cached under ``.cache/``. Pass ``--no-market-refresh`` to force
cache-only.
"""

from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any, Optional, Sequence

import pandas as pd

from fantasy_analyzer.players.draft_board import (
    build_draft_board,
    build_pick_availability_table,
)
from fantasy_analyzer.players.draft_market_cache import (
    get_draft_market_player_pool_cached,
)

from draft_guide_2026 import (  # noqa: E402  (sibling script, same directory)
    STREAM_POSITIONS,
    STREAM_POSITION_LAST_ROUNDS,
    GUIDE_REPORT_COLUMNS,
    load_prior,
    snake_picks,
    summarize_pick,
)

TEMPLATE_PATH = Path(__file__).parent / "templates" / "draft_board_artifact.html.tpl"

#: Positions that get a value-cliff panel, in display order. K/DEF are
#: omitted deliberately: they are market-only (see :data:`NOTE_STREAMERS`)
#: and streamed rather than reached for.
CLIFF_POSITIONS = ["RB", "WR", "TE", "QB"]

#: Known leagues, keyed by CLI slug. Values mirror
#: ``scripts/draft_guide_2026_league.sh`` -- all confirmed against Sleeper's
#: 2026 league settings.
LEAGUES: dict[str, dict[str, Any]] = {
    "nwc": {
        "title": "NWC FFL, est. 2011",
        "short_title": "NWC FFL",
        "teams": 12,
        "rounds": 16,
        "scoring": "half-ppr",
        "scoring_label": "Half PPR",
        "roster_positions": "QB,RB,RB,WR,WR,TE,FLEX,K,DEF,BN,BN,BN,BN,BN,BN,BN",
        "prior_csv": "scripts/output/draft2026/NWC_FFL_2025_prior_1257477810625196032.csv",
        "out_prefix": "NWC",
    },
    "new-wave": {
        "title": "New Wave Friends League",
        "short_title": "New Wave",
        "teams": 10,
        "rounds": 15,
        "scoring": "ppr",
        "scoring_label": "Full PPR",
        "roster_positions": "QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,BN,BN,BN,BN,BN",
        "prior_csv": "scripts/output/draft2026/New_Wave_2025_prior_1260307567133859840.csv",
        "out_prefix": "NewWave",
    },
    "zipline": {
        "title": "Just Here For The Zipline",
        "short_title": "Zipline",
        "teams": 10,
        "rounds": 16,
        "scoring": "half-ppr",
        "scoring_label": "Half PPR",
        "roster_positions": "QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,BN,BN,BN,BN,BN,BN",
        "prior_csv": "scripts/output/draft2026/Zipline_2025_prior_1262800342051999744.csv",
        "out_prefix": "Zipline",
    },
}

_ORDINALS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth",
    7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh",
    12: "twelfth",
}

_NUMBER_WORDS = {
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen",
    19: "nineteen", 20: "twenty",
}

NOTE_STREAMERS = (
    "Kicker and defense ranks are market only",
    "Your league's 2025 scoring could not be mapped for team defenses at all "
    "&mdash; sacks, interceptions, points allowed, return touchdowns &mdash; and "
    "only partially for kickers. Rather than rank them on a number that looks "
    "plausible but is built from unmapped rules, the retrospective component is "
    "switched off for both positions. They rank on 2026 consensus alone, which "
    "is the right call for two positions you stream anyway.",
    "",
)

NOTE_ROOKIES = (
    "Rookies are not penalized",
    "The 2025 production score is a minority input, not an equal partner, and it "
    "is dropped entirely for anyone without a 2025 season. A rookie ranks on "
    "market consensus alone with no penalty. Weighting last year at even half "
    "would have buried the entire incoming class.",
    "teal",
)


def _fmt(value: Any, digits: int = 2) -> Optional[float]:
    """Round a possibly-missing numeric cell to ``digits``, or ``None``."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(value), digits)


def _starters_label(roster_positions: Sequence[str]) -> str:
    """Render a compact starting-lineup label, e.g. ``QB&middot;RB2&middot;WR2``."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for slot in roster_positions:
        slot = slot.strip().upper()
        if slot in {"BN", "IR", "TAXI"}:
            continue
        if slot not in counts:
            order.append(slot)
        counts[slot] = counts.get(slot, 0) + 1
    short = {"FLEX": "FLX", "SUPER_FLEX": "SFLX", "REC_FLEX": "RFLX"}
    parts = [
        f"{short.get(slot, slot)}{counts[slot] if counts[slot] > 1 else ''}"
        for slot in order
    ]
    return "&middot;".join(parts)


def build_turns(
    board: pd.DataFrame, availability: pd.DataFrame, picks: Sequence[int]
) -> list[dict[str, Any]]:
    """Build the per-pick target lists shown in "Targets at each turn"."""
    turns: list[dict[str, Any]] = []
    for rnd, pick in enumerate(picks, start=1):
        rounds_left = len(picks) - rnd + 1
        hidden = (
            frozenset()
            if rounds_left <= STREAM_POSITION_LAST_ROUNDS
            else STREAM_POSITIONS
        )
        targets = summarize_pick(board, availability, pick, exclude_positions=hidden)
        turns.append(
            {
                "round": rnd,
                "pick": pick,
                "targets": [
                    {
                        "name": row["player_name"],
                        "pos": row["position"],
                        "team": row["nfl_team"],
                        "adp": _fmt(row["adp"], 1),
                        "vor": _fmt(row["vor"]),
                        "p": _fmt(row["p_available"], 3),
                        "exp": _fmt(row["expected_vor"]),
                        "bye": _fmt(row["bye_week"], 0),
                        "tier": _fmt(row["tier"], 0),
                        "delta": _fmt(row["adp_delta"], 1),
                    }
                    for _, row in targets.iterrows()
                ],
            }
        )
    return turns


def build_cliffs(
    board: pd.DataFrame, top_per_position: int
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Build the per-position VOR ladders and their one-line ledes.

    Returns:
        ``(cliffs, notes)`` where ``cliffs`` maps position to the top
        ``top_per_position`` players by VOR, and ``notes`` maps position to a
        sentence naming where the steepest single drop in that ladder falls.
    """
    cliffs: dict[str, list[dict[str, Any]]] = {}
    notes: dict[str, str] = {}
    for pos in CLIFF_POSITIONS:
        rows = (
            board[(board["position"] == pos) & board["vor"].notna()]
            .sort_values("vor", ascending=False)
            .head(top_per_position)
        )
        entries = [
            {
                "name": row["player_name"],
                "vor": _fmt(row["vor"]),
                "adp": _fmt(row["adp"], 1),
                "tier": _fmt(row["tier"], 0),
            }
            for _, row in rows.iterrows()
        ]
        cliffs[pos] = entries

        drop_idx, drop_size = -1, -1.0
        for i in range(1, len(entries)):
            gap = (entries[i - 1]["vor"] or 0) - (entries[i]["vor"] or 0)
            if gap > drop_size:
                drop_size, drop_idx = gap, i
        if drop_idx > 0:
            notes[pos] = (
                f"Steepest drop after {pos}{drop_idx}: "
                f"{entries[drop_idx - 1]['name']} to {entries[drop_idx]['name']}, "
                f"{drop_size:.2f} VOR"
            )
        else:
            notes[pos] = "Too few priced players to show a cliff"
    return cliffs, notes


def build_delta_tables(
    board: pd.DataFrame, *, board_top: int, limit: int = 12
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the top of the board into biggest market values and reaches.

    ``adp_delta`` is ``adp - adp_pool_rank``: positive means the market lets
    the player fall past where this board wants him (a value), negative means
    the board ranks him later than the room will take him (a reach).
    """
    scoped = board.head(board_top)
    priced = scoped[scoped["adp_delta"].notna()]

    def rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "name": row["player_name"],
                "pos": row["position"],
                "adp": _fmt(row["adp"], 1),
                "delta": _fmt(row["adp_delta"], 1),
                "vor": _fmt(row["vor"]),
            }
            for _, row in frame.iterrows()
        ]

    values = rows(priced.sort_values("adp_delta", ascending=False).head(limit))
    reaches = rows(priced.sort_values("adp_delta", ascending=True).head(limit))
    return values, reaches


def build_overall(board: pd.DataFrame, board_top: int) -> list[dict[str, Any]]:
    """Build the "Full board" table rows."""
    return [
        {
            "rank": _fmt(row["draft_rank"], 0),
            "name": row["player_name"],
            "pos": row["position"],
            "team": row["nfl_team"],
            "bye": _fmt(row["bye_week"], 0),
            "adp": _fmt(row["adp"], 1),
            "ecr": _fmt(row["ecr"], 1),
            "vor": _fmt(row["vor"]),
            "tier": _fmt(row["tier"], 0),
            "posrank": _fmt(row["position_rank"], 0),
            "delta": _fmt(row["adp_delta"], 1),
            "prior": _fmt(row["prior_ranking_score"]),
            "comp": int(row["components_used"]),
        }
        for _, row in board.head(board_top).iterrows()
    ]


def _picks_copy(picks: Sequence[int], slot: int, teams: int) -> tuple[str, str, str]:
    """Return (heading, sub-paragraph, gap note) describing the pick rhythm."""
    n = len(picks)
    word = _NUMBER_WORDS.get(n, str(n))
    heading = f"Your {word} picks"

    gaps = [picks[i + 1] - picks[i] for i in range(len(picks) - 1)]
    short, long = (min(gaps), max(gaps)) if gaps else (0, 0)
    ordinal = _ORDINALS.get(slot, f"{slot}th")

    if short == long:
        sub = (
            f"Slot {slot} of {teams} picks on an even {short}-pick rhythm all "
            "draft. Every turn is the same distance from the last, so the board "
            "moves the same amount between each of your decisions."
        )
        gap_note = (
            f"<b>{short} every time</b> <span>A steady cadence &mdash; no "
            "back-to-back pairs to plan around.</span>"
        )
    else:
        if short == 1:
            closeness = (
                "The highlighted picks are literally back-to-back &mdash; treat "
                "each pair as one decision covering two players, because nothing "
                "comes off the board in between."
            )
        elif short <= 5:
            closeness = (
                "The highlighted picks are the short side of each turn &mdash; "
                "treat each pair as close to one decision, because only a "
                f"handful of players ({short - 1}) go between them."
            )
        else:
            closeness = (
                f"The highlighted picks open each {short}-pick turnaround, the "
                "half of the draft where the board moves least between your "
                "selections."
            )
        sub = (
            f"Snake order puts the {ordinal} slot on an uneven rhythm: a "
            f"{long}-pick drought, then a {short}-pick turnaround. " + closeness
        )
        seq = " &rarr; ".join(str(g) for g in gaps[:4])
        gap_note = (
            f"<b>{seq}</b> <span>Gaps alternate all draft. You never pick twice "
            "quickly at the top of a round.</span>"
        )
    return heading, sub, gap_note


def _render_notes(notes: Sequence[tuple[str, str, str]], method: Sequence[str]) -> str:
    """Render the closing "Read this before you pick" notes and method list."""
    blocks = [
        f'  <div class="note{" " + tone if tone else ""}">\n'
        f"    <h3>{title}</h3>\n"
        f"    <p>{body}</p>\n"
        "  </div>\n"
        for title, body, tone in notes
    ]
    blocks.append(
        '  <h3 style="font-family:Oswald,sans-serif;font-size:14px;'
        "text-transform:uppercase;letter-spacing:.05em;margin:22px 0 8px\">"
        "How a rank is built</h3>\n"
        '  <ol class="method">\n'
    )
    blocks.extend(f"    <li>{item}</li>\n" for item in method)
    return "".join(blocks)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="draft_board_artifact.py",
        description="Render a 2026 draft-board artifact page for one league and slot.",
    )
    parser.add_argument(
        "--league",
        choices=sorted(LEAGUES),
        default=None,
        help="Known league slug; supplies teams/rounds/scoring/roster/prior CSV.",
    )
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--teams", type=int, default=None)
    parser.add_argument("--rounds", type=int, default=None)
    parser.add_argument("--scoring", default=None, help="e.g. ppr, half-ppr, standard")
    parser.add_argument("--scoring-label", default=None)
    parser.add_argument("--roster-positions", default=None)
    parser.add_argument("--prior-csv", type=Path, default=None)
    parser.add_argument("--league-title", default=None)
    parser.add_argument(
        "--short-title",
        default=None,
        help="Short league name used in the browser/gallery title. Defaults to "
        "--league-title.",
    )
    parser.add_argument(
        "--top-per-position",
        type=int,
        default=30,
        help="Players per position in the value-cliff panels (default 30).",
    )
    parser.add_argument(
        "--board-top",
        type=int,
        default=180,
        help="Rows in the full-board table (default 180).",
    )
    parser.add_argument(
        "--slot-provisional",
        action="store_true",
        help="Add a note that Sleeper has not assigned this draft order yet.",
    )
    parser.add_argument(
        "--exclude-id",
        action="append",
        default=[],
        help="Sleeper player_id to remove from the board (keepers). Repeatable.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("scripts/output/draft2026"))
    parser.add_argument("--out-prefix", default=None)
    parser.add_argument("--no-market-refresh", action="store_true")
    return parser


def resolve_config(args: argparse.Namespace) -> dict[str, Any]:
    """Merge a known-league preset with explicit CLI overrides.

    Raises:
        SystemExit: If a required setting is neither preset nor supplied.
    """
    preset = dict(LEAGUES[args.league]) if args.league else {}
    cfg = {
        "title": args.league_title or preset.get("title"),
        "short_title": (
            args.short_title
            or preset.get("short_title")
            or args.league_title
            or preset.get("title")
        ),
        "teams": args.teams or preset.get("teams"),
        "rounds": args.rounds or preset.get("rounds"),
        "scoring": args.scoring or preset.get("scoring"),
        "scoring_label": args.scoring_label or preset.get("scoring_label"),
        "roster_positions": args.roster_positions or preset.get("roster_positions"),
        "prior_csv": args.prior_csv or (
            Path(preset["prior_csv"]) if preset.get("prior_csv") else None
        ),
        "out_prefix": args.out_prefix or preset.get("out_prefix") or "draft_board",
    }
    missing = [k for k in ("title", "teams", "rounds", "scoring") if not cfg[k]]
    if missing:
        raise SystemExit(
            f"Missing required setting(s): {', '.join(missing)}. Pass --league, "
            "or supply them explicitly."
        )
    if not cfg["scoring_label"]:
        cfg["scoring_label"] = cfg["scoring"].replace("-", " ").title()
    return cfg


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cfg = resolve_config(args)
    teams, rounds = int(cfg["teams"]), int(cfg["rounds"])

    market = get_draft_market_player_pool_cached(
        args.season,
        teams=teams,
        scoring=cfg["scoring"],
        force_refresh=not args.no_market_refresh,
    )
    prior = load_prior(cfg["prior_csv"])

    roster_positions = (
        [s.strip() for s in cfg["roster_positions"].split(",") if s.strip()]
        if cfg["roster_positions"]
        else None
    )
    board = build_draft_board(
        market, prior, num_teams=teams, roster_positions=roster_positions
    )

    excluded_names: list[str] = []
    if args.exclude_id:
        excluded = {str(pid) for pid in args.exclude_id}
        gone = board[board["sleeper_player_id"].isin(excluded)]
        excluded_names = [
            f"{row['player_name']} ({row['position']})" for _, row in gone.iterrows()
        ]
        board = board[~board["sleeper_player_id"].isin(excluded)].copy()

    picks = snake_picks(args.slot, teams, rounds)
    availability = build_pick_availability_table(board, picks)

    cliffs, cliff_notes = build_cliffs(board, args.top_per_position)
    values, reaches = build_delta_tables(board, board_top=args.board_top)
    priced = int(board["adp"].notna().sum())

    data: dict[str, Any] = {
        "picks": list(picks),
        "turns": build_turns(board, availability, picks),
        "overall": build_overall(board, args.board_top),
        "cliffs": cliffs,
        "cliffNotes": cliff_notes,
        "cliffOrder": CLIFF_POSITIONS,
        "values": values,
        "reaches": reaches,
        "counts": {"board": int(len(board)), "adp": priced},
        "meta": {
            # The rail highlights picks separated by the draft's shortest gap
            # (the near-back-to-back turnaround pairs). A slot whose gaps are
            # all equal has no pairs to highlight.
            "shortGap": (
                min(b - a for a, b in zip(picks, picks[1:]))
                if len(picks) > 1
                and len({b - a for a, b in zip(picks, picks[1:])}) > 1
                else None
            ),
            "footer": (
                f"Built from {len(board)} ranked players, {priced} with live "
                f"market pricing. Market data: FantasyFootballCalculator "
                f"{teams}-team {cfg['scoring_label']} ADP and FantasyPros "
                f"expert consensus. Prior season: this league's own 2025 scoring."
            )
        },
    }

    heading, picks_sub, gap_note = _picks_copy(picks, args.slot, teams)
    starters = _starters_label(roster_positions or [])

    facts = [
        ("Slot", f"{args.slot} of {teams}"),
        ("Format", cfg["scoring_label"]),
        ("Rounds", str(rounds)),
    ]
    if starters:
        facts.append(("Starters", starters))
    mast_facts = "\n".join(
        f'    <div class="fact"><dt>{k}</dt><dd>{v}</dd></div>' for k, v in facts
    )

    notes: list[tuple[str, str, str]] = []
    if args.slot_provisional:
        notes.append(
            (
                "This slot is provisional",
                f"Sleeper has not assigned this league's 2026 draft order yet, so "
                f"slot {args.slot} is a stand-in. The full board, the value cliffs "
                f"and the market value/reach tables do not depend on it &mdash; "
                f"only the pick numbers and the per-turn availability do. Rerun "
                f"with the real slot once the order is set and everything else "
                f"comes out identical.",
                "",
            )
        )
    if excluded_names:
        notes.append(
            (
                "Keepers removed from this board",
                "Excluded before ranking: " + ", ".join(excluded_names) + ".",
                "",
            )
        )
    notes.extend([NOTE_STREAMERS, NOTE_ROOKIES])

    method = [
        f"<b>Market base (75%).</b> Average draft position from {teams}-team "
        f"{cfg['scoring_label']} mock drafts, blended 60/40 with expert "
        "consensus rank. Both are converted to a value curve before scoring, so "
        "the gap between the 1st and 5th ranked player counts for more than the "
        "gap between the 101st and 105th.",
        "<b>Last season's production (25%).</b> Your league's own 2025 composite "
        "value score, computed under your actual scoring settings across the full "
        "free-agent-inclusive player pool &mdash; not just players someone "
        "rostered.",
        "<b>Missing inputs are dropped, not zeroed.</b> A player missing either "
        "component is scored on what remains and renormalized, so a gap never "
        "reads as a weakness.",
        f"<b>Value over replacement</b> is measured against the last starter at "
        f"each position for a {teams}-team league with this exact lineup, which "
        "is what makes tight end and quarterback comparable to running back at "
        "all.",
        "<b>Availability</b> models each player's true draft position as a normal "
        "distribution around his ADP, using the market's own observed spread "
        "where it exists.",
    ]

    title = f"{cfg['short_title']} Pick {args.slot} Draft Board"
    template = TEMPLATE_PATH.read_text()
    page = (
        template.replace("{{TITLE}}", html.escape(title))
        .replace(
            "{{EYEBROW}}",
            f"{html.escape(cfg['title'])} &middot; {args.season} season",
        )
        .replace(
            "{{HEADLINE}}",
            f"Draft board<br>from slot {args.slot}",
        )
        .replace("{{MAST_FACTS}}", mast_facts)
        .replace("{{PICKS_HEADING}}", heading)
        .replace("{{PICKS_SUB}}", picks_sub)
        .replace("{{GAP_NOTE}}", gap_note)
        .replace(
            "{{CLIFF_SUB}}",
            f"Value over replacement for the top {args.top_per_position} at each "
            "position. The dashed rule marks the steepest single drop &mdash; the "
            "cliff worth reaching to stay ahead of.",
        )
        .replace("{{BOARD_N}}", str(args.board_top))
        .replace("{{NOTES}}", _render_notes(notes, method))
        .replace("{{DATA}}", json.dumps(data))
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{cfg['out_prefix']}_{args.season}_slot{args.slot}of{teams}"
    board_path = args.out_dir / f"{stem}_board.csv"
    avail_path = args.out_dir / f"{stem}_availability.csv"
    html_path = args.out_dir / f"{stem}_artifact.html"

    board[GUIDE_REPORT_COLUMNS].to_csv(board_path, index=False)
    availability.to_csv(avail_path, index=False)
    html_path.write_text(page)

    print(f"Board:        {len(board)} players ({priced} priced) -> {board_path}")
    print(f"Availability: {len(availability)} players -> {avail_path}")
    print(f"Artifact:     {html_path}")
    print(f"Title:        {title}")
    print(f"Picks (slot {args.slot} of {teams}): {picks}")
    for pos in CLIFF_POSITIONS:
        print(f"  cliff {pos}: {len(cliffs[pos])} rows -- {cliff_notes[pos]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
