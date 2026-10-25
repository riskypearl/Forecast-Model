"""
Sussex & Brighton mayoral election (May 2028), under the supplementary vote.

1. First choices: the general-election model (logistic + demographic swing
   from 2024 to the national polls, with polling error) for Sussex's 17
   constituencies, weighted by votes cast. No tactical voting: under the
   supplementary vote people can vote sincerely first.
2. Time to May 2028: each run adds one real historical poll movement over
   the same length of time (every such stretch since 2010, from
   data/poll_history.csv), so the parties move together as they have done.
   Run with --today for "if held today" instead.
3. Mayoral adjustment (data/mayoral_adjustment.csv, mayoral_adjustment.py):
   the national local-vs-polls gap (2012-2026), the mayoral-vs-local
   difference (2024-25 mayors), and Sussex's own local pattern (2021 and
   2026 county elections, Brighton & Hove 2019 and 2023) - each run draws
   one shift per party from their combined uncertainty.
4. Second count: if no one has 50%, the top two go through. Everyone else's
   voters transfer at YouGov's two-horse-race rates (data/yougov_tactical.csv),
   calibrated on the 12 mayoral contests of 2021-22 that went to second
   choices (fetch_sv_results.py):
     - how many second choices reach the finalists: YouGov's rates x 1.01;
       27% of independents' voters, split evenly
     - how they split between the two: real counts were less one-sided than
       YouGov's answers (0.43x as lopsided, measured from 50/50 - partly the
       2021 era, partly second preferences being less tactical). Each run
       draws a value between 0.43 and 1.

5. Katy Bourne's personal vote (bourne_effect.py): in all four Sussex PCC
   elections she ran ahead of the typical Conservative PCC candidate, measured
   against each area's general-election Conservative share. Centred on the two
   like-for-like comparisons (2021, 2024: +2.8, +4.7), with the spread of all
   four years (+2.6 to +11.5) as uncertainty. Other candidates' personal votes
   are only in the spread of the mayoral adjustment.

Run it with:  python uk/sussex_mayor.py            (May 2028)
              python uk/sussex_mayor.py --today    (if held today)
Writes uk/data/sussex_mayor.csv (or sussex_mayor_today.csv).
"""

import csv
import os
import sys
from collections import Counter
from datetime import date, timedelta

import numpy as np

import poll_average as pa
import seat_model as sm
import tactical as tactics

# ---------------------------------------------------------------------------
# ASSUMPTIONS
# ---------------------------------------------------------------------------

SIMULATIONS = 10_000
SEED = 2028

# The 17 constituencies wholly or mainly in East Sussex, West Sussex and Brighton & Hove.
SUSSEX = {
    "E14001067": "Arundel and South Downs", "E14001088": "Bexhill and Battle",
    "E14001108": "Bognor Regis and Littlehampton", "E14001129": "Brighton Kemptown and Peacehaven",
    "E14001130": "Brighton Pavilion", "E14001166": "Chichester", "E14001184": "Crawley",
    "E14001212": "East Grinstead and Uckfield", "E14001218": "East Worthing and Shoreham",
    "E14001219": "Eastbourne", "E14001274": "Hastings and Rye", "E14001294": "Horsham",
    "E14001296": "Hove and Portslade", "E14001330": "Lewes", "E14001366": "Mid Sussex",
    "E14001533": "Sussex Weald", "E14001599": "Worthing West",
}

ELECTION_DAY = date(2028, 5, 4)
DRIFT_WINDOW_DAYS = 21     # poll averages at each end of a historical stretch

# Mayoral adjustment: from data/mayoral_adjustment.csv for the five main
# parties. Independents and others: one real 2024/25 mayoral area's shift per
# run (data/other_shifts.csv) - usually a few points, occasionally 10-25, as
# when Jamie Driscoll took 25% in the North East. A bell curve around +2
# (the first version) left 2021-22 independents outside their 90% range three
# times in four.

# Second choices, from the 2021-22 mayoral counts
VOLUME = 1.01           # transfers reaching the finalists = YouGov-implied x this
INDEPENDENT = 0.27      # share of independents' voters whose second choice reached a finalist
SPLIT = (0.43, 1.0)     # lopsidedness of the split vs YouGov's, drawn per run

CANDIDATES = {"Con": "Katy Bourne", "Lab": "Caroline Baxter", "LD": "Ben Dempsey",
              "Grn": "Rachel Millward", "Ref": "Paul Linehan", "Oth": "Martin Webb (Ind) and others"}

PARTIES = sm.PARTIES
HERE = os.path.dirname(__file__)


