# UK general election nowcast (in progress)

A seat-by-seat nowcast for the next Westminster election, built with the same approach as the
US Senate model: a de-biased polling average, a swing model, tactical voting and simulations.
Methods are adapted from Hanretty, Lauderdale & Vivyan's electionforecast.co.uk model (papers in
`papers/`), re-implemented rather than copied.

Full run, in order:

```
python uk/fetch_results.py        # election results
python uk/fetch_census.py         # census
python uk/fetch_polls.py          # voting-intention polls
python uk/fetch_favourability.py  # leader ratings (tactical voting)
python uk/fetch_projections.py    # published seat projections (benchmark)
python uk/swing_regression.py     # fit the demographic swing
python uk/seat_model.py           # the nowcast
```

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

## Stage 2: seats

```
python uk/seat_model.py              # the nowcast: "if an election were held today"
python uk/seat_model.py --backtest   # test the swing model on 2019 notional -> 2024
```

(Run `python uk/swing_regression.py` first - see stage 3.)

Writes `data/seat_forecast.csv` (every GB seat: projected shares, win chances, rating) and
`data/seat_totals.csv` (seat range, chance of being largest party and of a majority of 326).

1. **Baseline:** each GB seat's 2024 result (`data/results_2024.csv`). Where Lab, Con, Ref, LD,
   Grn or Other didn't stand, they're given 1%. The Speaker's seat and Northern Ireland's 18 are held
   as they are.
2. **Logistic swing:** each party's national change is applied on the logit scale, with one
   shift per party solved so the seats add up exactly to the national figure. A party can't go
   negative, and gains land most where it was already competitive. "Other" swings uniformly
   instead, because its 2024 vote (local independents) and its growth since (new national
   parties) are different voters.
3. **Simulation (10,000 runs):** a national polling miss for each party (2.5 points SD for a
   party on 25%, t-distributed), then each seat's own error, then whoever is top wins.

**Calibrated on 2019 -> 2024**, using the 2019 results recalculated onto the 2024 boundaries
(`data/results_2019_notional.csv`). Given the real 2024 national result:

| Swing | Seats called right | Share error | Lab | Con | Ref | LD |
|---|---|---|---|---|---|---|
| Actual 2024 | | | 409 | 121 | 5 | 72 |
| Uniform | 441 / 631 | 6.4 pts | 303 | 236 | 1 | 32 |
| Logistic (stage 2) | 480 / 631 | 6.5 pts | 332 | 192 | 35 | 42 |
| Logistic + demographics (stage 3, used) | **509 / 631** | **5.5 pts** | 362 | 193 | 8 | 38 |

The stage 3 row is out of sample: its regression was fitted on 2010-2019 only.

Each seat's own error (5.7 points for a party on 25%) is the robust spread of the swing's
out-of-sample misses on 2024, measured on Lab, Con, LD, SNP and PC only. Reform's 2019 baseline
isn't clean (the Brexit Party stood aside in Conservative seats), and neither are the Greens'
or Others'.

## Stage 3: demographic swing

```
python uk/swing_regression.py   # fit, test, and write data/swing_coefficients.csv
```

Some seats swing harder than others. Each party's seat-level change becomes
**national shift x elasticity**, with elasticity = 1 + gamma . (seat features). The features
are the 2021 Census shares (degree, age 65+, age 18-34, white, Muslim, home ownership, social
renting, students, professional jobs), Wales and Scotland flags, and the party's own strength in
the seat. Gamma is fitted per party by weighted ridge regression, pooled over four election pairs:
2010->15, 2015->17 and 2017->19 (old boundaries, `results_2010.csv` ... `results_2019.csv`,
`census_2021_old_boundaries.csv`) and 2019 notional->2024. UKIP (2010-17) and the Brexit Party
(2019) count as Reform.

Tested by leaving one pair out (fit on three, predict the fourth), with the national result given:

| Held-out pair | Logistic | Demographic |
|---|---|---|
| 2010->15 | 590 / 631 | 586 / 631 |
| 2015->17 | 560 / 631 | 556 / 631 |
| 2017->19 | 582 / 630 | 580 / 630 |
| 2019->24 | 480 / 631 | **509 / 631** |
| Share error (average) | 4.16 pts | **3.96 pts** |

It helps most when the swing is big (2024) and costs a few seats in quieter years. What it
learned, roughly:
- Conservative and Reform swings run harder in non-graduate seats, softer in seats with many
  students or Muslim voters.
