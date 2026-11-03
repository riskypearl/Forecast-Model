"""Render the Senate and governor rating maps (1080x1350) - graphics/senate_map.png, governor_map.png

Each state with a race is coloured by its rating (Safe / Likely / Lean / Tilt /
Toss-up); states with no race this year are left grey. Reads results.csv and
governor_results.csv, so they match the latest forecast runs.

State shapes: us-atlas 3.0.1 states-albers-10m (Census Bureau boundaries,
Albers projection with Alaska and Hawaii inset; ISC licence, data/us-atlas/).
"""

import csv
import json
import os

from PIL import Image, ImageDraw

from make_instagram import (W, H, S, PAPER, INK, GRAPHITE, MUTED, BLUE, RED, ROOT,
                            font, digit_mid, text, tracked, rect, footer, masthead, date_label)
from make_house import RATING_ORDER, RATING_COLOUR
from make_governor import EXTRA_NAMES
from make_instagram import STATE_NAMES as _NAMES

STATE_NAMES = {**_NAMES, **EXTRA_NAMES}
CLOSE = 5.0          # races within this margin go in the closest-races list
from datetime import date

NO_RACE = (234, 229, 220)   # paler than toss-up grey
FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE",
        "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA",
        "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
        "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM",
        "36": "NY", "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
        "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
        "54": "WV", "55": "WI", "56": "WY"}


def load_states():
    """{state: [ring, ...]} in the file's projected coordinates (TopoJSON decoded by hand)."""
    topo = json.load(open(os.path.join(ROOT, "data", "us-atlas", "states-albers-10m.json")))
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(indices):
        pts = []
        for i in indices:
            seg = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts += seg[1:] if pts else seg
        return pts

    out = {}
    for g in topo["objects"]["states"]["geometries"]:
        polys = [g["arcs"]] if g["type"] == "Polygon" else g["arcs"]
        out[FIPS[g["id"]]] = [ring(p[0]) for p in polys]   # outer rings; holes are other states
    return out


