# Win probability model (FFA-114)

`src/fantasy_analyzer/players/win_probability.py` turns a team's expected
points into the probability it beats its opponent this week. The constants
are fitted by `scripts/fit_win_probability.py` and stored in
`.cache/nflverse/win_probability_parameters.json`. Every number below comes
from that script's run (command at the end).

## The metric

Each team's final score is modelled as a normal variable.

* `mu` = sum of the starters' expected points. Upstream (FFA-113) that is
  actual points for a game already kicked off, the projection for a game
  still pending, and 0 for an empty or unavailable slot.
* `sd^2` = sum over **pending** starters of `s(position, projection)^2`.
  A starter whose game is final has no variance left.
* `s(position, projection) = c_pos * sqrt(max(projection, 1.0))`. This is
  the `"sqrt"` form; the `"constant"` form `s = a_pos` is also implemented
  and lost the held-out comparison (below).

```text
P(me) = Phi( (mu_me - mu_opp) / (lambda * sqrt(sd_me^2 + sd_opp^2)) )
```

`lambda` is one fitted inflation factor on the margin's SD. It stands in for
what the independent sum ignores: within-team correlation and surprise
inactives.

Edge rules (all tested in `tests/players/test_win_probability.py`):

* **Ties.** A normal variable has no point mass, so `P(tie) = 0` and
  `P(me) + P(opp) = 1`. A real exact tie in the fitting data is dropped
  (there were none among the 203 calibration games).
* **No variance on either side** (every game final): the answer is the sign
  of the margin, `1.0` / `0.0`, and `0.5` for an exact tie.
* **Missing projection.** NaN is read as 0, negative is clipped to 0, and
  the sqrt form floors the projection at 1.0 so the SD is never 0.
* **Unknown position** uses `default_coefficient`; `DST` / `D/ST` are
  `DEF`.
* **Regular season vs playoff.** `lambda` and the coefficients are fitted on
  regular-season weeks only. The functions themselves know nothing about the
  calendar; applying them to a playoff week is an extrapolation nobody has
  measured.

### Toy example, worked by hand

Stored pooled coefficients: QB 1.7868, RB 2.1820, DEF 2.1064; `lambda` =
0.9873. Team A starts QB 20, RB 15, DEF 8 (mu = 43); team B starts QB 18, RB
12, DEF 9 (mu = 39). All six games are pending.

```text
c^2:  QB 3.1927   RB 4.7611   DEF 4.4369
A: 3.1927*20 + 4.7611*15 + 4.4369*8  = 63.853 + 71.417 + 35.495 = 170.765   sd_A = 13.068
B: 3.1927*18 + 4.7611*12 + 4.4369*9  = 57.468 + 57.133 + 39.932 = 154.533   sd_B = 12.431
sqrt(170.765 + 154.533) = 18.036;  * 0.9873 = 17.806
z = (43 - 39) / 17.806 = 0.2246;   Phi(0.2246) = 0.5889
```

The package returns 0.58887 for the same inputs. If A's QB has already
finished (not pending), `sd_A` drops to 10.340 and `P(A)` rises to 0.5989.

## Data and population

**Projection being tested.** The dashboard's own: QB/RB/WR/TE through
`build_free_agent_ros_projections` (usage-model blend with absent prior,
league scoring) and K/DEF through `build_kicker_defense_projections`
(`week_projected_points`, default K/DEF constants). Nothing is fitted
in-sample: for each test season `s`, the EB `n0`, the usage model and its
blend weights are fitted only on seasons 2015 to `s-1` at standard PPR
(`ensure_rolling_fit`, the `fit_usage_model` path). A check that truncating
the inputs at the cutoff leaves the 2025 week-5 skill projections unchanged
(691 players, max absolute difference 0.0) found no look-ahead.

**Seasons.** 2021 to 2025, five test seasons. 2021 is the first season with
six prior fit seasons (2015-2020) and a 17-game schedule throughout the
window; going earlier means fitting on fewer than six seasons. 2025 is the
holdout for the SD-form choice.

**Backtest rows.** Cutoffs `c = 1..16`: the projection at cutoff `c` against
the player's actual week `c+1` points under league scoring, for players who
played in week `c+1`. K/DEF rows come from nflverse team-defense and kicker
rows; a kicker with no attempt has no row, so he is absent.

