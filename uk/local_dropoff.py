"""
How much of the local-election gap is turnout drop-off, and how much is people
voting differently? From the BES Internet Panel's wave 31 (May-June 2026, just
after the 7 May 2026 local elections), checked against the 2026 projected
national share.

Respondents asked whether they voted in May's local elections (10,700 in
England with an age and a vote intention; "no election here" and don't-knows
dropped):

  1. their general-election vote intention - what polls measure
  2. turnout: a logistic model of "voted" on vote intention, age band and
     stated general-election turnout likelihood. Most of the panel say they
     voted against about a third in reality (panels over-represent voters, and
     people over-report), so the model's intercept is moved until predicted
     turnout matches a real local or mayoral turnout (TURNOUTS), and the
     intentions of those predicted to vote are reweighted
  3. switching: each party's general-election supporters who voted, by their
     local vote (recall)

turnout effect = (2) - (1); switching = (3 at that turnout) - (2); the sum is
the local gap the BES implies, compared with BBC PNS 2026 minus the polls
(local_gap.py).

    python uk/local_dropoff.py path/to/BES2024_W31_Panel_v31.05.dta   -> data/bes/local_dropoff_2026.csv
"""

import csv
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import brentq, minimize

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "data", "bes", "local_dropoff_2026.csv")
COLUMNS = ["wt_new_W31", "turnoutUKGeneralW31", "localTurnoutRetroW31", "localElectionVoteW31",
           "generalElectionVoteW31", "ageW31", "gorW31"]
VOTE = {"Brexit Party/Reform UK": "Ref", "Labour": "Lab", "Green Party": "Grn", "Conservative": "Con",
        "Liberal Democrat": "LD", "Other": "Oth"}
PARTIES = ["Lab", "Con", "Ref", "LD", "Grn", "Oth"]
TURNOUTS = (0.70, 0.35, 0.30)       # as reported; about the 2026 locals; about the 2024 mayors
AGE_BANDS = [17, 24, 34, 44, 54, 64, 74, 120]


def read(path, chunk=4000):
    parts = [block[COLUMNS] for block in pd.read_stata(path, chunksize=chunk)]
    d = pd.concat(parts, ignore_index=True)
    d = d[d["wt_new_W31"].notna() & ~d["gorW31"].astype(str).isin(["Scotland", "Wales"])].copy()
    d["intention"] = d["generalElectionVoteW31"].astype(str).map(VOTE)
    d["local"] = d["localElectionVoteW31"].astype(str).map(VOTE)
    d = d[d["localTurnoutRetroW31"].isin(["Yes, voted", "No, did not vote"]) & d["intention"].notna()]
    d["voted"] = (d["localTurnoutRetroW31"] == "Yes, voted").astype(int)
    d["age"] = pd.to_numeric(d["ageW31"], errors="coerce")
    d = d[d["age"].notna()]
    d["band"] = pd.cut(d["age"], AGE_BANDS).astype(str)
    d["likely"] = d["turnoutUKGeneralW31"].astype(str)
    return d


def turnout_model(d):
    """Weighted logistic regression (lightly ridged); returns each respondent's linear predictor."""
    X = pd.get_dummies(d[["intention", "band", "likely"]], drop_first=True).astype(float)
    X.insert(0, "const", 1.0)
    X, y, w = X.values, d["voted"].values, d["wt_new_W31"].values
    nll = lambda b: -(w * (y * (X @ b) - np.logaddexp(0, X @ b))).sum() + 0.01 * (b ** 2).sum()
    grad = lambda b: -X.T @ (w * (y - 1 / (1 + np.exp(-X @ b)))) + 0.02 * b
    return X @ minimize(nll, np.zeros(X.shape[1]), jac=grad, method="L-BFGS-B").x


def shares(weights, groups):
    s = pd.Series({p: weights[groups == p].sum() for p in PARTIES})
    return 100 * s / s.sum()


def main(path):
    d = read(path)
    w, groups = d["wt_new_W31"].values, d["intention"].values
    eta = turnout_model(d)
    voters = d[d["voted"] == 1]
    switch = pd.crosstab(voters["intention"], voters["local"].fillna("none"), values=voters["wt_new_W31"],
                         aggfunc="sum").reindex(index=PARTIES, columns=PARTIES, fill_value=0).fillna(0)
    switch = switch.div(switch.sum(axis=1), axis=0)

    with open(os.path.join(HERE, "data", "local_gap.csv"), newline="", encoding="utf-8") as f:
        pns_gap = {r["party"]: float(r["gap"]) for r in csv.DictReader(f) if r["year"] == "2026"}

    polls = shares(w, groups)
    rows = []
    for turnout in TURNOUTS:
        shift = brentq(lambda c: (w / (1 + np.exp(-(eta + c)))).sum() / w.sum() - turnout, -15, 15)
        p_vote = 1 / (1 + np.exp(-(eta + shift)))
        electorate = shares(w * p_vote, groups)
        local = (electorate / 100) @ switch * 100
        for p in PARTIES:
            rows.append({"turnout": turnout, "party": p, "intention_all": round(polls[p], 2),
                         "turnout_effect": round(electorate[p] - polls[p], 2),
                         "switching": round(local[p] - electorate[p], 2),
                         "bes_gap": round(local[p] - polls[p], 2),
                         "pns_gap": pns_gap.get(p, "")})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(d):,} respondents asked about the May 2026 locals; {np.average(d['voted'], weights=d['wt_new_W31']):.0%} say they voted (weighted)\n")
    by_age = d.groupby("band").apply(lambda g: np.average(g["voted"], weights=g["wt_new_W31"]))
    print("Reported turnout by age: " + ", ".join(f"{b} {v:.0%}" for b, v in by_age.items()))
    for turnout in TURNOUTS:
        print(f"\nAt {turnout:.0%} turnout   {'turnout':>8}{'switching':>10}{'BES gap':>9}{'PNS gap':>9}")
        for r in (r for r in rows if r["turnout"] == turnout):
            pns = f"{r['pns_gap']:+9.1f}" if r["pns_gap"] != "" else ""
            print(f"  {r['party']:15}{r['turnout_effect']:+8.1f}{r['switching']:+10.1f}{r['bes_gap']:+9.1f}{pns}")
        errors = [abs(r["bes_gap"] - r["pns_gap"]) for r in rows if r["turnout"] == turnout and r["pns_gap"] != ""]
        print(f"  mean miss vs PNS {np.mean(errors):.1f} pt")
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
