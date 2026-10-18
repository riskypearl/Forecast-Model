"""Render the Instagram forecast graphic (1080x1350) - graphics/instagram_forecast.png"""

import os
from PIL import Image, ImageDraw, ImageFont

FONTS = os.environ.get("CANVAS_FONTS", "")
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

RACES = [  # state, candidate, party, margin, flip
    ("NEW HAMPSHIRE", "Pappas", "D", 10.3, False),
    ("MINNESOTA", "Flanagan", "D", 10.2, False),
    ("MICHIGAN", "El-Sayed", "D", 7.2, False),
    ("NORTH CAROLINA", "Cooper", "D", 7.2, True),
    ("MAINE", "Jackson", "D", 2.6, True),
    ("TEXAS", "Talarico", "D", 1.9, True),
    ("ALASKA", "Peltola", "D", 0.6, True),
    ("OHIO", "Brown", "D", 0.6, True),
    ("NEBRASKA", "Ricketts", "R", 0.6, False),
    ("IOWA", "Hinson", "R", 2.5, False),
    ("FLORIDA", "Moody", "R", 4.6, False),
    ("KANSAS", "Marshall", "R", 4.9, False),
    ("MISSISSIPPI", "Hyde-Smith", "R", 9.5, False),
    ("SOUTH CAROLINA", "D. Graham", "R", 9.9, False),
]
DEM_SEATS, REP_SEATS, CONTROL = 52, 48, 66


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size * S)


def text(d, xy, s, f, fill, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)


def tracked(d, xy, s, f, fill, tracking, anchor="l"):
    """Letter-spaced small caps. anchor l / r for the run's left or right edge."""
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
    tracked(d, (R, 96), "18 OCT 2026  ·  16 DAYS OUT", mono, GRAPHITE, 1.6, anchor="r")
    rect(d, (L, 112, R, 113), INK)

    # --- verdict -------------------------------------------------------------
    base = 352
    w52 = d.textlength("52", font=numeral) / S
    wdash = d.textlength("–", font=numeral) / S
    w48 = d.textlength("48", font=numeral) / S
    x = L - 6
    dash_w, dash_gap = 46, 22
    text(d, (x, base), "52", numeral, BLUE, "ls")
    dash_x = x + w52 + dash_gap
    rect(d, (dash_x, base - 104, dash_x + dash_w, base - 96), INK)
    x48 = dash_x + dash_w + dash_gap
    text(d, (x48, base), "48", numeral, RED, "ls")

    right_block_x = x48 + w48 + 40
    text(d, (right_block_x, 226), "Democrats", serif_big, BLUE, "ls")
    text(d, (right_block_x, 268), "favoured to win", serif_big, INK, "ls")
    text(d, (right_block_x, 310), "the Senate", serif_big, INK, "ls")
    tracked(d, (right_block_x, 348), f"{CONTROL}% CHANCE OF DEM CONTROL", mono_b, GRAPHITE, 1.6)

    # --- seat strip: 100 tiles, 50 per row -----------------------------------
    top, tgap = 392, 3.6
    tile = ((R - L) - 49 * tgap) / 50          # 50 tiles fill the measure exactly
    for i in range(100):
        row, col = divmod(i, 50)
        tx = L + col * (tile + tgap)
        ty = top + row * (tile + tgap)
        rect(d, (tx, ty, tx + tile, ty + tile), BLUE if i < DEM_SEATS else RED)
    # majority marker after seat 50 (between tile 50 and 51 = start of row 2)
    tracked(d, (L, top + 2 * (tile + tgap) + 22), "100 SEATS", mono_sm, MUTED, 1.4)
    tracked(d, (R, top + 2 * (tile + tgap) + 22), "51 FOR CONTROL", mono_sm, MUTED, 1.4, anchor="r")

    # --- race ledger -----------------------------------------------------------
    head_y = 492
    rect(d, (L, head_y, R, head_y + 1), INK)
    tracked(d, (L, head_y + 26), "COMPETITIVE RACES", mono_b, INK, 2.0)
    tracked(d, (R, head_y + 26), "PROJECTED MARGIN", mono, GRAPHITE, 1.6, anchor="r")

    col_state, col_name = L, L + 232
    axis = 690                       # centre of the diverging bars
    half = 132                       # bar room either side of the axis
    scale = half / 11.0
    col_margin = R
    row_h, y0 = 46, head_y + 52
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
    split_y = y0 + 8 * row_h + split_gap / 2
    rect(d, (L, split_y - 0.5, R, split_y + 0.5), INK)
    label_w = tracked(d, (-1000, -1000), "TIPPING POINT", mono_sm, INK, 1.6)   # measure only
    lx = axis - label_w / 2
    rect(d, (lx - 12, split_y - 9, lx + label_w + 12, split_y + 9), PAPER)
    tracked(d, (lx, split_y + 4.5), "TIPPING POINT", mono_sm, INK, 1.6)

    # --- footer ------------------------------------------------------------------
    fy = H - 72
    rect(d, (L, fy - 26, R, fy - 25), INK)
    tracked(d, (L, fy), "FUNDAMENTALS + DE-BIASED POLLS · 10,000 SIMULATIONS", mono_sm, GRAPHITE, 1.2)
    tracked(d, (R, fy), "@AFCWILL10 ON X", mono_sm, GRAPHITE, 1.2, anchor="r")

    img = img.resize((W, H), Image.LANCZOS)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instagram_forecast.png")
    img.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
