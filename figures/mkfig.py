#!/usr/bin/env python3
"""Generate the paint-model subtitle cadence illustration.

Seven subtitle cards along a time axis running left to right, drawn in an
oblique (cabinet) projection.  Solid cards are parts where a new document is
sent; dashed empty cards are parts where nothing changed and the sample is an
8-byte box.

The "feed" variant is a portrait 1200x1500 figure for social feeds: four parts
stacked down the page, with the caption drawn the way a burnt-in subtitle looks
-- a tight black box, white text, very little height around it -- and type sized
so the labels survive being scaled to ~390 px wide on a phone.
"""
import math
import os
import sys

# ---------------------------------------------------------------- parameters
W, H = 440.0, 124.0          # card size in its own plane
AX, AY = 0.70, 0.30          # where the card's local x axis lands on screen
K = AY / AX                  # screen slope of the card's top and bottom edges
SX, SY = 238.6, -56.0        # time step between cards, on screen
RX = 10                      # card corner radius

FS_CUE = 34                  # cue text
FS_LBL = 22                  # per-card label
LBL_DY = 26                  # gap under the card, in the card's own plane

FONT = "'Helvetica Neue', Helvetica, Arial, sans-serif"

C_BG     = "#ffffff"
C_DOC    = "#133b5c"
C_DOC_ED = "#0c2942"
C_SHADOW = "#dde5ec"
C_NOCH   = "#8496a8"
C_GHOST  = "#c3ced8"
C_LBL    = "#64748b"
C_TITLE  = "#0f172a"
C_SUB    = "#475569"
C_AXIS   = "#64748b"
C_AXIS_L = "#334155"
C_HANDLE = "#c8813c"          # brush, marking a paint event
C_FERRUL = "#b9c5d1"
C_BRISTL = "#2f6ea8"

# The brush lives in the card's own plane, tip just inside the top-left corner,
# handle reaching up and left into the open space above the row.
BRUSH_AT = (34, 8)
BRUSH_ROT = 35
BRUSH_EXT = (-118, -15, 4, 15)   # brush shape before rotation

CARDS = [
    ("low",                   True),
    ("low",                   False),
    ("low",                   False),
    ("low latency",           True),
    ("low latency",           False),
    ("low latency",           False),
    ("low latency subtitles", True),
]
LBL_DOC = "document · ~1.3 kB"
LBL_NOC = "no change · 8 B"

TITLE = "Low-latency subtitles: paint model"
SUB1 = "A document only when the words change."
SUB2 = "8 bytes when they don’t."
CREDIT = "github.com/Eyevinn/paint-model-subtitles"

CANVAS_W, CANVAS_H = 1900, 1000
MARGIN = 80

# ---------------------------------------------- feed variant (portrait, 4:5)
# A feed image is displayed at ~552 px wide on desktop and ~390 px on a phone
# whatever it is exported at, so every size here is chosen as a fraction of
# FW: nothing below 3.3% (40 px) is readable once scaled.
FW, FH = 1200, 1500          # 4:5, the tallest ratio LinkedIn shows uncropped
F_MARGIN = 80
F_AXIS_X = 104               # the time axis, running down the left
F_SLOT_X = 150               # the parts, to the right of it
F_SLOT_H = 164
F_ROW = 258                  # pitch between parts
F_TOP = 372                  # first part

F_FS_TITLE = 68              # 5.7% of width
F_FS_SUB = 40
F_FS_CUE = 48                # the subtitle itself
F_FS_LBL = 54                # 4.5% -- the byte figures, the point of the figure
F_FS_FOOT = 34

CAP_PAD_X = 26               # a burnt-in subtitle hugs its text
CAP_PAD_Y = 13

C_CAP_BG = "#000000"
C_DOC_EDGE = "#133b5c"
C_SCREEN = "#eef2f6"

F_CARDS = [
    ("low-latency",           True),
    ("low-latency",           False),
    ("low-latency",           False),
    ("low-latency subtitles", True),
]
F_LBL_DOC = "document · ~1.6 kB"     # the livesim2 document, as quoted in the post
F_LBL_NOC = "no change · 8 B"

F_TITLE = "Low-latency subtitles: paint model"
F_SUB1 = "A document only when the words change."
F_SUB2 = "8 bytes when they don’t."
F_FOOT = "Proposed · github.com/Eyevinn/paint-model-subtitles"

# Rough Helvetica advance widths, enough to size a box around a short string.
_ADV = {" ": 0.28, "-": 0.33, ".": 0.28, "·": 0.35, ",": 0.28, ":": 0.28,
        "i": 0.22, "l": 0.22, "j": 0.22, "t": 0.28, "f": 0.28, "r": 0.33,
        "m": 0.83, "w": 0.72, "k": 0.50}


def advance(s, size):
    return size * sum(_ADV.get(c, 0.62 if c.isupper() else 0.52) for c in s)


def fit(s, size, room):
    """Largest size at or below `size` that keeps `s` on one line."""
    while size > 36 and advance(s, size) * 1.06 > room:
        size -= 1
    return size


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size, fill, anchor="start", weight="400", extra=""):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    w = f' font-weight="{weight}"' if weight != "400" else ""
    return (f'<text x="{x:.0f}" y="{y:.0f}"{a} font-family="{FONT}" '
            f'font-size="{size}"{w} fill="{fill}"{extra}>{esc(s)}</text>')


