"""
YouGov's tactical-voting study: "imagine the only two parties that appeared
to have a chance of winning in your constituency were X and Y - how would
you vote?", for ten pairings, by current Westminster vote intention.
Written to uk/data/yougov_tactical.csv, which tactical.py uses.

Source: YouGov's published results tables (the PDF linked from each
"What is the tactical voting landscape in <month>?" article). Default:
September 2026, fieldwork 15-22 September 2026, 6,077 GB adults - the first
run of the study under Andy Burnham.

Needs pypdf (pip install pypdf). Run it with:
    python uk/fetch_yougov_tactical.py [pdf path or URL]
"""

import csv
import io
import os
import re
import sys
import urllib.request

from pypdf import PdfReader

DEFAULT = "https://ygo-assets-websites-editorial-emea.yougov.net/documents/TacticalVoting_Merge_results_260922_w.pdf"
OUT = os.path.join(os.path.dirname(__file__), "data", "yougov_tactical.csv")

PARTY = {"Conservatives": "Con", "Conservative": "Con", "Labour": "Lab", "Liberal Democrats": "LD",
         "Liberal Democrat": "LD", "Reform UK": "Ref", "Greens": "Grn", "Green": "Grn",
         "Scottish National Party (SNP)": "SNP", "Plaid Cymru": "PC", "Some other party": "Oth",
         "Would not vote": "none", "Don't know": "dk", "Refused": "dk"}
# Column order after the two "Total" columns (previous run, this run): current vote intention
VOTERS = ["Con", "Lab", "LD", "Ref", "Grn"]


def read(source):
    if source.startswith("http"):
        req = urllib.request.Request(source, headers={"User-Agent": "senate-forecast/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            source = io.BytesIO(resp.read())
    reader = PdfReader(source)
    return "\n".join(page.extract_text() for page in reader.pages)


def contest(question):
    """'... were Reform UK and the Conservatives. If ...' -> ('Ref', 'Con')."""
    m = re.search(r"chance of winning were (?:the )?(.+?) and (?:the )?(.+?)\. If", question)
    return PARTY[m.group(1).strip()], PARTY[m.group(2).strip()]


def main(source=DEFAULT):
    lines = [l.strip() for l in read(source).splitlines()]
    fieldwork = next(l for l in lines if l.startswith("Fieldwork"))
    rows, i = [], 0
    while i < len(lines):
        if "only two parties" not in lines[i]:
            i += 1
            continue
        j = i
        while "If that were the case" not in " ".join(lines[i:j + 1]):
            j += 1
        a, b = contest(" ".join(lines[i - 1:j + 2]))
        k = j + 1
        block = []
        while k < len(lines) and not lines[k].startswith("Refused"):
            block.append(lines[k])
            k += 1
        block.append(lines[k] if k < len(lines) else "")
        for line in block:
            m = re.match(r"^(\D+?)\s+([\d\s]+)$", line)
            if not m or m.group(1).strip() not in PARTY:
                continue
            numbers = [int(x) for x in m.group(2).split()]
            if len(numbers) < 2 + len(VOTERS):
                continue                     # a continuation page with totals only
            choice = PARTY[m.group(1).strip()]
            for voters, pct in zip(VOTERS, numbers[2:2 + len(VOTERS)]):
                rows.append({"contest_a": a, "contest_b": b, "voters": voters, "choice": choice, "pct": pct})
        i = k + 1

    # combine "Don't know" and "Refused"; one row per (contest, voters, choice)
    merged = {}
    for r in rows:
        key = (r["contest_a"], r["contest_b"], r["voters"], r["choice"])
        merged[key] = merged.get(key, 0) + r["pct"]
    out = [{"contest_a": a, "contest_b": b, "voters": v, "choice": c, "pct": p} for (a, b, v, c), p in merged.items()]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)
    contests = sorted({(r["contest_a"], r["contest_b"]) for r in out})
    print(f"{fieldwork}: {len(contests)} contests -> {OUT}")
    for a, b in contests:
        cells = {(r["voters"], r["choice"]): r["pct"] for r in out if (r["contest_a"], r["contest_b"]) == (a, b)}
        print(f"  {a} v {b}: " + "; ".join(
            f"{v} voters {cells.get((v, a), 0)}/{cells.get((v, b), 0)}" for v in VOTERS))


if __name__ == "__main__":
    main(*sys.argv[1:])
