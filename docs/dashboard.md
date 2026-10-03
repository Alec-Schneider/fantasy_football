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

Then the snap-count and expected-points caches the usage model reads
(`docs/usage-data.md`):

```bash
.venv/bin/python scripts/fetch_usage_seasons.py --start 2026 --end 2026 --refresh-season 2026
```

nflverse publishes a week's stats a day or two after the games. Refreshing
on a Monday morning gets you Thursday/Sunday but not that night's MNF;
Tuesday is the day a refresh picks up the complete week. Refreshing earlier
is safe (see below) — it just publishes one week fewer.

### 2. Build the bundle

```bash
.venv/bin/python scripts/build_dashboard.py
```

Writes `scripts/output/dashboard/bundle.json` (~550 KB) and prints which
league-weeks still have no recap written. It also writes one full-universe
valuation per league — see "Full-universe valuation" below.

A week only counts as complete when **both** of these hold (FFA-108):

1. every contested fantasy matchup in it has non-zero scores on both sides,
   and
2. every NFL game scheduled that week has a final score in the nflverse
   schedule cache (`completed_nfl_weeks` in
   `players/opponent_strength.py`).

The first test alone was not enough: a week missing only its Monday night
game passes it, because every team already has *some* points. On
2026-09-21 that published week 2 as final before MNF with two **wrong
winners**, which propagated into the standings, the power rankings and the
written recaps. The second test closes it — 15 of 16 games scored is not a
complete week — so running the build mid-week is now safe: an unfinished
week is held back, not published with partial scores. The build prints the
NFL weeks it considers final (`NFL weeks final in the schedule cache: ...`).

Because the check reads the schedule cache, a stale `games.csv` holds weeks
back rather than letting them through. If a week you know is over is
missing, refresh the caches (step 1) and rebuild.

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

The page has two tabs, and both are driven by the same league switcher.
The page remembers which tab you last opened.

**Matchup** is the default tab. It shows the week about to be played (the
same week as the lineup call) from the point of view of your head-to-head
matchup. See "The Matchup tab" below.

**Season** is split by a real distinction, not by visual convenience:

- **Week N — what happened.** Scoreboard, recap, standings and power
  rankings, all recomputed for whichever week is selected. Standings come
  from `build_standings_through_week` (FFA-102), so an earlier week shows
  that week's table rather than today's.
- **Week N+1 — what to do.** The waiver board and the lineup call. These
  are always for the week about to be played. They do not follow the week
  picker, because there is no useful sense in which you can set last
  week's lineup.

## The Matchup tab

Epic 11 (FFA-113–118). The design and the bundle contract are in
`docs/matchup_tab.md`.

The tab is meant to be read at both refresh points. Before kickoff it is a
preview. After the mid-week rebuild it shows the score so far plus a
projection for everyone yet to play.

- **Scoreboard.** Both teams' live Sleeper scores, their projected finals,
  how many starters each has still to play, and the win probability.
- **Lineups, head to head.** The lineup *actually set in Sleeper* for each
  side, slot by slot. Each row shows the NFL matchup, kickoff time or
  Live/Final/Bye, injury, projection and actual points. Rows are tinted by
  the projected edge.
- **Positional edge.** Projected points, you minus the opponent, per slot
  group.
- **Alerts.** Out, IR or bye starters, empty slots and unprojected
  starters on either side. Also the gap between your set lineup and the
  recommended one, and how much your opponent is leaving on their bench.
- **Season comparison.** Through the last completed week: record, rank,
  PF/PA, PPG, last-3 PPG, high and low, weekly SD, all-play and power rank
  (`analytics/matchup_preview.py`). Also each team's started points per
  game by position with league rank, scored by Sleeper itself
  (`build_sleeper_scored_player_weeks`), and this season's head-to-head
  meetings.
- **Benches**, collapsed.

**How the projected final is built** (`players/matchup_projection.py`).
It is the sum over a side's starters of their expected points:

