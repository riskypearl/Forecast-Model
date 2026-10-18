"""
2026 US Senate forecast.

All margins are Dem minus Rep, in points: +5 means Democrat wins by 5,
-5 means Republican wins by 5.

Run it with:  python forecast.py
"""

import csv
import math
import os
import random
from datetime import date
from statistics import NormalDist

# ---------------------------------------------------------------------------
# ASSUMPTIONS - these are your judgement calls. Change them and re-run.
# ---------------------------------------------------------------------------

# How much each past presidential election counts towards a state's lean.
# High 2024 weight = betting the 2024 shifts are permanent.
LEAN_WEIGHTS = {2024: 0.75, 2020: 0.175, 2016: 0.075}

# National presidential margins, used to turn a state's result into a lean.
NATIONAL_MARGIN = {2024: -1.5, 2020: 4.5, 2016: 2.1}

# The national environment: the generic-ballot average (Dem minus Rep).
# None = calculate it from data/gcb_polls.csv. Put a number here to override.
NATIONAL_ENVIRONMENT = None
GCB_HALF_LIFE_DAYS = 14    # same as race polls - late in a campaign, recent polls matter most
# Reputable pollsters (rating 2.0+ of 3.0) are the yardstick: every other
# pollster's lean is measured against them and removed before averaging.
GCB_MIN_POLLSTER_WEIGHT = 2.0 / 3.0
GCB_HOUSE_EFFECT_WINDOW_DAYS = 14   # compare each poll with reputable polls this close in time

# Demographic reversion: the share of each group's 2020->2024 swing that
# snaps back in 2026. 0 = the 2024 shifts are permanent, 1 = they fully undo.
# (ElectIndex's methodology page says 0.25; its data notes say 0.5.)
DEMOGRAPHIC_REVERSION = 0.25

# Points an incumbent gets just for being the incumbent.
INCUMBENCY_BONUS = 2.5
# Appointed senators (never won the seat themselves) historically get less.
APPOINTED_INCUMBENCY_BONUS = 1.25

# Polls: more polls -> trust them more, up to this cap.
MAX_POLL_WEIGHT = 0.85
POLL_HALF_LIFE_DAYS = 14   # a poll this old counts half as much as one from today
HOUSE_EFFECT_SHRINK = 3    # bigger = more sceptical of house effects from few polls

# Polls paid for by a party-aligned group (DEM / REP sponsor) count for this much.
# 1.0 = treat them like any other poll, 0 = ignore them completely.
PARTISAN_POLL_WEIGHT = 0.5

# Likely voters are the best guess at who actually turns up.
POPULATION_WEIGHT = {"lv": 1.0, "rv": 0.8, "v": 0.8, "a": 0.5}

# Pollster quality: data/pollster_ratings.csv (columns: pollster,rating,banned).
# Ratings are scaled so the best pollster = 1.0. Pollsters not listed get this
# weight - roughly middle of the scale, so an unknown pollster isn't treated
# as top quality.
DEFAULT_POLLSTER_WEIGHT = 0.5

# Uncertainty. A national error moves every race the same way (polls miss
# together); a state error is specific to one race.
NATIONAL_ERROR_SD = 3.0
STATE_ERROR_SD_POLLED = 4.0     # a race with plenty of recent polls
STATE_ERROR_SD_UNPOLLED = 8.0   # a race with none - fundamentals only
# Further from election day, more can change. Added on top, per day remaining.
NATIONAL_SD_PER_DAY = 0.03
STATE_SD_PER_DAY = 0.05
SIMULATIONS = 10_000
# Fat tails: errors drawn from a t-distribution with this many degrees of
# freedom, so big upsets are less rare than a normal curve says.
# Lower = fatter tails; very large (e.g. 1000) = basically a normal curve.
TAIL_DF = 5
ELECTION_DAY = date(2026, 11, 3)

# Senate seats NOT up in 2026 (Dem total includes the two independents who
# caucus with them). Republicans hold the VP, so Dems need 51 for control.
SEATS_NOT_UP = {"D": 34, "R": 31}
DEM_SEATS_NEEDED = 51

TODAY = date.today()
DAYS_LEFT = max((ELECTION_DAY - TODAY).days, 0)


# ---------------------------------------------------------------------------
# STEP 1: partisan lean - how much more Dem/Rep a state is than the country
# ---------------------------------------------------------------------------

def partisan_lean(row):
    total = 0.0
    for year, weight in LEAN_WEIGHTS.items():
        state_margin = float(row[f"pres_{year}"])
        total += weight * (state_margin - NATIONAL_MARGIN[year])
    return total / sum(LEAN_WEIGHTS.values())