def brush():
    return (f'      <g transform="translate({BRUSH_AT[0]} {BRUSH_AT[1]}) rotate({BRUSH_ROT})">\n'
            f'        <rect x="-118" y="-8.5" width="66" height="17" rx="8.5" fill="{C_HANDLE}"/>\n'
            f'        <rect x="-56" y="-13" width="28" height="26" rx="3" fill="{C_FERRUL}"/>\n'
            f'        <polygon points="-30,-15 -30,15 -6,9 4,0 -6,-9" fill="{C_BRISTL}"/>\n'
            f'      </g>')


def brush_corners():
    """The brush's four bbox corners, rotated and placed in the card's plane."""
    a = math.radians(BRUSH_ROT)
    ca, sa = math.cos(a), math.sin(a)
    x0, y0, x1, y1 = BRUSH_EXT
    return [(BRUSH_AT[0] + x * ca - y * sa, BRUSH_AT[1] + x * sa + y * ca)
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]


def card(i, cue, is_doc, x0, y0, ghost):
    """One card, drawn in its own sheared coordinate system."""
    ax_, ay_ = x0 + i * SX, y0 + i * SY
    o = [f'    <g transform="matrix({AX} {AY} 0 1 {ax_:.1f} {ay_:.1f})">']
    cy = H / 2 + FS_CUE * 0.35
    if is_doc:
        o.append(f'      <rect x="7" y="10" width="{W}" height="{H}" rx="{RX}" fill="{C_SHADOW}"/>')
        o.append(f'      <rect width="{W}" height="{H}" rx="{RX}" fill="{C_DOC}" '
                 f'stroke="{C_DOC_ED}" stroke-width="2"/>')
        o.append("      " + text(W / 2, cy, cue, FS_CUE, "#ffffff", "middle", "500"))
        o.append(brush())
    else:
        o.append(f'      <rect width="{W}" height="{H}" rx="{RX}" fill="none" '
                 f'stroke="{C_NOCH}" stroke-width="2.5" stroke-dasharray="12 9"/>')
        if ghost:
            o.append("      " + text(W / 2, cy, cue, FS_CUE, C_GHOST, "middle", "500"))
    lbl = LBL_DOC if is_doc else LBL_NOC
    o.append("      " + text(W / 2, H + LBL_DY + FS_LBL * 0.8, lbl, FS_LBL, C_LBL, "middle"))
    o.append("    </g>")
    return "\n".join(o)


def row_bbox(x0, y0, with_brush=True):
    xs, ys = [], []
    for i in range(len(CARDS)):
        ax_, ay_ = x0 + i * SX, y0 + i * SY
        corners = [(0, 0), (W, 0), (W, H), (0, H),
                   (0, H + LBL_DY + FS_LBL), (W, H + LBL_DY + FS_LBL)]
        if with_brush and CARDS[i][1]:
            corners += brush_corners()
        for u, v in corners:
            xs.append(ax_ + AX * u)
            ys.append(ay_ + AY * u + v)
    return min(xs), min(ys), max(xs), max(ys)


def time_axis(x1, x2, y, label_x):
    head = 24
    return (
        f'  <g id="time-axis">\n'
        f'    <line x1="{x1}" y1="{y}" x2="{x2 - head + 3}" y2="{y}" stroke="{C_AXIS}" stroke-width="4"/>\n'
        f'    <polygon points="{x2},{y} {x2-head},{y-11} {x2-head},{y+11}" fill="{C_AXIS}"/>\n'
        f'    ' + text(label_x, y + 46, "time", 30, C_AXIS_L, weight="600",
                       extra=' letter-spacing="3"') + '\n'
        f'  </g>'
    )


def build(social, ghost):
    bx0, by0, bx1, by1 = row_bbox(0, 0)            # brush included: the canvas
    cx0, cy0, _, _ = row_bbox(0, 0, with_brush=False)   # cards only: the placing
    rw, rh = bx1 - bx0, by1 - by0

    if social:
        cw, ch = CANVAS_W, CANVAS_H
        ox = MARGIN - bx0 + (cw - 2 * MARGIN - rw) / 2
        oy = 280 - cy0
        head = [
            "  " + text(MARGIN, 150, TITLE, 54, C_TITLE, weight="600"),
            "  " + text(MARGIN, 208, SUB1, 27, C_SUB),
            "  " + text(MARGIN, 246, SUB2, 27, C_SUB),
            "  " + text(cw - MARGIN, 150, CREDIT, 21, C_LBL, anchor="end"),
            time_axis(MARGIN, cw - MARGIN, 920, MARGIN),
        ]
    else:
        pad = 46
        cw = int(rw + 2 * pad)
        ch = int(rh + 2 * pad + 62)
        ox, oy = pad - bx0, pad - by0
        head = [time_axis(pad, cw - pad, ch - 60, pad)]

    body = [card(i, c, d, ox, oy, ghost) for i, (c, d) in enumerate(CARDS)]
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {cw} {ch}" '
        f'width="{cw}" height="{ch}" role="img" aria-label="Seven subtitle parts in a row: '
        f'a new document is sent only when the text changes, otherwise an 8-byte no-change sample. A brush marks each paint event.">',
        f'  <rect width="{cw}" height="{ch}" fill="{C_BG}"/>',
        "\n".join(head),
        '  <g id="cards">',
        "\n".join(body),
        "  </g>",
        "</svg>",
        "",
    ])


