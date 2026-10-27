"""
The Sussex mayoral adjustment: how a 2028 Sussex & Brighton mayoral first
round should differ from the general-election model's Sussex shares.
Three measured pieces, added together:

1. National local gap (local_gap.py): every party's local-election result
   (BBC Projected National Share) against its Westminster polls,
   2012-2026. Being in government or years into a term made no measurable
   difference, so each party's average gap is used; its year-to-year spread
   is the uncertainty.
2. Mayoral vs local: what's left once that year's local gap is taken out of
   the May 2024 and May 2025 mayoral results (mayor_vs_ge.py). Area-wide
   mayoral races squeeze parties with patchy local strength. The spread
   between the 16 areas is the candidate / local uncertainty.
3. Sussex's own local pattern: how Sussex's councils vote against the
   national local picture, beyond what Sussex's general-election result
   already explains -
       (Sussex council share - national PNS) - (Sussex GE share - national GE share)
   - in West Sussex, East Sussex and Brighton & Hove, at two points: the
   2026 county elections (Brighton & Hove 2023) against the 2024 general
   election, and 2021 (Brighton & Hove 2019) against 2019. Their average is
   used, and how far the two disagree is its uncertainty.

Run it with:  python uk/mayoral_adjustment.py
              (after fetch_poll_history.py, local_gap.py and mayor_vs_ge.py)
Writes uk/data/mayoral_adjustment.csv, which sussex_mayor.py uses.
"""

import csv
import os
import time
from collections import Counter

import numpy as np
from bs4 import BeautifulSoup

import fetch_polls as fp
import fetch_sv_results as sv
import local_gap as lg
import mayor_vs_ge as mg

HERE = os.path.dirname(__file__)
PARTIES = ["Lab", "Con", "Ref", "LD", "Grn"]
OUT = os.path.join(HERE, "data", "mayoral_adjustment.csv")

# Reform barely stood in the 2024 local elections (PNS 2%), so that year says
# nothing about its local gap.
SKIP_GAP = {(2024, "Ref")}

# Sussex council elections: (area level, area name as in the ONS lookup, Wikipedia page title, year).
# The counties and the twelve district / borough councils each cover all of Sussex outside
# Brighton & Hove, at different elections; Brighton & Hove is a unitary council.
# Whole-council elections only: Adur, Crawley, Worthing and Hastings elect by thirds or halves,
# so only some wards vote each time, and comparing that with the whole area's general
# election is meaningless (Crawley 2019 came out Labour +28).
DISTRICTS = {"Arun": "Arun District", "Chichester": "Chichester District", "Horsham": "Horsham District",
             "Mid Sussex": "Mid Sussex District", "Eastbourne": "Eastbourne Borough",
             "Lewes": "Lewes District", "Rother": "Rother District", "Wealden": "Wealden District"}
SUSSEX_LOCAL = (
    [("utla", c, f"{y} {c} County Council election", y) for c in ("West Sussex", "East Sussex") for y in (2021, 2026)]
    + [("utla", "Brighton and Hove", f"{y} Brighton and Hove City Council election", y) for y in (2019, 2023)]
    + [("lad", lad, f"{y} {name} Council election", y) for lad, name in DISTRICTS.items() for y in (2019, 2023)]
)
# General election each local election is compared with (both on today's boundaries)
GE_FOR = {2019: "results_2019_notional.csv", 2021: "results_2019_notional.csv",
          2023: "results_2024.csv", 2026: "results_2024.csv"}
# Recent elections count for more: weight halves every this many years before 2026
RECENCY_HALF_LIFE = 5


def party_of(label):
    """Council results label -> our party. UKIP was Reform's predecessor; 'Labour Co-op' is Labour."""
    if "UK Independence" in label or label.strip() == "UKIP":
        return "Ref"
    return sv.party(label)


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def national_gap():
    rows = [r for r in read(os.path.join(HERE, "data", "local_gap.csv"))
            if (int(r["year"]), r["party"]) not in SKIP_GAP]
    out = {}
    for p in PARTIES:
        gaps = [float(r["gap"]) for r in rows if r["party"] == p]
        out[p] = (float(np.mean(gaps)), float(np.std(gaps)), len(gaps))
    return out


def gap_in(year):
    return {r["party"]: float(r["gap"]) for r in read(os.path.join(HERE, "data", "local_gap.csv"))
            if int(r["year"]) == year and (year, r["party"]) not in SKIP_GAP}