# ---------------------------------------------------------------------------
# STEP 2: fundamentals - what we'd expect before looking at any race polls
# ---------------------------------------------------------------------------

def fundamentals(row, lean, environment, demo):
    incumbency = 0.0
    if row["incumbent_running"] == "1":
        bonus = APPOINTED_INCUMBENCY_BONUS if row.get("incumbent_appointed") == "1" else INCUMBENCY_BONUS
        incumbency = bonus if row["incumbent_party"] == "D" else -bonus
    return lean + environment + demo + incumbency + float(row["candidate_adj"])


# ---------------------------------------------------------------------------
# STEP 2b: demographic adjustment - groups that swung hard in 2024 partly
# swing back, so states full of those groups move more
# ---------------------------------------------------------------------------

def load_demographics():
    """Returns ({state: {group: share}}, {group: swing}) or None if files are missing."""
    try:
        composition = {r["state"]: {g: float(v) for g, v in r.items() if g != "state"}
                       for r in load_csv("data/demographics.csv")}
        swings = {r["group"]: float(r["swing_2020_2024"]) for r in load_csv("data/group_swings.csv")}
    except FileNotFoundError:
        print("No data/demographics.csv - skipping the demographic adjustment "
              "(run fetch_demographics.py).")
        return None
    return composition, swings


def demographic_adjustment(state, demographics):
    """
    A state's expected swing = each group's share of adults x that group's
    2020->2024 swing. We only care how this state differs from the country
    (the national mood is already in the environment), so subtract the
    national figure, then reverse the chosen fraction of it.
    """
    if demographics is None:
        return 0.0
    composition, swings = demographics

    def expected_swing(shares):
        return sum(shares[g] * swings.get(g, 0.0) for g in shares)

    relative = expected_swing(composition[state]) - expected_swing(composition["US"])
    return -DEMOGRAPHIC_REVERSION * relative


# ---------------------------------------------------------------------------
# STEP 3: polling average - newer and bigger polls count for more
# ---------------------------------------------------------------------------

def polling_average(polls, pollster_weights, half_life=POLL_HALF_LIFE_DAYS, as_of=None):
    """
    Returns (average margin, effective number of polls). Old polls barely
    count, so a race with 20 polls from last year and none this month has an
    effective count near zero - the model then leans on the fundamentals.
    """
    if not polls:
        return None, 0.0
    weighted_sum = 0.0
    total_weight = 0.0
    effective_polls = 0.0
    for poll in polls:
        age_days = ((as_of or TODAY) - date.fromisoformat(poll["end_date"])).days
        recency = 0.5 ** (age_days / half_life)
        quality = pollster_weight(poll["pollster"], pollster_weights)
        quality *= POPULATION_WEIGHT.get(poll.get("population", "lv"), 0.8)
        if poll.get("partisan") in ("DEM", "REP"):
            quality *= PARTISAN_POLL_WEIGHT
        size = math.sqrt(float(poll["sample_size"]))
        weight = recency * quality * size
        margin = float(poll["dem_pct"]) - float(poll["rep_pct"])
        weighted_sum += weight * margin
        total_weight += weight
        effective_polls += recency * quality
    if total_weight == 0:
        return None, 0.0
    return weighted_sum / total_weight, effective_polls


def allocate_undecided(polls, baselines):
    """
    Undecided voters "come home": they split the way the state usually votes
    (its baseline = lean + national environment + demographics), not 50/50.
    Candidate quality is left out of the baseline on purpose - a weak
    candidate already shows up in how the decided voters answer.
    """
    out = []
    for p in polls:
        q = dict(p)
        undecided = float(p.get("undecided") or 0)
        baseline = baselines.get(p["state"], 0.0)
        dem_share = min(max(0.5 + baseline / 200, 0.0), 1.0)
        q["dem_pct"] = float(p["dem_pct"]) + undecided * dem_share
        q["rep_pct"] = float(p["rep_pct"]) + undecided * (1 - dem_share)
        out.append(q)
    return out


def house_effects(polls):
    """
    De-biasing. Some pollsters lean consistently one way. A pollster's house
    effect is how far its polls sit, on average, from the other polls of the
    same race. With only a few polls we can't be sure, so the estimate is
    shrunk towards zero (HOUSE_EFFECT_SHRINK).
    """
    by_state = {}
    for p in polls:
        by_state.setdefault(p["state"], []).append(p)

    gaps = {}  # pollster -> list of (its margin - average of the others)
    for state_polls in by_state.values():
        for p in state_polls:
            others = [q for q in state_polls if q["pollster"] != p["pollster"]]
            if not others:
                continue
            others_avg = sum(float(q["dem_pct"]) - float(q["rep_pct"]) for q in others) / len(others)
            margin = float(p["dem_pct"]) - float(p["rep_pct"])
            gaps.setdefault(p["pollster"], []).append(margin - others_avg)

    effects = {}
    for pollster, g in gaps.items():
        n = len(g)
        effects[pollster] = (sum(g) / n) * n / (n + HOUSE_EFFECT_SHRINK)
    return effects


