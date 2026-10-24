"""
Download 2021 Census demographics for every England and Wales constituency
and save shares to:

  uk/data/census_2021.csv                 2024 boundaries (575 seats)
  uk/data/census_2021_old_boundaries.csv  2010-2024 boundaries (573 seats),
                                          for the 2010-2019 elections

Source: the ONS census API (api.beta.ons.gov.uk), area types "p19wpc" (the
post-2019 review constituencies first used in July 2024: 543 in England, 32
in Wales) and "wpc" (the previous ones). Open Government Licence. The 2021
census is used for the 2010-2019 elections too: it is a decade late for
2010, but how seats differ from each other changes slowly.

Scotland's census was a year later (2022) and is published by Scotland's
Census, not the ONS, so the 57 Scottish seats are not covered yet. Northern
Ireland isn't modelled.

Run it with:  python uk/fetch_census.py
"""

import csv
import json
import os
import urllib.request
from collections import defaultdict

API = "https://api.beta.ons.gov.uk/v1/population-types/{pop}/census-observations?area-type={area}&dimensions={dim}"
DATA = os.path.join(os.path.dirname(__file__), "data")
AREA_TYPES = {"census_2021.csv": "p19wpc", "census_2021_old_boundaries.csv": "wpc"}

# Each output column = share of the people (or households) in the listed
# categories, out of everyone the question applies to ("Does not apply",
# code -8, is left out of the total).
#   (population type, ONS dimension, {column: [category codes]})
VARIABLES = [
    ("UR", "highest_qualification", {
        "degree": ["5"],                 # Level 4+, of residents aged 16+ (3 = apprenticeship, 4 = Level 3)
        "no_quals": ["0"],
    }),
    ("UR", "ns_sec_10a", {
        "professional": ["1", "2"],      # managerial / professional, of residents 16+
        "routine": ["6", "7"],
        "students": ["9"],
    }),
    ("UR", "ethnic_group_tb_6a", {
        "white": ["4"],
        "asian": ["1"],
        "black": ["2"],
    }),
    ("UR", "religion_tb", {
        "no_religion": ["1"],
        "christian": ["2"],
        "muslim": ["6"],
    }),
    ("HH", "hh_tenure_5a", {
        "own_outright": ["0"],           # of households
        "owned": ["0", "1"],
        "social_rent": ["2"],
        "private_rent": ["3"],
    }),
]

# Age bands are built from single years of age, as shares of adults (18+),
# since only adults vote.
AGE_BANDS = {"age_18_34": (18, 34), "age_65_plus": (65, 200)}


def fetch(pop, dim, area):
    """Returns {constituency code: {category code: count}} and {code: name}."""
    req = urllib.request.Request(API.format(pop=pop, dim=dim, area=area), headers={"User-Agent": "senate-forecast/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    counts, names = defaultdict(dict), {}
    for obs in data["observations"]:
        area, category = obs["dimensions"]
        counts[area["option_id"]][category["option_id"]] = obs["observation"]
        names[area["option_id"]] = area["option"]
    return counts, names


def main():
    for filename, area in AREA_TYPES.items():
        save(area, os.path.join(DATA, filename))


def save(area, out):
    rows = defaultdict(dict)
    for pop, dim, columns in VARIABLES:
        counts, names = fetch(pop, dim, area)
        for code, by_category in counts.items():
            total = sum(n for c, n in by_category.items() if c != "-8")
            rows[code]["name"] = names[code]
            for column, categories in columns.items():
                rows[code][column] = round(sum(by_category.get(c, 0) for c in categories) / total, 4)
        print(f"{dim}: {len(counts)} constituencies")

    counts, _ = fetch("UR", "resident_age_101a", area)
    for code, by_age in counts.items():
        ages = {int(a): n for a, n in by_age.items() if a.isdigit()}   # 100 = "100 and over"
        adults = sum(n for a, n in ages.items() if a >= 18)
        rows[code]["adults"] = adults
        for column, (lo, hi) in AGE_BANDS.items():
            rows[code][column] = round(sum(n for a, n in ages.items() if lo <= a <= hi) / adults, 4)
    print(f"resident_age_101a: {len(counts)} constituencies")

    fields = ["ons_code", "name", "adults", *AGE_BANDS] + [c for _, _, cols in VARIABLES for c in cols]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for code in sorted(rows):
            writer.writerow({"ons_code": code, **rows[code]})
    print(f"Saved {len(rows)} constituencies to {out}")


if __name__ == "__main__":
    main()
