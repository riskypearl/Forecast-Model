"""
Does a Senate candidate's record in an earlier GOVERNOR race predict how they
do in the Senate race? Tested on its own, separately from the Senate record.

Governor record = how far the candidate ran ahead of their party in their most
recent earlier governor race in the same state, Dem-minus-Rep, like
candidate_record() in backtest.py. "Their party" is measured two ways:
  lean       - presidential lean + national environment (what backtest.py uses)
  House vote - how the party's House candidates actually did in that state
               that year (contested districts; odd-year races use the year before)
plus a governor incumbency bonus.

Every combination is scored on fundamentals only (no polls), for Senate races
2008-2024:
  - Senate record only (the current model)
  - governor record only
  - both, as two separate adjustments with their own shrink factors
  - governor record only where the candidate has no Senate record
crossed with the two baselines, the governor incumbency bonus (0 / 2.5 / 5)
and the competitiveness rule for governor races (margin within 15, or any).

Each governor shrink factor is fitted on 2008-2016 and checked on 2018-2024.

Data: every governor general election 2002-2024 (polled or not, odd years
included) from FiveThirtyEight's election-results repository
(data/538/election_results_gubernatorial.csv). Senate, House and presidential
results from MIT Election Lab.

Run it with:  python backtest_governor.py
"""

import csv
from collections import defaultdict
from itertools import product

import backtest as bt

TUNE = [2008, 2010, 2012, 2014, 2016]
CHECK = [2018, 2020, 2022, 2024]
BASELINES = ["lean", "House vote"]
GOV_INCUMBENCY_OPTIONS = [0.0, 2.5, 5.0]
SHRINKS = [x / 20 for x in range(0, 21)]   # 0, 0.05 ... 1.0

# The setting the model uses (best on 2018-24 after fitting on 2008-16): lean
# baseline, no governor incumbency bonus, governor races of any margin, kept
# as its own adjustment alongside the Senate record.
GOVERNOR_SHRINK = 0.30
GOVERNOR_INCUMBENCY = 0.0
GOVERNOR_MAX_MARGIN = 999
GOVERNOR_BASELINE = "lean"

# 538 and MIT spell a few names differently.
ALIASES = {"JAMES JUSTICE": "JIM JUSTICE"}


def governor_races():
    """Every regular governor general election since 2002: Dem side (strongest
    non-Republican if no Democrat ran), Republican, and the margin."""
    grouped = defaultdict(list)
    with open("data/538/election_results_gubernatorial.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r["stage"] == "general" and r["special"] == "false" and r["candidate_name"]
                    and r["votes"] and int(r["cycle"]) >= bt.EARLIEST_PRIOR_RACE):
                grouped[r["race_id"]].append(r)
    races = []
    for rows in grouped.values():
        rows.sort(key=lambda r: -float(r["percent"]))
        reps = [r for r in rows if r["ballot_party"] == "REP"]
        dems = [r for r in rows if r["ballot_party"] == "DEM"] or [r for r in rows if r["ballot_party"] != "REP"]
        if not reps or not dems:
            continue
        key = lambda r: ALIASES.get(k := bt.name_key(r["candidate_name"].upper()), k)
        races.append({"year": int(rows[0]["cycle"]), "state": rows[0]["state_abbrev"],
                      "dem": key(dems[0]), "rep": key(reps[0]),
                      "margin": float(dems[0]["percent"]) - float(reps[0]["percent"])})
    return races


def governor_incumbency(race, gov_races, bonus):
    for prior in gov_races:
        if prior["state"] == race["state"] and race["year"] - 4 <= prior["year"] < race["year"]:
            winner = prior["dem"] if prior["margin"] > 0 else prior["rep"]
            if winner == race["dem"]:
                return bonus
            if winner == race["rep"]:
                return -bonus
    return 0.0


def party_baseline(state, year, pres, national, how):
    even = year - year % 2
    if how == "House vote":
        house, _ = bt.house_margins()
        if (even, state) in house:
            return house[(even, state)]
    return bt.presidential_lean(state, year, pres, national) + bt.NATIONAL_ENVIRONMENT[even]


def governor_record(name, side, state, year, gov_races, pres, national, bonus, max_margin, how):
    """side = "dem" or "rep" in the race being predicted. A candidate who ran
    for governor in the other party (Jim Justice, Democrat in 2016) has the
    record flipped, so it still means "ran ahead of their party"."""
    earlier = [g for g in gov_races if g["state"] == state and g["year"] < year
               and name in (g["dem"], g["rep"])
               and year - g["year"] <= bt.MAX_PRIOR_RACE_AGE and abs(g["margin"]) <= max_margin]
    if not earlier:
        return None
    g = max(earlier, key=lambda g: g["year"])
    expected = party_baseline(state, g["year"], pres, national, how) + governor_incumbency(g, gov_races, bonus)
    record = g["margin"] - expected
    return record if g[side] == name else -record


def model_governor_adjustment(name, side, state, year, gov_races, pres, national):
    """Points added to the Dem-minus-Rep margin for this candidate's governor
    record (0 if none), with the settings the model uses."""
    rec = governor_record(name, side, state, year, gov_races, pres, national, GOVERNOR_INCUMBENCY,
                          GOVERNOR_MAX_MARGIN, GOVERNOR_BASELINE)
    return 0.0 if rec is None else GOVERNOR_SHRINK * rec