def debias(polls, effects):
    adjusted = []
    for p in polls:
        shift = effects.get(p["pollster"], 0.0)
        q = dict(p)
        # move the poll's margin back towards the consensus, split evenly
        q["dem_pct"] = float(p["dem_pct"]) - shift / 2
        q["rep_pct"] = float(p["rep_pct"]) + shift / 2
        adjusted.append(q)
    return adjusted


def poll_weight(num_polls):
    # 0 polls -> 0, 4 polls -> half of the cap, many polls -> close to the cap
    return MAX_POLL_WEIGHT * num_polls / (num_polls + 4)


# ---------------------------------------------------------------------------
# STEP 4: rating from win probability
# ---------------------------------------------------------------------------

def state_error_sd(poll_weight_used, days_left=None):
    """
    How uncertain one race is. Slides from the unpolled SD to the polled SD
    as the polls get more weight, then widens with days left.
    """
    polled_share = poll_weight_used / MAX_POLL_WEIGHT
    base = STATE_ERROR_SD_UNPOLLED + (STATE_ERROR_SD_POLLED - STATE_ERROR_SD_UNPOLLED) * polled_share
    days = DAYS_LEFT if days_left is None else days_left
    return math.sqrt(base ** 2 + (STATE_SD_PER_DAY * days) ** 2)


def national_error_sd(days_left=None):
    days = DAYS_LEFT if days_left is None else days_left
    return math.sqrt(NATIONAL_ERROR_SD ** 2 + (NATIONAL_SD_PER_DAY * days) ** 2)


def fat_tailed_error(sd):
    """A random error with standard deviation sd, from a t-distribution."""
    z = random.gauss(0, 1)
    chi2 = random.gammavariate(TAIL_DF / 2, 2)
    t = z / math.sqrt(chi2 / TAIL_DF)
    return sd * t * math.sqrt((TAIL_DF - 2) / TAIL_DF)   # rescale so the SD stays sd


def rating(dem_win_prob):
    p = dem_win_prob
    if p >= 0.95: return "Safe D"
    if p >= 0.75: return "Likely D"
    if p >= 0.60: return "Lean D"
    if p > 0.40:  return "Toss-up"
    if p > 0.25:  return "Lean R"
    if p > 0.05:  return "Likely R"
    return "Safe R"


# ---------------------------------------------------------------------------
# Run the model
# ---------------------------------------------------------------------------

def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def national_environment(pollster_weights):
    """Generic-ballot average from data/gcb_polls.csv (see generic_ballot_average)."""
    if NATIONAL_ENVIRONMENT is not None:
        return NATIONAL_ENVIRONMENT
    try:
        rows = load_csv("data/gcb_polls.csv")
    except FileNotFoundError:
        print("No data/gcb_polls.csv - assuming an even national environment (D+0).")
        return 0.0
    return generic_ballot_average(rows, pollster_weights, TODAY)


def generic_ballot_average(rows, pollster_weights, as_of):
    """
    Rows need: pollster, end_date, dem, rep, n, and optionally population, lean.

    1. Undecided voters split evenly nationally, so each poll's margin is
       scaled up as if everyone had decided (a 44-36 poll counts as 55-45).
    2. House effects: each pollster's typical lean is measured against
       reputable pollsters polling at the same time, and removed. A pollster
       that usually runs 4 points more Republican and shows D+5 counts as D+9.
    3. Every non-banned pollster is then averaged, weighted by quality.
    """
    polls = []
    for r in rows:
        if date.fromisoformat(r["end_date"]) > as_of:
            continue
        dem, rep = float(r["dem"]), float(r["rep"])
        lean = r.get("lean", "").upper()
        polls.append({
            "pollster": r["pollster"], "end_date": r["end_date"],
            "margin": 100 * (dem - rep) / (dem + rep),
            "sample_size": r["n"],
            "population": r.get("population") or "lv",
            "partisan": "DEM" if lean.startswith("D") else "REP" if lean.startswith("R") else "",
        })

    reputable = [(date.fromisoformat(p["end_date"]), p["margin"]) for p in polls
                 if pollster_weight(p["pollster"], pollster_weights) >= GCB_MIN_POLLSTER_WEIGHT]
    gaps = {}
    for p in polls:
        d = date.fromisoformat(p["end_date"])
        nearby = [m for rd, m in reputable if abs((rd - d).days) <= GCB_HOUSE_EFFECT_WINDOW_DAYS]
        if len(nearby) >= 3:
            gaps.setdefault(p["pollster"], []).append(p["margin"] - sum(nearby) / len(nearby))
    effects = {name: (sum(g) / len(g)) * len(g) / (len(g) + HOUSE_EFFECT_SHRINK) for name, g in gaps.items()}

    for p in polls:
        corrected = p["margin"] - effects.get(p["pollster"], 0.0)
        p["dem_pct"], p["rep_pct"] = 50 + corrected / 2, 50 - corrected / 2
    average, _ = polling_average(polls, pollster_weights, GCB_HALF_LIFE_DAYS, as_of)
    return 0.0 if average is None else average


