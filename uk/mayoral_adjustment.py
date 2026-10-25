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

# Sussex councils: (Wikipedia page, national PNS year, general election to compare with)
SUSSEX_LOCAL = {
    "West Sussex": [("2026 West Sussex County Council election", 2026, 2024),
                    ("2021 West Sussex County Council election", 2021, 2019)],
    "East Sussex": [("2026 East Sussex County Council election", 2026, 2024),
                    ("2021 East Sussex County Council election", 2021, 2019)],
    "Brighton and Hove": [("2023 Brighton and Hove City Council election", 2023, 2024),
                          ("2019 Brighton and Hove City Council election", 2019, 2019)],
}
# 2010-2024 boundaries (for the 2019 general election), by council area
OLD_SEATS = {
    "West Sussex": ["Arundel and South Downs", "Bognor Regis and Littlehampton", "Chichester", "Crawley",
                    "East Worthing and Shoreham", "Horsham", "Mid Sussex", "Worthing West"],
    "East Sussex": ["Bexhill and Battle", "Eastbourne", "Hastings and Rye", "Lewes", "Wealden"],
    "Brighton and Hove": ["Brighton, Kemptown", "Brighton, Pavilion", "Hove"],
}
COUNCIL_PARTY = {"Labour": "Lab", "Conservative": "Con", "Reform": "Ref", "Reform UK": "Ref",
                 "Liberal Democrat": "LD", "Liberal Democrats": "LD", "Green": "Grn"}


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
            votes[COUNCIL_PARTY.get(r[1].strip(), "Oth")] += int(r[col].replace(",", ""))
        if votes:
            total = sum(votes.values())
            return {p: 100 * votes[p] / total for p in PARTIES}, votes
    raise ValueError(f"No results table on {page}")


def sussex_local():
    """{party: [(area, year, effect, weight)]}"""
    pns = {int(r["year"]): {p: float(r[p]) if r[p] else None for p in PARTIES}
           for r in read(os.path.join(HERE, "data", "pns.csv"))}
    nat = {2024: general_shares("results_2024.csv")[0], 2019: general_shares("results_2019.csv")[0]}
    new_seats = mg.constituencies({area: {"utlas": [area]} for area in SUSSEX_LOCAL})
    out = {p: [] for p in PARTIES}
    print("\nSussex's own local pattern: (council - national PNS) - (Sussex GE - national GE), points")
    for area, elections in SUSSEX_LOCAL.items():
        for page, pns_year, ge_year in elections:
            council, votes = council_shares(page)
            if ge_year == 2024:
                ge, weight = general_shares("results_2024.csv", codes=new_seats[area])
            else:
                ge, weight = general_shares("results_2019.csv", names=OLD_SEATS[area])
            effects = {}
            for p in PARTIES:
                if pns[pns_year][p] is None or votes[p] == 0 or council[p] < 1:
                    continue                      # not in the PNS that year, or (near enough) didn't stand
                effects[p] = (council[p] - pns[pns_year][p]) - (ge[p] - nat[ge_year][p])
                out[p].append((area, pns_year, effects[p], weight))
            print(f"  {area:18} {pns_year}: " + "  ".join(f"{p} {e:+.1f}" for p, e in effects.items()))
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
        # Sussex: average of the two snapshots (each a vote-weighted average over the three areas)
        snaps = {}
        for area, year, effect, weight in local[p]:
            snap = "recent" if year >= 2023 else "earlier"
            snaps.setdefault(snap, []).append((effect, weight))
        snap_means = [np.average([e for e, _ in v], weights=[w for _, w in v]) for v in snaps.values()]
        s_mean = float(np.mean(snap_means)) if snap_means else 0.0
        s_sd = float(abs(snap_means[0] - snap_means[1]) / 2) if len(snap_means) == 2 else 3.0
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
