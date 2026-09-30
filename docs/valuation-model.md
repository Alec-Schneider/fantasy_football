# Valuation model: opportunity-first rest-of-season projection (FFA-111, FFA-104)

The waiver board ranks players by projected rest-of-season points per game
above replacement. This page documents the projection behind that number: what it
is, how it was fitted, how it was measured, and what was adopted.

Code: `src/fantasy_analyzer/players/usage_projection.py` (model, fit, backtest),
`src/fantasy_analyzer/players/waiver_rankings.py` (integration),
`scripts/fit_usage_model.py` (refit). Fitted parameters:
`.cache/nflverse/usage_model_parameters.json`.

## What was adopted

| Position | `projected_ppg` = | Weight on usage (with snaps / without) |
|---|---|---|
| QB | blend of usage model and EB | 0.75 / 0.70 |
| RB | blend of usage model and EB | 0.65 / 0.60 |
| WR | blend of usage model and EB | 0.65 / 0.60 |
| TE | blend of usage model and EB | 0.80 / 0.70 |
| K, DEF | unchanged (EB for K; K/DEF are ranked by their own model) | — |

The blend won on MAE and rank correlation at every position, in the full and the
waiver population, under half-PPR and PPR, pooled over cutoffs and at cutoff 3.
Snap share is a feature because it measurably helped. Expected points (xFP) are
**not** a feature because they did not help; see "What did not help".

## The model

It works per player, for QB, RB, WR and TE.

**1. Volume per game** for pass attempts, carries and targets, as a
precision-weighted average of up to four sources:

```text
observed = (1 - rho) * season_mean + rho * last2_mean
volume   = (g*observed + d*g_prev*prior_mean + n_s*slope*snap_share_last2 + n0*baseline)
           / (g + d*g_prev + n_s + n0)
```

`g` is games to date and `g_prev` is prior-season games. `d` discounts a prior-season
game, `rho` weights the last two games (a role change shows up in usage before
points), and `n0` is pseudo-games at the positional baseline. There are two
baselines: one for players with at least 4 prior games, and a lower "no-prior" role
baseline for rookies and call-ups. The snap term applies only when a snap-count
frame is supplied and the player has a snap row. `slope` is fitted through the origin.

**2. Efficiency, touchdowns and turnovers per opportunity.** This covers catch
rate, yards per target, carry and attempt, completion rate, interception rate,
TD rates, fumbles lost per opportunity and 2-pt conversions:

```text
rate = (x + d*x_prev + k*mean) / (n + d*n_prev + k)
```

`k` (pseudo-opportunities at the positional mean) is fitted per rate and position,
so the data decide how hard each rate regresses. Fumbles use `fumbles_lost_total`
when present, which is the column the scoring engine charges.

**3. Score** the projected per-game stat line (volume × rate) with the league's own
settings through `scoring.calculate_fantasy_points`. Scoring is linear, so the
points of the expected line are the expected points, and half-PPR and PPR differ
exactly as the league scores them. nflverse's `fantasy_points` columns are never used.

**4. Blend** with the empirical-Bayes points projection (`ros_projection`):
`projected = a*usage + (1-a)*eb`, with `a` fitted per position by minimum MAE.
Ties go to the smaller `a`, the incumbent.

**5. Absent prior (FFA-104).** A player with no games to date and fewer than 4
prior-season games gets the fitted absent-prior stat line (below).

### Toy example (tested by hand in `tests/players/test_usage_projection.py`)

Take WR `w1` at cutoff week 3. He had 10, 6 and 2 targets (18 in all), 12
receptions, 150 yards and 1 TD, and last season 4 games of 5 targets. The
constants are hand-set: targets `n0=1, d=0.5, rho=0.5, baseline=8`; catch rate
`k=12, mean=0.5`; yards/target `k=12, mean=7.5`; TD rate `k=182, mean=0.04`.

- Targets: observed `0.5*6 + 0.5*4 = 5`; `(3*5 + 2*5 + 1*8)/(3+2+1) = 5.5`.
- Catch rate `(12+6)/30 = 0.6`, yards/target `(150+90)/30 = 8.0`, and TD rate
  `(1+7.28)/200 = 0.0414`. The observed 0.056 is pulled most of the way to 0.04.
- Stat line: 5.5 targets, 3.3 receptions, 44 yards, 0.2277 TD. Half-PPR
  `1.65 + 4.4 + 1.3662 = 7.4162`; PPR `9.0662`.
