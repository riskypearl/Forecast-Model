"""
Tactical voting.

In each seat, voters of the parties outside the top two can switch to
whichever of the top two they mind less - a Lib Dem in a Labour-v-Reform
seat backing Labour to stop Reform. How many switch depends on:

  1. Dislike: how much party k's voters mind party m, measured in the
     British Election Study: 1 - (k's voters' average 0-10 "how likely are
     you ever to vote for m") / 10, from the BES wave before each election
     (bes_tables.py -> data/bes/ptv_tables.csv; wave 31, May-June 2026, for
     the nowcast). An older version - an affinity judgement
     (data/tactical_affinity.csv) x leader unfavourability
     (data/favourability.csv) - is kept for comparison as "ratings".
  2. Preference gap: in a seat whose top two are a and b, a k voter's
     reason to switch is dislike(a) - dislike(b). If both are equally
     disliked, nobody bothers.
  3. Closeness: full effect when a and b are level, fading to nothing when
     the winner leads by CLOSENESS points or more.
  4. Strength: one overall multiplier, calibrated on 2024 (python
     uk/tactical.py), and varied from simulation to simulation, since how
     strong a tactical wave will be is uncertain - and it hits every seat
     at once when it comes.

Votes are moved between parties within each seat; seat_model.py then
re-solves the national swing, so the national totals still match the polls.
Tactical voting changes where votes are, not how many each party gets.

Which method. tactical_test.py scores eight methods on four past elections,
each with its strength picked on the other elections. Only the BES-measured
squeeze beat "no tactical voting" (2,237 seats right vs 2,231), so the
nowcast uses it alone (SCENARIOS), at strength 1.5, varied from run to run.
The other methods - leader ratings, anti-government - can be put back into
SCENARIOS, with chances, to mix them in again.

Run it with:  python uk/tactical.py   (calibrates the ratings STRENGTH on 2019 notional -> 2024)
"""

import csv
import os
from datetime import date, timedelta

import numpy as np

# ---------------------------------------------------------------------------
# ASSUMPTIONS
# ---------------------------------------------------------------------------

PARTIES = ["Lab", "Con", "Ref", "LD", "Grn", "SNP", "PC", "Oth"]

# Overall strength for the "ratings" method (the share of a fully motivated
# voter's party that switches when the race is level). Calibrated on 2024 -
# see main().
STRENGTH = 1.5

# BES squeeze strength. Held fixed across the four test elections, 1.5-3
# gained 13-21 seats over "none" in total; 1.5 is the cautious end, and it
# took the 2024 test from 509 to 528 seats right.
BES_STRENGTH = 1.5

# The nowcast's tactical methods: name -> (chance, typical strength,
# run-to-run SD of the strength, log-normal). Each simulation draws one.
# Possible names: "yougov", "bes", "ratings", "anti-government", "none".
#   yougov: YouGov's measured two-horse-race answers (data/yougov_tactical.csv,
#           September 2026), used as measured (strength 1). The SD allows for
#           people following through on a hypothetical more or less than they
#           say. Contests YouGov didn't ask about (SNP, Plaid ...) use BES.
SCENARIOS = {
    "yougov": (1.0, 1.0, 0.3),
}
GOVERNMENT = "Lab"

# Default run-to-run SD for scenarios that don't give one (0.75 = a typical
# run is between about 0.5x and 2x the scenario's strength).
STRENGTH_SD = 0.75

# Margin (points) at which the squeeze fades to nothing.
CLOSENESS = 25

# No more than this share of a party's voters ever switch.
MAX_SWITCH = 0.8

# Leader unfavourability: polls from this many days before the date used.
FAVOURABILITY_DAYS = 45
# For parties with no leader ratings (SNP, Plaid, Others), this negative share.
DEFAULT_NEGATIVE = 0.35

HERE = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def load_affinity(path=os.path.join(HERE, "data", "tactical_affinity.csv")):
    with open(path, newline="", encoding="utf-8") as f:
        rows = {r["voters"]: r for r in csv.DictReader(f)}
    return np.array([[float(rows[k][m]) for m in PARTIES] for k in PARTIES])


