"""
Compare tactical-voting methods on past elections.

Each method is scored the same way as the swing models: swing every seat
from the base election to the real national result (demographic swing,
fitted without the held-out pair), apply the method, and count seats called
right. Each method's strength is picked on the other election pairs, then
tested on the held-out one - so no method is scored on an election it was
tuned to.

Methods:
  none                no tactical voting
  affinity            squeeze direction from party closeness alone (everyone
                      equally disliked)
  ratings             affinity x leader unfavourability (the current model)
  changed             affinity, but only in seats whose top two have changed
                      since the base election
  changed+ratings     both
  anti-government     voters outside the top two back whoever can beat the
                      governing party (Conservative in every pair here)

Ratings only exist from December 2019, so the two ratings methods are tested
on 2017->19 and 2019->24 only (each strength picked on the other).

Run it with:  python uk/tactical_test.py           (held-out test)
              python uk/tactical_test.py --nowcast (today's seats under each method)
"""

import sys
from datetime import date

import numpy as np

import seat_model as sm
import swing_regression as sr
import tactical as t

STRENGTHS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3]
ELECTION_DAY = {"2015": date(2015, 5, 7), "2017": date(2017, 6, 8),
                "2019": date(2019, 12, 12), "2024": date(2024, 7, 4)}
GOVERNMENT = {"2015": "Con", "2017": "Con", "2019": "Con", "2024": "Con", "next": "Lab"}
EQUAL = 0.45
METHODS = ["none", "affinity", "ratings", "changed", "changed+ratings", "anti-government"]
NEEDS_RATINGS = {"ratings", "changed+ratings"}


def anti_government(government):
    """Everyone outside the governing party minds it, and nobody else."""
    d = np.zeros((len(sm.PARTIES), len(sm.PARTIES)))
    g = sm.PARTIES.index(government)
    d[:, g] = 1.0
    d[g, g] = 0.0
    return d


def method_inputs(method, base, election, as_of):
    """(dislike matrix, base top two or None) for a method, or None if it can't run."""
    if method == "none":
        return None
    if method in NEEDS_RATINGS:
        if as_of < date(2019, 12, 1):
            return None
        dislike = t.dislike_matrix(t.negatives(as_of))
    elif method == "anti-government":
        dislike = anti_government(GOVERNMENT[election])
    else:
        dislike = t.dislike_matrix({p: EQUAL for p in sm.PARTIES})
    changed = t.top_two(base) if method.startswith("changed") else None
    return dislike, changed


def score(pair, elasticity, method, strength):
    """(seats right, seats misallocated) for one pair."""
    old, new, weights = pair["old"], pair["new"], pair["weights"]
    election = pair["name"][-4:]
    inputs = method_inputs(method, old, election, ELECTION_DAY[election])
    if method != "none" and inputs is None:
        return None
    tactical = None
    if inputs is not None:
        dislike, changed = inputs
        tactical = (dislike, np.array([strength])) + ((changed,) if changed is not None else ())
    predicted = sm.logistic_swing(old, weights, (weights @ new)[None, :], elasticity=elasticity, tactical=tactical)[0]
    called, actual = predicted.argmax(1), new.argmax(1)
    error = np.abs(np.bincount(called, minlength=8) - np.bincount(actual, minlength=8)).sum()
    return int((called == actual).sum()), int(error)


def held_out():
    pairs = [sr.load_pair(*p) for p in sr.PAIRS]
    elasticities = [sr.elasticity(p["X"], sr.fit(pairs[:k] + pairs[k + 1:])) for k, p in enumerate(pairs)]
    cache = {}

    def cached(k, method, strength):
        key = (k, method, strength)
        if key not in cache:
            cache[key] = score(pairs[k], elasticities[k], method, strength)
        return cache[key]

    print("Held-out test: strength picked on the other pairs, scored on this one")
    print("(seats right / seats misallocated across parties; [strength picked])\n")
    print(f"{'method':17}" + "".join(f"{p['name']:>20}" for p in pairs) + f"{'total right':>13}")
    for method in METHODS:
        cells, total, complete = [], 0, True
        for k in range(len(pairs)):
            if cached(k, method, 1) is None:
                cells.append(f"{'-':>20}")
                complete = False
                continue
            if method == "none":
                s, pick = cached(k, method, 1), ""
            else:
                others = [j for j in range(len(pairs)) if j != k and cached(j, method, 1) is not None]
                pick = max(STRENGTHS, key=lambda st: sum(cached(j, method, st)[0] for j in others))
                s = cached(k, method, pick)
                pick = f"[{pick:g}]"
            total += s[0]
            cells.append(f"{s[0]:>9d} / {s[1]:<3d}{pick:>6}")
        print(f"{method:17}" + "".join(cells) + (f"{total:>13d}" if complete else f"{'-':>13}"))

    print("\nRatings methods on the two pairs they can run on, against 'none' and 'affinity':")
    for method in ["none", "affinity", "ratings", "changed", "changed+ratings"]:
        both = []
        for k in (2, 3):
            others = [3 if k == 2 else 2]
            pick = 1 if method == "none" else max(STRENGTHS, key=lambda st: sum(cached(j, method, st)[0] for j in others))
            both.append(cached(k, method, pick)[0])
        print(f"  {method:17} 2017->19 {both[0]}   2019->24 {both[1]}   total {sum(both)}")


