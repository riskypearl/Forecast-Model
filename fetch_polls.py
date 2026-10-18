"""
Download every 2026 Senate general-election poll into data/polls.csv, and
every national generic-ballot poll ("Democrat or Republican for Congress?")
into data/gcb_polls.csv - the generic ballot sets the national environment.

Source: PollResults.org, which republishes the New York Times poll database
under CC BY 4.0 (credit "Poll data from the New York Times" if you publish).

Run it with:  python fetch_polls.py
"""

import csv
import json
import urllib.parse
import urllib.request
from datetime import datetime

API = "https://api.pollresults.org/v1.0/politics/results/"
ELECTION_DATE = "2026-11-03"

# Prefer likely voters, then registered voters, then all adults.
POPULATION_ORDER = ["lv", "rv", "v", "a"]

# Some polls don't list a sample size. Rather than drop them, give them a
# cautious size so they count, but less than a typical poll.
DEFAULT_SAMPLE_SIZE = 600


def fetch_all(office):
    polls, cursor = [], None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        url = API + office + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "senate-forecast/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.load(resp)
        polls += page["results"]
        cursor = page.get("cursor")
        if not cursor or not page["results"]:
            return polls


def pick_question(poll):
    """A poll can ask several versions of the question. Take the likely-voter one."""
    questions = [q for q in poll["questions"] if q["stage"] == "general"]
    if not questions:
        return None

    def rank(q):
        pop = q["population"]
        order = POPULATION_ORDER.index(pop) if pop in POPULATION_ORDER else len(POPULATION_ORDER)
        return (order, -(q["sampleSize"] or 0))

    return min(questions, key=rank)


def two_sides(answers):
    """
    Return (dem_pct, rep_pct). Where there is no Democrat (e.g. Nebraska, where
    independent Dan Osborn is the main challenger) the strongest non-Republican
    candidate counts as the Dem side.
    """
    candidates = [a for a in answers if a["party"] != "NONE"]
    reps = [a["pct"] for a in candidates if a["party"] == "REP"]
    dems = [a["pct"] for a in candidates if a["party"] == "DEM"]
    if not dems:
        dems = [a["pct"] for a in candidates if a["party"] != "REP"]
    if not reps or not dems:
        return None
    return max(dems), max(reps)


def undecided_share(answers):
    """
    "Don't know" answers, plus anything unaccounted for (a poll whose answers
    add to 85% left 15% undecided or refused without listing them). Voters
    choosing "someone else" or "would not vote" are not undecided.
    """
    explicit = sum(a["pct"] for a in answers
                   if a["party"] == "NONE" and (a["answer"].startswith("Don't know") or a["answer"].startswith("DK")))
    unlisted = max(0.0, 100 - sum(a["pct"] for a in answers))
    return round(explicit + unlisted, 1)


def main():
    with open("data/states.csv", newline="") as f:
        our_states = {row["state"] for row in csv.DictReader(f)}

    raw = fetch_all("senate")
    rows, skipped = [], 0
    for poll in raw:
        if poll["state"] not in our_states or poll["electionDate"] != ELECTION_DATE or poll["hypothetical"]:
            skipped += 1
            continue
        q = pick_question(poll)
        sides = two_sides(q["answers"]) if q else None
        if not sides:
            skipped += 1
            continue
        end_date = datetime.strptime(poll["endDate"], "%m/%d/%y").date()
        rows.append({
            "state": poll["state"],
            "pollster": poll["displayName"] or poll["pollster"],
            "end_date": end_date.isoformat(),
            "dem_pct": sides[0],
            "rep_pct": sides[1],
            "undecided": undecided_share(q["answers"]),
            "sample_size": q["sampleSize"] or DEFAULT_SAMPLE_SIZE,
            "population": q["population"],
            "partisan": poll["partisan"],   # DEM / REP = sponsored by a partisan group
        })

    rows.sort(key=lambda r: (r["state"], r["end_date"]))
    with open("data/polls.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Senate: downloaded {len(raw)} polls, saved {len(rows)}, skipped {skipped}.")

    save_generic_ballot()


def save_generic_ballot():
    """
    Generic-ballot polls are in the House feed with state "US". Saved in the
    column format forecast.py reads (pollster, end_date, dem, rep, n, lean).
    Undecided voters are left out: nationally they're assumed to split evenly,
    which leaves the margin unchanged.
    """
    rows = []
    for poll in fetch_all("house"):
        if poll["state"] != "US" or poll["electionDate"] != ELECTION_DATE:
            continue
        q = pick_question(poll)
        sides = two_sides(q["answers"]) if q else None
        if not sides:
            continue
        rows.append({
            "pollster": poll["displayName"] or poll["pollster"],
            "end_date": datetime.strptime(poll["endDate"], "%m/%d/%y").date().isoformat(),
            "dem": sides[0],
            "rep": sides[1],
            "n": q["sampleSize"] or DEFAULT_SAMPLE_SIZE,
            "population": q["population"],
            "lean": {"DEM": "D", "REP": "R"}.get(poll["partisan"], ""),
        })

    rows.sort(key=lambda r: r["end_date"])
    with open("data/gcb_polls.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generic ballot: saved {len(rows)} polls.")


if __name__ == "__main__":
    main()
