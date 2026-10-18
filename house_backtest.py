"""
House backtest: how would the House model's fundamentals have done in
2016-2024, using only information available before each election?

  A. lean + national environment
  B. A + incumbency
  C. B + candidate quality (prior competitive House race, same rule as the Senate)

National environment = the actual national House vote (as in backtest.py),
so the test isolates the district-level pieces. Choices are compared on
2016-2020 and checked on 2022-2024.

Data (local only, not republished):
  - Presidential results by district on each year's map: Daily Kos Elections /
    The Downballot (https://www.the-downballot.com/p/data) for 2016-2022 maps;
    ElectIndex historical.csv for 2024 (states whose lines didn't change 2024->2026)
  - House results: MIT Election Data + Science Lab (CC0)

Run it with:  python house_backtest.py
"""

import csv
import math
from collections import defaultdict

import backtest as bt
import house_forecast as hf

TUNE, CHECK = [2016, 2018, 2020], [2022, 2024]
LEAN_WEIGHTS = [0.75, 0.175, 0.075]     # most recent presidential election first
CANDIDATE_SHRINK = 2 / 3
MAX_PRIOR_MARGIN = 15


def code(raw):
    """'AK-AL' / 'AK-1' / 'PA-07' -> 'AK-01'"""
    state, num = raw.strip().split("-")
    return f"{state}-{1 if num == 'AL' else int(num):02d}"


def load_maps():
    """{house_year: {district: {pres_year: margin}}} - presidential margins on that year's lines."""
    layouts = {  # house year: (file, [(pres year, dem column, rep column), ...])
        2016: ("maps2016.csv", [(2016, 3, 4), (2012, 5, 6), (2008, 7, 8)]),
        2018: ("maps2018.csv", [(2016, 3, 4), (2012, 5, 6), (2008, 7, 8)]),
        2020: ("maps2020.csv", [(2020, 3, 4), (2016, 5, 6), (2012, 7, 8), (2008, 9, 10)]),
        2022: ("maps2022.csv", [(2020, 3, 4)]),
    }
    maps = {}
    for year, (name, cols) in layouts.items():
        with open(f"data/downballot/{name}", encoding="utf-8") as f:
            rows = [r for r in csv.reader(f) if r and len(r[0]) >= 4 and r[0][2] == "-"]
        maps[year] = {code(r[0]): {py: float(r[d]) - float(r[rp]) for py, d, rp in cols
                                   if r[d].strip() and r[rp].strip()} for r in rows}

    # 2024: ElectIndex results on the 2026 lines, only where those match the 2024 lines
    hist = {r["code"]: r for r in hf.fc.load_csv_utf8("data/electindex/historical.csv") if r["level"] == "district"}
    same = hf.unchanged_states(hist, hf.mit_house_results())
    maps[2024] = {c: {2020: float(h["margin_2020"]), 2016: float(h["margin_2016"])}
                  for c, h in hist.items() if h["state"] in same}
    return maps


def house_results():
    """{(year, district): (margin, dem surname, rep surname)} for contested general elections."""
    raw = defaultdict(lambda: defaultdict(lambda: [0.0, set()]))
    with open("data/mit/house.csv", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["year"]) < 2012 or r["stage"].upper() != "GEN" or r["special"].upper() == "TRUE" \
                    or r["candidate"] in ("", "WRITEIN"):
                continue
            num = int(r["district"]) if r["district"].isdigit() else 0
            entry = raw[(int(r["year"]), f"{r['state_po']}-{max(num, 1):02d}")][r["candidate"]]
            entry[0] += float(r["candidatevotes"] or 0)
            entry[1].add(r["party"])
    out = {}
    for key, cands in raw.items():
        dem = max(((v, n) for n, (v, p) in cands.items() if p & hf.DEM_PARTIES), default=(0, None))
        rep = max(((v, n) for n, (v, p) in cands.items() if "REPUBLICAN" in p), default=(0, None))
        if dem[0] > 0 and rep[0] > 0:
            out[key] = (100 * (dem[0] - rep[0]) / (dem[0] + rep[0]), hf.surname(dem[1]), hf.surname(rep[1]))
    return out


