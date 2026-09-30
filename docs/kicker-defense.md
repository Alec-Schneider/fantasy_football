# Kicker and team-defense scoring and projections (FFA-112)

Every league this project follows starts one `K` and one `DEF`. This page
records how those two positions are scored from nflverse data, the evidence
that each scoring rule matches Sleeper, and how they are projected.

Code: `players/scoring.py` (`calculate_fantasy_points`,
`calculate_team_defense_points`), `players/nflverse_defense.py`
(`build_team_defense_weeks`), `players/kicker_defense.py`
(`build_kicker_defense_projections`). Reproduce every number here with
`scripts/verify_special_teams_scoring.py` (scoring) and
`scripts/verify_special_teams_scoring.py --backtest` (projections).

## The oracle

Sleeper's raw matchup payload (`SleeperClient.get_matchups(league_id, week)`)
carries `players_points`: Sleeper's own computed points for **every rostered
player**, bench included, keyed by player id. That covers DEF team codes
(`"SEA"`) and kickers. It is the ground truth for this page.

Sample: NWC, New Wave and Zipline (three scoring configurations), 2025 weeks
1-17 and 2026 weeks 1-3. That is 8,797 rostered player-weeks in 2025 and
1,542 in 2026. A match is `|ours - Sleeper| < 0.05`.

## Match rates

| Season | Position | n | Before FFA-112 | After |
|---|---|---:|---:|---:|
| 2025 | K | 573 | 507 (88.5%) | **573 (100%)** |
| 2025 | DEF | 665 | not scoreable | **656 (98.6%)** |
| 2025 | QB | 1,043 | 1,011 (96.9%) | 1,018 (97.6%) |
| 2025 | RB | 2,580 | 2,551 (98.9%) | 2,556 (99.1%) |
| 2025 | WR | 2,929 | 2,896 (98.9%) | 2,910 (99.4%) |
| 2025 | TE | 977 | 977 (100%) | 977 (100%) |
| 2026 wk 1-3 | K | 96 | 76 (79.2%) | **96 (100%)** |
| 2026 wk 1-3 | DEF | 101 | not scoreable | **101 (100%)** |
| 2026 wk 1-3 | QB / RB / WR / TE | 174 / 458 / 532 / 181 | 170 / 456 / 526 / 181 | 171 / 456 / 526 / 181 |

By league: every K league-week is 100% in every league. NWC's DEF is 100%
(275/275). New Wave's is 237/241 and Zipline's 245/250; each miss is one
row in 2025 weeks 8, 10, 12, 14 or 17. `--by-week` prints the full
league-by-week table.

### Residuals that remain

- **DEF, 9 rows (5 team-weeks), all ±1.** Four are forced-fumble
  attribution differences between nflverse and Sleeper's feed (for example,
  a quarterback credited with a forced fumble on the return after his own
  interception). One is a blocked field goal that the *blocking* team
  muffed. nflverse's weekly table cannot tell that recovery apart from a
  scrimmage one.
- **Skill positions, NWC only.** 77 rows, all with Sleeper 1 or 2 above us.
  NWC pays `pass_td_50p`/`rush_td_50p`/`rec_td_50p`, a bonus per touchdown of
  50+ yards. Touchdown length is a play-by-play fact the weekly table does not
  carry. Checked against 2025 play-by-play, **65 of the 66 2025 rows are
  explained exactly** by the player's count of 50+ yard touchdowns.
- **One QB-week** (Sleeper id 11560, 2025 week 6) disagrees by 0.5 in every
  league: a stat-feed disagreement, not a mapping.
- Outside NWC's touchdown-length bonuses and that one QB-week, New Wave and
  Zipline skill scoring matches Sleeper on every row.

## Mapping evidence

### Kickers and players (`calculate_fantasy_points`)

