// Minimal read-only PDF access. Mirrors clo2plt/pdfread.py.
//
// The file is held twice: as bytes, and as a latin-1 string where one char is
// exactly one byte, so string offsets and byte offsets are interchangeable and
// the Python regexes port across unchanged.

export class PdfError extends Error {}

const OBJ_RE = /(\d+)\s+(\d+)\s+obj\b/g;

export class Pdf {
  constructor(bytes) {
    this.bytes = bytes;
    this.text = new TextDecoder("latin1").decode(bytes);
    if (!this.text.startsWith("%PDF-")) {
      throw new PdfError("Not a PDF file (missing %PDF- header).");
    }
    if (this.text.includes("/ObjStm")) {
      throw new PdfError(
        "This PDF uses object streams, which this reader does not support. " +
          "Re-export it from CLO 3D, or flatten it first with Ghostscript."
      );
    }
    this.offsets = new Map();
    OBJ_RE.lastIndex = 0;
    let m;
    while ((m = OBJ_RE.exec(this.text)) !== null) {
      // Later definitions win: incremental updates append revised objects.
      this.offsets.set(Number(m[1]), m.index + m[0].length);
    }
    this.streams = new Map();
  }

  raw(num) {
    const start = this.offsets.get(num);
    if (start === undefined) throw new PdfError(`object ${num} not found`);
    const end = this.text.indexOf("endobj", start);
    if (end < 0) throw new PdfError(`object ${num} has no endobj`);
    return this.text.slice(start, end);
  }

  // Decode every stream up front so the interpreter can stay synchronous;
  // DecompressionStream is async and the interpreter recurses through forms.
  async decodeAll() {
    this.failed = [];
    for (const num of this.offsets.keys()) {
      const body = this.raw(num);
      const i = body.indexOf("stream");
      if (i < 0) continue;
      try {
        this.streams.set(num, await this.#decode(num, body, i));
      } catch (err) {
        this.failed.push(num);
      }
    }
  }

  async #decode(num, body, i) {
    const base = this.offsets.get(num);
    let j = i + "stream".length;
    if (body.slice(j, j + 2) === "\r\n") j += 2;
    else if (body[j] === "\r" || body[j] === "\n") j += 1;
    let k = body.lastIndexOf("endstream");
    if (k < 0) k = body.length;

    const header = body.slice(0, i);

    // Prefer the declared /Length. DecompressionStream rejects trailing bytes,
    // and there is almost always an EOL between the data and "endstream" --
    // Python's decompressobj ignores it, the browser's does not.
    const lenMatch = /\/Length\s+(\d+)(?!\s+\d+\s+R)/.exec(header);
    let end = base + k;
    if (lenMatch) {
      const declared = base + j + Number(lenMatch[1]);
      if (declared <= base + k) end = declared;
    }

    let payload = this.bytes.subarray(base + j, end);
    if (!header.includes("/FlateDecode")) {
      if (header.includes("/Filter")) {
        throw new PdfError(`object ${num}: unsupported stream filter`);
      }
      return new TextDecoder("latin1").decode(payload);
    }

    try {
      return await inflate(payload);
    } catch (err) {
      // Fall back to trimming trailing EOL bytes, for writers whose /Length
      // disagrees with the actual payload.
      let stop = base + k;
      while (stop > base + j) {
        const c = this.bytes[stop - 1];
        if (c === 0x0a || c === 0x0d || c === 0x20) stop -= 1;
        else break;
      }
      return await inflate(this.bytes.subarray(base + j, stop));
    }
  }

  stream(num) {
    const s = this.streams.get(num);
    if (s === undefined) throw new PdfError(`object ${num} has no usable stream`);
    return s;
  }

  hasStream(num) {
    return this.streams.has(num);
  }

  ref(body, key) {
    const m = new RegExp(`/${key}\\s+(\\d+)\\s+\\d+\\s+R\\b`).exec(body);
    return m ? Number(m[1]) : null;
  }

  name(body, key) {
    const m = new RegExp(`/${key}\\s*\\(`).exec(body);
    if (!m) return null;
    return unescapeString(balancedString(body, m.index + m[0].length - 1));
  }

  numbers(body, key) {
    const m = new RegExp(`/${key}\\s*\\[([^\\]]*)\\]`).exec(body);
    if (!m) return null;
    const found = m[1].match(/[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g);
    return found ? found.map(Number) : [];
  }

  xobjects(body) {
    const out = {};
    const re = /\/([A-Za-z0-9_.#-]+)\s+(\d+)\s+\d+\s+R/g;
    let m;
    while ((m = re.exec(body)) !== null) out[m[1]] = Number(m[2]);
    return out;
  }
}

async function inflate(payload) {
  const stream = new Blob([payload])
    .stream()
    .pipeThrough(new DecompressionStream("deflate"));
  const buf = await new Response(stream).arrayBuffer();
  return new TextDecoder("latin1").decode(new Uint8Array(buf));
}

function balancedString(body, start) {
  let depth = 0;
  let i = start;
  let out = "";
  while (i < body.length) {
    const c = body[i];
    if (c === "\\") {
      out += body.slice(i, i + 2);
      i += 2;
      continue;
    }
    if (c === "(") {
      depth += 1;
      if (depth === 1) {
        i += 1;
        continue;
      }
    } else if (c === ")") {
      depth -= 1;
      if (depth === 0) return out;
    }
    out += c;
    i += 1;
  }
  return out;
}

const ESCAPES = { n: "\n", r: "\r", t: "\t", b: "\b", f: "\f" };

export function unescapeString(s) {
  let out = "";
  let i = 0;
  while (i < s.length) {
    if (s[i] !== "\\") {
      out += s[i];
      i += 1;
      continue;
    }
    const next = s[i + 1];
    if (next >= "0" && next <= "9") {
      let digits = "";
      let j = i + 1;
      while (j < s.length && digits.length < 3 && s[j] >= "0" && s[j] <= "9") {
        digits += s[j];
        j += 1;
      }
      out += String.fromCharCode(parseInt(digits, 8) & 0xff);
      i = j;
    } else if (next in ESCAPES) {
      out += ESCAPES[next];
      i += 2;
    } else {
      out += next;
      i += 2;
    }
  }
  return out;
}

export async function load(bytes) {
  const pdf = new Pdf(bytes);
  await pdf.decodeAll();
  return pdf;
}
