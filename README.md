# 2026 US Senate Forecast

A probabilistic forecast of the 35 US Senate races on 3 November 2026.

Each race's forecast blends **fundamentals** (what we'd expect before any polling) with a
**de-biased polling average**, weighted by how much polling there is. 10,000 simulated
elections, with polling errors shared across races, turn those margins into win
probabilities and a chance of chamber control.

## How it works

1. **Partisan lean:** how much more Democratic or Republican a state is than the country,
   from the 2024, 2020 and 2016 presidential results (weighted 75 / 17.5 / 7.5%).
2. **Fundamentals:** lean + national environment (generic ballot) + incumbency +
   candidate quality + a demographic adjustment (groups that swung hard in 2024 are
   assumed to partly swing back). Appointed incumbents get half the incumbency bonus.
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

## Data sources

- Polls: New York Times poll database via [PollResults.org](https://pollresults.org/) (CC BY 4.0)
- Demographics: 2020 US Census redistricting data (table P4)
- Group swings 2020-2024: Pew Research Center validated voter studies
- Pollster ratings: ElectIndex
- Presidential results: state results 2016-2024
- Methodology inspired by the ElectIndex 2026 forecast's published methodology
