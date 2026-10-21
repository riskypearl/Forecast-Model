"""
EXPERIMENT - NOT USED BY THE FORECASTS (they use data/pollster_ratings.csv).

Two simple rating methods were tried and both failed a sense check:
  1. Total error vs other pollsters: rewards pollsters whose partisan lean
     happened to match a year's polling miss (2016/2020), which the model
     already removes as a house effect. Its backtest "win" was also distorted
     by a pollster-name mismatch.
  2. Noise after removing each pollster's lean (below): punishes pollsters
     who do small, hard district polls (Siena 0.34) and rewards herding
     (Trafalgar 0.76).
Proper ratings need adjustments for sample size, race type and herding.

Our own pollster ratings, from how accurate each pollster has actually been.

Method (a simplified version of FiveThirtyEight's "plus-minus"):
  1. For every general-election poll in FiveThirtyEight's raw_polls.csv
     (Senate, governor, House, president, final three weeks), the error is
     |poll margin - actual margin|.
  2. Races differ in difficulty, so each poll is compared with the OTHER
     pollsters in the same race: relative error = its error - their average.
  3. A pollster's score = its average relative error, shrunk towards zero
     when it has few polls (a lucky streak of 3 polls proves little).
  4. Score -> weight: average pollster 0.6, each point more accurate than
     its peers +0.1, each point worse -0.1, kept within 0.2 to 1.0.
Fabricated / fake pollsters keep weight 0 (banned list from pollster_ratings.csv).

Run it with:  python pollster_ratings_own.py      (writes data/own_pollster_ratings.csv)
"""

import csv
import math
import re
from collections import defaultdict

SHRINK_POLLS = 10         # a pollster needs ~10 polls before its score counts at half strength
AVERAGE_WEIGHT = 0.6
PER_POINT = 0.1
TYPES = {"Sen-G", "Gov-G", "House-G", "Pres-G"}

STOPWORDS = {"the", "university", "college", "polling", "poll", "research", "inc", "llc", "and",
             "group", "associates", "co", "center", "for", "of", "public", "opinion", "institute", "company"}


def normalise(name):
    """'Mason-Dixon Polling & Research, Inc.' -> 'masondixon'; used to match names across sources."""
    words = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("-", "").replace("&", " ")).split()
    return " ".join(w for w in words if w not in STOPWORDS)


def rate(rows):
    """
    {pollster: (n_polls, score, weight)} from 538 rows.

    The forecast already removes each pollster's consistent lean (house
    effects), so what matters is how NOISY a pollster is once that lean is
    removed - not whether its lean happened to match a year's polling miss.
    So: signed error relative to the other pollsters in the same race, minus
    the pollster's own average (its lean), then the typical size of what's
    left, compared with the typical pollster.
    """
    by_race = defaultdict(list)
    for r in rows:
        if r["type_simple"] not in TYPES:
            continue
        try:
            err = float(r["margin_poll"]) - float(r["margin_actual"])   # signed: + = too Democratic
        except ValueError:
            continue
        by_race[r["race_id"]].append((r["pollster"], err))

    relative = defaultdict(list)
    for polls in by_race.values():
        for pollster, err in polls:
            others = [e for p, e in polls if p != pollster]
            if others:
                relative[pollster].append(err - sum(others) / len(others))

    noise = {}
    for pollster, rel in relative.items():
        if len(rel) >= 2:
            lean = sum(rel) / len(rel)
            noise[pollster] = (len(rel), math.sqrt(sum((x - lean) ** 2 for x in rel) / (len(rel) - 1)))
    typical = sorted(sd for n, sd in noise.values() if n >= 10)[len([1 for n, _ in noise.values() if n >= 10]) // 2]

    ratings = {}
    for pollster, (n, sd) in noise.items():
        score = (sd - typical) * n / (n + SHRINK_POLLS)      # + = noisier than typical
        weight = min(max(AVERAGE_WEIGHT - PER_POINT * score, 0.2), 1.0)
        ratings[pollster] = (n, score, weight)
    return ratings


def load_538(max_cycle=None):
    with open("data/538/raw_polls.csv", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if max_cycle is None or int(r["cycle"]) <= max_cycle]


def banned():
    with open("data/pollster_ratings.csv", encoding="utf-8") as f:
        return {normalise(r["pollster"]) for r in csv.DictReader(f) if r.get("banned") and float(r["banned"]) == 1}


def as_weights(ratings):
    """{pollster name: weight}, banned pollsters forced to 0."""
    ban = banned()
    return {p: (0.0 if normalise(p) in ban else w) for p, (n, s, w) in ratings.items()}


def main():
    ratings = rate(load_538())
    ban = banned()
    with open("data/own_pollster_ratings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pollster", "polls", "plus_minus", "weight", "banned"])
        for p, (n, s, wt) in sorted(ratings.items(), key=lambda x: -x[1][2]):
            b = normalise(p) in ban
            w.writerow([p, n, round(s, 2), 0.0 if b else round(wt, 3), int(b)])
    print(f"Rated {len(ratings)} pollsters. Best and worst with 30+ polls:")
    big = sorted(((p, v) for p, v in ratings.items() if v[0] >= 30), key=lambda x: -x[1][2])
    for p, (n, s, wt) in big[:10] + [("...", (0, 0, 0))] + big[-8:]:
        print(f"  {p[:45]:<45}{n:>6}{s:>+7.2f}{wt:>7.2f}" if p != "..." else "  ...")


if __name__ == "__main__":
    main()
