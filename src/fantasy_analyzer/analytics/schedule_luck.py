"""Expected wins and schedule luck from a single season matchup frame (FFA-052).

Compares what a roster's record **was** against what its scoring strength
says it **should have been**, and calls the gap schedule luck. The scoring
strength comes from FFA-051's all-play win percentage (how often the roster
would have beaten a randomly-drawn opponent each week); the actual record
comes from FFA-034's :func:`
~fantasy_analyzer.matchups.reconciliation.derive_roster_totals`. This module
performs no network access; it operates entirely on an already-built
``season_matchup_df``.

AGENTS.md's worked example is the reference case::

    Actual Record:     8-6
    Expected Record:  10.0-4.0
    Schedule Luck:    -2.0 wins

i.e. a roster that played 14 games, went 8-6, but had an
``all_play_win_pct`` of ``10 / 14 = 0.714285...`` -- strong enough scoring to
"deserve" ten wins. The two-win shortfall is charged to its schedule.
``tests/analytics/test_schedule_luck.py``'s
``test_agents_md_worked_example`` reproduces exactly these numbers from a
hand-built 8-roster, 14-week season.

Actual record and all-play record must cover the same games
-------------------------------------------------------------

The single most dangerous way to get this metric wrong is to compare an
actual record and an all-play record that were computed over **different
sets of games**. FFA-051's author hit precisely this while validating
against live 2025 leagues: Sleeper's cumulative ``wins``/``losses`` counters
cover the 14 regular-season games, while the all-play table built there
covered all 18 loaded weeks, so ``win_pct - all_play_win_pct`` silently
compared unlike periods. The resulting "luck" number is not a small error;
it is meaningless.

This module is therefore designed so that mistake is **structurally
impossible for its caller**, not merely warned about.
:func:`build_schedule_luck` takes one shared input -- ``season_matchup_df``
-- and builds *both* halves of the comparison from it:

- the **actual** side by calling ``derive_roster_totals(season_matchup_df)``
  (imported and reused, not reimplemented);
- the **all-play** side by chaining
  ``build_weekly_scoring_ranks(season_matchup_df, teams_df)`` into
  ``build_all_play_standings(...)`` on the *same* frame.

There is no parameter through which a caller can hand in a pre-built,
independently-filtered table for either half, and Sleeper's season-cumulative
roster counters are never consulted. Whatever rows the caller passes define
both sides at once.

The consequence for callers is a single rule:

    Pass ``season_matchup_df[season_matchup_df["is_playoff"] == False]`` for
    a regular-season-only view. Do **not** build the two halves from
    separately-filtered frames -- there is no supported way to do so here,
    and doing it by hand outside this module reintroduces the phase-mismatch
    bug.

Metric definitions
-------------------

For each roster, over whatever rows of ``season_matchup_df`` were passed in:

- **games_played** -- ``wins + losses + ties`` from
  :func:`~fantasy_analyzer.matchups.reconciliation.derive_roster_totals`:
  the number of weeks in which the roster had a genuine head-to-head
  decision. See "Games played is decisions, not weeks" below for why this,
  and not the all-play table's ``weeks_played``, is the denominator.
- **win_pct** -- ``(wins + 0.5 * ties) / games_played``, the same formula
  and the same "half credit for a tie" convention as ``standings.py``'s
  ``win_pct`` and ``all_play.py``'s ``all_play_win_pct``, so all three are
  directly comparable.
- **all_play_win_pct** -- carried through unchanged from
  :func:`~fantasy_analyzer.analytics.all_play.build_all_play_standings`:
  ``(all_play_wins + 0.5 * all_play_ties) / all_play_games`` over every
  pairwise comparison the roster took part in.
- **expected_wins** -- ``all_play_win_pct * games_played``. The roster plays
  the same number of games it really played, but each one is won at its
  schedule-independent rate rather than against its actual opponent.
- **expected_losses** -- ``games_played - expected_wins``.
- **schedule_luck** -- ``(wins + 0.5 * ties) - expected_wins``, equivalently
  ``(win_pct - all_play_win_pct) * games_played``. Measured in wins.

Sign convention: **positive = lucky**, negative = unlucky. A positive
``schedule_luck`` means the roster's actual record *over*-performed its
scoring strength (a favorable schedule -- it kept drawing opponents it could
beat, or its big scores landed in weeks it needed them). A negative value
means it *under*-performed (a punishing schedule). AGENTS.md's example is
negative: an 8-6 record where the scoring deserved 10-4 is ``8 - 10.0 =
-2.0``, two wins the schedule took away. The league-wide sum of
``schedule_luck`` is approximately (not exactly) zero -- exactly zero only
when every roster played every week, since a roster absent from a week
neither takes nor gives luck in it.

Why ``expected_losses = games_played - expected_wins``
--------------------------------------------------------

The algebraic alternative ``(1 - all_play_win_pct) * games_played`` is
identical in exact arithmetic. Subtracting is preferred because it
guarantees the invariant ``expected_wins + expected_losses ==
games_played`` holds in floating point too, so a printed expected record
always adds up to the season length.

Note what this implies for ties: an expected record has a wins component and
a losses component but **no ties component**. All-play ties are already
folded into ``all_play_win_pct`` as half a win, so half of each expected tie
lands in ``expected_wins`` and half in ``expected_losses``. A roster whose
expected record is ``10.0-4.0`` is not being claimed to have zero expected
ties; ties are simply not a separate bucket in this metric.

Why the actual side is ``wins + 0.5 * ties``, not raw ``wins``
-----------------------------------------------------------------

``expected_wins`` is derived from a rate that gives a tie half credit, so
the actual quantity it is subtracted from must give a tie half credit too;
otherwise a roster is charged with bad luck purely for having tied a game.
Concretely, a roster that went 7-6-1 with an ``all_play_win_pct`` of exactly
0.5 has ``expected_wins = 7.0``. Using raw ``wins`` would report
``schedule_luck = 0.0`` for it while reporting the same ``0.0`` for a 7-7-0
roster with the same rate -- but the 7-6-1 roster genuinely did half a win
better than 7-7-0. With half credit it correctly reports ``+0.5``.

AGENTS.md's example (8-6, no ties) does not distinguish the two conventions:
``8 + 0.5 * 0 == 8``. The choice only ever matters for a roster with a real
tie, which is rare in fantasy football but not impossible. The column
``win_pct`` makes the convention visible without adding a redundant
``actual_wins_equivalent`` column: ``win_pct * games_played`` *is* the actual
side of the subtraction.

Games played is decisions, not weeks
---------------------------------------

``games_played`` deliberately comes from the actual side
(``wins + losses + ties``) rather than from the all-play side's
``weeks_played``. For a well-formed frame in which every week produces both
a score and an outcome the two coincide, but they diverge on **bye weeks**,
and the divergence matters:

- ``derive_roster_totals`` credits a bye row (``roster_2_id is None``) with
  ``points_for`` only -- no win, no loss, no tie -- so a bye does **not**
  count toward ``games_played``.
- ``build_all_play_standings`` *does* count a bye as a ``weeks_played`` and
  does compare that week's score against every other roster, because a bye
  is a real score.

Both behaviors are correct for their own metric, and combining them the way
this module does is also correct: the bye week's score still informs *how
good* the roster is (it is in the ``all_play_win_pct`` numerator and
denominator), but there was no opponent to beat that week, so it cannot add
an expected win. "Expected wins" over a week with no head-to-head decision
is not a smaller number, it is a meaningless one. A roster with 13 played
weeks and 1 bye therefore gets ``expected_wins = all_play_win_pct * 13``,
and its luck is measured against the 13 decisions it actually had.

Missing values / edge cases
----------------------------

- **Empty ``season_matchup_df``**: returns an empty DataFrame with
  :data:`SCHEDULE_LUCK_COLUMNS`.
- **A roster with ``games_played == 0``** -- no row. This covers a roster
  absent from the frame entirely, and a roster present only in rows that
  produced no decision (byes, or matchups with missing points). It follows
  the precedent set by ``derive_roster_totals`` ("a roster with zero matchup
  rows is absent") and ``build_all_play_standings`` ("a roster with no scored
  week is absent"): a per-game rate over zero games is undefined, not
  ``0.0``, and emitting a ``0.0-0.0`` expected record invites a reader to
  see a real result in a roster that never played. The most common way to
  hit this deliberately is filtering to ``is_playoff == True``: every roster
  eliminated before the playoffs simply drops out.
- **A bye-only roster** -- the specific case where the two halves disagree:
  it has ``weeks_played > 0`` on the all-play side (a bye is a real score,
  and it may even have a strong ``all_play_win_pct``) but ``wins + losses +
  ties == 0`` on the actual side. It gets **no row**, by the zero-games rule
  above. Its scores still count in *other* rosters' ``all_play_win_pct``,
  since it was part of those weeks' comparison fields -- it is excluded from
  the output, not from the league.
- **Ties** are handled on both sides: half credit in ``win_pct`` and in
  ``all_play_win_pct`` (see above), and shared ranks in both rank columns.
- **A roster with ``games_played > 0`` but no all-play row** cannot arise
  from the real pipeline: :mod:`~fantasy_analyzer.matchups.outcomes` only
  sets ``winner``/``loser``/``is_tie`` when both sides' points are present,
  and any row with present points produces an all-play row. A hand-built
  frame can violate that (e.g. a ``winner`` set on a row with no points), in
  which case :func:`build_schedule_luck` raises ``ValueError`` rather than
  guessing a scoring strength for a roster that has no recorded score. This
  mirrors ``weekly_scores.py``'s decision to raise on a data-integrity
  anomaly with no correct interpretation.
- **A roster with ``all_play_games == 0``** cannot appear in this output.
  ``all_play.py``'s zero-comparison case needs a week whose field size is
  one, but a *decided* game requires two scored rosters in that week, so
  every roster this module emits has at least one all-play comparison and
  ``all_play.py``'s ``all_play_win_pct = 0.0`` zero-denominator fallback is
  never the value carried through here. (A roster whose only weeks had a
  field size of one has no decided game at all and is dropped by the
  zero-games rule above.)
- **Multiple seasons in one frame** are summed into a single row per roster,
  inheriting that behavior from both upstream functions; filter by
  ``season`` first for per-season luck.

Ranking rule
------------

``schedule_luck_rank`` orders rosters by **descending** ``schedule_luck``,
so ``rank = 1`` is the **luckiest** roster, not the "best" one -- the one
whose record most exceeded its scoring. This is worth stating plainly
because, unlike ``standings.py``'s ``rank`` or ``all_play.py``'s
``all_play_rank``, rank 1 here is not a compliment.

Ranking uses standard competition ("1224") ranking on ``schedule_luck``
alone, the same convention as every other rank column in this package: tied
values share a rank and the next distinct rank skips the tied count.
Equality is exact float equality; two rosters with identical records and
identical all-play rates reach the same float through the same code path, so
this is reliable in the cases that matter. Rows are *ordered* by descending
``schedule_luck`` then ascending ``roster_id``, but that ``roster_id``
tiebreak is display order only and is not reflected in the rank.

``all_play_rank`` is carried through unchanged from
``build_all_play_standings``, where it is computed over that function's full
roster set. A roster dropped here for having zero games played is **not**
re-ranked out of it, so ``all_play_rank`` values in this frame may skip
numbers. That is deliberate: the column means "rank among every roster that
scored", and silently renumbering it would make it disagree with the
all-play table a caller may also be holding.

Regular season vs. playoffs
------------------------------

This function applies **no** ``is_playoff`` filter and makes no phase
distinction of its own -- it computes a single combined result over every
row it is given, matching FFA-040/FFA-042/FFA-050/FFA-051's established
precedent. ``is_playoff`` is not carried into the output, since a
season-total row spans both phases.

Filtering is the caller's job, and per the "Actual record and all-play
record must cover the same games" section above, filtering
``season_matchup_df`` *before* the call is both the only supported way to do
it and automatically consistent across both halves of the calculation. The
conventional and most meaningful view is regular-season-only: playoff
brackets are seeded, not scheduled, so "luck" over playoff weeks measures
something different.
"""