**Starter-caliber population.** At each (league, season, cutoff, position),
rank the players who played that week by projection and keep the top N, with
N = QB 12, RB 30, WR 36, TE 12, K 12, DEF 12 (starters across 12 teams).
Ranking among players who took the field mimics the dashboard, which never
starts an inactive player; the cost is that the SD is conditional on playing
and surprise inactives must be absorbed by `lambda`. 92,217 rows before the
restriction, 27,360 after (9,120 per league; the counts per position are
exactly N x 16 cutoffs x 5 seasons x 3 leagues, so the cut always bound).

**Leagues.** The three 2026 leagues in `scripts/draft_league_presets.py`, with
their 2025 seasons reached through `previous_league_id`. Scoring differs
(NWC half-PPR, interception -2, fumble lost -1; New Wave full PPR, -1, -2;
Zipline half-PPR, -1, -2).

## A. Player-level SD: measured

Held-out Gaussian NLL per player-week (nats; lower is better). Coefficients
fit on 2021-2024, scored on 2025. Each row pools the three leagues' scoring,
so `n_test` counts the same player-weeks three times (about 1,824 distinct).

| position | constant | sqrt | n_test |
|---|---|---|---|
| QB  | 3.4755 | 3.4710 |  576 |
| RB  | 3.5029 | 3.4867 | 1440 |
| WR  | 3.4063 | 3.3889 | 1728 |
| TE  | 3.3515 | 3.3395 |  576 |
| K   | 2.9283 | 2.9207 |  576 |
| DEF | 3.2338 | 3.2306 |  576 |
| **all** | **3.3647** | **3.3521** | **5472** |

The sqrt form wins at every position and overall, by 0.0126 nats per
observation. That is a small margin: it is the form with the lower held-out
NLL, not evidence that variance is strongly proportional to the projection.
It is the stored form.

Fitted coefficients (`c_pos`, all 2021-2025 starter-caliber rows). Per-league
columns are each league's own scoring, fitted on its 9,120 rows.

| position | pooled | NWC | New Wave | Zipline | max-min spread / pooled |
|---|---|---|---|---|---|
| QB  | 1.7868 | 1.8370 | 1.7609 | 1.7613 | 4.3% |
| RB  | 2.1820 | 2.1810 | 2.1783 | 2.1868 | 0.4% |
| WR  | 2.2055 | 2.1932 | 2.2340 | 2.1891 | 2.0% |
| TE  | 2.1795 | 2.1510 | 2.2409 | 2.1454 | 4.4% |
| K   | 1.5100 | 1.4419 | 1.5395 | 1.5462 | 6.9% |
| DEF | 2.1064 | 2.0840 | 2.1176 | 2.1176 | 1.6% |

The leagues differ by at most 6.9% (K), under the 10% flag threshold, so one
pooled set is stored. Default coefficient (unknown position): 2.0814. Rows
per position: QB 2,880, RB 7,200, WR 8,640, TE 2,880, K 2,880, DEF 2,880.

Mean residual (actual minus projection) over the same rows: QB -0.29, RB
+0.31, WR +0.24, TE +0.27, K -0.22, DEF -0.16. The SD is fitted around zero
residual, so this bias is inside the SD.

## B. Team-level calibration of lambda: measured

Population: each league's 2025 regular season (weeks 2 through
`playoff_week_start - 1`: 2-14 for NWC and New Wave, 2-13 for Zipline).
Week 1 is excluded because the projection pipeline requires cutoff >= 1.
Playoffs are excluded. Every starter is treated as pending, `mu` is the sum
of the cutoff `w-1` projections under that league's scoring, empty slots are
0, and an inactive starter simply scores his actual 0 (which `lambda`
absorbs; historical availability is not knowable). Of 3,903 starter slots,
none lacked a projection.

**n = 203 games** (NWC 78, New Wave 65, Zipline 60), no exact ties.

| forecast | Brier | log loss | favorite wins |
|---|---|---|---|
| (a) coin flip, 0.5 | 0.2500 | 0.6931 | n/a (no favorite) |
| (b) lambda = 1 | 0.2336 | 0.6590 | 63.5% (129/203) |
| (c) lambda = 0.9873 (fitted) | 0.2336 | 0.6590 | 63.5% (129/203) |

