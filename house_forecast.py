"""
2026 US House forecast - all 435 districts.

Same approach as the Senate model (forecast.py), reusing its pieces:
  1. Partisan lean of each district (2016/2020/2024 presidential results on
     the 2026 district maps)
  2. Fundamentals = lean + national environment + incumbency
  3. District polls (where they exist): undecided allocation, house effects,
     quality weighting
  4. Blend, then 10,000 simulated elections with national, regional and
     local errors

Not included yet: candidate quality and the demographic adjustment.

District results and rosters: ElectIndex 26_us_forecast_data (kept locally in
data/electindex/, not republished - the repository has no licence).
District polls: NYT via PollResults.org (CC BY 4.0).

Run it with:  python house_forecast.py   (after python fetch_polls.py)
"""

import csv
import math
import os
from collections import defaultdict

import forecast as fc

# Measured from 2024: incumbent Democrats ran 3.8 points ahead of Harris and
# incumbent Republicans 3.7 ahead of Trump, in states whose maps didn't change.
HOUSE_INCUMBENCY_BONUS = 3.7
SEATS = 435
MAJORITY = 218
SAFE_MARGIN = 999.0     # margin used for uncontested / same-party seats

# All 50 states, so every district has a region for the correlated error
REGIONS = {
    "Northeast": ["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA", "DE", "MD"],
    "Midwest": ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "South": ["AL", "AR", "FL", "GA", "KY", "LA", "MS", "NC", "OK", "SC", "TN", "TX", "VA", "WV"],
    "West": ["AK", "AZ", "CA", "CO", "HI", "ID", "MT", "NV", "NM", "OR", "UT", "WA", "WY"],
}
REGION_OF = {s: region for region, states in REGIONS.items() for s in states}


def missing(name):
    return not name or name.lower().startswith("(no")


def load_districts():
    hist = {r["code"]: r for r in fc.load_csv_utf8("data/electindex/historical.csv") if r["level"] == "district"}
    cands = {c["cand_id"]: c for c in fc.load_csv_utf8("data/electindex/candidates.csv")}
    districts = []
    for r in fc.load_csv_utf8("data/electindex/races.csv"):
        if r["race_type"] != "house":
            continue
        h = hist[r["race_code"]]
        dem_name, dem_id = r["dem_name"], r["dem_id"]
        if missing(dem_name) and r["ind_caucus"] == "DEM" and not missing(r["ind_name"]):
            dem_name, dem_id = r["ind_name"], r["ind_id"]       # independent caucusing with Dems
        fixed = None
        if r["same_party"]:
            fixed = "D" if r["same_party"] == "DEM" else "R"
        elif missing(dem_name):
            fixed = "R"
        elif missing(r["rep_name"]):
            fixed = "D"
        incumbency = 0.0
        if cands.get(dem_id, {}).get("incumbent") == "1":
            incumbency = HOUSE_INCUMBENCY_BONUS
        elif cands.get(r["rep_id"], {}).get("incumbent") == "1":
            incumbency = -HOUSE_INCUMBENCY_BONUS
        districts.append({
            "code": r["race_code"], "state": r["state"],
            "dem": dem_name, "rep": r["rep_name"], "holder": r["seat_holder"],
            "fixed": fixed, "incumbency": incumbency,
            "pres": {y: float(h[f"margin_{y}"]) for y in (2024, 2020, 2016)},
        })
    return districts


def district_lean(d):
    total = sum(w * (d["pres"][y] - fc.NATIONAL_MARGIN[y]) for y, w in fc.LEAN_WEIGHTS.items())
    return total / sum(fc.LEAN_WEIGHTS.values())


