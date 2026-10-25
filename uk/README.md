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
python uk/fetch_favourability.py  # leader ratings (tactical-voting comparison)
python uk/fetch_projections.py    # published seat projections (benchmark)
python uk/bes_tables.py <panel>   # British Election Study tables (tactical voting) - see stage 3b
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

Each seat's own error (5.5 points for a party on 25%) is the robust spread of the swing's
out-of-sample misses on 2024, with 2024's tactical squeeze included (stage 3b), measured on Lab,
Con, LD, SNP and PC only. Reform's 2019 baseline
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
python uk/fetch_yougov_tactical.py     # YouGov two-horse-race tables -> data/yougov_tactical.csv (needs pypdf)
python uk/bes_tables.py <panel .dta>   # BES "would you ever vote for" tables -> data/bes/ptv_tables.csv
python uk/fetch_favourability.py       # leader / party ratings -> data/favourability.csv
python uk/fetch_projections.py         # published MRPs -> data/seat_projections.csv
python uk/tactical_test.py             # compare tactical methods on past elections
python uk/tactical_test.py --nowcast   # today's seats under each method
```

**The squeeze** (`tactical.py`). In each seat, voters of the parties outside the top two can
switch to one of the two. It is full strength when the top two are level, fades to nothing at a
25-point lead, and runs inside the swing solve, so national totals still match the polls.

**The nowcast uses YouGov's measured rates.** YouGov's tactical-voting study (15-22 September
2026, 6,077 GB adults; earlier runs February 2025 and February 2026) asks: "imagine the only two
parties with a chance of winning in your constituency were X and Y - how would you vote?", for
ten pairings, by current vote. `fetch_yougov_tactical.py` reads the published tables into
`data/yougov_tactical.csv`. In a seat whose top two are one of those pairings, the other parties'
voters move at exactly those rates - to either party or to not voting. For example, Labour v
Reform:

| Current vote | Con | Lab | LD | Ref | Grn |
|---|---|---|---|---|---|
| would vote Labour | 18 | 97 | 68 | 0 | 63 |
| would vote Reform | 37 | 1 | 5 | 98 | 2 |

These rates already reflect Andy Burnham (leader from July 2026): between February and September
Labour v Green seats went from Green 30-20 to Labour 27-21, and Labour v Reform from 35-31 to
41-26. The ten pairings cover 538 of the 631 GB seats; the rest (mostly SNP and Plaid contests)
use the BES squeeze below. Run-to-run, the rates are scaled by a log-normal factor (SD 0.3), for
people following through on a hypothetical more or less than they say. YouGov's study has no
pre-2024 equivalent, so unlike the methods below it can't be scored on a past election.

**The BES squeeze, for the remaining seats and the backtests.** Who'd switch to whom, measured: the British Election Study Internet Panel
asks everyone how likely they are ever to vote for each party (0-10). `bes_tables.py` averages
that by current vote intention, from the wave before each election - 5 (2015), 12 (2017),
18 (2019), 27 (2024; the campaign wave didn't ask it) and 31 (May-June 2026, for the nowcast).
UKIP stands in for Reform up to 2017 and the Brexit Party in 2019. Now, for example:

| Voters of / for | Lab | Con | Ref | LD | Grn |
|---|---|---|---|---|---|
| Lab | 8.3 | 1.5 | 0.5 | 5.0 | 4.2 |
| Con | 1.4 | 8.6 | 2.9 | 2.5 | 1.1 |
| Ref | 0.7 | 4.7 | 8.9 | 1.1 | 0.8 |
| LD | 3.9 | 2.1 | 0.5 | 8.2 | 3.9 |
| Grn | 3.9 | 0.9 | 0.2 | 4.1 | 8.8 |

The BES files aren't in the repo (their terms don't allow redistributing them; `uk/data/bes/` is
git-ignored). Download the combined panel (`BES2024_W31_Panel_v31.05.dta`, free, from
britishelectionstudy.com) and run `bes_tables.py` on it before `seat_model.py`.

**Tested against the alternatives.** `tactical_test.py` scores each method on four past
elections, with its strength picked on the other three and tested on the held-out one (seats
called right, national result given):

| Method | 2010->15 | 2015->17 | 2017->19 | 2019->24 | Total |
|---|---|---|---|---|---|
| None | 586 | 556 | 580 | 509 | 2231 |
| **BES** | **593** | 550 | 573 | 521 | **2237** |
| BES, only in seats whose top two changed | 587 | 555 | 580 | 511 | 2233 |
| Only in seats whose top two changed | 586 | 555 | 579 | 510 | 2230 |
| Affinity only (judgement, everyone equally disliked) | 577 | 558 | 573 | 517 | 2225 |
| Anti-government | 562 | 556 | 572 | 526 | 2216 |
| Affinity x leader ratings | - | - | 574 | 524 | - |

BES is the only method to beat "none" out of sample, by a little. Held at one fixed strength, 1.5-3
gained 13-21 seats over "none" across the four elections, helping in the big-shift years (2015,
2024) and costing a few in 2017 and 2019. It runs at 1.5 where YouGov has no pairing. Any of
these methods can be mixed back into the nowcast through `SCENARIOS` in `tactical.py`.

**Its weakness, and why the nowcast moved to YouGov**: BES wave 31 (May-June 2026) predates
Burnham. An adjustment was tried (`burnham_adjustment.py`: shift each respondent's view of the
Labour leader by YouGov's Starmer-to-Burnham change, and carry it into their Labour score) and
backtested on the two leader changes in the BES panel (`leader_change_test.py`). It failed: the
real change was 2.2x its prediction for May -> Johnson and 0.25x for Corbyn -> Starmer, so it
isn't used.

**What it does now** (25 Oct 2026, median seats, 10,000 runs):

| | Lab | Con | Ref | LD | Grn |
|---|---|---|---|---|---|
| No tactical voting | 272 | 100 | 141 | 64 | 8 |
| BES squeeze | 263 | 113 | 120 | 68 | 14 |
| **YouGov rates (used)** | **273** | **134** | **81** | **75** | **18** |

With YouGov's rates Reform loses ~60 seats, to the Conservatives (Labour, Lib Dem and Green
voters backing them in Conservative-v-Reform seats) and to Labour and the Lib Dems. Reform's 90%
range is 33-152. One assumption still holds Labour back: national totals are held to the polls,
i.e. polls are assumed to already include tactical voting; if they don't, Labour gains more.

For comparison, the published MRPs in `data/seat_projections.csv` (September-October 2026) have
Labour at 241-353 and Reform at 84-153; Electoral Calculus's tactical versions have Reform at
81-108, and More in Common's September tactical scenario 117.

## Sussex & Brighton mayor (May 2028)

```
python uk/fetch_poll_history.py   # GB polls since 2010 + BBC projected national shares -> data/poll_history.csv, pns.csv
python uk/local_gap.py            # local elections vs national polls, 2012-2026 -> data/local_gap.csv
python uk/fetch_sv_results.py     # 2021-22 supplementary-vote counts (mayors + PCCs) -> data/sv_2021.csv
python uk/mayor_vs_ge.py          # 2024 mayors vs GE; model backtest on the 2025 mayors
python uk/mayoral_adjustment.py   # combine into the Sussex adjustment -> data/mayoral_adjustment.csv
python uk/bourne_effect.py        # Katy Bourne's personal vote from her four Sussex PCC elections
python uk/sussex_mayor.py         # method 1, general-election route: May 2028 (--today: if held today)
python uk/sussex_mayor_local.py   # method 2, council route: if held today (--2028: May 2028)
python uk/mayor_backtest.py       # method 1 on the 2021-22 supplementary-vote mayors
```

Two methods, run side by side because no past election is a clean stand-in for this one: the
general election had real stakes but very different turnout; the councils and PCCs are local but
low-stakes, and Reform wasn't on the PCC ballot.

The first election for the new Sussex & Brighton mayoralty was moved from May 2026 to May 2028,
and is expected to use the supplementary vote (a first and second choice; if no one has 50%,
the top two go through and the others' second choices are added).

**Method 1, general-election route** (`sussex_mayor.py`):

1. **First choices**: the general-election model for Sussex's 17 constituencies, without
   tactical voting (people can vote sincerely first under the supplementary vote).
2. **Time to May 2028**: each run adds one real historical movement in the national polls over
   the same 557 days (756 such stretches since 2010), centred on zero so past trends - UKIP's and
   Reform's rises, the Conservative collapse - aren't carried forward, only their size.
3. **Mayoral adjustment** (`mayoral_adjustment.py`), three measured parts:

   | Points | Lab | Con | Ref | LD | Grn |
   |---|---|---|---|---|---|
   | National local gap: local elections vs polls, 2012-26 | -5.2 | -3.0 | +1.7 | +6.9 | +4.7 |
   | Mayoral vs local: 2024-25 mayors after that year's gap | +2.4 | +3.7 | -2.3 | -3.3 | -4.7 |
   | Sussex's own local pattern, 2021 + 2026 councils | +1.7 | -1.0 | +3.8 | -5.4 | -1.9 |
   | **Total** | **-1.1** | **-0.3** | **+3.2** | **-1.9** | **-1.9** |

   - Labour has run below its polls in local elections every year since 2012, in government and
     in opposition alike; being in government or years into a term made no measurable difference
     (`local_gap.py`, tested year by year), so each party's average gap is used. Labour's dire
     2026 local result (projected share 17%) was mostly its polling at the time (19%).
   - Area-wide mayoral races give back some of that and squeeze the Lib Dems and Greens.
   - Sussex: (council share - national local share) - (Sussex GE share - national GE share).
     The Lib Dems' Sussex council vote is high, but not as high as their 2024 general-election
     vote there (much of it tactical, behind strong MPs); 2021 and 2026 agree (-5.2 / -5.6).
   - Each run draws the national gap and the Sussex pattern with their measured noise, and one
     real 2024/25 mayoral area's residuals whole - candidate effects are lumpy and come at the
     other parties' expense. Areas where an incumbent mayor stood are left out of the draws
     (London, West Midlands, Greater Manchester, West Yorkshire, Liverpool City Region, South
     Yorkshire, Tees Valley 2024; Doncaster 2025): no Sussex candidate is an incumbent mayor, and
     their personal votes (Burnham +21, Houchen +22, Street +14, Rotheram +12 ...) would otherwise
     inflate Labour and the Conservatives. That leaves 8 areas, averaging Labour -1.2,
     Conservative +1.9, Reform -1.7, Lib Dem -1.5, Green -3.2 (the table's "mayoral vs local"
     row is all 16).
   - Independents and others likewise get one real 2024/25 area's shift per run
     (`data/other_shifts.csv`): median +2 points, but up to +15 in one area in ten and +25 at
     most (Jamie Driscoll, North East 2024).
4. **Second count**: the others' voters transfer at YouGov's two-horse-race rates, calibrated on
   the 12 mayoral contests of 2021-22 that went to second choices (London, West Midlands, West
   Yorkshire ...). YouGov's rates predicted **how many** second choices reached the finalists
   almost exactly (1.01x), but real second choices **split** less one-sidedly - about 0.43x
   as lopsided as YouGov's answers, measured from 50/50. Each run draws a value between 0.43
   and 1. Police and crime commissioner counts were scraped too but not used: lower-profile
   races, more independents, and they behaved differently (0.85x).

**Katy Bourne's personal vote** (`bourne_effect.py`): in all four Sussex PCC elections she ran
ahead of the typical Conservative PCC candidate (against each area's general-election
Conservative share) by +2.6 (2012), +11.5 (2016), +2.8 (2021) and +4.7 (2024) - in the top third
of 36 forces each time. The model adds +3.8 (the like-for-like 2021 and 2024 comparisons), with
the spread of all four years as uncertainty (both methods).

**Method 2, council route** (`sussex_mayor_local.py`): starts from how Sussex actually voted
locally - the real votes in the May 2026 West Sussex and East Sussex county elections and the May
2023 Brighton & Hove election, weighted by voters (Brighton's multi-member wards divided out), so
local turnout is built in. Each area is moved by the national change since its election (polls in
the 3 weeks before it vs now, logit scale, plus a polling miss); Reform in Brighton, which didn't
stand in 2023, starts from its 2024 general-election share there. Then the same mayoral
residuals (no incumbents), Bourne's personal vote, independents' shift and second count as
method 1. Its weakness is the one raised about the 2026 county elections: little was at stake
(councils due for abolition, an unpopular government), which can understate the mainstream
parties - Labour especially. PCC results aren't used as a baseline because Reform didn't stand
in 2021 or 2024; they're used for Bourne's personal vote and as a check on Labour (Labour's 2021
and 2024 Sussex PCC shares, scaled to today's polls: 15-19%).

**The forecast: the likely shape, with ranges** (from polls on 25 Oct 2026; 10,000 runs each)

- Katy Bourne (Con) is the favourite under both methods and in every version tried.
- Reform is likely to be at or near the top of the first round but usually loses the second
  count, because second choices run heavily against it.
- The race is mostly about who joins Reform in the final: Bourne, or less often the Lib Dems or
  Labour.
- The exact numbers are soft; the two methods disagree mainly on Bourne's first-round share
  (about 3.5 points).

| First round, if held today | Method 1 (GE route) | Method 2 (council route) |
|---|---|---|
| Con - Katy Bourne | 24.5% | 28.0% |
| Ref - Paul Linehan | 23.1% | 22.0% |
| Lab - Caroline Baxter | 15.3% | 15.0% |
| LD - Ben Dempsey | 15.1% | 14.8% |
| Grn - Rachel Millward | 12.1% | 11.2% |
| Ind - Martin Webb and others | 6.8% | 5.9% |
| **Most likely final, if held today** | Con v Ref (49% of runs): **Con 59 - Ref 41** | Con v Ref (62%): **Con 62 - Ref 38** |

| Chance of winning | Method 1, today | Method 2, today | Method 1, May 2028 | Method 2, May 2028 |
|---|---|---|---|---|
| Con | 59% | 78% | **46%** | **60%** |
| LD | 18% | 15% | 17% | 17% |
| Lab | 11% | 3% | 18% | 11% |
| Ref | 9% | 2% | 16% | 10% |
| Ind | 3% | 3% | 2% | 2% |
| Grn | 1% | 0% | 1% | 0% |

The May 2028 columns add real historical poll movement over the 557 days to polling day
(centred on zero). That assumes politics stays about as turbulent as 2010-2026 - roughly ten
independent 18-month stretches, dominated by one-off shocks - so treat it as a rough guide to how
much could change, not a measurement. Labour's first-round share is best read as 15-19% (the
council route is the low end, for the reason above).

**When the May 2027 results arrive** (likely the first elections to Sussex's new councils, with
real stakes, and the first big test of Labour under Burnham at the ballot box):
1. Swap method 2's baseline to the 2027 results, including Brighton & Hove's 2027 all-out election.
2. Add 2027 to `data/pns.csv` and rerun `local_gap.py`: does Labour's local gap change under
   Burnham?
3. Re-run `mayoral_adjustment.py` with the 2027 Sussex council results as a third snapshot of
   Sussex's own pattern.
4. When the next BES wave comes out, measure the local turnout drop-off and switching by party
   from its "did you vote / who for in the locals" questions, check it reproduces the 2027
   projected national share, and if so use it in place of the national local gap.
5. Re-run both methods and save the forecast with its date, to score against the real result
   in May 2028.

**Backtest** (`mayor_backtest.py`): the whole method run on the 14 mayoral elections of 2021-22
that used the supplementary vote, with what was known on polling day (2019 baseline, polls in
the 3 weeks before, demographic swing fitted on 2010-19, local gap from earlier years):

| | Winners called | Main-party shares inside the 90% range | Independents / others inside |
|---|---|---|---|
| Combined-authority mayors (8 - the Sussex type) | **6 of 8** | **91%** | 4 of 4 |
| All 14 (adds Salford, Doncaster, North Tyneside, Croydon, Newham, Tower Hamlets) | 9 of 14 | 86% | 8 of 10 |

The two combined-authority misses were candidate-driven: Andy Street (West Midlands, 11 points
above the model) and a strong Lib Dem in Cambridgeshire whose second choices carried Labour.
The single-council misses were London-borough local politics (Croydon; Tower Hamlets, won by
Lutfur Rahman's Aspire). The independents' range was widened after a first run left them inside
it only 2 times in 10; the new range is measured on the 2024-25 mayors, so 2021-22 is a fair
test of it. Not fully out of sample: the mayoral-vs-local residuals come from 2024-25, and the
second-count calibration was fitted on these same contests. Bristol (wrong year scraped) and
Tees Valley (two candidates) are left out; parties that didn't stand aren't scored.

**Not included**: other candidates' personal votes, except as spread (they're unmeasured until
the campaign), new parties that haven't declared (Restore Britain, Your Party), and turnout
geography within method 1 (its Sussex-wide shares weight seats by 2024 general-election turnout).

## Known gaps

Scottish seats have no census data, only the Scotland flag, and the SNP comes out too high in
the 2024 test (23 vs 9). Seat errors are independent apart from the tactical strength, so seats
can't miss together by region or seat type yet (stage 4). The model also assumes 2024's
independents stand again, which is why "Other" wins around 15-20 seats.

## Not covered yet

Census data for Scotland's 57 seats (Scotland's 2022 census is published separately), Northern
Ireland (not modelled), Scotland- and Wales-specific polls, Leave-vote estimates on the new
boundaries, and by-elections or defections since 2024.
