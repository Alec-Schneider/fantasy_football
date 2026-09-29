# Live in-season power rankings (`scripts/live_power_rankings.py`)

Ad hoc analysis script -- not a package module, not on the AGENTS.md ticket
board, no tests -- that answers a different question than the package's own
documented power ranking
([`analytics/power_rankings.py`](../src/fantasy_analyzer/analytics/power_rankings.py),
FFA-056, see [`docs/analytics.md`](analytics.md#power-rankings-ffa-056)):

- **`analytics.power_rankings()` (FFA-056)** answers *"who has performed
  best so far this season"* -- it needs a meaningful sample of played weeks
  (win%, all-play win%, consistency) and is close to meaningless after one
  week.
- **This script** answers *"who is the strongest team right now"*, in the
  first week or two of a season, by blending preseason roster quality with
  the one week of results available and a forward-looking projection. It
  exists specifically to be usable when FFA-056's model can't be yet.

It currently covers only the three leagues that already have a 2026 draft
grade report (`scripts/draft_report_2026.py`): NWC FFL, New Wave, and
Zipline. The other two 2026 leagues on the account (NWC Guillotine '26, BBC
weird league) were excluded from that draft-grading pipeline already (see
`scripts/draft_league_presets.py`'s module docstring), so this script has no
draft-value input for them and does not attempt a partial ranking.

## The formula

For each team, in each league, independently:

```text
power_score = 0.5 * z(draft_value) + 0.2 * z(week1_points) + 0.3 * z(ros_outlook)
```

`z(...)` is a population z-score computed **within that league only** (each
league's 10-12 teams are their own population; scores are not comparable
across leagues). Weights were chosen deliberately roster-value-heavy: one
week of fantasy results is noisy, so it gets the smallest weight, while
preseason roster value and forward outlook (which do not depend on a single
week's puntable/injury luck) dominate.

### 1. Draft value (`draft_value_z`, weight 0.5)

Reuses each team's `overall_z` column from the existing 2026 draft grade
report:
`scripts/output/draft2026/<prefix>_2026_draft_report_team_grades.csv`, built
by [`players/draft_report.py`](../src/fantasy_analyzer/players/draft_report.py)
(`build_team_draft_grades`, FFA-084/085/086). That number is already a
value-scale z-score blending total value-over-replacement drafted and
average per-pick value -- see
[`docs/draft-grade-2026.md`](draft-grade-2026.md) for its own methodology.
This script does not recompute it; a missing/stale CSV here means a stale
draft-value signal, not a crash (the merge is a left join; a team the CSV
doesn't cover gets `draft_value_z = 0`, i.e. treated as league-average).

### 2. Week 1 performance (`week1_z`, weight 0.2)

The team's actual fantasy points from `SleeperClient.get_matchups(league_id,
week=1)`, z-scored across the league. Deliberately just the raw Sleeper
score for the cutoff week -- no strength-of-schedule or luck adjustment --
because with only one game played there isn't enough data yet to separate
"good team" from "easy matchup."

### 3. Rest-of-season outlook (`ros_outlook_z`, weight 0.3)

Each team's **projected starting lineup total** for the rest of the season,
built by reusing the already-shipped FFA-092 waiver-wire projection pipeline
against the team's own roster instead of the free-agent pool:

1. Build a rostered-player pool shaped exactly like
   [`free_agents.FREE_AGENT_POOL_COLUMNS`](../src/fantasy_analyzer/players/free_agents.py)
   (`player_id`, `full_name`, `position`, `team`, `status`, `gsis_id`,
   `has_crosswalk`), but over every player on every roster (tagged with
   `roster_id`) instead of unrostered players. Nothing in
   `waiver_rankings.build_free_agent_ros_projections` actually requires
   free-agent status -- it only needs this column shape -- so this is
   direct reuse, not a parallel reimplementation.
2. Crosswalk Sleeper IDs to nflverse `gsis_id` via
   `scripts/player_analysis.py`'s `build_robust_id_crosswalk` (the
   DynastyProcess-backed union, FFA-074) rather than the plain
   Sleeper-catalog-only crosswalk
   (`players.crosswalk.build_id_crosswalk`). This matters: the plain
   crosswalk left several clearly-rostered, well-known players (e.g. a
   team's starting RB1) with no `gsis_id` at all during testing, which
   silently zeroed their projection. The robust union fixed this.
3. Project each player's rest-of-season points per game with
   [`ros_projection.project_ppg`](../src/fantasy_analyzer/players/ros_projection.py)
   (FFA-090's empirical-Bayes shrinkage: `w * observed_ppg + (1-w) *
   prior_ppg`, `w = games / (games + n0)`), called via
   `waiver_rankings.build_free_agent_ros_projections`, and multiply by
   remaining regular-season games (`DEFAULT_SEASON_END_WEEK - cutoff_week`,
   i.e. 16 games after week 1).
4. Greedily fill the team's **starting slots only** (excludes bench) with
   its highest-projected players: process the most position-restrictive
   slots first (dedicated QB/RB/WR/TE/K/DEF), then FLEX-style slots
   (`lineup_efficiency.START_SLOT_ELIGIBILITY`), assigning each slot the
   best remaining eligible, not-yet-used player. Sum of the filled slots is
   `ros_outlook_starters`.

Starters-only is deliberate: summing the whole roster (bench included)
would let a deep-but-unstartable bench inflate a team's outlook without
that value ever actually being scoreable. This greedy fill is **not** the
exhaustive DP `lineup_efficiency._optimal_lineup` uses for *realized*
weekly points (that helper is private to that module and works over played
weeks, not projections) -- it's a simpler, transparent approximation
appropriate for a forward-looking, already-approximate number.

## Known limitations (read before trusting this for a real decision)

- **Unfitted shrinkage constant.** `ShrinkageParameters` uses the uniform
  default `n0=3.0` for every position, not the validated per-position
  values (`docs/ros-projection-accuracy.md` reports `n0 = {RB: 2.0, WR:
  2.0, TE: 2.5, QB: 4.0}`). Same tradeoff `cli.py`'s
  `build_free_agent_rankings` already documents and accepts for the same
  reason: fitting `n0` needs a persisted multi-season corpus this ad hoc
  script doesn't build.
- **Greedy, not optimal, lineup fill** for the ROS-outlook component (see
  above) -- close to optimal in practice, not guaranteed exact.
- **Draft value is a snapshot.** `overall_z` reflects the roster as drafted;
  it does not know about trades or waiver moves since draft day. A team
  that has overhauled its roster since the draft will look stronger/weaker
  in `ros_outlook_z` (which reads current rosters) than in `draft_value_z`
  (frozen at draft day) -- that divergence is a real signal, not a bug.
- **Only 3 of 5 leagues.** No draft-value input exists for NWC Guillotine
  '26 or BBC weird league; this script does not attempt a 2-of-3-signal
  fallback for them.
- **K/DEF projections are typically weak or missing** (nflverse's crosswalk
  and shrinkage prior are least reliable for these positions), same caveat
  FFA-090/092 already carry.

## Running it

```bash
uv run python scripts/live_power_rankings.py
```

Edit `CUTOFF_WEEK` at the top of the script to move to a later week as the
season progresses (`SEASON`/`LEAGUES` should not need to change mid-season).
Requires the corresponding `<prefix>_2026_draft_report_team_grades.csv`
files in `scripts/output/draft2026/` to already exist (gitignored --
regenerate via `scripts/draft_report_2026.py` if missing).

## Output columns

| Column | Meaning |
|---|---|
| `power_rank` | 1-indexed rank by descending `power_score` (1 = strongest). |
| `team` | Team name (from the draft grade CSV; falls back to the Sleeper roster's display name if a team is missing from that CSV). |
| `power_score` | The blended score described above. |
| `draft_value_z` | Component 1. |
| `week1_points` | Raw week-1 fantasy points (not z-scored; for context). |
| `week1_z` | Component 2. |
| `ros_outlook_starters` | Raw projected rest-of-season starting-lineup point total (not z-scored; for context). |
| `ros_outlook_z` | Component 3. |
