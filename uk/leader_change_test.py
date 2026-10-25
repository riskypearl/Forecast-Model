"""
Backtest the leader-change adjustment (burnham_adjustment.py) on the two
leader changes the BES panel covers:

  May -> Johnson (Conservative, July 2019): before = wave 16 (May-June 2019),
      after = wave 17 (November 2019), groups = 2017 vote
  Corbyn -> Starmer (Labour, April 2020): before = wave 18 (November-
      December 2019), after = wave 20 (June 2020), groups = 2019 vote

For each, the method is given only what it gets for Burnham: the before
wave, plus how views of the leader changed in each group (here from the
BES itself: old leader in the before wave, new leader in the after wave -
the job YouGov's figures do for Burnham). It predicts each group's
"how likely to ever vote <party>" score after the change; that is compared
with what the after wave actually measured.

"realised" = actual change / predicted change. 1 = the method gets the size
right; above 1 = it understates the leader effect; below 1 = it overstates.

Run it with:  python uk/leader_change_test.py <panel .dta>
"""

import sys

import numpy as np
import pandas as pd

import bes_tables as bt
import burnham_adjustment as ba

CASES = [
    {"name": "May -> Johnson (Con)", "party": "Con", "ptv": "ptvCon", "past": "p_past_vote_2017",
     "before": 16, "old": "likeMay", "after": 17, "new": "likeJohnson"},
    {"name": "Corbyn -> Starmer (Lab)", "party": "Lab", "ptv": "ptvLab", "past": "p_past_vote_2019",
     "before": 18, "old": "likeCorbyn", "after": 20, "new": "likeStarmer"},
]
GROUPS = ["Conservative", "Labour", "Liberal Democrat", "Green Party", "Brexit Party/Reform UK",
          "United Kingdom Independence Party (UKIP)", "Scottish National Party (SNP)"]


def like(series):
    return bt.score(series.astype(str).replace({"Strongly dislike": "0", "Strongly like": "10"}))


def columns(case):
    b, a = case["before"], case["after"]
    return [case["past"], f"wt_new_W{b}", f"wt_new_W{a}", f"{case['old']}W{b}", f"{case['new']}W{a}",
            f"{case['ptv']}W{b}", f"{case['ptv']}W{a}"]


def run(case, panel):
    b, a = case["before"], case["after"]
    past = panel[case["past"]].astype(str)
    old_like, new_like = like(panel[f"{case['old']}W{b}"]), like(panel[f"{case['new']}W{a}"])
    ptv_before, ptv_after = bt.score(panel[f"{case['ptv']}W{b}"]), bt.score(panel[f"{case['ptv']}W{a}"])
    w_before, w_after = panel[f"wt_new_W{b}"], panel[f"wt_new_W{a}"]

    print(f"\n{case['name']}: likelihood of ever voting {case['party']}, by {case['past'][-4:]} vote")
    print(f"{'group':24}{'before':>8}{'predicted':>11}{'actual':>8}{'realised':>10}")
    predicted_changes, actual_changes, sizes = [], [], []
    for g in GROUPS:
        in_before = (past == g) & w_before.notna() & old_like.notna()
        in_after = (past == g) & w_after.notna() & new_like.notna()
        if in_before.sum() < 100 or in_after.sum() < 100:
            continue
        # How views of the leader changed in this group (the YouGov step, here from the BES)
        fav0, unfav0 = ba.shares(old_like[in_before], w_before[in_before])
        fav1, unfav1 = ba.shares(new_like[in_after], w_after[in_after])
        shift = ba.best_shift(old_like[in_before], w_before[in_before], fav1, unfav1)
        b_slope = ba.slope(old_like[in_before], ptv_before[in_before], w_before[in_before])
        moved = (old_like[in_before] + shift).clip(0, 10) - old_like[in_before]
        ok_b = in_before & ptv_before.notna()
        ok_a = (past == g) & w_after.notna() & ptv_after.notna()
        before = np.average(ptv_before[ok_b], weights=w_before[ok_b])
        predicted = np.average((ptv_before[ok_b] + b_slope * moved[ok_b]).clip(0, 10), weights=w_before[ok_b])
        actual = np.average(ptv_after[ok_a], weights=w_after[ok_a])
        realised = (actual - before) / (predicted - before) if abs(predicted - before) > 0.05 else float("nan")
        print(f"{g[:23]:24}{before:8.2f}{predicted:11.2f}{actual:8.2f}{realised:10.2f}"
              f"   (leader fav {fav0:.0f}% -> {fav1:.0f}%)")
        predicted_changes.append(predicted - before)
        actual_changes.append(actual - before)
        sizes.append(ok_b.sum())
    p, y, s = np.array(predicted_changes), np.array(actual_changes), np.array(sizes, dtype=float)
    ratio = float(np.sum(s * p * y) / np.sum(s * p * p))   # least-squares scale on the predicted changes
    print(f"Overall: actual change = {ratio:.2f} x predicted change (fitted across groups, weighted by size)")
    print(f"Error, mean absolute: no adjustment {np.average(np.abs(y), weights=s):.2f}, "
          f"method {np.average(np.abs(y - p), weights=s):.2f}, method x {ratio:.2f} {np.average(np.abs(y - ratio * p), weights=s):.2f}")
    return ratio


def main(path):
    wanted = list(dict.fromkeys(c for case in CASES for c in columns(case)))
    panel = pd.concat([block[wanted] for block in pd.read_stata(path, chunksize=4000)], ignore_index=True)
    ratios = [run(case, panel) for case in CASES]
    print(f"\nRealised / predicted, the two leader changes: {', '.join(f'{r:.2f}' for r in ratios)}")


if __name__ == "__main__":
    main(sys.argv[1])
