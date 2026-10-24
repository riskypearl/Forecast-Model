"""
Demographic swing regression (stage 3).

Logistic swing moves every seat by the same amount on the logit scale. In
practice some seats respond more strongly than others: when UKIP / Reform
gains nationally it gains even more in older, non-graduate seats; when the
Lib Dems fall they fall furthest where they had been strongest. This fits,
for each party, how much harder or softer each kind of seat swings:

    seat logit change = national shift x elasticity
    elasticity        = 1 + gamma . features

Features are 2021 Census characteristics (England and Wales; Scottish seats
get the England-and-Wales average plus a Scotland flag), Wales and Scotland
flags, and the party's own starting strength in the seat.

It is fitted on four election pairs - 2010->15, 2015->17, 2017->19 (2010-24
boundaries) and 2019 notional->2024 (2024 boundaries) - and tested by
leaving one pair out at a time: fit on three, predict the fourth.

Only the part of each seat's change that scales with its party's national
move can be learned this way. A pattern special to one election (Labour's
losses in seats with large Muslim populations in 2024, say) can't be
projected forward from one example, so it stays in the seat error.

Run it with:  python uk/swing_regression.py
Writes uk/data/swing_coefficients.csv, which seat_model.py uses.
"""

import csv
import os

import numpy as np
from scipy.special import logit

import seat_model as sm

# ---------------------------------------------------------------------------
# ASSUMPTIONS
# ---------------------------------------------------------------------------

CENSUS_FEATURES = ["degree", "age_65_plus", "age_18_34", "white", "muslim",
                   "owned", "social_rent", "students", "professional"]
FEATURES = CENSUS_FEATURES + ["wales", "scotland", "own_strength"]

# Parties with an elasticity. "Oth" swings uniformly (see seat_model.py).
PARTIES = ["Lab", "Con", "Ref", "LD", "Grn", "SNP", "PC"]

# (base election, next election, census file). Same boundaries within a pair.
PAIRS = [
    ("results_2010.csv", "results_2015.csv", "census_2021_old_boundaries.csv"),
    ("results_2015.csv", "results_2017.csv", "census_2021_old_boundaries.csv"),
    ("results_2017.csv", "results_2019.csv", "census_2021_old_boundaries.csv"),
    ("results_2019_notional.csv", "results_2024.csv", "census_2021.csv"),
]

# Ridge penalty: shrinks every gamma towards 0 (plain logistic swing). Picked
# by the leave-one-pair-out test in main(); this grid is what gets tried.
RIDGE_GRID = [0, 1, 3, 10, 30, 100, 300]
RIDGE = 10

# A seat's elasticity is kept within these bounds, so no seat swings the
# opposite way to its party's national move.
ELASTICITY_RANGE = (0.25, 3.0)

# Shares below this (in either election) are left out of the fit: their
# logits are mostly noise.
MIN_SHARE = 0.01

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "data", "swing_coefficients.csv")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_census(filename):
    with open(os.path.join(HERE, "data", filename), newline="", encoding="utf-8") as f:
        return {r["ons_code"]: {k: float(r[k]) for k in CENSUS_FEATURES} for r in csv.DictReader(f)}


def features(rows, census_file, base):
    """
    seats x parties x features. Census columns are standardised across
    England and Wales seats (Scotland gets 0 = the average); own_strength is
    the party's logit share in the seat minus its average across seats.
    """
    census = load_census(census_file)
    values = np.array([[census[c][k] for k in CENSUS_FEATURES] for c in census])
    mean, sd = values.mean(axis=0), values.std(axis=0)
    seat = np.zeros((len(rows), len(FEATURES) - 1))
    for i, r in enumerate(rows):
        if r["ons_code"] in census:
            seat[i, :len(CENSUS_FEATURES)] = (np.array([census[r["ons_code"]][k] for k in CENSUS_FEATURES]) - mean) / sd
        seat[i, FEATURES.index("wales")] = r["country"] == "Wales"
        seat[i, FEATURES.index("scotland")] = r["country"] == "Scotland"
    with np.errstate(divide="ignore"):
        strength = logit(np.clip(base, 1e-4, None))
    strength = strength - np.array([strength[base[:, j] > 0, j].mean() for j in range(base.shape[1])])
    out = np.repeat(seat[:, None, :], base.shape[1], axis=1)
    return np.concatenate([out, strength[:, :, None]], axis=2)


def load_pair(base_file, next_file, census_file):
    """Seats in both elections (Speaker's seat in either left out), with shares, weights and features."""
    old_rows, _ = sm.load_results(base_file)
    new_rows, _ = sm.load_results(next_file)
    new_by_code = {r["ons_code"]: r for r in new_rows}
    rows = [r for r in old_rows if r["ons_code"] in new_by_code
            and r["speaker_seat"] != "1" and new_by_code[r["ons_code"]]["speaker_seat"] != "1"]
    old = sm.fill_new_candidates(sm.share_matrix(rows), rows)
    new = sm.share_matrix([new_by_code[r["ons_code"]] for r in rows])
    weights = np.array([float(r["valid_votes"]) for r in rows])
    weights /= weights.sum()
    return {"name": f"{base_file[8:12]}->{next_file[8:12]}", "rows": rows, "old": old, "new": new,
            "weights": weights, "X": features(rows, census_file, old)}


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------

