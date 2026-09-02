"""2026 draft board: blend market consensus with 2025 retrospective value (FFA-076).

This module answers one question a manager needs the night of a draft:
*given everything the market believes about 2026 and everything this
codebase measured about 2025, in what order should I take players, and
what does that order say relative to where the market expects them to
go?* It consumes two frames built by other modules and recomputes neither:

- **Input contract A -- 2026 market consensus** (built by a sibling ticket,
  ``draft_market.py``, not owned by this module): one row per
  ``sleeper_player_id`` with ``adp``/``adp_sd`` (FantasyFootballCalculator
  pick position, ~233 players) and ``ecr`` (FantasyPros redraft-overall
  consensus rank, ~517 players). Passed in as a plain DataFrame argument --
  this module makes no assumption about how it was fetched or cached.
- **Input contract B -- 2025 retrospective value**
  (:attr:`~fantasy_analyzer.players.player_analytics.PlayerAnalytics.player_ranking_df`,
  FFA-073): one row per ``sleeper_player_id`` for the 2025 NWC FFL league,
  carrying ``ranking_score`` (a five-component z-blend of realized
  production) and ``league_rank``.

Market is the base, not an equal partner -- read this before tuning weights
--------------------------------------------------------------------------

**The central methodological requirement of this ticket**: 2026 market
consensus (ADP/ECR) is the base signal, and 2025 retrospective value is an
*adjustment* on top of it, not a co-equal input. The reason is asymmetric
information, not a stylistic preference:

- 2025 realized production is completely blind to everything that changed
  since -- rookies (no NFL games exist for them), offseason team/scheme
  changes, injuries, retirements, and age curves. A rookie or a
  situation-change beneficiary has *no* row in Input Contract B.
- The market (ADP/ECR) already prices all of that in aggregate: it is
  forward-looking by construction, drafters and analysts have accounted
  for the rookie class, the offseason moves, and the depth-chart changes
  when they formed their pick and rank.

A naive 50/50 blend of the two would systematically bury every rookie
(``ranking_score`` undefined -> treated as replacement-level or worst-case
under most blending conventions) and over-rank 2025 compilers whose
situation quietly got worse. This module avoids that failure mode with two
design choices, both mandatory, not tunable away by accident:

1. **Drop-and-renormalize, never zero-fill**, for the retrospective
   component -- see "Missing retrospective data never penalizes" below.
   This is the single highest-risk failure mode of this ticket and is
   explicitly tested (:func:`test_draft_board.py`'s rookie cases).
2. **A capped, conservative default weight** on the retrospective
   component -- see :class:`DraftBoardWeights`, ``prior=0.25`` by default.

Two-level blend, and why rank is log-transformed before z-scoring
--------------------------------------------------------------------------

The blend has two levels, both drop-and-renormalize weighted averages of
z-scores (the exact convention ``player_rankings.py`` (FFA-073) already
established for this codebase -- see that module's "Missing components"
section, reused here rather than reinvented):

**Level 1 -- market_score**, from ``adp`` and ``ecr``::

    z_adp = z(-ln(adp))         # -ln(rank): see rank-to-value note below
    z_ecr = z(-ln(ecr))
    market_score = (w_adp * z_adp + w_ecr * z_ecr) / (w_adp + w_ecr)
                   over whichever of {adp, ecr} is defined for the player

**Level 2 -- draft_score**, blending ``market_score`` with the
retrospective signal::

    z_prior = z(prior_ranking_score)   # NOT log-transformed -- see below
    draft_score = (w_market * market_score + w_prior * z_prior)
                  / (w_market + w_prior)
                  over whichever of {market_score, z_prior} is defined

Both levels z-score (population z, ``ddof=0``, over the players in this
draft board for whom the raw quantity is defined) before blending -- never
raw ranks. This is deliberate and is the ticket's explicitly-flagged
methodological trap: **blending a raw ADP rank linearly with a z-scored
value metric is a real error**, because rank is an *ordinal* scale (the
gap between rank 1 and rank 2 is enormous in true fantasy value; the gap
between rank 150 and rank 151 is negligible) while a z-score is an
*interval* scale on the underlying value. Z-scoring the raw rank directly
would implicitly treat every one-rank step as equally meaningful, which is
false for exactly the shape a fantasy draft board has: value falls off
steeply at the top and flattens at the bottom.

``adp`` and ``ecr`` are ranks/rank-like pick positions, so before
z-scoring they are passed through ``value = -ln(rank)``, a monotone
decreasing-in-rank transform whose *successive gaps shrink logarithically*
(``ln(2) - ln(1) = 0.69``; ``ln(151) - ln(150) = 0.0066``) -- the same
qualitative shape a real points-by-ADP value curve has (rounds 1-2 differ
by tens of points per game; rounds 14-15 differ by fractions of a point).
This codebase has no fitted points-by-pick curve to calibrate against (no
season-long point projections are in scope for this ticket), so ``-ln``
is used as a principled, parameter-free stand-in for that curve rather
than an invented set of round-value coefficients.

``prior_ranking_score`` (FFA-073's output) is **not** log-transformed
before z-scoring: it is already a continuous, roughly-normal value metric
(a weighted blend of five z-scores), not an ordinal rank, so re-expressing
it on a log scale would distort rather than linearize it. It is z-scored
directly, computed fresh over *this draft board's* population (not reused
from FFA-073's original 2025-league z-scale), because the two frames do
not share a player universe -- see "Two different populations" below.

Missing retrospective data never penalizes -- the ticket's central test
--------------------------------------------------------------------------

A player with no 2025 row (rookie, or a 2025 no-show who is draftable in
2026) has ``prior_ranking_score = None``, so ``z_prior`` is undefined for
him, so **the level-2 blend drops that term and renormalizes on
``market_score`` alone**::

    draft_score = market_score        (weights.prior term dropped entirely)

His ``draft_score`` is therefore *exactly* his market-consensus score --
never zero-filled, never shrunk toward a league-average retrospective
score he was never measured against. See
``test_draft_board_rookie_not_penalized`` for the hand-checked assertion.

K and DEF are excluded from the retrospective component by default
--------------------------------------------------------------------------

The 2025 retrospective frame this ticket was built against
(``NWC_FFL_2025_full_1257477810625196032.csv``, FFA-073/FFA-064) has a
scoring engine that could not map every Sleeper scoring rule to an
nflverse stat column -- notably **every** team-defense rule
(``def_td``, ``pts_allow_*``, ``sack``, ``safe``, ``int``, ``ff``,
``fum_rec``, etc.) and some kicker rules (``fgm``, ``fum``). The practical
result: **zero DEF rows exist** in that frame at all, and the 40 K rows
that do exist are scored on an incomplete rule set, so a kicker's
``ranking_score`` there is not on the same footing as a QB/RB/WR/TE's.

Rather than rely on the generic missing-data path (which would correctly
handle DEF -- no row, no match, dropped-and-renormalized -- but would
silently *use* a partially-scored K row as if it were trustworthy), this
module takes an explicit, documented, overridable stance:
:data:`DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS` is ``frozenset({"K",
"DEF"})``, and for any player whose **market-frame position** is in that
set, ``prior_ranking_score``/``prior_league_rank`` are forced to ``None``
in the output *regardless of whether a matching 2025 row exists* -- not
merely down-weighted. This is stronger than "drop the component" because
it also suppresses a misleading non-``NaN`` value that was never actually
used in the blend. Pass ``retrospective_excluded_positions=frozenset()``
to disable this and fall back to the generic missing-data path (not
recommended against this specific retrospective input -- see above).
**The retrospective component in this module's default configuration is
trustworthy only for QB/RB/WR/TE.**

Two different populations -- why ``z_prior`` is not FFA-073's own z-scale
--------------------------------------------------------------------------

FFA-073's ``ranking_score`` is already a blend of z-scores computed over
*its own* 2025 league-season pool (roughly 620-650 players, one league).
This module's draft board population is the 2026 market frame (a
different, larger, forward-looking universe that includes rookies and
excludes retirees). Reusing FFA-073's z-scale unmodified would compare
apples grown in one field to apples about to be grown in a different one;
instead, ``prior_ranking_score`` is carried through **verbatim** from
Input Contract B, then z-scored **fresh**, over exactly the population
that ends up on this draft board (only players who both appear in the
market frame and have a usable prior score contribute to that mean/stdev).
This is an unavoidable simplification, not a solved problem: the overlap
between "2025 NWC FFL rostered-or-free-agent pool" and "2026 draftable
universe" is large but imperfect, and a player who barely qualified for
either frame sits at the edge of a small-sample z-score. Treat
``draft_score`` differences of a few hundredths, or single-digit
``draft_rank`` swings, as noise -- the same caution FFA-073 documents for
its own ``ranking_score``.

Weight defaults -- opinions, not fitted values
--------------------------------------------------------------------------

:class:`DraftBoardWeights` defaults, all overridable:

- ``adp=0.6, ecr=0.4`` -- ADP is real drafter behavior in *this exact*
  format (12-team half-PPR snake), the most directly relevant signal for
  "who is gone by pick N," so it gets the larger weight. ECR is a broader
  redraft-overall expert consensus with roughly double ADP's player
  coverage (517 vs. 233), so it is the only market signal available for
  deep bench-round sleepers (this draft's last pick is 188, still inside
  ADP's ~233-player universe, but ECR remains the more densely-populated
  signal there). 0.4 keeps expert opinion meaningfully represented without
  overriding revealed market behavior.
- ``market=0.75, prior=0.25`` -- the ticket's required "conservative
  default, 0.20-0.30 of the blend." 0.25 is the midpoint of that range: it
  lets 2025 realized value break ties and nudge the board (e.g. a
  consistent, low-``cv`` producer edges ahead of an equally-drafted boom/
  bust peer) without letting a blind-to-2026 signal dominate a forward-
  looking board. Nothing here was fit or backtested; it is a documented
  opinion, exactly like FFA-073's five component weights.

Neither weight pair is required to sum to 1.0 (each level is renormalized
by the weights actually used for that player -- see :func:`_weighted_blend`)
but the defaults do, at both levels.

Tiers -- a univariate gap rule on ``draft_score``, checked by hand
--------------------------------------------------------------------------

Within each position, sort the position's scored players by descending
``draft_score``. Start tier 1 at the top. Walk down the list; whenever the
gap to the previous player's score exceeds
:data:`DEFAULT_TIER_GAP_THRESHOLD` (0.30, in ``draft_score`` z-like units),
start a new tier. This is single-linkage 1-D clustering on a single
threshold: it is the simplest defensible break rule available without
inventing a fitted mixture model, and 0.30 was chosen (and checked against
the real 646-player NWC FFL retrospective plus a hand-built market frame --
see this module's tests and the ticket's verification report) to produce
several tiers per position rather than either one giant tier or a new tier
almost every player. A tied pair (gap of exactly 0.0) never breaks a tier
-- see "Ties" below. Worked example, four RBs scored 2.10, 2.05, 1.40,
1.38: gaps are 0.05 (< 0.30, same tier), 0.65 (>= 0.30, new tier), 0.02
(< 0.30, same tier) -> tiers ``[1, 1, 2, 2]``. Players with no
``draft_score`` (both market and prior undefined -- see "Missing values")
get ``tier = NaN``, sorted after every scored player at the position, and
never trigger or absorb a break.

``vor`` -- value over replacement for this exact 16-round league
--------------------------------------------------------------------------

FFA-068's replacement-level machinery
(:func:`~fantasy_analyzer.players.player_value.build_player_value_metrics`)
is built to consume *realized points*, and this module has none for 2026
-- there is no season-long point projection in scope for this ticket. So
``vor`` here is **not** points-scale VORP; it reuses FFA-068's exact
starter-cutoff *procedure* against ``draft_score`` instead of
``points_per_game``:

1. Map each slot in ``roster_positions`` (default
   :data:`DEFAULT_DRAFT_ROSTER_POSITIONS`, this league's exact 9-starter
   configuration) through
   :data:`~fantasy_analyzer.players.lineup_efficiency.START_SLOT_ELIGIBILITY`
   and count it toward **every** position it can start -- the identical
   convention FFA-068 uses, so the league's one ``FLEX`` slot (RB/WR/TE
   eligible) adds one starter to each of those three positions rather than
   being fractionally split. For this league: QB 1, RB 2+1=3, WR 2+1=3,
   TE 1+1=2, K 1, DEF 1 starters per team.
2. ``cutoff(position) = num_teams * starters(position)`` (default
   ``num_teams=12``): QB 12, RB 36, WR 36, TE 24, K 12, DEF 12.
3. Rank the position's players (those with a defined ``draft_score``) by
   descending ``draft_score``, ties broken by ascending
   ``sleeper_player_id``. The replacement player is at rank
   ``min(cutoff, field_size)`` -- clamped to the worst-scored player when
   the position has fewer scored players than the cutoff, identical to
   FFA-068's documented clamp and the identical caveat: this can overstate
   VOR at a position this draft board under-populates.
4. ``vor = draft_score - replacement_draft_score(position)``.

A position with zero scored players has no defined replacement level, so
``vor`` is ``NaN`` for every player at that position (unreachable for
QB/RB/WR/TE/K/DEF against a real market frame, reachable only from a
degenerate hand-built test frame).

``adp_delta`` -- the actionable column, and why it is NOT ``adp - draft_rank``
--------------------------------------------------------------------------

**Do not diff ``adp`` against ``draft_rank``.** An earlier version of this
module did exactly that and it is a real bug, not a hypothetical one:
FFC's ADP universe (~233 players) is much smaller than the full market
frame (~500+, once FantasyPros' deeper ECR coverage and the required K/DEF
rows are included), so ``draft_rank`` -- computed across *every* player on
the board -- is inflated for an ADP-having player by every no-ADP player
this board ranks above him, with no corresponding effect on his ``adp``.
Measured against the live 2026 board: the mean of ``adp - draft_rank``
over ADP-having players was **-45.0**, almost entirely this artifact (see
below); sorting by that quantity surfaced an all-kicker/DEF "biggest
reach" list, because kickers sit at ``draft_rank`` 340-410 (correctly --
see "K and DEF are excluded" above) while carrying an ``adp`` around 150,
and a raw diff reads that gap as a market disagreement rather than what it
actually is: being compared on a scale they were never plotted on.

The fix: ``adp_pool_rank`` is a **second, narrower ranking**, restricted
to only the players who have an ``adp`` at all, ranked by descending
``draft_score`` within that subset (same standard-competition-ranking
convention as ``draft_rank``, ties broken by ascending
``sleeper_player_id``). ``adp_delta = adp - adp_pool_rank`` -- both sides
now live in the same ~233-player universe. Re-measured this way, the mean
delta over ADP-having players drops to **-12.1** (still nonzero -- ADP-
having players are disproportionately the better players, so this board's
own ADP-only-pool ranks are not identically distributed to raw ADP either
-- but an order of magnitude smaller than the -45.0 artifact, and no
longer driven by K/DEF at all). ``adp_pool_rank`` is reported alongside
``adp_delta`` precisely so this computation can be audited without
re-deriving it.

**Sign convention, unchanged**: positive means this board ranks the
player better than the market does within the ADP pool (a VALUE -- he may
fall to you later than his market price suggests); negative means the
market ranks him better (a REACH relative to this board). Worked toy
example -- four ADP-having players ranked 1st, 2nd, 3rd, 4th by
``draft_score`` with ``adp`` values 2, 1, 4, 3 respectively:
``adp_pool_rank`` is exactly 1, 2, 3, 4 (the rank order *is* the
``draft_score`` order, by construction), so ``adp_delta`` is
``2-1=+1``, ``1-2=-1``, ``4-3=+1``, ``3-4=-1`` -- the two players this
board likes better than their ADP (ranked 1st and 3rd but with worse ADP
than the player behind them) show positive deltas, the other two negative.
Adding a fifth player with **no** ``adp`` anywhere in the board leaves all
four deltas above completely unchanged, because that player is excluded
from the ``adp_pool_rank`` sub-ranking entirely -- this invariant (no-ADP
players cannot shift an ADP-having player's delta) is the entire point of
using a second ranking rather than filtering the existing one, and is
explicitly tested (``test_no_adp_players_do_not_shift_adp_having_deltas``).
``adp_delta`` (and ``adp_pool_rank``) are ``NaN`` when ``adp`` is
undefined (a player with ECR but no ADP history) -- there is no market
pick position, and no ADP-pool rank, to compare against.

Pick availability -- a real, stated simplification
--------------------------------------------------------------------------

:func:`pick_availability_probability` models a player's true draft
position as ``Normal(adp, adp_sd)`` and returns
``P(true position >= pick_number)``, i.e. the probability nobody has
taken him in picks ``1..pick_number - 1``. When ``adp_sd`` is missing or
non-positive, it falls back to :data:`DEFAULT_ADP_SD` (6.0 picks) -- an
**arbitrary placeholder**, not fit to the real ADP-spread distribution; a
caller who has a real ``adp_sd`` should always prefer it. ``adp_sd`` can
also legitimately be **exactly 0.0** for a real player (a low-sample FFC
ADP entry drafted in essentially every mock at the same slot -- observed
on the live 2026 pull, e.g. Ollie Gordon II) -- ``sd > 0`` is checked
explicitly rather than ``sd is not None``, so a degenerate zero spread
also falls back to :data:`DEFAULT_ADP_SD` instead of collapsing the normal
model to a point mass.

**Independence assumption, stated plainly**: this treats every player's
draft position as independent of every other player's -- i.e. player A
going in pick 4 has zero effect on the modeled distribution for player B.
This is false in a real draft: positional runs (a QB run drags other QBs'
effective ADP down mid-run), team-need signals, and the fact that a player
literally cannot be drafted twice all induce correlation between players'
actual pick positions. The independence assumption is a deliberate
simplification to make the model tractable with only marginal
(``adp``, ``adp_sd``) inputs -- accounting for the correlation structure
would require modeling the whole draft jointly (e.g. a full draft
simulator), which is out of scope here. Treat the output as a rough,
context-free prior, most useful for *relative* comparisons ("is pick 20 or
29 more likely to still have him") rather than a calibrated probability.

Regular season vs. playoffs
--------------------------------------------------------------------------

This module makes no independent phase distinction -- it never sees
weekly data. The retrospective component's phase meaning is entirely
inherited from how the caller built ``prior_df`` upstream: FFA-073's
``player_ranking_df`` is itself built over whatever weeks the caller's
``player_season_df`` covers (see ``player_rankings.py``'s own
"Regular season vs. playoffs" section). This ticket's verification uses a
``phase="all"`` retrospective frame (regular season + playoffs); a
``phase="regular"`` frame is equally valid input and arguably the more
defensible "how good was this player over a full season" signal, since
playoff-only samples are small (a handful of weeks) and reflect a
subset of teams. This module does not enforce either choice.

Missing values / edge cases
--------------------------------------------------------------------------

- **Empty ``market_df``**: returns an empty frame with
  :data:`DRAFT_BOARD_COLUMNS` and documented per-column dtypes.
- **A ``market_df`` missing a required column** (any of FFA-075's
  :data:`~fantasy_analyzer.players.draft_market.DRAFT_MARKET_POOL_COLUMNS`
  -- this module validates against that full canonical contract, not a
  bespoke subset of its own, so a caller who builds ``market_df`` from
  :func:`~fantasy_analyzer.players.draft_market.build_draft_market_player_pool`
  is always shape-compatible): ``ValueError`` naming every missing column.
  A hand-built test frame must include every one of those columns (values
  may be ``None``/``NaN``); this module reads ``adp``, ``adp_sd``, ``ecr``,
  ``nfl_team``, and ``bye_week`` directly and is indifferent to the
  contents of ``adp_best``, ``adp_worst``, ``ecr_sd``, ``ecr_best``,
  ``ecr_worst``, and ``position_ecr``.
- **``adp`` and ``ecr`` missing independently** (a player one source
  covers and the other does not -- FFC's ADP has ~233 players, FantasyPros'
  overall ECR has ~517): never drops the player. ``market_score`` degrades
  gracefully to whichever of ``z_adp``/``z_ecr`` is defined, via the same
  drop-and-renormalize rule as every other component in this module.
- **Rows missing ``sleeper_player_id`` or ``position``** (``None``,
  ``NaN``, or the empty string): skipped -- cannot be placed on a board.
- **Duplicate ``sleeper_player_id`` rows** in either ``market_df`` or
  ``prior_df``: ``ValueError`` -- a duplicate would corrupt the z-score
  pools and the position replacement ranks.
- **A player missing both ``adp`` and ``ecr``**: ``market_score`` is
  ``NaN``. If ``prior_ranking_score`` is also unavailable (or excluded),
  ``draft_score`` is ``NaN``, ``components_used = 0``, and the player
  sorts last with ``draft_rank = NaN`` -- the same "nobody could score
  this player" convention ``player_rankings.py`` documents.
- **``prior_df=None`` or empty**: every player is scored on market
  consensus alone; ``draft_score`` equals ``market_score`` for the whole
  board. This is the ticket's rookie case applied universally and is a
  legitimate way to build a pure-market board.
- **A single-player frame, or a frame where a z-scored quantity has zero
  population variance**: that z-score is undefined (``None``) for every
  player -- the identical zero-variance guard ``player_rankings.py``
  documents -- and the affected component is dropped from every player's
  blend rather than dividing by zero.
- **Ties**: ``draft_rank``/``position_rank``/``adp_pool_rank`` all use
  standard competition ("1224") ranking on ``draft_score`` rounded to 6
  decimal places (the same float-noise convention
  ``player_value.py``/``player_rankings.py`` use); a tied pair never
  triggers a tier break (gap ``0.0 < 0.30``).
- **A player has no ``adp``**: ``adp_pool_rank`` and ``adp_delta`` are
  both ``NaN`` -- excluded from the ADP-pool sub-ranking entirely, not
  merely from the numerator (see "adp_delta" above for why this
  distinction matters and is load-bearing).

Column dtypes
--------------------------------------------------------------------------

``sleeper_player_id``, ``player_name``, ``position``, ``nfl_team`` are
``object`` (a missing label is restored to ``None`` explicitly).
``components_used`` is ``int64`` (always defined -- 0, 1, or 2). Every
other column (``adp``, ``adp_sd``, ``ecr``, ``bye_week``, both z-score
columns, ``market_score``, ``prior_ranking_score``, ``prior_league_rank``,
``z_prior``, ``draft_score``, ``draft_rank``, ``position_rank``,
``adp_pool_rank``, ``adp_delta``, ``tier``, ``vor``) is ``float64``, so an
undefined value is ``NaN`` and the dtype never depends on the data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any, Optional, Sequence

import pandas as pd

from fantasy_analyzer.players.draft_market import DRAFT_MARKET_POOL_COLUMNS
from fantasy_analyzer.players.lineup_efficiency import START_SLOT_ELIGIBILITY

#: Column order for :func:`build_draft_board`'s return value. Reads left to
#: right as the computation runs: identity, then the market inputs and
#: their z-scores, then the retrospective inputs and its z-score, then the
#: blend's audit trail, then the three ranking/actionability outputs.
DRAFT_BOARD_COLUMNS = [
    "sleeper_player_id",
    "player_name",
    "position",
    "nfl_team",
    "bye_week",
    "adp",
    "adp_sd",
    "ecr",
    "z_adp",
    "z_ecr",
    "market_score",
    "prior_ranking_score",
    "prior_league_rank",
    "z_prior",
    "components_used",
    "draft_score",
    "draft_rank",
    "position_rank",
    "adp_pool_rank",
    "adp_delta",
    "tier",
    "vor",
]

_FLOAT_COLUMNS = [
    "bye_week",
    "adp",
    "adp_sd",
    "ecr",
    "z_adp",
    "z_ecr",
    "market_score",
    "prior_ranking_score",
    "prior_league_rank",
    "z_prior",
    "draft_score",
    "draft_rank",
    "position_rank",
    "adp_pool_rank",
    "adp_delta",
    "tier",
    "vor",
]

_INT_COLUMNS = ["components_used"]

_LABEL_COLUMNS = ["sleeper_player_id", "player_name", "position", "nfl_team"]

#: Columns ``market_df`` must contain -- the full FFA-075
#: ``DRAFT_MARKET_POOL_COLUMNS`` contract, not a bespoke subset, so this
#: module always validates against the same canonical shape the ingestion
#: module promises. See the module docstring's "Missing values / edge
#: cases".
_REQUIRED_MARKET_COLUMNS = DRAFT_MARKET_POOL_COLUMNS

#: Positions whose retrospective component is forced off by default -- see
#: the module docstring's "K and DEF are excluded from the retrospective
#: component by default". Overridable via
#: ``build_draft_board(retrospective_excluded_positions=...)``.
DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS = frozenset({"K", "DEF"})

#: This exact league's 9-starter roster (QB, RB, RB, WR, WR, TE, FLEX, K,
#: DEF) plus 7 bench slots -- 16 rounds total. Used for :func:`_vor` when
#: the caller does not override ``roster_positions``.
DEFAULT_DRAFT_ROSTER_POSITIONS = [
    "QB",
    "RB",
    "RB",
    "WR",
    "WR",
    "TE",
    "FLEX",
    "K",
    "DEF",
    "BN",
    "BN",
    "BN",
    "BN",
    "BN",
    "BN",
    "BN",
]

#: This exact league's team count.
DEFAULT_DRAFT_NUM_TEAMS = 12

#: The ``draft_score`` gap (in z-like units) that starts a new tier within
#: a position -- see the module docstring's "Tiers" section and worked
#: example.
DEFAULT_TIER_GAP_THRESHOLD = 0.30

#: Fallback ADP standard deviation, in picks, used when a player's
#: ``adp_sd`` is missing or non-positive -- see the module docstring's
#: "Pick availability" section. An explicitly arbitrary placeholder.
DEFAULT_ADP_SD = 6.0


@dataclass(frozen=True)
class DraftBoardWeights:
    """Blend weights for :func:`build_draft_board`'s two-level blend.

    See the module docstring's "Two-level blend" and "Weight defaults"
    sections for the formulas and the reasoning behind the defaults.
    Neither weight pair (``adp``/``ecr``, ``market``/``prior``) is required
    to sum to 1.0 -- each level is renormalized by whichever weights were
    actually usable for a given player -- but the defaults do.

    Attributes:
        adp: Weight on ``z_adp`` in the market sub-blend.
        ecr: Weight on ``z_ecr`` in the market sub-blend.
        market: Weight on ``market_score`` in the top-level blend.
        prior: Weight on ``z_prior`` (2025 retrospective value) in the
            top-level blend. Kept conservative by default (0.25 -- inside
            the ticket's required 0.20-0.30 range) because the market
            already prices in everything 2025 realized production cannot
            see (rookies, injuries, offseason moves) -- see "Market is the
            base, not an equal partner" in the module docstring.

    Raises:
        ValueError: If any weight is negative or not a number, if
            ``adp`` and ``ecr`` are both zero, or if ``market`` and
            ``prior`` are both zero (no defined normalization for that
            level).
    """

    adp: float = 0.6
    ecr: float = 0.4
    market: float = 0.75
    prior: float = 0.25

    def __post_init__(self) -> None:
        for field_name in ("adp", "ecr", "market", "prior"):
            weight = getattr(self, field_name)
            if not (weight >= 0):
                raise ValueError(
                    f"DraftBoardWeights.{field_name} must be a non-negative "
                    f"number; got {weight!r}"
                )
        if self.adp + self.ecr <= 0:
            raise ValueError(
                "DraftBoardWeights.adp and .ecr cannot both be zero; the "
                "market sub-blend would have no defined normalization"
            )
        if self.market + self.prior <= 0:
            raise ValueError(
                "DraftBoardWeights.market and .prior cannot both be zero; "
                "the top-level blend would have no defined normalization"
            )


#: Default blend weights -- see :class:`DraftBoardWeights`.
DEFAULT_DRAFT_BOARD_WEIGHTS = DraftBoardWeights()


def _is_missing(value: Any) -> bool:
    """True for ``None``, ``NaN``/``NA``, and the empty string.

    Duplicated from the identical helper in ``player_rankings.py`` and
    ``player_value.py`` rather than imported -- this codebase does not
    import private names across modules.
    """
    if isinstance(value, str):
        return value == ""
    return pd.isna(value)


def _empty_frame() -> pd.DataFrame:
    """An empty DataFrame with :data:`DRAFT_BOARD_COLUMNS` and their dtypes."""
    return pd.DataFrame(
        {
            column: pd.Series(
                dtype=(
                    "int64"
                    if column in _INT_COLUMNS
                    else "float64"
                    if column in _FLOAT_COLUMNS
                    else object
                )
            )
            for column in DRAFT_BOARD_COLUMNS
        }
    )


def _require_market_columns(market_df: pd.DataFrame) -> None:
    """Raise ``ValueError`` naming any required column ``market_df`` lacks."""
    missing = [
        column for column in _REQUIRED_MARKET_COLUMNS if column not in market_df.columns
    ]
    if missing:
        raise ValueError(
            "market_df is missing required column(s): "
            + ", ".join(missing)
            + "; expected fantasy_analyzer.players.draft_market."
            "DRAFT_MARKET_POOL_COLUMNS (Input Contract A) -- see the "
            "module docstring"
        )


def _population_zscores(values: list[Optional[float]]) -> list[Optional[float]]:
    """Population z-score a list, preserving position and ``None`` gaps.

    Identical convention to ``player_rankings.py``'s helper of the same
    name: ``None`` entries take no part in the mean/stdev and come back as
    ``None``; returns all-``None`` when fewer than two values are usable
    or the population standard deviation is 0 (no scale to measure
    against -- never divides by zero, never emits ``inf``).
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
) -> tuple[Optional[float], int]:
    """``(score, components_used)`` from ``[(value, weight), ...]``.

    Drop-and-renormalize: a component with ``value is None`` or
    ``weight <= 0`` contributes nothing to the numerator or the
    denominator. Returns ``(None, 0)`` when no component qualifies. Used
    for both blend levels (market sub-blend and top-level blend) so the
    two levels can never drift apart in behavior.
    """
    terms: list[float] = []
    used_weights: list[float] = []
    for value, weight in components:
        if value is None or weight <= 0:
            continue
        terms.append(weight * value)
        used_weights.append(weight)
    if not used_weights:
        return None, 0
    return math.fsum(terms) / math.fsum(used_weights), len(used_weights)


