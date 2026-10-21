"""Render the House forecast on real 2026 district shapes (1080x1350) - graphics/house_shapes.png

Shapes: ElectIndex redistricting/current.geojson (local only, no licence), except
Missouri, where that file has the court-blocked 2025 map - Missouri uses the
2022 map from the Census Bureau (TIGERweb, 119th Congress, public domain).
Colours: each district's rating from house_results.csv.
"""

import json
import math
import os

from PIL import Image, ImageChops, ImageDraw

from make_instagram import W, H, S, PAPER, INK, GRAPHITE, MUTED, BLUE, RED, font, text, tracked, rect
from make_house import RATING_ORDER, RATING_COLOUR, DATE_LABEL, load, summary

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "electindex")


def albers(lat0, lat1, lat2, lon0):
    """Albers equal-area conic projection -> function (lon, lat) -> (x, y)."""
    p1, p2, p0 = (math.radians(v) for v in (lat1, lat2, lat0))
    n = (math.sin(p1) + math.sin(p2)) / 2
    c = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    rho0 = math.sqrt(c - 2 * n * math.sin(p0)) / n

    def project(lon, lat):
        theta = n * math.radians(lon - lon0)
        rho = math.sqrt(c - 2 * n * math.sin(math.radians(lat))) / n
        return rho * math.sin(theta), -(rho0 - rho * math.cos(theta))   # y down
    return project


def main_islands(ring):
    """Drop the uninhabited Northwestern Hawaiian Islands (west of 161W) - clutter on a map."""
    lon, lat = ring[0]
    return not (lat < 30 and lon < -161)


def outer_rings(geometry):
    """Exterior rings only (holes are other districts' enclaves, drawn on their own)."""
    rings = [geometry["coordinates"][0]] if geometry["type"] == "Polygon" else [p[0] for p in geometry["coordinates"]]
    return [r for r in rings if main_islands(r)]


def load_shapes():
    shapes = {}
    for f in json.load(open(os.path.join(DATA, "current.geojson"), encoding="utf-8"))["features"]:
        code = f["properties"]["district_code"]
        if not code.startswith("MO-"):
            shapes[code] = outer_rings(f["geometry"])
    for f in json.load(open(os.path.join(DATA, "mo_2022.geojson"), encoding="utf-8"))["features"]:
        shapes[f"MO-{int(f['properties']['CD119']):02d}"] = outer_rings(f["geometry"])
    return shapes


def fit(projected, box):
    """Scale + offset so all projected rings fit inside box (x0, y0, x1, y1), keeping aspect."""
    xs = [x for rings in projected.values() for ring in rings for x, _ in ring]
    ys = [y for rings in projected.values() for ring in rings for _, y in ring]
    x0, y0, x1, y1 = box
    k = min((x1 - x0) / (max(xs) - min(xs)), (y1 - y0) / (max(ys) - min(ys)))
    ox = x0 + ((x1 - x0) - (max(xs) - min(xs)) * k) / 2 - min(xs) * k
    oy = y0 + ((y1 - y0) - (max(ys) - min(ys)) * k) / 2 - min(ys) * k
    return lambda x, y: (x * k + ox, y * k + oy)


