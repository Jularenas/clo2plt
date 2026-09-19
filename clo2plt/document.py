"""Load a CLO 3D marker PDF into classified, plotter-ready geometry."""

import re
from dataclasses import dataclass, field

from . import classify
from . import geometry as g
from .content import Interpreter, parse_to_unicode
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


def read(path, tolerance=0.05, pieces=None):
    """Parse `path` into a Marker. `pieces` optionally filters by piece name."""
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
    interp = Interpreter(pdf, tolerance=tolerance, to_unicode=_to_unicode(pdf))
    result = interp.run_page(page, unit)

    # Page content is millimetres; the page-level `cm` supplies the scale that
    # maps them onto the MediaBox's points. Deriving it (rather than assuming)
    # means a differently-scaled export is caught below instead of mis-sized.
    page_w = (media[2] - media[0]) * MM_PER_POINT
    page_h = (media[3] - media[1]) * MM_PER_POINT

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
        curves=result.curves,
        lines=result.lines,
        producer=producer,
    )


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