def draw_map(title, ratings, dem, rep, words, control_line, label, filename, close):
    """close = [(state, candidate favoured, margin Dem-minus-Rep)] for the closest-races list."""
    img = Image.new("RGB", (W * S, H * S), PAPER)
    d = ImageDraw.Draw(img)
    mono = font("GeistMono-Regular.ttf", 15)
    mono_b = font("GeistMono-Bold.ttf", 15)
    mono_sm = font("GeistMono-Regular.ttf", 13)
    serif_big = font("InstrumentSerif-Italic.ttf", 38)
    numeral = font("BigShoulders-Bold.ttf", 150)
    L, R = 72, W - 72

    masthead(d, title, label, mono_b, mono)
    base = 262
    wd = d.textlength(str(dem), font=numeral) / S
    wr = d.textlength(str(rep), font=numeral) / S
    text(d, (L - 4, base), str(dem), numeral, BLUE, "ls")
    dx = L - 4 + wd + 14
    mid = digit_mid(d, numeral)
    rect(d, (dx, base - mid - 3, dx + 28, base - mid + 3), INK)
    xr = dx + 28 + 14
    text(d, (xr, base), str(rep), numeral, RED, "ls")
    bx = xr + wr + 36
    if words:   # None = headline numbers only (the governor map)
        text(d, (bx, 190), words[0], serif_big, BLUE, "ls")
        text(d, (bx, 230), words[1], serif_big, INK, "ls")
        tracked(d, (bx, 262), control_line, mono_b, GRAPHITE, 1.4)

    # --- map, scaled to fit the width ---------------------------------------------------
    shapes = load_states()
    xs = [x for rings in shapes.values() for rg in rings for x, _ in rg]
    ys = [y for rings in shapes.values() for rg in rings for _, y in rg]
    top, bottom = 340, 1080
    k = min((R - L) / (max(xs) - min(xs)), (bottom - top) / (max(ys) - min(ys)))
    ox = L + ((R - L) - (max(xs) - min(xs)) * k) / 2 - min(xs) * k
    oy = top - min(ys) * k
    map_bottom = oy + max(ys) * k
    for st, rings in shapes.items():
        fill = RATING_COLOUR[ratings[st]] if st in ratings else NO_RACE
        for rg in rings:
            d.polygon([((ox + x * k) * S, (oy + y * k) * S) for x, y in rg], fill=fill, outline=PAPER, width=2 * S // 2)

    # --- legend: every rating with its count, plus "no race" ----------------------------
    counts = {r: sum(v == r for v in ratings.values()) for r in RATING_ORDER}
    ly, lx = map_bottom + 60, L
    for i, r in enumerate(RATING_ORDER):
        rect(d, (lx, ly - 10, lx + 10, ly), RATING_COLOUR[r])
        lx += 15 + tracked(d, (lx + 15, ly), f"{r.upper()} {counts[r]}", mono_sm, GRAPHITE, 0.4) + 12
        if r == "Toss-up":
            lx, ly = L, ly + 26
    rect(d, (lx, ly - 10, lx + 10, ly), NO_RACE)
    tracked(d, (lx + 15, ly), "NO RACE", mono_sm, GRAPHITE, 0.4)

    # --- closest races, two columns ------------------------------------------------------
    caps = font("InstrumentSans-Bold.ttf", 15)
    name_f = font("InstrumentSerif-Italic.ttf", 21)
    head_y = ly + 44
    rect(d, (L, head_y, R, head_y + 1), INK)
    tracked(d, (L, head_y + 26), "CLOSEST RACES", mono_b, INK, 2.0)
    col_w, row_h = (R - L - 40) / 2, 34
    per_col = (len(close) + 1) // 2
    for i, (st, name, m) in enumerate(close):
        x = L + (i // per_col) * (col_w + 40)
        y = head_y + 64 + (i % per_col) * row_h
        colour = BLUE if m > 0 else RED
        tracked(d, (x, y), STATE_NAMES[st], caps, INK, 1.0)
        text(d, (x + 190, y + 1), name, name_f, GRAPHITE, "ls")
        text(d, (x + col_w, y), "EVEN" if abs(m) < 0.05 else f"{'D' if m > 0 else 'R'}+{abs(m):.1f}",
             mono_b, colour if abs(m) >= 0.05 else INK, "rs")

    fy = H - 72
    footer(d, fy, mono_sm)
    img = img.resize((W, H), Image.LANCZOS)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    img.save(out)
    print("saved", out, "|", dem, "-", rep, "|", control_line, "|", counts)


def closest(results, favoured):
    rows = [r for r in results.values() if abs(float(r["margin"])) < CLOSE]
    rows.sort(key=lambda r: -float(r["margin"]))
    return [(r["state"], favoured(r).split()[-1], float(r["margin"])) for r in rows]


def main():
    timeline = list(csv.DictReader(open(os.path.join(ROOT, "history", "timeline.csv"))))[-1]
    senate = {r["state"]: r for r in csv.DictReader(open(os.path.join(ROOT, "results.csv")))}
    with open(os.path.join(ROOT, "data", "candidates.csv"), encoding="utf-8", errors="replace") as f:
        names = {r["state"]: r for r in csv.DictReader(f)}
    dem = 34 + sum(float(r["margin"]) > 0 for r in senate.values())
    draw_map("2026 U.S. SENATE FORECAST", {s: r["rating"] for s, r in senate.items()}, dem, 100 - dem,
             ("Democrats favoured", "to win the Senate"),
             f"{round(100 * float(timeline['dem_control_prob']))}% CHANCE OF DEM CONTROL",
             date_label(date.fromisoformat(timeline["date"])), "senate_map.png",
             closest(senate, lambda r: names.get(r["state"], {}).get("dem_candidate" if float(r["margin"]) > 0
                                                                    else "rep_candidate", "")))

    gov = {r["state"]: r for r in csv.DictReader(open(os.path.join(ROOT, "governor_results.csv"), encoding="utf-8"))}
    summary = list(csv.DictReader(open(os.path.join(ROOT, "governor_summary.csv"))))[-1]
    gdem = int(summary["called_dem"])
    draw_map("2026 U.S. GOVERNOR FORECAST", {s: r["rating"] for s, r in gov.items()}, gdem, 50 - gdem,
             None, None,
             date_label(date.fromisoformat(summary["date"])), "governor_map.png",
             closest(gov, lambda r: r["democrat"] if float(r["margin"]) > 0 else r["republican"]))


if __name__ == "__main__":
    main()