def all_winners():
    """{(year, district): winner surname}, including uncontested races (for incumbency)."""
    best = defaultdict(lambda: (0.0, None))
    with open("data/mit/house.csv", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if int(r["year"]) < 2012 or r["stage"].upper() != "GEN" or r["special"].upper() == "TRUE" \
                    or r["candidate"] in ("", "WRITEIN"):
                continue
            num = int(r["district"]) if r["district"].isdigit() else 0
            key = (int(r["year"]), f"{r['state_po']}-{max(num, 1):02d}")
            v = float(r["candidatevotes"] or 0)
            if v > best[key][0]:
                best[key] = (v, hf.surname(r["candidate"]))
    return {k: n for k, (v, n) in best.items()}


def run(incumbency_bonus=hf.HOUSE_INCUMBENCY_BONUS, use_candidates=True, years=TUNE + CHECK):
    maps, results, winners = DATA
    _, pres_national = bt.presidential_margins()
    env = bt.NATIONAL_ENVIRONMENT

    def lean(year, district):
        pres = maps[year][district]
        ys = sorted((py for py in pres if py < year), reverse=True)[:3]
        if not ys:
            return None
        return sum(w * (pres[y] - pres_national[y]) for w, y in zip(LEAN_WEIGHTS, ys)) / sum(LEAN_WEIGHTS[:len(ys)])

    def incumbency(year, district, dem, rep):
        prev = winners.get((year - 2, district))
        return incumbency_bonus if prev == dem else -incumbency_bonus if prev == rep else 0.0

    def baseline(year, district, dem, rep):
        l = lean(year, district)
        return None if l is None else l + env[year] + incumbency(year, district, dem, rep)

    rows = []
    for (year, district), (margin, dem, rep) in results.items():
        if year not in years or district not in maps.get(year, {}):
            continue
        base = baseline(year, district, dem, rep)
        if base is None:
            continue
        cand = 0.0
        if use_candidates:
            for prior_year in (year - 2, year - 4):   # most recent earlier race, same district & map
                prior = results.get((prior_year, district))
                if not prior or prior_year not in maps or district not in maps[prior_year] \
                        or abs(prior[0]) > MAX_PRIOR_MARGIN or not ({dem, rep} & {prior[1], prior[2]}):
                    continue
                prior_base = baseline(prior_year, district, prior[1], prior[2])
                if prior_base is not None:
                    cand = CANDIDATE_SHRINK * (prior[0] - prior_base)
                break
        rows.append({"year": year, "district": district, "actual": margin,
                     "no_inc": base - incumbency(year, district, dem, rep), "pred": base + cand})
    return rows


def score(rows, key="pred"):
    miss = sum(abs(r["actual"] - r[key]) for r in rows) / len(rows)
    right = sum((r["actual"] > 0) == (r[key] > 0) for r in rows)
    return f"{miss:5.2f} {right:>4}/{len(rows):<4}"


def main():
    print("House backtest, fundamentals only (contested races; actual national House vote)\n")
    print(f"{'':<34}{'tune 2016-20':>16}{'check 2022-24':>17}")
    t, c = run(use_candidates=False, years=TUNE), run(use_candidates=False, years=CHECK)
    print(f"{'A: lean + environment':<34}{score(t, 'no_inc'):>16}{score(c, 'no_inc'):>17}")
    print(f"{'B: + incumbency (3.7)':<34}{score(t):>16}{score(c):>17}")
    t, c = run(years=TUNE), run(years=CHECK)
    print(f"{'C: + candidate quality':<34}{score(t):>16}{score(c):>17}")

    print("\nIncumbency bonus (with candidate quality):")
    for b in (0.0, 2.0, 3.7, 5.0, 7.0):
        print(f"  {b:<32}{score(run(b, years=TUNE)):>16}{score(run(b, years=CHECK)):>17}")

    print("\nBy year (model C):")
    for y in TUNE + CHECK:
        rows = run(years=[y])
        print(f"  {y}  {score(rows)}")


DATA = (load_maps(), house_results(), all_winners())

if __name__ == "__main__":
    main()
