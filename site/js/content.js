// PDF content-stream interpreter. Mirrors clo2plt/content.py.
//
// Yields stroked polylines (flattened to mm) and text labels, each tagged with
// its pattern piece. Fills are discarded: the only filled paths CLO emits are
// the fabric texture preview, which means nothing to a plotter.

import * as g from "./geometry.js";
import { PdfError, unescapeString } from "./pdfread.js";

const NUM_RE = /^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/;
const TOKEN_RE =
  /\/[^\s/[\]()<>{}%]*|\[|\]|<<|>>|\([^)\\]*(?:\\[\s\S][^)\\]*)*\)|<[0-9A-Fa-f\s]*>|[^\s/[\]()<>{}%]+/g;

const PAINT = new Set(["S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"]);
const STROKING = new Set(["S", "s", "B", "B*", "b", "b*"]);
const FILLING = new Set(["f", "F", "f*"]);

export function tokenize(data) {
  TOKEN_RE.lastIndex = 0;
  return data.match(TOKEN_RE) || [];
}

function asNum(tok) {
  return NUM_RE.test(tok) ? Number(tok) : null;
}

export class Interpreter {
  constructor(pdf, tolerance = 0.05, toUnicode = null, widths = null, defaultWidth = 1000) {
    this.pdf = pdf;
    this.tol = tolerance;
    this.toUnicode = toUnicode || new Map();
    this.widths = widths || new Map();
    this.defaultWidth = defaultWidth;
    this.strokes = [];
    this.labels = [];
    this.fillsDropped = 0;
    this.curves = 0;
    this.lines = 0;
    this.piece = "";
    this.fontSize = 0;
    this.depth = 0;
  }

  runPage(pageObj, unit = g.IDENTITY) {
    const body = this.pdf.raw(pageObj);
    let base = g.IDENTITY;
    for (const num of contentRefs(body)) {
      if (this.pdf.hasStream(num)) {
        base = this.#pageMatrix(this.pdf.stream(num), base);
      }
    }
    base = g.multiply(base, unit);

    const xobjRef = this.pdf.ref(body, "XObject");
    if (xobjRef === null) {
      throw new PdfError(
        "This page has no form XObjects, so it does not look like a CLO 3D marker export."
      );
    }
    const forms = this.pdf.xobjects(this.pdf.raw(xobjRef));
    const names = Object.keys(forms).sort(formOrder);
    for (const name of names) this.#runPiece(forms[name], base);
  }

