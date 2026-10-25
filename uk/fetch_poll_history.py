"""
GB Westminster voting-intention polls since the 2010 general election, into
uk/data/poll_history.csv, plus the BBC's Projected National Share (PNS) of
each year's local elections into uk/data/pns.csv.

Used for two things:
  - the local-vs-national gap: each year's PNS against the polls in the
    fortnight before (local_gap.py)
  - how far the polls move over months (time uncertainty to May 2028)

Sources: Wikipedia (CC BY-SA 4.0) - "Opinion polling for the 2015 / 2017 /
2019 / 2024 United Kingdom general election", and "Projected National Share".
The populist-right slot ("Ref") is UKIP to 2017, the Brexit Party / Reform
UK after. Polls after July 2024 come from fetch_polls.py (data/polls.csv).

Run it with:  python uk/fetch_poll_history.py
"""

import csv
import os
import re
import time

from bs4 import BeautifulSoup

import fetch_polls as fp
import fetch_sv_results as sv

PAGES = [
    "Opinion polling for the 2015 United Kingdom general election",
    "Opinion polling for the 2017 United Kingdom general election",
    "Opinion polling for the 2019 United Kingdom general election",
    "Opinion polling for the 2024 United Kingdom general election",
]
HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "data", "poll_history.csv")
PNS_OUT = os.path.join(HERE, "data", "pns.csv")
PARTIES = ["Lab", "Con", "Ref", "LD", "Grn"]

# Table column headers -> our parties
COLUMNS = {"Lab": "Lab", "Con": "Con", "LD": "LD", "Lib Dem": "LD", "Lib Dems": "LD", "UKIP": "Ref",
           "Brexit": "Ref", "Brx": "Ref", "Ref": "Ref", "Reform": "Ref", "Grn": "Grn", "Green": "Grn", "Greens": "Grn"}
# Where a table has both, the Brexit Party / Reform column is the populist-right slot, not UKIP
REF_PRIORITY = ["Ref", "Reform", "Brx", "Brexit", "UKIP"]
DATE_HEADERS = ("Date(s) conducted", "Fieldwork date", "Dates conducted", "Date(s)conducted")


def polls_from(page):
    soup = BeautifulSoup(sv.download(page), "lxml")
    out = []
    for table in soup.find_all("table", class_="wikitable"):
        grid = fp.grid(table)
        header = grid[0] or []
        date_col = next((i for i, h in enumerate(header) if h in DATE_HEADERS), None)
        pollster_col = next((i for i, h in enumerate(header) if h.startswith(("Pollster", "Polling organisation"))), None)
        party_cols = {COLUMNS[h]: i for i, h in enumerate(header) if h in COLUMNS and COLUMNS[h] != "Ref"}
        ref = next((h for h in REF_PRIORITY if h in header), None)
        if ref:
            party_cols["Ref"] = header.index(ref)
        if date_col is None or pollster_col is None or len(party_cols) < 3:
            continue
        if "Area" in header:
            area_col = header.index("Area")
        else:
            area_col = None
        year = fp.table_year(table)
        for cells in grid[1:]:
            if cells is None or len(cells) != len(header):
                continue
            if area_col is not None and cells[area_col] not in ("GB", "UK"):
                continue
            dates = fp.parse_dates(cells[date_col], year) if year else None
            if not dates:
                continue
            row = {"pollster": fp.pollster_name(cells[pollster_col]), "end_date": dates[1].isoformat()}
            for p in PARTIES:
                row[p] = fp.percent(cells[party_cols[p]]) if p in party_cols else None
            if row["Lab"] is None or row["Con"] is None or not (70 <= sum(v or 0 for v in row.values()
                                                                             if isinstance(v, float)) <= 102):
                continue
            out.append(row)
    return out


def pns():
    soup = BeautifulSoup(sv.download("Projected National Share"), "lxml")
    table = soup.find("table", class_="wikitable")
    rows = []
    for cells in fp.grid(table)[2:]:
        if not cells or not cells[0].isdigit():
            continue
        values = dict(zip(["Lab", "Con", "LD", "Ref", "Grn", "Oth"], cells[1:7]))
        rows.append({"year": int(cells[0]), **{p: (float(v) if re.fullmatch(r"\d+", v) else "") for p, v in values.items()}})
    return rows


def main():
    rows = []
    for page in PAGES:
        time.sleep(1)
        got = polls_from(page)
        print(f"{page[22:]}: {len(got)} polls")
        rows += got
    with open(os.path.join(HERE, "data", "polls.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({"pollster": r["pollster"], "end_date": r["end_date"],
                         **{p: float(r[p]) if r[p] else None for p in PARTIES}})
    unique = {(r["end_date"], r["pollster"], r["Lab"], r["Con"]): r for r in rows}
    rows = sorted(unique.values(), key=lambda r: r["end_date"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["pollster", "end_date"] + PARTIES)
        writer.writeheader()
        writer.writerows({k: ("" if v is None else v) for k, v in r.items()} for r in rows)
    print(f"Saved {len(rows)} polls ({rows[0]['end_date']} to {rows[-1]['end_date']}) to {OUT}")

    shares = pns()
    with open(PNS_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(shares[0].keys()))
        writer.writeheader()
        writer.writerows(shares)
    print(f"Saved PNS for {len(shares)} years ({shares[0]['year']}-{shares[-1]['year']}) to {PNS_OUT}")


if __name__ == "__main__":
    main()
