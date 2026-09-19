"""Optional label vectorisation via the embedded CFF font.

Used only by --text=outline. Plotter LB text is adequate for most cutting
rooms; outlines exist for when labels must match CLO's typeface exactly, or
when the plotter has no built-in font. fontTools is a soft dependency and is
never needed for the default path.
"""

import math
import re

from . import geometry as g
from .content import Stroke
from .pdfread import PdfError

_DEFAULT_ADVANCE = 600.0   # glyph units, matching the font's typical advance

INSTALL_HINT = (
    "--text=outline needs fontTools. Install it without touching system Python:\n"
    "    python3 -m venv .venv && .venv/bin/pip install fonttools\n"
    "then run clo2plt with .venv/bin/python instead of python3."
)


def available():
    try:
        import fontTools  # noqa: F401

        return True
    except ImportError:
        return False


def _load_font(pdf):
    m = re.search(rb"/FontFile3\s+(\d+)\s+\d+\s+R", pdf.data)
    if not m:
        raise PdfError("no embedded FontFile3 to vectorise; use --text=label")
    data = pdf.stream(int(m.group(1)))

    from fontTools.cffLib import CFFFontSet
    from io import BytesIO

    cff = CFFFontSet()
    cff.decompile(BytesIO(data), None)
    return cff[cff.fontNames[0]]


def _cid_map(font):
    """Map character code -> glyph name.

    CLO embeds a CID-keyed subset, so glyph order does not follow code order;
    fontTools names those glyphs 'cidNNNNN'. The encoding is Identity, so the
    CID is the character code. Name-keyed fonts fall back to their own charset
    order.
    """
    names = font.getGlyphOrder()
    mapping = {}
    cid_like = False
    for name in names:
        m = re.fullmatch(r"cid(\d+)", name)
        if m:
            mapping[int(m.group(1))] = name
            cid_like = True
    if not cid_like:
        for index, name in enumerate(names):
            mapping[index] = name
    return mapping


class _Pen:
    """Collect flattened contours from a CFF charstring."""

    def __init__(self, tol):
        self.tol = tol
        self.contours = []
        self._cur = []

    def moveTo(self, p):
        self._flushContour()
        self._cur = [tuple(p)]

    def lineTo(self, p):
        self._cur.append(tuple(p))

    def curveTo(self, *pts):
        # CFF is cubic; fontTools may hand back 2- or 3-point forms.
        if len(pts) == 3:
            g.flatten_cubic(self._cur[-1], tuple(pts[0]), tuple(pts[1]),
                            tuple(pts[2]), self.tol, self._cur)
        else:
            for p in pts:
                self._cur.append(tuple(p))

    def qCurveTo(self, *pts):
        for p in pts:
            if p is not None:
                self._cur.append(tuple(p))

    def closePath(self):
        if self._cur and self._cur[0] != self._cur[-1]:
            self._cur.append(self._cur[0])
        self._flushContour()

    endPath = closePath

    def addComponent(self, *a, **k):
        pass

    def _flushContour(self):
        if len(self._cur) >= 2:
            self.contours.append(self._cur)
        self._cur = []


def outline_labels(pdf, labels, tolerance=0.05):
    """Convert Label records into outline polylines (mm).

    Returns (strokes, missing) where `missing` holds any characters the
    embedded subset could not supply -- a silent gap in a piece label is
    exactly the kind of lost detail this tool exists to prevent.
    """
    if not available():
        raise PdfError(INSTALL_HINT)
    font = _load_font(pdf)
    charstrings = font.CharStrings
    codes = _cid_map(font)

    strokes = []
    missing = set()
    for label in labels:
        # Glyph space is 1000 units/em; scale into the label's mm size.
        em = label.size / 1000.0
        rad = math.radians(label.angle)
        cos, sin = math.cos(rad), math.sin(rad)
        place = (em * cos, em * sin, -em * sin, em * cos,
                 label.origin[0], label.origin[1])

        advance = 0.0
        for ch in label.text:
            name = codes.get(ord(ch))
            if name is None or name not in charstrings:
                missing.add(ch)
                advance += _DEFAULT_ADVANCE
                continue
            cs = charstrings[name]
            pen = _Pen(tolerance / max(em, 1e-9))
            try:
                cs.draw(pen)
            except Exception:
                missing.add(ch)
                advance += _DEFAULT_ADVANCE
                continue
            pen.closePath()
            shift = (1, 0, 0, 1, advance, 0)
            m = g.multiply(shift, place)
            for contour in pen.contours:
                pts = [g.apply(m, x, y) for x, y in contour]
                s = Stroke(g.dedupe(pts), (0.0, 0.0, 0.0), 0.0, label.piece)
                s.kind = "label"
                strokes.append(s)
            # fontTools sets .width while drawing, so no second pass is needed.
            advance += getattr(cs, "width", _DEFAULT_ADVANCE)

    if missing and not strokes:
        raise PdfError(
            "could not vectorise any label glyph from the embedded font; "
            "use --text=label"
        )
    return strokes, sorted(missing)
