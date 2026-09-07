"""Grade a completed 2026 draft for one or more leagues and render a report.

FFA-081/082/083 -- the final layer of the seven-ticket "Draft Grade Reports"
feature. This is a thin composition script: it defines no new metrics. It
wires together, in order:

1. :func:`fantasy_analyzer.league.snapshot.load_league_snapshot` (teams/
   owners for one league).
2. :func:`fantasy_analyzer.league.draft.load_league_draft` and
   :func:`~fantasy_analyzer.league.draft.build_normalized_draft_picks`
   (FFA-077 -- normalize the raw Sleeper draft into one row per pick).
3. :func:`~fantasy_analyzer.players.draft_market_cache.
   get_draft_market_player_pool_cached` and
   :func:`~fantasy_analyzer.players.draft_board.build_draft_board`
   (the same 2026 market+prior-season board ``draft_guide_2026.py`` and
   ``draft_board_artifact.py`` build).
4. :func:`~fantasy_analyzer.players.draft_grade.score_draft_picks`
   (FFA-078 -- grade each pick against the board's expectation).
5. :func:`~fantasy_analyzer.players.draft_report.build_team_draft_grades`
   and :func:`~fantasy_analyzer.players.draft_report.build_draft_talking_points`
   (FFA-079/080 -- per-team letter grade, rank, and structured facts).

``--league-id`` is required per league (FFA-081 design note)
--------------------------------------------------------------------------

:data:`draft_league_presets.LEAGUES` (the same preset dict
``draft_board_artifact.py``/``draft_guide_2026.py`` use) supplies
teams/rounds/scoring/roster_positions/prior_csv/out_prefix for a known
league slug, but it was built for the pre-draft market/board tools, neither
of which ever calls the Sleeper API and so never needed a real Sleeper
``league_id``. This script is the first consumer that fetches a league's
actual draft from Sleeper, so it requires ``league_id`` as a separate,
explicit input alongside the ``--league`` slug rather than assuming the
preset resolves one:

    --league nwc --league-id 1257477810625196032

``--league``/``--league-id`` are both repeatable (``action="append"``) and
zipped together positionally, the same parallel-list convention
``composite_ranking_report.py`` uses for ``--league-id``/``--league-name``.
Passing a different count of each is a ``SystemExit``. Omitting both flags
runs every slug in :data:`draft_league_presets.LEAGUES`, resolving each
slug's ``league_id`` from the preset's own ``league_id`` field -- which, as
of this writing, is a placeholder (``"REPLACE_WITH_REAL_LEAGUE_ID"``) for
every preset league. Fill in real Sleeper league IDs in
``draft_league_presets.py`` before relying on the no-argument default; it
is documented there.

``--market-refresh`` defaults to OFF, unlike the sibling scripts
--------------------------------------------------------------------------

``draft_board_artifact.py`` and ``draft_guide_2026.py`` both *refresh* the
market cache by default (``--no-market-refresh`` opts out). This script
inverts that default on purpose: the draft already happened, so grading it
should reflect the market snapshot as of draft time, not a later refresh
that could shuffle ADP/ECR out from under a pick that was perfectly
reasonable when it was made. Pass ``--market-refresh`` to force a fresh
pull anyway (rare for a post-draft grade). Do not confuse this with
``--no-market-refresh`` on the other two scripts -- the flag name and its
default are both deliberately different here.

Outputs
--------------------------------------------------------------------------

Under ``--out-dir`` (default ``scripts/output/draft2026``), per league,
stemmed ``{out_prefix}_{season}_draft_report`` (``out_prefix`` from the
league preset, or ``--out-prefix`` to override):

- ``{stem}_picks_scored.csv`` -- every pick in the draft, FFA-078's
  :data:`~fantasy_analyzer.players.draft_grade.SCORED_DRAFT_PICK_COLUMNS`.
- ``{stem}_team_grades.csv`` -- one row per team, FFA-079's team-grade
  columns plus the FFA-080 talking-point columns not already present
  (``num_teams``, ``total_vor_rank``, ``avg_pick_value_rank``,
  ``most_drafted_position``, ``position_counts``, ``reach_count``,
  ``value_count``). ``position_counts`` is written as a JSON string so the
  CSV stays flat and reloadable with ``json.loads``.
- ``{stem}_artifact.html`` -- a standalone HTML report, one card per team
  (grade letter, draft rank, best/worst pick, position-count breakdown),
  built from the template ``scripts/templates/draft_report_artifact.html.tpl``.

Running with multiple leagues (``--league``/``--league-id`` repeated, or the
no-argument "run every preset" default) additionally writes one
league-spanning file directly under ``--out-dir`` (not per-league-stemmed):

- ``combined_leaderboard.csv`` -- columns ``league, team_name, grade_letter,
  overall_z, draft_rank``, one row per team across every league whose
  pipeline completed this run. Deliberately compares ``overall_z`` (already
  population-z-scored within its own draft) rather than raw ``total_vor``
  -- different leagues have different roster sizes and scoring settings, so
  raw VOR totals are not comparable across them, but a z-score is.
  ``total_vor`` is intentionally NOT a column in this file.

A league whose pipeline raises is skipped: an error naming the league is
printed to stderr and the run continues with the remaining leagues, the
same resilience pattern ``composite_ranking_report.py`` uses.

**FFA-083 -- the manual narrative step this script does NOT do**: every
team card in ``{stem}_artifact.html`` contains a literal, greppable
placeholder paragraph of the form ``{{COMMENTARY_ROSTER_<roster_id>}}``
(e.g. ``{{COMMENTARY_ROSTER_3}}`` for the team with ``roster_id`` 3). This
script's job ends the moment those placeholders are written to disk. A
human or an AI agent must separately read the matching
``{stem}_team_grades.csv`` row for each team and write 2-4 sentences of
prose commentary about that team's draft, then search-and-replace each
``{{COMMENTARY_ROSTER_<roster_id>}}`` token in the HTML file with that
prose, before the page is published or shared. This narrative pass is a
manual/agent-executed workflow step performed *after* this script runs --
it is not automated by any code in this repository.

Example::

    .venv/bin/python scripts/draft_report_2026.py \\
        --league nwc --league-id 1257477810625196032

    .venv/bin/python scripts/draft_report_2026.py \\
        --league nwc --league-id 1257477810625196032 \\
        --league zipline --league-id 1262800342051999744

Network: hits Sleeper (league/users/rosters/players/drafts/draft picks)
once per league, and FantasyFootballCalculator/FantasyPros/DynastyProcess
once total (cached under ``.cache/``, cache-only unless ``--market-refresh``
is passed).
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

import pandas as pd
from draft_guide_2026 import load_prior  # noqa: E402  (sibling script, same directory)
from draft_league_presets import LEAGUES  # noqa: E402  (sibling script, same directory)

from fantasy_analyzer.league.draft import (
    build_normalized_draft_picks,
    load_league_draft,
)
from fantasy_analyzer.league.snapshot import load_league_snapshot
from fantasy_analyzer.players.draft_board import build_draft_board
from fantasy_analyzer.players.draft_grade import score_draft_picks
from fantasy_analyzer.players.draft_market_cache import (
    get_draft_market_player_pool_cached,
)
from fantasy_analyzer.players.draft_points_value import (
    POINTS_VALUE_PICK_COLUMNS,
    PointsValueCurve,
    fit_points_value_curve,
    score_points_value,
)
from fantasy_analyzer.players.draft_report import (
    TEAM_DRAFT_GRADE_COLUMNS,
    build_draft_talking_points,
    build_team_draft_grades,
)
from fantasy_analyzer.sleeper.client import SleeperClient
from fantasy_analyzer.sleeper.exceptions import SleeperAPIError

TEMPLATE_PATH = Path(__file__).parent / "templates" / "draft_report_artifact.html.tpl"

#: Talking-point (FFA-080) columns not already present in FFA-079's
#: TEAM_DRAFT_GRADE_COLUMNS -- appended to build the merged per-team report.
_EXTRA_TALKING_POINT_COLUMNS = [
    "num_teams",
    "total_vor_rank",
    "avg_pick_value_rank",
    "most_drafted_position",
    "position_counts",
    "reach_count",
    "value_count",
]

#: Column order for the per-team CSV report (FFA-079 columns, then the
#: FFA-080 columns not already present).
TEAM_GRADE_REPORT_COLUMNS = TEAM_DRAFT_GRADE_COLUMNS + _EXTRA_TALKING_POINT_COLUMNS

#: Column order for the cross-league leaderboard (FFA-082). ``total_vor`` is
#: deliberately excluded -- see the module docstring's "Outputs" section.
COMBINED_LEADERBOARD_COLUMNS = [
    "league",
    "team_name",
    "grade_letter",
    "overall_z",
    "draft_rank",
]

#: Exceptions a single league's pipeline can reasonably raise that should
#: not abort the whole multi-league run -- mirrors
#: ``composite_ranking_report.py``'s per-league exception set, plus
#: ``FileNotFoundError`` for a missing ``prior_csv``.
_PER_LEAGUE_EXCEPTIONS = (SleeperAPIError, ValueError, KeyError, FileNotFoundError)

_ORDINAL_SUFFIXES = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(n: int) -> str:
    """Render an integer as an ordinal, e.g. ``3`` -> ``"3rd"``."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = _ORDINAL_SUFFIXES.get(n % 10, "th")
    return f"{n}{suffix}"


