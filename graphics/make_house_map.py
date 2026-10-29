"""Render the House district cartogram (1080x1350) - graphics/house_map.png

Every district is one equal-sized square, grouped into its state; states sit on
a tile grid that follows rough US geography. A cartogram rather than a
geographic map: equal squares don't let big rural districts dominate, and it
needs no district outlines (several states have new 2026 lines).
Reads house_results.csv, so it matches the latest house_forecast.py run.
"""

import math
from collections import defaultdict

from PIL import Image, ImageDraw

from make_instagram import W, H, S, PAPER, INK, GRAPHITE, MUTED, BLUE, RED, font, digit_mid, text, tracked, rect
from make_house import RATING_ORDER, RATING_COLOUR, DATE_LABEL, load, summary

# (column, row) of each state on a geographic tile grid
GRID = {
    "AK": (0, 0), "ME": (11, 0),
    "WI": (6, 1), "VT": (10, 1), "NH": (11, 1),
    "WA": (1, 2), "ID": (2, 2), "MT": (3, 2), "ND": (4, 2), "MN": (5, 2), "IL": (6, 2), "MI": (7, 2),
    "NY": (9, 2), "MA": (10, 2),
    "OR": (1, 3), "NV": (2, 3), "WY": (3, 3), "SD": (4, 3), "IA": (5, 3), "IN": (6, 3), "OH": (7, 3),
    "PA": (8, 3), "NJ": (9, 3), "CT": (10, 3), "RI": (11, 3),
    "CA": (1, 4), "UT": (2, 4), "CO": (3, 4), "NE": (4, 4), "MO": (5, 4), "KY": (6, 4), "WV": (7, 4),
    "VA": (8, 4), "MD": (9, 4), "DE": (10, 4),
    "AZ": (2, 5), "NM": (3, 5), "KS": (4, 5), "AR": (5, 5), "TN": (6, 5), "NC": (7, 5), "SC": (8, 5),
    "OK": (4, 6), "LA": (5, 6), "MS": (6, 6), "AL": (7, 6), "GA": (8, 6),
    "HI": (0, 7), "TX": (4, 7), "FL": (9, 7),
}


def block_shape(n):
    """Columns x rows of squares for a state with n districts - roughly square."""
    cols = math.ceil(math.sqrt(n))
    return cols, math.ceil(n / cols)


