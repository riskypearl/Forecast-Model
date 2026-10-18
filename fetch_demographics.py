"""
Download each state's adult (18+) population by race/ethnicity from the 2020
Census into data/demographics.csv.

Needs a free Census API key: https://api.census.gov/data/key_signup.html
Then run (PowerShell):
    $env:CENSUS_API_KEY = "your-key"; python fetch_demographics.py
"""

import csv
import json
import os
import urllib.parse
import urllib.request

# 2020 Census redistricting table P4: Hispanic origin by race, age 18+.
VARIABLES = {
    "P4_001N": "total",
    "P4_002N": "hispanic",
    "P4_005N": "white",      # non-Hispanic, white alone
    "P4_006N": "black",      # non-Hispanic, Black alone
    "P4_008N": "asian",      # non-Hispanic, Asian alone
}

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}


def query(geography, key):
    params = {"get": "NAME," + ",".join(VARIABLES), "for": geography, "key": key}
    url = "https://api.census.gov/data/2020/dec/pl?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "senate-forecast/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        header, *rows = json.load(resp)
    return [dict(zip(header, row)) for row in rows]


def shares(row):
    counts = {name: int(row[var]) for var, name in VARIABLES.items()}
    total = counts.pop("total")
    out = {group: n / total for group, n in counts.items()}
    out["other"] = 1 - sum(out.values())   # Native, Pacific, multiracial, other
    return out


def main():
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        raise SystemExit("Set CENSUS_API_KEY first - see the top of this file.")

    rows = [("US", shares(query("us:1", key)[0]))]
    for row in query("state:*", key):
        if row["NAME"] in STATE_ABBR:
            rows.append((STATE_ABBR[row["NAME"]], shares(row)))

    groups = ["white", "black", "hispanic", "asian", "other"]
    with open("data/demographics.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["state"] + groups)
        for state, s in sorted(rows):
            writer.writerow([state] + [round(s[g], 4) for g in groups])
    print(f"Saved {len(rows)} rows to data/demographics.csv")


if __name__ == "__main__":
    main()
