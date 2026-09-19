"""PDF content-stream interpreter.

Walks a CLO 3D page and yields stroked polylines (already flattened to mm) and
text labels, each tagged with the pattern piece it belongs to. Fills are
discarded: in a CLO export the only filled paths are the fabric texture preview,
which has no meaning on a plotter.

Control points are transformed to page space *before* flattening so the chord
tolerance is expressed in real millimetres regardless of nested form matrices.
"""

import re
from dataclasses import dataclass, field

from . import geometry as g
from .pdfread import PdfError, unescape

_NUM_RE = re.compile(rb"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_TOKEN_RE = re.compile(
    rb"""
      /[^\s/\[\]()<>{}%]*        # name
    | \[ | \]                    # array delimiters
    | <<|>>                      # dict delimiters
    | \([^)\\]*(?:\\.[^)\\]*)*\) # literal string, escapes honoured
    | <[0-9A-Fa-f\s]*>           # hex string
    | [^\s/\[\]()<>{}%]+         # number or operator
    """,
    re.X | re.S,
)


@dataclass
class Stroke:
    points: list
    rgb: tuple
    width: float
    piece: str


@dataclass
class Label:
    text: str
    origin: tuple
    angle: float
    size: float
    piece: str


@dataclass
class _State:
    ctm: tuple = g.IDENTITY
    rgb: tuple = (0.0, 0.0, 0.0)
    width: float = 0.0

    def copy(self):
        return _State(self.ctm, self.rgb, self.width)


@dataclass
class Result:
    strokes: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    fills_dropped: int = 0
    curves: int = 0
    lines: int = 0


def tokenize(data: bytes):
    """Yield content-stream tokens. Comments are stripped."""
    for m in _TOKEN_RE.finditer(data):
        tok = m.group(0)
        if tok.startswith(b"%"):
            continue
        yield tok


def _as_num(tok):
    if _NUM_RE.match(tok):
        try:
            return float(tok)
        except ValueError:
            return None
    return None


