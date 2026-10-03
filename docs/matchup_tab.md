# Plan: Matchup tab (Epic 11)

A second tab on the season dashboard for the week being played: my lineup
against my opponent's, slot by slot, with live points, projections, a win
probability, and a season-to-date comparison of the two teams.

The dashboard already refreshes twice a week. There's a mid-week build after
Thursday night, which knows about game locks, and a weekend/Tuesday build
once the week is final (`docs/dashboard.md`). This tab is meant to be read
at both points. Before kickoff it's a preview. After Thursday it shows the
score so far plus a projection for the players who haven't played yet.

## Page shape

The existing page becomes the **Season** tab, unchanged. The new **Matchup**
tab is the default. Both tabs share the league switcher. The week stepper
applies only to Season, so it's hidden on Matchup. The chosen tab is saved
in `localStorage` (`schneid-desk-tab`) with the same try/catch pattern the
league switcher uses.

The Matchup tab always shows `league.upcoming_week`, the week the decision
half of the Season tab already covers. In top-to-bottom order:

1. **Scoreboard.** My team and the opponent side by side: team name, owner,
   record and standing, the live score, the projected final, the number of
   players still to play, and a win-probability bar.
2. **Lineups, head to head.** One row per starting slot, with my player on
   the left, the slot label in the middle and the opponent's player on the
   right. Each side shows the player, NFL team, `@OPP`/`vs OPP`, game state
   (kickoff time, live, final, bye), injury, projection and actual points.
   Each row is tinted by its projected edge.
3. **Positional edge.** A diverging bar for each slot group (QB, RB, WR, TE,
   FLEX, K, DEF) showing the projected points difference.
