"""Read HP-GL back into geometry.

Parses the file the plotter actually receives, rather than re-deriving it from
the source PDF, so a preview reflects the finished artifact. Handles the common
subset any plotter file uses -- not just output from this tool.
"""

import math
import re
from dataclasses import dataclass, field

MM_PER_UNIT = 1.0 / 40.0
_TERM = "\x03"

# A mnemonic is two letters; parameters run to the next ';'. LB is special:
# its text runs to the label terminator, which may itself contain ';'.
_CMD = re.compile(r"([A-Za-z]{2})([^;]*);?")


@dataclass
class Polyline:
    points: list
    pen: int


@dataclass
class Text:
    text: str
    origin: tuple
    angle: float
    size: float
    pen: int


@dataclass
class Drawing:
    polylines: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    pens: set = field(default_factory=set)
    unsupported: dict = field(default_factory=dict)

    @property
    def bbox(self):
        xs, ys = [], []
        for p in self.polylines:
            for x, y in p.points:
                xs.append(x)
                ys.append(y)
        for t in self.texts:
            for x, y in _text_corners(t):
                xs.append(x)
                ys.append(y)
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))


# Rough glyph metrics, enough to keep a label inside the preview's viewBox.
_ADVANCE = 0.62      # of the character cell height, per character
_ASCENT = 0.80
_DESCENT = 0.25


def _text_corners(t):
    """Corners of a label's approximate box, anchored at the baseline start.

    HP-GL gives no text metrics, so a preview that measured only the baseline
    origin would clip the glyphs above it.
    """
    rad = math.radians(t.angle)
    cos, sin = math.cos(rad), math.sin(rad)
    length = _ADVANCE * t.size * max(len(t.text), 1)
    x, y = t.origin
    corners = []
    for along, up in ((0.0, -_DESCENT), (length, -_DESCENT),
                      (length, _ASCENT), (0.0, _ASCENT)):
        u = up * t.size
        corners.append((x + along * cos - u * sin, y + along * sin + u * cos))
    return corners


def _nums(text):
    return [float(v) for v in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)", text)]


def parse(data, units_per_mm=40.0):
    """Parse HP-GL text into a Drawing, in millimetres."""
    scale = 1.0 / units_per_mm
    d = Drawing()

    pen = 0
    pos = (0.0, 0.0)
    down = False
    absolute = True
    current = []
    term = _TERM
    size = (0.187, 0.269)   # HP-GL default character cell, centimetres
    direction = (1.0, 0.0)

    def flush():
        nonlocal current
        if len(current) >= 2 and pen:
            d.polylines.append(Polyline(current, pen))
        current = []

    i = 0
    text = data.replace("\r", "").replace("\n", "")
    while i < len(text):
        m = _CMD.match(text, i)
        if not m:
            i += 1
            continue
        op, args = m.group(1).upper(), m.group(2)

        if op == "LB":
            # Label text runs to the terminator, not to a semicolon.
            start = m.start(2)
            end = text.find(term, start)
            if end < 0:
                end = len(text)
            label = text[start:end]
            if label and pen:
                angle = math.degrees(math.atan2(direction[1], direction[0]))
                # SI height is the character cell in cm; report it in mm.
                d.texts.append(Text(label, pos, angle, size[1] * 10.0, pen))
            i = end + len(term)
            if text[i : i + 1] == ";":
                i += 1
            continue

        i = m.end()
        values = _nums(args)

        if op == "SP":
            flush()
            pen = int(values[0]) if values else 0
            if pen:
                d.pens.add(pen)
        elif op == "PA":
            absolute = True
            pos, current, down = _move(values, scale, pos, current, down, True)
        elif op == "PR":
            absolute = False
            pos, current, down = _move(values, scale, pos, current, down, False)
        elif op == "PU":
            flush()
            down = False
            pos, current, down = _move(values, scale, pos, current, False, absolute)
        elif op == "PD":
            if not down:
                current = [pos]
            down = True
            pos, current, down = _move(values, scale, pos, current, True, absolute)
        elif op == "SI":
            if len(values) >= 2:
                size = (values[0], values[1])
        elif op == "DI":
            if len(values) >= 2 and (values[0] or values[1]):
                direction = (values[0], values[1])
        elif op == "DT":
            term = args[0] if args else _TERM
        elif op in ("IN", "DF", "PG", "SC", "IP", "VS", "FS", "LT", "CO",
                    "PW", "WU", "NP", "AA", "AR", "CI", "EA", "ER", "RA",
                    "RR", "WG", "EW", "TL", "XT", "YT", "SM", "UC", "PE"):
            if op in ("CI", "AA", "AR", "PE"):
                # Arcs and encoded polylines carry geometry this reader does
                # not reconstruct; surface them instead of dropping silently.
                d.unsupported[op] = d.unsupported.get(op, 0) + 1
            if op == "IN":
                flush()
                pos, down, absolute = (0.0, 0.0), False, True
        else:
            d.unsupported[op] = d.unsupported.get(op, 0) + 1

    flush()
    return d


def _move(values, scale, pos, current, down, absolute):
    """Apply a coordinate list, extending the run while the pen is down."""
    for j in range(0, len(values) - 1, 2):
        x, y = values[j] * scale, values[j + 1] * scale
        pos = (x, y) if absolute else (pos[0] + x, pos[1] + y)
        if down:
            current.append(pos)
    return pos, current, down
