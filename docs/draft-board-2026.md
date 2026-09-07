# 2026 draft board -- terms and formulas

This page documents the methodology behind the "Draft board from the five
hole" artifact -- a pick-5, 12-team, half-PPR, 16-round draft board for the
NWC FFL's 2026 season, built from [FFA-075](../AGENTS.md) (2026 market data:
ADP + ECR) and [FFA-076](../AGENTS.md) (draft board: market + retrospective
blend).

A full offline copy of the rendered artifact is saved alongside this page at
[`docs/draft-board-2026.html`](draft-board-2026.html) -- open it directly in
a browser to view the board without a network connection. This page explains
the terms and formulas used inside it.

## Terms

| Term | Meaning |
| --- | --- |
| **ADP** | Average Draft Position. Sourced from 12-team half-PPR mock drafts. |
| **ECR** | Expert Consensus Rank -- an aggregate of expert positional/overall rankings. |
| **VOR** (`VOR` column) | Value Over Replacement: a player's projected value above the last starter at his position, for a 12-team league with this exact starting lineup (QB, RB2, WR2, TE, FLEX, K, DEF). This is what makes a TE1 and an RB1 comparable on one scale. |
| **Δ ADP** (`ΔADP` column) | The gap between a player's market ADP and where this board ranks him, in picks. Positive = the board (and presumably the room) is letting him fall past his ADP; negative = the board or room likes him earlier than the market does. Only computed for players the market has actually priced. |
| **SRC** (`SRC` column) | Whether a player's rank blends both inputs (`both` = market + 2025 production) or market-only (`mkt`). Market-only applies to kickers, defenses, and rookies -- see [Exceptions](#exceptions-and-caveats) below. |
| **Expected value** | Used to rank "Targets at each turn": `VOR x P(available)`. A player's raw value discounted by the probability he's actually still on the board when your pick comes up. |
| **P(available)** | The modeled probability a player is still undrafted when your next pick arrives (see [Availability model](#availability-model)). |
| **Bye** | The player's 2026 bye week. |
| **Tier** | An internal grouping present in the underlying data but not currently surfaced as a UI label; the visible "tier break" markers on the position-cliff charts are derived directly from the VOR drop-off (see below), not from this field. |

## How a composite rank is built

Each player's overall rank blends two components:

1. **Market base -- 75% weight.** ADP from 12-team half-PPR mock drafts,
   blended 60/40 with ECR (60% ADP, 40% ECR). Both inputs are converted to a
   *value curve* before scoring (not used as raw ranks), so the gap between
   the 1st- and 5th-ranked player counts for more than the gap between the
   101st and 105th -- ranks compress at the bottom of the board the way real
   draft value does.
2. **Last season's production -- 25% weight.** The league's own 2025
   composite player-value score (see FFA-073, the league-wide composite
   player value ranking), computed under the league's actual Sleeper scoring
   settings across the full free-agent-inclusive player pool (FFA-074) --
   not just players who were rostered in 2025.

```text
composite_score = 0.75 * market_value_curve(0.6*ADP + 0.4*ECR)
                 + 0.25 * retrospective_2025_value_score
```

**Missing inputs are dropped, not zeroed.** If a player is missing either
component (e.g. a rookie has no 2025 score), the score is computed from
whatever remains and renormalized to that reduced weight base, rather than
treating the missing side as a zero. A missing input never reads as a
weakness.

### Availability model

Each player's probability of still being on the board at a given future pick
is modeled as a **normal distribution centered on his ADP**, using the
market's own observed standard deviation of draft position where that spread
data exists. `P(available at pick N)` is the probability mass of that
distribution at or beyond pick `N`.

### Value over replacement (VOR)

VOR is computed against the projected value of the last startable player at
each position, given a 12-team league and this league's exact lineup
(1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 K, 1 DEF). Replacement level is therefore
lineup- and league-size-specific, not a generic positional cutoff.

## Exceptions and caveats

- **Kicker and defense ranks are market-only.** The league's 2025 scoring
  could not be mapped for team defenses at all (sacks, interceptions, points
  allowed, return touchdowns), and only partially for kickers. Rather than
  rank them on a retrospective number built from incompletely-mapped rules,
  the 25%-weight retrospective component is switched off entirely for both
  positions -- they rank on 2026 market consensus alone (`SRC = mkt`).
- **Rookies are not penalized for having no 2025 season.** Since the
  retrospective component is a minority weight (25%) and is dropped (not
  zeroed) when absent, a rookie ranks on market consensus alone with no
  artificial penalty for missing a partner input.
- **Two rostered keepers may already be off the board.** The source league
  has two rosters carrying Sleeper keepers (Jayden Daniels and Ladd McConkey
  on one; Matthew Stafford on another), but the draft was configured as a
  plain 16-round snake with no keeper rounds recorded -- possibly stale
  carryover from 2025. If those keepers are live for 2026, all three should
  be treated as unavailable; this board still includes them since the
  keeper state could not be confirmed from Sleeper's draft config.

## Board sections

- **Your sixteen picks** -- the pick-5 snake sequence for a 12-team, 16-round
  draft. Gaps alternate 15 -> 9 -> 15 -> 9 picks between your turns all
  draft; pairs of picks close enough together that the board barely moves
  between them are highlighted as one combined decision.
- **Targets at each turn** -- ranked by expected value (see above), capped at
  three players per position per turn (a 4th-best available TE isn't a real
  choice in a 1-TE lineup). Kickers/defenses are hidden until the final three
  rounds.
- **Where each position falls off** -- VOR for the top of each position,
  with the steepest single drop between consecutive ranked players marked as
  the "cliff" worth reaching for.
- **Value and reach against the market** -- players split into "falling to
  you" (positive Δ ADP) and "going too early" (negative Δ ADP) relative to
  market ADP.
- **Full board** -- top 180 of the ranked pool with ADP, ECR, VOR, Δ ADP, and
  SRC for each player.

## Related tickets

- **FFA-072** -- Projection and ranking provider interface.
- **FFA-073** -- League-wide composite player value ranking (the 2025
  retrospective score used as the 25%-weight input here).
- **FFA-074** -- League-wide free-agent player pool and ID-crosswalk
  coverage fix (makes the 2025 retrospective score cover the *entire* player
  pool, not just rostered players).
- **FFA-075** -- 2026 draft market data (ADP + ECR ingestion).
- **FFA-076** -- 2026 draft board (this artifact): market + retrospective
  blend.
- **FFA-077 through FFA-086** -- Post-draft grading and points-value analysis:
  see [`docs/draft-grade-2026.md`](draft-grade-2026.md) for the sequel that
  grades how teams actually drafted against this board.