class Interpreter:
    def __init__(self, pdf, tolerance=0.05, to_unicode=None):
        self.pdf = pdf
        self.tol = tolerance
        self.to_unicode = to_unicode or {}
        self.result = Result()
        self.piece = ""
        self._font_size = 0.0
        self._depth = 0

    # -- public -------------------------------------------------------------

    def run_page(self, page_obj, unit=g.IDENTITY):
        """Interpret a page: its content streams, then each piece form.

        `unit` post-multiplies the page matrix, so callers can land the output
        in millimetres instead of PDF points.
        """
        body = self.pdf.raw(page_obj)
        base = g.IDENTITY

        for num in _content_refs(body):
            base = self._page_matrix(self.pdf.stream(num), base)
        base = g.multiply(base, unit)

        xobj_ref = self.pdf.ref(body, "XObject")
        if xobj_ref is None:
            raise PdfError("page has no /XObject resources; not a CLO export?")
        forms = self.pdf.xobjects(self.pdf.raw(xobj_ref))

        for name in sorted(forms, key=_form_order):
            self._run_piece(forms[name], base)
        return self.result

    # -- internals ----------------------------------------------------------

    def _page_matrix(self, stream, base):
        """Extract the page-level `cm` that sets the unit scale."""
        stack = []
        for tok in tokenize(stream):
            if tok == b"cm" and len(stack) >= 6:
                base = g.multiply(tuple(stack[-6:]), base)
                stack = []
            else:
                n = _as_num(tok)
                stack.append(n if n is not None else tok)
        return base

    def _run_piece(self, form_num, base):
        """A page-level form is one pattern piece; /OC names it."""
        body = self.pdf.raw(form_num)
        oc = self.pdf.ref(body, "OC")
        self.piece = (self.pdf.name(self.pdf.raw(oc), "Name") or "") if oc else ""
        self._execute(form_num, base)

    def _execute(self, form_num, ctm):
        """Run a form XObject's stream under `ctm`."""
        if self._depth > 12:
            raise PdfError("XObject nesting too deep (recursive form?)")
        body = self.pdf.raw(form_num)

        matrix = self.pdf.numbers(body, "Matrix")
        if matrix and len(matrix) == 6:
            ctm = g.multiply(tuple(matrix), ctm)

        res_ref = self.pdf.ref(body, "Resources")
        forms = {}
        if res_ref is not None:
            res = self.pdf.raw(res_ref)
            xo = self.pdf.ref(res, "XObject")
            if xo is not None:
                forms = self.pdf.xobjects(self.pdf.raw(xo))

        self._depth += 1
        try:
            self._interpret(self.pdf.stream(form_num), ctm, forms)
        finally:
            self._depth -= 1

    def _interpret(self, stream, ctm, forms):
        st = _State(ctm=ctm)
        stack = []
        operands = []

        path = []          # list of subpaths; each a list of page-space points
        current = None
        start = None
        pending_text = None
        text_matrix = None

        for tok in tokenize(stream):
            num = _as_num(tok)
            if num is not None:
                operands.append(num)
                continue
            if tok[:1] in (b"/", b"(", b"<", b"[", b"]") or tok in (b"<<", b">>"):
                operands.append(tok)
                continue

            op = tok

            # -- graphics state
            if op == b"q":
                stack.append(st.copy())
            elif op == b"Q":
                if stack:
                    st = stack.pop()
            elif op == b"cm" and len(operands) >= 6:
                st.ctm = g.multiply(tuple(operands[-6:]), st.ctm)
            elif op == b"w" and operands:
                st.width = float(operands[-1])
            elif op == b"RG" and len(operands) >= 3:
                st.rgb = tuple(float(v) for v in operands[-3:])
            elif op == b"G" and operands:
                v = float(operands[-1])
                st.rgb = (v, v, v)

            # -- path construction (transform immediately to page space)
            elif op == b"m" and len(operands) >= 2:
                if current:
                    path.append(current)
                start = g.apply(st.ctm, operands[-2], operands[-1])
                current = [start]
            elif op == b"l" and len(operands) >= 2:
                if current is not None:
                    current.append(g.apply(st.ctm, operands[-2], operands[-1]))
                    self.result.lines += 1
            elif op in (b"c", b"v", b"y") and current is not None:
                self._curve(op, operands, st, current)
            elif op == b"re" and len(operands) >= 4:
                if current:
                    path.append(current)
                x, y, w, h = (float(v) for v in operands[-4:])
                current = [
                    g.apply(st.ctm, x, y),
                    g.apply(st.ctm, x + w, y),
                    g.apply(st.ctm, x + w, y + h),
                    g.apply(st.ctm, x, y + h),
                ]
                current.append(current[0])
                start = current[0]
            elif op == b"h":
                if current and start and current[-1] != start:
                    current.append(start)

            # -- painting
            elif op in (b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"):
                if op in (b"s", b"b", b"b*") and current and start:
                    current.append(start)
                if current:
                    path.append(current)
                current = None
                if op in (b"S", b"s", b"B", b"B*", b"b", b"b*"):
                    self._emit(path, st)
                elif op in (b"f", b"F", b"f*"):
                    self.result.fills_dropped += 1
                path = []
                start = None

            # -- text
            elif op == b"BT":
                text_matrix = g.IDENTITY
                pending_text = None
            elif op == b"Tf" and operands:
                self._font_size = float(operands[-1])
            elif op == b"Tm" and len(operands) >= 6:
                text_matrix = tuple(operands[-6:])
            elif op in (b"Td", b"TD") and len(operands) >= 2:
                text_matrix = g.multiply(
                    (1, 0, 0, 1, operands[-2], operands[-1]), text_matrix or g.IDENTITY
                )
            elif op in (b"Tj", b"TJ", b"'", b'"'):
                pending_text = _text_of(operands, self.to_unicode)
            elif op == b"ET":
                if pending_text and text_matrix:
                    self._label(pending_text, text_matrix, st)
                pending_text = None
                text_matrix = None

            # -- XObjects
            elif op == b"Do" and operands:
                name = operands[-1]
                if isinstance(name, bytes) and name.startswith(b"/"):
                    ref = forms.get(name[1:].decode("latin-1"))
                    if ref is not None and self._is_form(ref):
                        self._execute(ref, st.ctm)

            operands = []

        if current:
            path.append(current)

    def _curve(self, op, operands, st, current):
        p0 = current[-1]
        if op == b"c" and len(operands) >= 6:
            a, b, c, d, e, f = (float(v) for v in operands[-6:])
            p1 = g.apply(st.ctm, a, b)
            p2 = g.apply(st.ctm, c, d)
            p3 = g.apply(st.ctm, e, f)
        elif op == b"v" and len(operands) >= 4:
            c, d, e, f = (float(v) for v in operands[-4:])
            p1 = p0
            p2 = g.apply(st.ctm, c, d)
            p3 = g.apply(st.ctm, e, f)
        elif op == b"y" and len(operands) >= 4:
            a, b, e, f = (float(v) for v in operands[-4:])
            p1 = g.apply(st.ctm, a, b)
            p3 = g.apply(st.ctm, e, f)
            p2 = p3
        else:
            return
        g.flatten_cubic(p0, p1, p2, p3, self.tol, current)
        self.result.curves += 1

    def _emit(self, path, st):
        for pts in path:
            pts = g.dedupe(pts)
            if len(pts) >= 2:
                self.result.strokes.append(
                    Stroke(pts, st.rgb, st.width * g.scale_of(st.ctm), self.piece)
                )

    def _label(self, text, tm, st):
        m = g.multiply(tm, st.ctm)
        self.result.labels.append(
            Label(
                text=text,
                origin=(m[4], m[5]),
                angle=g.rotation_of(m),
                size=self._font_size * g.scale_of(m),
                piece=self.piece,
            )
        )

    def _is_form(self, num):
        return b"/Subtype/Form" in self.pdf.raw(num).replace(b" ", b"")


def _content_refs(page_body):
    m = re.search(rb"/Contents\s*\[([^\]]*)\]", page_body)
    if m:
        return [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", m.group(1))]
    m = re.search(rb"/Contents\s+(\d+)\s+\d+\s+R", page_body)
    return [int(m.group(1))] if m else []


def _form_order(name):
    m = re.search(r"(\d+)$", name)
    return (int(m.group(1)) if m else 0, name)


def _text_of(operands, to_unicode):
    """Decode string operands of a text-showing operator."""
    chunks = []
    for tok in operands:
        if not isinstance(tok, bytes):
            continue
        if tok.startswith(b"("):
            chunks.append(unescape(tok[1:-1]))
        elif tok.startswith(b"<") and not tok.startswith(b"<<"):
            hexdigits = re.sub(rb"\s", b"", tok[1:-1])
            if len(hexdigits) % 2:
                hexdigits += b"0"
            chunks.append(bytes.fromhex(hexdigits.decode("ascii")))
    raw = b"".join(chunks)
    if not raw:
        return ""
    # Identity-H: two-byte codes, resolved through ToUnicode when present.
    out = []
    for i in range(0, len(raw) - 1, 2):
        code = (raw[i] << 8) | raw[i + 1]
        out.append(to_unicode.get(code, chr(code)))
    return "".join(out).strip()


def parse_to_unicode(stream):
    """Build {code: char} from a ToUnicode CMap's bfchar/bfrange sections."""
    mapping = {}
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", stream, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            mapping[int(src, 16)] = _utf16(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", stream, re.S):
        for lo, hi, dst in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
        ):
            base = int(dst, 16)
            for i in range(int(lo, 16), int(hi, 16) + 1):
                mapping[i] = chr(base + i - int(lo, 16))
    return mapping


def _utf16(hexstr):
    raw = bytes.fromhex(hexstr.decode("ascii"))
    try:
        return raw.decode("utf-16-be")
    except UnicodeDecodeError:
        return "?"