def mayoral_shift(rng, n):
    """
    n x parties (points). Per run: the national local gap and Sussex's own pattern (their
    means, plus normal noise of their measured SDs), and one real 2024/2025 mayoral area's
    residuals - drawn whole, since candidate effects are lumpy (most areas near zero, a few
    huge, like Burnham or Houchen) and push the other parties down when one party surges.
    """
    with open(os.path.join(HERE, "data", "mayoral_adjustment.csv"), newline="", encoding="utf-8") as f:
        parts = {r["party"]: r for r in csv.DictReader(f)}
    with open(os.path.join(HERE, "data", "mayoral_residuals.csv"), newline="", encoding="utf-8") as f:
        areas = list(csv.DictReader(f))
    picked = [areas[i] for i in rng.integers(len(areas), size=n)]
    out = np.zeros((n, len(PARTIES)))
    for p, r in parts.items():
        j = PARTIES.index(p)
        out[:, j] = (float(r["local_gap"]) + float(r["local_gap_sd"]) * rng.standard_normal(n)
                     + float(r["sussex"]) + float(r["sussex_sd"]) * rng.standard_normal(n)
                     + np.array([float(a[p]) for a in picked]))
    out[:, PARTIES.index("Oth")] = other_shift_draws(rng, n)
    return out


def bourne_draws(rng, n):
    """n draws (points) of Katy Bourne's personal vote: mean of the 2021 and 2024 comparisons, SD of all four."""
    path = os.path.join(HERE, "data", "bourne_effect.csv")
    if not os.path.exists(path):
        return np.zeros(n)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    clean = [float(r["edge"]) for r in rows if int(r["year"]) >= 2021]
    every = [float(r["edge"]) for r in rows]
    return np.mean(clean) + np.std(every) * rng.standard_normal(n)


def other_shift_draws(rng, n, exclude=()):
    """n draws (points) of the independents / others shift, each one real 2024/25 mayoral area's."""
    with open(os.path.join(HERE, "data", "other_shifts.csv"), newline="", encoding="utf-8") as f:
        values = np.array([float(r["shift"]) for r in csv.DictReader(f) if r["area"] not in exclude])
    return values[rng.integers(len(values), size=n)]


def drift_draws(rng, days, n):
    """
    n x parties (points): real changes in the national poll average over `days`, from every
    such stretch since 2010 (start dates a week apart), drawn at random.
    """
    import local_gap as lg
    with open(os.path.join(HERE, "data", "poll_history.csv"), newline="", encoding="utf-8") as f:
        polls = [{"end_date": date.fromisoformat(r["end_date"]),
                  **{p: float(r[p]) if r[p] else None for p in lg.PARTIES}} for r in csv.DictReader(f)]
    first, last = polls[0]["end_date"] + timedelta(days=DRIFT_WINDOW_DAYS), polls[-1]["end_date"]
    changes, day = [], first
    while day + timedelta(days=days) <= last:
        a, _ = lg.poll_average(polls, day)
        b, _ = lg.poll_average(polls, day + timedelta(days=days))
        if all(a[p] is not None and b[p] is not None for p in lg.PARTIES):
            changes.append([b[p] - a[p] for p in lg.PARTIES])
        day += timedelta(days=7)
    # centred on zero: 2010-2026 had UKIP's and Reform's rises and the Conservative collapse,
    # and those trends shouldn't be carried forward - only how big movements get
    changes = np.array(changes)
    changes -= changes.mean(axis=0)
    picked = changes[rng.integers(len(changes), size=n)]
    out = np.zeros((n, len(PARTIES)))
    for k, p in enumerate(lg.PARTIES):
        out[:, PARTIES.index(p)] = picked[:, k]
    return out, len(changes)


def first_choices(rng, to_election=True):
    """sims x parties Sussex-wide first-choice shares (rows add to 1), and the model's median before step 3."""
    rows, _ = sm.load_results("results_2024.csv")
    gb = [r for r in rows if r["speaker_seat"] != "1"]
    raw = sm.share_matrix(gb)
    base = sm.fill_new_candidates(raw, gb)
    weights = np.array([float(r["valid_votes"]) for r in gb])
    weights /= weights.sum()
    field = np.array([weights[raw[:, j] > 0].sum() for j in range(len(PARTIES))])
    polls = pa.load_polls()
    today, _ = pa.average(polls, pa.house_effects(polls), pa.TODAY)
    average = np.array([today[p] for p in PARTIES]) / 100
    elasticity = sm.seat_elasticity(gb, base)

    seats = [i for i, r in enumerate(gb) if r["ons_code"] in SUSSEX]
    seat_weights = np.array([float(gb[i]["valid_votes"]) for i in seats])
    seat_weights /= seat_weights.sum()

    nationals = sm.national_draws(rng, average, field)[:SIMULATIONS]
    global DRIFT_STRETCHES
    if to_election:
        drift, DRIFT_STRETCHES = drift_draws(rng, (ELECTION_DAY - pa.TODAY).days, SIMULATIONS)
        nationals = np.clip(nationals + drift / 100, 0.002, None)
        nationals[:, [PARTIES.index("SNP"), PARTIES.index("PC")]] = average[[PARTIES.index("SNP"), PARTIES.index("PC")]]
        nationals /= nationals.sum(axis=1, keepdims=True)
    first = np.zeros((SIMULATIONS, len(PARTIES)))
    for start in range(0, SIMULATIONS, 1000):
        swung = sm.swing(base, weights, nationals[start:start + 1000], elasticity)[:, seats, :]
        first[start:start + 1000] = np.einsum("i,sij->sj", seat_weights, swung)
    model = np.median(first, axis=0)

    first += mayoral_shift(rng, SIMULATIONS) / 100
    first[:, PARTIES.index("Con")] += bourne_draws(rng, SIMULATIONS) / 100
    first = np.clip(first, 0.002, None)
    first[:, [PARTIES.index("SNP"), PARTIES.index("PC")]] = 0
    return first / first.sum(axis=1, keepdims=True), model