def general_shares(filename, codes=None, names=None):
    rows = [r for r in read(os.path.join(HERE, "data", filename)) if r["country"] != "Northern Ireland"]
    if codes is not None:
        rows = [r for r in rows if r["ons_code"] in codes]
    if names is not None:
        rows = [r for r in rows if r["name"] in names]
    votes = Counter()
    for r in rows:
        for p in PARTIES:
            votes[p] += int(r[f"{p}_votes"])
        votes["all"] += sum(int(r[f"{q}_votes"]) for q in ["Lab", "Con", "Ref", "LD", "Grn", "SNP", "PC", "Oth"])
    return {p: 100 * votes[p] / votes["all"] for p in PARTIES}, votes["all"]


def mayoral_residuals():
    """Per area and party: mayoral first round minus the model at the time minus that year's local gap."""
    out = []
    # 2025: the model was run on polling day (mayor_vs_ge.test_2025)
    gap = gap_in(2025)
    for r in read(os.path.join(HERE, "data", "mayor_vs_model_2025.csv")):
        out.append({p: float(r[p]) - gap[p] for p in PARTIES if p in gap} | {"area": r["area"], "year": 2025})
    # 2024: compared with the July general election, so also take out how far the national
    # result moved from the May polls (polls 3 weeks before 2 May 2024 vs the GB result)
    polls = [{"end_date": __import__("datetime").date.fromisoformat(r["end_date"]),
              **{p: float(r[p]) if r[p] else None for p in PARTIES}}
             for r in read(os.path.join(HERE, "data", "poll_history.csv"))]
    may, _ = lg.poll_average(polls, lg.LOCAL_DAY[2024])
    result, _ = general_shares("results_2024.csv")
    gap = gap_in(2024)
    for r in read(os.path.join(HERE, "data", "mayor_vs_ge_2024.csv")):
        out.append({p: float(r[f"{p}_diff"]) - (may[p] - result[p]) - gap[p] for p in PARTIES if p in gap}
                   | {"area": r["area"], "year": 2024})
    return out


def council_shares(page):
    time.sleep(1)
    soup = BeautifulSoup(sv.download(page), "lxml")
    for table in soup.find_all("table"):
        rows = [r for r in fp.grid(table) if r]
        header = rows[0] if rows else []
        if "Votes" not in header or "Party" not in header:
            continue
        col = header.index("Votes")
        votes = Counter()
        for r in rows[1:]:
            if len(r) <= col or not r[col].replace(",", "").isdigit():
                continue
            votes[party_of(r[1])] += int(r[col].replace(",", ""))
        if votes:
            total = sum(votes.values())
            return {p: 100 * votes[p] / total for p in PARTIES}, votes
    raise ValueError(f"No results table on {page}")


def area_general_shares(filename, level, name):
    """
    General-election shares (%) and votes in a council area. Constituencies don't follow district
    boundaries, so each constituency's votes are split evenly across its wards (ONS lookup) and
    the wards in the area are added up.
    """
    rows = {r["ons_code"]: r for r in read(os.path.join(HERE, "data", filename))}
    with open(mg.LOOKUP, newline="", encoding="utf-8-sig") as f:
        wards = list(csv.DictReader(f))
    per_seat = Counter(w["PCON24CD"] for w in wards)
    votes = Counter()
    for w in wards:
        if (w["LAD24NM"] if level == "lad" else w["UTLA24NM"]) != name or w["PCON24CD"] not in rows:
            continue
        r, share = rows[w["PCON24CD"]], 1 / per_seat[w["PCON24CD"]]
        for p in PARTIES + ["SNP", "PC", "Oth"]:
            if p in PARTIES or p == "Oth":
                votes[p] += share * int(r[f"{p}_votes"])
            votes["all"] += share * int(r[f"{p}_votes"])
    return {p: 100 * votes[p] / votes["all"] for p in PARTIES}, votes["all"]


def sussex_local():
    """
    {party: [(year, Sussex-wide effect that year, total weight)]}: for every Sussex council election,
    (council share - national PNS) - (area GE share - national GE share), averaged over the areas
    voting that year, weighted by their general-election votes.
    """
    pns = {int(r["year"]): {p: float(r[p]) if r[p] else None for p in PARTIES}
           for r in read(os.path.join(HERE, "data", "pns.csv"))}
    nat = {f: general_shares(f)[0] for f in set(GE_FOR.values())}
    by_year = {}
    print("\nSussex's own local pattern: (council - national PNS) - (area GE - national GE), points")
    for level, name, page, year in SUSSEX_LOCAL:
        try:
            council, votes = council_shares(page)
        except Exception as e:
            print(f"  {name:18} {year}: no results ({str(e)[:50]})")
            continue
        ge, weight = area_general_shares(GE_FOR[year], level, name)
        effects = {p: (council[p] - pns[year][p]) - (ge[p] - nat[GE_FOR[year]][p]) for p in PARTIES
                   if pns[year][p] is not None and council[p] >= 1}      # in the PNS that year, and stood
        for p, e in effects.items():
            by_year.setdefault((p, year), []).append((e, weight))
        print(f"  {name:18} {year}: " + "  ".join(f"{p} {e:+.1f}" for p, e in effects.items()))
    out = {p: [] for p in PARTIES}
    for (p, year), values in by_year.items():
        out[p].append((year, float(np.average([e for e, _ in values], weights=[w for _, w in values])),
                       sum(w for _, w in values)))
    return out


