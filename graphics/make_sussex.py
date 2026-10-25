"""Render the Sussex & Brighton mayoral projection (1080x1350) - graphics/sussex_mayor.png

Laid out like a supplementary-vote results card (London Elects / broadcaster style):
the first round, then the final round with each finalist's first preferences plus
the second preferences that counted. Central projection "if held today" from the UK
model's general-election route (uk/sussex_mayor.py --today, data/sussex_mayor_today.csv).
"""

import csv
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = os.environ.get("CANVAS_FONTS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "uk"))
W, H = 1080, 1350
S = 2

BG = (247, 246, 243)
BAND = (16, 22, 33)
INK = (20, 22, 27)
SOFT = (110, 112, 118)
FAINT = (168, 166, 160)
TRACK = (229, 227, 222)
WHITE = (255, 255, 255)
PARTY = {"Con": (0, 106, 196), "Lab": (214, 32, 52), "Ref": (0, 166, 194), "LD": (240, 150, 0),
         "Grn": (32, 150, 72), "Oth": (128, 126, 120)}
NAMES = {"Con": ("BOURNE", "Katy", "Conservative"), "Ref": ("LINEHAN", "Paul", "Reform UK"),
         "Lab": ("BAXTER", "Caroline", "Labour"), "LD": ("DEMPSEY", "Ben", "Liberal Democrat"),
         "Grn": ("MILLWARD", "Rachel", "Green"), "Oth": ("WEBB", "Martin", "Independent and others")}
SCALE_MAX = 45.0           # % of all ballots at the full bar width, same in both rounds


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size * S)


SANS = "InstrumentSans-Bold.ttf"
MONO = "GeistMono-Bold.ttf"
MONO_REG = "GeistMono-Regular.ttf"


def text(d, xy, s, f, fill, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)


def box(d, x0, y0, x1, y1, fill, radius=0):
    if radius:
        d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=radius * S, fill=fill)
    else:
        d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill)


def tint(rgb, amount):
    return tuple(int(c + (255 - c) * amount) for c in rgb)


def chip(d, x, y, label, fill, color=WHITE, anchor="left"):
    f = font(SANS, 13)
    w = d.textlength(label, font=f) / S + 18
    x0 = x if anchor == "left" else x - w
    box(d, x0, y, x0 + w, y + 24, fill, radius=4)
    text(d, (x0 + w / 2, y + 12.5), label, f, color, "mm")


def projection():
    """Central first round (adds to 100) and the most likely final with its transfers."""
    import sussex_mayor as sx
    import tactical as tactics
    with open(os.path.join(ROOT, "uk", "data", "sussex_mayor_today.csv"), newline="", encoding="utf-8") as f:
        rows = {r["party"]: float(r["first_choice"]) for r in csv.DictReader(f)}
    total = sum(rows.values())
    first = {p: 100 * v / total for p, v in rows.items()}
    order = sorted(first, key=lambda p: -first[p])
    a, b = order[0], order[1]
    rates, covered = tactics.yougov_rates()
    P = sx.PARTIES
    ia, ib = P.index(a), P.index(b)
    lopsided = float(np.mean(sx.SPLIT))
    gained = {a: 0.0, b: 0.0}
    for k, share in first.items():
        if k in (a, b):
            continue
        if k == "Oth":
            gained[a] += share * sx.INDEPENDENT / 2
            gained[b] += share * sx.INDEPENDENT / 2
            continue
        ya, yb = rates[ia, ib, P.index(k), 0], rates[ia, ib, P.index(k), 1]
        if ya + yb == 0:
            continue
        reach = sx.VOLUME * (ya + yb)
        to_a = 0.5 + lopsided * (ya / (ya + yb) - 0.5)
        gained[a] += share * reach * to_a
        gained[b] += share * reach * (1 - to_a)
    return first, order, (a, b), gained


