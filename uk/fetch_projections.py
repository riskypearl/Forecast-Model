"""
Download published seat projections (MRPs and other models) for the next
general election into uk/data/seat_projections.csv - a benchmark for our own
nowcast, and, where a pollster published versions with and without tactical
voting, a check on how big our tactical-voting effect is.

Source: Wikipedia, "Seat projections for the next United Kingdom general
election" (CC BY-SA 4.0), via the MediaWiki API. The page has two tables:
"Not accounting for tactical voting" and "Accounting for tactical voting".

Run it with:  python uk/fetch_projections.py
"""

import csv
import json
import os
import re
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

import fetch_polls as fp

PAGE = "Seat_projections_for_the_next_United_Kingdom_general_election"
OUT = os.path.join(os.path.dirname(__file__), "data", "seat_projections.csv")
PARTY_COLUMNS = {"Lab": "Lab", "Con": "Con", "Ref": "Ref", "LD": "LD", "Grn": "Grn",
                 "SNP": "SNP", "PC": "PC", "Others": "Oth"}


def download():
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "parse", "page": PAGE, "prop": "text", "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": "senate-forecast/0.1 (personal research project)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["parse"]["text"]


def main():
    soup = BeautifulSoup(download(), "lxml")
    rows = []
    for table in soup.find_all("table", class_="wikitable"):
        heading = table.find_previous(["h2", "h3", "h4"]).get_text(strip=True).lower()
        if "tactical" not in heading:
            continue
        tactical = int(not heading.startswith("not"))
        grid = fp.grid(table)
        header = grid[0]
        col = {name: i for i, name in enumerate(header)}
        for cells in grid[1:]:
            if cells is None or len(cells) != len(header):
                continue
            dates = fp.parse_dates(cells[col["Date(s) conducted"]], None)
            seats = {p: cells[col[name]] for name, p in PARTY_COLUMNS.items() if name in col}
            if not dates or not dates[1].year or not seats["Lab"].isdigit():
                continue
            rows.append({
                "end_date": dates[1].isoformat(),
                "pollster": fp.pollster_name(cells[col["Pollster"]]),
                "client": cells[col["Client"]],
                "method": cells[col["Method"]],
                "sample_size": int(re.sub(r"\D", "", cells[col["Sample size"]]) or 0),
                "tactical": tactical,
                **{p: int(v) if v.isdigit() else "" for p, v in seats.items()},
            })

    rows.sort(key=lambda r: (r["end_date"], r["pollster"], r["tactical"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} projections ({sum(r['tactical'] for r in rows)} with tactical voting) to {OUT}")


if __name__ == "__main__":
    main()
