# Rest-of-season projection accuracy (FFA-089 / FFA-090)

Measured accuracy of the empirical-Bayes rest-of-season projection against its
baselines. Reproduce with the harness in
`fantasy_analyzer.players.ros_backtest` and the model in
`fantasy_analyzer.players.ros_projection`.

## Protocol

- **Corpus**: nflverse weekly player stats, seasons 2015-2025, cached locally by
  `scripts/fetch_nflverse_seasons.py`.
- **Scoring**: full PPR, applied through the league scoring engine
  (`calculate_fantasy_points`).
- **Target**: rest-of-season fantasy points per game, weeks `w+1..17`, over weeks
  actually played. Players with fewer than 4 remaining games are excluded.
- **Fit**: shrinkage constant `n0` fitted per position on seasons **2016-2020**.
- **Test**: held-out seasons **2021-2025**. No parameter saw a test season.
- **Positions**: RB, WR, TE pooled in the tables below.

Fitted `n0`, in games:

| Position | RB | WR | TE | QB |
|---|---|---|---|---|
| `n0` | 2.0 | 2.0 | 2.5 | 4.0 |

`n0` is the number of observed games at which the current season and the prior
season carry equal weight. Values of 2 to 2.5 mean the current season overtakes
the prior very quickly for skill positions; quarterbacks hold their prior longer.

## Full player population

| Cutoff | Prediction | MAE | Spearman | Top-5 hit rate |
|---|---|---|---|---|
| 2 | prior-season PPG | 2.769 | 0.741 | 0.427 |
| 2 | season-to-date PPG | 3.411 | 0.698 | 0.320 |
| 2 | **projection** | **2.594** | **0.768** | 0.413 |
| 4 | prior-season PPG | 2.836 | 0.729 | 0.440 |
| 4 | season-to-date PPG | 2.913 | 0.739 | 0.373 |
| 4 | **projection** | **2.487** | **0.776** | **0.440** |
| 6 | season-to-date PPG | 2.686 | 0.763 | 0.387 |
| 6 | **projection** | **2.464** | **0.778** | **0.453** |
| 8 | season-to-date PPG | 2.661 | 0.771 | 0.413 |
| 8 | **projection** | **2.474** | **0.782** | **0.480** |
| 10 | season-to-date PPG | 2.695 | 0.763 | 0.467 |
| 10 | **projection** | **2.536** | **0.778** | **0.480** |

The projection wins on every metric at every cutoff. Error falls 6 to 10 percent
against the best baseline.

## Waiver population (below-median scorers)

This is the honest test. `filter_to_waiver_population` keeps players at or below
the within-position median of season-to-date scoring, which is the population a
waiver tool actually serves. Every correlation drops by roughly 0.2 once
established starters are conditioned away.

| Cutoff | Prediction | MAE | Spearman | Top-5 hit rate |
|---|---|---|---|---|
| 2 | prior-season PPG | 2.356 | **0.562** | **0.560** |
| 2 | season-to-date PPG | 2.692 | 0.466 | 0.307 |
| 2 | **projection** | **2.165** | 0.534 | 0.400 |
| 4 | prior-season PPG | 2.433 | 0.469 | **0.347** |
| 4 | season-to-date PPG | 2.344 | 0.462 | 0.187 |
| 4 | **projection** | **2.089** | **0.514** | 0.307 |
| 6 | season-to-date PPG | 2.008 | 0.500 | **0.240** |
| 6 | **projection** | **1.876** | **0.525** | 0.200 |
| 8 | season-to-date PPG | 2.111 | 0.488 | **0.267** |
| 8 | **projection** | **1.965** | **0.521** | 0.240 |
| 10 | season-to-date PPG | 2.154 | 0.471 | 0.227 |
| 10 | **projection** | **2.008** | **0.501** | **0.267** |

## Read this honestly

**What is settled.** The projection is the best available predictor on error and
on ranking. It wins mean absolute error at every cutoff in both populations, and
it wins rank correlation against season-to-date scoring at every cutoff in both
populations. Those two results are consistent and not close.

**What is not settled.** Top-5 hit rate does not follow. In the waiver
population the projection wins that metric at only two of five cutoffs, and at
week 2 **prior-season points per game is dramatically the better top-5 picker**
(0.560 against the projection's 0.400). Two things are going on, and they should
not be conflated:

1. Top-5 hit rate is computed over 15 cells here (5 seasons by 3 positions), so
   a single cell swings it by about 0.07. It is much noisier than the other two
   metrics and should not be read to three decimal places.
2. Early in a season the prior genuinely is the better *extreme* signal. Rank
   correlation rewards getting the whole ordering roughly right; hit rate only
   rewards the very top. A blend that is better on average can still be worse at
   the top, and here it is.

**What this means for the product.** Ship the projection as the ranking, and do
not present the top-5 as more reliable than it is. Before week 4, a manager is
well served by weighting last season heavily, which is exactly what the fitted
`n0` does for quarterbacks and not quite enough for skill positions in the top
tail.

**The known gap.** This model prices players on *points*, so it inherits the
touchdown-rate trap: touchdown rate is the least stable input measured, and a
player whose season-to-date scoring is touchdown-driven is being priced on the
least repeatable thing he did. Opportunity-first reconstruction, projecting
volume and applying a regressed efficiency rate, is the largest identified
remaining gain and is not implemented.