from __future__ import annotations

import pandas as pd

from fantasy_analyzer.analytics.all_play import build_all_play_standings
from fantasy_analyzer.analytics.weekly_scores import build_weekly_scoring_ranks
from fantasy_analyzer.matchups.reconciliation import derive_roster_totals

#: Column order for the DataFrame returned by :func:`build_schedule_luck`.
SCHEDULE_LUCK_COLUMNS = [
    "roster_id",
    "owner",
    "games_played",
    "wins",
    "losses",
    "ties",
    "win_pct",
    "all_play_games",
    "all_play_win_pct",
    "all_play_rank",
    "expected_wins",
    "expected_losses",
    "schedule_luck",
    "schedule_luck_rank",
]


def _win_pct(wins: float, losses: float, ties: float) -> float:
    """Compute win percentage, returning ``0.0`` at zero games.

    ``(wins + 0.5 * ties) / (wins + losses + ties)`` -- the same formula and
    the same zero-denominator rule as
    :func:`fantasy_analyzer.analytics.standings._win_pct`, reimplemented here
    rather than imported so this module does not depend on another module's
    private helper (the same choice ``weekly_scores.py`` and ``all_play.py``
    already made).

    In practice the zero-games branch is unreachable from
    :func:`build_schedule_luck`, which drops zero-game rosters before calling
    this; it is kept so the helper is total.
    """
    games = wins + losses + ties
    if games == 0:
        return 0.0
    return (wins + 0.5 * ties) / games


