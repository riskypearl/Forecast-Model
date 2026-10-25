"""
Katy Bourne's personal vote. She has been the Conservative candidate for
Sussex Police and Crime Commissioner at every election - 2012, 2016, 2021
(supplementary vote) and 2024 (first past the post) - so Sussex-wide, the
same electorate as the 2028 mayoralty.

Measured as a difference-in-differences, so national swing and anything
special about PCC elections cancel out. In each year, for every English
police force area:

    gap = Conservative PCC first-choice share - Conservative general-election share there

and Bourne's edge = Sussex's gap - the average gap of all the other
Conservative PCC candidates that year. The spread of the other candidates'
gaps shows how much ordinary candidates differ, i.e. whether her edge is
distinguishable from noise.

General-election shares: July 2024 for the May 2024 PCCs; the 2019
notional results (on today's boundaries) for 2012, 2016 and 2021 - exact
for 2021, approximate for the earlier years.

Run it with:  python uk/bourne_effect.py
Writes uk/data/bourne_effect.csv; sussex_mayor.py uses it.
"""

import csv
import os
import time
from collections import Counter

import numpy as np
from bs4 import BeautifulSoup

import fetch_sv_results as sv
import mayor_vs_ge as mg

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "data", "bourne_effect.csv")
YEARS = {2012: "results_2019_notional.csv", 2016: "results_2019_notional.csv",
         2021: "results_2019_notional.csv", 2024: "results_2024.csv"}

# English police force areas (London and Greater Manchester have their mayors instead)
FORCES = {
    "Avon and Somerset": ["Bath and North East Somerset", "Bristol, City of", "North Somerset", "South Gloucestershire", "Somerset"],
    "Bedfordshire": ["Bedford", "Central Bedfordshire", "Luton"],
    "Cambridgeshire": ["Cambridgeshire", "Peterborough"],
    "Cheshire": ["Cheshire East", "Cheshire West and Chester", "Halton", "Warrington"],
    "Cleveland": ["Hartlepool", "Middlesbrough", "Redcar and Cleveland", "Stockton-on-Tees"],
    "Cumbria": ["Cumberland", "Westmorland and Furness"],
    "Derbyshire": ["Derby", "Derbyshire"],
    "Devon and Cornwall": ["Cornwall", "Devon", "Plymouth", "Torbay", "Isles of Scilly"],
    "Dorset": ["Bournemouth, Christchurch and Poole", "Dorset"],
    "Durham": ["County Durham", "Darlington"],
    "Essex": ["Essex", "Southend-on-Sea", "Thurrock"],
    "Gloucestershire": ["Gloucestershire"],
    "Hampshire": ["Hampshire", "Portsmouth", "Southampton", "Isle of Wight"],
    "Hertfordshire": ["Hertfordshire"],
    "Humberside": ["East Riding of Yorkshire", "Kingston upon Hull, City of", "North Lincolnshire", "North East Lincolnshire"],
    "Kent": ["Kent", "Medway"],
    "Lancashire": ["Lancashire", "Blackburn with Darwen", "Blackpool"],
    "Leicestershire": ["Leicester", "Leicestershire", "Rutland"],
    "Lincolnshire": ["Lincolnshire"],
    "Merseyside": ["Liverpool", "Knowsley", "Sefton", "St. Helens", "Wirral"],
    "Norfolk": ["Norfolk"],
    "Northamptonshire": ["North Northamptonshire", "West Northamptonshire"],
    "Northumbria": ["Gateshead", "Newcastle upon Tyne", "North Tyneside", "Northumberland", "South Tyneside", "Sunderland"],
    "North Yorkshire": ["North Yorkshire", "York"],
    "Nottinghamshire": ["Nottingham", "Nottinghamshire"],
    "South Yorkshire": ["Barnsley", "Doncaster", "Rotherham", "Sheffield"],
    "Staffordshire": ["Staffordshire", "Stoke-on-Trent"],
    "Suffolk": ["Suffolk"],
    "Surrey": ["Surrey"],
    "Sussex": ["West Sussex", "East Sussex", "Brighton and Hove"],
    "Thames Valley": ["Bracknell Forest", "Buckinghamshire", "Milton Keynes", "Oxfordshire", "Reading", "Slough",
                      "West Berkshire", "Windsor and Maidenhead", "Wokingham"],
    "Warwickshire": ["Warwickshire"],
    "West Mercia": ["Herefordshire, County of", "Shropshire", "Telford and Wrekin", "Worcestershire"],
    "West Midlands": ["Birmingham", "Coventry", "Dudley", "Sandwell", "Solihull", "Walsall", "Wolverhampton"],
    "West Yorkshire": ["Bradford", "Calderdale", "Kirklees", "Leeds", "Wakefield"],
    "Wiltshire": ["Swindon", "Wiltshire"],
}


