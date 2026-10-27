"""
Sussex & Brighton mayor, second method: start from how Sussex actually voted
in its own local elections, not from the general election.

1. Baseline: the real votes in the May 2026 West Sussex and East Sussex
   county elections and the May 2023 Brighton & Hove election - together the
   whole mayoral area. Areas are weighted by voters: the county divisions
   elect one councillor each, but Brighton's wards elect two or three, so its
   party vote totals are divided by the average councillors per ward. That
   gives local-election turnout, much closer to mayoral turnout than a general
   election's.
2. National change since each election, on the logit scale: the GB polls in
   the 3 weeks before that election against the polls now (same simple
   average both times), plus this run's polling miss. A party that didn't
   stand locally (Reform in Brighton in 2023) starts from the area's July
   2024 general-election share instead.
3. Then exactly as in sussex_mayor.py: one real mayoral area's residuals
   (mayoral vs local; no incumbents), Katy Bourne's personal vote, the
   independents' shift, and the second count. No national local gap - the
   baseline already is a local election.

Run it with:  python uk/sussex_mayor_local.py           (if held today)
              python uk/sussex_mayor_local.py --2028    (May 2028, with poll movement)
Writes uk/data/sussex_mayor_local.csv.
"""

import csv
import os
import sys
from collections import Counter
from datetime import date

import numpy as np
from scipy.special import expit, logit

import local_gap as lg
import mayor_vs_ge as mg
import mayoral_adjustment as ma
import poll_average as pa
import seat_model as sm
import sussex_mayor as sx
import tactical as tactics

HERE = os.path.dirname(__file__)
PARTIES = sm.PARTIES
MAIN = ["Lab", "Con", "Ref", "LD", "Grn"]
SIMULATIONS = sx.SIMULATIONS

# (area, Wikipedia page, polling day, councillors per ward on average)
COUNCILS = [
    ("West Sussex", "2026 West Sussex County Council election", date(2026, 5, 7), 1.0),
    ("East Sussex", "2026 East Sussex County Council election", date(2026, 5, 7), 1.0),
    ("Brighton and Hove", "2023 Brighton and Hove City Council election", date(2023, 5, 4), 54 / 23),
]
STOOD = 1.0     # % below this counts as not having stood locally


def history():
    with open(os.path.join(HERE, "data", "poll_history.csv"), newline="", encoding="utf-8") as f:
        return [{"end_date": date.fromisoformat(r["end_date"]), **{p: float(r[p]) if r[p] else None for p in MAIN}}
                for r in csv.DictReader(f)]


def baseline():
    """[(area, shares over PARTIES (add to 1), voters, polling day, GE-2024 shares)]"""
    seats = mg.constituencies({area: {"utlas": [area]} for area, *_ in COUNCILS})
    out = []
    for area, page, day, per_ward in COUNCILS:
        _, votes = ma.council_shares(page)
        total = sum(votes.values())
        shares = np.array([votes.get(p, 0) / total for p in PARTIES])
        ge, _ = ma.general_shares("results_2024.csv", codes=seats[area])
        out.append((area, shares, total / per_ward, day, ge))
    return out


