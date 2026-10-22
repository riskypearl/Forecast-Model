"""
Full-model backtest: run the real forecast on past Senate elections, as of
the day before each election, and see how it would have done.

For each cycle 2012-2022 it uses:
  - generic-ballot polls  -> national environment (same method as forecast.py)
  - Senate polls          -> undecided allocation, house effects, quality weighting
  - fundamentals          -> lean + environment + incumbency + candidate quality
  - blend + uncertainty   -> margin and win probability

and compares three predictions with what actually happened: fundamentals
only, polls only, and the blended model.

Not included (no historical data): the demographic adjustment and
appointed-incumbent rule. Pollster ratings are matched by name, so pollsters
FiveThirtyEight names differently get the default weight.

Data: FiveThirtyEight raw_polls.csv (CC BY 4.0) and MIT Election Lab (CC0).
Run it with:  python backtest_full.py
"""

import csv
from collections import defaultdict
from datetime import date, timedelta

import backtest as bt
import forecast as fc

CYCLES = [2012, 2014, 2016, 2018, 2020, 2022]
SIMS_PER_RACE = 4000

# Optional correction added to each race's polling average, keyed (cycle, state).
# Empty = off. backtest_state_bias.py fills it to test state-level poll bias.
STATE_POLL_BIAS = {}

# How many days before each election the forecast is made. Polls released
# after that day are left out.
DAYS_BEFORE = 1

# FiveThirtyEight spells some pollsters differently from our ratings file.
POLLSTER_ALIASES = {
    "The New York Times/Siena College": "The New York Times/Siena University",
    "Marist College": "Marist University",
    "Scott Rasmussen (Rasmussen Reports)": "Rasmussen Reports",
    "Beacon Research/Shaw & Co. Research": "Beacon Research/Shaw & Company Research",
    "SSRS": "CNN/SSRS",
    "Harris Insights & Analytics": "HarrisX/Harris Poll",
    "Marquette University Law School": "Marquette Law School",
}


