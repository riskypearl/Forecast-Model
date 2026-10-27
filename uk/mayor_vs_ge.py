"""
How do mayoral elections differ from general-election voting in the same
place? The May 2024 mayoral elections were held two months before the July
2024 general election, so the gap between the two in each area is mostly
the "mayoral effect" - lower turnout, candidates' personal votes, local
issues - rather than national change.

For each 2024 mayoral area, its constituencies (those with most of their
wards in the area's councils, from data/ward_pcon_lad_2024.csv, the ONS
July 2024 lookup) give the general-election shares; the mayoral first-round
shares come from Wikipedia. Writes uk/data/mayor_vs_ge_2024.csv.

Run it with:  python uk/mayor_vs_ge.py
"""

import csv
import os
import time
from collections import Counter, defaultdict

import numpy as np
from bs4 import BeautifulSoup

import fetch_sv_results as sv

HERE = os.path.dirname(__file__)
LOOKUP = os.path.join(HERE, "data", "ward_pcon_lad_2024.csv")
OUT = os.path.join(HERE, "data", "mayor_vs_ge_2024.csv")
PARTIES = ["Lab", "Con", "Ref", "LD", "Grn", "Oth"]

# 2024 mayoral areas: Wikipedia page -> the councils (LAD24 names, or upper-tier names) in it
AREAS = {
    "2024 London mayoral election": {"utla_prefix": "E09"},
    "2024 West Midlands mayoral election": {"lads": ["Birmingham", "Coventry", "Dudley", "Sandwell", "Solihull",
                                                     "Walsall", "Wolverhampton"]},
    "2024 Greater Manchester mayoral election": {"lads": ["Bolton", "Bury", "Manchester", "Oldham", "Rochdale", "Salford",
                                                          "Stockport", "Tameside", "Trafford", "Wigan"]},
    "2024 West Yorkshire mayoral election": {"lads": ["Bradford", "Calderdale", "Kirklees", "Leeds", "Wakefield"]},
    "2024 Liverpool City Region mayoral election": {"lads": ["Halton", "Knowsley", "Liverpool", "St. Helens", "Sefton",
                                                             "Wirral"]},
    "2024 South Yorkshire mayoral election": {"lads": ["Barnsley", "Doncaster", "Rotherham", "Sheffield"]},
    "2024 Tees Valley mayoral election": {"lads": ["Darlington", "Hartlepool", "Middlesbrough", "Redcar and Cleveland",
                                                   "Stockton-on-Tees"]},
    "2024 North East mayoral election": {"lads": ["County Durham", "Gateshead", "Newcastle upon Tyne", "North Tyneside",
                                                  "Northumberland", "South Tyneside", "Sunderland"]},
    "2024 East Midlands mayoral election": {"utlas": ["Derby", "Derbyshire", "Nottingham", "Nottinghamshire"]},
    "2024 York and North Yorkshire mayoral election": {"lads": ["York", "North Yorkshire"]},
}


# May 2025 mayoral elections: a real out-of-sample test of the whole model -
# polls as of polling day, swung onto each area, against the actual result.
AREAS_2025 = {
    "2025 Greater Lincolnshire mayoral election": {"utlas": ["Lincolnshire", "North Lincolnshire", "North East Lincolnshire"]},
    "2025 Hull and East Yorkshire mayoral election": {"utlas": ["Kingston upon Hull, City of", "East Riding of Yorkshire"]},
    "2025 Cambridgeshire and Peterborough mayoral election": {"utlas": ["Cambridgeshire", "Peterborough"]},
    "2025 West of England mayoral election": {"utlas": ["Bath and North East Somerset", "Bristol, City of", "South Gloucestershire"]},
    "2025 Doncaster mayoral election": {"lads": ["Doncaster"]},
    "2025 North Tyneside mayoral election": {"lads": ["North Tyneside"]},
}
POLLING_DAY_2025 = "2025-05-01"