4. **Alerts.** Problems in the lineup I've actually set: an Out/IR/bye
   starter, an empty slot, or a starter with no projection. Also "the
   recommended lineup projects +X" with a pointer to the Season tab's
   lineup call. For the opponent, the same problems plus how much they're
   leaving on the bench (their optimal lineup minus the one they've set).
5. **Season comparison.** Through the last completed week: record, rank,
   PF, PA, PPG, last-3 PPG, high, low, weekly SD, all-play, power rank.
   Also each team's points per game by position with league rank, and
   this season's head-to-head meetings.
6. **Benches.** Both benches in a collapsed `<details>`.

"My lineup" here means the lineup **actually set in Sleeper**, because
that's what gets scored. The Season tab's "Recommended lineup" is still
the advice. The Matchup tab only reports the gap between the two.

## Methodology

**Projection per player** is the same `lineup_ppg` column the lineup call
already solves on, so the two tabs never disagree. Skill players use the
FFA-111 blend's `projected_ppg`. K and DEF use the K/DEF model's
`week_projected_points`.

**Expected points per starter** (the projected final is their sum):

| Starter state | Expected points | Pending (carries variance) |
|---|---|---|
| Empty slot (Sleeper id `"0"`, missing) | 0 | no |
| NFL game kicked off (`in_progress` or `final`) | Sleeper live `players_points` (0.0 if absent) | no |
| Not kicked off, unavailable (Out/IR/bye/...) | 0 | no |
| Not kicked off, available, no projection | 0, flagged `projection_missing` | no |
| Not kicked off, available, projected | projection | **yes** |

A game in progress is scored at its live points. That matches what
`_build_lineup` already does with locked starters, and the two scheduled
refresh times (after Thursday, Tuesday) never land mid-game. A refresh
during a game understates that game. That's documented, not modelled.

**Win probability** (FFA-114) treats each team's final score as normal. The
mean is the projected final above. The variance is the sum, over pending
starters, of a fitted per-player single-week variance. Then:

```text
P(me) = Phi( (mu_me - mu_opp) / (lambda * sqrt(sd_me^2 + sd_opp^2)) )
```

`lambda` is a single fitted inflation factor that covers within-team
correlation and surprise inactives, which the independence sum ignores.
Ties have probability zero under a continuous model. If one side has no
variance left (every game final), the formula is replaced by the sign of
the margin, with 0.5 for an exact tie. The fitted parameters live in
`.cache/nflverse/win_probability_parameters.json`, written by
`scripts/fit_win_probability.py`. When the file is missing, the bundle
carries `win_probability: null` and the page shows only the projected
margin. **The probability is never shown uncalibrated.**

## Bundle contract

`build_dashboard.py` adds one key to each league object, `matchup`. It's
`null` when there's no roster for the user, no opponent (a bye), or no
matchup payload. The template must treat a missing `matchup` key exactly
like `null`, because older bundles don't have it.

```jsonc
"matchup": {
  "week": 4,
  "phase": "pre" | "live",          // "live" once any NFL game this week has kicked off
  "nfl_games": {"total": 16, "kicked_off": 1, "final": 1},
  "me": Side,
  "opponent": Side,
  "win_probability": null | {
    "me": 0.61, "opponent": 0.39,
    "projected_margin": 5.4,         // mu_me - mu_opp
    "margin_sd": 24.8,               // lambda * sqrt(sd_me^2 + sd_opp^2)
    "me_sd": 17.0, "opponent_sd": 16.9
  },
  "position_edges": [                // slot groups in roster_positions order, deduplicated
    {"group": "QB", "me": 18.1, "opponent": 21.0, "edge": -2.9}
  ],
  "my_recommended_total": 100.6,     // lineup.projected_points (the Season tab's lineup call)
  "my_recommended_gain": 2.4,        // my_recommended_total - me.projected_total
  "comparison": null | Comparison    // null before any week is complete
}
```

`Side`:

```jsonc
{
  "roster_id": 3, "owner": "schneidbaby", "team_name": "...",
  "points": 6.0,                     // Sleeper's matchup `points`, the official live score
  "projected_total": 98.2,           // sum of expected_points over starters
  "players_remaining": 8,            // count of pending starters
  "optimal_total": 101.0,            // best legal lineup given locks + availability; null if unsolvable
  "starters": [SlotRow, ...],        // one per startable slot, in roster_positions order
  "bench": [SlotRow, ...],           // slot = "BN" (or "IR" for reserve), sorted by projection desc
  "alerts": [{"player_id": "...", "full_name": "...", "slot": "WR",
              "reason": "Out" | "IR" | "Bye" | "Empty slot" | "No projection" | "Questionable" | "Doubtful" | ...}]
}
```

`SlotRow` (bench rows use the same shape):

```jsonc
{
  "slot": "RB", "player_id": "1234" | null, "full_name": "...", "position": "RB",
  "team": "PIT",                     // Sleeper spelling
  "nfl_opponent": "CLE", "is_home": false,
  "kickoff": "2026-10-04T13:00:00-04:00" | null,
  "game_state": "scheduled" | "in_progress" | "final" | "bye" | null,   // null for an empty slot
  "injury_status": null, "injury_body_part": null,
  "available": true, "unavailable_reason": null,
  "projection": 14.2 | null,         // lineup_ppg
  "actual_points": 12.3 | null,      // only once kicked off
  "expected_points": 12.3,
  "pending": false,
  "projection_missing": false,
  "ppg_to_date": 13.1, "last3_ppg": 15.0, "snap_share": 0.71, "target_share": 0.22
}
```

`Comparison`:

```jsonc
{
  "through_week": 3,
  "me": TeamStats, "opponent": TeamStats,
  "positions": [{"position": "QB", "me_ppg": 21.0, "me_rank": 3, "opponent_ppg": 17.5, "opponent_rank": 9}],
  "head_to_head": {"meetings": 0, "wins": 0, "losses": 0, "ties": 0,
                   "games": [{"week": 2, "points": 110.2, "opponent_points": 98.0}]}
}
```

`TeamStats`: `roster_id, wins, losses, ties, rank, points_for,
points_against, ppg, last3_ppg, high, low, stdev_points, all_play_wins,
all_play_losses, all_play_ties, power_rank, power_score`. A column that
can't be computed (for example `stdev_points` with fewer than 2 weeks) is
`null`, not omitted.

## Tickets

Wave 1 runs in parallel. The four tickets touch disjoint files. Wave 2
wires them together.

| Ticket | Owner | Files | Depends |
|---|---|---|---|
| FFA-113 Matchup lineup projection | Software Eng. | `players/opponent_strength.py` (`nfl_game_states`), new `players/matchup_projection.py` | — |
| FFA-114 Win probability model | Data Scientist | new `players/win_probability.py`, `scripts/fit_win_probability.py`, `docs/win-probability.md` | — |
| FFA-115 Matchup team comparison | Software Eng. | new `analytics/matchup_preview.py`, `players/player_week.py` (Sleeper-scored started frame) | — |
| FFA-117 Matchup tab page | Software Eng. | `scripts/templates/dashboard.html.tpl` only | contract above |
| FFA-116 Bundle wiring | Software Eng. | `scripts/build_dashboard.py`, `tests/test_build_dashboard_script.py` | 113, 114, 115 |
| FFA-118 Docs and board | — | `docs/dashboard.md`, `AGENTS.md` | 116, 117 |

FFA-116 lands in wave 2 and FFA-118 closes the epic. After that comes a real
build, a visual check of the rendered page, and a republish to the existing
dashboard URL.

## Out of scope (follow-ups)

- **All-time head-to-head** across seasons via `previous_league_id`. This
  tab shows the current season only.
- **Box scores for past weeks**, using Sleeper's `starters_points` on the
  Season tab's scoreboard.
- **Matchup-adjusted (defense-vs-position) projections for rostered
  players.** `DEFAULT_DVP_SHRINKAGE_GAMES` is still an unfitted prior.