- Blended with EB 10.0 at `a = 0.75`: `8.06215`.

### Fitted constants (persisted fit, seasons 2015–2025, cutoffs 2/3/4/6/8/10)

Volume (snap model):

| Pos | Volume | n0 | d | rho | snap n0 | snap slope | baseline | no-prior baseline |
|---|---|---|---|---|---|---|---|---|
| QB | attempts | 6.0 | 0.5 | 0.2 | 3.0 | 34.1 | 32.20 | 28.94 |
| QB | carries | 1.5 | 0.4 | 0.0 | 0.0 | — | 3.34 | 3.70 |
| RB | carries | 1.0 | 0.2 | 0.4 | 0.5 | 20.9 | 8.72 | 7.27 |
| RB | targets | 1.5 | 0.2 | 0.2 | 1.0 | 5.8 | 2.49 | 2.00 |
| WR | targets | 1.0 | 0.3 | 0.0 | 2.0 | 8.0 | 5.04 | 3.50 |
| TE | targets | 0.5 | 0.2 | 0.0 | 1.0 | 6.5 | 3.69 | 2.79 |

Rates (the larger `k` is, the harder the regression). TD rates regress hardest,
as expected:

| Pos | Rate | k | d | mean |
|---|---|---|---|---|
| QB | pass yds/att | 300 | 0.25 | 7.216 |
| QB | pass TD rate | 500 | 0.25 | 0.0463 |
| QB | INT rate | 1500 | 0.5 | 0.0217 |
| QB | rush yds/carry | 10 | 0.5 | 4.474 |
| RB | rush yds/carry | 200 | 0.5 | 4.299 |
| RB | rush TD rate | 300 | 0.25 | 0.0313 |
| RB | catch rate | 150 | 0.25 | 0.766 |
| WR | catch rate | 50 | 0.5 | 0.622 |
| WR | rec yds/target | 150 | 0.5 | 7.946 |
| WR | rec TD rate | 300 | 0.5 | 0.0487 |
| TE | catch rate | 100 | 1.0 | 0.683 |
| TE | rec yds/target | 100 | 1.0 | 7.338 |
| TE | rec TD rate | 300 | 0.75 | 0.0537 |

## Backtest protocol

- **Harness**: `ros_backtest.build_ros_evaluation_set` / `score_baselines` /
  `filter_to_waiver_population`. The target is rest-of-season points per game over
  weeks `w+1..17` (regular season), and a player needs ≥1 game to date and ≥4
  remaining games.
- **Rolling origin** (`usage_projection.run_usage_backtest`): each scored season
  2019–2025 is scored with every constant fitted only on 2015 through the season
  before. That covers EB `n0`, volume and rate constants, blend weights and the
  absent-prior line. Blend weights are fitted on training-season predictions whose
  component constants were fitted on those same training seasons. That is
  in-sample for a handful of constants over roughly 20,000 rows, and never touches
  the scored season.
- **Cells**: 7 seasons × 6 cutoffs = 42 cells per position. Metrics are averaged
  over cells. There are about 36 QBs, 95 RBs, 151 WRs and 78 TEs per cell in the
  full population, and about half that in the waiver population.
- **Scoring**: the corpus and the projection both use the current
  `scoring.py` (sha256 `a9f60415…`), under NWC's real half-PPR settings and under
  full PPR. The numbers below were all produced after the scoring-engine update
  that added threshold bonuses, `st_td`, `fum_rec_td` and `fumbles_lost_total`.

## Results — half-PPR (NWC's real settings)

MAE / Spearman / top-5 hit rate, mean over cells. **Cutoff 3 is the live
situation (week-4 waivers).**

### Full population

