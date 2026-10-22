"""
Does a Senate candidate's record in an earlier GOVERNOR race predict how they
do in the Senate race? Tested on its own, separately from the Senate record.

Governor record = how far the candidate ran ahead of expectations (lean +
national environment + governor incumbency) in their most recent earlier
governor race in the same state, Dem-minus-Rep, like candidate_record() in
backtest.py.

Every combination is scored on fundamentals only (no polls), for Senate races
2008-2024:
  - Senate record only (the current model)
  - governor record only
  - both, as two separate adjustments with their own shrink factors
  - governor record only where the candidate has no Senate record
crossed with the competitiveness rule on or off for governor races (margin
within 15) and the governor incumbency bonus (0 / 2.5 / 5).

Each governor shrink factor is fitted on 2008-2016 and checked on 2018-2024.

Data: governor results from FiveThirtyEight raw_polls.csv (every governor race
with a poll - nearly all competitive ones; odd-year races are skipped because
the national environment is only known for even years). Senate and
presidential results from MIT Election Lab.

Run it with:  python backtest_governor.py
"""

import csv
from itertools import product

import backtest as bt

TUNE = [2008, 2010, 2012, 2014, 2016]
CHECK = [2018, 2020, 2022, 2024]
GOV_INCUMBENCY_OPTIONS = [0.0, 2.5, 5.0]
SHRINKS = [x / 20 for x in range(0, 21)]   # 0, 0.05 ... 1.0

# 538 and MIT spell a few names differently.
ALIASES = {"JAMES JUSTICE": "JIM JUSTICE"}


def governor_races():
    races = {}
    with open("data/538/raw_polls.csv", encoding="utf-8") as f:
        for p in csv.DictReader(f):
            year = int(p["cycle"])
            if p["type_simple"] != "Gov-G" or year % 2 or year not in bt.NATIONAL_ENVIRONMENT:
                continue
            parties = (p["cand1_party"], p["cand2_party"])
            if parties not in (("DEM", "REP"), ("REP", "DEM")):
                continue
            sign = 1 if parties == ("DEM", "REP") else -1
            names = [ALIASES.get(k, k) for k in (bt.name_key(p["cand1_name"].upper()),
                                                 bt.name_key(p["cand2_name"].upper()))]
            dem, rep = names if sign == 1 else names[::-1]
            races[p["race"]] = {"year": year, "state": p["location"], "dem": dem, "rep": rep,
                                "margin": sign * float(p["margin_actual"])}
    return list(races.values())


def governor_incumbency(race, gov_races, bonus):
    for prior in gov_races:
        if prior["state"] == race["state"] and race["year"] - 4 <= prior["year"] < race["year"]:
            winner = prior["dem"] if prior["margin"] > 0 else prior["rep"]
            if winner == race["dem"]:
                return bonus
            if winner == race["rep"]:
                return -bonus
    return 0.0


def governor_record(name, side, state, year, gov_races, pres, national, bonus, max_margin):
    """side = "dem" or "rep" in the race being predicted. A candidate who ran
    for governor in the other party (Jim Justice, Democrat in 2016) has the
    record flipped, so it still means "ran ahead of their party"."""
    earlier = [g for g in gov_races if g["state"] == state and g["year"] < year
               and name in (g["dem"], g["rep"])
               and year - g["year"] <= bt.MAX_PRIOR_RACE_AGE and abs(g["margin"]) <= max_margin]
    if not earlier:
        return None
    g = max(earlier, key=lambda g: g["year"])
    expected = (bt.lean(state, g["year"], pres, national) + bt.NATIONAL_ENVIRONMENT[g["year"]]
                + governor_incumbency(g, gov_races, bonus))
    record = g["margin"] - expected
    return record if g[side] == name else -record


def build_rows(races, gov_races, pres, national, bonus, max_margin):
    rows = []
    for race in races:
        if race["year"] not in TUNE + CHECK:
            continue
        sen = [bt.candidate_record(race[s], race["state"], race["year"], races, pres, national)
               for s in ("dem", "rep")]
        gov = [governor_record(race[s], s, race["state"], race["year"], gov_races, pres, national,
                               bonus, max_margin) for s in ("dem", "rep")]
        rows.append({
            **race, "base": bt.baseline(race, races, pres, national),
            "sen": sum(x for x in sen if x is not None),
            "gov": sum(x for x in gov if x is not None),
            # governor record only for candidates with no Senate record of their own
            "gov_fill": sum(g for s, g in zip(sen, gov) if g is not None and s is None),
            "has_gov": any(x is not None for x in gov),
        })
    return rows


