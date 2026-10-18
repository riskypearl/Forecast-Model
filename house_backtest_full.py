"""
Full House backtest, with polls: run the whole House model on 2016-2022 as of
the day before each election.

  - National environment from generic-ballot polls (not the actual result)
  - Fundamentals: district lean + environment + incumbency + candidate quality
  - District polls (FiveThirtyEight raw_polls.csv): undecided allocation,
    house effects, quality weighting, blended exactly as house_forecast.py does
  - Win probabilities from the same uncertainty model

Compares fundamentals only, polls only and the full model, checks calibration,
and tests the poll weight (tuned on 2016-18, checked on 2020-22).

Run it with:  python house_backtest_full.py
"""

import math
from collections import defaultdict
from datetime import date, timedelta

import backtest_full as bf
import forecast as fc
import house_backtest as hb
import house_forecast as hf

CYCLES = [2016, 2018, 2020, 2022]
SIMS = 2000


def district_polls(polls, cycle, results):
    """538 district polls matched to the MIT race by both candidates' surnames."""
    out = []
    for p in polls:
        if p["type_simple"] != "House-G" or int(p["cycle"]) != cycle:
            continue
        try:
            district = hb.code(p["location"])
        except ValueError:
            continue
        race = results.get((cycle, district))
        if not race:
            continue
        _, dem, rep = race
        pct = {hf.surname(p["cand1_name"]): float(p["cand1_pct"]), hf.surname(p["cand2_name"]): float(p["cand2_pct"])}
        if dem not in pct or rep not in pct:
            continue
        out.append({
            "state": district, "pollster": p["pollster"], "end_date": p["polldate"],
            "dem_pct": pct[dem], "rep_pct": pct[rep], "undecided": max(0.0, 100 - pct[dem] - pct[rep]),
            "sample_size": p["samplesize"], "population": "lv",
            "partisan": p["partisan"] if p["partisan"] in ("DEM", "REP") else "",
        })
    return out


def run_cycle(cycle, polls_538, weights):
    maps, results, winners = hb.DATA
    _, pres_national = hb.bt.presidential_margins()
    election_day = date.fromisoformat(next(p["electiondate"] for p in polls_538
                                           if int(p["cycle"]) == cycle and p["type_simple"] == "House-G"))
    as_of = election_day - timedelta(days=1)
    environment = fc.generic_ballot_average(bf.generic_ballot_rows(polls_538, cycle), weights, as_of)

    def lean(year, district):
        pres = maps[year][district]
        ys = sorted((py for py in pres if py < year), reverse=True)[:3]
        return sum(w * (pres[y] - pres_national[y]) for w, y in zip(hb.LEAN_WEIGHTS, ys)) / sum(hb.LEAN_WEIGHTS[:len(ys)]) if ys else None

    def incumbency(year, district, dem, rep):
        prev = winners.get((year - 2, district))
        return hf.HOUSE_INCUMBENCY_BONUS if prev == dem else -hf.HOUSE_INCUMBENCY_BONUS if prev == rep else 0.0

    def candidate(year, district, dem, rep):
        for prior_year in (year - 2, year - 4):
            prior = results.get((prior_year, district))
            if not prior or district not in maps.get(prior_year, {}) or abs(prior[0]) > hb.MAX_PRIOR_MARGIN \
                    or not ({dem, rep} & {prior[1], prior[2]}):
                continue
            l = lean(prior_year, district)
            if l is None:
                return 0.0
            base = l + hb.bt.NATIONAL_ENVIRONMENT[prior_year] + incumbency(prior_year, district, prior[1], prior[2])
            return hb.CANDIDATE_SHRINK * (prior[0] - base)
        return 0.0

    races = []
    for (year, district), (margin, dem, rep) in results.items():
        if year != cycle or district not in maps.get(year, {}):
            continue
        l = lean(year, district)
        if l is None:
            continue
        races.append({"district": district, "dem": dem, "rep": rep, "actual": margin, "lean": l,
                      "fundamentals": l + environment + incumbency(year, district, dem, rep)
                      + candidate(year, district, dem, rep)})

    polls = district_polls(polls_538, cycle, results)
    polls = fc.allocate_undecided(polls, {r["district"]: r["lean"] + environment for r in races})
    raw = defaultdict(list)
    for p in polls:
        raw[p["state"]].append(p)
    polls = fc.debias(polls, fc.house_effects(polls))
    by_district = defaultdict(list)
    for p in polls:
        by_district[p["state"]].append(p)

    for r in races:
        avg, n = fc.polling_average(by_district.get(r["district"], []), weights, as_of=as_of)
        r["polls"], _ = fc.polling_average(raw.get(r["district"], []), weights, as_of=as_of)
        r["n"] = n
        r["avg"] = avg
    return environment, races