def build_schedule_luck(
    season_matchup_df: pd.DataFrame, teams_df: pd.DataFrame
) -> pd.DataFrame:
    """Build one row per roster of expected wins and schedule luck.

    Derives both halves of the comparison from the same
    ``season_matchup_df``: the actual record via
    :func:`~fantasy_analyzer.matchups.reconciliation.derive_roster_totals`,
    and the schedule-independent all-play rate via
    :func:`~fantasy_analyzer.analytics.weekly_scores.build_weekly_scoring_ranks`
    chained into
    :func:`~fantasy_analyzer.analytics.all_play.build_all_play_standings`.
    Because there is only one input frame, the two halves always cover the
    same set of games -- see the module docstring for why that matters, for
    the exact expected-wins and schedule-luck formulas, the sign convention,
    the ``games_played`` (decisions, not weeks) denominator, and the
    zero-game/bye-only edge cases.

    Args:
        season_matchup_df: A ``SEASON_MATCHUP_COLUMNS``-shaped DataFrame, as
            produced by
            :func:`~fantasy_analyzer.matchups.season_matchups.build_season_matchup_df`.
            Filter it to ``is_playoff == False`` *before* calling for the
            conventional regular-season-only view; this function applies no
            phase filter of its own.
        teams_df: A ``LeagueSnapshot.teams_df``-shaped DataFrame with at
            least ``["roster_id", "display_name"]``, used only to resolve the
            ``owner`` label.

    Returns:
        A DataFrame with columns :data:`SCHEDULE_LUCK_COLUMNS`, one row per
        roster with at least one decided game in the input, sorted by
        descending ``schedule_luck`` then ascending ``roster_id``.
        ``schedule_luck_rank`` is 1-indexed standard competition ranking with
        ``1`` the **luckiest** roster. A roster with zero decided games
        (including a bye-only roster) is absent. Returns an empty DataFrame
        with the expected columns if ``season_matchup_df`` is empty or no
        roster has a decided game. A roster whose ``owner`` is unresolved
        stays ``None`` rather than raising.

    Raises:
        ValueError: If a roster has decided games but no all-play row -- an
            internally inconsistent input (a win recorded for a roster with
            no score); see the module docstring's "Missing values / edge
            cases" section.
    """
    if season_matchup_df.empty:
        return pd.DataFrame(columns=SCHEDULE_LUCK_COLUMNS)

    # Both halves are built from the same frame -- this is the whole point of
    # the single-input design; see the module docstring.
    actual_totals = derive_roster_totals(season_matchup_df)
    all_play = build_all_play_standings(
        build_weekly_scoring_ranks(season_matchup_df, teams_df)
    )

    all_play_by_roster = {
        int(row.roster_id): row for row in all_play.itertuples(index=False)
    }

    rows = []
    owners = []
    for totals in actual_totals.itertuples(index=False):
        roster_id = int(totals.roster_id)
        wins = int(totals.wins)
        losses = int(totals.losses)
        ties = int(totals.ties)
        games_played = wins + losses + ties

        # Zero decided games -> no row: a rate over zero games is undefined,
        # not 0.0. This is also where a bye-only roster drops out.
        if games_played == 0:
            continue

        all_play_row = all_play_by_roster.get(roster_id)
        if all_play_row is None:
            raise ValueError(
                f"roster_id {roster_id} has {games_played} decided game(s) but "
                "no all-play record -- it has a win/loss/tie on a matchup row "
                "with no points, so its scoring strength is unknown"
            )

        all_play_win_pct = float(all_play_row.all_play_win_pct)
        expected_wins = all_play_win_pct * games_played
        # Subtraction (rather than (1 - pct) * games) so that
        # expected_wins + expected_losses == games_played exactly.
        expected_losses = games_played - expected_wins
        win_pct = _win_pct(wins, losses, ties)

        rows.append(
            {
                "roster_id": roster_id,
                "games_played": games_played,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_pct": win_pct,
                "all_play_games": int(all_play_row.all_play_games),
                "all_play_win_pct": all_play_win_pct,
                "all_play_rank": int(all_play_row.all_play_rank),
                "expected_wins": expected_wins,
                "expected_losses": expected_losses,
                # Half credit for a tie on the actual side too, to match the
                # convention baked into all_play_win_pct.
                "schedule_luck": (wins + 0.5 * ties) - expected_wins,
            }
        )
        owners.append(all_play_row.owner if pd.notna(all_play_row.owner) else None)

    # Every roster may have been dropped (e.g. a frame of byes only): return
    # an empty, correctly-shaped frame rather than letting pd.DataFrame([])
    # build a columnless frame.
    if not rows:
        return pd.DataFrame(columns=SCHEDULE_LUCK_COLUMNS)

    owner_by_roster = {row["roster_id"]: owner for row, owner in zip(rows, owners)}

    result = pd.DataFrame(rows)
    result = result.sort_values(
        by=["schedule_luck", "roster_id"], ascending=[False, True]
    ).reset_index(drop=True)

    # Standard competition ("1224") ranking on schedule_luck alone, luckiest
    # first: tied rosters share a rank and the next distinct rank skips the
    # tied count. The roster_id sort above is display order only and is not a
    # rank tiebreak -- see the module docstring's "Ranking rule" section.
    ranks = []
    current_rank = 0
    previous_key = None
    for position, key in enumerate(result["schedule_luck"], start=1):
        if key != previous_key:
            current_rank = position
            previous_key = key
        ranks.append(current_rank)
    result["schedule_luck_rank"] = ranks

    # ``owner`` is assigned as its own explicit ``dtype=object`` Series rather
    # than as a plain dict value inside ``rows``: pandas' newer default
    # string-dtype inference otherwise upcasts a column mixing real owner
    # names with ``None`` into a string dtype that silently turns ``None``
    # into ``NaN``, breaking the documented "unresolved owner -> ``None``"
    # contract (see ``all_play.py``/``weekly_scores.py``'s identical note).
    result["owner"] = pd.Series(
        [owner_by_roster[roster_id] for roster_id in result["roster_id"]],
        dtype=object,
    )
    return result[SCHEDULE_LUCK_COLUMNS]
