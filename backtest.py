"""
Backtest: does the candidate-quality adjustment actually work?

For every Senate race in 2018, 2020, 2022 and 2024 we predict the margin from
fundamentals using only information available before that election, twice:

  A. lean + national environment + incumbency
  B. A + candidate adjustment (from each candidate's earlier Senate races)

then compare both with the real result. If B is closer, candidate quality
genuinely predicts results. No polls are used here.

Data: MIT Election Data + Science Lab, US Senate and US President 1976-2024
(CC0), in data/mit/.

Run it with:  python backtest.py
"""

import csv
import math
from collections import defaultdict

TEST_YEARS = [2018, 2020, 2022, 2024]

# Same settings as forecast.py
LEAN_WEIGHTS = [0.75, 0.175, 0.075]   # most recent presidential election first
INCUMBENCY_BONUS = 5.0
CANDIDATE_SHRINK = 2 / 3

# Only learn candidate quality from REAL contests. A 60-point blowout against
# an unknown opponent measures the opponent's weakness, not the candidate's
# strength. Set these to 999 to see what happens without the rule (the
# adjustment then makes predictions worse - best shrink drops to ~0.24).
MAX_PRIOR_RACE_AGE = 12      # years
MAX_PRIOR_RACE_MARGIN = 15   # points

# National environment = national House popular-vote margin (Dem minus Rep).
# Using the real result isolates the question: GIVEN the national mood, does
# knowing the candidates help? Figures are the commonly reported House
# popular-vote margins - check them against the Clerk of the House if you cite them.
NATIONAL_ENVIRONMENT = {
    2002: -4.6, 2004: -2.6, 2006: 8.0, 2008: 10.6, 2010: -6.8, 2012: 1.2,
    2014: -5.7, 2016: -1.1, 2018: 8.6, 2020: 3.1, 2022: -2.8, 2024: -2.7,
}
EARLIEST_PRIOR_RACE = 2002


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