- A player whose NFL game has kicked off counts his live Sleeper points.
- An available player yet to play counts his projection.
- An empty slot, or an unavailable or unprojected starter, counts zero.

The projection is the `lineup_ppg` column the lineup call solves on, so
the two tabs never disagree about a player.

A game in progress is scored at its live points. That understates the
game, since its remaining minutes are not projected. The two scheduled
refreshes never land mid-game.

"Players to play" counts the starters still carrying a projection, and
those are the starters the win probability's variance comes from.

Each side's **optimal total** is the lineup solver run over that roster
with locks and availability applied. For you it is the Season tab's
recommended lineup. For the opponent it is how many points they are
leaving on the bench.

**Win probability** (FFA-114, `docs/win-probability.md`). Each team's
final score is modelled as normal. Its mean is the projected final, and
its variance sums a fitted per-player single-week variance over the
starters still to play. Measured on 203 games from the three leagues'
2025 seasons, it beats a coin flip (Brier 0.234 vs 0.250, log loss 0.659
vs 0.693), and the favorite won 63.5% of the time. That is a real but
modest edge. Read 60% as "slight favorite", not as a lock.

The parameters come from `scripts/fit_win_probability.py`, saved as
`.cache/nflverse/win_probability_parameters.json`. Fitting is a one-off,
not part of the weekly refresh. Rerun it only if the projection pipeline
changes. The build prints `win probability: calibrated, ...`. If the file
is missing or uncalibrated, it says so, and the page shows only the
projected margin. Week 1 never shows a probability either, because the
calibration starts at week 2.

## Who is valued, and by which model

