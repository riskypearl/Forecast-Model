# 2026 US Senate Forecast

A probabilistic forecast of the 35 US Senate races on 3 November 2026.

Each race's forecast blends **fundamentals** (what we'd expect before any polling) with a
**de-biased polling average**, weighted by how much polling there is. 10,000 simulated
elections, with polling errors shared across races, turn those margins into win
probabilities and a chance of chamber control.

## How it works

1. **Partisan lean:** how much more Democratic or Republican a state is than the country,
   from the 2024, 2020 and 2016 presidential results (weighted 75 / 17.5 / 7.5%).
2. **Fundamentals:** lean + national environment + incumbency +
   candidate quality + a demographic adjustment (groups that swung hard in 2024 are
   assumed to partly swing back). Appointed incumbents get half the incumbency bonus.
   Candidate quality is calculated automatically from each 2026 candidate's competitive
   Senate races in the last 12 years (the same method `backtest.py` tests); records outside
   the Senate data (e.g. House, Attorney General) are entered by hand in `states.csv`.
   The national environment is a recency-weighted generic-ballot average: every pollster's
   lean is measured against reputable pollsters (rated 2.0+) and removed, and undecided
   voters are split evenly.
3. **Polling average:** undecided voters are allocated the way the state usually votes
   ("coming home"); polls are then recency-, sample-size- and quality-weighted;
   partisan-sponsored polls count for half; pollster house effects are estimated and removed.
4. **Blend:** the more recent polling a race has, the more the polls count.
5. **Simulation:** one national error shared by every race plus one error per race.
   Uncertainty is wider for races with little polling and further from election day, and
   errors come from a fat-tailed distribution so upsets aren't treated as near-impossible.
   Part of each race's error is shared with its region (Northeast, Midwest, South, West), so
   neighbouring states' polls can miss together.

Every assumption is a named setting at the top of `forecast.py`.

## Running it

```
python fetch_polls.py        # download the latest polls
python forecast.py           # run the forecast
```

`fetch_demographics.py` (needs a free Census API key in `CENSUS_API_KEY`) only needs
running once.

Each run writes `results.csv`, a dated copy in `history/`, and a line in
`history/timeline.csv`.

`update.ps1` does all of it (fetch, forecast, commit, push) and runs automatically every
2 days until 2 November 2026 via Windows Task Scheduler.

## House forecast

`house_forecast.py` forecasts all 435 districts with the same machinery: district lean
(2016/2020/2024 presidential results on the **2026 maps**), the same national environment,
incumbency, district polls (100 districts have them), and the same simulation.

- **House incumbency = 3.7 points**, measured from 2024: incumbent Democrats ran 3.8 points
  ahead of Harris and incumbent Republicans 3.7 ahead of Trump (states with unchanged maps).
- **Candidate quality**: same rule as the Senate - how far a candidate ran ahead of their
  district's 2024 presidential vote in a competitive race (within 15), minus incumbency,
  two-thirds kept. Only where the 2026 lines match 2024. 63 districts get one (e.g.
  Fitzpatrick -8.8, Miller-Meeks +8.1). Known weakness: the record also reflects the old
  opponent (AK-01: Begich's 2024 result was against Peltola, who isn't running there now).
- Uncontested seats and California same-party top-two races are certain wins.
- Not yet included: demographic adjustment.

**House backtest** (`house_backtest.py`, fundamentals with the actual national House vote,
2,400+ contested races; tuned on 2016-20, checked on 2022-24):

| | 2016-20 avg miss | 2022-24 avg miss | 2022-24 winners |
|---|---|---|---|
| Lean + environment | 6.88 | 5.14 | 584/625 |
| + incumbency (3.7) | 6.02 | 5.06 | 592/625 |
| + candidate quality | 5.92 | 4.81 | 593/625 |

Candidate quality helps on both periods - the same rule that worked for the Senate works
for the House. Incumbency 3.7 fits 2016-20 best; on 2022-24 alone a smaller bonus (2.0)
did slightly better, consistent with incumbency advantage shrinking over time.

**Full House backtest with polls** (`house_backtest_full.py`, 2016-2022, generic-ballot polls
for the environment, 346 races with district polls): calibration is good (favourites given
80-95% won 238 of 263, 234.8 expected; Brier 0.037). Unlike the Senate, **heavier poll
weighting helped on both periods** (2020-22: 5.47 vs 5.86 avg miss), so the House model gives
district polls more weight (max 0.95, n/(n+0.5)). District fundamentals are cruder than
state ones, so the rare district poll carries more information.

