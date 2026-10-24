"""
Should a state's lean include how it votes for governor and Senate, not just
for president? (Kansas: R+16 for president, but it elected Laura Kelly twice.)

backtest.STATEWIDE_LEAN_WEIGHT blends the presidential lean with the state's
average lean in governor and Senate races from the last STATEWIDE_LEAN_YEARS
years (each race's margin minus that year's national environment, Senate
incumbency removed; races involving the current candidates left out, since
their records are the candidate adjustment).

Scored two ways, tuned on the early years and checked on unseen later ones:
  1. fundamentals only, Senate races 2008-16 / 2018-24 (with the Senate and
     governor candidate adjustments the model uses)
  2. the full model with polls, 2012-18 / 2020-22, forecasts 1 and 21 days out

Run it with:  python backtest_statewide_lean.py
"""

from itertools import product

import backtest as bt
import backtest_full as bf
import backtest_governor as bg
import forecast as fc

WEIGHTS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
YEARS = [4, 8, 12]


def fundamentals_scores(races, gov_races, pres, national):
    tune, check = [], []
    for race in races:
        if race["year"] not in bg.TUNE + bg.CHECK:
            continue
        sen = [bt.candidate_record(race[s], race["state"], race["year"], races, pres, national)
               for s in ("dem", "rep")]
        pred = (bt.baseline(race, races, pres, national)
                + bt.CANDIDATE_SHRINK * sum(x for x in sen if x is not None)
                + sum(bg.model_governor_adjustment(race[s], s, race["state"], race["year"], gov_races, pres, national)
                      for s in ("dem", "rep")))
        (tune if race["year"] in bg.TUNE else check).append((race["margin"], pred))
    score = lambda rows: (sum(abs(a - p) for a, p in rows) / len(rows), sum((a > 0) == (p > 0) for a, p in rows))
    return score(tune), score(check), len(check)


def full_scores(polls, races, pres, national, weights, days):
    bf.DAYS_BEFORE = days
    results = []
    for cycle in bf.CYCLES:
        results += bf.run_cycle(cycle, polls, races, pres, national, weights)[1]
    bf.DAYS_BEFORE = 1
    miss = lambda cyc: sum(abs(r["actual"] - r["model"]) for r in results if r["cycle"] in cyc) / \
        sum(r["cycle"] in cyc for r in results)
    return miss([2012, 2014, 2016, 2018]), miss([2020, 2022])


def main():
    pres, national = bt.presidential_margins()
    races = bt.senate_races()
    gov_races = bg.governor_races()
    bf.SIMS_PER_RACE = 50
    polls = bf.load_538()
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")

    print("Statewide (governor + Senate) lean blended into the presidential lean\n")
    print(f"  {'weight':>6}{'years':>6}   {'fundamentals only':^28}   {'full model, avg miss':^34}")
    print(f"  {'':>6}{'':>6}   {'tune 08-16':>10}{'check 18-24':>18}   {'1 day: tune':>12}{'check':>7}{'21 days: tune':>15}{'check':>7}")
    for w, yrs in product(WEIGHTS, YEARS):
        if w == 0 and yrs != YEARS[0]:
            continue
        bt.STATEWIDE_LEAN_WEIGHT, bt.STATEWIDE_LEAN_YEARS = w, yrs
        (tm, tr), (cm, cr), n = fundamentals_scores(races, gov_races, pres, national)
        f1 = full_scores(polls, races, pres, national, weights, 1)
        f21 = full_scores(polls, races, pres, national, weights, 21)
        label = "current" if w == 0 else f"{yrs}"
        print(f"  {w:>6}{label:>8} {tm:>10.2f}{cm:>11.2f} {cr:>3}/{n}"
              f"   {f1[0]:>10.2f}{f1[1]:>7.2f}{f21[0]:>13.2f}{f21[1]:>7.2f}")
    bt.STATEWIDE_LEAN_WEIGHT = 0.0

    print("\n2026 leans (presidential vs statewide, last 8 years, current candidates left out):")
    import csv
    for row in csv.DictReader(open("data/candidates.csv", encoding="cp1252")):
        st = row["state"]
        exclude = (bt.name_key(row["dem_candidate"].upper()), bt.name_key(row["rep_candidate"].upper()))
        sw = bt.statewide_lean(st, 2026, exclude)
        if sw is not None and abs(bt.presidential_lean(st, 2026, pres, national)) < 25:
            print(f"  {st}  presidential {bt.presidential_lean(st, 2026, pres, national):+6.1f}   statewide {sw:+6.1f}")


if __name__ == "__main__":
    main()
