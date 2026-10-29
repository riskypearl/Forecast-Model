"""
Backtest for the governor model (governor_forecast.py).

Governor races are less tied to presidential partisanship than Senate races
(Phil Scott, Laura Kelly, Andy Beshear), so the Senate settings aren't assumed:

  1. Fundamentals, no polls: margin = LEAN_SCALE x presidential lean
     + ENV_SCALE x national environment (actual House vote) + incumbency
     + governor record + Senate record. Every combination is fitted on
     2010-16 and checked on 2018-24.
  2. With polls (FiveThirtyEight raw_polls, generic-ballot environment), as
     of 1 and 21 days out: how much the polls should count. 2010-16 / 2018-22.
  3. Calibration: how big the misses really are next to the Senate model's
     uncertainty, which sets GOV_ERROR_SCALE.

Data: governor results 2002-2024 (538 election-results, CC BY 4.0), polls
(538 raw_polls, CC BY 4.0), MIT Election Lab presidential and Senate results.

Run it with:  python governor_backtest.py
"""

import csv
from collections import defaultdict
from datetime import date, timedelta
from itertools import product
import math
import statistics

import backtest as bt
import backtest_full as bf
import backtest_governor as bg
import forecast as fc

TUNE = [2010, 2012, 2014, 2016]
CHECK = [2018, 2020, 2022, 2024]


def build(gov_races, senate, pres, national, inc_bonus):
    """One row per even-year governor race with every fundamentals ingredient."""
    rows = []
    for g in gov_races:
        if g["year"] not in TUNE + CHECK:
            continue
        gov = [bg.governor_record(g[s], s, g["state"], g["year"], gov_races, pres, national,
                                  inc_bonus, 999, "lean") for s in ("dem", "rep")]
        sen = [bt.candidate_record(g[s], g["state"], g["year"], senate, pres, national) for s in ("dem", "rep")]
        rows.append({**g, "lean": bt.presidential_lean(g["state"], g["year"], pres, national),
                     "env": bt.NATIONAL_ENVIRONMENT[g["year"]],
                     "inc": bg.governor_incumbency(g, gov_races, 1.0),
                     "gov": sum(x for x in gov if x is not None),
                     "sen": sum(x for x in sen if x is not None)})
    return rows


def fundamentals(r, p):
    return (p["lean"] * r["lean"] + p["env"] * r["env"] + p["inc"] * r["inc"]
            + p["gov"] * r["gov"] + p["sen"] * r["sen"])


def miss(rows, f):
    return sum(abs(r["margin"] - f(r)) for r in rows) / len(rows)


def right(rows, f):
    return sum((f(r) > 0) == (r["margin"] > 0) for r in rows)


# --- with polls ----------------------------------------------------------------------

def governor_polls(polls_538, race):
    out = []
    for p in polls_538:
        if p["type_simple"] != "Gov-G" or p["location"] != race["state"] or int(p["cycle"]) != race["year"]:
            continue
        names = {bt.name_key(p["cand1_name"].upper()): float(p["cand1_pct"]),
                 bt.name_key(p["cand2_name"].upper()): float(p["cand2_pct"])}
        names = {bg.ALIASES.get(k, k): v for k, v in names.items()}
        if race["dem"] not in names or race["rep"] not in names:
            continue
        dem, rep = names[race["dem"]], names[race["rep"]]
        out.append({"state": race["state"], "pollster": p["pollster"], "end_date": p["polldate"],
                    "dem_pct": dem, "rep_pct": rep, "undecided": max(0.0, 100 - dem - rep),
                    "sample_size": p["samplesize"], "population": "lv",
                    "partisan": p["partisan"] if p["partisan"] in ("DEM", "REP") else ""})
    return out


def run_polls(rows_by_cycle, polls_538, weights, params, days, cap, k):
    fc.MAX_POLL_WEIGHT, fc.POLL_WEIGHT_K = cap, k
    out = []
    for cycle, rows in rows_by_cycle.items():
        election_day = date.fromisoformat(next(p["electiondate"] for p in polls_538
                                               if int(p["cycle"]) == cycle and p["type_simple"] == "Gov-G"))
        as_of = election_day - timedelta(days=days)
        env = fc.generic_ballot_average(bf.generic_ballot_rows(polls_538, cycle), weights, as_of)
        polls = []
        for r in rows:
            polls += [p for p in governor_polls(polls_538, r) if date.fromisoformat(p["end_date"]) <= as_of]
        base = {r["state"]: params["lean"] * r["lean"] + params["env"] * env for r in rows}
        polls = fc.allocate_undecided(polls, base)
        polls = fc.debias(polls, fc.house_effects(polls))
        for r in rows:
            fund = fundamentals({**r, "env": env}, params)
            avg, n = fc.polling_average([p for p in polls if p["state"] == r["state"]], weights, as_of=as_of)
            w = fc.poll_weight(n)
            model = fund if avg is None else (1 - w) * fund + w * avg
            out.append({**r, "model": model, "w": w, "polled": avg is not None,
                        "sd": math.sqrt(fc.state_error_sd(w, days_left=days) ** 2
                                        + fc.national_error_sd(days_left=days) ** 2)})
    fc.MAX_POLL_WEIGHT, fc.POLL_WEIGHT_K = 0.85, 4
    return out


