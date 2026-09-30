# Player coverage (FFA-103, FFA-109)

"Is every Sleeper player accounted for?" A player can leave the pipeline at
four points: the free-agent rules, the roster population, the Sleeper to
nflverse ID crosswalk, and the stats themselves. Before these tickets, every
one of those exits was silent.

## What changed

| Where | What |
|---|---|
| `players/free_agents.py` | **FFA-103.** `build_free_agent_pool(..., require_nfl_team=True)` drops unsigned players (`team: None`). DEF entries always pass: their id is the team code. |
| `players/free_agents.py` | **`build_player_universe(raw_rosters, player_catalog, roster_positions, crosswalk=None, ownership_lookup=None)`** returns every rostered player (any capacity, any status, team or position) plus every free agent, with `is_rostered` and `roster_id`. It replaces `build_free_agent_pool([], ...)` as the league-wide population. |
| `players/crosswalk.py` | **Name fallback.** `build_name_match_crosswalk` / `extend_crosswalk_with_name_matches` map nflverse players neither ID source covers, matching on name, position and team. `build_robust_id_crosswalk(..., nflverse_stats=...)` applies it. |
| `players/coverage.py` | `build_forward_coverage_audit` (Sleeper to nflverse, one `coverage_reason` per player) and `build_reverse_coverage_audit` (nflverse production mapped to no Sleeper id). |
| `scripts/player_coverage_report.py` | Runs both audits for every preset league, before and after the fallback, and writes CSVs to `scripts/output/coverage/`. |

The `coverage_reason` definitions and their precedence are in
`players/coverage.py`'s module docstring. The name-fallback rules and its
toy example are in `players/crosswalk.py`'s "last-resort" section.

## Running it

```bash
.venv/bin/python scripts/player_coverage_report.py --season 2026
```

The report uses live Sleeper rosters and league settings, and local caches
for everything else (the Sleeper catalog, DynastyProcess IDs, and nflverse
stats for the season and the one before). None of the caches is
TTL-checked, so refresh them first.

## Measured on 2026-09-29 (after week 3)

- **FFA-103:** each league's free-agent pool drops about 2,160 teamless
  players (NWC 2,772 to 613). None of them has a 2026 stat row. A raw
  dashboard-style top 50 carried 30, 11 and 17 teamless players (NWC, New
  Wave, Zipline) before the guard, and 0 after.
- **Universe:** the old `[]` population dropped 10, 7 and 8 rostered
  players, all of them marked `Inactive` by Sleeper while on NFL IR or Out.
  Examples are A.J. Brown, De'Von Achane, Jaxson Dart and Jordyn Tyson. The
  universe keeps all of them, plus every rostered K and DEF.
- **Crosswalk:** 14 name-fallback matches, all rookies or young players
  whose DynastyProcess row had a `gsis_id` but no `sleeper_id`. The
  DynastyProcess birthdate matched Sleeper's for every one.
  - Unmapped 2026 player-weeks with a target, carry, pass attempt or kick
    went from 13 to 1, and their points from about 82 to about 2.5,
    depending on the league's scoring.
  - Rostered players with no `gsis_id` went from 1 (Trey Smack, K, in NWC
    and Zipline) to 0.
  - No top-100 scorer was unmapped either before or after.
  - The one remaining orphan is DJ Herman (RB, MIA), who is not in
    Sleeper's catalog at all.
