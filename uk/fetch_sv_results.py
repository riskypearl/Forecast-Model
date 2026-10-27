"""
Real supplementary-vote counts, saved to uk/data/sv_2021.csv, one row per
candidate: first-choice votes, second-choice transfers received (finalists
only), and whether they were a finalist. Two kinds of contest ("kind"):

  mayor  the 2021 and 2022 mayoral elections - combined-authority mayors
         (London, West Midlands, West Yorkshire ...) and single-council
         mayors - the closest match to the Sussex & Brighton mayoralty
  pcc    the 6 May 2021 police and crime commissioner elections (plus the
         August 2021 Wiltshire re-run): more contests, but lower-profile
         races with more independents, so used only as a cross-check

These are what the Sussex mayoral model's second-choice step is calibrated
on: given the eliminated candidates' first-choice votes, how many second
choices actually reached each finalist. (Mayoral elections switched to
first past the post from 2023.)

Source: Wikipedia (CC BY-SA 4.0), via the MediaWiki API.

Run it with:  python uk/fetch_sv_results.py
"""

import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup

import fetch_polls as fp

PCC_PAGE = "2021 England and Wales police and crime commissioner elections"
MAYOR_PAGES = [
    "2021 London mayoral election", "2021 West Midlands mayoral election", "2021 Greater Manchester mayoral election",
    "2021 West Yorkshire mayoral election", "2021 Liverpool City Region mayoral election",
    "2021 Cambridgeshire and Peterborough mayoral election", "2021 West of England mayoral election",
    "2021 Tees Valley mayoral election", "2022 South Yorkshire mayoral election",
    "2021 Bristol mayoral election", "2021 Liverpool mayoral election", "2021 Salford mayoral election",
    "2021 Doncaster mayoral election", "2021 North Tyneside mayoral election",
    "2022 Croydon mayoral election", "2022 Hackney mayoral election", "2022 Lewisham mayoral election",
    "2022 Newham mayoral election", "2022 Tower Hamlets mayoral election", "2022 Watford mayoral election",
]
OUT = os.path.join(os.path.dirname(__file__), "data", "sv_2021.csv")


def party(label):
    label = re.sub(r"\s+", " ", label)
    for key, code in (("Conservative", "Con"), ("Labour", "Lab"), ("Liberal", "LD"), ("Green", "Grn"),
                      ("Reform", "Ref"), ("Brexit", "Ref"), ("Plaid", "PC")):
        if key in label:
            return code
    return "Oth"


def download(page, tries=5):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "parse", "page": page, "prop": "text", "format": "json", "formatversion": 2, "redirects": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "senate-forecast/0.1 (personal research project)"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp).get("parse", {}).get("text")
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))        # Wikipedia rate limit: back off and retry


def number(text):
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def parse(table, area, kind="pcc"):
    rows = [r for r in fp.grid(table) if r]
    header = next((i for i, r in enumerate(rows) if "Candidate" in r), None)
    if header is None:
        return []
    two_rounds = any("Transfers" in r for r in rows[header:header + 2])
    start = header + (2 if two_rounds else 1)
    out = []
    for r in rows[start:]:
        if len(r) < 4 or not r[2] or r[1].startswith(("Rejected", "Total", "Turnout", "Majority", "Registered")):
            continue
        first = number(r[3])
        if first is None:
            continue
        transfers = number(r[5]) if two_rounds and len(r) > 5 else None
        out.append({"kind": kind, "area": area, "party": party(r[1]), "candidate": r[2].replace("*", "").strip(),
                    "first": first, "transfers": transfers if transfers is not None else "",
                    "finalist": int(two_rounds and transfers is not None), "two_rounds": 0})
    # it only went to second choices if two finalists actually received transfers
    went = sum(r["finalist"] for r in out) == 2
    for r in out:
        r["two_rounds"] = int(went)
        r["finalist"] = int(went and r["finalist"])
    return out


def main():
    rows = []
    soup = BeautifulSoup(download(PCC_PAGE), "lxml")
    for table in soup.find_all("table"):
        heading = table.find_previous(["h3", "h4"])
        area = heading.get_text(strip=True) if heading else ""
        if not area or area in ("Results summary", "England", "Wales", "Notes", "Greater Manchester Police",
                                "Metropolitan Police"):
            continue                              # GM and London's PCC roles belong to their mayors
        rows += parse(table, area, "pcc")

    for page in MAYOR_PAGES:
        time.sleep(1)
        html = download(page)
        if not html:
            print("Not found:", page)
            continue
        # The overall result: a table of 3+ candidates, preferring one with a second round, then the
        # one with the most first-choice votes (not ward or borough breakdowns). Any single cell over
        # 10 million is a garbled merged number, not a vote count.
        tables = [parse(t, page, "mayor") for t in BeautifulSoup(html, "lxml").find_all("table")]
        tables = [t for t in tables if len(t) >= 3 and max(r["first"] for r in t) < 10_000_000]
        if tables:
            rows += max(tables, key=lambda t: (t[0]["two_rounds"], sum(r["first"] for r in t)))

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    for kind in ("mayor", "pcc"):
        areas = {r["area"] for r in rows if r["kind"] == kind}
        runoffs = {r["area"] for r in rows if r["kind"] == kind and r["two_rounds"]}
        print(f"{kind}: {len(areas)} contests, {len(runoffs)} went to second choices")
    print(f"Saved {len(rows)} candidates to {OUT}")


if __name__ == "__main__":
    main()