| Sleeper key | nflverse column(s) | Evidence |
|---|---|---|
| `fgm_0_19` … `fgm_40_49`, `fgm_50p`, `xpm` | `fg_made_<band>`; `fgm_50p` = `fg_made_50_59 + fg_made_60_` | Unchanged; exact on all 669 kicker-weeks. |
| `fgm_50_59`, `fgm_60p` | `fg_made_50_59`, `fg_made_60_` | **New.** Zipline scores the bands separately (5/6). They were unmapped, so every 50+ yard FG scored 0: 45 of the 66 2025 kicker misses. |
| `fgmiss` | `fg_missed` **+ `fg_blocked`** | **Changed.** The other 21 of the 66 misses were all +1 rows with `fg_blocked` or `pat_blocked` = 1. nflverse keeps `fg_att = fg_made + fg_missed + fg_blocked` (and the same for PATs) on every kicking row 2014-2026, so `fg_missed` excludes blocks. Sleeper counts a block as a miss. |
| `xpmiss` | `pat_missed` **+ `pat_blocked`** | **Changed.** Same finding for extra points (New Wave, Zipline weight -1). |
| `fum_lost` | `fumbles_lost_total` (falls back to the three scrimmage columns when absent) | **Changed.** Every fumble-related skill miss was a fumble lost outside the rush/reception/sack categories (a muffed punt or kick return, or a fumble after a turnover). Only the total counts those. The total is never below the three-column sum (0 rows in any season 2014-2026). |
| `st_td` | `special_teams_tds` | **New.** Punt/kick returners were 6 short on their return-TD weeks. |
| `fum_rec_td` | `fumble_recovery_tds` | **New.** An RB recovering a fumble in the end zone was 6 short. |
| `bonus_pass_yd_400`, `bonus_rush_yd_200`, `bonus_rec_yd_200` | threshold: stat `>= 400/200/200` pays the weight once | **New.** NWC's 400-yard passers and 200-yard rushers/receivers were short by the bonus. With it mapped, 65 of 66 remaining NWC 2025 skill misses are explained exactly by 50+ yard TDs, so no threshold miss remains. |
| `fgm` | `fg_made` | New, unambiguous. Weight 0 everywhere, so unverified. |
| `pass/rush/rec_td_50p`, `st_ff`, `st_fum_rec`, `fum`, `bonus_*_100/300`, `fgmiss_<band>` | unmapped (reported as unsupported) | Either not in weekly data, or not weighted in any league so unverifiable. |

Backward compatibility: every new column is optional, and an absent column
contributes zero. A frame from `nflverse_provider.normalize_player_stats`
(which does not pass `fg_blocked`, `pat_blocked`, `fumbles_lost_total`,
`special_teams_tds` or `fumble_recovery_tds` through) therefore scores
exactly as before FFA-112. The raw-table path (`ros_backtest.build_scored_player_weeks`,
used by the waiver board) gets the corrections.

### Team DEF (`calculate_team_defense_points` on `build_team_defense_weeks`)

Each rule was settled with 2025 play-by-play. Play-by-play classifies every
play, so special-teams and scrimmage events can be told apart. With exact
play-by-play inputs, Sleeper's DEF points were reproduced on 637 of 642
league-weeks (99.2%). The table's n is league-weeks, with the distinct
team-weeks in brackets.

| Sleeper key | Definition | Evidence (discriminating rows, all exact) |
|---|---|---|
| `pts_allow_*` | Tier on **opponent score − 6 × opponent defensive TDs − 2 × opponent safeties** | Match rate by definition: raw score 95.3%, −6 per def TD 98.4%, −7 per def TD 96.6%, −6 per def *and* ST TD 94.1%, **−6 per def TD −2 per safety 99.2%**. Opp def TD 35 (15), opp ST TD 31 (15, *not* subtracted), opp safety 16 (8). |
| `sack` | Opponent's `sacks_suffered` | Weekly-vs-play-by-play agreement 544/544 team-games; the sum of `def_sacks` gives 535/544 (misses unattributed team sacks). |
| `int` | `def_interceptions` | 544/544. |
| `fum_rec` (2) vs `def_st_fum_rec` (1) | Special-teams recovery = opponent returner's non-scrimmage fumbles lost, capped at our recoveries | ST recoveries 40 (19): paid 1 once. Paying `fum_rec` (2) instead drops the match rate to 93.0%. `st_fum_rec` has the same weight, so the oracle cannot tell it from `def_st_fum_rec`, but paying both is ruled out. |
| `ff`, `def_st_ff` | All forced fumbles (`def_fumbles_forced`) under `ff` | Every league weights the two equally, so the total is exact; `st_forced_fumbles` is emitted as 0. |
| `st_ff` | **Not paid to the DEF** | 15 NWC team-weeks with a special-teams forced fumble (`st_ff`=1, `def_st_ff`=0) all match with zero. |
| `def_td` | `def_tds` + fumble-return TDs by **defenders** (DL/LB/DB) | 55 (26). nflverse files fumble returns under `fumble_recovery_tds`, not `def_tds`. The defenders-only rule agrees with play-by-play 544/544 (all players: 543/544). |
| `def_st_td` | `special_teams_tds` | Return TDs 33 (14): paid 6 once, not also `st_td`. |
| `safe` | `def_safeties` + unattributed safeties recovered from the score | 11 (6). See data quality below. |
| `blk_kick` | punt + FG + **PAT** blocks | Blocked PATs 7 (5), punts/FGs 26 (16), in the leagues weighting `blk_kick`. |