def negatives(as_of, days=FAVOURABILITY_DAYS, path=os.path.join(HERE, "data", "favourability.csv")):
    """
    {party: share negative} - the average negative rating of each party's
    leader in the `days` before (and, for a past election, just after)
    as_of. Where a party changed leader in the window, only the leader
    polled most recently counts.
    """
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["kind"] == "leader"]
    lo, hi = as_of - timedelta(days=days), as_of + timedelta(days=days // 3)
    window = [r for r in rows if lo <= date.fromisoformat(r["end_date"]) <= hi]
    out = {}
    for party in PARTIES:
        mine = [r for r in window if r["party"] == party]
        if not mine:
            out[party] = DEFAULT_NEGATIVE
            continue
        latest = max(mine, key=lambda r: r["end_date"])["name"]
        values = [float(r["neg"]) for r in mine if r["name"] == latest]
        out[party] = sum(values) / len(values) / 100
    return out


def dislike_matrix(neg):
    """voters x target: how much each party's voters mind each party."""
    return load_affinity() * np.array([neg[m] for m in PARTIES])[None, :]


# BES-measured dislike (bes_tables.py): 1 - (average 0-10 "how likely are you
# ever to vote for m" among party k's intending voters) / 10. Pairs the BES
# doesn't ask (SNP voters about Plaid, anything about "Other") get these.
BES_MISSING = 0.9
BES_OTHER = 0.8      # how much everyone minds an "Other" candidate (independents ...)

# How willing each party's voters are to switch at all (1 = as the BES scores
# say). Halving Reform's helped the 2024 test (528 -> 533 seats right) but
# hurt 2015 (589 -> 583, UKIP voters did switch), so overall it was a wash
# and it's left at 1. Lowering it gives Labour a few more seats, since in
# Labour-v-Conservative seats Reform voters lean Conservative.
WILLINGNESS = {"Ref": 1.0}


def bes_dislike(election, path=os.path.join(HERE, "data", "bes", "ptv_tables.csv")):
    """voters x target dislike measured in the BES wave before `election` ('2015' ... '2024', 'now')."""
    d = np.full((len(PARTIES), len(PARTIES)), BES_MISSING)
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["election"] == election:
                d[PARTIES.index(r["voters"]), PARTIES.index(r["party"])] = 1 - float(r["mean_ptv"]) / 10
    oth = PARTIES.index("Oth")
    d[:, oth] = BES_OTHER
    d[oth, :] = 0.0          # no data on Other voters' preferences: they don't switch
    np.fill_diagonal(d, 0.0)
    for party, willing in WILLINGNESS.items():
        d[PARTIES.index(party), :] *= willing
    return d


def strength_draws(rng, n, strength=None):
    strength = STRENGTH if strength is None else strength
    return strength * np.exp(rng.normal(-STRENGTH_SD ** 2 / 2, STRENGTH_SD, size=n))


def anti_government(government=GOVERNMENT):
    """Everyone outside the governing party minds it, and nobody else."""
    d = np.zeros((len(PARTIES), len(PARTIES)))
    g = PARTIES.index(government)
    d[:, g] = 1.0
    d[g, g] = 0.0
    return d


def scenario_matrices(as_of):
    """{scenario: dislike matrix} for the nowcast, for each method in SCENARIOS."""
    builders = {
        "none": lambda: np.zeros((len(PARTIES), len(PARTIES))),
        "bes": lambda: bes_dislike("now"),
        "yougov": lambda: bes_dislike("now"),       # BES for the contests YouGov didn't ask about
        "ratings": lambda: dislike_matrix(negatives(as_of)),
        "anti-government": anti_government,
    }
    if {"bes", "yougov"} & set(SCENARIOS) and not os.path.exists(os.path.join(HERE, "data", "bes", "ptv_tables.csv")):
        raise SystemExit("Tactical voting needs data/bes/ptv_tables.csv: download the BES panel and run "
                         "python uk/bes_tables.py <panel .dta> (or set TACTICAL_VOTING = False in seat_model.py).")
    return {name: builders[name]() for name in SCENARIOS}


def scenario_draws(rng, n, matrices):
    """
    For n simulations: a list of (scenario index, sims using it, tactical
    argument for seat_model.logistic_swing) - one per scenario drawn.
    """
    names = list(SCENARIOS)
    chances = np.array([SCENARIOS[s][0] for s in names])
    which = rng.choice(len(names), size=n, p=chances / chances.sum())
    out = []
    for k, name in enumerate(names):
        sims = np.flatnonzero(which == k)
        if not len(sims):
            continue
        typical = SCENARIOS[name][1]
        sd = SCENARIOS[name][2] if len(SCENARIOS[name]) > 2 else STRENGTH_SD
        strength = typical * np.exp(rng.normal(-sd ** 2 / 2, sd, size=len(sims)))
        if name == "yougov":
            tactical = {"method": "yougov", "dislike": matrices[name], "strength": strength}
        else:
            tactical = (matrices[name], strength)
        out.append((k, sims, tactical))
    return out


# ---------------------------------------------------------------------------
# YouGov's measured two-horse races
# ---------------------------------------------------------------------------

YOUGOV_PATH = os.path.join(HERE, "data", "yougov_tactical.csv")
_yougov = None


def yougov_rates(path=YOUGOV_PATH):
    """
    (rates, covered). rates[a, b, k] = (share of k's voters who'd vote a,
    who'd vote b, who wouldn't vote) when a and b are the only two in
    contention; covered[a, b] says whether YouGov asked about that pairing.
    """
    global _yougov
    if _yougov is None:
        n = len(PARTIES)
        rates, covered = np.zeros((n, n, n, 3)), np.zeros((n, n), dtype=bool)
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                a, b, k = (PARTIES.index(r[c]) for c in ("contest_a", "contest_b", "voters"))
                p = float(r["pct"]) / 100
                slot = {r["contest_a"]: 0, r["contest_b"]: 1, "none": 2}.get(r["choice"])
                if slot is None:
                    continue
                rates[a, b, k, slot] = p
                rates[b, a, k, [1, 0, 2][slot]] = p
                covered[a, b] = covered[b, a] = True
        _yougov = rates, covered
    return _yougov


def squeeze_yougov(shares, strength, fallback):
    """
    Voters outside a seat's top two (a, b) move at YouGov's measured rates
    for an a-v-b race - to a, to b, or to not voting - scaled by how close
    the race is and by this run's strength. Voters YouGov doesn't break out
    (SNP, Plaid, Other) stay put. Seats whose pairing YouGov didn't ask
    about get the BES squeeze (fallback dislike matrix) instead.
    """
    rates, covered = yougov_rates()
    order = np.argsort(-shares, axis=2)
    a, b = order[..., 0], order[..., 1]
    s_a = np.take_along_axis(shares, a[..., None], axis=2)[..., 0]
    s_b = np.take_along_axis(shares, b[..., None], axis=2)[..., 0]
    close = np.clip(1 - 100 * (s_a - s_b) / CLOSENESS, 0, 1)

    k = np.arange(shares.shape[2])
    r = rates[a[..., None], b[..., None], k[None, None, :]]                # sims x seats x parties x 3
    outside = (k[None, None, :] != a[..., None]) & (k[None, None, :] != b[..., None])
    scale = (strength[:, None, None] * close[..., None] * outside)[..., None]
    moves = np.minimum(r * scale, 1.0)
    moves *= np.minimum(1.0, 1.0 / np.maximum(moves.sum(axis=3, keepdims=True), 1e-9))   # never more than all of them
    moved = shares[..., None] * moves                                       # sims x seats x parties x 3

    out = shares - moved.sum(axis=3)
    np.put_along_axis(out, a[..., None], (s_a + moved[..., 0].sum(axis=2))[..., None], axis=2)
    np.put_along_axis(out, b[..., None], (s_b + moved[..., 1].sum(axis=2))[..., None], axis=2)
    out = np.clip(out, 0, None)                                             # rounding can leave -1e-17
    out /= out.sum(axis=2, keepdims=True)                                   # the non-voters drop out

    known = covered[a, b]
    if not known.all():
        other = squeeze(shares, fallback, BES_STRENGTH * strength)
        out = np.where(known[..., None], out, other)
    return out


def apply(shares, tactical):
    """seat_model.logistic_swing's hook: a (dislike, strength[, base top two]) tuple, or a YouGov dict."""
    if isinstance(tactical, dict):
        return squeeze_yougov(shares, tactical["strength"], tactical["dislike"])
    return squeeze(shares, *tactical)


# ---------------------------------------------------------------------------
# The squeeze
# ---------------------------------------------------------------------------

def top_two(shares):
    """seats x 2: the two leading parties in each seat (unordered pairs, smaller index first)."""
    order = np.argsort(-shares, axis=-1)[..., :2]
    return np.sort(order, axis=-1)


def squeeze(shares, dislike, strength, base_top_two=None):
    """
    shares:       sims x seats x parties (rows add to 1)
    dislike:      parties x parties, or sims x parties x parties (one per sim)
    strength:     sims
    base_top_two: optional seats x 2 from top_two(base). If given, only
                  seats whose top two have changed since the base election
                  are squeezed: a seat with the same contest already has
                  that contest's tactical voting in its baseline.
    Returns shares after third-placed (and lower) parties' voters switch.
    """
    order = np.argsort(-shares, axis=2)
    a, b = order[..., 0], order[..., 1]                           # leader, runner-up
    s_a = np.take_along_axis(shares, a[..., None], axis=2)[..., 0]
    s_b = np.take_along_axis(shares, b[..., None], axis=2)[..., 0]
    close = np.clip(1 - 100 * (s_a - s_b) / CLOSENESS, 0, 1)
    if base_top_two is not None:
        now = np.sort(np.stack([a, b], axis=-1), axis=-1)
        close = close * (now != base_top_two[None, :, :]).any(axis=-1)

    # gap[k] = how much more party k's voters mind the leader than the runner-up
    if dislike.ndim == 2:
        gap = dislike.T[a] - dislike.T[b]                         # sims x seats x parties
    else:
        targets = dislike.transpose(0, 2, 1)                      # sims x target x voter
        sims = np.arange(len(dislike))[:, None]
        gap = targets[sims, a] - targets[sims, b]
    k = np.arange(shares.shape[2])
    outside = (k[None, None, :] != a[..., None]) & (k[None, None, :] != b[..., None])
    rate = np.clip(strength[:, None, None] * close[..., None] * np.abs(gap), 0, MAX_SWITCH) * outside
    moved = shares * rate

    out = shares - moved
    to_b = (moved * (gap > 0)).sum(axis=2)                        # mind the leader more -> back the runner-up
    to_a = (moved * (gap < 0)).sum(axis=2)
    np.put_along_axis(out, b[..., None], (s_b + to_b)[..., None], axis=2)
    np.put_along_axis(out, a[..., None], (s_a + to_a)[..., None], axis=2)
    return out


# ---------------------------------------------------------------------------
# Calibration on 2024
# ---------------------------------------------------------------------------

def main():
    import seat_model as sm
    import swing_regression as sr

    pairs = [sr.load_pair(*p) for p in sr.PAIRS]
    latest = pairs[-1]
    old, new, weights = latest["old"], latest["new"], latest["weights"]
    elasticity = sr.elasticity(latest["X"], sr.fit(pairs[:-1]))   # out of sample, as in the backtest
    neg = negatives(date(2024, 7, 4))
    dislike = dislike_matrix(neg)
    target = (weights @ new)[None, :]
    actual = new.argmax(axis=1)
    true_seats = np.array([(actual == j).sum() for j in range(len(PARTIES))])

    print("Leader negatives around the 2024 election:", ", ".join(f"{p} {100 * v:.0f}%" for p, v in neg.items()))
    print("\nCalibration: 2019 notional -> 2024, actual national result, demographic swing (fitted on 2010-19)")
    print(f"{'strength':>9}{'seats right':>13}{'seat error':>12}   seats ({', '.join(PARTIES)})")
    print(f"{'actual':>9}{'':>25}   {true_seats.tolist()}")
    best = None
    for strength in [0, 0.5, 1, 1.5, 2, 2.5, 3, 4]:
        tactics = (dislike, np.array([strength])) if strength else None
        predicted = sm.logistic_swing(old, weights, target, elasticity=elasticity, tactical=tactics)[0]
        called = predicted.argmax(axis=1)
        seats = np.array([(called == j).sum() for j in range(len(PARTIES))])
        right, error = int((called == actual).sum()), int(np.abs(seats - true_seats).sum())
        print(f"{strength:9.1f}{right:9d}/{len(called)}{error:12d}   {seats.tolist()}")
        if best is None or right > best[1]:
            best = (strength, right)
    print(f"\nMost seats right: strength {best[0]} (STRENGTH is set to {STRENGTH}). "
          "'seat error' = total seats misallocated across parties.")


if __name__ == "__main__":
    main()
