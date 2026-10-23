"""Render the Instagram forecast graphic (1080x1350) - graphics/instagram_forecast.png"""

import os
from PIL import Image, ImageDraw, ImageFont

# Fonts live in graphics/fonts (all SIL Open Font License)
FONTS = os.environ.get("CANVAS_FONTS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
W, H = 1080, 1350
S = 2                      # draw at 2x, then downsample for crisp edges

PAPER = (242, 237, 228)
INK = (24, 26, 31)
GRAPHITE = (92, 94, 100)
MUTED = (150, 146, 138)
RULE = (214, 207, 195)
BLUE = (34, 82, 191)
RED = (196, 52, 52)
BLUE_TINT = (205, 216, 240)
RED_TINT = (240, 210, 208)

import csv
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ELECTION_DAY = date(2026, 11, 3)
COMPETITIVE = 11.0          # races within this many points go on the graphic
SEATS_NOT_UP_D = 34
STATE_NAMES = {
    "AK": "ALASKA", "AL": "ALABAMA", "AR": "ARKANSAS", "CO": "COLORADO", "DE": "DELAWARE", "FL": "FLORIDA",
    "GA": "GEORGIA", "IA": "IOWA", "ID": "IDAHO", "IL": "ILLINOIS", "KS": "KANSAS", "KY": "KENTUCKY",
    "LA": "LOUISIANA", "MA": "MASSACHUSETTS", "ME": "MAINE", "MI": "MICHIGAN", "MN": "MINNESOTA",
    "MS": "MISSISSIPPI", "MT": "MONTANA", "NC": "NORTH CAROLINA", "NE": "NEBRASKA", "NH": "NEW HAMPSHIRE",
    "NJ": "NEW JERSEY", "NM": "NEW MEXICO", "OH": "OHIO", "OK": "OKLAHOMA", "OR": "OREGON",
    "RI": "RHODE ISLAND", "SC": "SOUTH CAROLINA", "SD": "SOUTH DAKOTA", "TN": "TENNESSEE", "TX": "TEXAS",
    "VA": "VIRGINIA", "WV": "WEST VIRGINIA", "WY": "WYOMING",
}
SHORT_NAMES = {"Darline Graham": "D. Graham"}   # avoid confusion with Lindsey Graham


def load_senate():
    """Competitive races, seat call, control chance and date - from the latest forecast run."""
    results = list(csv.DictReader(open(os.path.join(ROOT, "results.csv"))))
    holders = {r["state"]: r["incumbent_party"] for r in csv.DictReader(open(os.path.join(ROOT, "data", "states.csv")))}
    names = {r["state"]: r for r in csv.DictReader(open(os.path.join(ROOT, "data", "candidates.csv"), encoding="cp1252"))}
    timeline = list(csv.DictReader(open(os.path.join(ROOT, "history", "timeline.csv"))))[-1]

    races = []
    for r in results:
        m = float(r["margin"])
        if abs(m) > COMPETITIVE:
            continue
        party = "D" if m > 0 else "R"
        full = names.get(r["state"], {}).get("dem_candidate" if party == "D" else "rep_candidate", "")
        name = SHORT_NAMES.get(full, full.split()[-1] if full else "")
        races.append((STATE_NAMES[r["state"]], name, party, abs(m), party != holders[r["state"]]))
    races.sort(key=lambda x: (x[2] == "R", -x[3] if x[2] == "D" else x[3]))
    dem_seats = SEATS_NOT_UP_D + sum(float(r["margin"]) > 0 for r in results)
    run_date = date.fromisoformat(timeline["date"])
    label = f"{run_date.day} {run_date.strftime('%b').upper()} {run_date.year}  ·  {(ELECTION_DAY - run_date).days} DAYS OUT"
    return races, dem_seats, 100 - dem_seats, round(100 * float(timeline["dem_control_prob"])), label


# Type style. "swiss" (Archivo) is the default; "ledger" is the original set. The others swap every font through
# STYLES (file, variable-font axes, size factor) so all the graphics change together.
# Choose with the GRAPHICS_STYLE environment variable.
STYLE = os.environ.get("GRAPHICS_STYLE", "swiss")
FRANKLIN, SERIF, ARCHIVO = "LibreFranklin-Variable.ttf", "SourceSerif4-Variable.ttf", "Archivo-Variable.ttf"
STYLES = {
    "newspaper": {   # Franklin Gothic labels, Source Serif names - US newspaper data desk
        "GeistMono-Regular.ttf": (FRANKLIN, lambda sz: [400], 1.0),
        "GeistMono-Bold.ttf": (FRANKLIN, lambda sz: [700], 1.0),
        "InstrumentSans-Bold.ttf": (FRANKLIN, lambda sz: [700], 1.0),
        "InstrumentSerif-Italic.ttf": (SERIF, lambda sz: [400, min(max(sz, 8), 60)], 0.82),
        "BigShoulders-Bold.ttf": (FRANKLIN, lambda sz: [800], 0.72),
    },
    "swiss": {       # one family: Archivo, extra-condensed black for the big numbers
        "GeistMono-Regular.ttf": (ARCHIVO, lambda sz: [400, 100], 1.0),
        "GeistMono-Bold.ttf": (ARCHIVO, lambda sz: [700, 100], 1.0),
        "InstrumentSans-Bold.ttf": (ARCHIVO, lambda sz: [700, 100], 1.0),
        "InstrumentSerif-Italic.ttf": (ARCHIVO, lambda sz: [400, 100], 0.8),
        "BigShoulders-Bold.ttf": (ARCHIVO, lambda sz: [900, 62], 0.95),
    },
}
TRACKING_SCALE = {"ledger": 1.0}.get(STYLE, 0.35)   # proportional fonts need far less letter-spacing


def font(name, size):
    if STYLE in STYLES:
        file, axes, scale = STYLES[STYLE][name]
        f = ImageFont.truetype(os.path.join(FONTS, file), round(size * scale * S))
        f.set_variation_by_axes(axes(size * scale))
        return f
    return ImageFont.truetype(os.path.join(FONTS, name), size * S)


def digit_mid(d, f):
    """Height above the baseline of the middle of a digit - where the dash between numbers sits."""
    return -d.textbbox((0, 0), "0", font=f, anchor="ls")[1] / S / 2


def text(d, xy, s, f, fill, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)


def tracked(d, xy, s, f, fill, tracking, anchor="l"):
    """Letter-spaced small caps. anchor l / r for the run's left or right edge."""
    tracking *= TRACKING_SCALE
    widths = [d.textlength(c, font=f) for c in s]
    total = sum(widths) + tracking * S * (len(s) - 1)
    x = xy[0] * S if anchor == "l" else xy[0] * S - total
    for c, w in zip(s, widths):
        d.text((x, xy[1] * S), c, font=f, fill=fill, anchor="ls")
        x += w + tracking * S
    return total / S


def rect(d, box, fill):
    d.rectangle([v * S for v in box], fill=fill)


def rounded(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([v * S for v in box], radius=r * S, fill=fill, outline=outline, width=width * S)


def main():
    RACES, DEM_SEATS, REP_SEATS, CONTROL, DATE_LABEL = load_senate()
    n_dem_rows = sum(r[2] == "D" for r in RACES)
    img = Image.new("RGB", (W * S, H * S), PAPER)
    d = ImageDraw.Draw(img)

    mono = font("GeistMono-Regular.ttf", 15)
    mono_b = font("GeistMono-Bold.ttf", 15)
    mono_sm = font("GeistMono-Regular.ttf", 13)
    caps = font("InstrumentSans-Bold.ttf", 17)
    serif_i = font("InstrumentSerif-Italic.ttf", 25)
    serif_big = font("InstrumentSerif-Italic.ttf", 40)
    numeral = font("BigShoulders-Bold.ttf", 250)

    L, R = 72, W - 72

    # --- masthead ---------------------------------------------------------
    tracked(d, (L, 96), "2026 U.S. SENATE FORECAST", mono_b, INK, 2.2)
    tracked(d, (R, 96), DATE_LABEL, mono, GRAPHITE, 1.6, anchor="r")
    rect(d, (L, 112, R, 113), INK)

    # --- verdict -------------------------------------------------------------
    base = 352
    w52 = d.textlength(str(DEM_SEATS), font=numeral) / S
    w48 = d.textlength(str(REP_SEATS), font=numeral) / S
    x = L - 6
    dash_w, dash_gap = 46, 22
    text(d, (x, base), str(DEM_SEATS), numeral, BLUE, "ls")
    dash_x = x + w52 + dash_gap
    mid = digit_mid(d, numeral)
    rect(d, (dash_x, base - mid - 4, dash_x + dash_w, base - mid + 4), INK)
    x48 = dash_x + dash_w + dash_gap
    text(d, (x48, base), str(REP_SEATS), numeral, RED, "ls")

    right_block_x = x48 + w48 + 40
    text(d, (right_block_x, 226), "Democrats", serif_big, BLUE, "ls")
    text(d, (right_block_x, 268), "favoured to win", serif_big, INK, "ls")
    text(d, (right_block_x, 310), "the Senate", serif_big, INK, "ls")
    tracked(d, (right_block_x, 348), f"{CONTROL}% CHANCE OF DEM CONTROL", mono_b, GRAPHITE, 1.6)

    # --- race ledger -----------------------------------------------------------
    head_y = 412
    rect(d, (L, head_y, R, head_y + 1), INK)
    tracked(d, (L, head_y + 26), "COMPETITIVE RACES", mono_b, INK, 2.0)
    tracked(d, (R, head_y + 26), "PROJECTED MARGIN", mono, GRAPHITE, 1.6, anchor="r")

    col_state, col_name = L, L + 232
    axis = 690                       # centre of the diverging bars
    half = 132                       # bar room either side of the axis
    scale = half / 11.0
    col_margin = R
    row_h, y0 = 50, head_y + 52
    split_gap = 22

    for i, (state, name, party, margin, flip) in enumerate(RACES):
        y = y0 + i * row_h + (split_gap if party == "R" else 0)
        colour = BLUE if party == "D" else RED
        tint = BLUE_TINT if party == "D" else RED_TINT
        mid = y + row_h / 2

        tracked(d, (col_state, mid + 6), state, caps, INK, 1.2)
        text(d, (col_name, mid + 8), name, serif_i, GRAPHITE, "ls")

        # faint full-scale track, then the bar from the axis outward
        rect(d, (axis - half, mid - 1, axis + half, mid), RULE)
        length = max(margin * scale, 4)
        if party == "D":
            rect(d, (axis - length, mid - 6, axis, mid + 6), colour)
        else:
            rect(d, (axis, mid - 6, axis + length, mid + 6), colour)

        label = f"{'D' if party == 'D' else 'R'}+{margin:.1f}"
        text(d, (col_margin, mid + 6), label, mono_b, colour, "rs")
        if flip:
            fx = col_margin - 92
            rounded(d, (fx - 48, mid - 11, fx, mid + 11), 11, fill=tint)
            text(d, (fx - 24, mid + 5), "FLIP", mono_sm, colour, "ms")

        if i < len(RACES) - 1:
            nxt = RACES[i + 1]
            if not (party == "D" and nxt[2] == "R"):
                rect(d, (L, y + row_h, R, y + row_h + 0.6), RULE)

    # axis spine and the tipping point between the two blocs
    first_mid = y0 + row_h / 2 - 16
    last_mid = y0 + (len(RACES) - 1) * row_h + split_gap + row_h / 2 + 16
    rect(d, (axis - 0.5, first_mid, axis + 0.5, last_mid), INK)
    split_y = y0 + n_dem_rows * row_h + split_gap / 2
    rect(d, (L, split_y - 0.5, R, split_y + 0.5), INK)
    label_w = tracked(d, (-1000, -1000), "TIPPING POINT", mono_sm, INK, 1.6)   # measure only
    lx = axis - label_w / 2
    rect(d, (lx - 12, split_y - 9, lx + label_w + 12, split_y + 9), PAPER)
    tracked(d, (lx, split_y + 4.5), "TIPPING POINT", mono_sm, INK, 1.6)

    # --- footer ------------------------------------------------------------------
    fy = H - 72
    rect(d, (L, fy - 26, R, fy - 25), INK)
    tracked(d, (L, fy), "WEIGHTED POLLS + FUNDAMENTALS", mono_sm, GRAPHITE, 1.2)
    tracked(d, (R, fy), "@AFCWILL10 ON X", mono_sm, GRAPHITE, 1.2, anchor="r")

    img = img.resize((W, H), Image.LANCZOS)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instagram_forecast.png")
    img.save(out)
    print("saved", out, "|", DATE_LABEL, "|", DEM_SEATS, "-", REP_SEATS, f"| {CONTROL}% |", len(RACES), "races")


if __name__ == "__main__":
    main()