def main():
    rows, dist = load()
    rating = {r["district"]: r["rating"] for r in rows}
    shapes = load_shapes()
    assert set(shapes) == set(rating), set(shapes) ^ set(rating)
    dem_avg, control, lo, hi = summary(dist)

    img = Image.new("RGB", (W * S, H * S), PAPER)
    d = ImageDraw.Draw(img)
    mono = font("GeistMono-Regular.ttf", 15)
    mono_b = font("GeistMono-Bold.ttf", 15)
    mono_sm = font("GeistMono-Regular.ttf", 13)
    serif_big = font("InstrumentSerif-Italic.ttf", 38)
    numeral = font("BigShoulders-Bold.ttf", 150)
    L, R = 72, W - 72

    # --- masthead + verdict (same as the other graphics) ---------------------------------
    tracked(d, (L, 96), "2026 U.S. HOUSE FORECAST", mono_b, INK, 2.2)
    tracked(d, (R, 96), DATE_LABEL, mono, GRAPHITE, 1.6, anchor="r")
    rect(d, (L, 112, R, 113), INK)
    base = 262
    dem_txt, rep_txt = str(dem_avg), str(435 - dem_avg)
    wd = d.textlength(dem_txt, font=numeral) / S
    wr = d.textlength(rep_txt, font=numeral) / S
    text(d, (L - 4, base), dem_txt, numeral, BLUE, "ls")
    dx = L - 4 + wd + 14
    rect(d, (dx, base - 63, dx + 28, base - 57), INK)
    xr = dx + 28 + 14
    text(d, (xr, base), rep_txt, numeral, RED, "ls")
    bx = xr + wr + 36
    text(d, (bx, 190), "Democrats favoured", serif_big, BLUE, "ls")
    text(d, (bx, 230), "to win the House", serif_big, INK, "ls")
    tracked(d, (bx, 262), f"{control:.0%} CHANCE OF DEM CONTROL", mono_b, GRAPHITE, 1.4)
    tracked(d, (L, 298), f"AVERAGE OF 10,000 SIMULATIONS  ·  80% RANGE {lo}-{hi} DEM SEATS",
            mono_sm, MUTED, 1.1)

    # --- projections -------------------------------------------------------------------------
    lower48 = albers(37.5, 29.5, 45.5, -96)
    alaska = albers(50, 55, 65, -154)
    hawaii = albers(3, 8, 18, -157)

    def project_all(codes, proj):
        out = {}
        for c in codes:
            out[c] = [[proj(lon - 360 if lon > 0 else lon, lat) for lon, lat in ring] for ring in shapes[c]]
        return out

    main_codes = [c for c in shapes if not c.startswith(("AK", "HI"))]
    main_proj = project_all(main_codes, lower48)
    ak_proj = project_all([c for c in shapes if c.startswith("AK")], alaska)
    hi_proj = project_all([c for c in shapes if c.startswith("HI")], hawaii)

    map_box = (L, 340, R, 1000)
    to_px = fit(main_proj, map_box)
    ak_px = fit(ak_proj, (L, 870, L + 190, 1000))
    hi_px = fit(hi_proj, (L + 205, 905, L + 375, 1000))

    land = Image.new("L", img.size, 0)          # where districts are drawn = land
    land_d = ImageDraw.Draw(land)

    def draw(projected, to_screen):
        for code, rings in projected.items():
            colour = RATING_COLOUR[rating[code]]
            for ring in rings:
                pts = [tuple(v * S for v in to_screen(x, y)) for x, y in ring]
                if len(pts) >= 3:
                    d.polygon(pts, fill=colour, outline=PAPER, width=1)
                    land_d.polygon(pts, fill=255)

    draw(main_proj, to_px)
    draw(ak_proj, ak_px)
    draw(hi_proj, hi_px)

    # state borders on top (Census, public domain)
    border = (60, 62, 68)
    lines = Image.new("L", img.size, 0)          # state borders, kept only over land
    lines_d = ImageDraw.Draw(lines)
    states = json.load(open(os.path.join(DATA, "states.geojson"), encoding="utf-8"))["features"]
    for f in states:
        st = f["properties"]["STUSAB"]
        if st in ("AS", "GU", "MP", "PR", "VI", "DC"):
            continue
        proj, screen = (alaska, ak_px) if st == "AK" else (hawaii, hi_px) if st == "HI" else (lower48, to_px)
        geom = f["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for poly in polys:
            for ring in (r for r in poly if main_islands(r)):
                pts = [tuple(v * S for v in screen(*proj(lon - 360 if lon > 0 else lon, lat))) for lon, lat in ring]
                if len(pts) >= 2:
                    lines_d.line(pts + [pts[0]], fill=255, width=2, joint="curve")
    img.paste(Image.new("RGB", img.size, border), (0, 0), ImageChops.multiply(lines, land))

    # --- legend ---------------------------------------------------------------------------
    counts = {k: sum(r["rating"] == k for r in rows) for k in RATING_ORDER}
    ly, lx = 1060, L
    for k in RATING_ORDER:
        label = f"{k.upper()} {counts[k]}"
        rect(d, (lx, ly - 10, lx + 10, ly), RATING_COLOUR[k])
        lx += 15 + tracked(d, (lx + 15, ly), label, mono_sm, GRAPHITE, 0.4) + 12
        if k == "Toss-up":
            lx, ly = L, ly + 26
    assert lx <= R

    note_y = ly + 46
    flips = [r for r in rows if (r["p"] >= 0.5) != (r["holder"] == "DEM")]
    d_gain = sum(r["p"] >= 0.5 for r in flips)
    tracked(d, (L, note_y), f"PROJECTED FLIPS: {d_gain} TO DEMOCRATS, {len(flips) - d_gain} TO REPUBLICANS",
            mono_b, INK, 1.4)
    tracked(d, (L, note_y + 24), "2026 DISTRICT LINES  ·  EACH DISTRICT COLOURED BY ITS RATING",
            mono_sm, MUTED, 1.2)

    fy = H - 72
    assert note_y + 24 < fy - 40
    rect(d, (L, fy - 26, R, fy - 25), INK)
    tracked(d, (L, fy), "UNBIASED POLLS + PAST ELECTION RESULTS · 10,000 SIMULATED ELECTIONS", mono_sm, GRAPHITE, 1.2)
    tracked(d, (R, fy), "@AFCWILL10 ON X", mono_sm, GRAPHITE, 1.2, anchor="r")

    img = img.resize((W, H), Image.LANCZOS)
    img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "house_shapes.png"))
    print(f"saved house_shapes.png | districts {len(shapes)} | flips D {d_gain} R {len(flips) - d_gain}")


if __name__ == "__main__":
    main()
