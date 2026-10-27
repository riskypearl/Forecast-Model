"""
Update the BES "now" table for Labour's change of leader.

BES wave 31 (May-June 2026) was fielded under Keir Starmer; Andy Burnham
took over in mid-July 2026. The wave's "how likely are you ever to vote
Labour" scores are therefore Starmer-era. This re-estimates them for
Burnham, without picking a multiplier:

1. How views of the leader changed, by 2024 vote: YouGov's favourable /
   unfavourable shares for Starmer (12-13 May 2026) and Burnham (9-10
   September 2026), in data/leader_change.csv. Groups not listed (2024 SNP,
   Plaid, Other, non-voters) use YouGov's overall change.
2. Each BES respondent's 0-10 "like Starmer" score is shifted by one amount
   per 2024-vote group, so that the group's share favourable (6+) and
   unfavourable (4 or less) move by YouGov's change. Only the change is
   used, not YouGov's levels: BES respondents give fewer "don't knows", so
   the two surveys' levels differ by a few points throughout.
3. The shift is turned into a change in their "how likely to vote Labour"
   score with the link between the two within wave 31: in each 2024-vote
   group, the weighted slope of Labour likelihood on liking the leader.
   That slope compares different people (those who like Starmer are also
   more Labour-leaning for other reasons), so it probably overstates the
   effect of a leader change - an upper end, not a central estimate.
4. The table by current vote intention is rebuilt and appended to
   data/bes/ptv_tables.csv as election "now-burnham".

Run it with:  python uk/burnham_adjustment.py   (after bes_tables.py)
"""

import csv
import os

import numpy as np
import pandas as pd

import bes_tables as bt

HERE = os.path.dirname(__file__)
WAVE_FILE = os.path.join(HERE, "data", "bes", "BES2024_W31_v31.05.dta")
CHANGE = os.path.join(HERE, "data", "leader_change.csv")
TABLES = os.path.join(HERE, "data", "bes", "ptv_tables.csv")
ELECTION = "now-burnham"

FAVOURABLE = 5.5     # a 0-10 "like" of 6 or more counts as favourable
UNFAVOURABLE = 4.5   # 4 or less as unfavourable
SHIFTS = np.arange(-3, 6.01, 0.05)


def load():
    columns = ["wt", "likeStarmer", "ptvLab", "p_past_vote_2024", "generalElectionVote"] + list(bt.PTV.values()) + ["ptvBrexitParty"]
    d = pd.read_stata(WAVE_FILE, columns=list(dict.fromkeys(columns)))
    d["like"] = bt.score(d["likeStarmer"].astype(str).replace({"Strongly dislike": "0", "Strongly like": "10"}))
    d["past"] = d["p_past_vote_2024"].astype(str)
    return d


def shares(like, weights):
    """
    (% favourable, % unfavourable). Scores are whole numbers, so each one is
    treated as spread evenly over +-0.5 - otherwise any shift between two
    half-points would change nothing and the search would land on steps.
    Scores pushed past 0 or 10 stay at the end of the scale.
    """
    ok = like.notna()
    x, w = like[ok].to_numpy(), weights[ok].to_numpy()
    top = np.where(x >= 10, 1.0, np.clip(x + 0.5 - FAVOURABLE, 0, 1))
    bottom = np.where(x <= 0, 1.0, np.clip(UNFAVOURABLE - (x - 0.5), 0, 1))
    return 100 * np.sum(w * top) / w.sum(), 100 * np.sum(w * bottom) / w.sum()


def best_shift(like, weights, target_fav, target_unfav):
    """The single shift of everyone's score (kept within 0-10) that best hits both target shares."""
    errors = []
    for s in SHIFTS:
        fav, unfav = shares((like + s).clip(0, 10), weights)
        errors.append((fav - target_fav) ** 2 + (unfav - target_unfav) ** 2)
    return float(SHIFTS[int(np.argmin(errors))])


def slope(like, ptv, weights):
    ok = like.notna() & ptv.notna()
    x, y, w = like[ok], ptv[ok], weights[ok]
    xm, ym = np.average(x, weights=w), np.average(y, weights=w)
    return float(np.sum(w * (x - xm) * (y - ym)) / np.sum(w * (x - xm) ** 2))


def main():
    d = load()
    lab = bt.score(d["ptvLab"])
    with open(CHANGE, newline="", encoding="utf-8") as f:
        change = {r["group"]: {k: float(v) for k, v in r.items() if k != "group"} for r in csv.DictReader(f)}

    groups = [g for g in change if g != "Total"]
    d["group"] = np.where(d["past"].isin(groups), d["past"], "Total")
    new_lab = lab.copy()
    print(f"{'2024 vote':24}{'BES fav/unfav':>15}{'target':>13}{'reached':>13}{'shift':>7}{'slope':>7}{'Labour score':>15}")
    for g in groups + ["Total"]:
        m = d["group"] == g
        c = change[g]
        fav, unfav = shares(d.loc[m, "like"], d.loc[m, "wt"])
        target = (fav + c["new_favourable"] - c["old_favourable"], unfav + c["new_unfavourable"] - c["old_unfavourable"])
        shift = best_shift(d.loc[m, "like"], d.loc[m, "wt"], *target)
        reached = shares((d.loc[m, "like"] + shift).clip(0, 10), d.loc[m, "wt"])
        b = slope(d.loc[m, "like"], lab[m], d.loc[m, "wt"])
        moved = (d.loc[m, "like"] + shift).clip(0, 10) - d.loc[m, "like"]
        moved = moved.fillna(shift)                       # no leader rating: the group's shift
        new_lab[m] = (lab[m] + b * moved).clip(0, 10)
        before = np.average(lab[m].dropna(), weights=d.loc[m & lab.notna(), "wt"])
        after = np.average(new_lab[m].dropna(), weights=d.loc[m & new_lab.notna(), "wt"])
        print(f"{g[:23]:24}{fav:7.0f}/{unfav:<7.0f}{target[0]:6.0f}/{target[1]:<6.0f}"
              f"{reached[0]:6.0f}/{reached[1]:<6.0f}{shift:7.2f}{b:7.2f}{before:8.1f} ->{after:5.1f}")

    # Rebuild the table by current vote intention, with the new Labour scores
    d["vote"] = d["generalElectionVote"].astype(str).map(bt.VOTE)
    stems = {**bt.PTV, "Ref": "ptvBrexitParty"}
    rows = []
    for k in stems:
        mine = d["vote"] == k
        for m, stem in stems.items():
            values = new_lab[mine] if m == "Lab" else bt.score(d.loc[mine, stem])
            ok = values.notna()
            if ok.sum() < 30:
                continue
            mean = float(np.average(values[ok], weights=d.loc[mine, "wt"][ok]))
            rows.append({"election": ELECTION, "wave": 31, "voters": k, "party": m,
                         "mean_ptv": round(mean, 3), "n": int(ok.sum())})

    with open(TABLES, newline="", encoding="utf-8") as f:
        existing = [r for r in csv.DictReader(f) if r["election"] != ELECTION]
    with open(TABLES, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(existing + rows)

    old = {(r["voters"], r["party"]): float(r["mean_ptv"]) for r in existing if r["election"] == "now"}
    print("\nLikelihood of ever voting Labour, by current vote intention (Starmer-era wave 31 -> Burnham-adjusted):")
    for r in rows:
        if r["party"] == "Lab":
            print(f"  {r['voters']:4} {old.get((r['voters'], 'Lab'), float('nan')):5.1f} -> {r['mean_ptv']:5.1f}")
    print(f"Appended '{ELECTION}' to {TABLES}")


if __name__ == "__main__":
    main()
