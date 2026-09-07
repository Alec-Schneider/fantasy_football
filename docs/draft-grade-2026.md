# 2026 draft grading -- terms and formulas

This page documents the methodology for grading how teams actually drafted
against the board described in [`docs/draft-board-2026.md`](draft-board-2026.md).
Where that page explains the *pre-draft* ranking and availability model, this
page covers the *post-draft* analysis: normalizing picks, scoring each pick
against its board expectation, rolling them into per-team grades, and
explaining where in the draft each team won or lost value.

## Terms

| Term | Meaning |
| --- | --- |
| **`pick_value`** | Board-relative value of a single pick: player's `draft_score` minus the board's expected score at that pick slot. Positive = steal (fell past expectation); negative = reach. Sign bug fixed in FFA-084 (see Exceptions below). |
| **`expected_value_at_pick`** | The board's expected score for whoever goes at this exact pick number, interpolated from the full board's `(draft_rank, draft_score)` pairs. One audit-trail value per pick so `pick_value` can be hand-checked. |
| **`projected_points_value`** | Points-scale equivalent of `pick_value`, fitted from a league's real prior-season data (FFA-085). Answers "given where this year's board ranks this player, how many real points above replacement does history say that rank typically returns?" |
| **`expected_points_value_at_pick`** | The board's expected points-return for this exact pick slot, from the fitted curve. Complement to `projected_points_value`, same audit-trail convention as `expected_value_at_pick`. |
| **`pick_value_points`** | Points-scale reach/steal: `projected_points_value - expected_points_value_at_pick`. Same sign convention as `pick_value` (positive = steal, negative = reach), but in real fantasy points rather than board value units. |
| **`pick_phase`** | Bucketing each pick into early/mid/late thirds of the draft, by round. Used for phase-breakdown summaries (see below). |
| **Keeper** | A pick whose player was already rostered as a keeper, not a live market decision. Excluded from team grades and `pick_value` computation. |

## How `pick_value` is computed (board-relative)

1. **Build the value curve:** Extract every `(draft_rank, draft_score)` pair
   from the board, sort ascending by rank, collapse duplicates (tied players
   share an identical score by construction). This is the full-board population,
   not the narrower ADP-only pool -- `pick_no` is a real draft-slot number
   spanning every actual pick.

2. **Interpolate:** For each draft pick at `pick_no`, query the curve:
   - **Exact match:** if `pick_no` exactly matches a `draft_rank`, use that
     `draft_score` directly.
   - **Between ranks:** if `pick_no` falls between two ranked players, linearly
     interpolate their scores.
   - **Outside range:** if `pick_no` exceeds the board's ranked population,
     clamp to the last ranked value.

3. **Grade the pick:** `pick_value = draft_score(player taken) - expected_value_at_pick`.

**Tie handling:** Two picks landing on identical `pick_value` require no
special logic -- every pick is scored independently. Ties in `pick_value` are
genuine and reported as-is.

**Sign convention history:** An earlier version of this metric computed
`pick_value = expected_pick - pick_no` (a raw rank-position diff). This had
two compounding problems: (1) **wrong sign** -- the formula was positive for
reaches and negative for steals, exactly backwards; (2) **wrong scale** --
diffing raw pick positions penalizes late-round moves equally to early-round
ones, despite enormous differences in true value. Both bugs are fixed in the
current approach, which uses the board's own value scale and interpolates
correctly. The metrics published as draft-grade Artifacts for NWC/New Wave/Zipline
were regenerated with this corrected formula.

## The points-value curve (real-points-scale)

For a league with an already-completed prior season, `draft_points_value.py`
(FFA-085) fits a second, complementary value scale by regression on real data:

1. **Gather training data:** Join the prior season's normalized draft picks
   (FFA-077) onto that same season's FFA-073 composite player ranking
   (real fantasy points above replacement), filtered to non-keeper picks and
   non-K/DEF positions.

2. **Fit the curve:** Ordinary least squares of
   `points_above_replacement = intercept + slope * ln(pick_no)`, closed-form
   (no external dependencies). The log shape mirrors `draft_board.py`'s own
   assumption: value falls steeply at the top, flattens at the bottom.

3. **Evaluate for a new draft:** Apply the fitted `PointsValueCurve` to an
   upcoming draft's picks:
   - `projected_points_value = curve.value_at(draft_rank of player taken)` --
     "what do history and this year's board say this rank typically returns?"
   - `expected_points_value_at_pick = curve.value_at(pick_no used)` -- "what
     does history say this slot typically returns?"
   - `pick_value_points = projected_points_value - expected_points_value_at_pick`.

Same sign convention as `pick_value` (positive = steal, negative = reach), but
in real points, not board units -- the two metrics are complementary and can
be read side by side.

## Phase breakdown

`scripts/draft_report_2026.py`'s `build_points_value_team_summary` (FFA-086,
script layer, not the core `players` package) buckets each team's scoreable
picks into **early/mid/late thirds** of the draft by round, independent of
league size:

- **Early phase:** picks in rounds 1-N/3
- **Mid phase:** picks in rounds N/3+1 to 2N/3
- **Late phase:** picks in rounds 2N/3+1 to N

For each phase, reports:
- Pick count (scoreable picks only, excluding keepers and unscored players)
- Average `pick_value` (board-relative)
- Average `pick_value_points` (real-points-scale, if a fitted curve is available)

This breaks down *where* in the draft a team won or lost value (e.g., "strong
in the early rounds, weak mid-draft") rather than reporting only a single
blended number. A team's total `total_points_value` (sum of `pick_value_points`
across scoreable picks) is also reported.

## Exceptions and caveats

- **Sign bug, now fixed.** An earlier version of `pick_value` inverted the
  sign and used raw pick-position diffs instead of a value curve. This bug
  affected every published grade until FFA-084; all subsequent grades use the
  corrected formula. Do not use pre-FFA-084 numbers for comparison.
- **Keepers are excluded.** A keeper's "cost" (its draft slot) is not a live
  market signal. Picks marked `is_keeper == True` are excluded from `pick_value`,
  `pick_value_points`, and team grades. The pick itself remains visible (with
  its other fields intact) so a reader can see what the player would have
  graded as if drafted normally.
- **Points curve is a rough estimate.** The fitted curve is trained on a single
  season (~130-160 non-keeper picks for the leagues this codebase covers),
  individual player outcomes are noisy (injuries, breakouts, busts), and
  `r_squared` typically ranges 0.3-0.4 on real data. This is explicitly not a
  precise projection but a better-than-nothing estimate, and **must be reported
  alongside any number it produces** (the HTML template includes `n_picks` and
  `r_squared` inline). The curve has not yet been validated against 2026 results.
- **K/DEF are excluded from curve fitting.** Same rationale as `draft_board.py`'s
  `DEFAULT_RETROSPECTIVE_EXCLUDED_POSITIONS`: 2025 scoring for these positions
  is incompletely mapped, so no reliable historical value exists to fit against.

## Related tickets

- **FFA-077 through FFA-083** -- 2026 draft grading pipeline: normalize picks,
  score each pick's value, build per-team grades and talking points, render
  cross-league leaderboards and per-league HTML artifacts.
- **FFA-084** -- Fix draft `pick_value` sign bug and ordinal-scale error, switch
  to board value-curve interpolation (see Exceptions above).
- **FFA-085** -- Fit real-points-scale draft value curve from prior-season
  history, add complementary `pick_value_points` metric.
- **FFA-086** -- Add phase-breakdown summaries to draft reports, explain where
  teams won/lost value by draft stage, update HTML templates with new metrics.