| Pos | Prediction | All cutoffs MAE | ρ | top-5 | **Cutoff 3 MAE** | **ρ** | **top-5** |
|---|---|---|---|---|---|---|---|
| ALL | season-to-date | 2.868 | 0.763 | 0.314 | 3.013 | 0.755 | 0.286 |
| ALL | prior season | 2.835 | 0.746 | 0.319 | 2.723 | 0.759 | 0.314 |
| ALL | EB (old default) | 2.449 | 0.797 | 0.386 | 2.445 | 0.799 | 0.400 |
| ALL | usage only | 2.319 | 0.822 | 0.400 | 2.263 | 0.829 | 0.429 |
| ALL | **blend (new)** | **2.288** | **0.824** | 0.405 | **2.232** | **0.831** | 0.486 |
| QB | EB | 3.758 | 0.582 | 0.448 | 3.725 | 0.586 | 0.429 |
| QB | usage only | 3.429 | 0.579 | 0.443 | 3.318 | 0.593 | 0.429 |
| QB | **blend** | **3.435** | **0.591** | 0.457 | **3.312** | **0.600** | 0.429 |
| RB | EB | 2.746 | 0.767 | 0.405 | 2.784 | 0.765 | 0.371 |
| RB | usage only | 2.635 | 0.792 | 0.381 | 2.599 | 0.797 | 0.400 |
| RB | **blend** | **2.596** | 0.789 | 0.414 | **2.567** | 0.793 | 0.429 |
| WR | EB | 2.329 | 0.769 | 0.357 | 2.310 | 0.775 | 0.314 |
| WR | usage only | 2.223 | 0.794 | 0.352 | 2.170 | 0.805 | 0.286 |
| WR | **blend** | **2.184** | **0.798** | 0.400 | **2.126** | **0.807** | 0.371 |
| TE | EB | 1.712 | 0.733 | 0.567 | 1.694 | 0.736 | 0.629 |
| TE | usage only | 1.610 | 0.766 | 0.490 | 1.545 | 0.777 | 0.457 |
| TE | **blend** | **1.585** | **0.774** | 0.533 | **1.531** | **0.786** | 0.543 |

### Waiver population (below-median scorers to date)

| Pos | Prediction | All cutoffs MAE | ρ | top-5 | **Cutoff 3 MAE** | **ρ** | **top-5** |
|---|---|---|---|---|---|---|---|
| ALL | season-to-date | 2.374 | 0.550 | 0.381 | 2.463 | 0.546 | 0.457 |
| ALL | prior season | 2.463 | 0.565 | 0.510 | 2.417 | 0.590 | 0.514 |
| ALL | EB (old default) | 2.096 | 0.573 | 0.505 | 2.105 | 0.576 | 0.629 |
| ALL | usage only | 2.030 | 0.651 | 0.457 | 2.029 | 0.665 | 0.457 |
| ALL | **blend (new)** | **1.987** | **0.650** | 0.476 | **1.977** | **0.661** | 0.486 |
| QB | EB | 3.937 | 0.424 | 0.510 | 3.789 | 0.493 | 0.629 |
| QB | **blend** | **3.670** | **0.470** | 0.481 | **3.548** | **0.552** | 0.486 |
| RB | EB | 2.227 | 0.453 | 0.295 | 2.238 | 0.468 | 0.343 |
| RB | **blend** | **2.156** | **0.530** | 0.295 | **2.133** | **0.557** | 0.286 |
| WR | EB | 1.940 | 0.479 | 0.262 | 1.960 | 0.474 | 0.257 |
| WR | **blend** | **1.834** | **0.584** | 0.290 | **1.839** | **0.598** | 0.343 |
| TE | EB | 1.385 | 0.467 | 0.333 | 1.426 | 0.498 | 0.400 |
| TE | **blend** | **1.301** | **0.540** | 0.448 | **1.313** | **0.591** | 0.486 |

### Paired MAE difference, blend − EB (half-PPR)

The standard error is clustered by season (n = 7), because cutoffs within a
season share targets. "Seasons won" counts the seasons in which the blend's mean
MAE was lower.

| Population | Pos | All cutoffs Δ ± SE | seasons won | Cutoff 3 Δ ± SE | seasons won |
|---|---|---|---|---|---|
| Full | ALL | −0.161 ± 0.018 | 7/7 | −0.212 ± 0.028 | 7/7 |
| Full | QB | −0.323 ± 0.088 | 7/7 | −0.413 ± 0.081 | 7/7 |
| Full | RB | −0.151 ± 0.029 | 7/7 | −0.217 ± 0.043 | 7/7 |
| Full | WR | −0.145 ± 0.033 | 7/7 | −0.185 ± 0.044 | 7/7 |
| Full | TE | −0.126 ± 0.032 | 7/7 | −0.163 ± 0.044 | 6/7 |
| Waiver | ALL | −0.109 ± 0.023 | 7/7 | −0.128 ± 0.030 | 6/7 |
| Waiver | QB | −0.267 ± 0.170 | 5/7 | −0.240 ± 0.110 | 5/7 |
| Waiver | RB | −0.071 ± 0.024 | 6/7 | −0.106 ± 0.041 | 6/7 |
| Waiver | WR | −0.106 ± 0.027 | 7/7 | −0.121 ± 0.043 | 6/7 |
| Waiver | TE | −0.085 ± 0.028 | 6/7 | −0.113 ± 0.040 | 6/7 |

