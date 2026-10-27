"""
How local elections differ from national polls, and why.

Each May the BBC projects the local results onto a national scale (the
Projected National Share, PNS). Its gap to the Westminster polls in the
three weeks before polling day shows how each party does in local
contests relative to its national rating - the effect that a mayoral
forecast built on national polls has to correct for.

The gap is modelled, not copied:

    gap = party effect + government effect + government effect per year into the term

so a governing party's mid-term slump is estimated from every year of
2012-2026 (Coalition, Conservative and Labour governments), not just one.
Tested by leaving each year out in turn.

Run it with:  python uk/local_gap.py   (after fetch_poll_history.py)
Writes uk/data/local_gap.csv (one row per party and year).
"""

import csv
import os
from datetime import date

import numpy as np

HERE = os.path.dirname(__file__)
PARTIES = ["Lab", "Con", "Ref", "LD", "Grn"]

# Local election polling days
LOCAL_DAY = {2012: date(2012, 5, 3), 2013: date(2013, 5, 2), 2014: date(2014, 5, 22), 2015: date(2015, 5, 7),
             2016: date(2016, 5, 5), 2017: date(2017, 5, 4), 2018: date(2018, 5, 3), 2019: date(2019, 5, 2),
             2021: date(2021, 5, 6), 2022: date(2022, 5, 5), 2023: date(2023, 5, 4), 2024: date(2024, 5, 2),
             2025: date(2025, 5, 1), 2026: date(2026, 5, 7)}
# General elections, and who governed after each
GENERAL = [(date(2010, 5, 6), {"Con", "LD"}), (date(2015, 5, 7), {"Con"}), (date(2017, 6, 8), {"Con"}),
           (date(2019, 12, 12), {"Con"}), (date(2024, 7, 4), {"Lab"})]
POLL_WINDOW_DAYS = 21


def government(day):
    """(governing parties, years since the government was first elected - continuous Conservative rule counts from 2010)."""
    parties = [g for d, g in GENERAL if d <= day][-1]
    start = min(d for d, g in GENERAL if g & parties and all(g2 & parties for d2, g2 in GENERAL if d <= d2 <= day))
    return parties, (day - start).days / 365.25


def poll_average(polls, day):
    window = [p for p in polls if 0 <= (day - p["end_date"]).days <= POLL_WINDOW_DAYS]
    return {party: np.mean([p[party] for p in window if p[party] is not None]) if any(p[party] is not None for p in window)
            else None for party in PARTIES}, len(window)


def load():
    with open(os.path.join(HERE, "data", "poll_history.csv"), newline="", encoding="utf-8") as f:
        polls = [{"end_date": date.fromisoformat(r["end_date"]), **{p: float(r[p]) if r[p] else None for p in PARTIES}}
                 for r in csv.DictReader(f)]
    with open(os.path.join(HERE, "data", "pns.csv"), newline="", encoding="utf-8") as f:
        pns = {int(r["year"]): {p: float(r[p]) if r[p] else None for p in PARTIES} for r in csv.DictReader(f)}
    rows = []
    for year, day in LOCAL_DAY.items():
        if year not in pns:
            continue
        avg, n = poll_average(polls, day)
        gov, years_in = government(day)
        for p in PARTIES:
            if pns[year][p] is None or avg[p] is None:
                continue
            rows.append({"year": year, "party": p, "pns": pns[year][p], "polls": round(avg[p], 1),
                         "gap": round(pns[year][p] - avg[p], 1), "gov": int(p in gov),
                         "years_in": round(years_in, 2) if p in gov else 0.0, "n_polls": n})
    return rows


def design(rows):
    X = [[1.0 * (r["party"] == p) for p in PARTIES] + [r["gov"], r["years_in"]] for r in rows]
    return np.array(X), np.array([r["gap"] for r in rows])


def fit(rows, ridge=1.0):
    X, y = design(rows)
    return np.linalg.solve(X.T @ X + ridge * np.eye(X.shape[1]), X.T @ y)


def predict(coef, party, gov, years_in):
    x = np.array([1.0 * (party == p) for p in PARTIES] + [gov, years_in if gov else 0.0])
    return float(x @ coef)


def main():
    rows = load()
    with open(os.path.join(HERE, "data", "local_gap.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("Local elections (BBC projected national share) minus Westminster polls in the 3 weeks before, points")
    print(f"{'year':6}" + "".join(f"{p:>7}" for p in PARTIES) + "   governing")
    for year in sorted({r["year"] for r in rows}):
        gap = {r["party"]: r["gap"] for r in rows if r["year"] == year}
        gov, years_in = government(LOCAL_DAY[year])
        print(f"{year:<6}" + "".join(f"{gap[p]:+7.1f}" if p in gap else f"{'':>7}" for p in PARTIES)
              + f"   {'+'.join(sorted(gov))}, {years_in:.1f} yrs in")

    coef = fit(rows)
    names = [f"{p} (base)" for p in PARTIES] + ["in government", "per year in government"]
    print("\nModel: " + ", ".join(f"{n} {c:+.1f}" for n, c in zip(names, coef)))

    # Leave one year out: predict each year's gaps from the others
    errors = {"model": [], "party average": [], "zero (no gap)": []}
    for year in sorted({r["year"] for r in rows}):
        train = [r for r in rows if r["year"] != year]
        test = [r for r in rows if r["year"] == year]
        c = fit(train)
        for r in test:
            errors["model"].append(r["gap"] - predict(c, r["party"], r["gov"], r["years_in"]))
            same = [t["gap"] for t in train if t["party"] == r["party"]]
            errors["party average"].append(r["gap"] - (np.mean(same) if same else 0))
            errors["zero (no gap)"].append(r["gap"])
    print("\nLeave-one-year-out error (mean absolute, points):")
    for name, e in errors.items():
        print(f"  {name:16} {np.mean(np.abs(e)):.1f}   (SD {np.std(e):.1f})")

    print(f"\nPredicted gap for May 2028 (Labour governing, {government(date(2028, 5, 4))[1]:.1f} years in):")
    for p in PARTIES:
        gov = p == "Lab"
        print(f"  {p:4} {predict(coef, p, gov, government(date(2028, 5, 4))[1] if gov else 0):+.1f}")
    resid = np.array(errors["model"])
    print(f"  (uncertainty: leave-one-year-out residual SD {np.std(resid):.1f} points)")


if __name__ == "__main__":
    main()
