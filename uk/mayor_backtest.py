"""
Backtest the Sussex mayoral method on the mayoral elections that used the
supplementary vote: May 2021 (and May 2022 for South Yorkshire and the
London boroughs). Each contest is forecast with what was known on polling
day, run 10,000 times, and scored: did it pick the winner, how far off were
the first-choice shares, and did the real result land inside the 90% range?

What the forecast gets (as in sussex_mayor.py):
  - baseline: the 2019 general election (notional results on today's
    boundaries, so the ONS ward lookup assigns seats to each mayoral area)
  - national polls: the 3 weeks before polling day, with a polling miss
  - demographic swing fitted on 2010-2019 only
  - national local gap from local elections up to the year before only
  - mayoral-vs-local residuals: one real 2024/25 mayoral area drawn whole
    per run (these only exist for 2024-25 - later data, so not out of sample)
  - each area's own local pattern: unknown here, so noise of the size
    measured for Sussex
  - independents / others: one real 2024/25 mayoral area's shift per run
    (data/other_shifts.csv) - measured on later contests, so 2021-22 is a
    fair test of it
  - the second count, at YouGov's rates as calibrated - on these same
    contests, so that step is in sample; the first round is the real test
No poll movement is added: it's polling day.

Bristol 2021 is left out: its Wikipedia page lists several elections and
the scraper picked the wrong one (2016).

Run it with:  python uk/mayor_backtest.py
"""

import csv
import os
from collections import Counter, defaultdict
from datetime import date

import numpy as np

import local_gap as lg
import mayor_vs_ge as mg
import seat_model as sm
import sussex_mayor as sx
import swing_regression as sr
import tactical as tactics

HERE = os.path.dirname(__file__)
PARTIES = sm.PARTIES
MAIN = ["Lab", "Con", "Ref", "LD", "Grn"]
SIMULATIONS = 10_000

AREAS = {
    "2021 London mayoral election": {"utla_prefix": "E09"},
    "2021 West Midlands mayoral election": mg.AREAS["2024 West Midlands mayoral election"],
    "2021 Greater Manchester mayoral election": mg.AREAS["2024 Greater Manchester mayoral election"],
    "2021 West Yorkshire mayoral election": mg.AREAS["2024 West Yorkshire mayoral election"],
    "2021 Liverpool City Region mayoral election": mg.AREAS["2024 Liverpool City Region mayoral election"],
    "2021 Tees Valley mayoral election": mg.AREAS["2024 Tees Valley mayoral election"],
    "2021 Cambridgeshire and Peterborough mayoral election": {"utlas": ["Cambridgeshire", "Peterborough"]},
    "2021 West of England mayoral election": {"utlas": ["Bath and North East Somerset", "Bristol, City of",
                                                        "South Gloucestershire"]},
    "2022 South Yorkshire mayoral election": mg.AREAS["2024 South Yorkshire mayoral election"],
    "2021 Salford mayoral election": {"lads": ["Salford"]},
    "2021 Doncaster mayoral election": {"lads": ["Doncaster"]},
    "2021 North Tyneside mayoral election": {"lads": ["North Tyneside"]},
    "2022 Croydon mayoral election": {"lads": ["Croydon"]},
    "2022 Newham mayoral election": {"lads": ["Newham"]},
    "2022 Tower Hamlets mayoral election": {"lads": ["Tower Hamlets"]},
}
POLLING_DAY = {2021: date(2021, 5, 6), 2022: date(2022, 5, 5)}


