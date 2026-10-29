"""
2026 governor forecast - all 36 races.

Same machinery as the Senate model (forecast.py), with the settings refitted
on every governor race since 2010 (governor_backtest.py):
  1. Fundamentals = 0.8 x presidential lean (governor races are less partisan
     than Senate races) + national environment + incumbency (5 points)
     + half of each candidate's record in earlier governor races
  2. Governor polls: undecided allocation, house effects, quality weighting,
     and much more weight than in the Senate model - in the backtest, leaning
     on governor polls was better in both 2010-16 and 2018-22
  3. 10,000 simulated elections with national, regional and local errors,
     25% wider than the Senate model's (governor races were measured to miss
     by more)

Races and candidates: ElectIndex 26_us_forecast_data (kept locally in
data/electindex/, not republished). Polls: NYT via PollResults.org (CC BY 4.0).

Run it with:  python governor_forecast.py   (after python fetch_polls.py)
"""

import csv
import math
import random

import backtest as bt
import backtest_governor as bg
import forecast as fc
import house_forecast as hf

# Fitted on 2010-16 governor races, checked on 2018-24 (governor_backtest.py)
LEAN_SCALE = 0.8
INCUMBENCY_BONUS = 5.0
GOVERNOR_RECORD_SHRINK = 0.5
POLL_MAX_WEIGHT = 0.95
POLL_K = 0.25              # weight = max * n / (n + k), n = effective number of polls
GOV_ERROR_SCALE = 1.25     # governor misses were 1.2-1.4x the Senate model's uncertainty

# Governors not up in 2026 (DE, KY, NJ, NC, VA, WA / IN, LA, MS, MO, MT, ND, UT, WV)
NOT_UP = {"D": 6, "R": 8}
MAJORITY = 26


def load_races():
    cands = {c["cand_id"]: c for c in fc.load_csv_utf8("data/electindex/candidates.csv")}
    races = []
    for r in fc.load_csv_utf8("data/electindex/races.csv"):
        if r["race_type"] != "governor":
            continue
        inc = 0.0
        if cands.get(r["dem_id"], {}).get("incumbent") == "1":
            inc = INCUMBENCY_BONUS
        elif cands.get(r["rep_id"], {}).get("incumbent") == "1":
            inc = -INCUMBENCY_BONUS
        races.append({"state": r["state"], "dem": r["dem_name"], "rep": r["rep_name"],
                      "holder": r["seat_holder"], "inc": inc})
    return races


def last_name(name):
    return name.replace(".", " ").split()[-1].upper()


def record_key(name, state, gov_races):
    """The name key a candidate has in the governor results (matched on surname within the state)."""
    surname = last_name(name)
    for g in gov_races:
        for key in (g["dem"], g["rep"]):
            if g["state"] == state and key.split()[-1] == surname:
                return key
    return None


def governor_adjustment(race, gov_races, pres, national):
    total, parts = 0.0, []
    for side in ("dem", "rep"):
        key = record_key(race[side], race["state"], gov_races)
        if key is None:
            continue
        rec = bg.governor_record(key, side, race["state"], 2026, gov_races, pres, national,
                                 INCUMBENCY_BONUS, 999, "lean")
        if rec is not None:
            total += GOVERNOR_RECORD_SHRINK * rec
            parts.append(f"{race[side]} {GOVERNOR_RECORD_SHRINK * rec:+.1f}")
    return total, ", ".join(parts)


def poll_weight(n):
    return POLL_MAX_WEIGHT * n / (n + POLL_K)