def second_count(f, rng, rates, covered):
    """(winner, finalists, finalist a's final share) for one run's first-choice shares f."""
    order = np.argsort(-f)
    a, b = order[0], order[1]
    if f[a] > 0.5:
        return PARTIES[a], (PARTIES[a], PARTIES[b]), None
    lopsided = rng.uniform(*SPLIT)
    va, vb = f[a], f[b]
    for k in range(len(PARTIES)):
        if k in (a, b) or f[k] == 0:
            continue
        if PARTIES[k] == "Oth":
            va += f[k] * INDEPENDENT / 2
            vb += f[k] * INDEPENDENT / 2
            continue
        ya, yb = rates[a, b, k, 0], rates[a, b, k, 1]
        if not covered[a, b] or ya + yb == 0:
            continue
        reach = VOLUME * (ya + yb)
        to_a = 0.5 + lopsided * (ya / (ya + yb) - 0.5)
        va += f[k] * reach * to_a
        vb += f[k] * reach * (1 - to_a)
    return (PARTIES[a] if va > vb else PARTIES[b]), (PARTIES[a], PARTIES[b]), va / (va + vb)


DRIFT_STRETCHES = 0


def main(to_election=True):
    rng = np.random.default_rng(SEED)
    first, model = first_choices(rng, to_election)
    rates, covered = tactics.yougov_rates()

    winners, pairs, finals = Counter(), Counter(), {}
    for s in range(SIMULATIONS):
        winner, (a, b), share_a = second_count(first[s], rng, rates, covered)
        winners[winner] += 1
        pair = tuple(sorted((a, b)))
        pairs[pair] += 1
        if share_a is not None:
            finals.setdefault(pair, []).append(share_a if a == pair[0] else 1 - share_a)

    shown = [j for j in np.argsort(-np.median(first, axis=0)) if PARTIES[j] not in ("SNP", "PC")]
    out = []
    for j in shown:
        p = PARTIES[j]
        lo, mid, hi = np.percentile(first[:, j], [5, 50, 95]) * 100
        out.append({"party": p, "candidate": CANDIDATES.get(p, ""), "model_share": round(100 * model[j], 1),
                    "first_choice": round(mid, 1), "first_p5": round(lo, 1), "first_p95": round(hi, 1),
                    "win": round(winners[p] / SIMULATIONS, 3)})
    name = "sussex_mayor.csv" if to_election else "sussex_mayor_today.csv"
    with open(os.path.join(HERE, "data", name), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)

    when = (f"{ELECTION_DAY:%d %b %Y}, from polls on {pa.TODAY:%d %b %Y} "
            f"(+ real poll movement over {(ELECTION_DAY - pa.TODAY).days} days, {DRIFT_STRETCHES} historical stretches)"
            if to_election else f"if held {pa.TODAY:%d %b %Y}")
    print(f"Sussex & Brighton mayor, supplementary vote: {when} - {SIMULATIONS:,} runs\n")
    print(f"{'':5}{'candidate':30}{'model':>7}{'first choice':>14}{'90% range':>13}{'win':>6}")
    for r in out:
        print(f"{r['party']:5}{r['candidate']:30}{r['model_share']:6.1f}%{r['first_choice']:13.1f}%"
              f"{r['first_p5']:7.1f}-{r['first_p95']:<5.1f}{100 * r['win']:5.0f}%")
    print("\nFinal two (how often), and who wins it:")
    for (x, y), n in pairs.most_common(6):
        shares = finals.get((x, y))
        detail = (f"   {x} wins {100 * np.mean(np.array(shares) > 0.5):.0f}%, typically "
                  f"{100 * np.median(shares):.0f}-{100 - 100 * np.median(shares):.0f}") if shares else ""
        print(f"  {x} v {y}: {100 * n / SIMULATIONS:4.0f}%{detail}")


if __name__ == "__main__":
    main(to_election="--today" not in sys.argv)
