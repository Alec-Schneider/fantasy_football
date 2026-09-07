# 2026 draft boards -- New Wave Friends League & Just Here For The Zipline

Companion page to [`docs/draft-board-2026.md`](draft-board-2026.md), which
documents the market + retrospective blend methodology (FFA-075/FFA-076)
used for the NWC FFL board. That methodology -- composite rank formula,
VOR, the availability model, the "why K/DEF are market-only" caveat -- is
shared verbatim by these two leagues; this page covers what's different:
their settings, their slots, and how to rebuild either board.

## The boards

Both are rendered by `scripts/draft_board_artifact.py` and published as
Artifacts. Their position-cliff panels show the **top 30 at each position**
(the NWC board showed 14); everything else is the same page shape.

| | New Wave Friends League | Just Here For The Zipline |
| --- | --- | --- |
| `league_id` (2026) | `1389754945892274176` | `1389707229824815104` |
| Teams | 10 | 10 |
| Scoring | Full PPR (`rec` = 1.0) | Half PPR (`rec` = 0.5) |
| Roster | QB, RB, RB, WR, WR, TE, FLEX, FLEX, K, DEF, 5 BN | QB, RB, RB, WR, WR, TE, FLEX, FLEX, K, DEF, 6 BN |
| Draft rounds | 15 | 16 |
| Draft slot | **3** (provisional -- see below) | **10** (assigned by Sleeper) |
| Keepers on 2026 rosters | None | None |
| Board pool | 509 ranked, 258 market-priced | 509 ranked, 222 market-priced |

Both leagues run **two FLEX slots**, not the NWC board's one -- this
doubles the RB/WR/TE starter count used for VOR's replacement-level cutoff
(`cutoff = num_teams * starters(position)`), so RB/WR/TE VOR compresses
faster down the board than on the 12-team, 1-FLEX NWC board. This is a
real difference in replacement level, not an artifact to correct for.

The two leagues also draw from **different market pools**: FantasyFootball-
Calculator ADP is fetched per scoring format, so New Wave's board is built
on 10-team full-PPR ADP and Zipline's on 10-team half-PPR. Pass-catching
backs and high-volume receivers price higher on the New Wave board as a
result (CeeDee Lamb 10.4 vs 12.0; De'Von Achane 9.7 vs 10.9), and
low-target backs price lower (Saquon Barkley 18.4 vs 16.5).

### New Wave's slot is provisional

Sleeper has not assigned New Wave's 2026 draft order (`draft_order` is
`null`, status `pre_draft`), so slot 3 is a stand-in and the page says so.
The full board, the value cliffs and the market value/reach tables do not
depend on the slot -- only the pick numbers and the per-turn availability
probabilities do. Rerun with the real slot when the order is set.

Zipline's order *is* assigned: `schneidbaby` (`865610532865060864`) drafts
from slot 10 of 10, the wheel -- picks 10, 11, 30, 31, ... back-to-back
pairs all draft.

## Rebuilding a board

```bash
.venv/bin/python scripts/draft_board_artifact.py \
  --league zipline --slot 10 --top-per-position 30

.venv/bin/python scripts/draft_board_artifact.py \
  --league new-wave --slot 3 --top-per-position 30 --slot-provisional
```

Known slugs are `nwc`, `new-wave`, and `zipline` (see `LEAGUES` in the
script), each of which supplies teams / rounds / scoring / roster
positions / prior CSV. Any other league works by passing those explicitly:

```bash
.venv/bin/python scripts/draft_board_artifact.py \
  --slot 7 --teams 12 --rounds 15 --scoring ppr --scoring-label "Full PPR" \
  --roster-positions "QB,RB,RB,WR,WR,WR,TE,FLEX,K,DEF,BN,BN,BN,BN,BN" \
  --prior-csv scripts/output/draft2026/<league>_2025_prior_<id>.csv \
  --league-title "Some Other League" --short-title "Other" \
  --out-prefix Other
```

Useful flags: `--top-per-position` (cliff depth, default 30),
`--board-top` (full-board rows, default 180), `--exclude-id` (repeatable,
for keepers), `--slot-provisional` (adds the stand-in-slot note),
`--no-market-refresh` (cache-only ADP/ECR).

Each run writes three files to `scripts/output/draft2026/` (gitignored):

- `<prefix>_2026_slot<N>of<T>_board.csv` -- full ranked board
  (`GUIDE_REPORT_COLUMNS` from `draft_guide_2026.py`).
- `<prefix>_2026_slot<N>of<T>_availability.csv` -- `P(available)` per
  player at each of your picks.
- `<prefix>_2026_slot<N>of<T>_artifact.html` -- the standalone page,
  ready to publish as an Artifact.

`scripts/draft_guide_2026_league.sh` still exists for the console-only
pick-by-pick report; the artifact script supersedes it for anything you
want to read as a page.

### Regenerating the 2025 prior

The FFA-073 retrospective value score -- the 25%-weight input to the
composite rank -- doesn't depend on draft slot, so it is built once per
league and reused:

```bash
.venv/bin/python scripts/composite_ranking_report.py \
  --league-id 1260307567133859840 --league-name "New_Wave_2025_prior" \
  --league-id 1262800342051999744 --league-name "Zipline_2025_prior" \
  --out-dir scripts/output/draft2026 --phase all --top 2000
```

Note these are the **2025** league IDs, not the 2026 ones in the table
above.

## Verification notes

Both boards were checked against the board CSVs and live Sleeper settings
before publishing. Worth knowing:

- **Overall rank is by `draft_score`, not VOR.** Rows in the full board are
  therefore not strictly VOR-descending; a player can rank above another
  with higher VOR when the market prices him higher.
- **Retrospective join coverage** (top 180): New Wave 163 blended / 17
  market-only; Zipline 159 / 21. Every K and DEF is market-only by design;
  the rest are rookies and players with no 2025 snaps.
- **Sleeper's league-level `settings.draft_rounds` is unreliable** --
  Zipline's reports `3`. The draft object's `settings.rounds` (16) is
  authoritative and is what the `LEAGUES` entries are keyed to.
- **Same-name collision in the player pool**: two distinct "Antonio
  Williams" (WR/WAS `13301`, RB/FA `7203`). Both fall outside the top 180
  on both boards, so neither surfaces on a page, but a name-only lookup
  against the CSVs will hit both.

## Related tickets

- **FFA-073** -- League-wide composite player value ranking (the 2025
  retrospective score used as the prior CSVs above).
- **FFA-074** -- League-wide free-agent player pool coverage.
- **FFA-075** -- 2026 draft market data (ADP + ECR ingestion) -- shared,
  unmodified, across all three leagues.
- **FFA-076** -- 2026 draft board build (`build_draft_board`), with the
  `roster_positions` passthrough that makes it correct for non-NWC lineups.