### Data-quality findings in nflverse's weekly table

- **Player-less rows.** One row per week has no `player_id` and holds that
  week's unattributed stats, penalty safeties above all, under an
  **arbitrary team**. In 2025 week 3 it credited Arizona's safety to Miami.
  `build_team_defense_weeks` drops it.
- **Unattributed safeties are recoverable.** Reconstructing every team's
  score from its players' TDs, kicks, 2-point conversions and safeties is
  exact for every team-game 2015-2026, except teams short by exactly 2. In
  **every week of those 12 seasons**, the number of 2-short teams equals the
  player-less row's safety count. So a positive, even residual is taken as
  `residual / 2` safeties.
- **Team codes.** nflverse's schedule keeps `OAK` (through 2019), `SD`
  (2016) and `STL`, while its player stats use the current franchise code for
  every season. They are folded before joining (`FRANCHISE_CODE_ALIASES`).
  Without this, 2016-2019 Raiders/Chargers games reconciled to nothing.

## Projections

### Definition

Per player, at cutoff week `c`:

```
prior_resolved = (m * prior_ppg + k * positional_mean) / (m + k)
w              = g / (g + n0)
projected_ppg  = w * ppg_to_date + (1 - w) * prior_resolved       (rest of season, per game)

week_projected_points = projected_ppg + slope * (implied - center)   if the team plays
                      = 0                                          on a bye / with no NFL team
```

