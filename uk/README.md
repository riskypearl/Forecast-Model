# UK general election nowcast (in progress)

A seat-by-seat nowcast for the next Westminster election, built with the same approach as the
US Senate model: a de-biased polling average, then (to come) a swing model and correlated
simulations. Methods are adapted from Hanretty, Lauderdale & Vivyan's electionforecast.co.uk
model (papers in `papers/`), re-implemented rather than copied.

## Stage 1: data and polling average

```
python uk/fetch_results.py   # 2024 results, 650 seats on the 2024 boundaries
python uk/fetch_census.py    # 2021 Census, 575 England & Wales seats
python uk/fetch_polls.py     # national polls since July 2024, from Wikipedia
python uk/poll_average.py    # GB average with house effects removed
```

| File | What's in it | Source |
|---|---|---|
| `data/results_2024.csv` | votes and shares for Lab, Con, Ref, LD, Grn, SNP, PC, Oth; winner, majority, turnout, Speaker's seat | electionresults.parliament.uk (Commons Library) |
| `data/census_2021.csv` | degree, professional / routine jobs, students, age 18-34 / 65+, ethnicity, religion, home ownership / renting | ONS census API (`p19wpc` = 2024 seats) |
| `data/polls.csv` | one row per GB/UK poll; parties not tracked (Restore Britain, Your Party ...) are in Oth | Wikipedia |
| `data/poll_average.csv` | today's average, the average without house effects, and how noisy each party's polls are | `poll_average.py` |
| `data/house_effects.csv` | each pollster's lean, in points against today's average | `poll_average.py` |
| `data/poll_trend.csv` | the average every week since the election | `poll_average.py` |

**How the average works.** Each poll becomes log-ratios against Labour (log(party / Lab)), so
shares always add to 100 and none can go negative. House effects are each pollster's average gap
against other pollsters' polls from the same fortnight, shrunk for pollsters with few polls and
centred on the average pollster. Polls are then weighted by recency (21-day half-life) and
sample size (capped at 5,000 so MRPs don't dominate). Weekly pollsters are damped so they don't
outweigh everyone else just by polling more often. All of these are settings at the top of
`poll_average.py`.

**Not covered yet:** census data for Scotland's 57 seats (Scotland's 2022 census is published
separately), Northern Ireland (not modelled), Scotland- and Wales-specific polls, Leave-vote
estimates on the new boundaries, and by-elections or defections since 2024.
