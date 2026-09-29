# Season dashboard

One page covering all three 2026 leagues: week-by-week results, standings,
recap commentary and power rankings, plus the waiver board and lineup call
for the week about to be played.

Published at <https://claude.ai/artifact/VdWAVYzpoJndkfzXMFHuVX>.

## Why it is a static page

The page is a published Artifact. Its CSP blocks outbound requests, so it
cannot call Sleeper or nflverse itself — and the waiver board could not use
them directly anyway, since it depends on the local nflverse, crosswalk and
shrinkage caches. Everything the page can ever show is baked in at publish
time.

So "refresh" means: re-run the pipeline locally, re-render, republish to the
same URL.

## Refreshing

Four steps. Ask Claude in a session to run them, or run them yourself.

### 1. Refresh the caches

None of the caches are TTL-checked, and a stale Sleeper catalog silently
produces wrong NFL teams and wrong injury statuses — which the dashboard
now relies on for its start/sit calls.

```python
from fantasy_analyzer.sleeper.cache import refresh_player_cache
from fantasy_analyzer.sleeper.client import SleeperClient
from fantasy_analyzer.players.nflverse_cache import refresh_player_stats_cache
from fantasy_analyzer.players.nflverse_client import NflverseClient
from fantasy_analyzer.players.nflverse_schedule_cache import refresh_games_cache
from fantasy_analyzer.players.nflverse_schedule_client import NflverseScheduleClient
from fantasy_analyzer.players.id_crosswalk_cache import refresh_player_ids_cache
from fantasy_analyzer.players.id_crosswalk_client import PlayerIdCrosswalkClient

refresh_player_cache(SleeperClient())
refresh_player_stats_cache(NflverseClient(), 2026)
refresh_games_cache(NflverseScheduleClient())
refresh_player_ids_cache(PlayerIdCrosswalkClient())
```

nflverse publishes a week's stats a day or two after the games. Refreshing
on a Monday morning gets you Thursday/Sunday but not that night's MNF;
Tuesday is the safe day for a complete week.

### 2. Build the bundle

```bash
.venv/bin/python scripts/build_dashboard.py
```

Writes `scripts/output/dashboard/bundle.json` (~350 KB) and prints which
league-weeks still have no recap written. A week only counts as complete
when every contested matchup in it has non-zero scores on both sides, so a
week in progress is skipped rather than shown at 0–0.

**That completeness test is not sufficient, and this matters.** A week that
is only missing its Monday night game passes it — every team already has
*some* points — so the week publishes as final with partial scores. On
2026-09-21 this put two games on the page with the **wrong winner**, which
then propagated into the standings, the power rankings and the written
recaps. Until FFA-108 lands, the "refresh on Tuesday" rule below is
load-bearing, not advice. To check by hand, compare the scored-game count
in the schedule cache against the scheduled count for that week:

```python
import pandas as pd
g = pd.read_csv(".cache/nflverse/games.csv")
g = g[(g["season"] == 2026) & (g["week"] == 2)]
print(len(g), g["home_score"].count())   # complete only when these match
```

### 3. Write the new week's recaps

The bundle carries a ready-to-paste `commentary_prompt` per league-week.
Claude writes the recap from that prompt and saves it to:

```
scripts/output/dashboard/commentary/<slug>_week<N>.md
```

Then re-run step 2 to fold the new files in. Past weeks' recaps persist on
disk, so this only ever costs the newest week.

This deliberately does not call the Anthropic API. The package *can*
(`fantasy-analyzer commentary recap ... --generate`), but that needs
`ANTHROPIC_API_KEY` and bills per run; a Claude session doing the refresh is
already capable of writing them.

### 4. Render and republish

```bash
.venv/bin/python scripts/dashboard_artifact.py
```

Writes `scripts/output/dashboard/dashboard.html` with the bundle inlined.
Republish that file to the **existing** URL (pass it as `url`) so the link
stays stable.

## What the page shows

The page is split by a real distinction, not by visual convenience:

- **Week N — what happened.** Scoreboard, recap, standings and power
  rankings, all recomputed for whichever week is selected. Standings come
  from `build_standings_through_week` (FFA-102), so an earlier week shows
  that week's table rather than today's.
- **Week N+1 — what to do.** The waiver board and the lineup call. These
  are always for the week about to be played; they do not follow the week
  picker, because there is no useful sense in which you can set last week's
  lineup.

## Known limitations

- **No D/ST or kickers anywhere.** nflverse publishes no weekly stat rows
  for team defenses or kickers, so they have no projection. They are
  excluded from the lineup recommendation and the add/drop search rather
  than silently ranked at zero, and the page says so.
- **The board is filtered, not fixed.** Two measured upstream defects
  (FFA-103, FFA-104) would otherwise put teamless and no-data players at the
  top of the board. `build_dashboard.py`'s `WAIVER_QUALITY_FILTER` removes
  them at display time. Delete it once those tickets land.
- **Defense-vs-position is a weak signal this early.** It is shrunk toward
  1.0 by an unfitted prior (`DEFAULT_DVP_SHRINKAGE_GAMES`), so after two
  weeks `matchup_adjusted_ppg` sits within a rounding error of
  `projected_ppg`. It will mean more in November.
- **Injury data is only as fresh as the Sleeper catalog.** Step 1 is not
  optional.
