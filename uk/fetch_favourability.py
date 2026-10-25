"""
Download leader and party favourability polls into uk/data/favourability.csv.
The tactical-voting model uses how disliked each party is ("neg") to decide
which way squeezed voters jump.

Sources (Wikipedia, CC BY-SA 4.0, via the MediaWiki API):
  - "Leadership approval opinion polling for the next United Kingdom general
    election": leader and party ratings since July 2024, one table per year,
    three columns (Pos. / Neg. / Net) per leader or party.
  - "Leadership approval opinion polling for the 2024 United Kingdom general
    election": leader ratings up to the 2024 election, one table per leader
    (the leader is the section heading), Approve / Disapprove columns.
    Needed to calibrate tactical voting on 2024.

Question wordings differ (favourable, approve, satisfied ...); each row keeps
the share positive and negative as published.

Run it with:  python uk/fetch_favourability.py
"""

import csv
import json
import os
import re
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

import fetch_polls as fp   # same table helpers as the voting-intention scraper

PAGES = [
    "Leadership_approval_opinion_polling_for_the_next_United_Kingdom_general_election",
    "Leadership_approval_opinion_polling_for_the_2024_United_Kingdom_general_election",
]
OUT = os.path.join(os.path.dirname(__file__), "data", "favourability.csv")

# Leaders whose ratings count for their party. Anyone else on the pages
# (hypothetical leaders, former leaders) is skipped.
LEADER_PARTY = {
    "Keir Starmer": "Lab", "Andy Burnham": "Lab", "Jeremy Corbyn": "Lab",
    "Rishi Sunak": "Con", "Kemi Badenoch": "Con", "Boris Johnson": "Con",
    "Jo Swinson": "LD",
    "Nigel Farage": "Ref",
    "Ed Davey": "LD",
    "Zack Polanski": "Grn", "Carla Denyer": "Grn", "Adrian Ramsay": "Grn",
    "Rupert Lowe": "Oth",
}
PARTY_NAMES = {"Labour": "Lab", "Conservative": "Con", "Reform": "Ref", "Lib Dems": "LD", "Green": "Grn"}

SKIP_HEADINGS = {"Graphical summary"}


def download(page):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "parse", "page": page, "prop": "text", "format": "json", "formatversion": 2})
    req = urllib.request.Request(url, headers={"User-Agent": "senate-forecast/0.1 (personal research project)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["parse"]["text"]


def section(table):
    """The nearest heading above the table that isn't a year: a leader's name, 'Party approval' ..."""
    for heading in table.find_all_previous(["h2", "h3", "h4"]):
        text = heading.get_text(strip=True)
        if not re.fullmatch(r"\d{4}", text) and text not in SKIP_HEADINGS:
            return text
    return ""


def number(text):
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match and "N/a" not in text else None


def row_basics(cells, col, year):
    dates = fp.parse_dates(cells[col["date"]], year)
    if not dates:
        return None
    return {"end_date": dates[1].isoformat(), "pollster": fp.pollster_name(cells[col["pollster"]]),
            "sample_size": int(re.sub(r"\D", "", cells[col["sample"]]) or 0)}


def grouped_table(table, year, kind):
    """Current page: a header row of names (3 columns each), then a Pos. / Neg. / Net row."""
    rows = fp.grid(table)
    sub = next(i for i, r in enumerate(rows) if r and "Pos." in r)
    names, labels = rows[0], rows[sub]
    col = {"date": 0, "pollster": 1, "sample": 2}
    out = []
    for cells in rows[sub + 1:]:
        if cells is None or len(cells) != len(labels):
            continue
        basics = row_basics(cells, col, year)
        if not basics:
            continue
        found = {}
        for c, (name, label) in enumerate(zip(names, labels)):
            name = fp.re.sub(r"\s+", " ", name).strip()
            party = LEADER_PARTY.get(name) if kind == "leader" else PARTY_NAMES.get(name)
            if party and label in ("Pos.", "Neg."):
                found.setdefault(name, {"party": party})[label] = number(cells[c])
        for name, v in found.items():
            if v.get("Pos.") is not None and v.get("Neg.") is not None:
                out.append({**basics, "kind": kind, "name": name, "party": v["party"],
                            "pos": v["Pos."], "neg": v["Neg."]})
    return out


def leader_table(table, year, leader):
    """2024 page: one leader per table, Approve / Disapprove columns."""
    rows = fp.grid(table)
    header = rows[0]
    col = {"date": 0, "pollster": 1, "sample": 2,
           "pos": header.index("Approve"), "neg": header.index("Disapprove")}
    out = []
    for cells in rows[2:]:
        if cells is None or len(cells) != len(header):
            continue
        basics = row_basics(cells, col, year)
        pos, neg = number(cells[col["pos"]]), number(cells[col["neg"]])
        if basics and pos is not None and neg is not None:
            out.append({**basics, "kind": "leader", "name": leader, "party": LEADER_PARTY[leader],
                        "pos": pos, "neg": neg})
    return out


def main():
    rows = []
    for page in PAGES:
        soup = BeautifulSoup(download(page), "lxml")
        for table in soup.find_all("table", class_="wikitable"):
            year = fp.table_year(table)
            name = section(table)
            header = fp.grid(table)[0] or []
            if year is None:
                continue
            if "Approve" in header and name in LEADER_PARTY:
                rows += leader_table(table, year, name)
            elif name == "Leadership approval":
                rows += grouped_table(table, year, "leader")
            elif name == "Party approval":
                rows += grouped_table(table, year, "party")

    # the same poll can appear on both pages around July 2024
    unique = {(r["end_date"], r["pollster"], r["kind"], r["name"]): r for r in rows}
    rows = sorted(unique.values(), key=lambda r: (r["end_date"], r["kind"], r["name"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    for r in rows:
        counts[(r["kind"], r["name"])] = counts.get((r["kind"], r["name"]), 0) + 1
    print(f"Saved {len(rows)} ratings ({rows[0]['end_date']} to {rows[-1]['end_date']}) to {OUT}")
    for (kind, name), n in sorted(counts.items()):
        print(f"  {kind:7} {name:16} {n}")


if __name__ == "__main__":
    main()