def build_rows(races, gov_races, pres, national, bonus, max_margin, how):
    rows = []
    for race in races:
        if race["year"] not in TUNE + CHECK:
            continue
        sen = [bt.candidate_record(race[s], race["state"], race["year"], races, pres, national)
               for s in ("dem", "rep")]
        gov = [governor_record(race[s], s, race["state"], race["year"], gov_races, pres, national,
                               bonus, max_margin, how) for s in ("dem", "rep")]
        rows.append({
            **race, "base": bt.baseline(race, races, pres, national),
            "sen": sum(x for x in sen if x is not None),
            "gov": sum(x for x in gov if x is not None),
            # governor record only for candidates with no Senate record of their own
            "gov_fill": sum(g for s, g in zip(sen, gov) if g is not None and s is None),
            "has_gov": any(x is not None for x in gov),
        })
    return rows


def predict(r, sen_shrink, gov_key, gov_shrink):
    return r["base"] + sen_shrink * r["sen"] + (gov_shrink * r[gov_key] if gov_key else 0)


def miss(rows, sen_shrink, gov_key, gov_shrink):
    return sum(abs(r["margin"] - predict(r, sen_shrink, gov_key, gov_shrink)) for r in rows) / len(rows)


def right(rows, sen_shrink, gov_key, gov_shrink):
    return sum((predict(r, sen_shrink, gov_key, gov_shrink) > 0) == (r["margin"] > 0) for r in rows)


def best_shrink(rows, sen_shrink, gov_key):
    return min(SHRINKS, key=lambda s: miss(rows, sen_shrink, gov_key, s))


def main():
    pres, national = bt.presidential_margins()
    races = bt.senate_races()
    gov_races = governor_races()
    s = bt.CANDIDATE_SHRINK
    combos = [("Senate + governor, separate", s, "gov"),
              ("Senate, governor if no Senate rec", s, "gov_fill"),
              ("Governor only (no Senate record)", 0.0, "gov")]

    print(f"Governor record as a Senate candidate-quality signal ({len(gov_races)} governor races, "
          "fundamentals only)")
    print("Governor shrink fitted on 2008-16; miss = avg error (points) on unseen 2018-24.\n")
    check_all = [r for r in build_rows(races, gov_races, pres, national, 0, 15, "lean") if r["year"] in CHECK]
    print(f"  Current model (Senate record only): {miss(check_all, s, None, 0):.2f} avg miss, "
          f"{right(check_all, s, None, 0)}/{len(check_all)} winners, all 2018-24 races\n")
    print(f"  {'baseline':<11}{'gov inc':>8}{'gov races':>11}  {'combination':<35}{'shrink':>7}"
          f"{'records':>9}{'rec races':>10}{'all races':>10}{'winners':>9}")
    print(f"  {'':<11}{'':>8}{'':>11}  {'':<35}{'':>7}{'tune/chk':>9}{'current':>10}")
    for how, bonus, max_margin in product(BASELINES, GOV_INCUMBENCY_OPTIONS, (bt.MAX_PRIOR_RACE_MARGIN, 999)):
        rows = build_rows(races, gov_races, pres, national, bonus, max_margin, how)
        tune_g = [r for r in rows if r["year"] in TUNE and r["has_gov"]]
        check = [r for r in rows if r["year"] in CHECK]
        check_g = [r for r in check if r["has_gov"]]
        rule = "within 15" if max_margin < 999 else "any"
        for i, (label, sen_shrink, key) in enumerate(combos):
            g = best_shrink(tune_g, sen_shrink, key)
            setting = f"  {how:<11}{bonus:>8}{rule:>11}" if i == 0 else f"  {'':<30}"
            print(f"{setting}  {label:<35}{g:>7.2f}{f'{len(tune_g)}/{len(check_g)}':>9}"
                  f"{miss(check_g, sen_shrink, key, g):>6.2f}/{miss(check_g, s, None, 0):<4.1f}"
                  f"{miss(check, sen_shrink, key, g):>9.2f}{right(check, sen_shrink, key, g):>6}/{len(check)}")
        print()

    for how in BASELINES:
        rows = build_rows(races, gov_races, pres, national, 0.0, bt.MAX_PRIOR_RACE_MARGIN, how)
        print(f"Senate races with a governor record ({how} baseline, incumbency 0, within 15):")
        print(f"  {'year':<6}{'st':<4}{'dem':<22}{'rep':<20}{'actual':>8}{'current':>9}{'gov rec':>9}")
        for r in sorted((r for r in rows if r["has_gov"]), key=lambda r: (r["year"], r["state"])):
            print(f"  {r['year']:<6}{r['state']:<4}{r['dem'][:21]:<22}{r['rep'][:19]:<20}"
                  f"{r['margin']:>+8.1f}{r['base'] + s * r['sen']:>+9.1f}{r['gov']:>+9.1f}")
        print()

    print("2026 candidates' governor records (incumbency 0):")
    for row in csv.DictReader(open("data/candidates.csv", encoding="cp1252")):
        for name, side in ((row["dem_candidate"], "dem"), (row["rep_candidate"], "rep")):
            for how, max_margin in product(BASELINES, (bt.MAX_PRIOR_RACE_MARGIN, 999)):
                rec = governor_record(bt.name_key(name.upper()), side, row["state"], 2026, gov_races,
                                      pres, national, 0.0, max_margin, how)
                if rec is not None:
                    rule = "within 15" if max_margin < 999 else "any margin"
                    print(f"  {row['state']} {name:<18} {rec:+6.1f}  ({how}, {rule})")


if __name__ == "__main__":
    main()