def _grade_badge_class(letter: Optional[str]) -> str:
    """Map a letter grade to the CSS class coloring its badge.

    A/A+/B/B+ -> teal (good), C/C+ -> amber (mid), D/F -> clay (bad),
    ``None`` (ungraded) -> a distinct neutral state.
    """
    if letter is None:
        return "grade-none"
    if letter in ("A+", "A", "B+", "B"):
        return "grade-good"
    if letter in ("C+", "C"):
        return "grade-mid"
    return "grade-bad"


def load_prior_draft(prior_draft_csv: Optional[Path]) -> Optional[pd.DataFrame]:
    """Load a completed season's normalized draft-picks CSV (FFA-085), if any.

    Unlike ``load_prior`` (required input to the draft board itself), this
    is an optional enhancement: a missing/absent path returns ``None``
    rather than raising, so a league without a fetched historical draft
    still gets a full report -- just without the points-value columns
    (:func:`~fantasy_analyzer.players.draft_points_value.
    fit_points_value_curve` treats a ``None``/empty frame identically to
    "no curve could be fit").

    Args:
        prior_draft_csv: Path to a ``fetch_season_draft_picks.py`` CSV, or
            ``None``.

    Returns:
        The frame with ``sleeper_player_id`` as ``str``, or ``None`` when
        no path was given or the file does not exist.
    """
    if prior_draft_csv is None:
        return None
    path = Path(prior_draft_csv)
    if not path.exists():
        return None
    draft = pd.read_csv(path)
    if "sleeper_player_id" in draft.columns:
        draft["sleeper_player_id"] = draft["sleeper_player_id"].astype(str)
    return draft


