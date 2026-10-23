"""Render the House forecast graphic (1080x1350) - graphics/house_forecast.png

Reads house_results.csv and house_seat_distribution.csv, so it always matches
the latest run of house_forecast.py.
"""

import csv
import os

from PIL import Image, ImageDraw

from make_instagram import (W, H, S, PAPER, INK, GRAPHITE, MUTED, RULE, BLUE, RED, BLUE_TINT, RED_TINT,
                            font, text, tracked, rect, rounded)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _date_label():
    """'21 OCT 2026  ·  13 DAYS OUT' from the date of the latest forecast run."""
    import csv as _csv
    from datetime import date as _date
    last = list(_csv.DictReader(open(os.path.join(ROOT, "history", "timeline.csv"))))[-1]["date"]
    d = _date.fromisoformat(last)
    return f"{d.day} {d.strftime('%b').upper()} {d.year}  ·  {(_date(2026, 11, 3) - d).days} DAYS OUT"


DATE_LABEL = _date_label()

RATING_ORDER = ["Safe D", "Likely D", "Lean D", "Tilt D", "Toss-up", "Tilt R", "Lean R", "Likely R", "Safe R"]
RATING_COLOUR = {
    "Safe D": BLUE, "Likely D": (88, 125, 212), "Lean D": (142, 168, 226), "Tilt D": (192, 207, 239),
    "Toss-up": (205, 199, 188),
    "Tilt R": (240, 199, 196), "Lean R": (226, 142, 140), "Likely R": (211, 99, 97), "Safe R": RED,
}


# Multi-word surnames that "last word" would cut short
COMPOUND_SURNAMES = ["Trone Garriott", "De La Cruz", "Costa Honeycutt", "Padilla Stout", "Benitez-Thompson"]


def surname(name):
    for compound in COMPOUND_SURNAMES:
        if name.endswith(compound):
            return compound
    parts = [p for p in name.replace(",", "").split() if p.rstrip(".") not in ("Jr", "Sr", "II", "III", "IV")]
    return parts[-1] if parts else name


def load():
    rows = list(csv.DictReader(open(os.path.join(ROOT, "house_results.csv"), encoding="utf-8")))
    dist = [(int(r["dem_seats"]), float(r["probability"]))
            for r in csv.DictReader(open(os.path.join(ROOT, "house_seat_distribution.csv")))]
    for r in rows:
        r["p"] = float(r["dem_win_prob"])
        r["m"] = float(r["margin"])
    return rows, dist


def summary(dist):
    avg = sum(k * p for k, p in dist)
    control = sum(p for k, p in dist if k >= 218)
    cum, lo, hi = 0.0, None, None
    for k, p in sorted(dist):
        cum += p
        lo = k if lo is None and cum >= 0.10 else lo
        hi = k if hi is None and cum >= 0.90 else hi
    return round(avg), control, lo, hi


def margin_label(m):
    if abs(m) < 0.05:
        return "EVEN", INK
    return (f"D+{m:.1f}", BLUE) if m > 0 else (f"R+{-m:.1f}", RED)


