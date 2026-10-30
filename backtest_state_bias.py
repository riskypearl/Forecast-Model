"""
Do some states' polls miss the same way every cycle? Test a state-level
poll-bias correction on the full-model backtest.

For each state and past cycle, the "poll miss" is the actual result minus the
average of the final three weeks of polls (Senate, President and Governor,
Democrat v Republican only). Before forecasting a cycle, each state's
correction is the average of its misses in EARLIER cycles only, shrunk
towards zero when there are few of them, and added to its polling average.

Variants:
  total     - the state's whole miss, including the part every state shared
  relative  - the miss minus that cycle's average miss across all states
              (the shared part is the national error the simulation already has)
  same type - only cycles of the same kind (midterm or presidential)

Tuned on 2012-2018, checked on 2020-2022, like backtest_choices.py. A
correction is only worth adopting if it helps on the check years by 0.1+.

Run it with:  python backtest_state_bias.py
"""

import csv
from collections import defaultdict

import backtest as bt
import backtest_full as bf
import forecast as fc

TUNE = [2012, 2014, 2016, 2018]
CHECK = [2020, 2022]
FINAL_DAYS = 21          # polls this close to election day count as "final"
RACE_TYPES = ("Sen-G", "Pres-G", "Gov-G")


def state_misses():
    """{(cycle, state): actual minus final-poll margin (Dem minus Rep)}, even years only."""
    by_race = defaultdict(list)
    with open("data/538/raw_polls.csv", encoding="utf-8") as f:
        for p in csv.DictReader(f):
            cycle = int(p["cycle"])
            if (p["type_simple"] not in RACE_TYPES or cycle % 2 or p["location"] == "US"
                    or int(p["time_to_election"]) > FINAL_DAYS):
                continue
            parties = (p["cand1_party"], p["cand2_party"])
            if parties == ("DEM", "REP"):
                sign = 1
            elif parties == ("REP", "DEM"):
                sign = -1
            else:
                continue
            miss = sign * (float(p["margin_actual"]) - float(p["margin_poll"]))
            by_race[(cycle, p["location"], p["race"])].append(miss)

    by_state = defaultdict(list)
    for (cycle, state, _), misses in by_race.items():
        by_state[(cycle, state)].append(sum(misses) / len(misses))
    return {k: sum(v) / len(v) for k, v in by_state.items()}


def relative(misses):
    """Remove each cycle's shared (national) miss."""
    by_cycle = defaultdict(list)
    for (cycle, _), m in misses.items():
        by_cycle[cycle].append(m)
    shared = {c: sum(v) / len(v) for c, v in by_cycle.items()}
    return {(c, s): m - shared[c] for (c, s), m in misses.items()}


def is_midterm(cycle):
    return cycle % 4 == 2


def corrections(misses, cycles, shrink, same_type=False, scale=1.0):
    """{(cycle, state): correction} from earlier cycles' misses only."""
    out = {}
    states = {s for _, s in misses}
    for cycle in cycles:
        for state in states:
            past = [m for (c, s), m in misses.items() if s == state and c < cycle
                    and (not same_type or is_midterm(c) == is_midterm(cycle))]
            if past:
                out[(cycle, state)] = scale * sum(past) / len(past) * len(past) / (len(past) + shrink)
    return out


def evaluate(results, cycles):
    sub = [r for r in results if r["cycle"] in cycles]
    miss = sum(abs(r["actual"] - r["model"]) for r in sub) / len(sub)
    right = sum((r["actual"] > 0) == (r["model"] > 0) for r in sub)
    return f"{miss:5.2f} {right:>3}/{len(sub):<3}"


def run_all(polls, races, pres, national, weights):
    results = []
    for cycle in TUNE + CHECK:
        results += bf.run_cycle(cycle, polls, races, pres, national, weights)[1]
    return results


def main():
    bf.SIMS_PER_RACE = 50   # only margins matter here
    polls = bf.load_538()
    races = bt.senate_races()
    pres, national = bt.presidential_margins()
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")

    total = state_misses()
    rel = relative(total)
    variants = [("none (current)", None)]
    for name, misses, same in (("total", total, False), ("relative", rel, False),
                               ("total, same type", total, True), ("relative, same type", rel, True)):
        for shrink in (1, 3, 6):
            variants.append((f"{name}, shrink {shrink}", (misses, shrink, same)))

    print("State-level poll-bias correction, full-model backtest")
    print(f"  {'variant':<32}{'tune 2012-18':>16}{'check 2020-22':>17}")
    for label, spec in variants:
        bf.STATE_POLL_BIAS = {} if spec is None else corrections(spec[0], TUNE + CHECK, spec[1], spec[2])
        results = run_all(polls, races, pres, national, weights)
        print(f"  {label:<32}{evaluate(results, TUNE):>16}{evaluate(results, CHECK):>17}")
    bf.STATE_POLL_BIAS = {}

    print("\nTexas: poll misses by cycle (actual minus final polls, + = Dem beat polls)")
    print(f"  {'cycle':<7}{'total':>8}{'relative':>10}")
    for cycle in sorted(c for c, s in total if s == "TX"):
        print(f"  {cycle:<7}{total[(cycle, 'TX')]:>+8.1f}{rel[(cycle, 'TX')]:>+10.1f}")
    print("\nTexas correction for 2026 (cycles to 2022; 538's polls end there)")
    for name, misses, same in (("total", total, False), ("relative", rel, False),
                               ("total, same type", total, True), ("relative, same type", rel, True)):
        c = corrections(misses, [2026], 3, same).get((2026, "TX"), 0.0)
        print(f"  {name + ', shrink 3':<32}{c:>+6.1f}")


if __name__ == "__main__":
    main()