  #pageMatrix(stream, base) {
    let stack = [];
    for (const tok of tokenize(stream)) {
      if (tok === "cm" && stack.length >= 6) {
        base = g.multiply(stack.slice(-6), base);
        stack = [];
      } else {
        const n = asNum(tok);
        stack.push(n === null ? tok : n);
      }
    }
    return base;
  }

  #runPiece(formNum, base) {
    const body = this.pdf.raw(formNum);
    const oc = this.pdf.ref(body, "OC");
    this.piece = oc ? this.pdf.name(this.pdf.raw(oc), "Name") || "" : "";
    this.#execute(formNum, base);
  }

  #execute(formNum, ctm) {
    if (this.depth > 12) throw new PdfError("XObject nesting too deep");
    const body = this.pdf.raw(formNum);

    const matrix = this.pdf.numbers(body, "Matrix");
    if (matrix && matrix.length === 6) ctm = g.multiply(matrix, ctm);

    let forms = {};
    const resRef = this.pdf.ref(body, "Resources");
    if (resRef !== null) {
      const res = this.pdf.raw(resRef);
      const xo = this.pdf.ref(res, "XObject");
      if (xo !== null) forms = this.pdf.xobjects(this.pdf.raw(xo));
    }

    if (!this.pdf.hasStream(formNum)) return;
    this.depth += 1;
    try {
      this.#interpret(this.pdf.stream(formNum), ctm, forms);
    } finally {
      this.depth -= 1;
    }
  }

  #interpret(stream, ctm, forms) {
    let st = { ctm, rgb: [0, 0, 0], width: 0 };
    const stack = [];
    let operands = [];

    let path = [];
    let current = null;
    let start = null;
    let pendingText = null;
    let pendingCodes = [];
    let textMatrix = null;

    for (const tok of tokenize(stream)) {
      const num = asNum(tok);
      if (num !== null) {
        operands.push(num);
        continue;
      }
      const c = tok[0];
      if (c === "/" || c === "(" || c === "<" || c === "[" || c === "]") {
        operands.push(tok);
        continue;
      }

      const op = tok;
      const n = operands.length;

      if (op === "q") {
        stack.push({ ...st });
      } else if (op === "Q") {
        if (stack.length) st = stack.pop();
      } else if (op === "cm" && n >= 6) {
        st.ctm = g.multiply(operands.slice(-6), st.ctm);
      } else if (op === "w" && n) {
        st.width = operands[n - 1];
      } else if (op === "RG" && n >= 3) {
        st.rgb = operands.slice(-3);
      } else if (op === "G" && n) {
        const v = operands[n - 1];
        st.rgb = [v, v, v];
      } else if (op === "m" && n >= 2) {
        if (current) path.push(current);
        start = g.apply(st.ctm, operands[n - 2], operands[n - 1]);
        current = [start];
      } else if (op === "l" && n >= 2) {
        if (current !== null) {
          current.push(g.apply(st.ctm, operands[n - 2], operands[n - 1]));
          this.lines += 1;
        }
      } else if ((op === "c" || op === "v" || op === "y") && current !== null) {
        this.#curve(op, operands, st, current);
      } else if (op === "re" && n >= 4) {
        if (current) path.push(current);
        const [x, y, w, h] = operands.slice(-4);
        current = [
          g.apply(st.ctm, x, y),
          g.apply(st.ctm, x + w, y),
          g.apply(st.ctm, x + w, y + h),
          g.apply(st.ctm, x, y + h),
        ];
        current.push(current[0]);
        start = current[0];
      } else if (op === "h") {
        if (current && start && !same(current[current.length - 1], start)) {
          current.push(start);
        }
      } else if (PAINT.has(op)) {
        if ((op === "s" || op === "b" || op === "b*") && current && start) {
          current.push(start);
        }
        if (current) path.push(current);
        current = null;
        if (STROKING.has(op)) this.#emit(path, st);
        else if (FILLING.has(op)) this.fillsDropped += 1;
        path = [];
        start = null;
      } else if (op === "BT") {
        textMatrix = g.IDENTITY;
        pendingText = null;
      } else if (op === "Tf" && n) {
        this.fontSize = operands[n - 1];
      } else if (op === "Tm" && n >= 6) {
        textMatrix = operands.slice(-6);
      } else if ((op === "Td" || op === "TD") && n >= 2) {
        textMatrix = g.multiply(
          [1, 0, 0, 1, operands[n - 2], operands[n - 1]],
          textMatrix || g.IDENTITY
        );
      } else if (op === "Tj" || op === "TJ" || op === "'" || op === '"') {
        pendingCodes = codesOf(operands);
        pendingText = decode(pendingCodes, this.toUnicode);
      } else if (op === "ET") {
        if (pendingText && textMatrix) this.#label(pendingText, pendingCodes, textMatrix, st);
        pendingText = null;
        pendingCodes = [];
        textMatrix = null;
      } else if (op === "Do" && n) {
        const name = operands[n - 1];
        if (typeof name === "string" && name[0] === "/") {
          const ref = forms[name.slice(1)];
          if (ref !== undefined && this.#isForm(ref)) this.#execute(ref, st.ctm);
        }
      }

      operands = [];
    }

    if (current) path.push(current);
  }

  #curve(op, operands, st, current) {
    const p0 = current[current.length - 1];
    const n = operands.length;
    let p1, p2, p3;
    if (op === "c" && n >= 6) {
      const v = operands.slice(-6);
      p1 = g.apply(st.ctm, v[0], v[1]);
      p2 = g.apply(st.ctm, v[2], v[3]);
      p3 = g.apply(st.ctm, v[4], v[5]);
    } else if (op === "v" && n >= 4) {
      const v = operands.slice(-4);
      p1 = p0;
      p2 = g.apply(st.ctm, v[0], v[1]);
      p3 = g.apply(st.ctm, v[2], v[3]);
    } else if (op === "y" && n >= 4) {
      const v = operands.slice(-4);
      p1 = g.apply(st.ctm, v[0], v[1]);
      p3 = g.apply(st.ctm, v[2], v[3]);
      p2 = p3;
    } else {
      return;
    }
    g.flattenCubic(p0, p1, p2, p3, this.tol, current);
    this.curves += 1;
  }

  #emit(path, st) {
    for (let pts of path) {
      pts = g.dedupe(pts);
      if (pts.length >= 2) {
        this.strokes.push({
          points: pts,
          rgb: st.rgb,
          width: st.width * g.scaleOf(st.ctm),
          piece: this.piece,
        });
      }
    }
  }

  #label(text, codes, tm, st) {
    const m = g.multiply(tm, st.ctm);
    const size = this.fontSize * g.scaleOf(m);
    // Glyph widths are thousandths of the font size; CLO embeds one font.
    let units = 0;
    for (const c of codes) units += this.widths.get(c) ?? this.defaultWidth;
    this.labels.push({
      text,
      origin: [m[4], m[5]],
      angle: g.rotationOf(m),
      size,
      piece: this.piece,
      width: (units / 1000) * size,
    });
  }

  #isForm(num) {
    return this.pdf.raw(num).replace(/ /g, "").includes("/Subtype/Form");
  }
}