def main():
    first, order, (a, b), gained = projection()
    final = {p: first[p] + gained[p] for p in (a, b)}
    counted = sum(final.values())
    winner = max((a, b), key=lambda p: final[p])

    img = Image.new("RGB", (W * S, H * S), BG)
    d = ImageDraw.Draw(img)
    L, R = 64, W - 64

    # header band
    box(d, 0, 0, W, 196, BAND)
    text(d, (L, 58), "SUSSEX & BRIGHTON MAYOR", font(SANS, 40), WHITE)
    text(d, (L, 116), "Projection if an election were held today", font(SANS, 22), tint(BAND, 0.62))
    text(d, (L, 148), "SUPPLEMENTARY VOTE  ·  POLLS TO 25 OCT 2026", font(MONO_REG, 15), tint(BAND, 0.45))

    name_w = 300
    bar_l, bar_r = L + name_w, R - 120

    def bar_x(pct):
        return bar_l + (bar_r - bar_l) * pct / SCALE_MAX

    # first round
    y = 238
    text(d, (L, y), "FIRST ROUND", font(SANS, 17), SOFT)
    text(d, (R, y), "% OF VOTES", font(MONO_REG, 13), FAINT, "ra")
    y += 40
    row_h = 82
    for p in order:
        through = p in (a, b)
        name, given, party = NAMES[p]
        box(d, L, y, L + 8, y + row_h - 14, PARTY[p])
        text(d, (L + 24, y + 4), name, font(SANS, 27), INK if through else SOFT)
        text(d, (L + 24, y + 38), f"{given}  ·  {party}", font(SANS, 15), SOFT if through else FAINT)
        box(d, bar_l, y + 18, bar_r, y + 40, TRACK)
        box(d, bar_l, y + 18, bar_x(first[p]), y + 40, PARTY[p] if through else tint(PARTY[p], 0.35))
        text(d, (R, y + 29), f"{first[p]:.1f}", font(MONO, 26), INK if through else SOFT, "rm")
        if through:
            chip(d, bar_x(first[p]) + 10, y + 17, "THROUGH", INK)
        y += row_h

    # transfer note
    y += 8
    d.line([L * S, y * S, R * S, y * S], fill=TRACK, width=2 * S)
    eliminated = [NAMES[p][0].title() for p in order if p not in (a, b)]
    text(d, (L, y + 22), "↓  Second preferences of " + ", ".join(eliminated[:-1]) + " and " + eliminated[-1]
         + " voters are added", font(SANS, 17), SOFT)

    # final round
    y += 78
    text(d, (L, y), "FINAL ROUND", font(SANS, 17), SOFT)
    text(d, (R, y), "FINAL SHARE", font(MONO_REG, 13), FAINT, "ra")
    y += 40
    big_h = 126
    for p in sorted((a, b), key=lambda q: -final[q]):
        name, given, party = NAMES[p]
        box(d, L, y, L + 8, y + big_h - 18, PARTY[p])
        text(d, (L + 24, y + 6), name, font(SANS, 34), INK)
        text(d, (L + 24, y + 48), f"{given}  ·  {party}", font(SANS, 16), SOFT)
        if p == winner:
            chip(d, L + 24, y + 72, "PROJECTED WINNER", PARTY[p])
        box(d, bar_l, y + 20, bar_r, y + 60, TRACK)
        box(d, bar_l, y + 20, bar_x(first[p]), y + 60, PARTY[p])
        box(d, bar_x(first[p]), y + 20, bar_x(final[p]), y + 60, tint(PARTY[p], 0.45))
        text(d, (bar_l + 10, y + 40), f"1st {first[p]:.1f}", font(MONO, 15), WHITE, "lm")
        label = f"+{gained[p]:.1f}"
        segment = bar_x(final[p]) - bar_x(first[p])
        if segment > d.textlength(label, font=font(MONO, 15)) / S + 16:      # fits inside its segment
            text(d, (bar_x(first[p]) + segment / 2, y + 40), label, font(MONO, 15), INK, "mm")
        else:
            text(d, (bar_x(final[p]) + 8, y + 40), label, font(MONO, 15), INK, "lm")
        text(d, (R, y + 40), f"{100 * final[p] / counted:.1f}%", font(MONO, 34), INK, "rm")
        y += big_h

    # key and notes
    y += 6
    box(d, L, y + 4, L + 26, y + 18, PARTY[winner])
    text(d, (L + 36, y + 11), "first preferences", font(SANS, 15), SOFT, "lm")
    box(d, L + 220, y + 4, L + 246, y + 18, tint(PARTY[winner], 0.45))
    text(d, (L + 256, y + 11), "second preferences added (% of all ballots)", font(SANS, 15), SOFT, "lm")
    d.line([L * S, (y + 44) * S, R * S, (y + 44) * S], fill=TRACK, width=2 * S)
    notes = [f"{100 - counted:.0f}% of ballots had no counting second preference for the final two.",
             "Central projection from a polling model - not a result or a poll. Not for publication."]
    for i, n in enumerate(notes):
        text(d, (L, y + 66 + 26 * i), n, font(SANS, 15), FAINT)

    img = img.resize((W, H), Image.LANCZOS)
    out = os.path.join(ROOT, "graphics", "sussex_mayor.png")
    img.save(out)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
