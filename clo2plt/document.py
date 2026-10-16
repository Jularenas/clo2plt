"""Load a CLO 3D marker PDF into classified, plotter-ready geometry."""

import math
import re
from dataclasses import dataclass, field

from . import classify
from . import geometry as g
from .content import Interpreter, parse_to_unicode, parse_widths
from .pdfread import PdfError, load

MM_PER_POINT = 25.4 / 72.0


@dataclass
class Piece:
    name: str
    strokes: list = field(default_factory=list)
    labels: list = field(default_factory=list)


@dataclass
class Marker:
    path: str
    page_w: float          # mm
    page_h: float          # mm
    pieces: list
    strokes: list
    labels: list
    unknown_colors: dict
    fills_dropped: int
    offpage: list
    curves: int
    lines: int
    producer: str = ""

    @property
    def bbox(self):
        boxes = [s.points for s in self.strokes]
        return g.bbox(boxes)

    def counts(self):
        tally = {k: 0 for k in classify.ORDER}
        for s in self.strokes:
            tally[s.kind] += 1
        tally[classify.LABEL] = len(self.labels)
        return tally


def read(path, tolerance=0.05, pieces=None, keep_offpage=False):
    """Parse `path` into a Marker. `pieces` optionally filters by piece name.

    Elements lying entirely outside the page are dropped unless
    `keep_offpage`: the PDF clips them, so CLO never shows them, and a single
    stray one -- CLO parks the fabric name ~860 mm left of some markers --
    stretches the plot and lands at negative plotter coordinates.
    """
    pdf = load(path)
    page = _first_page(pdf)
    body = pdf.raw(page)

    media = pdf.numbers(body, "MediaBox")
    if not media or len(media) != 4:
        raise PdfError("page has no usable /MediaBox")

    # Land everything in millimetres: the page `cm` maps content units to
    # points, and this converts points to mm. Tolerances and output are mm
    # throughout from here on.
    unit = (MM_PER_POINT, 0.0, 0.0, MM_PER_POINT,
            -media[0] * MM_PER_POINT, -media[1] * MM_PER_POINT)
    widths, default_width = parse_widths(pdf.data)
    interp = Interpreter(pdf, tolerance=tolerance, to_unicode=_to_unicode(pdf),
                         widths=widths, default_width=default_width)
    result = interp.run_page(page, unit)

    # Page content is millimetres; the page-level `cm` supplies the scale that
    # maps them onto the MediaBox's points. Deriving it (rather than assuming)
    # means a differently-scaled export is caught below instead of mis-sized.
    page_w = (media[2] - media[0]) * MM_PER_POINT
    page_h = (media[3] - media[1]) * MM_PER_POINT

    offpage = []
    if not keep_offpage:
        result.strokes, result.labels, offpage = cull_offpage(
            result.strokes, result.labels, page_w, page_h)

    unknown = {}
    for s in result.strokes:
        s.kind = classify.line_type(s.rgb)
        if s.kind == classify.UNKNOWN:
            key = tuple(round(v, 6) for v in s.rgb)
            unknown[key] = unknown.get(key, 0) + 1

    wanted = None
    if pieces:
        wanted = {p.strip().casefold() for p in pieces if p.strip()}
        result.strokes = [s for s in result.strokes if s.piece.casefold() in wanted]
        result.labels = [l for l in result.labels if l.piece.casefold() in wanted]
        found = {s.piece.casefold() for s in result.strokes}
        missing = wanted - found
        if missing:
            raise PdfError(
                "no such piece(s): " + ", ".join(sorted(missing)) + ". Use --list."
            )

    by_name = {}
    for s in result.strokes:
        by_name.setdefault(s.piece, Piece(s.piece)).strokes.append(s)
    for l in result.labels:
        by_name.setdefault(l.piece, Piece(l.piece)).labels.append(l)

    producer = ""
    m = re.search(rb"/Producer\s*\(([^)]*)\)", pdf.data)
    if m:
        producer = m.group(1).decode("latin-1")

    return Marker(
        path=path,
        page_w=page_w,
        page_h=page_h,
        pieces=list(by_name.values()),
        strokes=result.strokes,
        labels=result.labels,
        unknown_colors=unknown,
        fills_dropped=result.fills_dropped,
        offpage=offpage,
        curves=result.curves,
        lines=result.lines,
        producer=producer,
    )


# Rough glyph metrics, as fractions of the font size. HP-GL and the PDF text
# operators give no extents, so a label's footprint is estimated from these.
_ADVANCE = 0.62
_ASCENT = 0.80
_DESCENT = 0.25


def label_box(label):
    """Approximate (minx, miny, maxx, maxy) of a label, from its baseline start."""
    rad = math.radians(label.angle)
    cos, sin = math.cos(rad), math.sin(rad)
    length = label.width or _ADVANCE * label.size * max(len(label.text), 1)
    x, y = label.origin
    corners = []
    for along, up in ((0.0, -_DESCENT), (length, -_DESCENT),
                      (length, _ASCENT), (0.0, _ASCENT)):
        u = up * label.size
        corners.append((x + along * cos - u * sin, y + along * sin + u * cos))
    return g.bbox([corners])


def cull_offpage(strokes, labels, page_w, page_h):
    """Split off elements whose whole extent lies outside the page.

    Returns (strokes, labels, dropped). Anything that touches the page is kept,
    including grain arrows that run past the edge -- only elements the PDF
    would clip away entirely are removed. `dropped` lists them for reporting.
    """
    def outside(box):
        return box[2] < 0 or box[0] > page_w or box[3] < 0 or box[1] > page_h

    kept_s, kept_l, dropped = [], [], []
    for s in strokes:
        box = g.bbox([s.points])
        if outside(box):
            dropped.append(("stroke", s.piece, None, box))
        else:
            kept_s.append(s)
    for l in labels:
        box = label_box(l)
        if outside(box):
            dropped.append(("label", l.piece, l.text, box))
        else:
            kept_l.append(l)
    return kept_s, kept_l, dropped


def _first_page(pdf):
    for m in re.finditer(rb"(\d+)\s+0\s+obj", pdf.data):
        num = int(m.group(1))
        body = pdf.raw(num)
        if re.search(rb"/Type\s*/Page[^s]", body):
            return num
    raise PdfError("no page object found")


def _to_unicode(pdf):
    """Merge every ToUnicode CMap in the file; CLO emits a single shared font."""
    mapping = {}
    for m in re.finditer(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", pdf.data):
        try:
            mapping.update(parse_to_unicode(pdf.stream(int(m.group(1)))))
        except PdfError:
            continue
    return mapping
