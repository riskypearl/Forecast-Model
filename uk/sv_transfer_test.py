"""
Test the Sussex mayor's second count on real supplementary-vote counts.

For every 2021-22 mayoral and PCC contest that went to second choices
(data/sv_2021.csv; Bristol excluded - scraped the wrong year - and contests
with an independent finalist skipped), predict how many second choices each
finalist picked up from the eliminated candidates' first choices, and so the
final-round share. Three ways:

  - YouGov's two-horse-race rates as the model uses them (VOLUME x how many
    reach a finalist, split SPLIT x as lopsided as YouGov's, from 50/50),
    with VOLUME and the split refitted leaving the contest out
  - the same at YouGov's raw rates (no calibration)
  - BES ranked: the second choices people actually gave in May 2021 (BES
    wave 21, PCC first and second choice, data/bes/second_choices_2021.csv
    from bes_tables.py) - no fitting at all

Scored on transfers to each finalist (error as % of the real transfers),
the final-round share (mean absolute error, bias) and the winner. The model
is calibrated on mayors only; PCC contests are an outside check.

Also prints, for each mayoral contest, the split that would have fitted it
exactly: the spread the Sussex model draws SPLIT from.

    python uk/sv_transfer_test.py      -> data/sv_transfer_test.csv
"""

import csv
import os
from collections import defaultdict

import numpy as np

import tactical as tactics

HERE = os.path.dirname(__file__)
BES = os.path.join(HERE, "data", "bes", "second_choices_2021.csv")
OUT = os.path.join(HERE, "data", "sv_transfer_test.csv")
MAIN = ["Con", "Lab", "LD", "Grn", "Ref"]
INDEPENDENT = 0.27          # share of independents' voters reaching a finalist (as sussex_mayor.py)


def contests():
    by = defaultdict(list)
    with open(os.path.join(HERE, "data", "sv_2021.csv"), newline="", encoding="utf-8") as f:
        for x in csv.DictReader(f):
            if x["two_rounds"] == "1" and "Bristol" not in x["area"]:
                by[(x["kind"], x["area"])].append(x)
    out = []
    for (kind, area), xs in by.items():
        fin = [x for x in xs if x["finalist"] == "1"]
        a, b = fin[0]["party"], fin[1]["party"]
        if a not in MAIN or b not in MAIN or a == b:
            continue
        out.append({"kind": kind, "area": area, "a": a, "b": b,
                    "first": (int(fin[0]["first"]), int(fin[1]["first"])),
                    "transfers": (int(fin[0]["transfers"]), int(fin[1]["transfers"])),
                    "eliminated": [(x["party"], int(x["first"])) for x in xs if x["finalist"] == "0"]})
    return out


def yougov(c, rates, volume, split):
    P = tactics.PARTIES
    ia, ib = P.index(c["a"]), P.index(c["b"])
    ta = tb = 0.0
    for p, n in c["eliminated"]:
        if p not in MAIN:
            ta += n * INDEPENDENT / 2
            tb += n * INDEPENDENT / 2
            continue
        ya, yb = rates[ia, ib, P.index(p), 0], rates[ia, ib, P.index(p), 1]
        if ya + yb == 0:
            continue
        to_a = 0.5 + split * (ya / (ya + yb) - 0.5)
        ta += n * volume * (ya + yb) * to_a
        tb += n * volume * (ya + yb) * (1 - to_a)
    return ta, tb


def ranked(c, matrix):
    get = lambda p: matrix.get(p, matrix["Oth"])
    return (sum(n * get(p)[c["a"]] for p, n in c["eliminated"]),
            sum(n * get(p)[c["b"]] for p, n in c["eliminated"]))


def final_share(c, t):
    return (c["first"][0] + t[0]) / (sum(c["first"]) + t[0] + t[1])


def score(c, t):
    real = final_share(c, c["transfers"])
    guess = final_share(c, t)
    return {"transfer_error": abs(t[0] - c["transfers"][0]) + abs(t[1] - c["transfers"][1]),
            "transfers": sum(c["transfers"]), "share_error": 100 * (guess - real),
            "winner_right": (guess > 0.5) == (real > 0.5)}


def fit(train, rates):
    """VOLUME and split minimising the transfer error over train (grid)."""
    best = None
    for volume in np.arange(0.70, 1.40, 0.02):
        for split in np.arange(0.0, 1.21, 0.05):
            e = sum(score(c, yougov(c, rates, volume, split))["transfer_error"] for c in train)
            if best is None or e < best[0]:
                best = (e, round(volume, 2), round(split, 2))
    return best[1:]


def exact_split(c, rates, volume):
    return min(np.arange(-0.2, 1.61, 0.05), key=lambda s: abs(score(c, yougov(c, rates, volume, s))["share_error"]))


def main():
    rates, covered = tactics.yougov_rates()
    matrix = None
    if os.path.exists(BES):
        with open(BES, newline="", encoding="utf-8") as f:
            matrix = {r["first"]: {k: float(v) for k, v in r.items() if k not in ("first", "respondents")}
                      for r in csv.DictReader(f)}
    cs = contests()
    mayors = [c for c in cs if c["kind"] == "mayor"]
    volume, split = fit(mayors, rates)

    rows = []
    for c in cs:
        train = [m for m in mayors if m is not c]
        v, s = fit(train, rates) if c["kind"] == "mayor" else (volume, split)
        methods = {"YouGov, calibrated (leave one out)": yougov(c, rates, v, s),
                   "YouGov, raw": yougov(c, rates, 1.0, 1.0)}
        if matrix:
            methods["BES ranked (no fitting)"] = ranked(c, matrix)
        for name, t in methods.items():
            rows.append({"kind": c["kind"], "area": c["area"], "final": f"{c['a']} v {c['b']}", "method": name,
                         "real_final_share": round(100 * final_share(c, c["transfers"]), 1),
                         "predicted_final_share": round(100 * final_share(c, t), 1),
                         **{k: (round(x, 2) if isinstance(x, float) else x) for k, x in score(c, t).items()}})

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Calibration on {len(mayors)} mayoral counts: VOLUME {volume}, split {split}\n")
    print(f"{'':8}{'method':38}{'transfer error':>15}{'final share MAE':>17}{'bias':>7}{'winner':>8}")
    for kind in ("mayor", "pcc"):
        for name in dict.fromkeys(r["method"] for r in rows):
            rs = [r for r in rows if r["kind"] == kind and r["method"] == name]
            err = sum(r["transfer_error"] for r in rs) / sum(r["transfers"] for r in rs)
            mae = np.mean([abs(r["share_error"]) for r in rs])
            bias = np.mean([r["share_error"] for r in rs])
            right = sum(r["winner_right"] for r in rs)
            print(f"{kind:8}{name:38}{err:14.0%}{mae:15.2f}pt{bias:+7.2f}{right:>5}/{len(rs)}")
    print("\nSplit that fits each mayoral count exactly (1 = as lopsided as YouGov):")
    for c in mayors:
        print(f"  {c['area'][:44]:46}{c['a']} v {c['b']:5}{exact_split(c, rates, volume):5.2f}")
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main()
