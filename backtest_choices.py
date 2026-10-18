"""
Test the model's judgment calls on the full-model backtest, with a holdout:
choices are compared on 2012-2018 ("tune") and checked on 2020-2022
("check", years the comparison never looked at). A change is only worth
making if it helps on the check years too.

Run it with:  python backtest_choices.py
"""

import backtest as bt
import backtest_full as bf
import forecast as fc

TUNE = [2012, 2014, 2016, 2018]
CHECK = [2020, 2022]


def evaluate():
    polls = bf.load_538()
    races = bt.senate_races()
    pres, national = bt.presidential_margins()
    weights = fc.load_pollster_weights("data/pollster_ratings.csv")
    results = []
    for cycle in TUNE + CHECK:
        results += bf.run_cycle(cycle, polls, races, pres, national, weights)[1]

    def score(cycles):
        sub = [r for r in results if r["cycle"] in cycles]
        miss = sum(abs(r["actual"] - r["model"]) for r in sub) / len(sub)
        right = sum((r["actual"] > 0) == (r["model"] > 0) for r in sub)
        return f"{miss:5.2f} {right:>3}/{len(sub):<3}"
    return score(TUNE), score(CHECK)


def report(title, options):
    print(f"\n{title}")
    print(f"  {'option':<34}{'tune 2012-18':>16}{'check 2020-22':>17}")
    for label, apply in options:
        restore = apply()
        tune, check = evaluate()
        restore()
        print(f"  {label:<34}{tune:>16}{check:>17}")


def setting(module, name, value):
    def apply():
        old = getattr(module, name)
        setattr(module, name, value)
        return lambda: setattr(module, name, old)
    return apply


# Alternative ways of handling undecided voters
current_allocate = fc.allocate_undecided


def proportional(polls, baselines):
    out = []
    for p in polls:
        q = dict(p)
        u, d, r = float(p.get("undecided") or 0), float(p["dem_pct"]), float(p["rep_pct"])
        q["dem_pct"], q["rep_pct"] = d + u * d / (d + r), r + u * r / (d + r)
        out.append(q)
    return out


def leave_out(polls, baselines):
    return polls


def main():
    bf.SIMS_PER_RACE = 50   # win probabilities aren't needed here, only margins

    report("1. Undecided voters", [
        ("split by state baseline (current)", setting(fc, "allocate_undecided", current_allocate)),
        ("split like decided voters", setting(fc, "allocate_undecided", proportional)),
        ("left out", setting(fc, "allocate_undecided", leave_out)),
    ])
    report("2. Partisan-sponsored poll weight", [
        (f"{w}" + (" (current)" if w == fc.PARTISAN_POLL_WEIGHT else ""),
         setting(fc, "PARTISAN_POLL_WEIGHT", w)) for w in (0.0, 0.25, 0.5, 1.0)])
    report("3. Incumbency bonus (points)", [
        (f"{b}" + (" (current)" if b == bt.INCUMBENCY_BONUS else ""),
         setting(bt, "INCUMBENCY_BONUS", b)) for b in (0.0, 1.5, 2.5, 4.0)])
    report("4. Lean weights (latest, previous, oldest presidential election)", [
        (str(w) + (" (current)" if w == bt.LEAN_WEIGHTS else ""), setting(bt, "LEAN_WEIGHTS", w))
        for w in ([0.75, 0.175, 0.075], [0.6, 0.3, 0.1], [0.5, 0.3, 0.2], [1.0, 0.0, 0.0], [0.34, 0.33, 0.33])])


if __name__ == "__main__":
    main()