def blend(races, max_weight=None, k=4):
    max_weight = fc.MAX_POLL_WEIGHT if max_weight is None else max_weight
    for r in races:
        w = max_weight * r["n"] / (r["n"] + k)
        r["model"] = r["fundamentals"] if r["avg"] is None else (1 - w) * r["fundamentals"] + w * r["avg"]
        r["w"] = w
    return races


def accuracy(label, pairs):
    miss = sum(abs(a - p) for a, p in pairs) / len(pairs)
    right = sum((a > 0) == (p > 0) for a, p in pairs)
    print(f"  {label:<20}{miss:>8.2f}{right:>8}/{len(pairs)}")


def main():
    polls_538 = bf.load_538()
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")
    cycles = {}
    print("Full House backtest (forecast the day before each election)\n")
    print(f"{'Cycle':<7}{'Generic ballot (polls)':>24}{'Actual House vote':>19}{'races':>7}{'with polls':>12}")
    for c in CYCLES:
        env, races = run_cycle(c, polls_538, weights)
        cycles[c] = blend(races)
        print(f"{c:<7}{fc.fmt_margin(env):>24}{fc.fmt_margin(hb.bt.NATIONAL_ENVIRONMENT[c]):>19}"
              f"{len(races):>7}{sum(r['avg'] is not None for r in races):>12}")

    everything = [r for c in CYCLES for r in cycles[c]]
    polled = [r for r in everything if r["polls"] is not None]
    print(f"\nAll {len(everything)} contested races   avg miss  winners")
    accuracy("Fundamentals only", [(r["actual"], r["fundamentals"]) for r in everything])
    accuracy("Full model", [(r["actual"], r["model"]) for r in everything])
    print(f"\n{len(polled)} races with polls      avg miss  winners")
    accuracy("Fundamentals only", [(r["actual"], r["fundamentals"]) for r in polled])
    accuracy("Polls only", [(r["actual"], r["polls"]) for r in polled])
    accuracy("Full model", [(r["actual"], r["model"]) for r in polled])

    # Calibration
    nat_sd = fc.national_error_sd(days_left=1)
    for r in everything:
        sd = fc.state_error_sd(r["w"], days_left=1)
        r["prob"] = sum(r["model"] + fc.fat_tailed_error(nat_sd) + fc.fat_tailed_error(sd) > 0
                        for _ in range(SIMS)) / SIMS
    print("\nCalibration")
    print(f"  {'Favourite given':<18}{'races':>6}{'expected wins':>15}{'actual wins':>13}")
    for lo, hi in ((0.5, 0.65), (0.65, 0.8), (0.8, 0.95), (0.95, 1.01)):
        b = [r for r in everything if lo <= max(r["prob"], 1 - r["prob"]) < hi]
        if b:
            exp = sum(max(r["prob"], 1 - r["prob"]) for r in b)
            act = sum((r["prob"] >= 0.5) == (r["actual"] > 0) for r in b)
            print(f"  {f'{lo:.0%}-{min(hi, 1):.0%}':<18}{len(b):>6}{exp:>15.1f}{act:>13}")
    brier = sum((r["prob"] - (r["actual"] > 0)) ** 2 for r in everything) / len(everything)
    print(f"\nBrier score: {brier:.3f}")

    print("\nPoll weight (races with polls; tune 2016-18, check 2020-22)")
    print(f"  {'setting':<26}{'tune':>10}{'check':>10}")
    for maxw, k in ((0.85, 4), (0.85, 2), (0.95, 1), (0.95, 0.5)):
        def miss(cs):
            rows = [r for c in cs for r in blend(cycles[c], maxw, k) if r["polls"] is not None]
            return sum(abs(r["actual"] - r["model"]) for r in rows) / len(rows)
        label = f"max {maxw}, n/(n+{k})" + (" (current)" if (maxw, k) == (fc.MAX_POLL_WEIGHT, 4) else "")
        print(f"  {label:<26}{miss([2016, 2018]):>10.2f}{miss([2020, 2022]):>10.2f}")


if __name__ == "__main__":
    main()
