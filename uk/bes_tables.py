"""
Turn the British Election Study Internet Panel into small "who would vote
for whom" tables for the tactical-voting model.

For each election, from the panel wave fielded just before it, the weighted
average 0-10 "how likely are you ever to vote for <party>" score, by the
party the respondent currently intends to vote for. Written to
uk/data/bes/ptv_tables.csv (git-ignored, like the BES files themselves).

Input: the combined panel file (BES2024_W31_Panel_v31.05.dta - waves 1-31,
3.8 GB). Download it yourself from britishelectionstudy.com (free; you agree
to the BES terms, which don't allow redistributing the data) and pass its
path:

    python uk/bes_tables.py path/to/BES2024_W31_Panel_v31.05.dta

Waves: 5 (2015 campaign), 12 (2017 campaign), 18 (2019 campaign), 27 (just
before the 2024 campaign - the campaign wave, 28, didn't ask these
questions) and 31 (May-June 2026, for the nowcast). The populist-right slot
("Ref") is UKIP in 2015 and 2017, the Brexit Party in 2019 and Reform UK
after.
"""

import csv
import os
import sys

import pandas as pd

OUT = os.path.join(os.path.dirname(__file__), "data", "bes", "ptv_tables.csv")

# election -> (wave, weight variable, {our party: that wave's ptv variable stem})
WAVES = {
    "2015": (5, "wt_full_W5", {"Ref": "ptvUKIP"}),
    "2017": (12, "wt_new_W12", {"Ref": "ptvUKIP"}),
    "2019": (18, "wt_new_W18", {"Ref": "ptvBrexitParty"}),
    "2024": (27, "wt_new_W27", {"Ref": "ptvBrexitParty"}),
    "now": (31, "wt_new_W31", {"Ref": "ptvBrexitParty"}),
}
PTV = {"Lab": "ptvLab", "Con": "ptvCon", "LD": "ptvLD", "Grn": "ptvGrn", "SNP": "ptvSNP", "PC": "ptvPC"}

# Vote-intention answers -> our parties. UKIP counts as Ref only while it
# was the populist-right party (up to 2017).
VOTE = {"Labour": "Lab", "Conservative": "Con", "Liberal Democrat": "LD", "Green Party": "Grn",
        "Scottish National Party (SNP)": "SNP", "Plaid Cymru": "PC", "Brexit Party/Reform UK": "Ref"}
UKIP_VOTE = {"United Kingdom Independence Party (UKIP)": "Ref"}


def score(series):
    """'Very unlikely' -> 0 ... 'Very likely' -> 10; "Don't know" -> missing."""
    return pd.to_numeric(series.astype(str).replace({"Very unlikely": "0", "Very likely": "10"}), errors="coerce")


def wave_columns(wave, weight, ref):
    return [f"generalElectionVoteW{wave}", weight, f"starttimeW{wave}"] + [f"{s}W{wave}" for s in {**PTV, **ref}.values()]


def read(path, chunk=4000):
    """
    Only the needed columns. The file has 13,000+ columns, and pandas would
    otherwise load them all (several GB) before picking these out, so it is
    read a few thousand respondents at a time.
    """
    wanted = [c for wave, weight, ref in WAVES.values() for c in wave_columns(wave, weight, ref)]
    parts = [block[wanted] for block in pd.read_stata(path, chunksize=chunk)]
    return pd.concat(parts, ignore_index=True)


def main(path):
    panel = read(path)
    rows = []
    for election, (wave, weight, ref) in WAVES.items():
        stems = {**PTV, **ref}
        d = panel[wave_columns(wave, weight, ref)]
        d = d[d[f"generalElectionVoteW{wave}"].notna()].copy()
        votes = {**VOTE, **(UKIP_VOTE if election in ("2015", "2017") else {})}
        d["vote"] = d[f"generalElectionVoteW{wave}"].astype(str).map(votes)
        start = d[f"starttimeW{wave}"]
        print(f"{election}: wave {wave}, {start.min():%d %b %Y} - {start.max():%d %b %Y}, {len(d):,} respondents")
        for k in stems:
            mine = d[d["vote"] == k]
            for m, stem in stems.items():
                values = score(mine[f"{stem}W{wave}"])
                ok = values.notna() & mine[weight].notna()
                if ok.sum() < 30:
                    continue
                mean = float((values[ok] * mine.loc[ok, weight]).sum() / mine.loc[ok, weight].sum())
                rows.append({"election": election, "wave": wave, "voters": k, "party": m,
                             "mean_ptv": round(mean, 3), "n": int(ok.sum())})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} cells to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
