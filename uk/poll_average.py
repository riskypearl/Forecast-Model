"""
GB polling average for the next UK general election, from uk/data/polls.csv.

With eight parties, averaging raw percentages can give shares that don't add
up, or a negative share once house effects are removed. So every step runs on
log-ratios: each party's share relative to Labour, log(party / Lab). Labour's
own log-ratio is always 0. Averages and house effects are added and
subtracted on that scale, then turned back into shares that always add to 100.

Writes:
  uk/data/poll_average.csv   today's average for each party
  uk/data/house_effects.csv  each pollster's lean, in points against today's average
  uk/data/poll_trend.csv     the average every week since the 2024 election

Run it with:  python uk/poll_average.py
"""

import csv
import math
import os
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# ASSUMPTIONS - change them and re-run.
# ---------------------------------------------------------------------------

PARTIES = ["Lab", "Con", "Ref", "LD", "Grn", "SNP", "PC", "Oth"]
BASE = "Lab"   # the party every log-ratio is measured against (any party works; the result is the same)

# A poll this old counts half as much as one from today. Longer than the US
# model's 14 days: the election is years away and UK pollsters publish
# weekly, so a month of polls is still a fair picture.
HALF_LIFE_DAYS = 21

# "0%" in a table means under 0.5%, and log(0) is undefined, so shares are
# floored here (in percent).
MIN_SHARE = 0.25

# Bigger polls count more (square root of the sample size), up to this size.
# MRPs with 15,000+ respondents would otherwise swamp everything else.
MAX_SAMPLE_SIZE = 5000

# Prolific pollsters: More in Common, Find Out Now and YouGov each publish
# every week. Without this, a pollster's weight grows with how often it
# polls. A poll's weight is divided by (its pollster's polls in the last
# HALF_LIFE_DAYS) to this power: 0 = no adjustment, 1 = every pollster counts
# the same however often it polls.
PROLIFIC_DAMPING = 0.5

# House effects: how far a pollster's polls sit from other pollsters'
# polls fielded within this many days. Shrunk towards zero for pollsters
# with few polls (bigger = more sceptical).
HOUSE_EFFECT_WINDOW_DAYS = 14
HOUSE_EFFECT_SHRINK = 3
HOUSE_EFFECT_ITERATIONS = 3   # re-estimate against already-debiased polls

# Which pollsters define "no house effect". None = the average pollster
# (each pollster with at least ANCHOR_MIN_POLLS polls counts once). Put a list
# of names here to measure everyone against those pollsters instead, e.g.
# the ones closest to the 2024 result.
ANCHOR_POLLSTERS = None
ANCHOR_MIN_POLLS = 5

TREND_START = date(2024, 7, 12)
TREND_STEP_DAYS = 7

TODAY = date.today()

HERE = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Log-ratio helpers
# ---------------------------------------------------------------------------

def to_log_ratios(shares):
    """{party: percent or None} -> {party: log(share / BASE)}; parties not listed are left out."""
    base = max(shares[BASE], MIN_SHARE)
    return {p: math.log(max(s, MIN_SHARE) / base) for p, s in shares.items() if s is not None and p != BASE}


def to_shares(log_ratios):
    """{party: log-ratio} (BASE implied 0) -> {party: percent}, adding to 100. A party with no polls gets 0."""
    exp = {BASE: 1.0, **{p: math.exp(v) for p, v in log_ratios.items()}}
    total = sum(exp.values())
    return {p: 100 * exp.get(p, 0.0) / total for p in PARTIES}


# ---------------------------------------------------------------------------
# Polls
# ---------------------------------------------------------------------------

def load_polls(path=os.path.join(HERE, "data", "polls.csv")):
    polls = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            shares = {p: float(r[p]) if r[p] != "" else None for p in PARTIES}
            polls.append({
                "pollster": r["pollster"],
                "end_date": date.fromisoformat(r["end_date"]),
                "sample_size": int(r["sample_size"]),
                "mrp": r["mrp"] == "1",
                "lr": to_log_ratios(shares),
            })
    return polls


def house_effects(polls):
    """
    {pollster: {party: log-ratio effect}}. A poll's gap = its log-ratio minus
    the average of other pollsters' (already debiased) polls fielded within
    HOUSE_EFFECT_WINDOW_DAYS. A pollster's effect is its average gap, shrunk.
    Effects are then centred on the anchor, since the polls can only say how
    pollsters differ from each other, not which of them is right.
    """
    effects = {}
    for _ in range(HOUSE_EFFECT_ITERATIONS):
        gaps = {}   # (pollster, party) -> list of gaps
        for p in polls:
            others = [q for q in polls if q["pollster"] != p["pollster"]
                      and abs((q["end_date"] - p["end_date"]).days) <= HOUSE_EFFECT_WINDOW_DAYS]
            for party, value in p["lr"].items():
                nearby = [q["lr"][party] - effects.get(q["pollster"], {}).get(party, 0.0)
                          for q in others if party in q["lr"]]
                if nearby:
                    gaps.setdefault((p["pollster"], party), []).append(value - sum(nearby) / len(nearby))
        new = {}
        for (pollster, party), g in gaps.items():
            new.setdefault(pollster, {})[party] = (sum(g) / len(g)) * len(g) / (len(g) + HOUSE_EFFECT_SHRINK)
        effects = centre(new, polls)
    return effects