def main():
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")
    environment = fc.national_environment(weights)
    districts = load_districts()

    for d in districts:
        d["lean"] = district_lean(d)
        d["fundamentals"] = d["lean"] + environment + d["incumbency"]

    # District polls, pooled so house effects are estimated across all districts
    polls = [dict(p, state=p["district"]) for p in fc.load_csv("data/house_polls.csv")]
    baselines = {d["code"]: d["lean"] + environment for d in districts}
    polls = fc.allocate_undecided(polls, baselines)
    polls = fc.debias(polls, fc.house_effects(polls))
    by_district = defaultdict(list)
    for p in polls:
        by_district[p["district"]].append(p)

    for d in districts:
        avg, n = fc.polling_average(by_district.get(d["code"], []), weights)
        w = fc.poll_weight(n)
        d["poll_avg"], d["num_polls"] = avg, n
        d["margin"] = d["fundamentals"] if avg is None else (1 - w) * d["fundamentals"] + w * avg
        if d["fixed"]:
            d["margin"] = SAFE_MARGIN if d["fixed"] == "D" else -SAFE_MARGIN
        d["sd"] = fc.state_error_sd(w)
        d["local_sd"] = math.sqrt(max(d["sd"] ** 2 - fc.REGION_ERROR_SD ** 2, 1.0))
        d["dem_wins"] = 0

    seat_counts = []
    national_sd = fc.national_error_sd()
    for _ in range(fc.SIMULATIONS):
        national = fc.fat_tailed_error(national_sd)
        regional = {r: fc.fat_tailed_error(fc.REGION_ERROR_SD) for r in REGIONS}
        dem = 0
        for d in districts:
            if d["margin"] + national + regional[REGION_OF[d["state"]]] + fc.fat_tailed_error(d["local_sd"]) > 0:
                d["dem_wins"] += 1
                dem += 1
        seat_counts.append(dem)

    for d in districts:
        d["dem_prob"] = d["dem_wins"] / fc.SIMULATIONS
        d["rating"] = fc.rating(d["dem_prob"])

    report(districts, seat_counts, environment)
    save(districts, seat_counts)


def report(districts, seat_counts, environment):
    ordered = sorted(seat_counts)
    avg = sum(ordered) / len(ordered)
    control = sum(s >= MAJORITY for s in ordered) / len(ordered)
    by_favourite = sum(d["dem_prob"] >= 0.5 for d in districts)
    flips = [d for d in districts if (d["dem_prob"] >= 0.5) != (d["holder"] == "DEM")]
    ratings = defaultdict(int)
    for d in districts:
        ratings[d["rating"]] += 1

    print(f"\n2026 House forecast  ({fc.TODAY}, {fc.DAYS_LEFT} days out, "
          f"national environment {fc.fmt_margin(environment)})\n")
    print(f"Average outcome: {avg:.0f} D - {SEATS - avg:.0f} R   "
          f"(80% range: {ordered[len(ordered) // 10]} to {ordered[9 * len(ordered) // 10]} D seats)")
    print(f"Calling each seat for its favourite: {by_favourite} D - {SEATS - by_favourite} R")
    print(f"Chance Democrats win the House: {control:.0%}\n")
    order = ["Safe D", "Likely D", "Lean D", "Tilt D", "Toss-up", "Tilt R", "Lean R", "Likely R", "Safe R"]
    print("Ratings: " + ", ".join(f"{k} {ratings[k]}" for k in order))

    print(f"\nCompetitive districts (favourite under 80%), {sum(1 for d in districts if 0.2 < d['dem_prob'] < 0.8)} total:")
    print(f"  {'District':<9}{'Democrat':<24}{'Republican':<24}{'Lean':>7}{'Polls':>8}{'Margin':>8}{'Dem win':>9}  Rating")
    for d in sorted(districts, key=lambda d: -d["dem_prob"]):
        if 0.2 < d["dem_prob"] < 0.8:
            print(f"  {d['code']:<9}{d['dem'][:22]:<24}{d['rep'][:22]:<24}{fc.fmt_margin(d['lean']):>7}"
                  f"{fc.fmt_margin(d['poll_avg']):>8}{fc.fmt_margin(d['margin']):>8}{d['dem_prob']:>8.0%}  {d['rating']}")
    print(f"\nProjected flips ({len(flips)}): " + ", ".join(
        f"{d['code']} ({'D' if d['dem_prob'] >= 0.5 else 'R'})" for d in sorted(flips, key=lambda d: d["code"])))


def save(districts, seat_counts):
    os.makedirs("history", exist_ok=True)
    header = ["district", "democrat", "republican", "holder", "lean", "incumbency", "fundamentals",
              "poll_avg", "num_polls", "margin", "dem_win_prob", "rating"]
    for path in ("house_results.csv", f"history/{fc.TODAY}_house.csv"):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            for d in districts:
                w.writerow([d["code"], d["dem"], d["rep"], d["holder"], round(d["lean"], 2), d["incumbency"],
                            round(d["fundamentals"], 2), "" if d["poll_avg"] is None else round(d["poll_avg"], 2),
                            round(d["num_polls"], 2), round(max(min(d["margin"], 100), -100), 2),
                            round(d["dem_prob"], 3), d["rating"]])
    with open("house_seat_distribution.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dem_seats", "probability"])
        for s in sorted(set(seat_counts)):
            w.writerow([s, round(seat_counts.count(s) / len(seat_counts), 4)])


if __name__ == "__main__":
    main()
