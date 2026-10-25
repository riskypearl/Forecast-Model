"""
UK seat nowcast, stage 2: "if a general election were held today".

1. Baseline: every GB seat's 2024 result.
2. Logistic swing: each party's national change since 2024 is applied on the
   logit scale, not in points. A party on 2% can't drop 5 points and go
   negative, and a big national gain shows up most where the party was
   already competitive. The shift is solved so that the seats add back up to
   the national polling average exactly.
3. Simulation: each run draws a national polling miss for every party (fat
   tailed), swings every seat to that national result, then adds each seat's
   own error. Whoever is top wins the seat.

Both the swing and the size of a seat's own error are measured, not assumed,
on 2019 notional -> 2024: swing every seat to the actual 2024 national result
and compare with what it really did (see --backtest and seat_error_sd).

Stage 2 deliberately leaves out regional and seat-type correlation (stage 4)
and the demographic swing regression (stage 3), so it is the baseline those
have to beat.

Run it with:  python uk/seat_model.py
Backtest:     python uk/seat_model.py --backtest   (2019 notional -> 2024, given the real national result)
"""

import csv
import os
import sys

import numpy as np
from scipy.special import expit, logit

import poll_average as pa
import tactical as tactics

# ---------------------------------------------------------------------------
# ASSUMPTIONS - change them and re-run.
# ---------------------------------------------------------------------------

PARTIES = pa.PARTIES   # Lab, Con, Ref, LD, Grn, SNP, PC, Oth

# National polling miss, in points, for a party on 25% (smaller parties get
# proportionally less: the SD scales with sqrt(p * (1 - p)), measured on the
# party's share where it stands, so the SNP's is sized against its Scottish
# share). UK final polls have missed a party by 4+ points in 1992, 2015 and
# 2024 (Labour overstated); 2.5 makes a miss that size about a 1-in-10 event.
NATIONAL_ERROR_SD = 2.5

# A nowcast: no allowance for change between now and an election (none is
# due until 2029). Errors are polling misses only.

# Seats where a party didn't stand in 2024 get this share before swinging,
# for the parties that now stand almost everywhere in Great Britain. "Oth"
# is included because its growth is new national parties, not just the
# 303 seats that had an "other" candidate in 2024.
STANDS_EVERYWHERE = ["Lab", "Con", "Ref", "LD", "Grn", "Oth"]
NEW_CANDIDATE_SHARE = 0.01

# Swing: 0 = logistic, 1 = uniform (the same points change in every seat),
# in between = a blend. On 2019 -> 2024, given the real national result,
# logistic called 480 of 631 seats right and uniform 441; blends fell in
# between. Logistic also had the smallest seat-total errors.
SWING_UNIFORM_WEIGHT = 0.0

# Parties that always swing uniformly. "Oth" is a different set of people in
# every seat: in 2024 it was mostly local independents (Islington North,
# Blackburn, Dewsbury and Batley ...); its national rise since is new
# national parties (Restore Britain, Your Party). Logistic swing would hand
# that rise to the 2024 independents, 40% -> 48%; uniform spreads it evenly.
UNIFORM_SWING_PARTIES = ["Oth"]

# Stage 3: let seats swing harder or softer than average depending on their
# demographics and the party's strength there (swing_regression.py, which
# must have been run). Out of sample on 2019 -> 2024 it called 509 of 631
# seats right, against 480 for plain logistic swing.
DEMOGRAPHIC_SWING = True

# Tactical voting (tactical.py): voters of parties outside a seat's top two
# switch to one of the two at the rates YouGov measured in September 2026
# ("if only X and Y could win here, how would you vote?"); contests YouGov
# didn't ask about use the BES squeeze, the only method that beat "no
# tactical voting" on past elections. False = no tactical voting at all.
TACTICAL_VOTING = True

# A seat's own error, in points, for a party on 25% there (smaller shares get
# proportionally less, by sqrt(p * (1 - p))). None = measure it from
# 2019 -> 2024 (see seat_error_sd); or put a number here.
SEAT_ERROR_SD = None
# Measured on these parties only: their 2019 baselines are clean. Reform's
# isn't (the Brexit Party stood aside in 317 Conservative seats in 2019), nor
# the Greens' and Others' (candidates coming and going), which inflates
# their apparent errors in a way that won't repeat from a 2024 baseline.
SEAT_ERROR_PARTIES = ["Lab", "Con", "LD", "SNP", "PC"]