def force_of(heading):
    """'Sussex Police', 'Cambridgeshire Constabulary' ... -> our force name, or None."""
    for force in sorted(FORCES, key=len, reverse=True):
        if heading.startswith(force):
            return force
    return None


def pcc_results(year):
    """{force: (Conservative first-choice share %, Conservative candidate)}"""
    time.sleep(1)
    soup = BeautifulSoup(sv.download(f"{year} England and Wales police and crime commissioner elections"), "lxml")
    out = {}
    for table in soup.find_all("table"):
        heading = table.find_previous(["h3", "h4"])
        force = force_of(heading.get_text(strip=True)) if heading else None
        if not force or force in out:
            continue
        rows = sv.parse(table, force, "pcc")
        if not rows:
            continue
        total = sum(r["first"] for r in rows)
        con = [r for r in rows if r["party"] == "Con"]
        if con and total:
            out[force] = (100 * con[0]["first"] / total, con[0]["candidate"])
    return out


def general_con_shares(filename, seats):
    with open(os.path.join(HERE, "data", filename), newline="", encoding="utf-8") as f:
        rows = {r["ons_code"]: r for r in csv.DictReader(f)}
    out = {}
    for force, codes in seats.items():
        con = sum(int(rows[c]["Con_votes"]) for c in codes if c in rows)
        total = sum(sum(int(rows[c][f"{p}_votes"]) for p in ["Lab", "Con", "Ref", "LD", "Grn", "SNP", "PC", "Oth"])
                    for c in codes if c in rows)
        if total:
            out[force] = 100 * con / total
    return out


def main():
    seats = mg.constituencies({force: {"utlas": councils} for force, councils in FORCES.items()})
    missing = [f for f in FORCES if not seats.get(f)]
    if missing:
        print("No constituencies matched for:", missing)

    rows = []
    print(f"{'year':6}{'Bourne':>8}{'Con GE':>8}{'her gap':>9}{'others':>9}{'spread':>8}{'edge':>7}{'rank':>8}")
    for year, ge_file in YEARS.items():
        pcc = pcc_results(year)
        ge = general_con_shares(ge_file, seats)
        gaps = {f: pcc[f][0] - ge[f] for f in pcc if f in ge}
        if "Sussex" not in gaps:
            print(year, "no Sussex result found")
            continue
        others = np.array([g for f, g in gaps.items() if f != "Sussex"])
        edge = gaps["Sussex"] - others.mean()
        rank = 1 + int(np.sum(others > gaps["Sussex"]))
        rows.append({"year": year, "bourne_share": round(pcc["Sussex"][0], 1), "con_ge_share": round(ge["Sussex"], 1),
                     "gap": round(gaps["Sussex"], 1), "others_mean_gap": round(others.mean(), 1),
                     "others_sd": round(others.std(), 1), "edge": round(edge, 1), "rank": rank, "forces": len(gaps)})
        print(f"{year:<6}{pcc['Sussex'][0]:7.1f}%{ge['Sussex']:7.1f}%{gaps['Sussex']:+9.1f}{others.mean():+9.1f}"
              f"{others.std():8.1f}{edge:+7.1f}{f'{rank}/{len(gaps)}':>8}")

    edges = np.array([r["edge"] for r in rows])
    print(f"\nBourne's edge over a typical Conservative candidate: mean {edges.mean():+.1f} points "
          f"(years range {edges.min():+.1f} to {edges.max():+.1f}); other candidates' typical spread "
          f"{np.mean([r['others_sd'] for r in rows]):.1f}")
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()
