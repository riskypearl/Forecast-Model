"""Render the governor forecast graphic (1080x1350) - graphics/governor_forecast.png

Reads governor_results.csv and governor_summary.csv, so it always matches the
latest governor_forecast.py run.
"""

import csv
import os
from datetime import date

from make_instagram import ROOT, ELECTION_DAY, STATE_NAMES, draw

COMPETITIVE = 8.0           # races within this many points go on the graphic
EXTRA_NAMES = {"CA": "CALIFORNIA", "CT": "CONNECTICUT", "HI": "HAWAII", "MD": "MARYLAND", "NV": "NEVADA",
               "NY": "NEW YORK", "PA": "PENNSYLVANIA", "VT": "VERMONT", "WI": "WISCONSIN", "AZ": "ARIZONA"}


def load_governors():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "governor_results.csv"), encoding="utf-8")))
    summary = list(csv.DictReader(open(os.path.join(ROOT, "governor_summary.csv"))))[-1]
    races = []
    for r in rows:
        m = float(r["margin"])
        if abs(m) > COMPETITIVE:
            continue
        party = "D" if m > 0 else "R"
        name = (r["democrat"] if party == "D" else r["republican"]).split()[-1]
        holder = "D" if r["holder"] == "DEM" else "R"
        races.append(({**STATE_NAMES, **EXTRA_NAMES}[r["state"]], name, party, abs(m), party != holder))
    races.sort(key=lambda x: (x[2] == "R", -x[3] if x[2] == "D" else x[3]))
    dem = int(summary["called_dem"])
    run_date = date.fromisoformat(summary["date"])
    label = f"{run_date.day} {run_date.strftime('%b').upper()} {run_date.year}  ·  {(ELECTION_DAY - run_date).days} DAYS OUT"
    return races, dem, 50 - dem, round(100 * float(summary["dem_majority_prob"])), label


def main():
    races, dem, rep, majority, label = load_governors()
    favoured = "Democrats" if dem >= 26 else "Republicans"
    draw(races, dem, rep, f"{majority if dem >= 26 else 100 - majority}% CHANCE OF A {favoured[:3].upper()} MAJORITY",
         label, "2026 U.S. GOVERNOR FORECAST", "most governorships", None, "governor_forecast.png")


if __name__ == "__main__":
    main()