In cells (out of 42), the blend beats EB on MAE ALL 42 / QB 37 / RB 39 / WR 40 /
TE 39 in the full population, and 38 / 29 / 34 / 35 / 34 in the waiver population.
On Spearman it wins ALL 42 / QB 22 / RB 41 / WR 42 / TE 40 (full) and
42 / 29 / 41 / 41 / 34 (waiver).

### Full PPR (summary)

| Population | Pos | EB MAE / ρ | Blend MAE / ρ | Δ ± SE (season-clustered) |
|---|---|---|---|---|
| Full | ALL | 2.705 / 0.798 | 2.542 / 0.822 | −0.163 ± 0.017 |
| Full | QB | 3.690 / 0.585 | 3.372 / 0.596 | −0.318 ± 0.083 |
| Full | RB | 2.952 / 0.771 | 2.793 / 0.792 | −0.159 ± 0.031 |
| Full | WR | 2.680 / 0.786 | 2.537 / 0.809 | −0.143 ± 0.033 |
| Full | TE | 1.998 / 0.749 | 1.863 / 0.784 | −0.135 ± 0.032 |
| Waiver | ALL | 2.315 / 0.576 | 2.204 / 0.646 | −0.111 ± 0.025 |
| Waiver | QB | 3.846 / 0.416 | 3.567 / 0.467 | −0.278 ± 0.171 |
| Waiver | RB | 2.419 / 0.458 | 2.338 / 0.534 | −0.081 ± 0.027 |
| Waiver | WR | 2.241 / 0.506 | 2.144 / 0.595 | −0.097 ± 0.027 |
| Waiver | TE | 1.624 / 0.491 | 1.526 / 0.553 | −0.098 ± 0.030 |

### Read this honestly

- **Settled:** the blend beats the EB default on error and rank correlation at
  every position, in both populations and under both scorings. The differences
  are 3–8 season-clustered standard errors from zero everywhere except QB in the
  waiver population (about 18 QBs per cell, −0.27 ± 0.17). In the waiver population
  the rank-correlation gain is large (0.573 → 0.650 half-PPR).
- **Not settled:** top-5 hit rate. It is noisy (each cell moves in steps of 0.2)
  and does not follow the other metrics. In the waiver population at cutoff 3 the
  EB projection has the better pooled top-5 (0.629 vs 0.486 half-PPR; 7 cells, and
  pooled "ALL" top-5 is effectively a QB top-5). Do not present the top of the
  board as more reliable than it is.
- **QB rank correlation** gains are small in the full population (22–24 of 42
  cells). The QB gain is mostly error (MAE −0.32), not ordering.

## What helped and what did not (marginal gains, PPR, rolling origin)

| Feature | Comparison | Full ΔMAE ± SE, cells won | Waiver ΔMAE ± SE, cells won | Adopted |
|---|---|---|---|---|
| Snap share (recent) in volume | blend with vs without | −0.035 ± 0.005, 40/42 | −0.048 ± 0.006, 40/42 | **yes** |
| xFP expected rates as shrinkage targets | vs volume-only | +0.001 ± 0.002, 22/42 | −0.001 ± 0.003, 19/42 | no |
| xFP expected rates on top of snaps | vs snap model | +0.001 ± 0.003, 20/42 | −0.001 ± 0.003, 21/42 | no |
| Shrunk league-scored xFP/game as a 3rd stacked component | vs 2-way blend | +0.002, 21/42 | −0.002, 23/42 | no |

Half-PPR gives the same answers: snap share −0.029 ± 0.004 (39/42) full and
−0.040 ± 0.005 (38/42) waiver; xFP rates +0.001 ± 0.003 (19/42). xFP on its own
(shrunk xFP per game, MAE 2.640 PPR full) beats EB (2.705) but not the usage model
(2.584). Once volume is modeled it adds nothing measurable. It is still shown on
the board as `xfp_per_game` and `points_over_expected_per_game`, which is
touchdown and efficiency luck to date, because it explains *why* EB and usage
disagree.