def main():
    pres, national = bt.presidential_margins()
    gov_races = bg.governor_races()
    weights = fc.live_pollster_weights()
    environment = fc.national_environment(weights)
    races = load_races()

    for r in races:
        r["lean"] = bt.presidential_lean(r["state"], 2026, pres, national)
        r["cand"], r["cand_why"] = governor_adjustment(r, gov_races, pres, national)
        r["fundamentals"] = LEAN_SCALE * r["lean"] + environment + r["inc"] + r["cand"]

    # Polls of this year's matchup only (not primary-season or hypothetical pairings)
    matchup = {r["state"]: (last_name(r["dem"]), last_name(r["rep"])) for r in races}
    polls = [p for p in fc.load_csv_utf8("data/gov_polls.csv")
             if p["state"] in matchup and (last_name(p["dem_name"]), last_name(p["rep_name"])) == matchup[p["state"]]]
    polls = fc.allocate_undecided(polls, {r["state"]: LEAN_SCALE * r["lean"] + environment for r in races})
    polls = fc.debias(polls, fc.house_effects(polls))

    for r in races:
        avg, n = fc.polling_average([p for p in polls if p["state"] == r["state"]], weights)
        w = poll_weight(n)
        r["poll_avg"], r["num_polls"], r["poll_weight"] = avg, n, w
        r["margin"] = r["fundamentals"] if avg is None else (1 - w) * r["fundamentals"] + w * avg
        r["sd"] = GOV_ERROR_SCALE * fc.state_error_sd(min(w, fc.MAX_POLL_WEIGHT))
        r["local_sd"] = math.sqrt(max(r["sd"] ** 2 - fc.REGION_ERROR_SD ** 2, 1.0))
        r["dem_wins"] = 0

    counts = []
    national_sd = GOV_ERROR_SCALE * fc.national_error_sd()
    for _ in range(fc.SIMULATIONS):
        nat = fc.fat_tailed_error(national_sd)
        reg = {region: fc.fat_tailed_error(fc.REGION_ERROR_SD) for region in hf.REGIONS}
        dem = NOT_UP["D"]
        for r in races:
            if r["margin"] + nat + reg[hf.REGION_OF[r["state"]]] + fc.fat_tailed_error(r["local_sd"]) > 0:
                r["dem_wins"] += 1
                dem += 1
        counts.append(dem)
    counts.sort()
    avg_dem = sum(counts) / len(counts)
    majority = sum(c >= MAJORITY for c in counts) / len(counts)
    called = NOT_UP["D"] + sum(r["margin"] > 0 for r in races)
    for r in races:
        r["dem_prob"] = r["dem_wins"] / fc.SIMULATIONS
        r["rating"] = fc.rating(r["dem_prob"])

    print(f"\n2026 governor forecast  ({fc.TODAY}, {fc.DAYS_LEFT} days out, "
          f"national environment {fc.fmt_margin(environment)})\n")
    print(f"{'State':<6}{'Democrat':<22}{'Republican':<24}{'Lean':>7}{'Fund.':>8}{'Polls':>8}{'#':>5}"
          f"{'Margin':>9}{'Dem win':>9}  Rating")
    for r in sorted(races, key=lambda r: -r["margin"]):
        print(f"{r['state']:<6}{r['dem'][:21]:<22}{r['rep'][:23]:<24}{fc.fmt_margin(r['lean']):>7}"
              f"{fc.fmt_margin(r['fundamentals']):>8}{fc.fmt_margin(r['poll_avg']):>8}{r['num_polls']:>5.1f}"
              f"{fc.fmt_margin(r['margin']):>9}{r['dem_prob']:>8.0%}  {r['rating']}")
    print("Governor records: " + "; ".join(f"{r['state']} ({r['cand_why']})" for r in races if r["cand_why"]))
    flips = [f"{r['state']} ({'D' if r['margin'] > 0 else 'R'})" for r in races
             if (r["margin"] > 0) != (r["holder"] == "DEM")]
    print(f"Projected flips ({len(flips)}): {', '.join(flips)}")
    print(f"Governorships after the election, calling each race for its favourite: {called} D - {50 - called} R")
    print(f"Average outcome: {avg_dem:.1f} D - {50 - avg_dem:.1f} R  "
          f"(80% range: {counts[int(0.1 * len(counts))]} to {counts[int(0.9 * len(counts))]} D)")
    print(f"Chance Democrats hold a majority of governorships (26+): {majority:.0%}\n")

    with open("governor_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["state", "democrat", "republican", "holder", "lean", "incumbency", "candidate",
                         "fundamentals", "poll_avg", "num_polls", "poll_weight", "margin", "sd",
                         "dem_win_prob", "rating"])
        for r in sorted(races, key=lambda r: r["state"]):
            writer.writerow([r["state"], r["dem"], r["rep"], r["holder"], round(r["lean"], 2), r["inc"],
                             round(r["cand"], 2), round(r["fundamentals"], 2),
                             "" if r["poll_avg"] is None else round(r["poll_avg"], 2), round(r["num_polls"], 2),
                             round(r["poll_weight"], 2), round(r["margin"], 2), round(r["sd"], 2),
                             round(r["dem_prob"], 3), r["rating"]])
    with open("governor_summary.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "environment", "called_dem", "avg_dem", "dem_low", "dem_high", "dem_majority_prob"])
        writer.writerow([fc.TODAY, round(environment, 2), called, round(avg_dem, 2),
                         counts[int(0.1 * len(counts))], counts[int(0.9 * len(counts))], round(majority, 3)])


if __name__ == "__main__":
    random.seed()
    main()