def load_538():
    with open("data/538/raw_polls.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if int(r["cycle"]) in CYCLES]
    for r in rows:
        r["pollster"] = POLLSTER_ALIASES.get(r["pollster"], r["pollster"])
    return rows


def generic_ballot_rows(polls, cycle):
    return [{
        "pollster": p["pollster"], "end_date": p["polldate"],
        "dem": p["cand1_pct"], "rep": p["cand2_pct"], "n": p["samplesize"],
        "lean": {"DEM": "D", "REP": "R"}.get(p["partisan"], ""),
    } for p in polls if p["type_simple"] == "House-G-US" and int(p["cycle"]) == cycle
        and p["cand1_party"] == "DEM" and p["cand2_party"] == "REP"]


def senate_polls_for(race, polls):
    """538 polls of this exact matchup (matched on state and both candidates' names)."""
    out = []
    for p in polls:
        if p["type_simple"] != "Sen-G" or p["location"] != race["state"]:
            continue
        names = {bt.name_key(p["cand1_name"].upper()): p["cand1_party"],
                 bt.name_key(p["cand2_name"].upper()): p["cand2_party"]}
        if race["dem"] not in names or race["rep"] not in names:
            continue
        pct = {p["cand1_name"]: float(p["cand1_pct"]), p["cand2_name"]: float(p["cand2_pct"])}
        by_key = {bt.name_key(n.upper()): v for n, v in pct.items()}
        dem, rep = by_key[race["dem"]], by_key[race["rep"]]
        out.append({
            "state": race["state"], "pollster": p["pollster"], "end_date": p["polldate"],
            "dem_pct": dem, "rep_pct": rep, "undecided": max(0.0, 100 - dem - rep),
            "sample_size": p["samplesize"], "population": "lv",
            "partisan": p["partisan"] if p["partisan"] in ("DEM", "REP") else "",
        })
    return out


def win_probability(margin, sd, national_sd):
    wins = sum(margin + fc.fat_tailed_error(national_sd) + fc.fat_tailed_error(sd) > 0
               for _ in range(SIMS_PER_RACE))
    return wins / SIMS_PER_RACE


def run_cycle(cycle, polls_538, races, pres, national, weights):
    election_day = date.fromisoformat(
        next(p["electiondate"] for p in polls_538 if int(p["cycle"]) == cycle and p["type_simple"] == "Sen-G"))
    as_of = election_day - timedelta(days=DAYS_BEFORE)
    environment = fc.generic_ballot_average(generic_ballot_rows(polls_538, cycle), weights, as_of)

    cycle_races = [r for r in races if r["year"] == cycle]
    leans = {id(r): bt.lean(r["state"], cycle, pres, national) for r in cycle_races}

    # Pool every Senate poll of the cycle, so house effects are estimated across races
    all_polls = []
    for r in cycle_races:
        all_polls += [p for p in senate_polls_for(r, polls_538)
                      if date.fromisoformat(p["end_date"]) <= as_of]
    baselines = {r["state"]: leans[id(r)] + environment for r in cycle_races}
    all_polls = fc.allocate_undecided(all_polls, baselines)
    raw_by_race = defaultdict(list)
    for p in all_polls:
        raw_by_race[p["state"]].append(p)
    polls = fc.debias(all_polls, fc.house_effects(all_polls))

    results = []
    for r in cycle_races:
        records = [bt.candidate_record(r[side], r["state"], cycle, races, pres, national)
                   for side in ("dem", "rep")]
        cand = bt.CANDIDATE_SHRINK * sum(x for x in records if x is not None)
        fund = leans[id(r)] + environment + bt.incumbency(r, races) + cand

        state_polls = [p for p in polls if p["state"] == r["state"]]
        poll_avg, n = fc.polling_average(state_polls, weights, as_of=as_of)
        if poll_avg is not None:
            poll_avg += STATE_POLL_BIAS.get((cycle, r["state"]), 0.0)
        raw_avg, _ = fc.polling_average(raw_by_race[r["state"]], weights, as_of=as_of)
        w = fc.poll_weight(n)
        margin = fund if poll_avg is None else (1 - w) * fund + w * poll_avg
        sd = fc.state_error_sd(w, days_left=DAYS_BEFORE)
        results.append({
            "cycle": cycle, "state": r["state"], "dem": r["dem"], "rep": r["rep"],
            "actual": r["margin"], "fundamentals": fund, "polls": raw_avg, "model": margin,
            "dem_prob": win_probability(margin, sd, fc.national_error_sd(days_left=DAYS_BEFORE)),
        })
    return environment, results


def accuracy(label, preds):
    errors = [abs(a - p) for a, p in preds]
    right = sum((a > 0) == (p > 0) for a, p in preds)
    print(f"  {label:<20}{sum(errors) / len(errors):>8.1f}{right:>8}/{len(preds)}")


def main():
    polls_538 = load_538()
    races = bt.senate_races()
    pres, national = bt.presidential_margins()
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")

    everything = []
    print("Full-model Senate backtest (forecast made the day before each election)\n")
    print(f"{'Cycle':<7}{'Generic ballot (polls)':>24}{'Actual House vote':>19}")
    for cycle in CYCLES:
        env, results = run_cycle(cycle, polls_538, races, pres, national, weights)
        print(f"{cycle:<7}{fc.fmt_margin(env):>24}{fc.fmt_margin(bt.NATIONAL_ENVIRONMENT[cycle]):>19}")
        everything += results

    polled = [r for r in everything if r["polls"] is not None]
    print(f"\nAll {len(everything)} races          avg miss  winners right")
    accuracy("Fundamentals only", [(r["actual"], r["fundamentals"]) for r in everything])
    accuracy("Full model", [(r["actual"], r["model"]) for r in everything])
    print(f"\n{len(polled)} races with polls        avg miss  winners right")
    accuracy("Fundamentals only", [(r["actual"], r["fundamentals"]) for r in polled])
    accuracy("Polls only", [(r["actual"], r["polls"]) for r in polled])
    accuracy("Full model", [(r["actual"], r["model"]) for r in polled])

    # Calibration: when the model gave the favourite X%, how often did they win?
    print("\nCalibration (is the model's confidence honest?)")
    print(f"  {'Favourite given':<18}{'races':>6}{'expected wins':>15}{'actual wins':>13}")
    for lo, hi in ((0.5, 0.65), (0.65, 0.8), (0.8, 0.95), (0.95, 1.01)):
        bucket = [r for r in everything if lo <= max(r["dem_prob"], 1 - r["dem_prob"]) < hi]
        if not bucket:
            continue
        expected = sum(max(r["dem_prob"], 1 - r["dem_prob"]) for r in bucket)
        actual = sum((r["dem_prob"] >= 0.5) == (r["actual"] > 0) for r in bucket)
        print(f"  {f'{lo:.0%}-{min(hi, 1):.0%}':<18}{len(bucket):>6}{expected:>15.1f}{actual:>13}")
    brier = sum((r["dem_prob"] - (r["actual"] > 0)) ** 2 for r in everything) / len(everything)
    print(f"\nBrier score: {brier:.3f}  (0 = perfect, 0.25 = coin-flipping every race)")

    with open("backtest_full_results.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["cycle", "state", "dem", "rep", "actual", "fundamentals", "polls", "model", "dem_prob"])
        for r in everything:
            writer.writerow([r["cycle"], r["state"], r["dem"], r["rep"], round(r["actual"], 1),
                             round(r["fundamentals"], 1), "" if r["polls"] is None else round(r["polls"], 1),
                             round(r["model"], 1), round(r["dem_prob"], 3)])


if __name__ == "__main__":
    main()
