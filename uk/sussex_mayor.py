"""
Sussex & Brighton mayoral election (May 2028), under the supplementary vote,
"if it were held today".

1. First choices: the general-election model (logistic + demographic swing
   from 2024 to today's polling average, with national polling error) for
   Sussex's 17 constituencies, weighted by votes cast. No tactical voting:
   under the supplementary vote people can vote sincerely first.
2. Mayoral adjustment: mayoral first rounds don't match Westminster voting.
   Run on the May 2025 mayoral elections (mayor_vs_ge.py), the model was off
   by these amounts on average (Labour -4.9, Reform +2.6 ...), with these
   spreads between areas; each run draws one shift per party.
3. Second count: if no one has 50%, the top two go through. Everyone else's
   voters transfer at YouGov's two-horse-race rates (data/yougov_tactical.csv),
   calibrated on the 12 mayoral contests of 2021-22 that went to second
   choices (fetch_sv_results.py):
     - how many second choices reach the finalists: YouGov's rates x 1.01;
       27% of independents' voters, split evenly
     - how they split between the two: real counts were less one-sided than
       YouGov's answers (0.43x as lopsided, measured from 50/50 - partly the
       2021 era, partly second preferences being less tactical). Each run
       draws a value between 0.43 and 1.

Not included: time until 2028 (this is a snapshot of today's polls), Sussex
local election results, and candidates' personal votes - notably Katy
Bourne's, who has won Sussex-wide under this system three times as Police
and Crime Commissioner.

Run it with:  python uk/sussex_mayor.py
Writes uk/data/sussex_mayor.csv.
"""

import csv
import os
from collections import Counter

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

# Mayoral first round minus the model, May 2025 mayors: (mean, spread), points.
MAYOR_SHIFT = {"Lab": (-4.9, 5.8), "Con": (-0.8, 3.8), "Ref": (2.6, 1.5),
               "LD": (2.2, 7.9), "Grn": (-0.9, 1.2), "Oth": (1.9, 2.8)}

# Second choices, from the 2021-22 mayoral counts
VOLUME = 1.01           # transfers reaching the finalists = YouGov-implied x this
INDEPENDENT = 0.27      # share of independents' voters whose second choice reached a finalist
SPLIT = (0.43, 1.0)     # lopsidedness of the split vs YouGov's, drawn per run

CANDIDATES = {"Con": "Katy Bourne", "Lab": "Caroline Baxter", "LD": "Ben Dempsey",
              "Grn": "Rachel Millward", "Ref": "Paul Linehan", "Oth": "Martin Webb (Ind) and others"}

PARTIES = sm.PARTIES
HERE = os.path.dirname(__file__)


def first_choices(rng):
    """sims x parties Sussex-wide first-choice shares (rows add to 1), and the model's median before step 2."""
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
    first = np.zeros((SIMULATIONS, len(PARTIES)))
    for start in range(0, SIMULATIONS, 1000):
        swung = sm.swing(base, weights, nationals[start:start + 1000], elasticity)[:, seats, :]
        first[start:start + 1000] = np.einsum("i,sij->sj", seat_weights, swung)
    model = np.median(first, axis=0)

    for p, (mean, sd) in MAYOR_SHIFT.items():
        first[:, PARTIES.index(p)] += (mean + sd * rng.standard_normal(SIMULATIONS)) / 100
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


def main():
    rng = np.random.default_rng(SEED)
    first, model = first_choices(rng)
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
    with open(os.path.join(HERE, "data", "sussex_mayor.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        writer.writeheader()
        writer.writerows(out)

    print(f"Sussex & Brighton mayor, supplementary vote, if held {pa.TODAY:%d %b %Y} ({SIMULATIONS:,} runs)\n")
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
    main()