Without a snap frame (`usage=None`) the separately fitted no-snap model still beats
EB on MAE at every position. Half-PPR full: ALL 2.317 vs 2.449; QB 3.489 vs 3.758;
RB 2.612 vs 2.746; WR 2.212 vs 2.329; TE 1.620 vs 1.712. The one exception is QB
Spearman, which is a hair under EB (0.579 vs 0.582).

## FFA-104: absent prior

This covers a player with **no games to date and fewer than 4 prior-season games**.
The old rule gave him the positional mean of players who *are* playing.

Historical cohort: players in exactly that state at a cutoff who **then played ≥4
games** (nflverse, held out 2019–2025, cutoffs 2–10; 202 QB, 304 RB, 254 TE and 459
WR player-cutoff rows). The line and ratio were fitted on earlier seasons only.
PPR points per game:

| Pos | Actual mean | Old fallback: mean / bias / MAE | Fitted line: bias / MAE | Ratio × mean: MAE |
|---|---|---|---|---|
| QB | 7.46 | 14.68 / +7.22 / 7.28 | +0.08 / 4.16 | 4.22 |
| RB | 3.88 | 7.68 / +3.80 / 4.25 | +0.78 / 2.63 | 2.61 |
| TE | 2.95 | 5.17 / +2.21 / 2.95 | −0.09 / 1.77 | 1.77 |
| WR | 3.06 | 7.60 / +4.54 / 4.90 | +0.27 / 2.24 | 2.19 |

Half-PPR is the same in shape: old fallback bias +7.33/+3.35/+1.75/+3.77, fitted
line +0.05/+0.65/−0.08/+0.20. Conditioning on having played makes the cohort an
**upper bound**, because a player who never takes the field has no row to measure.

The fix has two tiers:

- **With a usage model** (the dashboard and the `free-agents` CLI, whenever the
  fitted parameter file is cached), the absent player gets the fitted
  absent-prior stat line scored in the league. For NWC half-PPR that is QB 7.7,
  RB 3.8, TE 2.3 and WR 2.6 ppg. It does not depend on who else is in the pool.
- **Without one** (a caller that passes no usage model, or a run with no cached
  parameter file), the positional mean is scaled
  by the measured `DEFAULT_ABSENT_PRIOR_RATIO` (QB 0.51, RB 0.56, TE 0.54, WR 0.41).

Why the old fallback had to go: it is the mean of whoever is in the frame. On the
2026 week-1 board it was 7.78 RB ppg, with five retired or unsigned backs tied at
waiver rank 20. On the week-4 NWC universe it is 5.87, which tied 15 no-data RBs at
rank 43, inside the top 40 skill rows. With the usage model, the first no-data
player on that board is at rank 153 of 568 skill rows. Every absent player at a
position shares one value, so they tie (standard competition ranking).
`projection_model = "absent_prior"`.

That made the dashboard's display filter (drop a skill player with fewer than 4
prior-season games and no games this season) redundant, and it was removed on
2026-09-30. Re-measured on that day's week-4 boards, the best-ranked player it
would have removed was 136th of 577 skill free agents in NWC, 167th in New Wave
and 140th in Zipline — all far below the 40 rows the page shows.

## Live check: 2026 week-4 board (cutoff week 3), NWC FFL (half-PPR)

This is the dashboard composition: the universe as the replacement population and
the skill board with the dashboard's display filter, as it stood on 2026-09-29.
Removing the filter since then leaves every rank below unchanged, because nothing
it removed ranked above 136.