def first_choices(rng, to_election=False):
    polls = history()
    now_hist, _ = lg.poll_average(polls, pa.TODAY)
    # this run's national polling miss (and, for 2028, poll movement), from the main model
    published = pa.load_polls()
    today, _ = pa.average(published, pa.house_effects(published), pa.TODAY)
    average = np.array([today[p] for p in PARTIES]) / 100
    rows, _ = sm.load_results("results_2024.csv")
    gb = [r for r in rows if r["speaker_seat"] != "1"]
    raw = sm.share_matrix(gb)
    weights = np.array([float(r["valid_votes"]) for r in gb]); weights /= weights.sum()
    field = np.array([weights[raw[:, j] > 0].sum() for j in range(len(PARTIES))])
    miss = sm.national_draws(rng, average, field)[:SIMULATIONS] - average
    if to_election:
        drift, _ = sx.drift_draws(rng, (sx.ELECTION_DAY - pa.TODAY).days, SIMULATIONS)
        miss += drift / 100
    ge_national, _ = ma.general_shares("results_2024.csv")

    areas = baseline()
    voters = np.array([v for _, _, v, _, _ in areas])
    first = np.zeros((SIMULATIONS, len(PARTIES)))
    print(f"{'area':18}{'voters':>9}  baseline (Ref/Con/Lab/LD/Grn/Oth) -> today, at the central polls")
    for (area, shares, n, day, ge), w in zip(areas, voters / voters.sum()):
        then_hist, _ = lg.poll_average(polls, day)
        area_sims = np.tile(shares, (SIMULATIONS, 1))
        for p in MAIN:
            j = PARTIES.index(p)
            now = np.clip(now_hist[p] / 100 + miss[:, j], 0.002, None)
            if 100 * shares[j] >= STOOD:
                start, then = shares[j], then_hist[p] / 100
            else:                                   # didn't stand: the area's 2024 general-election share
                start, then = ge[p] / 100, ge_national[p] / 100
            area_sims[:, j] = expit(logit(max(start, 0.002)) + logit(now) - logit(then))
        area_sims /= area_sims.sum(axis=1, keepdims=True)
        first += w * area_sims
        mid = np.median(area_sims, axis=0) * 100
        print(f"{area:18}{n:9,.0f}  " + "/".join(f"{100 * shares[PARTIES.index(p)]:.0f}" for p in ["Ref", "Con", "Lab", "LD", "Grn", "Oth"])
              + "  ->  " + "/".join(f"{mid[PARTIES.index(p)]:.0f}" for p in ["Ref", "Con", "Lab", "LD", "Grn", "Oth"]))
    base = np.median(first, axis=0)

    # mayoral vs local (no national local gap: the baseline is already local), Bourne, independents
    with open(os.path.join(HERE, "data", "mayoral_residuals.csv"), newline="", encoding="utf-8") as f:
        residuals = [a for a in csv.DictReader(f) if (int(a["year"]), a["area"]) not in sx.INCUMBENT_AREAS]
    picked = [residuals[i] for i in rng.integers(len(residuals), size=SIMULATIONS)]
    for p in MAIN:
        first[:, PARTIES.index(p)] += np.array([float(a[p]) for a in picked]) / 100
    first[:, PARTIES.index("Con")] += sx.bourne_draws(rng, SIMULATIONS) / 100
    first[:, PARTIES.index("Oth")] += sx.other_shift_draws(rng, SIMULATIONS) / 100
    first = np.clip(first, 0.002, None)
    first[:, [PARTIES.index("SNP"), PARTIES.index("PC")]] = 0
    return first / first.sum(axis=1, keepdims=True), base


def main(to_election=False):
    rng = np.random.default_rng(sx.SEED)
    first, base = first_choices(rng, to_election)
    rates, covered = tactics.yougov_rates()
    winners, pairs, finals = Counter(), Counter(), {}
    for s in range(SIMULATIONS):
        winner, (a, b), share_a = sx.second_count(first[s], rng, rates, covered)
        winners[winner] += 1
        pair = tuple(sorted((a, b)))
        pairs[pair] += 1
        if share_a is not None:
            finals.setdefault(pair, []).append(share_a if a == pair[0] else 1 - share_a)

    out = []
    for j in np.argsort(-np.median(first, axis=0)):
        p = PARTIES[j]
        if p in ("SNP", "PC"):
            continue
        lo, mid, hi = np.percentile(first[:, j], [5, 50, 95]) * 100
        out.append({"party": p, "candidate": sx.CANDIDATES.get(p, ""), "local_baseline": round(100 * base[j], 1),
                    "first_choice": round(mid, 1), "first_p5": round(lo, 1), "first_p95": round(hi, 1),
                    "win": round(winners[p] / SIMULATIONS, 3)})
    with open(os.path.join(HERE, "data", "sussex_mayor_local.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)

    when = f"May 2028 from polls on {pa.TODAY:%d %b %Y}" if to_election else f"if held {pa.TODAY:%d %b %Y}"
    print(f"\nSussex & Brighton mayor - council-baseline method, {when} ({SIMULATIONS:,} runs)\n")
    print(f"{'':5}{'candidate':30}{'local base':>11}{'first choice':>14}{'90% range':>13}{'win':>6}")
    for r in out:
        print(f"{r['party']:5}{r['candidate']:30}{r['local_baseline']:10.1f}%{r['first_choice']:13.1f}%"
              f"{r['first_p5']:7.1f}-{r['first_p95']:<5.1f}{100 * r['win']:5.0f}%")
    print("\nFinal two (how often), and who wins it:")
    for (x, y), n in pairs.most_common(6):
        shares = finals.get((x, y))
        detail = (f"   {x} wins {100 * np.mean(np.array(shares) > 0.5):.0f}%, typically "
                  f"{100 * np.median(shares):.0f}-{100 - 100 * np.median(shares):.0f}") if shares else ""
        print(f"  {x} v {y}: {100 * n / SIMULATIONS:4.0f}%{detail}")


if __name__ == "__main__":
    main(to_election="--2028" in sys.argv)