SIMULATIONS = 10_000
TAIL_DF = 5     # t-distribution degrees of freedom, as in the US model
SEED = 2026

SEATS_TOTAL = 650
MAJORITY = 326

RATING_BANDS = [(0.95, "Safe"), (0.80, "Likely"), (0.65, "Lean"), (0.55, "Tilt")]

HERE = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_results(filename):
    with open(os.path.join(HERE, "data", filename), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    gb = [r for r in rows if r["country"] != "Northern Ireland"]
    ni = [r for r in rows if r["country"] == "Northern Ireland"]
    return gb, ni


def share_matrix(rows):
    return np.array([[float(r[f"{p}_share"]) for p in PARTIES] for r in rows])


def fill_new_candidates(shares, rows):
    """A main GB party with no 2024 candidate gets NEW_CANDIDATE_SHARE, taken proportionally from the others."""
    out = shares.copy()
    for i, r in enumerate(rows):
        missing = [PARTIES.index(p) for p in STANDS_EVERYWHERE if out[i, PARTIES.index(p)] == 0]
        if missing:
            out[i] *= 1 - NEW_CANDIDATE_SHARE * len(missing)
            out[i, missing] = NEW_CANDIDATE_SHARE
    return out


# ---------------------------------------------------------------------------
# Logistic swing
# ---------------------------------------------------------------------------

def logistic_swing(base, weights, targets, iterations=25, elasticity=None, tactical=None):
    """
    base:       seats x parties, shares (rows add to 1; 0 = party not standing)
    weights:    seats, each seat's share of the national vote
    targets:    sims x parties, national shares to hit (rows add to 1)
    elasticity: seats x parties, optional - how strongly each seat responds
                to its party's national shift (1 = like everywhere else;
                from swing_regression.py). None = 1 everywhere.
    tactical:   optional (dislike matrix, strength per sim) - see tactical.py.
                Applied inside the loop, so the national totals still hit
                the target after voters switch.
    Returns sims x seats x parties.

    Each party gets one shift per sim, added to every seat's logit (times
    that seat's elasticity), or for UNIFORM_SWING_PARTIES to every seat's
    share. After shifting, each seat is rescaled to add to 1, which moves the
    national totals a little, so the shifts are re-solved until the seats add
    up to the target (usually within 0.01 points after a few rounds).
    """
    with np.errstate(divide="ignore"):
        base_logit = logit(base)                                  # -inf where a party didn't stand
    if elasticity is None:
        elasticity = np.ones_like(base)
    uniform = [PARTIES.index(p) for p in UNIFORM_SWING_PARTIES]
    national = weights @ base
    shift = logit(targets) - logit(national)                      # first guess
    shift[:, uniform] = (targets - national)[:, uniform]
    for _ in range(iterations):
        shares = expit(base_logit[None, :, :] + shift[:, None, :] * elasticity[None, :, :])
        if uniform:
            additive = base[None, :, uniform] + shift[:, None, uniform]
            shares[:, :, uniform] = np.clip(additive, 0.001, None) * (base[None, :, uniform] > 0)
        shares /= shares.sum(axis=2, keepdims=True)
        if tactical is not None:
            shares = tactics.apply(shares, tactical)
        achieved = np.einsum("i,sij->sj", weights, shares)
        step = logit(targets) - logit(achieved)
        step[:, uniform] = (targets - achieved)[:, uniform]
        shift += step
    return shares


def uniform_swing(base, weights, targets):
    """Every seat gets the national change in points (floored at 0.1%, then rescaled to add to 1)."""
    shares = base[None, :, :] + (targets - weights @ base)[:, None, :]
    shares = np.clip(shares, 0.001, None) * (base > 0)[None, :, :]
    return shares / shares.sum(axis=2, keepdims=True)


def swing(base, weights, targets, elasticity=None, tactical=None):
    if SWING_UNIFORM_WEIGHT == 0:
        return logistic_swing(base, weights, targets, elasticity=elasticity, tactical=tactical)
    return ((1 - SWING_UNIFORM_WEIGHT) * logistic_swing(base, weights, targets, elasticity=elasticity, tactical=tactical)
            + SWING_UNIFORM_WEIGHT * uniform_swing(base, weights, targets))


def seat_elasticity(seats, base):
    """Stage 3 elasticities for the 2024-boundary seats, or None if switched off / not fitted."""
    import swing_regression as sr   # imported here: swing_regression imports this module
    gammas = sr.load_coefficients() if DEMOGRAPHIC_SWING else None
    if gammas is None:
        return None
    return sr.elasticity(sr.features(seats, "census_2021.csv", base), gammas)


def size_scale(shares):
    """sqrt(p * (1 - p)) relative to a party on 25%: how much a share of this size moves."""
    return np.sqrt(shares * (1 - shares) / (0.25 * 0.75))


def backtest_inputs():
    """2019 notional and 2024 shares for the 631 GB seats (Speaker's seat left out), plus vote weights."""
    old_rows, _ = load_results("results_2019_notional.csv")
    new_rows, _ = load_results("results_2024.csv")
    keep = [i for i, r in enumerate(new_rows) if r["speaker_seat"] != "1"]
    old = fill_new_candidates(share_matrix([old_rows[i] for i in keep]), [old_rows[i] for i in keep])
    new = share_matrix([new_rows[i] for i in keep])
    # weighted by 2019 turnout: a forecast only knows the base election's
    weights = np.array([float(old_rows[i]["valid_votes"]) for i in keep])
    return old, new, weights / weights.sum()


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------

def seat_error_sd():
    """
    How far individual seats strayed from the swing model in 2024, in points
    for a party on 25%. Swing every seat from its 2019 notional result to the
    actual 2024 national result and compare with what it really did; each
    miss is divided by size_scale so big and small shares are comparable.

    A robust SD (1.4826 x the median absolute deviation) is used, so a few
    freak results - independents winning by 30 points - don't set the size of
    every seat's error. The fat tails come from the t-distribution instead.

    With DEMOGRAPHIC_SWING, the regression used here is fitted on the three
    earlier election pairs only, so 2024 is out of sample and the error isn't
    flattered. With TACTICAL_VOTING, 2024's tactical squeeze is included,
    using the BES wave before 2024 at BES_STRENGTH.
    """
    if SEAT_ERROR_SD is not None:
        return SEAT_ERROR_SD
    if DEMOGRAPHIC_SWING:
        import swing_regression as sr
        pairs = [sr.load_pair(*p) for p in sr.PAIRS]
        latest = pairs[-1]
        old, new, weights = latest["old"], latest["new"], latest["weights"]
        tactical = None
        if TACTICAL_VOTING:
            tactical = (tactics.bes_dislike("2024"), np.array([tactics.BES_STRENGTH]))
        predicted = logistic_swing(old, weights, (weights @ new)[None, :],
                                   elasticity=sr.elasticity(latest["X"], sr.fit(pairs[:-1])), tactical=tactical)[0]
    else:
        old, new, weights = backtest_inputs()
        predicted = swing(old, weights, (weights @ new)[None, :])[0]
    residuals = []
    for p in SEAT_ERROR_PARTIES:
        j = PARTIES.index(p)
        ok = (old[:, j] > 0) & (new[:, j] > 0)
        residuals.append(100 * (new[ok, j] - predicted[ok, j]) / size_scale(predicted[ok, j]))
    r = np.concatenate(residuals)
    return float(1.4826 * np.median(np.abs(r - np.median(r))))


def t_draws(rng, shape):
    """t-distributed draws rescaled to SD 1."""
    return rng.standard_t(TAIL_DF, size=shape) * np.sqrt((TAIL_DF - 2) / TAIL_DF)


def national_draws(rng, average, field):
    """
    sims x parties national results. average: today's shares (add to 1).
    field: the share of the GB vote cast in seats where each party stands
    (1 for most; ~0.09 for the SNP).
    """
    p_field = average / field
    sd_points = NATIONAL_ERROR_SD * np.sqrt(p_field * (1 - p_field) / (0.25 * 0.75))
    sd_logit = sd_points / 100 / (p_field * (1 - p_field))
    drawn = expit(logit(p_field)[None, :] + t_draws(rng, (SIMULATIONS, len(PARTIES))) * sd_logit) * field
    return drawn / drawn.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def simulate(base, weights, average, field, seat_sd, rng, elasticity=None, matrices=None, chunk=1000):
    """
    Returns (winner index per sim and seat, mean projected shares per seat,
    tactical scenario index per sim). matrices: {scenario: dislike matrix}
    from tactical.scenario_matrices, or None for no tactical voting.
    """
    nationals = national_draws(rng, average, field)
    winners = np.empty((SIMULATIONS, base.shape[0]), dtype=np.int8)
    scenarios = np.zeros(SIMULATIONS, dtype=np.int8)
    share_sum = np.zeros_like(base)
    standing = base > 0
    for start in range(0, SIMULATIONS, chunk):
        targets = nationals[start:start + chunk]
        if matrices is None:
            swung = swing(base, weights, targets, elasticity)
        else:
            # each scenario drawn in this chunk is swung separately
            swung = np.empty((len(targets),) + base.shape)
            for k, sims, tactical in tactics.scenario_draws(rng, len(targets), matrices):
                scenarios[start + sims] = k
                swung[sims] = swing(base, weights, targets[sims], elasticity, tactical)
        noise = t_draws(rng, swung.shape) * seat_sd / 100 * size_scale(swung)
        noisy = np.clip(swung + noise, 0.0005, None) * standing[None, :, :]
        noisy /= noisy.sum(axis=2, keepdims=True)
        winners[start:start + chunk] = noisy.argmax(axis=2)
        share_sum += noisy.sum(axis=0)
    return winners, share_sum / SIMULATIONS, scenarios


def rating(probs):
    best = int(np.argmax(probs))
    for threshold, label in RATING_BANDS:
        if probs[best] >= threshold:
            return f"{label} {PARTIES[best]}"
    return "Toss-up"


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    rng = np.random.default_rng(SEED)
    rows, ni = load_results("results_2024.csv")
    speaker = [i for i, r in enumerate(rows) if r["speaker_seat"] == "1"]
    contested = [i for i in range(len(rows)) if i not in speaker]
    seats = [rows[i] for i in contested]

    raw = share_matrix(seats)
    base = fill_new_candidates(raw, seats)
    weights = np.array([float(r["valid_votes"]) for r in seats])
    weights /= weights.sum()
    field = np.array([weights[raw[:, j] > 0].sum() for j in range(len(PARTIES))])

    polls = pa.load_polls()
    effects = pa.house_effects(polls)
    today, _ = pa.average(polls, effects, pa.TODAY)
    average = np.array([today[p] for p in PARTIES]) / 100

    seat_sd = seat_error_sd()
    elasticity = seat_elasticity(seats, base)
    matrices = tactics.scenario_matrices(pa.TODAY) if TACTICAL_VOTING else None
    winners, mean_shares, scenarios = simulate(base, weights, average, field, seat_sd, rng, elasticity, matrices)

    # Seat probabilities and the per-seat file
    win_prob = np.stack([(winners == j).mean(axis=0) for j in range(len(PARTIES))], axis=1)
    out = []
    for i, r in enumerate(seats):
        row = {"ons_code": r["ons_code"], "name": r["name"], "region": r["region"],
               "winner_2024": r["winner_label"]}
        row.update({f"{p}_share": round(100 * mean_shares[i, j], 1) for j, p in enumerate(PARTIES)})
        row.update({f"{p}_win": round(win_prob[i, j], 3) for j, p in enumerate(PARTIES)})
        row["favourite"] = PARTIES[int(np.argmax(win_prob[i]))]
        row["rating"] = rating(win_prob[i])
        out.append(row)
    write_csv(os.path.join(HERE, "data", "seat_forecast.csv"), out)

    # Seat totals. NI's 18 seats and the Speaker are held fixed: GB parties don't contest NI.
    counts = np.stack([(winners == j).sum(axis=1) for j in range(len(PARTIES))], axis=1)
    largest = counts.argmax(axis=1)
    totals = []
    for j, p in enumerate(PARTIES):
        c = counts[:, j]
        totals.append({
            "party": p, "vote_share": round(100 * average[j], 1),
            "mean": round(c.mean(), 1), "median": int(np.median(c)),
            "p5": int(np.percentile(c, 5)), "p95": int(np.percentile(c, 95)),
            "largest_party": round(float(((largest == j) & (c > np.sort(counts, axis=1)[:, -2])).mean()), 3),
            "majority": round(float((c >= MAJORITY).mean()), 3),
        })
    write_csv(os.path.join(HERE, "data", "seat_totals.csv"), totals)

    print(f"UK seat nowcast, {pa.TODAY:%d %b %Y} - {SIMULATIONS:,} simulations, {len(seats)} GB seats "
          f"(+ Speaker + {len(ni)} Northern Ireland, held fixed)")
    print(f"Swing: {'logistic + demographic elasticities' if elasticity is not None else 'logistic'}; "
          f"seat error SD, measured on 2019->2024: {seat_sd:.1f} points for a party on 25%")
    if matrices is not None:
        print("Tactical voting: " + ", ".join(
            f"{name} ({100 * spec[0]:.0f}% of runs, strength ~{spec[1]:g}, varied by run)"
            for name, spec in tactics.SCENARIOS.items()))
    print(f"\n{'':6}{'vote':>6}{'seats':>7}{'90% range':>13}{'largest':>9}{'majority':>10}")
    for t in sorted(totals, key=lambda t: -t["mean"]):
        print(f"{t['party']:6}{t['vote_share']:6.1f}{t['median']:7d}{t['p5']:>7d}-{t['p95']:<5d}"
              f"{100 * t['largest_party']:8.0f}%{100 * t['majority']:9.0f}%")
    no_majority = 1 - sum(t["majority"] for t in totals)
    print(f"\nHung parliament: {100 * no_majority:.0f}%")
    if matrices is not None:
        print("\nMedian seats by tactical scenario:")
        print(f"{'':17}" + "".join(f"{p:>5}" for p in PARTIES))
        for k, name in enumerate(tactics.SCENARIOS):
            mine = counts[scenarios == k]
            print(f"{name:17}" + "".join(f"{int(np.median(mine[:, j])):5d}" for j in range(len(PARTIES))))
    ratings = {}
    for r in out:
        key = r["rating"].split()[0]
        ratings[key] = ratings.get(key, 0) + 1
    print("Seat ratings:", ", ".join(f"{k} {ratings.get(k, 0)}" for k in ["Safe", "Likely", "Lean", "Tilt", "Toss-up"]))


def backtest():
    """
    Swing every seat from 2019 notional to the real 2024 national result,
    and count how many seats logistic swing called right. This tests the
    swing model alone - the national result is given, not forecast.
    """
    old, new, weights = backtest_inputs()
    target = (weights @ new)[None, :]
    actual = new.argmax(axis=1)
    print("Backtest: 2019 notional -> 2024, given the actual GB result")
    print(f"{'uniform weight':>15}{'seats right':>13}{'share RMSE':>12}   seats by party ({', '.join(PARTIES)})")
    print(f"{'actual':>15}{'':>25}   {[int((actual == j).sum()) for j in range(len(PARTIES))]}")
    for lam in np.linspace(0, 1, 6):
        predicted = ((1 - lam) * logistic_swing(old, weights, target)
                     + lam * uniform_swing(old, weights, target))[0]
        called = predicted.argmax(axis=1)
        rmse = 100 * np.sqrt(np.mean((new - predicted) ** 2))
        print(f"{lam:15.1f}{(called == actual).sum():9d}/{len(actual)}{rmse:12.2f}   "
              f"{[int((called == j).sum()) for j in range(len(PARTIES))]}")

    # Stage 3, out of sample: the regression fitted on 2010->15, 15->17 and 17->19 only.
    import swing_regression as sr
    pairs = [sr.load_pair(*p) for p in sr.PAIRS]
    right, rmse, predicted = sr.evaluate(pairs[-1], sr.fit(pairs[:-1]))
    called = predicted.argmax(axis=1)
    print(f"{'demographic':>15}{right:9d}/{len(called)}{rmse:12.2f}   "
          f"{[int((called == j).sum()) for j in range(len(PARTIES))]}   (logistic + elasticities fitted on 2010-19)")


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        backtest()
    else:
        main()
