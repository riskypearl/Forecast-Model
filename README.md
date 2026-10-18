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

## Backtest: does candidate quality help?

`backtest.py` predicts every Senate race from 2018 to 2024 from fundamentals alone (no polls),
using only information available before each election, with and without candidate
adjustments.

| | Avg error | Winners right |
|---|---|---|
| Without candidate adjustments | 6.7 pts | 121/137 |
| With candidate adjustments | 6.1 pts | 120/137 |
| ...races where a candidate had a record (58) | 6.3 → 4.8 pts | 50 → 49 |

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
| Fundamentals only | 7.5 pts | 174 |
| Full model | 6.4 pts | 184 (91%) |

**Calibration:** favourites given 80-95% won 39 of 44 races (39.0 expected); favourites
given 95%+ won 124 of 125 (123.4 expected). The model's probabilities are honest.

**Poll weight:** relying more heavily on polls fitted 2012-2018 best but did *worse* on
2020-2022, when polls missed badly. The model's hedge towards fundamentals was kept.

**Lean compression (tested, rejected):** scaling presidential lean down (e.g. Senate races
follow 80% of it, for ticket-splitting) made predictions worse on unseen years. Modern
Senate results track presidential lean almost one-for-one - a sign of polarisation.

**Generic-ballot bias:** final generic-ballot polls overstated Democrats in 5 of 6 cycles,
by 3.2 points on average (2.4 in midterm years).

## Data sources

- Polls: New York Times poll database via [PollResults.org](https://pollresults.org/) (CC BY 4.0)
- Demographics: 2020 US Census redistricting data (table P4)
- Group swings 2020-2024: Pew Research Center validated voter studies
- Pollster ratings: ElectIndex
- Presidential results: state results 2016-2024
- Backtest: MIT Election Data + Science Lab, U.S. Senate and U.S. President 1976-2024 (CC0)
- Historical polls: FiveThirtyEight `raw_polls.csv` (github.com/fivethirtyeight/data, CC BY 4.0)
- Methodology inspired by the ElectIndex 2026 forecast's published methodology
