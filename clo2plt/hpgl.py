"""HP-GL emitter.

Targets the generic HP-GL dialect understood by essentially every garment
plotter: IN / SP / PU / PD / PA in plotter units of 1/40 mm, plus LB for text.
Nothing HP-GL/2-specific (PE, PW, TR) is used, so output stays portable.
"""

import math
import unicodedata

from . import classify

UNITS_PER_MM = 40.0        # 1 plotter unit = 0.025 mm
_TERM = "\x03"             # ETX, the default HP-GL label terminator
# Older serial controllers have a 255-byte input buffer. Cap the command text
# well under that so the CRLF terminators still fit.
_MAX_LINE = 240


def _u(mm):
    return int(round(mm * UNITS_PER_MM))


def emit(strokes, labels, pens, text_mode="label", page_advance=False,
         header=None):
    """Return (document, retitled) where `retitled` lists transliterated labels.

    `header` is emitted as HP-GL/2 CO comments only when requested; plain HP-GL
    has no comment instruction and some controllers fault on an unknown
    mnemonic, so provenance is opt-in.
    """
    out = []
    if header:
        for line in header:
            out.append(f'CO"{_ascii(line)[0]}";')
    out.append("IN;")
    out.append("PA;")

    by_pen = {}
    for s in strokes:
        by_pen.setdefault(pens.get(s.kind, pens[classify.UNKNOWN]), []).append(s)

    label_pen = pens.get(classify.LABEL, 6)
    if labels and text_mode == "label":
        by_pen.setdefault(label_pen, [])

    retitled = []
    want_labels = bool(labels) and text_mode == "label"

    for pen in sorted(by_pen):
        out.append(f"SP{pen};")
        for stroke in by_pen[pen]:
            out.extend(_polyline(stroke.points))
        if want_labels and pen == label_pen:
            lines, retitled = _labels(labels)
            out.extend(lines)
            want_labels = False

    out.append("PU;")
    out.append("SP0;")
    if page_advance:
        out.append("PG;")
    out.append("IN;")
    return "\n".join(out) + "\n", retitled


def _polyline(points):
    """One polyline as a PU move followed by PD runs within the line limit."""
    if len(points) < 2:
        return []
    lines = [f"PU{_u(points[0][0])},{_u(points[0][1])};"]

    parts = []
    length = 3  # "PD" plus the trailing ";"
    for px, py in points[1:]:
        coord = f"{_u(px)},{_u(py)}"
        # +1 for the comma joining this coordinate to the previous one.
        extra = len(coord) + (1 if parts else 0)
        if parts and length + extra > _MAX_LINE:
            lines.append(f"PD{','.join(parts)};")
            parts, length = [], 3
            extra = len(coord)
        parts.append(coord)
        length += extra
    if parts:
        lines.append(f"PD{','.join(parts)};")
    return lines


def _labels(labels):
    if not labels:
        return [], []
    lines = [f"DT{_TERM};"]
    retitled = []
    for l in labels:
        # SI sets the character cell in centimetres. The ratios come from the
        # embedded font's metrics (CapHeight 733/1000, typical advance 600/1000)
        # so plotter text lands close to CLO's on-screen size.
        w = 0.60 * l.size / 10.0
        h = 0.72 * l.size / 10.0
        rad = math.radians(l.angle)
        lines.append(f"SI{w:.4f},{h:.4f};")
        lines.append(f"DI{math.cos(rad):.6f},{math.sin(rad):.6f};")
        text, changed = _ascii(l.text)
        if changed:
            retitled.append((l.text, text))
        lines.append(f"PU{_u(l.origin[0])},{_u(l.origin[1])};")
        lines.append(f"LB{text}{_TERM};")
    lines.append("DI1,0;")
    return lines, retitled


def _ascii(text):
    """Fold text to printable ASCII, returning (text, changed).

    Plain HP-GL only guarantees the ASCII character set, and a high byte can
    terminate a label early on some controllers. Accented characters are folded
    to their base letter ("puños" -> "punos") so the label stays legible;
    --text=outline renders the real glyphs when exact spelling matters.
    """
    folded = unicodedata.normalize("NFKD", text)
    out = "".join(
        c for c in folded
        if not unicodedata.combining(c) and 32 <= ord(c) < 127 and c != _TERM
    )
    return out, out != text