def load_pollster_weights(path):
    """
    Accepts either a 'weight' column (0-1) or a 'rating' column (higher =
    better, scaled so the best pollster gets 1.0). Pollsters with banned=1
    (suspected fake / fabricated polls) get 0 and are ignored.
    """
    try:
        rows = load_csv(path)
    except FileNotFoundError:
        return {}
    weights = {}
    ratings = [float(r["rating"]) for r in rows if r.get("rating")]
    best = max(ratings) if ratings else 1.0
    for r in rows:
        if r.get("banned") and float(r["banned"]) == 1:
            weights[r["pollster"]] = 0.0
        elif r.get("weight"):
            weights[r["pollster"]] = float(r["weight"])
        elif r.get("rating"):
            weights[r["pollster"]] = float(r["rating"]) / best
    return weights


def pollster_weight(name, pollster_weights):
    """
    Exact match first. Joint polls ("Fabrizio Ward/Impact Research") get the
    average of whichever partners are rated - but a banned partner bans the poll.
    """
    if name in pollster_weights:
        return pollster_weights[name]
    partners = [pollster_weights[p.strip()] for p in name.split("/") if p.strip() in pollster_weights]
    if not partners:
        return DEFAULT_POLLSTER_WEIGHT
    if 0.0 in partners:
        return 0.0
    return sum(partners) / len(partners)


def main():
    states = load_csv("data/states.csv")
    pollster_weights = load_pollster_weights("data/pollster_ratings.csv")
    environment = national_environment(pollster_weights)
    demographics = load_demographics()

    leans = {row["state"]: partisan_lean(row) for row in states}
    demos = {row["state"]: demographic_adjustment(row["state"], demographics) for row in states}
    baselines = {st: leans[st] + environment + demos[st] for st in leans}

    polls = load_csv("data/polls.csv")
    polls = allocate_undecided(polls, baselines)
    effects = house_effects(polls)
    polls = debias(polls, effects)

    races = []
    for row in states:
        lean, demo = leans[row["state"]], demos[row["state"]]
        fund = fundamentals(row, lean, environment, demo)
        state_polls = [p for p in polls if p["state"] == row["state"]]
        poll_avg, n = polling_average(state_polls, pollster_weights)
        w = poll_weight(n)
        margin = fund if poll_avg is None else (1 - w) * fund + w * poll_avg
        races.append({
            "state": row["state"], "lean": lean, "demo": demo, "fundamentals": fund,
            "poll_avg": poll_avg, "num_polls": n, "poll_weight": w,
            "margin": margin, "sd": state_error_sd(w), "dem_wins": 0,
        })

    # STEP 5: simulate the election many times. Each simulation draws one
    # national error shared by every race, plus a separate error per race.
    dem_seat_counts = []
    national_sd = national_error_sd()
    for _ in range(SIMULATIONS):
        national_error = fat_tailed_error(national_sd)
        dem_seats = SEATS_NOT_UP["D"]
        for race in races:
            result = race["margin"] + national_error + fat_tailed_error(race["sd"])
            if result > 0:
                race["dem_wins"] += 1
                dem_seats += 1
        dem_seat_counts.append(dem_seats)

    for race in races:
        race["dem_prob"] = race["dem_wins"] / SIMULATIONS
        race["rating"] = rating(race["dem_prob"])

    summary = summarise(dem_seat_counts, races)
    print_results(races, summary, environment)
    save_results(races, summary, environment)


def fmt_margin(m):
    if m is None:
        return "-"
    return f"D+{m:.1f}" if m >= 0 else f"R+{-m:.1f}"