def fit(pairs, ridge=RIDGE):
    """
    {party: gamma vector}. For each pair, plain logistic swing to the real
    national result gives each seat's predicted logit; the miss is regressed
    on (national shift x features), weighted by p(1 - p) so that small
    shares, whose logits are noisy, count for less.
    """
    gammas = {}
    for p in PARTIES:
        j = sm.PARTIES.index(p)
        Z, y, w = [], [], []
        for pair in pairs:
            old, new, weights = pair["old"], pair["new"], pair["weights"]
            predicted = sm.logistic_swing(old, weights, (weights @ new)[None, :])[0]
            shift = logit(weights @ new)[j] - logit(weights @ old)[j]
            ok = (old[:, j] >= MIN_SHARE) & (new[:, j] >= MIN_SHARE)
            Z.append(shift * pair["X"][ok, j, :])
            y.append(logit(new[ok, j]) - logit(predicted[ok, j]))
            w.append(predicted[ok, j] * (1 - predicted[ok, j]))
        Z, y, w = np.concatenate(Z), np.concatenate(y), np.concatenate(w)
        A = Z.T @ (Z * w[:, None]) + ridge * np.eye(Z.shape[1])
        # least squares, not solve: with no ridge, the SNP's census columns are all 0 (Scotland only)
        gammas[p] = np.linalg.lstsq(A, Z.T @ (w * y), rcond=None)[0]
    return gammas


def elasticity(X, gammas):
    """seats x parties multipliers for seat_model.logistic_swing."""
    out = np.ones(X.shape[:2])
    for p, g in gammas.items():
        j = sm.PARTIES.index(p)
        out[:, j] = np.clip(1 + X[:, j, :] @ g, *ELASTICITY_RANGE)
    return out


def evaluate(pair, gammas):
    """(seats called right, share RMSE in points) swinging to the pair's real national result."""
    old, new, weights = pair["old"], pair["new"], pair["weights"]
    e = elasticity(pair["X"], gammas) if gammas else None
    predicted = sm.logistic_swing(old, weights, (weights @ new)[None, :], elasticity=e)[0]
    right = int((predicted.argmax(1) == new.argmax(1)).sum())
    return right, 100 * float(np.sqrt(np.mean((new - predicted) ** 2))), predicted


def load_coefficients(path=OUT):
    """{party: gamma vector} from swing_coefficients.csv, or None if it hasn't been made."""
    if not os.path.exists(path):
        return None
    gammas = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gammas[r["party"]] = np.array([float(r[k]) for k in FEATURES])
    return gammas


def main():
    pairs = [load_pair(*p) for p in PAIRS]

    print("Leave-one-pair-out test: fit on three election pairs, predict the fourth")
    print(f"{'ridge':>6}" + "".join(f"{p['name']:>15}" for p in pairs) + f"{'total':>9}{'RMSE':>7}")
    base_scores = [evaluate(p, None)[:2] for p in pairs]
    print(f"{'none':>6}" + "".join(f"{s[0]:>10d}/{len(p['rows'])}" for s, p in zip(base_scores, pairs))
          + f"{sum(s[0] for s in base_scores):9d}{np.mean([s[1] for s in base_scores]):7.2f}   <- plain logistic")
    best = None
    for ridge in RIDGE_GRID:
        scores = [evaluate(pairs[k], fit(pairs[:k] + pairs[k + 1:], ridge))[:2] for k in range(len(pairs))]
        total, rmse = sum(s[0] for s in scores), float(np.mean([s[1] for s in scores]))
        print(f"{ridge:>6}" + "".join(f"{s[0]:>10d}/{len(p['rows'])}" for s, p in zip(scores, pairs))
              + f"{total:9d}{rmse:7.2f}")
        if best is None or rmse < best[1]:
            best = (ridge, rmse)
    print(f"Lowest out-of-sample RMSE: ridge {best[0]} (RIDGE is set to {RIDGE})")

    gammas = fit(pairs, RIDGE)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["party"] + FEATURES)
        writer.writeheader()
        for p, g in gammas.items():
            writer.writerow({"party": p, **{k: round(float(v), 4) for k, v in zip(FEATURES, g)}})
    print(f"\nFitted on all four pairs -> {OUT}")
    print("Elasticity change per 1 SD of each feature (+0.10 = seats 1 SD above average swing 10% harder):")
    print(f"{'':14}" + "".join(f"{p:>7}" for p in PARTIES))
    for k, name in enumerate(FEATURES):
        print(f"{name:14}" + "".join(f"{gammas[p][k]:+7.2f}" for p in PARTIES))


if __name__ == "__main__":
    main()