#: Draft-phase labels, in draft order -- see ``_pick_phase``.
_PHASE_LABELS = ("Early", "Mid", "Late")


def _pick_phase(round_no: Any, num_rounds: int) -> Optional[str]:
    """Bucket a 1-indexed ``round`` into the early/mid/late third of the draft.

    A simple, league-size-agnostic split: round 1 of a 15-round draft and
    round 1 of a 16-round draft both land in "Early" (fraction 0/15 vs
    0/16, both ``< 1/3``). ``None`` if ``round_no``/``num_rounds`` is
    missing or non-positive.
    """
    if round_no is None or pd.isna(round_no) or num_rounds <= 0:
        return None
    fraction = (int(round_no) - 1) / num_rounds
    if fraction < 1 / 3:
        return "Early"
    if fraction < 2 / 3:
        return "Mid"
    return "Late"


def build_points_value_team_summary(
    points_value_df: pd.DataFrame, num_rounds: int
) -> dict[Any, dict[str, Any]]:
    """Per-team display aggregates answering "why is this grade what it is."

    Pure presentation-layer aggregation of already-computed, already-tested
    numbers (``draft_grade.py``'s ``pick_value`` and
    ``draft_points_value.py``'s ``projected_points_value``/
    ``pick_value_points``) -- not a new metric definition in its own right,
    so it lives in the script layer rather than the core ``players``
    package, the same "thin composition" convention this module's own
    docstring already claims for the rest of its glue code.

    For each ``roster_id`` present in ``points_value_df``:

    - ``total_points_value``: sum of ``projected_points_value`` over every
      pick with a defined value (keepers included -- this describes the
      roster the team ended up with, not a draft-day decision, the same
      distinction ``draft_grade.py`` draws for ``draft_score``/``tier`` on
      a keeper row). ``None`` if no pick has a defined value.
    - ``phases``: one entry per :data:`_PHASE_LABELS`, each
      ``{"phase", "n", "avg_pick_value", "avg_pick_value_points"}`` --
      restricted to the scoreable, non-excluded filter
      ``draft_report.py``'s own module docstring defines (a keeper or an
      unscored pick counts toward roster construction, not toward "was
      this a good pick," the identical reasoning ``reach_count``/
      ``value_count`` already use there). ``avg_pick_value``/
      ``avg_pick_value_points`` are ``None`` for a phase with zero
      contributing picks or with picks but no defined values in it.
    """
    totals: dict[Any, float] = {}
    has_total: dict[Any, bool] = {}
    phase_picks: dict[Any, dict[str, list[Any]]] = {}

    for row in points_value_df.itertuples(index=False):
        roster_id = row.roster_id
        phase_picks.setdefault(roster_id, {label: [] for label in _PHASE_LABELS})

        ppv = getattr(row, "projected_points_value", None)
        if ppv is not None and not pd.isna(ppv):
            totals[roster_id] = totals.get(roster_id, 0.0) + ppv
            has_total[roster_id] = True

        unscored = getattr(row, "expected_pick_source", None) == "unscored"
        excluded = getattr(row, "excluded_reason", None) is not None
        if unscored or excluded:
            continue
        phase = _pick_phase(getattr(row, "round", None), num_rounds)
        if phase is None:
            continue
        phase_picks[roster_id][phase].append(row)

    result: dict[Any, dict[str, Any]] = {}
    for roster_id, phases_for_team in phase_picks.items():
        phases: list[dict[str, Any]] = []
        for label in _PHASE_LABELS:
            picks = phases_for_team[label]
            pv = [
                p.pick_value
                for p in picks
                if p.pick_value is not None and not pd.isna(p.pick_value)
            ]
            pvp = [
                p.pick_value_points
                for p in picks
                if p.pick_value_points is not None and not pd.isna(p.pick_value_points)
            ]
            phases.append(
                {
                    "phase": label,
                    "n": len(picks),
                    "avg_pick_value": (sum(pv) / len(pv)) if pv else None,
                    "avg_pick_value_points": (sum(pvp) / len(pvp)) if pvp else None,
                }
            )
        result[roster_id] = {
            "total_points_value": (
                totals.get(roster_id) if has_total.get(roster_id) else None
            ),
            "phases": phases,
        }
    return result


