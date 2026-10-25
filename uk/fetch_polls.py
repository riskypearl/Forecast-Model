"""
Download every national (GB / UK) Westminster voting-intention poll since the
July 2024 election into uk/data/polls.csv.

Source: Wikipedia, "Opinion polling for the next United Kingdom general
election" (CC BY-SA 4.0), read through the MediaWiki API. The page has one
table per year; the regional tables further down are skipped.

Shares are in percent. Parties a poll didn't list ("-") are saved as blank;
parties the model doesn't track (e.g. Restore Britain, Your Party) are added
to Oth.

Run it with:  python uk/fetch_polls.py
"""

import csv
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date

from bs4 import BeautifulSoup

PAGE = "Opinion_polling_for_the_next_United_Kingdom_general_election"
API = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
    {"action": "parse", "page": PAGE, "prop": "text", "format": "json", "formatversion": 2})
OUT = os.path.join(os.path.dirname(__file__), "data", "polls.csv")

PARTIES = ["Lab", "Con", "Ref", "LD", "Grn", "SNP", "PC"]
LAST_ELECTION = date(2024, 7, 4)

# Polls that don't list a sample size get this.
DEFAULT_SAMPLE_SIZE = 1000

# A poll whose shares don't add to 100 within this many points is probably a
# parsing problem (merged cells, footnotes) - it's reported and dropped.
SUM_TOLERANCE = 4

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def download():
    req = urllib.request.Request(API, headers={"User-Agent": "senate-forecast/0.1 (personal research project)"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)["parse"]["text"]


def clean(cell):
    # A collapsed "Others" cell shows its total as a title above the breakdown
    # (YP 0%, Other 1%); take the total only, or the parties are counted twice.
    title = cell.find(class_="hidden-title")
    if title is not None:
        cell = title
    for style in cell.find_all("style"):
        style.decompose()
    text = cell.get_text(" ", strip=True)
    text = re.sub(r"\[\s*[^\]]*\]", "", text)        # footnote markers like [ 12 ]
    return text.replace("–", "-").replace("—", "-").strip()


def grid(table):
    """
    The table as a list of rows of cell texts, with merged cells repeated in
    every row and column they cover - so a party column that is one tall
    "not yet founded" cell for early polls still lines up. Rows containing a
    cell spanning several columns (by-elections, events) are marked None.
    """
    rows, carry = [], {}   # carry: column -> (text, rows still to fill)
    for tr in table.find_all("tr"):
        row, wide, col = {}, False, 0
        cells = list(tr.find_all(["th", "td"]))
        while cells or col in carry:
            if col in carry:
                text, left = carry.pop(col)
                row[col] = text
                if left > 1:
                    carry[col] = (text, left - 1)
                col += 1
                continue
            cell = cells.pop(0)
            # some pages have malformed spans like colspan="2,"
            span = int(re.sub(r"\D", "", str(cell.get("colspan", 1))) or 1)
            down = int(re.sub(r"\D", "", str(cell.get("rowspan", 1))) or 1)
            wide = wide or span > 3
            text = clean(cell)
            for c in range(col, col + span):
                row[c] = text
                if down > 1:
                    carry[c] = (text, down - 1)
            col += span
        rows.append(None if wide else [row[c] for c in sorted(row)])
    return rows


def parse_dates(text, table_year):
    """
    "21-23 Oct", "30 Sep - 2 Oct", "28 Dec 2025 - 3 Jan 2026" -> (start, end).
    The end date takes the table's year unless the cell gives one; a start
    month later than the end month means the poll started the year before.
    """
    tokens = re.findall(r"\d{4}|\d{1,2}|[A-Za-z]{3,}", text)
    days, months, years = [], [], []
    for t in tokens:
        if len(t) == 4 and t.isdigit():
            years.append(int(t))
        elif t.isdigit():
            days.append(int(t))
        elif t[:3].lower() in MONTHS:
            months.append(MONTHS[t[:3].lower()])
    if not days or not months:
        return None
    end_year = years[-1] if years else table_year
    end = date(end_year, months[-1], days[-1])
    start_month = months[0] if len(months) > 1 else months[-1]
    start_year = years[0] if len(years) > 1 else (end_year - 1 if start_month > end.month else end_year)
    start = date(start_year, start_month, days[0])
    return start, end


def percent(text):
    """'30%' -> 30.0, '<1%' -> 0.5, '-' or '' -> None. Cells listing several parties are summed."""
    if "<1" in text:
        return 0.5
    numbers = re.findall(r"\d+(?:\.\d+)?(?=\s*%)", text) or re.findall(r"^\d+(?:\.\d+)?$", text)
    return sum(float(n) for n in numbers) if numbers else None


def pollster_name(text):
    """
    'More in Common  (MRP)' -> 'More in Common', 'Find Out Now/ Electoral Calculus' ->
    'Find Out Now': the firm that ran the fieldwork, so its MRPs share its house effect.
    """
    name = re.sub(r"\(MRP\)", "", text)
    name = name.split("/")[0]
    return re.sub(r"\s+", " ", name).strip()


def table_year(table):
    heading = table.find_previous(["h2", "h3", "h4"])
    while heading is not None:
        match = re.fullmatch(r"\s*(\d{4})\s*", heading.get_text())
        if match:
            return int(match.group(1))
        heading = heading.find_previous(["h2", "h3", "h4"])
    return None


def main():
    soup = BeautifulSoup(download(), "lxml")
    rows, dropped = [], []
    for table in soup.find_all("table", class_="wikitable"):
        header = [clean(c) for c in table.find("tr").find_all(["th", "td"])]
        if "Area" not in header or "Pollster" not in header:
            continue                              # a regional table
        year = table_year(table)
        col = {name: i for i, name in enumerate(header)}
        for cells in grid(table)[1:]:
            if cells is None or len(cells) != len(header):
                continue                          # a by-election or event row spanning the table
            if cells[col["Area"]] not in ("GB", "UK"):
                continue
            if "election" in cells[col["Pollster"]].lower() and not cells[col["Sample size"]]:
                continue                          # the 2024 result row
            dates = parse_dates(cells[col["Date(s) conducted"]], year)
            if not dates or dates[1] <= LAST_ELECTION:
                continue
            row = {
                "pollster": pollster_name(cells[col["Pollster"]]),
                "client": cells[col.get("Client", 0)] if "Client" in col else "",
                "area": cells[col["Area"]],
                "start_date": dates[0].isoformat(),
                "end_date": dates[1].isoformat(),
                "sample_size": int(re.sub(r"\D", "", cells[col["Sample size"]]) or DEFAULT_SAMPLE_SIZE),
                "mrp": int("MRP" in cells[col["Pollster"]]),
            }
            for p in PARTIES:
                row[p] = percent(cells[col[p]]) if p in col else None
            # everything else that isn't a party we track counts as Other
            other_columns = [name for name in header
                             if name not in PARTIES and name not in
                             ("Date(s) conducted", "Pollster", "Client", "Area", "Sample size", "Lead")]
            row["Oth"] = sum(percent(cells[col[name]]) or 0 for name in other_columns)
            total = sum(row[p] or 0 for p in PARTIES) + row["Oth"]
            if abs(total - 100) > SUM_TOLERANCE:
                dropped.append(f"{row['end_date']} {row['pollster']} (adds to {total:g})")
                continue
            rows.append(row)

    rows.sort(key=lambda r: (r["end_date"], r["pollster"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} polls ({rows[0]['end_date']} to {rows[-1]['end_date']}) to {OUT}")
    if dropped:
        print(f"Dropped {len(dropped)} that didn't add up:", "; ".join(dropped))


if __name__ == "__main__":
    main()