def main():
    rows, dist = load()
    dem_avg, control, lo, hi = summary(dist)
    by_state = defaultdict(list)
    for r in rows:
        by_state[r["district"][:2]].append(r)
    assert set(by_state) == set(GRID) - {"DC"}, set(by_state) ^ set(GRID)
    assert sum(len(v) for v in by_state.values()) == 435

    img = Image.new("RGB", (W * S, H * S), PAPER)
    d = ImageDraw.Draw(img)
    mono = font("GeistMono-Regular.ttf", 15)
    mono_b = font("GeistMono-Bold.ttf", 15)
    mono_sm = font("GeistMono-Regular.ttf", 13)
    label_f = font("GeistMono-Bold.ttf", 11)
    serif_big = font("InstrumentSerif-Italic.ttf", 38)
    numeral = font("BigShoulders-Bold.ttf", 150)
    L, R = 72, W - 72

    # --- masthead + verdict --------------------------------------------------------
    tracked(d, (L, 96), "2026 U.S. HOUSE FORECAST", mono_b, INK, 2.2)
    tracked(d, (R, 96), DATE_LABEL, mono, GRAPHITE, 1.6, anchor="r")
    rect(d, (L, 112, R, 113), INK)
    base = 262
    dem_txt, rep_txt = str(dem_avg), str(435 - dem_avg)
    wd = d.textlength(dem_txt, font=numeral) / S
    wr = d.textlength(rep_txt, font=numeral) / S
    text(d, (L - 4, base), dem_txt, numeral, BLUE, "ls")
    dx = L - 4 + wd + 14
    mid = digit_mid(d, numeral)
    rect(d, (dx, base - mid - 3, dx + 28, base - mid + 3), INK)
    xr = dx + 28 + 14
    text(d, (xr, base), rep_txt, numeral, RED, "ls")
    bx = xr + wr + 36
    text(d, (bx, 190), "Democrats favoured", serif_big, BLUE, "ls")
    text(d, (bx, 230), "to win the House", serif_big, INK, "ls")
    tracked(d, (bx, 262), f"{control:.0%} CHANCE OF DEM CONTROL", mono_b, GRAPHITE, 1.4)
    tracked(d, (L, 298), f"PROJECTED AVERAGE  ·  80% RANGE {lo}-{hi} DEM SEATS  ·  1 SQUARE = 1 DISTRICT",
            mono_sm, MUTED, 1.1)

    # --- cartogram ----------------------------------------------------------------------
    shapes = {s: block_shape(len(v)) for s, v in by_state.items()}
    ncols = max(c for c, _ in GRID.values()) + 1
    nrows = max(r for _, r in GRID.values()) + 1
    col_w = [max((shapes[s][0] for s, (c, _) in GRID.items() if c == col and s in shapes), default=1)
             for col in range(ncols)]
    row_h = [max((shapes[s][1] for s, (_, r) in GRID.items() if r == row and s in shapes), default=1)
             for row in range(nrows)]
    label_room = 1.2                      # in squares, under each block for the state label
    gap_units = 0.9                       # space between state cells, in squares
    total_w = sum(col_w) + gap_units * (ncols - 1)
    total_h = sum(row_h) + (gap_units + label_room) * nrows
    map_top, map_bottom = 330, 1150
    unit = min((R - L) / total_w, (map_bottom - map_top) / total_h)
    sq_gap = max(unit * 0.14, 1.2)
    x_off = L + ((R - L) - total_w * unit) / 2

    col_x = [x_off + (sum(col_w[:c]) + gap_units * c) * unit for c in range(ncols)]
    row_y = [map_top + (sum(row_h[:r]) + (gap_units + label_room) * r) * unit for r in range(nrows)]

    content_bottom = map_top
    for s, districts in by_state.items():
        c, r = GRID[s]
        cols, rws = shapes[s]
        # centre the block in its grid cell
        bx0 = col_x[c] + (col_w[c] - cols) * unit / 2
        by0 = row_y[r] + (row_h[r] - rws) * unit
        ordered = sorted(districts, key=lambda x: (RATING_ORDER.index(x["rating"]), -x["p"]))
        for i, dd in enumerate(ordered):
            cc, rr = i % cols, i // cols
            x0, y0 = bx0 + cc * unit, by0 + rr * unit
            rect(d, (x0, y0, x0 + unit - sq_gap, y0 + unit - sq_gap), RATING_COLOUR[dd["rating"]])
        tracked(d, (bx0 + (cols * unit - sq_gap) / 2 - 7, by0 + rws * unit + 12), s, label_f, GRAPHITE, 0.8)
        content_bottom = max(content_bottom, by0 + rws * unit + 12)

    # --- legend ------------------------------------------------------------------------
    counts = {k: sum(x["rating"] == k for x in rows) for k in RATING_ORDER}
    # straight under the map rather than down by the footer, so it survives Instagram's crop
    ly, lx = content_bottom + 44, L
    for k in RATING_ORDER:
        label = f"{k.upper()} {counts[k]}"
        rect(d, (lx, ly - 10, lx + 10, ly), RATING_COLOUR[k])
        lx += 15 + tracked(d, (lx + 15, ly), label, mono_sm, GRAPHITE, 0.4) + 12
        if k == "Toss-up":
            lx, ly = L, ly + 26
    assert lx <= R

    fy = H - 72
    rect(d, (L, fy - 26, R, fy - 25), INK)
    tracked(d, (L, fy), "WEIGHTED POLLS, FUNDAMENTALS AND CANDIDATE RECORDS", mono_sm, GRAPHITE, 1.2)
    tracked(d, (R, fy), "@AFCWILL10 ON X", mono_sm, GRAPHITE, 1.2, anchor="r")

    img = img.resize((W, H), Image.LANCZOS)
    img.save("house_map.png")
    print("saved house_map.png | unit", round(unit, 1), "px | states", len(by_state))


if __name__ == "__main__":
    main()