def summarise(dem_seat_counts, races):
    ordered = sorted(dem_seat_counts)
    # Polls-only: who'd win if every polling average were exactly right
    # (races with no polls fall back to their fundamentals).
    polls_only = SEATS_NOT_UP["D"] + sum(
        1 for r in races if (r["poll_avg"] if r["poll_avg"] is not None else r["fundamentals"]) > 0)
    return {
        "distribution": {seats: ordered.count(seats) / SIMULATIONS for seats in sorted(set(ordered))},
        "polls_only": polls_only,
        "avg_dem": sum(ordered) / SIMULATIONS,
        "low": ordered[int(0.1 * SIMULATIONS)],
        "high": ordered[int(0.9 * SIMULATIONS)],
        "dem_control": sum(1 for s in ordered if s >= DEM_SEATS_NEEDED) / SIMULATIONS,
    }


def print_results(races, summary, environment):
    print(f"\n2026 Senate forecast  ({TODAY}, {DAYS_LEFT} days out, "
          f"national environment {fmt_margin(environment)})\n")
    print(f"{'State':<6}{'Lean':>8}{'Demo':>7}{'Fund.':>8}{'Polls':>8}{'#':>6}{'Margin':>9}{'+/-':>6}{'Dem win':>9}  Rating")
    print("-" * 81)
    for r in sorted(races, key=lambda r: r["margin"], reverse=True):
        print(f"{r['state']:<6}{fmt_margin(r['lean']):>8}{r['demo']:>+7.1f}{fmt_margin(r['fundamentals']):>8}"
              f"{fmt_margin(r['poll_avg']):>8}{r['num_polls']:>6.1f}{fmt_margin(r['margin']):>9}"
              f"{r['sd']:>6.1f}{r['dem_prob']:>8.0%}  {r['rating']}")

    print("-" * 81)
    print(f"Average outcome: {summary['avg_dem']:.1f} D - {100 - summary['avg_dem']:.1f} R")
    print(f"80% range for Dem seats: {summary['low']} to {summary['high']}")
    print(f"Chance Democrats win control: {summary['dem_control']:.0%}")
    print(f"Chance Republicans keep control: {1 - summary['dem_control']:.0%}")
    print(f"If every polling average were exactly right: {summary['polls_only']} D - {100 - summary['polls_only']} R\n")

    print("Chance of each outcome (simulated):")
    for seats, prob in sorted(summary["distribution"].items(), reverse=True):
        if prob < 0.005:
            continue
        control = "D control" if seats >= DEM_SEATS_NEEDED else "R control"
        print(f"  {seats} D - {100 - seats} R  {prob:>5.1%}  {'#' * round(prob * 100)}  ({control})")
    print()


def save_results(races, summary, environment):
    """
    Writes results.csv (latest run), a dated copy in history/, and one line
    per day in history/timeline.csv - so you can show how the forecast moved.
    """
    header = ["state", "lean", "demo", "fundamentals", "poll_avg", "num_polls",
              "poll_weight", "margin", "sd", "dem_win_prob", "rating"]
    rows = [[r["state"], round(r["lean"], 2), round(r["demo"], 2), round(r["fundamentals"], 2),
             "" if r["poll_avg"] is None else round(r["poll_avg"], 2),
             round(r["num_polls"], 2), round(r["poll_weight"], 2), round(r["margin"], 2),
             round(r["sd"], 2), round(r["dem_prob"], 3), r["rating"]] for r in races]

    os.makedirs("history", exist_ok=True)
    for path in ("results.csv", f"history/{TODAY}.csv"):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

    for path in ("seat_distribution.csv", f"history/{TODAY}_seats.csv"):
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["dem_seats", "rep_seats", "probability"])
            for seats, prob in sorted(summary["distribution"].items()):
                writer.writerow([seats, 100 - seats, round(prob, 4)])

    # Timeline: one row per date; re-running on the same day replaces that day.
    timeline_path = "history/timeline.csv"
    timeline = load_csv(timeline_path) if os.path.exists(timeline_path) else []
    timeline = [t for t in timeline if t["date"] != str(TODAY)]
    timeline.append({
        "date": str(TODAY), "environment": round(environment, 2),
        "avg_dem_seats": round(summary["avg_dem"], 2),
        "dem_seats_low": summary["low"], "dem_seats_high": summary["high"],
        "dem_control_prob": round(summary["dem_control"], 3),
        "polls_only_dem_seats": summary["polls_only"],
    })
    timeline.sort(key=lambda t: t["date"])
    with open(timeline_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(timeline[0].keys()))
        writer.writeheader()
        writer.writerows(timeline)


if __name__ == "__main__":
    main()
