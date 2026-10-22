"""
How fast should old polls stop counting when deciding how much to trust the
polls over the fundamentals?

The polling average uses a 14-day half-life (POLL_HALF_LIFE_DAYS). Until now
the same half-life also set the effective poll count that decides the blend,
so a race with no new polls for a few weeks slid back to its fundamentals
even though its old polls were still the best evidence (Kansas, October 2026).
POLL_COUNT_HALF_LIFE_DAYS separates the two.

The day-before backtest can't see this - nearly every race has fresh polls
the day before an election - so each setting is scored with forecasts made
1, 7, 14, 21 and 28 days out. Tuned on 2012-2018, checked on 2020-2022.

538's raw polls only go back about 60 days before each election, so very
long half-lives are tested against a shortened poll history.

Run it with:  python backtest_poll_recency.py
"""

import backtest as bt
import backtest_full as bf
import forecast as fc

TUNE = [2012, 2014, 2016, 2018]
CHECK = [2020, 2022]
DAYS_OUT = [1, 7, 14, 21, 28]
HALF_LIVES = [14, 21, 30, 45, 60, 10 ** 6]


def score(results, cycles):
    sub = [r for r in results if r["cycle"] in cycles]
    return sum(abs(r["actual"] - r["model"]) for r in sub) / len(sub)


def main():
    bf.SIMS_PER_RACE = 50   # only margins matter here
    polls = bf.load_538()
    races = bt.senate_races()
    pres, national = bt.presidential_margins()
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")
    current = fc.POLL_COUNT_HALF_LIFE_DAYS

    table = {}
    for days in DAYS_OUT:
        bf.DAYS_BEFORE = days
        for hl in HALF_LIVES:
            fc.POLL_COUNT_HALF_LIFE_DAYS = hl
            results = []
            for cycle in TUNE + CHECK:
                results += bf.run_cycle(cycle, polls, races, pres, national, weights)[1]
            table[(days, hl)] = (score(results, TUNE), score(results, CHECK))
    fc.POLL_COUNT_HALF_LIFE_DAYS = current
    bf.DAYS_BEFORE = 1

    for label, i in (("tune 2012-18", 0), ("check 2020-22", 1)):
        print(f"\nAverage miss (points), {label}, by days before the election")
        print(f"  {'count half-life':<18}" + "".join(f"{d:>7}" for d in DAYS_OUT) + f"{'mean':>8}")
        for hl in HALF_LIVES:
            row = [table[(d, hl)][i] for d in DAYS_OUT]
            name = "no decay" if hl >= 10 ** 6 else f"{hl} days"
            if hl == current:
                name += " (current)"
            print(f"  {name:<18}" + "".join(f"{x:>7.2f}" for x in row) + f"{sum(row) / len(row):>8.2f}")


if __name__ == "__main__":
    main()
