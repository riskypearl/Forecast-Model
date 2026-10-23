"""
How fast should the polls take over from the fundamentals? poll_weight() is
MAX_POLL_WEIGHT * n / (n + POLL_WEIGHT_K), n = effective number of polls.
Scored with forecasts made 1, 7, 14, 21 and 28 days out; tuned on 2012-2018,
checked on 2020-2022.

Run it with:  python backtest_poll_weight.py
"""

import backtest as bt
import backtest_full as bf
import forecast as fc

TUNE = [2012, 2014, 2016, 2018]
CHECK = [2020, 2022]
DAYS_OUT = [1, 7, 14, 21, 28]


def score(results, cycles):
    sub = [r for r in results if r["cycle"] in cycles]
    return sum(abs(r["actual"] - r["model"]) for r in sub) / len(sub)


def main():
    bf.SIMS_PER_RACE = 50   # only margins matter here
    polls = bf.load_538()
    races = bt.senate_races()
    pres, national = bt.presidential_margins()
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")
    current = fc.MAX_POLL_WEIGHT, fc.POLL_WEIGHT_K

    print("Average miss (points), mean over forecasts made 1-28 days out")
    print(f"  {'cap':>5}{'K':>4}{'tune 2012-18':>14}{'check 2020-22':>15}")
    for cap in (0.75, 0.85, 0.95):
        for k in (1, 2, 3, 4, 6):
            fc.MAX_POLL_WEIGHT, fc.POLL_WEIGHT_K = cap, k
            tune, check = [], []
            for days in DAYS_OUT:
                bf.DAYS_BEFORE = days
                results = []
                for cycle in TUNE + CHECK:
                    results += bf.run_cycle(cycle, polls, races, pres, national, weights)[1]
                tune.append(score(results, TUNE))
                check.append(score(results, CHECK))
            flag = "  (current)" if (cap, k) == current else ""
            print(f"  {cap:>5}{k:>4}{sum(tune) / len(tune):>14.2f}{sum(check) / len(check):>15.2f}{flag}")
    fc.MAX_POLL_WEIGHT, fc.POLL_WEIGHT_K = current
    bf.DAYS_BEFORE = 1


if __name__ == "__main__":
    main()