def miss(rows, sen_shrink, gov_key, gov_shrink):
    pred = lambda r: r["base"] + sen_shrink * r["sen"] + (gov_shrink * r[gov_key] if gov_key else 0)
    return sum(abs(r["margin"] - pred(r)) for r in rows) / len(rows)


def best_shrink(rows, sen_shrink, gov_key):
    return min(SHRINKS, key=lambda s: miss(rows, sen_shrink, gov_key, s))


def main():
    pres, national = bt.presidential_margins()
    races = bt.senate_races()
    gov_races = governor_races()
    s = bt.CANDIDATE_SHRINK

    print("Governor record as a Senate candidate-quality signal (fundamentals only)")
    print("Shrink fitted on 2008-16, checked on 2018-24. Miss = average error in points,")
    print("over races where a candidate HAS a governor record (and over all races).\n")

    combos = [("Neither (lean + env + incumbency)", 0.0, None),
              ("Senate record only (current)", s, None),
              ("Governor record only", 0.0, "gov"),
              ("Senate + governor, separate", s, "gov"),
              ("Senate, governor if no Senate rec", s, "gov_fill")]
    header = f"  {'combination':<36}{'shrink':>7}{'tune':>7}{'check':>7}{'all races chk':>14}"

    for bonus, max_margin in product(GOV_INCUMBENCY_OPTIONS, (bt.MAX_PRIOR_RACE_MARGIN, 999)):
        rows = build_rows(races, gov_races, pres, national, bonus, max_margin)
        tune = [r for r in rows if r["year"] in TUNE]
        check = [r for r in rows if r["year"] in CHECK]
        tune_g = [r for r in tune if r["has_gov"]]
        check_g = [r for r in check if r["has_gov"]]
        rule = "within 15 only" if max_margin < 999 else "any margin"
        print(f"Governor incumbency {bonus}, governor races {rule}: "
              f"{len(tune_g)} tune / {len(check_g)} check races with a governor record")
        print(header)
        for label, sen_shrink, key in combos:
            g_shrink = best_shrink(tune_g, sen_shrink, key) if key else 0.0
            print(f"  {label:<36}{g_shrink:>7.2f}{miss(tune_g, sen_shrink, key, g_shrink):>7.2f}"
                  f"{miss(check_g, sen_shrink, key, g_shrink):>7.2f}"
                  f"{miss(check, sen_shrink, key, g_shrink):>14.2f}")
        print()

    # The races themselves, with the default setting (incumbency 5, within 15)
    rows = build_rows(races, gov_races, pres, national, 5.0, bt.MAX_PRIOR_RACE_MARGIN)
    print("Senate races with a governor record (incumbency 5, within 15):")
    print(f"  {'year':<6}{'st':<4}{'dem':<22}{'rep':<20}{'actual':>8}{'base+sen':>9}{'gov rec':>9}")
    for r in sorted((r for r in rows if r["has_gov"]), key=lambda r: (r["year"], r["state"])):
        print(f"  {r['year']:<6}{r['state']:<4}{r['dem'][:21]:<22}{r['rep'][:19]:<20}"
              f"{r['margin']:>+8.1f}{r['base'] + s * r['sen']:>+9.1f}{r['gov']:>+9.1f}")

    print("\n2026 candidates' governor records (incumbency 5):")
    for st, dem, rep in [(r["state"], r["dem_candidate"], r["rep_candidate"])
                         for r in csv.DictReader(open("data/candidates.csv", encoding="cp1252"))]:
        for name, side in ((dem, "dem"), (rep, "rep")):
            for max_margin in (bt.MAX_PRIOR_RACE_MARGIN, 999):
                rec = governor_record(bt.name_key(name.upper()), side, st, 2026, gov_races, pres, national,
                                      5.0, max_margin)
                if rec is not None:
                    rule = "within 15" if max_margin < 999 else "any margin"
                    print(f"  {st} {name:<20} {rec:+.1f}  ({rule})")


if __name__ == "__main__":
    main()