def merge_team_grades_and_talking_points(
    team_grades_df: pd.DataFrame, talking_points_df: pd.DataFrame
) -> pd.DataFrame:
    """Combine FFA-079's team grades with FFA-080's talking points.

    ``team_grades_df`` is the base (it already carries every column the two
    frames share -- ``roster_id``, ``team_name``, ``grade_letter``,
    ``draft_rank``, ``total_vor``, ``avg_pick_value``, ``best_pick_*``,
    ``worst_pick_*``, ``unscored_pick_count``); only
    :data:`_EXTRA_TALKING_POINT_COLUMNS` (the columns talking points adds
    that team grades does not have) are joined on, on ``roster_id``. This
    avoids both duplicating shared columns and a naive outer join that
    would suffix every shared column.

    Returns:
        A DataFrame with columns :data:`TEAM_GRADE_REPORT_COLUMNS`. Empty
        (with the same columns) if ``team_grades_df`` is empty.
    """
    if team_grades_df.empty:
        return pd.DataFrame(columns=TEAM_GRADE_REPORT_COLUMNS)

    extra = talking_points_df[["roster_id", *_EXTRA_TALKING_POINT_COLUMNS]]
    merged = team_grades_df.merge(extra, on="roster_id", how="left")
    return merged[TEAM_GRADE_REPORT_COLUMNS]


def _fmt(value: Any, digits: int = 2) -> str:
    """Render a possibly-missing numeric value, or an em dash if missing."""
    if value is None:
        return "—"
    try:
        if pd.isna(value):
            return "—"
    except (TypeError, ValueError):
        pass
    return f"{float(value):.{digits}f}"


def _pick_line(
    label: str, player: Any, round_: Any, pick_no: Any, value: Any
) -> str:
    """Render one "best pick" / "worst pick" line for a team card."""
    if player is None or (isinstance(player, float) and pd.isna(player)):
        return (
            f'<div class="pickline"><span class="lbl">{html.escape(label)}</span>'
            '<span class="who">—</span><span class="val"></span></div>'
        )
    where = ""
    if round_ is not None and not pd.isna(round_):
        where = f" (rd {int(round_)}"
        if pick_no is not None and not pd.isna(pick_no):
            where += f", pick {int(pick_no)}"
        where += ")"
    is_positive = value is not None and not pd.isna(value) and value >= 0
    val_cls = "up" if is_positive else "down"
    return (
        f'<div class="pickline"><span class="lbl">{html.escape(label)}</span>'
        f'<span class="who">{html.escape(str(player))}{html.escape(where)}</span>'
        f'<span class="val {val_cls}">{_fmt(value, 1)}</span></div>'
    )


