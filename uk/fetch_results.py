"""
Download the 4 July 2024 general election results, and the 2019 results
re-calculated onto the same (2024) boundaries ("notional" results), and save
one row per constituency to:

  uk/data/results_2024.csv
  uk/data/results_2019_notional.csv

The notional 2019 file is what the seat model calibrates against: how far each
seat's 2019 -> 2024 change strayed from the national change.

Source: the House of Commons Library's results site, electionresults.parliament.uk
(Open Parliament Licence). The 2019 notionals are Rallings & Thrasher's.

Each row has the votes and vote share of every modelled party (see PARTIES),
with every other candidate counted as "Oth". The Speaker's seat is flagged,
because the main parties don't stand there.

Run it with:  python uk/fetch_results.py
"""

import csv
import io
import os
import urllib.request
from collections import defaultdict

URL = "https://electionresults.parliament.uk/general-elections/{}/candidacies.csv"
ELECTIONS = {"results_2024.csv": 6, "results_2019_notional.csv": 5}   # the site's election numbers
DATA = os.path.join(os.path.dirname(__file__), "data")

# The parties the model tracks, and the site's abbreviation for each.
# Labour Co-op candidates are listed as Lab; Scottish Greens share the Green
# code; the Brexit Party (2019) became Reform UK.
PARTIES = {"Lab": "Lab", "Con": "Con", "RUK": "Ref", "BRX": "Ref", "LD": "LD", "Green": "Grn", "SNP": "SNP", "PC": "PC"}
COLUMNS = ["Lab", "Con", "Ref", "LD", "Grn", "SNP", "PC", "Oth"]


def download(number):
    req = urllib.request.Request(URL.format(number), headers={"User-Agent": "senate-forecast/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return list(csv.DictReader(io.StringIO(resp.read().decode("utf-8-sig"))))


def by_constituency(candidates):
    seats = {}
    votes = defaultdict(lambda: dict.fromkeys(COLUMNS, 0))
    for c in candidates:
        code = c["Constituency geographic code"]
        party = PARTIES.get(c["Main party abbreviation"], "Oth")
        votes[code][party] += int(c["Candidate vote count"] or 0)
        if code not in seats:
            seats[code] = {
                "ons_code": code,
                "name": c["Constituency name"],
                "country": c["Country name"],
                "region": c["English region name"] or c["Country name"],
                "electorate": int(c["Electorate"] or 0),
                "valid_votes": int(c["Election valid vote count"] or 0),
                "speaker_seat": 0,
            }
        if c["Candidate is standing as Commons Speaker"] == "true":
            seats[code]["speaker_seat"] = 1
        if c["Candidate result position"] == "1":
            # winner's party in our columns, plus the site's own label (SF, DUP, Ind ...)
            seats[code]["winner"] = party
            if c["Candidate is standing as Commons Speaker"] == "true":
                label = "Spk"
            elif c["Candidate is standing as independent"] == "true":
                label = "Ind"
            else:
                label = c["Main party abbreviation"] or "Oth"
            seats[code]["winner_label"] = label
            seats[code]["winner_name"] = f"{c['Candidate given name']} {c['Candidate family name']}".strip()
            seats[code]["majority"] = int(c["Majority"] or 0)

    rows = []
    for code, seat in seats.items():
        total = sum(votes[code].values())
        row = dict(seat)
        row["turnout"] = round(seat["valid_votes"] / seat["electorate"], 4) if seat["electorate"] else ""
        for p in COLUMNS:
            row[f"{p}_votes"] = votes[code][p]
        for p in COLUMNS:
            row[f"{p}_share"] = round(votes[code][p] / total, 5)
        rows.append(row)
    return sorted(rows, key=lambda r: r["ons_code"])


def main():
    os.makedirs(DATA, exist_ok=True)
    for filename, number in ELECTIONS.items():
        candidates = download(number)
        rows = by_constituency(candidates)
        path = os.path.join(DATA, filename)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

        winners = defaultdict(int)
        for r in rows:
            winners[r["winner_label"]] += 1
        print(f"Saved {len(rows)} constituencies ({len(candidates)} candidates) to {path}")
        print("  Seats won:", ", ".join(f"{p} {n}" for p, n in sorted(winners.items(), key=lambda x: -x[1])))


if __name__ == "__main__":
    main()