def actual_results():
    out = defaultdict(list)
    with open(os.path.join(HERE, "data", "sv_2021.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kind"] == "mayor":
                out[r["area"]].append(r)
    return out


def local_gap_before(year):
    """
    {party: (mean, sd)} from local elections before `year` (no later data). The Greens only
    have a projected national share from 2022, so for them the full-sample gap is used - a
    small use of later data, but the mayoral residuals drawn below only make sense paired
    with a local gap.
    """
    with open(os.path.join(HERE, "data", "local_gap.csv"), newline="", encoding="utf-8") as f:
        every = [r for r in csv.DictReader(f) if (int(r["year"]), r["party"]) not in {(2024, "Ref")}]
    out = {}
    for p in MAIN:
        g = [float(r["gap"]) for r in every if r["party"] == p and int(r["year"]) < year]
        if not g:
            g = [float(r["gap"]) for r in every if r["party"] == p]
        out[p] = (float(np.mean(g)), float(np.std(g)))
    return out


def main():
    rng = np.random.default_rng(2021)
    results = actual_results()
    rows, _ = sm.load_results("results_2019_notional.csv")
    gb = [r for r in rows if r["speaker_seat"] != "1"]
    raw = sm.share_matrix(gb)
    base = sm.fill_new_candidates(raw, gb)
    weights = np.array([float(r["valid_votes"]) for r in gb])
    weights /= weights.sum()
    field = np.array([weights[raw[:, j] > 0].sum() for j in range(len(PARTIES))])
    pairs = [sr.load_pair(*p) for p in sr.PAIRS]
    gammas = sr.fit(pairs[:-1])                                   # 2010-2019 only
    elasticity = sr.elasticity(sr.features(gb, "census_2021.csv", base), gammas)
    index = {r["ons_code"]: i for i, r in enumerate(gb)}
    # one area at a time: Salford is inside Greater Manchester, Croydon inside London ...
    seats = {page: mg.constituencies({page: spec})[page] for page, spec in AREAS.items()}

    with open(os.path.join(HERE, "data", "poll_history.csv"), newline="", encoding="utf-8") as f:
        polls = [{"end_date": date.fromisoformat(r["end_date"]), **{p: float(r[p]) if r[p] else None for p in MAIN}}
                 for r in csv.DictReader(f)]
    with open(os.path.join(HERE, "data", "mayoral_adjustment.csv"), newline="", encoding="utf-8") as f:
        own_sd = {r["party"]: float(r["sussex_sd"]) for r in csv.DictReader(f)}
    with open(os.path.join(HERE, "data", "mayoral_residuals.csv"), newline="", encoding="utf-8") as f:
        residual_areas = list(csv.DictReader(f))
    rates, covered = tactics.yougov_rates()
    national_2019 = weights @ raw

    scored = []
    print(f"{'contest':34}{'winner':>8}{'model':>16}   first choice: actual (model median, 90% range)")
    for page, spec in AREAS.items():
        year = int(page[:4])
        cands = results[page]
        if not cands:
            print(f"{page[5:-17][:33]:34}  (no results scraped - skipped)")
            continue
        votes = Counter()
        for c in cands:
            votes[c["party"]] += int(c["first"])
        total = sum(votes.values())
        actual = {p: 100 * votes[p] / total for p in PARTIES}
        winner = (max((c for c in cands if c["finalist"] == "1"), key=lambda c: int(c["first"]) + int(c["transfers"] or 0))
                  if cands[0]["two_rounds"] == "1" else max(cands, key=lambda c: int(c["first"])))["party"]

        avg, _ = lg.poll_average(polls, POLLING_DAY[year])
        target = national_2019.copy()
        for p in MAIN:
            target[PARTIES.index(p)] = avg[p] / 100
        target[PARTIES.index("Oth")] = max(0.005, 1 - sum(target[j] for j in range(len(PARTIES)) if PARTIES[j] != "Oth"))
        target /= target.sum()

        nationals = sm.national_draws(rng, target, field)[:SIMULATIONS]
        i = [index[c] for c in seats[page] if c in index]
        w = np.array([float(gb[k]["valid_votes"]) for k in i])
        w /= w.sum()
        first = np.zeros((SIMULATIONS, len(PARTIES)))
        for start in range(0, SIMULATIONS, 1000):
            swung = sm.swing(base, weights, nationals[start:start + 1000], elasticity)[:, i, :]
            first[start:start + 1000] = np.einsum("i,sij->sj", w, swung)

        gap = local_gap_before(year)
        picked = [residual_areas[k] for k in rng.integers(len(residual_areas), size=SIMULATIONS)]
        for p in MAIN:
            j = PARTIES.index(p)
            first[:, j] += (gap[p][0] + gap[p][1] * rng.standard_normal(SIMULATIONS)
                            + own_sd.get(p, 2.0) * rng.standard_normal(SIMULATIONS)
                            + np.array([float(a[p]) for a in picked])) / 100
        first[:, PARTIES.index("Oth")] += sx.other_shift_draws(rng, SIMULATIONS) / 100
        first = np.clip(first, 0.002, None)
        first[:, [PARTIES.index("SNP"), PARTIES.index("PC")]] = 0
        first /= first.sum(axis=1, keepdims=True)

        wins = Counter(sx.second_count(first[s], rng, rates, covered)[0] for s in range(SIMULATIONS))
        favourite = wins.most_common(1)[0][0]
        row = {"contest": page[5:-17], "winner": winner, "favourite": favourite,
               "p_winner": wins[winner] / SIMULATIONS}
        cells = []
        for p in MAIN + ["Oth"]:
            j = PARTIES.index(p)
            lo, mid, hi = np.percentile(first[:, j], [5, 50, 95]) * 100
            row[f"{p}_actual"], row[f"{p}_median"] = actual[p], mid
            row[f"{p}_inside"] = int(lo <= actual[p] <= hi)
            if actual[p] >= 3 or mid >= 3:
                cells.append(f"{p} {actual[p]:.0f} ({mid:.0f}, {lo:.0f}-{hi:.0f}){'' if lo <= actual[p] <= hi else '*'}")
        scored.append(row)
        print(f"{page[5:-17][:33]:34}{winner:>8}{favourite + f' {100 * wins[favourite] / SIMULATIONS:.0f}%':>16}   " + "  ".join(cells))

    n = len(scored)
    print(f"\nWinner called (model's favourite won): {sum(r['winner'] == r['favourite'] for r in scored)} of {n}")
    print(f"Average chance the model gave the actual winner: {100 * np.mean([r['p_winner'] for r in scored]):.0f}%")
    brier = np.mean([(1 - r["p_winner"]) ** 2 for r in scored])
    print(f"Brier-style score on the winner (0 = perfect, 0.25 = coin toss): {brier:.3f}")
    print("\nFirst-choice shares, by party (* above = actual outside the 90% range):")
    print(f"{'':5}{'mean abs error':>16}{'bias (actual-model)':>21}{'inside 90% range':>18}")
    for p in MAIN + ["Oth"]:
        err = [r[f"{p}_actual"] - r[f"{p}_median"] for r in scored]
        inside = [r[f"{p}_inside"] for r in scored]
        print(f"{p:5}{np.mean(np.abs(err)):16.1f}{np.mean(err):+21.1f}{100 * np.mean(inside):17.0f}%")
    allin = [r[f"{p}_inside"] for r in scored for p in MAIN + ["Oth"]]
    print(f"Overall: {100 * np.mean(allin):.0f}% of actual shares inside the 90% ranges (90% = well calibrated)")

    with open(os.path.join(HERE, "data", "mayor_backtest.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(scored[0].keys()))
        writer.writeheader()
        writer.writerows({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in scored)


if __name__ == "__main__":
    main()