def caption(cx, y_bottom, cue):
    """A burnt-in subtitle: tight black box, white text, centred."""
    w = advance(cue, F_FS_CUE) + 2 * CAP_PAD_X
    h = F_FS_CUE * 1.18 + 2 * CAP_PAD_Y
    x, y = cx - w / 2, y_bottom - h
    return (f'      <rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
            f'fill="{C_CAP_BG}"/>\n      '
            + text(cx, y + CAP_PAD_Y + F_FS_CUE * 0.80, cue, F_FS_CUE,
                   "#ffffff", "middle", "500"))


def part(i, cue, is_doc):
    """One part: the picture with the caption on it, and what went on the wire."""
    top = F_TOP + i * F_ROW
    x, w = F_SLOT_X, FW - F_SLOT_X - F_MARGIN
    edge = (f'stroke="{C_DOC_EDGE}" stroke-width="3"' if is_doc
            else f'stroke="{C_NOCH}" stroke-width="2.5" stroke-dasharray="11 8"')
    o = ['    <g>',
         f'      <rect x="{x}" y="{top}" width="{w}" height="{F_SLOT_H}" rx="14" '
         f'fill="{C_SCREEN}" {edge}/>']
    if is_doc:
        o.append(f'      <g transform="translate({x + 140} {top + 112}) scale(1.45)">\n'
                 + brush() + '\n      </g>')
    o.append('      ' + caption(x + w / 2, top + F_SLOT_H - 22, cue))
    lbl = F_LBL_DOC if is_doc else F_LBL_NOC
    o.append('      ' + text(x + 4, top + F_SLOT_H + 12 + F_FS_LBL * 0.8, lbl,
                             F_FS_LBL, C_DOC_EDGE if is_doc else C_LBL,
                             weight="600" if is_doc else "400"))
    o.append('    </g>')
    return "\n".join(o)


def build_feed():
    n = len(F_CARDS)
    y0, y1 = F_TOP - 20, F_TOP + (n - 1) * F_ROW + F_SLOT_H + 20
    head = 26
    axis = (f'  <g id="time-axis">\n'
            f'    <line x1="{F_AXIS_X}" y1="{y0}" x2="{F_AXIS_X}" y2="{y1 - head + 3}" '
            f'stroke="{C_AXIS}" stroke-width="5"/>\n'
            f'    <polygon points="{F_AXIS_X},{y1} {F_AXIS_X-12},{y1-head} '
            f'{F_AXIS_X+12},{y1-head}" fill="{C_AXIS}"/>\n'
            f'    <g transform="rotate(-90 {F_AXIS_X - 26} {(y0 + y1) / 2:.0f})">'
            + text(F_AXIS_X - 26, (y0 + y1) / 2, "time", 38, C_AXIS_L,
                   anchor="middle", weight="600", extra=' letter-spacing="3"')
            + '</g>\n  </g>')
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {FW} {FH}" '
        f'width="{FW}" height="{FH}" role="img" aria-label="Four subtitle parts '
        f'stacked in time. The caption stays on screen throughout; a complete '
        f'document of about 1.6 kB is sent only when the words change, and 8 '
        f'bytes when they do not.">',
        f'  <rect width="{FW}" height="{FH}" fill="{C_BG}"/>',
        "  " + text(F_MARGIN, 150, F_TITLE,
                    fit(F_TITLE, F_FS_TITLE, FW - 2 * F_MARGIN), C_TITLE, weight="600"),
        "  " + text(F_MARGIN, 232, F_SUB1, F_FS_SUB, C_SUB),
        "  " + text(F_MARGIN, 282, F_SUB2, F_FS_SUB, C_SUB),
        axis,
        '  <g id="parts">',
        "\n".join(part(i, c, d) for i, (c, d) in enumerate(F_CARDS)),
        "  </g>",
        "  " + text(F_MARGIN, FH - 46, F_FOOT, F_FS_FOOT, C_LBL),
        "</svg>",
        "",
    ])


# usage: mkfig.py [outdir] [--ghost]
#   --ghost draws the unchanged text faintly inside the no-change cards
args = [a for a in sys.argv[1:] if not a.startswith("-")]
ghost = "--ghost" in sys.argv
outdir = args[0] if args else os.path.dirname(os.path.abspath(__file__))
FIGURES = (
    ("paint-model-cadence", lambda: build(False, ghost)),
    ("paint-model-cadence-social", lambda: build(True, ghost)),
    ("paint-model-cadence-feed", build_feed),
)
for name, make in FIGURES:
    path = os.path.join(outdir, name + ".svg")
    with open(path, "w") as f:
        f.write(make())
    print(path)