def presidential_margins():
    """({(year, state): margin}, {year: national margin}), margins Dem minus Rep in points."""
    votes = defaultdict(lambda: defaultdict(float))
    totals = {}
    with open("data/mit/president.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (int(r["year"]), r["state_po"])
            votes[key][r["party_simplified"]] += float(r["candidatevotes"])
            totals[key] = float(r["totalvotes"])
    state, national = {}, defaultdict(lambda: [0.0, 0.0, 0.0])
    for (year, st), v in votes.items():
        state[(year, st)] = 100 * (v["DEMOCRAT"] - v["REPUBLICAN"]) / totals[(year, st)]
        n = national[year]
        n[0] += v["DEMOCRAT"]; n[1] += v["REPUBLICAN"]; n[2] += totals[(year, st)]
    return state, {y: 100 * (d - r) / t for y, (d, r, t) in national.items()}


def name_key(name):
    """'SHERROD C. BROWN JR.' -> 'SHERROD BROWN' so the same person matches across years."""
    parts = [p for p in name.replace(",", " ").replace(".", " ").split()
             if p not in ("JR", "SR", "II", "III", "IV") and len(p) > 1]
    return f"{parts[0]} {parts[-1]}" if parts else name


def senate_races():
    """
    One entry per general election race: year, state, special flag, the main
    Democratic-side and Republican candidates, and the actual margin. Where no
    Democrat ran (Sanders, Osborn), the strongest non-Republican is the Dem side.
    """
    grouped = defaultdict(list)
    with open("data/mit/senate.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["stage"].lower() != "gen" or r["candidate"] in ("", "OTHER") or r["writein"] == "True":
                continue
            grouped[(int(r["year"]), r["state_po"], r["special"] == "True")].append(r)

    races = []
    for (year, st, special), rows in grouped.items():
        if year < EARLIEST_PRIOR_RACE:
            continue
        rows.sort(key=lambda r: -float(r["candidatevotes"]))
        reps = [r for r in rows if r["party_simplified"] == "REPUBLICAN"]
        dems = [r for r in rows if r["party_simplified"] == "DEMOCRAT"] or \
               [r for r in rows if r["party_simplified"] != "REPUBLICAN"]
        if not reps or not dems:
            continue
        total = float(rows[0]["totalvotes"])
        d, rp = dems[0], reps[0]
        races.append({
            "year": year, "state": st, "special": special,
            "dem": name_key(d["candidate"]), "rep": name_key(rp["candidate"]),
            "margin": 100 * (float(d["candidatevotes"]) - float(rp["candidatevotes"])) / total,
        })
    return races


# ---------------------------------------------------------------------------
# The model pieces, using only information from before each election
# ---------------------------------------------------------------------------

def lean(state, year, pres, national):
    """Weighted lean from the three presidential elections BEFORE this year."""
    years = [y for y in range(year - 1, 1975, -1) if (y, state) in pres][:3]
    total = sum(w * (pres[(y, state)] - national[y]) for w, y in zip(LEAN_WEIGHTS, years))
    return total / sum(LEAN_WEIGHTS[:len(years)])


def incumbency(race, races):
    """+bonus if the Dem won this state's Senate seat in the last 6 years, -bonus for the Rep."""
    for prior in races:
        if prior["state"] == race["state"] and race["year"] - 6 <= prior["year"] < race["year"]:
            winner = prior["dem"] if prior["margin"] > 0 else prior["rep"]
            if winner == race["dem"]:
                return INCUMBENCY_BONUS
            if winner == race["rep"]:
                return -INCUMBENCY_BONUS
    return 0.0


def baseline(race, races, pres, national):
    return lean(race["state"], race["year"], pres, national) + \
        NATIONAL_ENVIRONMENT[race["year"]] + incumbency(race, races)


def candidate_record(name, state, year, races, pres, national):
    """
    How far this candidate ran ahead of expectations (Dem-minus-Rep points) in
    their most recent earlier Senate race in this state, or None if they have
    no record. Incumbency is already in the baseline, so it isn't double counted.
    """
    earlier = [r for r in races if r["state"] == state and r["year"] < year
               and name in (r["dem"], r["rep"])
               and year - r["year"] <= MAX_PRIOR_RACE_AGE
               and abs(r["margin"]) <= MAX_PRIOR_RACE_MARGIN]
    if not earlier:
        return None
    prior = max(earlier, key=lambda r: r["year"])
    return prior["margin"] - baseline(prior, races, pres, national)


# ---------------------------------------------------------------------------
# Run the test
# ---------------------------------------------------------------------------

def stats(errors):
    n = len(errors)
    return sum(abs(e) for e in errors) / n, math.sqrt(sum(e * e for e in errors) / n)


def main():
    pres, national = presidential_margins()
    races = senate_races()

    rows = []
    for race in races:
        if race["year"] not in TEST_YEARS:
            continue
        base = baseline(race, races, pres, national)
        records = [candidate_record(race[side], race["state"], race["year"], races, pres, national)
                   for side in ("dem", "rep")]
        raw_adj = sum(r for r in records if r is not None)
        rows.append({**race, "base": base, "raw_adj": raw_adj,
                     "has_record": any(r is not None for r in records)})

    def report(label, subset):
        a = [r["margin"] - r["base"] for r in subset]
        b = [r["margin"] - (r["base"] + CANDIDATE_SHRINK * r["raw_adj"]) for r in subset]
        win_a = sum((r["base"] > 0) == (r["margin"] > 0) for r in subset)
        win_b = sum((r["base"] + CANDIDATE_SHRINK * r["raw_adj"] > 0) == (r["margin"] > 0) for r in subset)
        (mae_a, rmse_a), (mae_b, rmse_b) = stats(a), stats(b)
        print(f"\n{label} ({len(subset)} races)")
        print(f"  {'':<26}{'avg error':>10}{'RMSE':>8}{'winners right':>15}")
        print(f"  {'A: without candidates':<26}{mae_a:>10.1f}{rmse_a:>8.1f}{win_a:>9}/{len(subset)}")
        print(f"  {'B: with candidates':<26}{mae_b:>10.1f}{rmse_b:>8.1f}{win_b:>9}/{len(subset)}")

    print("Senate backtest, 2018-2024 (fundamentals only, no polls)")
    report("All races", rows)
    with_record = [r for r in rows if r["has_record"]]
    report("Races where a candidate had an earlier Senate race", with_record)

    # What shrink factor fits best? Least-squares slope of (actual - baseline)
    # on the raw candidate record. forecast.py uses 2/3.
    num = sum(r["raw_adj"] * (r["margin"] - r["base"]) for r in with_record)
    den = sum(r["raw_adj"] ** 2 for r in with_record)
    print(f"\nBest-fitting shrink factor: {num / den:.2f}  (model uses {CANDIDATE_SHRINK:.2f})")

    for year in TEST_YEARS:
        report(str(year), [r for r in rows if r["year"] == year])

    with open("backtest_results.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "state", "special", "dem", "rep", "actual", "baseline",
                         "candidate_adj", "prediction_with_candidates"])
        for r in sorted(rows, key=lambda r: (r["year"], r["state"])):
            adj = CANDIDATE_SHRINK * r["raw_adj"]
            writer.writerow([r["year"], r["state"], r["special"], r["dem"], r["rep"],
                             round(r["margin"], 1), round(r["base"], 1), round(adj, 1),
                             round(r["base"] + adj, 1)])


if __name__ == "__main__":
    main()