function same(a, b) {
  return a[0] === b[0] && a[1] === b[1];
}

function contentRefs(pageBody) {
  const arr = /\/Contents\s*\[([^\]]*)\]/.exec(pageBody);
  if (arr) {
    const found = arr[1].match(/(\d+)\s+\d+\s+R/g) || [];
    return found.map((s) => Number(/\d+/.exec(s)[0]));
  }
  const one = /\/Contents\s+(\d+)\s+\d+\s+R/.exec(pageBody);
  return one ? [Number(one[1])] : [];
}

function formOrder(a, b) {
  const na = /(\d+)$/.exec(a);
  const nb = /(\d+)$/.exec(b);
  const ia = na ? Number(na[1]) : 0;
  const ib = nb ? Number(nb[1]) : 0;
  if (ia !== ib) return ia - ib;
  return a < b ? -1 : a > b ? 1 : 0;
}

function codesOf(operands) {
  let raw = "";
  for (const tok of operands) {
    if (typeof tok !== "string") continue;
    if (tok[0] === "(") {
      raw += unescapeString(tok.slice(1, -1));
    } else if (tok[0] === "<" && tok[1] !== "<") {
      let hex = tok.slice(1, -1).replace(/\s/g, "");
      if (hex.length % 2) hex += "0";
      for (let i = 0; i < hex.length; i += 2) {
        raw += String.fromCharCode(parseInt(hex.slice(i, i + 2), 16));
      }
    }
  }
  // Identity-H: two-byte codes.
  const codes = [];
  for (let i = 0; i + 1 < raw.length; i += 2) {
    codes.push((raw.charCodeAt(i) << 8) | raw.charCodeAt(i + 1));
  }
  return codes;
}

function decode(codes, toUnicode) {
  let out = "";
  for (const c of codes) out += toUnicode.get(c) ?? String.fromCharCode(c);
  return out.trim();
}

/** Merge every CID font /W array into a Map(code -> width), plus /DW. */
export function parseWidths(text) {
  const widths = new Map();
  const head = /\/W\s*\[/g;
  let m;
  while ((m = head.exec(text)) !== null) {
    let depth = 1;
    let j = m.index + m[0].length;
    const start = j;
    while (depth && j < text.length) {
      if (text[j] === "[") depth += 1;
      else if (text[j] === "]") depth -= 1;
      j += 1;
    }
    const toks = text.slice(start, j - 1).match(/\[|\]|[-+]?\d*\.?\d+/g) || [];
    let k = 0;
    try {
      while (k < toks.length) {
        const first = Math.trunc(Number(toks[k]));
        if (toks[k + 1] === "[") {
          k += 2;
          let code = first;
          while (toks[k] !== "]") {
            if (toks[k] === undefined) throw new Error("unterminated");
            widths.set(code, Number(toks[k]));
            code += 1;
            k += 1;
          }
          k += 1;
        } else {
          if (toks[k + 2] === undefined) throw new Error("short range");
          const last = Math.trunc(Number(toks[k + 1]));
          const value = Number(toks[k + 2]);
          for (let code = first; code <= last; code += 1) widths.set(code, value);
          k += 3;
        }
      }
    } catch {
      // malformed array: keep what was read, estimate the rest
    }
  }
  const dw = /\/DW\s+([-+]?\d*\.?\d+)/.exec(text);
  return { widths, defaultWidth: dw ? Number(dw[1]) : 1000 };
}

export function parseToUnicode(stream) {
  const mapping = new Map();
  for (const block of stream.match(/beginbfchar[\s\S]*?endbfchar/g) || []) {
    const re = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g;
    let m;
    while ((m = re.exec(block)) !== null) {
      mapping.set(parseInt(m[1], 16), utf16(m[2]));
    }
  }
  for (const block of stream.match(/beginbfrange[\s\S]*?endbfrange/g) || []) {
    const re = /<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g;
    let m;
    while ((m = re.exec(block)) !== null) {
      const lo = parseInt(m[1], 16);
      const hi = parseInt(m[2], 16);
      const base = parseInt(m[3], 16);
      for (let i = lo; i <= hi; i += 1) {
        mapping.set(i, String.fromCharCode(base + i - lo));
      }
    }
  }
  return mapping;
}

function utf16(hex) {
  let out = "";
  for (let i = 0; i + 3 < hex.length + 1; i += 4) {
    const chunk = hex.slice(i, i + 4);
    if (chunk.length === 4) out += String.fromCharCode(parseInt(chunk, 16));
  }
  return out || "?";
}