def _rank_value(rank: Optional[float]) -> Optional[float]:
    """``-ln(rank)`` for a positive rank/pick position, else ``None``.

    See the module docstring's "why rank is log-transformed before
    z-scoring" -- a monotone transform whose successive gaps shrink as
    rank grows, mirroring a real points-by-pick value curve, without
    requiring a fitted curve this ticket has no data to fit. ``None`` for
    a non-positive or missing rank (a log has no meaning there); this
    never raises.
    """
    if rank is None or not (rank > 0):
        return None
    return -math.log(rank)


def _normalize_market(market_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows of ``market_df`` this module can place on the board.

    Skips rows missing ``sleeper_player_id`` or ``position``. Raises
    ``ValueError`` on a duplicate ``sleeper_player_id`` -- see the module
    docstring's "Missing values / edge cases". ``adp``/``ecr`` may be
    missing independently for a given row without dropping it (see
    "``adp`` and ``ecr`` missing independently" in the module docstring);
    ``getattr(..., default=None)`` also tolerates a caller-built frame
    that satisfies :func:`_require_market_columns` but leaves a value
    ``None`` rather than ``NaN``.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in market_df.itertuples(index=False):
        player_id = getattr(row, "sleeper_player_id", None)
        position = getattr(row, "position", None)
        if _is_missing(player_id) or _is_missing(position):
            continue

        key = str(player_id)
        if key in seen:
            raise ValueError(
                "market_df contains duplicate sleeper_player_id "
                f"{player_id!r}; this module's row universe is one row per "
                "player"
            )
        seen.add(key)

        adp = getattr(row, "adp", None)
        ecr = getattr(row, "ecr", None)
        adp_sd = getattr(row, "adp_sd", None)
        bye_week = getattr(row, "bye_week", None)

        rows.append(
            {
                "sleeper_player_id": player_id,
                "player_name": getattr(row, "player_name", None),
                "position": position,
                "nfl_team": getattr(row, "nfl_team", None),
                "bye_week": None if _is_missing(bye_week) else float(bye_week),
                "adp": None if _is_missing(adp) else float(adp),
                "adp_sd": None if _is_missing(adp_sd) else float(adp_sd),
                "ecr": None if _is_missing(ecr) else float(ecr),
            }
        )
    return rows


def _normalize_prior(
    prior_df: Optional[pd.DataFrame],
) -> dict[str, dict[str, Optional[float]]]:
    """``sleeper_player_id`` -> ``{"ranking_score", "league_rank"}``.

    ``None``/empty ``prior_df`` yields an empty lookup (every player is
    treated as having no retrospective data -- the "prior_df=None" case in
    the module docstring). Raises ``ValueError`` on a duplicate
    ``sleeper_player_id``.
    """
    lookup: dict[str, dict[str, Optional[float]]] = {}
    if prior_df is None or prior_df.empty:
        return lookup

    for row in prior_df.itertuples(index=False):
        player_id = getattr(row, "sleeper_player_id", None)
        if _is_missing(player_id):
            continue
        key = str(player_id)
        if key in lookup:
            raise ValueError(
                f"prior_df contains duplicate sleeper_player_id {player_id!r}"
            )
        ranking_score = getattr(row, "ranking_score", None)
        league_rank = getattr(row, "league_rank", None)
        lookup[key] = {
            "ranking_score": (
                None if _is_missing(ranking_score) else float(ranking_score)
            ),
            "league_rank": None if _is_missing(league_rank) else float(league_rank),
        }
    return lookup


def _starter_slots(roster_positions: list[str]) -> dict[str, int]:
    """Starting slots per position per team, from a roster-slot list.

    Identical convention to ``player_value.py``'s helper of the same name:
    each slot counts toward every position ``START_SLOT_ELIGIBILITY`` says
    it can accept, so a ``FLEX`` slot adds one starter to each of RB, WR,
    and TE. Bench/unrecognized slots contribute nothing.
    """
    slots: dict[str, int] = {}
    for slot in roster_positions or []:
        eligible = START_SLOT_ELIGIBILITY.get(slot)
        if eligible is None:
            continue
        for position in eligible:
            slots[position] = slots.get(position, 0) + 1
    return slots


def _assign_competition_ranks(
    rows: list[dict[str, Any]], score_key: str, rank_key: str
) -> None:
    """Standard competition ("1224") ranks in place, best score first.

    ``rows`` must already be sorted descending by ``score_key`` (``None``
    last, tie-broken by ascending ``sleeper_player_id``). Ties are judged
    on the score rounded to 6 decimal places -- the float-noise convention
    ``player_value.py``/``player_rankings.py`` use.
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


def _sort_key(row: dict[str, Any], score_key: str) -> tuple[int, float, str]:
    """Display order: best score first, ``None`` last, ties by player id."""
    score = row[score_key]
    if score is None:
        return (1, 0.0, str(row["sleeper_player_id"]))
    return (0, -score, str(row["sleeper_player_id"]))


def _assign_tiers(
    rows: list[dict[str, Any]], gap_threshold: float
) -> None:
    """Assign ``tier`` in place over one position's players.

    ``rows`` must already be sorted descending by ``draft_score`` (the
    display order). See the module docstring's "Tiers" section for the
    rule and worked example. Rows with ``draft_score is None`` get
    ``tier = None`` and never start or absorb a break; a gap of exactly
    ``0.0`` (a tie) never starts a new tier.
    """
    current_tier = 0
    previous_score: Optional[float] = None
    for row in rows:
        score = row["draft_score"]
        if score is None:
            row["tier"] = None
            continue
        if previous_score is None or (previous_score - score) > gap_threshold:
            current_tier += 1
        row["tier"] = float(current_tier)
        previous_score = score


def _assign_vor(
    rows: list[dict[str, Any]], starter_slots: dict[str, int], num_teams: int
) -> None:
    """Assign ``vor`` in place over one position's players.

    See the module docstring's "``vor``" section for the replacement-rank
    procedure. ``rows`` need not be pre-sorted; this function sorts its
    own copy. Rows with ``draft_score is None`` are excluded from the
    replacement computation and get ``vor = None``.
    """
    scored = [row for row in rows if row["draft_score"] is not None]
    for row in rows:
        row["vor"] = None
    if not scored:
        return

    position = scored[0]["position"]
    ordered = sorted(
        scored,
        key=lambda row: (-row["draft_score"], str(row["sleeper_player_id"])),
    )
    field_size = len(ordered)
    cutoff = num_teams * starter_slots.get(position, 0)
    replacement_rank = field_size if cutoff < 1 else min(cutoff, field_size)
    replacement_score = ordered[replacement_rank - 1]["draft_score"]
    for row in scored:
        row["vor"] = row["draft_score"] - replacement_score


def build_draft_board(
    market_df: pd.DataFrame,
    prior_df: Optional[pd.DataFrame] = None,
    *,
    weights: DraftBoardWeights = DEFAULT_DRAFT_BOARD_WEIGHTS,
    roster_positions: Optional[list[str]] = None,
    num_teams: int = DEFAULT_DRAFT_NUM_TEAMS,
    retrospective_excluded_positions: frozenset[
        str
    ] = DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS,
    tier_gap_threshold: float = DEFAULT_TIER_GAP_THRESHOLD,
) -> pd.DataFrame:
    """Build a ranked 2026 draft board blending market consensus with 2025 value.

    See the module docstring for every formula, the drop-and-renormalize
    rookie protection (the ticket's central requirement), the K/DEF
    retrospective exclusion, the tier rule with a worked example, and the
    draft-specific VOR definition.

    Args:
        market_df: Input Contract A -- a
            :data:`~fantasy_analyzer.players.draft_market.DRAFT_MARKET_POOL_COLUMNS`-shaped
            frame, one row per ``sleeper_player_id``, as produced by
            :func:`~fantasy_analyzer.players.draft_market.build_draft_market_player_pool`
            (or its cached wrapper,
            :func:`~fantasy_analyzer.players.draft_market_cache.get_draft_market_player_pool_cached`).
            This module reads ``sleeper_player_id``, ``player_name``,
            ``position``, ``nfl_team``, ``bye_week``, ``adp``, ``adp_sd``,
            and ``ecr`` directly; ``adp`` and ``ecr`` may each be ``NaN``
            independently without dropping the row (a player only one
            source resolved) -- see the module docstring.
        prior_df: Input Contract B -- FFA-073's
            :attr:`~fantasy_analyzer.players.player_analytics.PlayerAnalytics.player_ranking_df`-shaped
            frame (or ``None``/empty for a pure-market board), read for
            ``sleeper_player_id``, ``ranking_score``, and ``league_rank``.
        weights: The two-level blend weights. See :class:`DraftBoardWeights`.
        roster_positions: The league's roster-slot list for the ``vor``
            replacement baseline. Defaults to
            :data:`DEFAULT_DRAFT_ROSTER_POSITIONS` (this league's exact
            9-starter, 7-bench configuration).
        num_teams: Team count for the ``vor`` replacement baseline.
            Defaults to :data:`DEFAULT_DRAFT_NUM_TEAMS` (12).
        retrospective_excluded_positions: Market-frame positions whose
            retrospective component is forced to ``None`` regardless of a
            matching ``prior_df`` row. Defaults to
            :data:`DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS` (``{"K",
            "DEF"}``) -- see the module docstring.
        tier_gap_threshold: The ``draft_score`` gap (z-like units) that
            starts a new tier within a position. Defaults to
            :data:`DEFAULT_TIER_GAP_THRESHOLD` (0.30).

    Returns:
        A DataFrame with columns :data:`DRAFT_BOARD_COLUMNS`, one row per
        usable player in ``market_df``, sorted by ascending ``draft_rank``
        (unscored players last), ties broken by ascending
        ``sleeper_player_id``. Empty (with the same columns/dtypes) if
        ``market_df`` is empty or no row is usable.

    Raises:
        ValueError: If ``market_df`` is missing a required column, or
            either input frame has a duplicate ``sleeper_player_id``.
    """
    if market_df.empty:
        return _empty_frame()

    _require_market_columns(market_df)
    if roster_positions is None:
        roster_positions = DEFAULT_DRAFT_ROSTER_POSITIONS

    market_rows = _normalize_market(market_df)
    if not market_rows:
        return _empty_frame()

    prior_lookup = _normalize_prior(prior_df)

    # --- Level 1: market sub-blend -----------------------------------
    adp_values = [_rank_value(row["adp"]) for row in market_rows]
    ecr_values = [_rank_value(row["ecr"]) for row in market_rows]
    z_adp_list = _population_zscores(adp_values)
    z_ecr_list = _population_zscores(ecr_values)

    for row, z_adp, z_ecr in zip(market_rows, z_adp_list, z_ecr_list):
        row["z_adp"] = z_adp
        row["z_ecr"] = z_ecr
        market_score, _ = _weighted_blend(
            [(z_adp, weights.adp), (z_ecr, weights.ecr)]
        )
        row["market_score"] = market_score

    # --- Retrospective lookup, with the K/DEF exclusion --------------
    for row in market_rows:
        prior = None
        if row["position"] not in retrospective_excluded_positions:
            prior = prior_lookup.get(str(row["sleeper_player_id"]))
        row["prior_ranking_score"] = prior["ranking_score"] if prior else None
        row["prior_league_rank"] = prior["league_rank"] if prior else None

    # --- Level 2: top-level blend -------------------------------------
    z_prior_list = _population_zscores(
        [row["prior_ranking_score"] for row in market_rows]
    )
    for row, z_prior in zip(market_rows, z_prior_list):
        row["z_prior"] = z_prior
        draft_score, components_used = _weighted_blend(
            [(row["market_score"], weights.market), (z_prior, weights.prior)]
        )
        row["draft_score"] = draft_score
        row["components_used"] = components_used

    # --- Ranks (league-wide) -------------------------------------------
    market_rows.sort(key=lambda row: _sort_key(row, "draft_score"))
    _assign_competition_ranks(market_rows, "draft_score", "draft_rank")

    # adp_delta must compare adp against a rank drawn from the *same*
    # population ADP was assigned over -- every player without an ADP
    # (FFC's ~233-player universe is much smaller than the full market
    # frame) is excluded from this sub-ranking entirely, not just from the
    # numerator. See the module docstring's "adp_delta" section for why
    # diffing against the full-board draft_rank is wrong.
    for row in market_rows:
        row["adp_pool_rank"] = None
    adp_pool = [row for row in market_rows if row["adp"] is not None]
    adp_pool.sort(key=lambda row: _sort_key(row, "draft_score"))
    _assign_competition_ranks(adp_pool, "draft_score", "adp_pool_rank")

    for row in market_rows:
        row["adp_delta"] = (
            None
            if row["adp"] is None or row["adp_pool_rank"] is None
            else row["adp"] - row["adp_pool_rank"]
        )

    # --- Per-position ranks, tiers, and VOR -----------------------------
    starter_slots = _starter_slots(roster_positions)
    by_position: dict[str, list[dict[str, Any]]] = {}
    for row in market_rows:
        by_position.setdefault(str(row["position"]), []).append(row)

    for position_rows in by_position.values():
        # Already in display order (sorting the whole board preserved
        # every subsequence's relative order).
        _assign_competition_ranks(position_rows, "draft_score", "position_rank")
        _assign_tiers(position_rows, tier_gap_threshold)
        _assign_vor(position_rows, starter_slots, int(num_teams or 0))

    result = pd.DataFrame(market_rows, columns=DRAFT_BOARD_COLUMNS)
    result["components_used"] = result["components_used"].astype(int)
    for column in _FLOAT_COLUMNS:
        result[column] = result[column].astype(float)
    for label_column in _LABEL_COLUMNS:
        result[label_column] = pd.Series(
            [
                None if _is_missing(value) else value
                for value in result[label_column].tolist()
            ],
            dtype=object,
        )

    return result[DRAFT_BOARD_COLUMNS]


def _standard_normal_cdf(z: float) -> float:
    """``Φ(z)`` for the standard normal distribution, via ``math.erf``."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def pick_availability_probability(
    pick_number: int,
    adp: Optional[float],
    adp_sd: Optional[float] = None,
    *,
    default_adp_sd: float = DEFAULT_ADP_SD,
) -> float:
    """``P(player still on the board immediately before ``pick_number``)``.

    Models the player's true draft position as
    ``Normal(adp, adp_sd or default_adp_sd)`` and returns
    ``P(true position >= pick_number) = 1 - Φ((pick_number - adp) / sd)``.
    See the module docstring's "Pick availability" section for the
    independence assumption this makes and why it is a simplification, and
    for why :data:`DEFAULT_ADP_SD` is an explicitly arbitrary placeholder.

    Args:
        pick_number: The overall pick number to evaluate (1-indexed; must
            be ``>= 1``).
        adp: The player's average draft position. ``NaN``/``None`` returns
            ``NaN`` (no market pick position to model).
        adp_sd: The player's ADP standard deviation, in picks. ``NaN``,
            ``None``, or non-positive falls back to ``default_adp_sd``.
        default_adp_sd: The fallback spread. Defaults to
            :data:`DEFAULT_ADP_SD`.

    Returns:
        A probability in ``[0.0, 1.0]``, or ``NaN`` if ``adp`` is missing.

    Raises:
        ValueError: If ``pick_number < 1``.
    """
    if pick_number < 1:
        raise ValueError(f"pick_number must be >= 1; got {pick_number!r}")
    if adp is None or _is_missing(adp):
        return float("nan")
    sd = adp_sd
    if sd is None or _is_missing(sd) or not (sd > 0):
        sd = default_adp_sd
    z = (pick_number - float(adp)) / sd
    return 1.0 - _standard_normal_cdf(z)


def build_pick_availability_table(
    draft_board_df: pd.DataFrame,
    picks: Sequence[int],
    *,
    default_adp_sd: float = DEFAULT_ADP_SD,
) -> pd.DataFrame:
    """A convenience table: probability each player survives to each pick.

    For every row in ``draft_board_df`` (expected to carry ``adp`` and
    ``adp_sd``, e.g. :func:`build_draft_board`'s own output) and every
    pick number in ``picks``, computes
    :func:`pick_availability_probability`. Intended to drive "who can I
    actually get at pick 20 vs. 29" -- see the module docstring.

    Args:
        draft_board_df: A frame with at least ``sleeper_player_id``,
            ``player_name``, ``position``, ``adp``, ``adp_sd``.
        picks: The pick numbers to evaluate, e.g. one manager's full slot
            list. Each must be ``>= 1``.
        default_adp_sd: Passed through to
            :func:`pick_availability_probability`.

    Returns:
        A copy of ``draft_board_df``'s identity columns plus one
        ``prob_available_pick_{n}`` column per entry in ``picks``, in the
        order given. Empty picks list returns just the identity columns.
    """
    identity_columns = [
        column
        for column in ("sleeper_player_id", "player_name", "position", "adp", "adp_sd")
        if column in draft_board_df.columns
    ]
    result = draft_board_df[identity_columns].copy()
    for pick_number in picks:
        column_name = f"prob_available_pick_{pick_number}"
        result[column_name] = [
            pick_availability_probability(
                pick_number, adp, adp_sd, default_adp_sd=default_adp_sd
            )
            for adp, adp_sd in zip(
                draft_board_df.get("adp", pd.Series(dtype=float)),
                draft_board_df.get("adp_sd", pd.Series(dtype=float)),
            )
        ]
    return result