- `g` is games through `c` and `m` is last season's games. The positional
  mean is the mean `ppg_to_date` of every player at the position with a game
  by `c` (last season's mean before week 1).
- `implied` is the kicker's **own** team's implied total, or the defense's
  **opponent's**, from `games.csv` `spread_line`/`total_line`. It is 0
  adjustment when the week has no line.
- Fitted on 2016-2025 (NWC scoring): **K: n0 = 20, k = 50, slope +0.130;
  DEF: n0 = 25, k = 50, slope −0.364; center 22.77.** New Wave and Zipline
  scoring fit the same `n0`/`k` and slopes within 0.013.

Heavy shrinkage is the finding. At week 3 a kicker's own season carries
3/23 = 13% of the weight, and a full 17-game prior is itself pulled 50/67 =
75% of the way to the mean.

### Toy example (tested in `tests/players/test_kicker_defense.py`)

A kicker with 3 games at 12.0 and a 5-game prior at 10.8, with a positional
mean of 7.6, projects as follows under the fitted K parameters:

```
prior_resolved = (5 * 10.8 + 50 * 7.6) / 55 = 7.8909
projected_ppg  = 3/23 * 12 + 20/23 * 7.8909 = 8.4269
```

The real 2026 case is Spencer Shrader (NWC, cutoff 3): 12.0 ppg over 3 games
on a 5-game 10.80 prior. He projects to **8.57**, **+0.69 ppg** over NWC's
replacement kicker (7.88).

### Backtest

The backtest uses a rolling origin: each season 2019-2025 is projected with
parameters fitted on 2016 through the season before it. Every player with a
game by the cutoff is scored. "ROS" is realized rest-of-season points per
game (players with 4+ remaining games). "Next week" is week `c+1` points
(players who played). Figures are MAE in fantasy points, under NWC scoring.

**Cutoffs 3-4 (the requested window):**

| Pos | Horizon | n | Shrinkage (+ implied) | Shrinkage | Positional mean | Season-to-date |
|---|---|---:|---:|---:|---:|---:|
| K | ROS | 437 | — | 1.291 | **1.288** | 2.182 |
| K | Next week | 408 | 3.595 | 3.578 | **3.547** | 3.930 |
| DEF | ROS | 448 | — | **1.548** | 1.605 | 2.747 |
| DEF | Next week | 426 | **4.315** | 4.392 | 4.436 | 4.798 |

**Cutoffs 3-12 (robustness, same holdout):**

| Pos | Horizon | n | Shrinkage (+ implied) | Shrinkage | Positional mean | Season-to-date |
|---|---|---:|---:|---:|---:|---:|
| K | ROS | 2,154 | — | **1.414** | 1.420 | 1.933 |
| K | Next week | 1,984 | **3.390** | 3.414 | 3.419 | 3.647 |
| DEF | ROS | 2,240 | — | **1.894** | 1.946 | 2.580 |
| DEF | Next week | 2,038 | **4.351** | 4.438 | 4.450 | 4.671 |

Paired differences (mean ± standard error of the per-row absolute-error
difference; negative means the first method is better):

| Comparison | Cutoffs 3-4 | Cutoffs 3-12 |
|---|---|---|
| K ROS: shrinkage − positional mean | +0.003 ± 0.026 | −0.007 ± 0.014 |
| K next week: + implied − shrinkage | +0.017 ± 0.020 | **−0.025 ± 0.009** |
| DEF ROS: shrinkage − positional mean | −0.057 ± 0.034 | **−0.051 ± 0.017** |
| DEF next week: + implied − shrinkage | −0.077 ± 0.065 | **−0.087 ± 0.030** |
| Either position, either horizon: best model − season-to-date | −0.34 to −1.20, all > 3.5 SE | −0.26 to −0.69, all > 7 SE |

New Wave and Zipline scoring give the same ordering at cutoffs 3-4 (DEF
next week 4.612 with implied vs 4.691 without vs 4.716 positional mean;
K ROS 1.389 vs 1.388).

What this supports:

- **Both positions: never use the season-to-date average.** It is the worst
  predictor everywhere, by 0.3-1.2 points.
- **DEF: the projection beats the positional mean**, and the opponent's
  implied total improves the weekly call. At cutoffs 3-4 alone both gains are
  within noise; across 3-12 they are 3 SE.
- **K: nothing beats "an average kicker" at weeks 3-4.** The shrinkage
  projection ties the positional mean. The own-team implied total helps only
  across the wider 3-12 window (0.025 points, about 2.8 SE) and is slightly
  worse at 3-4. It was kept on the wider evidence. Treat kicker rankings as
  near-coin-flips: the whole projected range for 2026 at week 3 is 7.00-8.57.

Measured and dropped, in the exploratory research pass (same holdout and
cutoffs 3-4, but fixed full-period `n0`/`k` rather than the rolling fit, so
not directly comparable to the tables above): a home/away term (DEF 4.395
vs 4.399 without it, K 3.578 vs 3.563, so no gain once the implied total is
in) and a stats-based opponent-offense adjustment for DEF (4.364 vs 4.399,
weaker than the market's 4.318).

### Value over replacement (NWC, 12 teams, 1 K + 1 DEF slot)

Measured with `player_value.build_player_value_metrics` on the cutoff-3
projections:

- **K:** replacement 7.88, best +0.70 ppg.
- **DEF:** replacement 5.90, best +1.04 ppg.

Both positions are low-leverage by construction, which is the honest reading
of the backtest above.

## Limits

- No injury, weather, or kicker-competition signal. `status` is passed
  through from Sleeper for the caller to filter on.
- A kicker with zero attempts in a game has no nflverse row, so that game is
  missing from his average. This is rare: it takes a game with no score and
  no field-goal attempt.
- Rookie kickers missing from both crosswalk sources are matched by
  normalized name (Trey Smack, GB, 2026). A kicker nflverse has never seen
  gets the positional mean with `has_crosswalk = False`.
- `yds_allow_*` and `def_2pt` are surfaced as unsupported. No league here
  weights `yds_allow_*`, and NWC weights `def_2pt` at 0.
