"""Minimal read-only PDF access: object index, dictionary parsing, stream inflation.

Scoped deliberately to what CLO 3D emits (PDF 1.4, no object streams, FlateDecode
only). Anything outside that raises rather than guessing, so a future export that
breaks these assumptions fails loudly instead of producing a subtly wrong marker.
"""

import re
import zlib

_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_NUM = rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


class PdfError(Exception):
    pass


class Pdf:
    def __init__(self, data: bytes):
        if not data.startswith(b"%PDF-"):
            raise PdfError("not a PDF (missing %PDF- header)")
        if b"/ObjStm" in data:
            raise PdfError(
                "PDF uses object streams, which this reader does not support. "
                "Re-export from CLO 3D, or convert first with: gs -sDEVICE=pdfwrite "
                "-dCompatibilityLevel=1.4 -o flat.pdf input.pdf"
            )
        self.data = data
        self._offsets = {}
        for m in _OBJ.finditer(data):
            # Later definitions win: incremental updates append revised objects.
            self._offsets[int(m.group(1))] = m.end()

    def raw(self, num: int) -> bytes:
        """Bytes of object `num`, from after 'obj' up to 'endobj'."""
        try:
            start = self._offsets[num]
        except KeyError:
            raise PdfError(f"object {num} not found")
        end = self.data.find(b"endobj", start)
        if end < 0:
            raise PdfError(f"object {num} has no endobj")
        return self.data[start:end]

    def stream(self, num: int) -> bytes:
        """Decoded stream payload of object `num`."""
        body = self.raw(num)
        i = body.find(b"stream")
        if i < 0:
            raise PdfError(f"object {num} has no stream")
        j = i + len(b"stream")
        if body[j : j + 2] == b"\r\n":
            j += 2
        elif body[j : j + 1] in (b"\r", b"\n"):
            j += 1
        k = body.rfind(b"endstream")
        payload = body[j:k] if k > 0 else body[j:]
        header = body[:i]
        if b"/FlateDecode" not in header:
            if b"/Filter" in header:
                raise PdfError(f"object {num}: unsupported stream filter")
            return payload
        try:
            # decompressobj tolerates the trailing EOL some writers leave behind.
            return zlib.decompressobj().decompress(payload)
        except zlib.error as exc:
            raise PdfError(f"object {num}: inflate failed ({exc})")

    # -- dictionary helpers -------------------------------------------------
    # These read the raw object text rather than building a full object model.
    # CLO's dictionaries are flat and machine-generated, so targeted extraction
    # is both sufficient and far less code than a general parser.

    def ref(self, body: bytes, key: str):
        """Resolve `/Key N 0 R` to the integer object number, or None."""
        m = re.search(rb"/" + key.encode() + rb"\s+(\d+)\s+\d+\s+R\b", body)
        return int(m.group(1)) if m else None

    def name(self, body: bytes, key: str):
        """Read `/Key(literal string)`, unescaping PDF octal escapes."""
        m = re.search(rb"/" + key.encode() + rb"\s*\(", body)
        if not m:
            return None
        return unescape(_balanced_string(body, m.end() - 1)).decode("latin-1")

    def numbers(self, body: bytes, key: str):
        """Read `/Key[ n n n ]` as a list of floats."""
        m = re.search(rb"/" + key.encode() + rb"\s*\[([^\]]*)\]", body)
        if not m:
            return None
        return [float(x) for x in re.findall(_NUM, m.group(1))]

    def xobjects(self, body: bytes) -> dict:
        """Map `/Name N 0 R` entries of an XObject dictionary to object numbers."""
        return {
            k.decode("latin-1"): int(v)
            for k, v in re.findall(rb"/([A-Za-z0-9_.#-]+)\s+(\d+)\s+\d+\s+R", body)
        }


def _balanced_string(body: bytes, start: int) -> bytes:
    """Extract a PDF literal string starting at '(' honouring nesting/escapes."""
    depth = 0
    i = start
    out = bytearray()
    while i < len(body):
        c = body[i : i + 1]
        if c == b"\\":
            out += body[i : i + 2]
            i += 2
            continue
        if c == b"(":
            depth += 1
            if depth == 1:
                i += 1
                continue
        elif c == b")":
            depth -= 1
            if depth == 0:
                return bytes(out)
        out += c
        i += 1
    return bytes(out)


_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def unescape(s: bytes) -> bytes:
    """Resolve PDF string escapes, including \\ddd octal."""
    out = bytearray()
    i = 0
    while i < len(s):
        if s[i : i + 1] != b"\\":
            out += s[i : i + 1]
            i += 1
            continue
        nxt = s[i + 1 : i + 2]
        if nxt.isdigit():
            j = i + 1
            digits = b""
            while j < len(s) and len(digits) < 3 and s[j : j + 1].isdigit():
                digits += s[j : j + 1]
                j += 1
            out.append(int(digits, 8) & 0xFF)
            i = j
        elif nxt in _ESC:
            out += _ESC[nxt]
            i += 2
        else:
            out += nxt
            i += 2
    return bytes(out)


def load(path: str) -> Pdf:
    with open(path, "rb") as fh:
        return Pdf(fh.read())