def constituencies(areas=None):
    """{area page: set of PCON24 codes}: each constituency goes to the area holding most of its wards."""
    areas = AREAS if areas is None else areas
    wards = defaultdict(Counter)
    with open(LOOKUP, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            area = next((page for page, spec in areas.items()
                         if r["LAD24NM"] in spec.get("lads", []) or r["UTLA24NM"] in spec.get("utlas", [])
                         or ("utla_prefix" in spec and r["UTLA24CD"].startswith(spec["utla_prefix"]))), None)
            wards[r["PCON24CD"]][area] += 1
    out = defaultdict(set)
    for code, counts in wards.items():
        page, n = counts.most_common(1)[0]
        if page:
            out[page].add(code)
    return out


def shares(rows):
    total = sum(rows.values())
    return {p: 100 * rows.get(p, 0) / total for p in PARTIES}


def main():
    seats = constituencies()
    with open(os.path.join(HERE, "data", "results_2024.csv"), newline="", encoding="utf-8") as f:
        ge = {r["ons_code"]: r for r in csv.DictReader(f)}

    out = []
    for page in AREAS:
        time.sleep(1)
        tables = [sv.parse(t, page, "mayor") for t in BeautifulSoup(sv.download(page), "lxml").find_all("table")]
        tables = [t for t in tables if len(t) >= 3 and max(r["first"] for r in t) < 10_000_000]
        result = max(tables, key=lambda t: sum(r["first"] for r in t))
        mayor = Counter()
        for r in result:
            mayor[r["party"] if r["party"] in PARTIES else "Oth"] += r["first"]
        general = Counter()
        for code in seats[page]:
            for p in PARTIES:
                general[p] += int(ge[code][f"{p}_votes"])
            general["Oth"] += int(ge[code]["SNP_votes"]) + int(ge[code]["PC_votes"])
        m, g = shares(mayor), shares(general)
        winner = max(result, key=lambda r: r["first"])
        out.append({"area": page[5:-17], "seats": len(seats[page]), "winner": f"{winner['candidate']} ({winner['party']})",
                    **{f"{p}_mayor": round(m[p], 1) for p in PARTIES}, **{f"{p}_ge": round(g[p], 1) for p in PARTIES},
                    **{f"{p}_diff": round(m[p] - g[p], 1) for p in PARTIES}})

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)

    print("Mayoral first round (May 2024) minus general election (July 2024), same area, points:")
    print(f"{'area':28}{'seats':>6}  " + "".join(f"{p:>6}" for p in PARTIES) + "   winner")
    for r in out:
        print(f"{r['area'][:27]:28}{r['seats']:6d}  " + "".join(f"{r[f'{p}_diff']:+6.1f}" for p in PARTIES) + f"   {r['winner']}")
    print(f"{'average':28}{'':6}  " + "".join(f"{np.mean([r[f'{p}_diff'] for r in out]):+6.1f}" for p in PARTIES))
    print(f"{'spread (SD)':28}{'':6}  " + "".join(f"{np.std([r[f'{p}_diff'] for r in out]):6.1f}" for p in PARTIES))
    test_2025()


def area_result(page):
    tables = [sv.parse(t, page, "mayor") for t in BeautifulSoup(sv.download(page), "lxml").find_all("table")]
    tables = [t for t in tables if len(t) >= 3 and max(r["first"] for r in t) < 10_000_000]
    result = max(tables, key=lambda t: sum(r["first"] for r in t))
    votes = Counter()
    for r in result:
        votes[r["party"] if r["party"] in PARTIES else "Oth"] += r["first"]
    return shares(votes), max(result, key=lambda r: r["first"])


def test_2025():
    """The model's general-election-style shares on 1 May 2025 for each 2025 mayoral area, against the result."""
    from datetime import date
    import poll_average as pa
    import seat_model as sm

    rows, _ = sm.load_results("results_2024.csv")
    gb = [r for r in rows if r["speaker_seat"] != "1"]
    raw = sm.share_matrix(gb)
    base = sm.fill_new_candidates(raw, gb)
    weights = np.array([float(r["valid_votes"]) for r in gb])
    weights /= weights.sum()
    polls = pa.load_polls()
    day = date.fromisoformat(POLLING_DAY_2025)
    average, _ = pa.average(polls, pa.house_effects(polls), day)
    target = np.array([[average[p] for p in sm.PARTIES]]) / 100
    swung = sm.swing(base, weights, target, sm.seat_elasticity(gb, base))[0]
    index = {r["ons_code"]: i for i, r in enumerate(gb)}
    print(f"\nMay 2025 mayors: actual first round minus our model on {day:%d %b %Y} (polls swung onto each area), points")
    print(f"  (national average then: " + ", ".join(f"{p} {average[p]:.0f}" for p in PARTIES[:5]) + ")")
    print(f"{'area':28}{'seats':>6}  " + "".join(f"{p:>6}" for p in PARTIES) + "   winner")
    diffs = []
    for page, codes in constituencies(AREAS_2025).items():
        time.sleep(1)
        i = [index[c] for c in codes if c in index]
        w = np.array([float(gb[k]["valid_votes"]) for k in i])
        model = (w @ swung[i]) / w.sum()
        model = {p: 100 * (model[sm.PARTIES.index(p)] + (model[sm.PARTIES.index("SNP")] + model[sm.PARTIES.index("PC")]
                                                         if p == "Oth" else 0)) for p in PARTIES}
        actual, winner = area_result(page)
        d = {p: actual[p] - model[p] for p in PARTIES}
        diffs.append({"area": page[5:-17], **{k: round(v, 2) for k, v in d.items()}})
        print(f"{page[5:-17][:27]:28}{len(i):6d}  " + "".join(f"{d[p]:+6.1f}" for p in PARTIES)
              + f"   {winner['candidate']} ({winner['party']})")
    print(f"{'average':28}{'':6}  " + "".join(f"{np.mean([d[p] for d in diffs]):+6.1f}" for p in PARTIES))
    print(f"{'spread (SD)':28}{'':6}  " + "".join(f"{np.std([d[p] for d in diffs]):6.1f}" for p in PARTIES))
    with open(os.path.join(HERE, "data", "mayor_vs_model_2025.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(diffs[0].keys()))
        writer.writeheader()
        writer.writerows(diffs)


if __name__ == "__main__":
    main()