District presidential results for past maps: Daily Kos Elections / The Downballot
(https://www.the-downballot.com/p/data), used locally and not republished, per their terms.

District results and candidate rosters come from the ElectIndex
`26_us_forecast_data` repository. It has no licence, so those files are used locally
(`data/electindex/`, git-ignored) and not republished here.

## Backtest: does candidate quality help?

`backtest.py` predicts every Senate race from 2018 to 2024 from fundamentals alone (no polls),
using only information available before each election, with and without candidate
adjustments.

| | Avg error | Winners right |
|---|---|---|
| Without candidate adjustments | 6.8 pts | 122/137 |
| With candidate adjustments | 6.3 pts | 121/137 |
| ...races where a candidate had a record (58) | 6.2 → 5.0 pts | 51 → 50 |

Key finding: candidate quality only predicts results when measured from **competitive,
recent** past races (margin within 15, within 12 years). Measured from all past races -
including blowouts against unknown opponents - the adjustment made predictions *worse*.
All five 2026 adjustments (Collins, Osborn, Paxton, Brown, Peltola) come from competitive
races in the last 12 years.

## Full-model backtest

`backtest_full.py` runs the whole model (generic ballot, polls, fundamentals, blend,
uncertainty) on every Senate race from 2012 to 2022, as of the day before each election,
using FiveThirtyEight's historical polls.

| 203 races, 2012-2022 | Avg miss | Winners right |
|---|---|---|
| Fundamentals only | 7.3 pts | 178 |
| Full model | 6.2 pts | 186 (92%) |

**Calibration:** favourites given 80-95% won 31 of 36 races (32.1 expected); favourites
given 95%+ won 131 of 132 (130.5 expected). Brier score 0.060. The model's probabilities are honest.

**Poll weight:** relying more heavily on polls fitted 2012-2018 best but did *worse* on
2020-2022, when polls missed badly. The model's hedge towards fundamentals was kept.

**Lean compression (tested, rejected):** scaling presidential lean down (e.g. Senate races
follow 80% of it, for ticket-splitting) made predictions worse on unseen years. Modern
Senate results track presidential lean almost one-for-one - a sign of polarisation.

**Judgment calls tested** (`backtest_choices.py`; changed only if better by 0.1+ pts on unseen 2020-22):
- Undecided voters split by state baseline vs 50/50 vs left out: tie - kept
- Partisan-poll weight 0 / 0.25 / 0.5 / 1: no real difference - kept 0.5
- Incumbency bonus: 5 points beat 2.5 on both periods (5.39 vs 5.64) - **changed to 5**
- Lean weights: mixed results - kept 75 / 17.5 / 7.5
- Opponent-strength correction (subtract an earlier opponent's own record): worse on the
  fundamentals backtest, only 0.08 better on the full model - not adopted
  (`OPPONENT_CORRECTION = 0` in `backtest.py`)
- Own pollster ratings from FiveThirtyEight's accuracy data (`pollster_ratings_own.py`): two
  simple methods tried, both failed a sense check (one rewarded lucky partisan lean, the other
  punished small district polls and rewarded herding) - not adopted
- **Pollster ratings now come from Silver Bulletin** (letter grades -> weights: A+ 1.0 ... B 0.7
  ... C+ 0.5, F = excluded; unrated 0.5). They adjust for sample size, race type and herding,
  which simple methods miss. Can't be fairly backtested (built on data including 2020-22), so
  adopted on a sense check; switching moved no Senate or House call. Used locally, not
  republished (`data/silverbulletin/`, git-ignored). ElectIndex ratings remain the fallback.
- Down-ballot lean (blend in each state's House vote, contested districts only): worse on the
  full model and on older years - not adopted (`HOUSE_LEAN_WEIGHT = 0`). Michigan's House lean
  is actually slightly *more* Democratic than its presidential lean, so it doesn't explain
  Michigan Senate races running close.

**Generic-ballot bias:** final generic-ballot polls overstated Democrats in 5 of 6 cycles,
by 3.2 points on average (2.4 in midterm years).

## Data sources

- Polls: New York Times poll database via [PollResults.org](https://pollresults.org/) (CC BY 4.0)
- Demographics: 2020 US Census redistricting data (table P4)
- Group swings 2020-2024: Pew Research Center validated voter studies
- Pollster ratings: ElectIndex
- Presidential results: state results 2016-2024
- Backtest: MIT Election Data + Science Lab, U.S. Senate, U.S. President and U.S. House 1976-2024 (CC0)
- Historical polls: FiveThirtyEight `raw_polls.csv` (github.com/fivethirtyeight/data, CC BY 4.0)
- Methodology inspired by the ElectIndex 2026 forecast's published methodology