def centre(effects, polls):
    counts = {}
    for p in polls:
        counts[p["pollster"]] = counts.get(p["pollster"], 0) + 1
    if ANCHOR_POLLSTERS:
        anchors = [a for a in ANCHOR_POLLSTERS if a in effects]
    else:
        anchors = [name for name, n in counts.items() if n >= ANCHOR_MIN_POLLS and name in effects]
    for party in PARTIES:
        values = [effects[a][party] for a in anchors if party in effects[a]]
        if not values:
            continue
        shift = sum(values) / len(values)
        for e in effects.values():
            if party in e:
                e[party] -= shift
    return effects


def average(polls, effects, as_of):
    """
    Debiased, weighted average of polls ending on or before as_of.
    Returns ({party: percent}, effective number of polls).
    """
    usable = [p for p in polls if p["end_date"] <= as_of]
    recent_counts = {}
    for p in usable:
        if (as_of - p["end_date"]).days <= HALF_LIFE_DAYS:
            recent_counts[p["pollster"]] = recent_counts.get(p["pollster"], 0) + 1

    sums, weights = {}, {}
    effective = 0.0
    for p in usable:
        recency = 0.5 ** ((as_of - p["end_date"]).days / HALF_LIFE_DAYS)
        damping = max(recent_counts.get(p["pollster"], 1), 1) ** -PROLIFIC_DAMPING
        weight = recency * damping * math.sqrt(min(p["sample_size"], MAX_SAMPLE_SIZE))
        effective += recency * damping
        for party, value in p["lr"].items():
            corrected = value - effects.get(p["pollster"], {}).get(party, 0.0)
            sums[party] = sums.get(party, 0.0) + weight * corrected
            weights[party] = weights.get(party, 0.0) + weight
    if not weights:
        return None, 0.0
    return to_shares({party: sums[party] / weights[party] for party in sums}), effective


def spread(polls, effects, today_avg, as_of):
    """Recency-weighted SD (points) of debiased recent polls around today's average - how noisy each party's polls are."""
    out = {}
    for party in PARTIES:
        total, weight = 0.0, 0.0
        for p in polls:
            if p["end_date"] > as_of or (party != BASE and party not in p["lr"]):
                continue
            corrected = {k: v - effects.get(p["pollster"], {}).get(k, 0.0) for k, v in p["lr"].items()}
            share = to_shares({k: corrected.get(k, math.log(max(today_avg[k], MIN_SHARE) / today_avg[BASE]))
                               for k in PARTIES if k != BASE})[party]
            w = 0.5 ** ((as_of - p["end_date"]).days / HALF_LIFE_DAYS)
            total += w * (share - today_avg[party]) ** 2
            weight += w
        out[party] = math.sqrt(total / weight) if weight else None
    return out


def effects_in_points(effects, today_avg):
    """Turn log-ratio house effects into points: how far each pollster would sit from today's average."""
    today_lr = {p: math.log(today_avg[p] / today_avg[BASE]) for p in PARTIES if p != BASE}
    out = {}
    for pollster, e in effects.items():
        shifted = to_shares({p: v + e.get(p, 0.0) for p, v in today_lr.items()})
        out[pollster] = {p: shifted[p] - today_avg[p] for p in PARTIES}
    return out


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    polls = load_polls()
    effects = house_effects(polls)
    today_avg, effective = average(polls, effects, TODAY)
    noise = spread(polls, effects, today_avg, TODAY)
    raw_avg, _ = average(polls, {}, TODAY)

    write_csv(os.path.join(HERE, "data", "poll_average.csv"), [
        {"party": p, "share": round(today_avg[p], 2), "without_house_effects": round(raw_avg[p], 2),
         "poll_sd": round(noise[p], 2) if noise[p] is not None else ""}
        for p in PARTIES])

    counts = {}
    for p in polls:
        counts[p["pollster"]] = counts.get(p["pollster"], 0) + 1
    points = effects_in_points(effects, today_avg)
    write_csv(os.path.join(HERE, "data", "house_effects.csv"), [
        {"pollster": name, "polls": counts[name], **{p: round(points[name][p], 2) for p in PARTIES}}
        for name in sorted(points, key=lambda n: -counts[n])])

    trend, day = [], TREND_START
    while day <= TODAY:
        shares, eff = average(polls, effects, day)
        if shares:
            trend.append({"date": day.isoformat(), **{p: round(shares[p], 2) for p in PARTIES},
                          "effective_polls": round(eff, 1)})
        day += timedelta(days=TREND_STEP_DAYS)
    write_csv(os.path.join(HERE, "data", "poll_trend.csv"), trend)

    print(f"GB polling average, {TODAY:%d %b %Y} ({len(polls)} polls; effective {effective:.1f})")
    print(f"{'':6}{'share':>7}{'raw':>7}{'poll SD':>9}")
    for p in sorted(PARTIES, key=lambda x: -today_avg[x]):
        print(f"{p:6}{today_avg[p]:7.1f}{raw_avg[p]:7.1f}{noise[p]:9.1f}")
    print("\nHouse effects (points vs average), pollsters with 10+ polls:")
    print(f"{'':22}" + "".join(f"{p:>6}" for p in PARTIES[:5]))
    for name in sorted(points, key=lambda n: -counts[n]):
        if counts[name] >= 10:
            print(f"{name[:21]:22}" + "".join(f"{points[name][p]:+6.1f}" for p in PARTIES[:5]))


if __name__ == "__main__":
    main()