def _position_counts_html(position_counts: Any) -> str:
    """Render a team's ``position_counts`` dict as a simple bar list."""
    if not isinstance(position_counts, dict) or not position_counts:
        return '<p class="ungraded-note">No picks recorded.</p>'
    max_count = max(position_counts.values())
    order = sorted(position_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    rows = []
    for position, count in order:
        width = round(count / max_count * 100) if max_count else 0
        rows.append(
            "<li>"
            f'<span class="pos">{html.escape(str(position))}</span>'
            f'<span class="track"><span style="width:{width}%"></span></span>'
            f'<span class="n">{count}</span>'
            "</li>"
        )
    return '<ul class="posbar">' + "".join(rows) + "</ul>"


def _phase_breakdown_html(phases: Optional[list[dict[str, Any]]]) -> str:
    """Render a team's early/mid/late round-phase value breakdown.

    ``avg_pick_value_points`` (real, projected-points-scale) is the primary
    number shown per phase -- this directly answers "which part of the
    draft actually moved this team's projected scoring," the explanation
    ``pick_value`` alone (a market-relative, not points-scale, number)
    cannot give on its own. ``avg_pick_value`` (the board's own
    market-relative scale) is shown as a smaller secondary figure.
    """
    if not phases:
        return ""
    rows = []
    for phase in phases:
        n = phase.get("n", 0)
        pvp = phase.get("avg_pick_value_points")
        pv = phase.get("avg_pick_value")
        has_pvp = pvp is not None and not pd.isna(pvp)
        cls = "up" if (has_pvp and pvp >= 0) else ("down" if has_pvp else "")
        primary = _fmt(pvp, 1) if has_pvp else "—"
        has_pv = pv is not None and not pd.isna(pv)
        secondary = (
            f' <span class="ph-sub">({_fmt(pv, 2)} board)</span>' if has_pv else ""
        )
        rows.append(
            '<li><span class="ph-lbl">'
            f'{html.escape(str(phase.get("phase", "")))}'
            f'<span class="ph-n">{n} pk</span></span>'
            f'<span class="ph-val {cls}">{primary}{secondary}</span></li>'
        )
    return (
        '<div class="phase-breakdown">'
        '<p class="phase-title">Value by draft phase '
        '<span class="ph-hint">(proj. real-points value, avg/pick)</span></p>'
        f'<ul class="phase-list">{"".join(rows)}</ul>'
        "</div>"
    )


def build_team_card(
    row: dict[str, Any], points_summary: Optional[dict[str, Any]] = None
) -> str:
    """Render one team's grade card, including its commentary placeholder.

    The commentary paragraph is written as a literal
    ``{{COMMENTARY_ROSTER_<roster_id>}}`` token -- see the module
    docstring's FFA-083 section. It is emitted here, not filled in, because
    no prose is generated by this script.

    ``points_summary`` is this team's entry from
    :func:`build_points_value_team_summary` (``None`` when no points-value
    curve could be fit for this league -- the card degrades gracefully,
    simply omitting the points-value stat and phase breakdown).
    """
    roster_id = row["roster_id"]
    team_name = html.escape(str(row["team_name"]))
    letter = row["grade_letter"]
    badge_class = _grade_badge_class(letter)
    badge_text = html.escape(letter) if letter is not None else "N/A"

    draft_rank = row["draft_rank"]
    num_teams = row.get("num_teams")
    if draft_rank is not None and not pd.isna(draft_rank) and num_teams:
        rank_line = f"{_ordinal(int(draft_rank))} of {int(num_teams)}"
    else:
        rank_line = "unranked"

    body_parts: list[str] = []
    if letter is None:
        body_parts.append(
            '<p class="ungraded-note">Not enough scoreable picks to grade '
            "this team's draft (e.g. an all-keeper roster, or no picks "
            "matched the market board).</p>"
        )

    body_parts.append(
        _pick_line(
            "Best",
            row.get("best_pick_player"),
            row.get("best_pick_round"),
            row.get("best_pick_pick_no"),
            row.get("best_pick_value"),
        )
    )
    body_parts.append(
        _pick_line(
            "Worst",
            row.get("worst_pick_player"),
            row.get("worst_pick_round"),
            row.get("worst_pick_pick_no"),
            row.get("worst_pick_value"),
        )
    )

    total_vor_stat = f'<b>{_fmt(row.get("total_vor"))}</b>'
    avg_value_stat = f'<b>{_fmt(row.get("avg_pick_value"), 1)}</b>'
    reach_stat = f'<b>{row.get("reach_count", "—")}</b>'
    value_stat = f'<b>{row.get("value_count", "—")}</b>'
    unscored_stat = f'<b>{row.get("unscored_pick_count", "—")}</b>'
    stat_spans = [
        f'<span class="stat">Total VOR<br>{total_vor_stat}</span>',
        f'<span class="stat">Avg pick value<br>{avg_value_stat}</span>',
        f'<span class="stat">Reaches<br>{reach_stat}</span>',
        f'<span class="stat">Values<br>{value_stat}</span>',
        f'<span class="stat">Unscored<br>{unscored_stat}</span>',
    ]
    if points_summary is not None:
        total_points_value = points_summary.get("total_points_value")
        total_points_stat = f"<b>{_fmt(total_points_value, 1)}</b>"
        stat_spans.append(
            f'<span class="stat">Proj. pts value<br>{total_points_stat}</span>'
        )
    body_parts.append('<div class="stat-row">' + "".join(stat_spans) + "</div>")

    body_parts.append(_position_counts_html(row.get("position_counts")))

    if points_summary is not None:
        body_parts.append(_phase_breakdown_html(points_summary.get("phases")))

    body_parts.append(
        f'<p class="commentary" '
        f'data-roster-id="{roster_id}">'
        f"{{{{COMMENTARY_ROSTER_{roster_id}}}}}</p>"
    )

    return (
        '<article class="grade-card">'
        "<header>"
        f'<span class="grade-badge {badge_class}">{badge_text}</span>'
        '<span class="team-id">'
        f"<h3>{team_name}</h3>"
        f'<span class="rank">Draft rank: {html.escape(rank_line)}</span>'
        "</span>"
        "</header>"
        f'<div class="body">{"".join(body_parts)}</div>'
        "</article>"
    )


def build_team_cards(
    merged_df: pd.DataFrame,
    points_summary_by_roster: Optional[dict[Any, dict[str, Any]]] = None,
) -> str:
    """Render every team's card, in the frame's existing (ranked) order."""
    points_summary_by_roster = points_summary_by_roster or {}
    return "\n".join(
        build_team_card(row, points_summary_by_roster.get(row["roster_id"]))
        for row in merged_df.to_dict(orient="records")
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="draft_report_2026.py",
        description=(
            "Grade a completed 2026 draft (FFA-077..080) for one or more "
            "leagues and render a per-team HTML report. See the module "
            "docstring for the manual FFA-083 commentary step this script "
            "does not perform."
        ),
    )
    parser.add_argument(
        "--league",
        action="append",
        choices=sorted(LEAGUES),
        default=None,
        help=(
            "Known league slug from draft_league_presets.LEAGUES; supplies "
            "teams/rounds/scoring/roster_positions/prior_csv/out_prefix. "
            "Repeatable -- pair each with a --league-id in the same "
            "position. Omit both --league and --league-id to run every "
            "preset league."
        ),
    )
    parser.add_argument(
        "--league-id",
        action="append",
        default=None,
        help=(
            "Sleeper league_id for the matching --league (same position in "
            "the argument list). Required whenever --league is given, "
            "since draft_league_presets.LEAGUES itself carries no real "
            "Sleeper league_id (see module docstring). Example: "
            "--league nwc --league-id 1257477810625196032"
        ),
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument(
        "--market-refresh",
        action="store_true",
        help=(
            "Force a fresh market-data pull instead of using the cache "
            "(rarely wanted for a post-draft grade -- see module "
            "docstring; this default is the OPPOSITE of "
            "draft_board_artifact.py/draft_guide_2026.py's "
            "--no-market-refresh)."
        ),
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("scripts/output/draft2026")
    )
    parser.add_argument(
        "--out-prefix",
        default=None,
        help=(
            "Override every selected league's out_prefix. Only sensible "
            "for a single-league run -- running multiple leagues with the "
            "same --out-prefix makes each overwrite the previous one's "
            "files."
        ),
    )
    return parser


def resolve_config(slug: str, args: argparse.Namespace) -> dict[str, Any]:
    """Look up ``slug``'s preset in ``LEAGUES``, applying CLI overrides.

    Raises:
        SystemExit: If ``slug`` has no entry in ``LEAGUES``.
    """
    if slug not in LEAGUES:
        raise SystemExit(
            f"Unknown league slug {slug!r}. Known slugs: {sorted(LEAGUES)}."
        )
    cfg = dict(LEAGUES[slug])
    if args.out_prefix:
        cfg["out_prefix"] = args.out_prefix
    if cfg.get("prior_csv"):
        cfg["prior_csv"] = Path(cfg["prior_csv"])
    return cfg


def _resolve_leagues(
    args: argparse.Namespace,
) -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``[(slug, league_id, cfg), ...]`` for the leagues to run.

    Defaults to every preset in ``LEAGUES`` when both ``--league`` and
    ``--league-id`` are omitted. Raises ``SystemExit`` if the two flags were
    repeated a different number of times.
    """
    if not args.league and not args.league_id:
        slugs = sorted(LEAGUES)
        league_ids = [LEAGUES[slug]["league_id"] for slug in slugs]
    else:
        slugs = args.league or []
        league_ids = args.league_id or []
        if len(slugs) != len(league_ids):
            raise SystemExit(
                f"--league and --league-id must be repeated the same "
                f"number of times: got {len(slugs)} --league value(s) but "
                f"{len(league_ids)} --league-id value(s)."
            )
    return [
        (slug, league_id, resolve_config(slug, args))
        for slug, league_id in zip(slugs, league_ids)
    ]


def run_one_league(
    client: SleeperClient,
    slug: str,
    league_id: str,
    cfg: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Run the FFA-077..080 pipeline for one league and write its artifacts.

    Returns:
        A dict describing what was written --
        ``{"slug", "league_id", "league_title", "stem", "picks_path",
        "grades_path", "html_path", "team_grades", "n_teams"}`` --
        ``team_grades`` is the merged :data:`TEAM_GRADE_REPORT_COLUMNS`
        frame (used by the caller to build the cross-league leaderboard).
    """
    teams = int(cfg["teams"])

    snapshot = load_league_snapshot(client, league_id)
    raw_draft, raw_picks = load_league_draft(client, league_id)
    picks_df = build_normalized_draft_picks(
        raw_picks,
        snapshot.teams_df,
        season=args.season,
        league_id=league_id,
        draft_id=raw_draft["draft_id"],
    )

    market = get_draft_market_player_pool_cached(
        args.season,
        teams=teams,
        scoring=cfg["scoring"],
        force_refresh=args.market_refresh,
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

    scored_picks = score_draft_picks(picks_df, board)
    team_grades = build_team_draft_grades(scored_picks)
    talking_points = build_draft_talking_points(team_grades, scored_picks)
    merged = merge_team_grades_and_talking_points(team_grades, talking_points)

    # FFA-085: a real-points-scale value curve, fit from this league's own
    # prior completed season (its own draft + realized production). Purely
    # additive -- curve=None (no prior_draft_csv, or too little history to
    # fit) degrades every points-value figure to "not shown," it never
    # blocks the FFA-078/079/080 grade itself.
    prior_draft = load_prior_draft(cfg.get("prior_draft_csv"))
    curve = (
        fit_points_value_curve(prior_draft, prior) if prior_draft is not None else None
    )
    points_value = score_points_value(scored_picks, board, curve)
    points_summary = build_points_value_team_summary(points_value, int(cfg["rounds"]))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{cfg['out_prefix']}_{args.season}_draft_report"

    picks_path = args.out_dir / f"{stem}_picks_scored.csv"
    points_value[POINTS_VALUE_PICK_COLUMNS].to_csv(picks_path, index=False)

    grades_path = args.out_dir / f"{stem}_team_grades.csv"
    grades_out = merged.copy()
    grades_out["position_counts"] = grades_out["position_counts"].apply(
        lambda d: json.dumps(d) if isinstance(d, dict) else d
    )
    grades_out.to_csv(grades_path, index=False)

    html_path = args.out_dir / f"{stem}_artifact.html"
    html_path.write_text(_build_html(cfg, args, merged, points_summary, curve))

    curve_note = (
        f", points curve n={curve.n_picks} r2={curve.r_squared:.2f}"
        if curve is not None
        else ", no points curve"
    )
    print(
        f"{cfg['title']}: {len(scored_picks)} picks -> {picks_path}, "
        f"{len(merged)} teams -> {grades_path}, artifact -> {html_path}"
        f"{curve_note}"
    )

    return {
        "slug": slug,
        "league_id": league_id,
        "league_title": cfg["title"],
        "stem": stem,
        "picks_path": picks_path,
        "grades_path": grades_path,
        "html_path": html_path,
        "team_grades": merged,
        "n_teams": len(merged),
    }


def _build_html(
    cfg: dict[str, Any],
    args: argparse.Namespace,
    merged: pd.DataFrame,
    points_summary: Optional[dict[Any, dict[str, Any]]] = None,
    curve: Optional[PointsValueCurve] = None,
) -> str:
    """Render the per-league artifact HTML page."""
    facts = [
        ("Season", str(args.season)),
        ("Teams", str(int(cfg["teams"]))),
        ("Format", cfg.get("scoring_label") or cfg["scoring"]),
    ]
    mast_facts = "\n".join(
        f'    <div class="fact"><dt>{html.escape(k)}</dt>'
        f'<dd>{html.escape(v)}</dd></div>'
        for k, v in facts
    )

    n_graded = int(merged["grade_letter"].notna().sum()) if not merged.empty else 0
    footer = (
        f"{len(merged)} teams, {n_graded} graded. Board: 2026 market "
        "(FantasyFootballCalculator ADP + FantasyPros ECR) blended with "
        "this league's own 2025 retrospective value -- see draft_board.py."
    )
    if curve is not None:
        footer += (
            f" Points value: a real-points curve fit from this league's own "
            f"{curve.n_picks}-pick 2025 draft (R²={curve.r_squared:.2f} -- "
            "a rough, single-season estimate, not a precise projection) -- "
            "see draft_points_value.py."
        )

    data = {
        "teams": [
            {
                "team_name": row["team_name"],
                "roster_id": row["roster_id"],
                "overall_z": _optional_json_float(row.get("overall_z")),
                "grade_letter": row.get("grade_letter"),
            }
            for row in merged.to_dict(orient="records")
        ]
    }

    template = TEMPLATE_PATH.read_text()
    title = f"{cfg['short_title']} {args.season} Draft Report"
    return (
        template.replace("{{TITLE}}", html.escape(title))
        .replace(
            "{{EYEBROW}}",
            f"{html.escape(cfg['title'])} &middot; {args.season} draft report",
        )
        .replace("{{HEADLINE}}", "Draft grade report")
        .replace("{{MAST_FACTS}}", mast_facts)
        .replace("{{FOOTER}}", html.escape(footer))
        .replace("{{TEAM_CARDS}}", build_team_cards(merged, points_summary))
        .replace("{{DATA}}", json.dumps(data))
    )


def _optional_json_float(value: Any) -> Optional[float]:
    """``float(value)`` unless missing, in which case ``None`` (JSON ``null``)."""
    try:
        if value is None or pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    leagues = _resolve_leagues(args)

    client = SleeperClient()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    leaderboard_rows: list[dict[str, Any]] = []
    succeeded = 0
    for slug, league_id, cfg in leagues:
        try:
            result = run_one_league(client, slug, league_id, cfg, args)
        except _PER_LEAGUE_EXCEPTIONS as exc:
            print(
                f"Error building draft report for {cfg['title']} "
                f"({slug}, league_id={league_id}): {exc}",
                file=sys.stderr,
            )
            continue

        succeeded += 1
        for row in result["team_grades"].to_dict(orient="records"):
            leaderboard_rows.append(
                {
                    "league": result["league_title"],
                    "team_name": row["team_name"],
                    "grade_letter": row["grade_letter"],
                    "overall_z": row["overall_z"],
                    "draft_rank": row["draft_rank"],
                }
            )

    leaderboard_path = args.out_dir / "combined_leaderboard.csv"
    pd.DataFrame(leaderboard_rows, columns=COMBINED_LEADERBOARD_COLUMNS).to_csv(
        leaderboard_path, index=False
    )
    print(
        f"Combined leaderboard: {len(leaderboard_rows)} teams across "
        f"{succeeded} of {len(leagues)} league(s) -> {leaderboard_path}"
    )

    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