def main():
    gap = national_gap()
    residuals = mayoral_residuals()
    local = sussex_local()

    rows = []
    print(f"\n{'':5}{'local gap':>12}{'mayoral':>12}{'Sussex':>12}{'total':>9}{'SD':>6}")
    for p in PARTIES:
        g_mean, g_sd, _ = gap[p]
        r = [x[p] for x in residuals if p in x]
        m_mean, m_sd = float(np.mean(r)), float(np.std(r))
        # Sussex: every election year's Sussex-wide effect, recent years weighted more; the spread
        # between years is the uncertainty (one year only: 3 points)
        years = sorted(local[p])
        recency = np.array([0.5 ** ((2026 - y) / RECENCY_HALF_LIFE) for y, _, _ in years])
        effects = np.array([e for _, e, _ in years])
        s_mean = float(np.average(effects, weights=recency)) if len(years) else 0.0
        s_sd = float(np.sqrt(np.average((effects - s_mean) ** 2, weights=recency))) if len(years) > 1 else 3.0
        snaps = {str(y): e for y, e, _ in years}
        snap_means = list(snaps.values())
        total = g_mean + m_mean + s_mean
        sd = float(np.sqrt(g_sd ** 2 + m_sd ** 2 + s_sd ** 2))
        rows.append({"party": p, "local_gap": round(g_mean, 2), "local_gap_sd": round(g_sd, 2),
                     "mayoral": round(m_mean, 2), "mayoral_sd": round(m_sd, 2),
                     "sussex": round(s_mean, 2), "sussex_sd": round(s_sd, 2),
                     "sussex_snapshots": " / ".join(f"{k} {v:+.1f}" for k, v in zip(snaps, snap_means)),
                     "total": round(total, 2), "sd": round(sd, 2)})
        print(f"{p:5}{g_mean:+9.1f}±{g_sd:<3.1f}{m_mean:+8.1f}±{m_sd:<3.1f}{s_mean:+8.1f}±{s_sd:<3.1f}{total:+8.1f}{sd:6.1f}"
              f"   (Sussex {rows[-1]['sussex_snapshots']})")
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    # each area's own residuals, so a forecast can draw a real area's whole pattern (a strong
    # candidate for one party comes with weaker results for the others)
    with open(os.path.join(HERE, "data", "mayoral_residuals.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["year", "area"] + PARTIES)
        writer.writeheader()
        writer.writerows({"year": r["year"], "area": r["area"], **{p: round(r.get(p, 0.0), 2) for p in PARTIES}}
                         for r in residuals)
    # Independents and other parties: how far their mayoral share ran from the general-election
    # picture in each 2024 and 2025 area. Lumpy - mostly a few points, occasionally a Jamie
    # Driscoll (North East 2024, +25) - so forecasts draw one real area's value, not a bell curve.
    others = [{"year": 2024, "area": r["area"], "shift": float(r["Oth_diff"])}
              for r in read(os.path.join(HERE, "data", "mayor_vs_ge_2024.csv"))]
    others += [{"year": 2025, "area": r["area"], "shift": float(r["Oth"])}
               for r in read(os.path.join(HERE, "data", "mayor_vs_model_2025.csv"))]
    with open(os.path.join(HERE, "data", "other_shifts.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["year", "area", "shift"])
        writer.writeheader()
        writer.writerows(others)
    values = np.array([o["shift"] for o in others])
    print(f"\nOther / independents, mayoral minus GE picture, {len(values)} areas: median {np.median(values):+.1f}, "
          f"90% of areas {np.percentile(values, 5):+.1f} to {np.percentile(values, 95):+.1f}, largest {values.max():+.1f}")
    print(f"Saved to {OUT}, data/mayoral_residuals.csv and data/other_shifts.csv")


if __name__ == "__main__":
    main()