| Old (EB) rank | Player | Old ppg | New (blend) rank | New ppg | EB / usage | xFP/g | Pts over exp/g | Snap last 2 |
|---|---|---|---|---|---|---|---|---|
| 2 | Jake Ferguson TE | 9.20 | 2 | 7.27 | 9.20 / 6.79 | 7.10 | +2.47 | 0.64 |
| 3 | Mike Gesicki TE | 8.74 | 12 | 6.28 | 8.74 / 5.66 | 9.41 | +4.34 | 0.43 |
| 4 | Noah Fant TE | 7.33 | 26 | 5.60 | 7.33 / 5.17 | 6.06 | +3.47 | 0.50 |
| 5 | Tyler Higbee TE | 7.12 | 6 | 6.63 | 7.12 / 6.50 | 8.43 | +0.27 | 0.48 |
| 6 | Pat Freiermuth TE | 6.93 | 9 | 6.38 | 6.93 / 6.24 | 6.48 | +1.05 | 0.63 |
| 7 | AJ Barner TE | 6.72 | 8 | 6.58 | 6.72 / 6.55 | 6.45 | −0.08 | 0.86 |
| 8 | Brenton Strange TE | 6.63 | 11 | 6.31 | 6.63 / 6.23 | 5.37 | +0.20 | 0.80 |
| 12 | Wan'Dale Robinson WR | 8.88 | 4 | 9.25 | 8.88 / 9.44 | 6.27 | +1.36 | 0.58 |
| 13 | Kalif Raymond WR | 8.84 | 34 | 7.38 | 8.84 / 6.59 | 8.73 | +3.57 | 0.69 |
| 14 | Cade Otton TE | 5.99 | 3 | 7.06 | 5.99 / 7.32 | 6.97 | −1.14 | 0.92 |
| 144 | Deshaun Watson QB | 15.34 | 15 | 17.00 | 15.34 / 17.55 | 15.34 | +2.66 | 0.99 |

Touchdown-driven starts drop: Gesicki (+4.3 points over expected per game) goes
from 3 to 12, Fant (+3.5) from 4 to 26 and Raymond (+3.6) from 13 to 34. High-snap, under-rewarded usage rises:
Otton (92% of snaps, −1.1 over expected) goes from 14 to 3. That is the touchdown
trap the EB docstring named, now priced.

**Tyler Shough vs Lamar Jackson (NWC lineup call):**

| | Shough (NO) | Lamar (BAL) |
|---|---|---|
| Games / ppg to date | 3 / 24.79 | 3 / 20.40 |
| Prior season ppg (games) | 14.54 (11) | 16.76 (13) |
| Attempts / carries per game to date | 44.0 / 4.7 | 25.3 / 5.7 |
| Prior attempts / carries per game | 29.7 / 4.1 | 23.2 / 5.2 |
| Projected attempts / carries per game | 33.6 / 4.2 | 28.2 / 5.0 |
| xFP per game (half-PPR) / points over expected | 25.64 / −0.85 | 18.78 / +1.62 |
| EB / usage / **blend** | 19.27 / 17.69 / **18.09** | 18.44 / 17.36 / **17.63** |

The new model narrows the gap from 0.83 to 0.46 ppg but does not flip the call. It
doesn't flip because Shough's volume is real: 44 attempts a game, and his points
match his expected points (−0.85/g). Lamar's to-date output runs slightly *above*
his expected points. Both projections regress Shough hard (usage 17.7 against 24.8
to date), but not below Lamar. A 0.46 ppg gap is far inside the model's QB error
(MAE ≈ 3.3–3.4), so this is a near coin flip that the model resolves slightly
toward Shough. Lamar's projection is held down mainly by his prior season (16.76
ppg over 13 games), which both models weight. His rushing efficiency is mostly
kept, since QB yards per carry regresses with only `k = 10` pseudo-carries.

## What this does not support

- **Not a weekly start/sit model.** This is a rest-of-season per-game rate with no
  opponent adjustment, no injury or availability model, and no bye handling. The
  lineup call inherits all of that.
- **Top-5 precision.** See "Read this honestly".
- **Unprojected scoring.** Step-function bonuses (`bonus_pass_yd_400`,
  `bonus_rec_yd_200`, …) and `st_td` / `fum_rec_td` are not projected, because an
  expected per-game line never crosses a 400-yard threshold. In NWC, realized
  points run slightly above the usage projection for high-ceiling players.
- **K, DEF and IDP** are out of scope.
- **Games are nflverse stat rows.** A snap-only week with no stat is missing from
  both the features and the target, consistently.

## Reproduce

```bash
.venv/bin/python scripts/fit_shrinkage_parameters.py --start 2016 --end 2025   # EB n0
.venv/bin/python scripts/fit_usage_model.py --start 2015 --end 2025            # this model
```

The backtest is `usage_projection.build_usage_panel` →
`attach_opportunity_quality` → `run_usage_backtest(panel, cohort, range(2019, 2026),
scoring_settings[, waiver_population_only=True])`. The cohort is stacked
`build_absent_prior_cohort` rows for 2015–2025 × cutoffs.