def main():
    pres, national = bt.presidential_margins()
    senate = bt.senate_races()
    gov_races = bg.governor_races()

    # 1. fundamentals grid
    best = None
    grid = product([0.5, 0.6, 0.7, 0.8, 0.9, 1.0], [0.5, 0.75, 1.0], [0.0, 2.5, 5.0, 7.5, 10.0],
                   [0.0, 0.15, 0.3, 0.5], [0.0, bt.CANDIDATE_SHRINK])
    cache = {}
    results = []
    for lean, env, inc, gov, sen in grid:
        if inc not in cache:
            cache[inc] = build(gov_races, senate, pres, national, inc)
        rows = cache[inc]
        p = {"lean": lean, "env": env, "inc": inc, "gov": gov, "sen": sen}
        f = lambda r: fundamentals(r, p)
        tune = [r for r in rows if r["year"] in TUNE]
        check = [r for r in rows if r["year"] in CHECK]
        results.append((miss(tune, f), miss(check, f), right(check, f), len(check), p))
    results.sort(key=lambda x: x[0])
    print("  Best combination for each lean scale (fitted on 2010-16):")
    print(f"  {'lean':>5}{'env':>6}{'inc':>6}{'gov rec':>9}{'sen rec':>9}{'tune 10-16':>12}{'check 18-24':>13}{'winners':>9}")
    for lean in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        t, c, w, n, p = next(x for x in results if x[4]["lean"] == lean)
        print(f"  {p['lean']:>5}{p['env']:>6}{p['inc']:>6}{p['gov']:>9.2f}{p['sen']:>9.2f}{t:>12.2f}{c:>13.2f}{w:>5}/{n}")
    print()
    senate_like = next(x for x in results if x[4] == {"lean": 1.0, "env": 1.0, "inc": 5.0, "gov": 0.3, "sen": bt.CANDIDATE_SHRINK})
    print(f"1. Fundamentals only ({len(cache[0.0])} governor races 2010-24)")
    print(f"  {'lean':>5}{'env':>6}{'inc':>6}{'gov rec':>9}{'sen rec':>9}{'tune 10-16':>12}{'check 18-24':>13}{'winners':>9}")
    for t, c, w, n, p in results[:8] + [senate_like]:
        tag = "  <- Senate model's settings" if p is senate_like[4] else ""
        print(f"  {p['lean']:>5}{p['env']:>6}{p['inc']:>6}{p['gov']:>9.2f}{p['sen']:>9.2f}{t:>12.2f}{c:>13.2f}{w:>5}/{n}{tag}")
    best = results[0][4]

    # 2. with polls
    bf.SIMS_PER_RACE = 50
    with open("data/538/raw_polls.csv", encoding="utf-8") as f:
        polls_538 = [r for r in csv.DictReader(f) if 2010 <= int(r["cycle"]) <= 2022]
    for r in polls_538:
        r["pollster"] = bf.POLLSTER_ALIASES.get(r["pollster"], r["pollster"])
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")
    rows = build(gov_races, senate, pres, national, best["inc"])
    by_cycle = defaultdict(list)
    for r in rows:
        if r["year"] <= 2022:
            by_cycle[r["year"]].append(r)
    print(f"\n2. With polls, fundamentals {best} - average miss")
    print(f"  {'cap':>5}{'K':>4}{'1 day: tune':>13}{'check':>7}{'21 days: tune':>15}{'check':>7}")
    poll_results = {}
    for cap, k in product([0.75, 0.85, 0.95], [1, 2, 4]):
        cells = []
        for days in (1, 21):
            res = run_polls(by_cycle, polls_538, weights, best, days, cap, k)
            poll_results[(cap, k, days)] = res
            cells += [miss([r for r in res if r["year"] in TUNE], lambda r: r["model"]),
                      miss([r for r in res if r["year"] in CHECK], lambda r: r["model"])]
        print(f"  {cap:>5}{k:>4}{cells[0]:>13.2f}{cells[1]:>7.2f}{cells[2]:>15.2f}{cells[3]:>7.2f}")

    # 3. calibration at the Senate poll-weight setting
    res = poll_results[(0.85, 4, 1)]
    z = [(r["margin"] - r["model"]) / r["sd"] for r in res]
    print(f"\n3. Calibration (Senate poll weight, 1 day out): misses are {statistics.pstdev(z):.2f}x "
          f"the Senate model's uncertainty (1.00 = right size)")


if __name__ == "__main__":
    main()