The favorite is the higher-`mu` side for both (b) and (c), so their accuracy
is identical. Fitting `lambda` changed log loss by 0.000005: the data say
`lambda` = 1. Its bootstrap 95% interval (300 resamples of the 203 games) is
0.61 to 1.85, so the point value is weakly determined. The log-loss gain over
a coin flip at the fitted `lambda` has bootstrap 95% interval 0.0023 to
0.0669 (point value 0.0341): better than a coin flip, but a gap that small
rests on 203 games.

Calibration at the fitted `lambda` (bins on the favorite's probability):

| bin | n | mean predicted | favorite won |
|---|---|---|---|
| [0.5, 0.6) | 114 | 0.551 | 0.649 |
| [0.6, 0.7) |  63 | 0.645 | 0.587 |
| [0.7, 0.8) |  24 | 0.739 | 0.667 |
| [0.8, 0.9) |   2 | 0.833 | 1.000 |
| [0.9, 1.0) |   0 | n/a   | n/a   |

The bins do not show a consistent direction (under-confident in the lowest
bin, over-confident in the next two), and the top two bins hold 26 games.
Treat the table as "no evidence of gross miscalibration", not as proof of good
calibration.

Leave-one-league-out `lambda` (fit on the other two leagues, scored on the
held-out one):

| held-out league | n | lambda from other two | held-out log loss | same at lambda = 1 | lambda fit on the league alone |
|---|---|---|---|---|---|
| NWC      | 78 | 0.9959 | 0.6590 | 0.6590 | 0.9732 |
| New Wave | 65 | 1.0410 | 0.6521 | 0.6518 | 0.8885 |
| Zipline  | 60 | 0.9325 | 0.6677 | 0.6670 | 1.1376 |

Across the held-out folds `lambda` ranged 0.93 to 1.04. Out of league, the
fitted value beat `lambda = 1` by 0.00001 log loss in one fold and lost by
0.0004 and 0.0008 in the other two. Refitting the player-level coefficients without 2025 gives
`lambda` = 0.9855, so overlap between the SD fit and calibration season does
not move it.

Team-level diagnostic over the 406 team-games: realised points minus `mu`
has mean +3.46 and SD 23.01; the model's root-mean-square team SD is 22.08.
The mean residual is a common bias on both sides of a matchup and mostly
cancels in the margin.

## Limitations

* **Independence.** The SD sums player variances as if starters were
  uncorrelated. A QB and his receivers move together, so the true team SD is
  larger. `lambda` is the only correction, and with n = 203 it is estimated
  at 0.99 with a 95% interval of 0.61 to 1.85: the data neither show that
  correlation is negligible nor identify how large it is.
* **Normality.** Assumed, not tested. A player's score has a floor and a
  right tail (kickers and defenses especially), and the tails of a team's
  score were not examined; the 0.8-1.0 calibration bins hold 2 games.
* **Games in progress are scored as final.** `mu` uses live points for a game
  that has kicked off and `sd` counts it as no longer pending, so a
  half-played game is treated as if its remaining points were known. Mid-game
  refreshes overstate certainty. This was not measured.
* **Starter-caliber population.** The SD is fitted on the top-N projected
  players who played. It says nothing about a deep bench player in a
  starting slot, and it is conditional on playing; the surprise-inactive
  effect is only captured at the team level through `lambda`, which is
  calibrated on 2025 games where every starter is counted pending.
* **Sample sizes.** 203 calibration games from three leagues in one season;
  the A-side leagues share the same player-weeks (scored three ways), so they
  are not three independent samples. The sqrt-vs-constant gain is 0.0126 nats.
* **Week 1 and playoffs** are not covered (see above).
* **Projection coupling.** The coefficients belong to this projection
  pipeline. A change to the usage model or EB constants invalidates them
  until the script is rerun.

## Reproduce

```bash
.venv/bin/python scripts/fit_win_probability.py --seasons 2021 2022 2023 2024 2025 \
    --calibration-season 2025
```

The rolling projection fits are cached under `.cache/win_probability/`
(the 2021 fit alone, on six seasons, took 3 min 50 s; later seasons fit on
more data and take longer). With the fits cached, the backtest and
calibration took roughly ten minutes (not timed precisely). Pass
`--report out.json` to dump every table above.