def main():
    rows, dist = load()
    assert len(rows) == 435
    dem_avg, control, lo, hi = summary(dist)
    counts = {k: sum(r["rating"] == k for r in rows) for k in RATING_ORDER}
    assert sum(counts.values()) == 435

    img = Image.new("RGB", (W * S, H * S), PAPER)
    d = ImageDraw.Draw(img)
    mono = font("GeistMono-Regular.ttf", 15)
    mono_b = font("GeistMono-Bold.ttf", 15)
    mono_sm = font("GeistMono-Regular.ttf", 13)
    mono_sm_b = font("GeistMono-Bold.ttf", 13)
    caps = font("InstrumentSans-Bold.ttf", 16)
    serif_i = font("InstrumentSerif-Italic.ttf", 23)
    serif_big = font("InstrumentSerif-Italic.ttf", 38)
    numeral = font("BigShoulders-Bold.ttf", 196)
    L, R = 72, W - 72

    # --- masthead ---------------------------------------------------------------
    tracked(d, (L, 96), "2026 U.S. HOUSE FORECAST", mono_b, INK, 2.2)
    tracked(d, (R, 96), DATE_LABEL, mono, GRAPHITE, 1.6, anchor="r")
    rect(d, (L, 112, R, 113), INK)

    # --- verdict -------------------------------------------------------------------
    base = 318
    dem_txt, rep_txt = str(dem_avg), str(435 - dem_avg)
    wd = d.textlength(dem_txt, font=numeral) / S
    wr = d.textlength(rep_txt, font=numeral) / S
    x = L - 5
    text(d, (x, base), dem_txt, numeral, BLUE, "ls")
    dash_x = x + wd + 18
    rect(d, (dash_x, base - 82, dash_x + 36, base - 75), INK)
    xr = dash_x + 36 + 18
    text(d, (xr, base), rep_txt, numeral, RED, "ls")
    bx = xr + wr + 36
    assert bx + 250 < R, "headline too wide"
    text(d, (bx, 206), "Democrats", serif_big, BLUE, "ls")
    text(d, (bx, 246), "favoured to win", serif_big, INK, "ls")
    text(d, (bx, 286), "the House", serif_big, INK, "ls")
    tracked(d, (bx, 318), f"{control:.0%} CHANCE OF DEM CONTROL", mono_b, GRAPHITE, 1.4)
    tracked(d, (L, 350), f"PROJECTED AVERAGE  ·  80% RANGE {lo}-{hi} DEM SEATS",
            mono_sm, MUTED, 1.3)

    # --- 435 tiles, column by column, ordered Safe D -> Safe R ------------------------
    ordered = sorted(rows, key=lambda r: (RATING_ORDER.index(r["rating"]), -r["p"]))
    top, rows_n, cols_n, gap = 380, 5, 87, 2.0
    tile = ((R - L) - (cols_n - 1) * gap) / cols_n
    for i, r in enumerate(ordered):
        col, row = divmod(i, rows_n)
        tx, ty = L + col * (tile + gap), top + row * (tile + gap)
        rect(d, (tx, ty, tx + tile, ty + tile), RATING_COLOUR[r["rating"]])
    block_bottom = top + rows_n * (tile + gap) - gap
    # majority line: seat 218 sits in column (218-1)//5
    mx = L + ((218 - 1) // rows_n) * (tile + gap) + tile / 2
    rect(d, (mx - 0.6, top - 12, mx + 0.6, block_bottom + 12), INK)
    tracked(d, (mx + 8, top - 6), "218 FOR MAJORITY", mono_sm, INK, 1.2)

    # legend with counts
    ly = block_bottom + 36
    lx = L
    for k in RATING_ORDER:
        label = f"{k.replace(' D', '').replace(' R', '').upper()} {counts[k]}"   # colour shows the party
        rect(d, (lx, ly - 10, lx + 10, ly), RATING_COLOUR[k])
        w = tracked(d, (lx + 15, ly), label, mono_sm, GRAPHITE, 0.6)
        lx += 15 + w + 15
    assert lx - 15 <= R + 1, "legend too wide"

    # --- ledger of the closest races --------------------------------------------------
    head_y = ly + 34
    rect(d, (L, head_y, R, head_y + 1), INK)
    tracked(d, (L, head_y + 24), "CLOSEST RACES", mono_b, INK, 2.0)
    tracked(d, (R, head_y + 24), "PROJECTED MARGIN", mono, GRAPHITE, 1.6, anchor="r")

    close = sorted((r for r in rows if r["rating"] in ("Tilt D", "Toss-up", "Tilt R")), key=lambda r: -r["m"])
    col_code, col_name, axis, half = L, L + 112, 655, 105
    scale = half / 3.0
    # up to 20 rows of 28px fit with the lean lists; more close races -> tighter rows
    row_h, y0 = min(28, 572 // max(len(close), 1)), head_y + 38
    for i, r in enumerate(close):
        y = y0 + i * row_h
        mid = y + row_h / 2
        favoured_d = r["m"] > 0 if abs(r["m"]) >= 0.05 else r["p"] >= 0.5
        holder_d = r["holder"] == "DEM"
        name = surname(r["democrat"] if favoured_d else r["republican"])
        tracked(d, (col_code, mid + 5), r["district"], caps, INK, 1.0)
        text(d, (col_name, mid + 7), name, serif_i, GRAPHITE, "ls")
        tracked(d, (col_name + 190, mid + 5), r["rating"].upper(), mono_sm, MUTED, 1.0)
        rect(d, (axis - half, mid - 0.5, axis + half, mid + 0.5), RULE)
        length = min(abs(r["m"]) * scale, half)
        if r["m"] > 0:
            rect(d, (axis - max(length, 2), mid - 5, axis, mid + 5), BLUE)
        elif r["m"] < 0:
            rect(d, (axis, mid - 5, axis + max(length, 2), mid + 5), RED)
        label, colour = margin_label(r["m"])
        text(d, (R, mid + 5), label, mono_b, colour, "rs")
        if abs(r["m"]) >= 0.05 and favoured_d != holder_d:
            fx = R - 84
            tint, c = (BLUE_TINT, BLUE) if favoured_d else (RED_TINT, RED)
            rounded(d, (fx - 46, mid - 10, fx, mid + 10), 10, fill=tint)
            text(d, (fx - 23, mid + 4.5), "FLIP", mono_sm, c, "ms")
        if i < len(close) - 1:
            rect(d, (L, y + row_h, R, y + row_h + 0.6), RULE)
    rect(d, (axis - 0.5, y0 - 4, axis + 0.5, y0 + len(close) * row_h + 4), INK)

    # --- lean lists -----------------------------------------------------------------------
    y = y0 + len(close) * row_h + 30
    for rating, colour in (("Lean D", BLUE), ("Lean R", RED)):
        codes = [r["district"] for r in sorted(rows, key=lambda r: -r["p"]) if r["rating"] == rating]
        label_w = tracked(d, (L, y), f"{rating.upper()} ({len(codes)})", mono_sm_b, colour, 1.2)
        x, start = L + 128, L + 128
        for c in codes:
            w = d.textlength(c, font=mono_sm) / S
            if x + w > R:
                x, y = start, y + 22
            text(d, (x, y), c, mono_sm, GRAPHITE, "ls")
            x += w + 14
        y += 30

    # --- footer ---------------------------------------------------------------------------
    fy = H - 72
    assert y < fy - 40, "content runs into footer"
    rect(d, (L, fy - 26, R, fy - 25), INK)
    tracked(d, (L, fy), "WEIGHTED POLLS + FUNDAMENTALS", mono_sm, GRAPHITE, 1.2)
    tracked(d, (R, fy), "@AFCWILL10 ON X", mono_sm, GRAPHITE, 1.2, anchor="r")

    img = img.resize((W, H), Image.LANCZOS)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "house_forecast.png")
    img.save(out)
    print("saved", out, "| headline", dem_avg, "-", 435 - dem_avg, f"| control {control:.1%}",
          "| close races", len(close))


if __name__ == "__main__":
    main()