- Reform, Lib Dem and Green swings are less "multiplicative" than pure logistic: their gains
  don't pile up as much where they were already strong.
- Reform swings softer in Scotland.

The SNP and Plaid get almost no adjustment: too few seats to learn from.

Labour is still undercounted in the 2024 test (362 vs 409): anti-Conservative tactical voting
doesn't scale with Labour's national shift, which barely moved in 2024. That's stage 3b.

## Stage 3b: tactical voting

```
python uk/fetch_favourability.py   # leader / party ratings -> data/favourability.csv
python uk/fetch_projections.py     # published MRPs -> data/seat_projections.csv
python uk/tactical.py              # calibrate the squeeze on 2024
python uk/tactical_test.py         # compare tactical methods on past elections
python uk/tactical_test.py --nowcast
```

**The squeeze** (`tactical.py`). In each seat, voters of the parties outside the top two can
switch to whichever of the two they mind less. "Mind" = an affinity matrix
(`data/tactical_affinity.csv`, a judgement you can edit: 1 = opposite camps, 0.25 = near
neighbours) x the share with a negative view of each party's leader (`data/favourability.csv`,
3,000+ ratings since December 2019, from Wikipedia). It is full strength when the top two are
level, fades to nothing at a 25-point lead, and runs inside the swing solve, so national totals
still match the polls. One strength parameter is calibrated on 2024:

| 2019 notional -> 2024 | Seats right | Lab | Con | Ref | LD |
|---|---|---|---|---|---|
| Actual | | 409 | 121 | 5 | 72 |
| Demographic swing, no tactical | 509 / 631 | 362 | 193 | 8 | 38 |
| + squeeze, strength 1.5 | **543 / 631** | 402 | 121 | 4 | 67 |

**But it doesn't hold up on other elections.** `tactical_test.py` scores six methods with each
method's strength picked on the other election pairs and tested on the held-out one:

| Method | 2010->15 | 2015->17 | 2017->19 | 2019->24 | Total |
|---|---|---|---|---|---|
| None | 586 | 556 | 580 | 509 | **2231** |
| Affinity only (everyone equally disliked) | 577 | 558 | 573 | 517 | 2225 |
| Affinity x leader ratings | - | - | 574 | 524 | - |
| Only in seats whose top two changed | 586 | 555 | 579 | 510 | 2230 |
| Changed seats x leader ratings | - | - | 580 | 510 | - |
| Anti-government | 562 | 556 | 572 | 526 | 2216 |

(Ratings start in December 2019, so those methods only run on the last two pairs; there,
ratings 1,098 seats right vs none 1,089 and affinity-only 1,090 - a small edge.) 2024 needed a
strong squeeze; earlier elections almost none, and each baseline already contains its own
election's tactical voting. No method's strength can be learned from the others.

**So the nowcast draws a scenario per simulation** (`SCENARIOS` in `tactical.py`), a third each:

| Scenario | Strength | What it means now | Lab | Con | Ref | LD |
|---|---|---|---|---|---|---|
| none | 0 | no extra tactical voting beyond the 2024 baseline | 273 | 99 | 140 | 64 |
| ratings | ~1.5 | against the most disliked leaders - currently Farage, so mostly anti-Reform | 293 | 107 | 87 | 74 |
| anti-government | ~0.5 | outside voters back whoever can beat Labour | 181 | 123 | 176 | 68 |

(median seats in each scenario, 25 Oct 2026.) Strength also varies by run (log-normal, SD 0.75).
That makes the overall seat ranges much wider - Labour's 90% range is roughly 80-350 - which is
the honest position: the direction and size of the next tactical wave are the biggest unknown in
the model. For comparison, the published MRPs in `data/seat_projections.csv` (September-October
2026) have Labour at 241-353 and Reform at 84-153; Electoral Calculus's own tactical adjustment
takes 5-43 seats off Reform.

## Known gaps

Scottish seats have no census data, only the Scotland flag, and the SNP comes out too high in
the 2024 test (23 vs 9). Seat errors are independent apart from the tactical scenario, so seats
can't miss together by region or seat type yet (stage 4). The model also assumes 2024's
independents stand again, which is why "Other" wins around 15-20 seats.

## Not covered yet

Census data for Scotland's 57 seats (Scotland's 2022 census is published separately), Northern
Ireland (not modelled), Scotland- and Wales-specific polls, Leave-vote estimates on the new
boundaries, and by-elections or defections since 2024.
