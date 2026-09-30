# Usage data: snap counts and expected points (FFA-110)

`fantasy_analyzer.players.usage` joins two opportunity sources onto one
GSIS-keyed player-week table. The design notes (id mapping, scoring system,
null semantics) live in that module's docstring; this page covers the
workflow and the numbers.

## Sources and caches

| Source | Cache file | Seasons published | Key |
|---|---|---|---|
| nflverse snap counts (PFR) | `.cache/nflverse/snap_counts_<season>.csv` | 2013+ (2012 header-only) | `pfr_player_id` |
| ffopportunity `ep_weekly` | `.cache/ffopportunity/ep_weekly_<season>.csv` | 2006+ | `player_id` (GSIS) |
| DynastyProcess ID crosswalk | `.cache/id_crosswalk/db_playerids.csv` | n/a | `pfr_id` -> `gsis_id` |

## Refreshing

```bash
# first-time backfill (populated 2014-2026 on 2026-09-29)
.venv/bin/python scripts/fetch_usage_seasons.py --start 2014 --end 2026

# weekly, once the week is final (see docs/dashboard.md)
.venv/bin/python scripts/fetch_usage_seasons.py --start 2026 --end 2026 --refresh-season 2026
```

`load_usage_player_weeks` never downloads anything. It raises
`FileNotFoundError` for a season that was never fetched, and returns no rows
for a season the script cached as unpublished.

## Using it

```python
from fantasy_analyzer.players.usage import attach_usage, load_usage_player_weeks

usage = load_usage_player_weeks(range(2016, 2027))   # full snap universe
scored = attach_usage(scored_player_weeks, usage)     # enrich stat rows only
```

`build_scored_player_weeks` always names its id column `player_id` (a GSIS id
for raw nflverse input), which is `attach_usage`'s default.

Things to know:

- **`ep_*_fantasy_points*` are full PPR.** Re-score the `ep_*_exp`
  components for a half-PPR league.
- **`ep_total_fantasy_points_exp_team` excludes passing xFP.** An xFP share is
  `(ep_rec_fantasy_points_exp + ep_rush_fantasy_points_exp) /
  ep_total_fantasy_points_exp_team`.
- **Null means no source row, never zero.** A week with `offense_snaps > 0`
  and null `ep_*` is a real zero-opportunity week.
- **`attach_usage` cannot add zero-usage weeks.** nflverse stats have no row
  for a player who ran routes and recorded nothing, which covers 692-932 skill
  snap-weeks per full season. Start from `load_usage_player_weeks` if you need
  those weeks.

## Coverage (measured 2026-09-29)

Denominator: nflverse regular-season player-weeks at QB/RB/WR/TE with at
least one target, carry or pass attempt.

| Season | Stat rows | With snap row | Crosswalk only | With ep row | Unmapped pfr ids w/ offense snaps (skill) |
|---|---|---|---|---|---|
| 2016 | 4,903 | 99.98% | 99.49% | 100.00% | 203 (2) |
| 2017 | 4,924 | 100.00% | 99.51% | 100.00% | 183 (2) |
| 2018 | 4,889 | 99.96% | 99.51% | 100.00% | 182 (3) |
| 2019 | 4,893 | 99.98% | 99.94% | 100.00% | 192 (2) |
| 2020 | 5,048 | 99.88% | 99.88% | 100.00% | 245 (6) |
| 2021 | 5,300 | 100.00% | 99.94% | 100.00% | 244 (7) |
| 2022 | 5,270 | 100.00% | 99.98% | 100.00% | 233 (6) |
| 2023 | 5,292 | 99.96% | 99.96% | 100.00% | 230 (6) |
| 2024 | 5,234 | 99.98% | 99.96% | 100.00% | 250 (4) |
| 2025 | 5,279 | 99.96% | 99.91% | 100.00% | 260 (3) |
| 2026 (wk 1-3) | 940 | 100.00% | 99.68% | 100.00% | 195 (3) |

Almost every unmapped pfr id is an offensive lineman. DynastyProcess has no
`pfr_id` for them, and linemen have no stats rows for the name fallback to
match. The name fallback agreed with nflverse's own `players` table on 365 of
365 checkable pfr ids (2016-2026).
