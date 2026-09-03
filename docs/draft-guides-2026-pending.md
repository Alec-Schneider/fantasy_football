# 2026 draft guides -- New Wave Friends League & Just Here For The Zipline

Companion page to [`docs/draft-board-2026.md`](draft-board-2026.md), which
documents the market + retrospective blend methodology (FFA-075/FFA-076)
used for the NWC FFL board. That methodology -- composite rank formula,
VOR, the availability model, the "why K/DEF are market-only" caveat -- is
shared verbatim by these two leagues; this page only covers what's
different: their settings, and why the boards themselves aren't built yet.

## Why these boards aren't in `docs/` yet

A draft board's pick-by-pick sections (targets at each turn, "your N
picks") are built around one specific snake-draft slot. Sleeper has not
assigned a draft order for either league's 2026 draft (`draft_order` is
`null`, draft status `pre_draft`), and slot 5 (the NWC board's slot) is
not a safe stand-in -- both leagues are 10 teams, not 12, so the slot
numbering and pick gaps don't match anyway.

Rather than publish a board built on a guessed slot, this page ships the
runnable command. Once your Sleeper draft order is set (or your league
agrees on slots in chat before Sleeper randomizes), run it with the real
slot number and the board/CSV outputs and console pick guide come out
identical in shape to the NWC one.

## League settings (2026, confirmed via Sleeper)

| | New Wave Friends League | Just Here For The Zipline |
| --- | --- | --- |
| `league_id` (2026) | `1389754945892274176` | `1389707229824815104` |
| Teams | 10 | 10 |
| Scoring | Full PPR (`rec` = 1.0) | Half PPR (`rec` = 0.5) |
| Roster | QB, RB, RB, WR, WR, TE, FLEX, FLEX, K, DEF, 5 BN | QB, RB, RB, WR, WR, TE, FLEX, FLEX, K, DEF, 6 BN |
| Draft rounds | 15 | 16 |
| Keepers found on 2026 rosters | None | None |

Both leagues run **two FLEX slots**, not the NWC board's one -- this
doubles the RB/WR/TE starter count used for VOR's replacement-level cutoff
(`cutoff = num_teams * starters(position)`), so RB/WR/TE VOR compresses
faster down the board than on the 12-team, 1-FLEX NWC board. This is a
real difference in replacement level, not an artifact to correct for.

Unlike NWC (two rostered keepers not reflected in its 2026 draft config),
neither league's 2025-season rosters carry a Sleeper `keepers` list on the
2026 roster objects, so no `--exclude-id` is needed here.

## What was already built (no slot required)

The FFA-073 2025 retrospective value score -- the 25%-weight input to the
composite rank -- doesn't depend on draft slot, so it's already generated
locally (League-wide, free-agent-inclusive, full 2025 season -- 646 ranked
players each, same scope as the NWC prior):

```text
scripts/output/draft2026/New_Wave_2025_prior_1260307567133859840.csv
scripts/output/draft2026/Zipline_2025_prior_1262800342051999744.csv
```

`scripts/output/` is gitignored, so these aren't checked into the repo --
they're reproducible on demand via the command below and the wrapper
script picks them up from that path automatically. Regenerate them (e.g.
after a stats refresh) with:

```bash
.venv/bin/python scripts/composite_ranking_report.py \
  --league-id 1260307567133859840 --league-name "New_Wave_2025_prior" \
  --league-id 1262800342051999744 --league-name "Zipline_2025_prior" \
  --out-dir scripts/output/draft2026 --phase all --top 2000
```

`draft_guide_2026.py` also gained a `--roster-positions` flag (it
previously hardcoded the NWC 1-FLEX/12-team lineup for its VOR baseline
regardless of `--teams`), so it can build a correct board for any league
shape.

## Run it once you know your slot

A wrapper script bakes in each league's teams/scoring/roster/rounds/prior
CSV, so the only thing you supply is `--slot`:

```bash
./scripts/draft_guide_2026_league.sh new-wave --slot <N>
./scripts/draft_guide_2026_league.sh zipline  --slot <N>
```

This writes, per league, to `scripts/output/draft2026/`:

- `<prefix>_2026_slot<N>of10_board.csv` -- full ranked board (same
  columns as `GUIDE_REPORT_COLUMNS` in `draft_guide_2026.py`).
- `<prefix>_2026_slot<N>of10_availability.csv` -- `P(available)` per
  player at every one of your picks.
- A console pick-by-pick report (top targets per position at each of your
  picks, K/DEF hidden until the final 3 rounds), same as the NWC guide.

Add `--exclude-id <sleeper_player_id>` (repeatable) if a keeper turns up
before you run it, and `--no-market-refresh` to force cache-only ADP/ECR
data instead of re-fetching.

Once a board is generated, turn it into a published page the same way the
NWC one was built (see [`docs/draft-board-2026.md`](draft-board-2026.md)
and `docs/draft-board-2026.html` for the target shape) and add its own
methodology page here if its exceptions differ from NWC's.

## Related tickets

- **FFA-073** -- League-wide composite player value ranking (the 2025
  retrospective score used as the prior CSVs above).
- **FFA-074** -- League-wide free-agent player pool coverage (the prior
  CSVs' 646-player, free-agent-inclusive scope).
- **FFA-075** -- 2026 draft market data (ADP + ECR ingestion) -- shared,
  unmodified, across all three leagues.
- **FFA-076** -- 2026 draft board build (`build_draft_board`) -- extended
  here with a `roster_positions` passthrough in `draft_guide_2026.py` so
  it isn't hardcoded to NWC's lineup.