Every number is computed over one population: the **player universe**
(`build_player_universe`, FFA-109) — every rostered player whatever his
status (an Inactive player in an IR slot is still on his manager's roster),
plus every free agent the package's pool rules admit, which now require an
NFL team (FFA-103). That universe sets each position's replacement level
and is what the projections are built for.

Each position is projected by exactly one model:

- **QB, RB, WR, TE** — the waiver pipeline's skill-player model: the
  per-position blend of the opportunity-first usage model and the
  empirical-Bayes projection (FFA-111), with a fitted absent-prior line for
  a player with no games and fewer than 4 prior-season games (FFA-104). See
  `docs/valuation-model.md`. The waiver board and the lineup call are built
  from the same inputs, so a player's projection is the same on both. The
  build prints which model it ran (`usage model: fitted; snap/xFP rows ...`).
  A missing parameter file falls back to empirical Bayes alone, and a missing
  snap cache to the no-snap usage model; both are less accurate.
- **K and DEF** — `players/kicker_defense.py` (see `docs/kicker-defense.md`).
  Its rest-of-season rate drives the waiver board, the VORP and the moves;
  its this-week projection (nudged by the betting market's implied points,
  0.0 on a bye) drives the lineup call.

VORP for every position comes from the same `player_value` function, so a
kicker's replacement level is the league's last starting kicker (one per
team) and the board ranks all positions on one basis. Expect K and DEF
free agents to rank on small numbers: in NWC at week 4 the best free-agent
kicker was Spencer Shrader at 8.57 per game, +0.7 over replacement.

Before building the universe the crosswalk is extended with verified name
matches (`extend_crosswalk_with_name_matches`), which recovers players the
ID sources miss — NWC's rookie kicker Trey Smack among them.

## Full-universe valuation

Each build writes `<out-dir>/valuations/<slug>_week<N>.csv`, `N` being the
week about to be played: every universe player (about 800 per league) with
projection, VORP, overall and positional rank, rostered state and owner,
injury and bye. It is the complete table the page only samples, and it is
not rendered on the page.

## Who can play (FFA-107)

The lineup and the moves use the package's availability rule
(`players/availability.py`), not a local filter:

- **Out, Doubtful, COV** — out for the coming week only.
- **IR, PUP, NA, Sus/Suspended, DNR** — assumed out for four weeks,
  counting the coming one. That is the NFL's minimum stay on
  reserve/injured, PUP and NFI, so it is a lower bound: a season-ending
  injury is understated. Sleeper's catalog carries no injury start date to
  do better.
- **Questionable** — starts, flagged.
- **Bye** — from the NFL schedule, that week only.

The recommended lineup is solved for the coming week with unavailable
players excluded. The **moves** are scored over the rest of the fantasy
regular season — the sum of each week's best lineup, with each player's
week-by-week availability — and reported as a per-week average plus the
total. So a player who is merely Out or on bye *this* week is never offered
as a free drop, and a bench player who covers a bye has real value.
IR-slot (`reserve`) players are never proposed as drops, since dropping one
frees no bench spot, and a roster with an open spot adds without a drop. A
rostered player with no projection is never the drop either — his value is
unknown, not zero. If the solve leaves a slot empty, the page shows your
available-but-unprojected player there (flagged "no projection") rather
than telling you to bench him.

Free agents with a long-term status (IR, PUP, NA, suspended) stay on the
waiver board, flagged, but are not offered as moves: they are stashes, and
the four-week lower bound would overrate a season-ending injury.

A slot nobody on your roster can fill that week — your starter is on bye
or hurt and there is no backup — is scored at that position's
**replacement level**, what you could stream off the waiver wire, not at
zero. (A `FLEX` takes the cheapest of the positions it accepts.) So a
backup is worth only his margin over a streamer, and one who projects
below the streamer is worth nothing. The levels are the same replacement
levels the board's VORP uses and are carried in the bundle as
`lineup.streaming_values`.

A kicker or defense move is also scored as a **swap for the one you
roster**, not against your cheapest bench player — a kicker is only ever
added to replace a kicker.

## Refreshing mid-week: game locks

Rebuilding between Thursday night and Monday night is supported, and is
the way to pick up Friday's final injury designations. Once an NFL game
kicks off Sleeper locks its players, and the build honours that
(`started_nfl_teams` in `players/opponent_strength.py`, which reads the
schedule cache's scores and kickoff times):

- A locked player **in your current lineup** keeps his slot and scores his
  actual points (Sleeper's live `players_points`). The headline projection
  is those points plus the projection for the remaining slots.
- A locked player **on your bench** cannot come in. He is listed with the
  unavailable players, showing what he scored.
- A locked **free agent** cannot be added until waivers run. He stays on the
  waiver board marked "played" and is left out of the moves. A locked
  rostered player is never the drop. While every kicker (or defense) you
  roster is locked, no kicker (or defense) swap is offered.
- The "Week N vs" stat shows the live score so far.

Projections are unaffected: they read weeks up to the last *completed*
week, so a partial week's stats never leak in. One known approximation
remains. The moves' rest-of-season scorer uses one slot list for every
week, so in the coming week alone it may bench a locked starter for an
add. The error is at most one week of the horizon, and it needs a free
agent projected above a locked starter he could replace. The build
records the locked teams (`lineup.locked_teams`) so this can be checked.

## Known limitations

- **Kickers are close to a coin flip.** The K model only ties the
  positional average out of sample this early in a season
  (`docs/kicker-defense.md`); a kicker "upgrade" of under a point a week is
  within noise.
- **The streamer is the replacement level, not the actual wire.** It is
  the league's last starter at the position, which in a deep league can be
  rostered: in NWC at week 4 the QB level (18.2) is above the best free
  agent QB (16.6), so QB bye cover is valued slightly low. At K, DEF and
  TE the wire is currently above replacement. It is one number per
  position for the whole season, not who is available in a given week.
- **Defense-vs-position is a weak signal this early.** It is shrunk toward
  1.0 by an unfitted prior (`DEFAULT_DVP_SHRINKAGE_GAMES`), so after two
  weeks `matchup_adjusted_ppg` sits within a rounding error of
  `projected_ppg`. It will mean more in November.
- **Injury data is only as fresh as the Sleeper catalog.** Step 1 is not
  optional.