def nowcast():
    """Today's median seats under each method, at the strength that does best on 2019->24."""
    import poll_average as pa
    sm.SIMULATIONS = 2000
    pairs = [sr.load_pair(*p) for p in sr.PAIRS]
    latest, e_latest = pairs[-1], sr.elasticity(pairs[-1]["X"], sr.fit(pairs[:-1]))

    rows, _ = sm.load_results("results_2024.csv")
    seats = [r for r in rows if r["speaker_seat"] != "1"]
    raw = sm.share_matrix(seats)
    base = sm.fill_new_candidates(raw, seats)
    weights = np.array([float(r["valid_votes"]) for r in seats])
    weights /= weights.sum()
    field = np.array([weights[raw[:, j] > 0].sum() for j in range(len(sm.PARTIES))])
    polls = pa.load_polls()
    today, _ = pa.average(polls, pa.house_effects(polls), pa.TODAY)
    average = np.array([today[p] for p in sm.PARTIES]) / 100
    seat_sd = sm.seat_error_sd()
    elasticity = sm.seat_elasticity(seats, base)

    print(f"Nowcast under each method ({sm.SIMULATIONS:,} simulations; strength = best on 2019->24)")
    print(f"{'method':17}{'strength':>9}  " + " ".join(f"{p:>4}" for p in sm.PARTIES))
    for method in METHODS:
        if method == "none":
            dislike, changed, strength = None, None, 0
        else:
            strength = max(STRENGTHS, key=lambda st: score(latest, e_latest, method, st)[0])
            if method in NEEDS_RATINGS:
                dislike = t.dislike_matrix(t.negatives(pa.TODAY))
            elif method == "anti-government":
                dislike = anti_government(GOVERNMENT["next"])
            else:
                dislike = t.dislike_matrix({p: EQUAL for p in sm.PARTIES})
            changed = t.top_two(base) if method.startswith("changed") else None
        t.STRENGTH = strength
        winners, _ = simulate_with(base, weights, average, field, seat_sd, elasticity, dislike, changed)
        counts = np.stack([(winners == j).sum(axis=1) for j in range(len(sm.PARTIES))], axis=1)
        print(f"{method:17}{strength:9g}  " + " ".join(f"{int(np.median(counts[:, j])):4d}" for j in range(len(sm.PARTIES))))


def simulate_with(base, weights, average, field, seat_sd, elasticity, dislike, changed, chunk=500):
    """seat_model.simulate, with the changed-contest option passed through."""
    rng = np.random.default_rng(sm.SEED)
    nationals = sm.national_draws(rng, average, field)
    winners = np.empty((sm.SIMULATIONS, base.shape[0]), dtype=np.int8)
    standing = base > 0
    for start in range(0, sm.SIMULATIONS, chunk):
        targets = nationals[start:start + chunk]
        tactical = None
        if dislike is not None:
            tactical = (dislike, t.strength_draws(rng, len(targets))) + ((changed,) if changed is not None else ())
        swung = sm.swing(base, weights, targets, elasticity, tactical)
        noisy = np.clip(swung + sm.t_draws(rng, swung.shape) * seat_sd / 100 * sm.size_scale(swung), 0.0005, None)
        noisy *= standing[None, :, :]
        winners[start:start + chunk] = noisy.argmax(axis=2)
    return winners, None


if __name__ == "__main__":
    nowcast() if "--nowcast" in sys.argv else held_out()
