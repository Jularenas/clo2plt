// Load a CLO 3D marker PDF into classified geometry. Mirrors clo2plt/document.py.

import * as classify from "./classify.js";
import * as g from "./geometry.js";
import { Interpreter, parseToUnicode } from "./content.js";
import { PdfError, load } from "./pdfread.js";

export const MM_PER_POINT = 25.4 / 72;

export async function read(bytes, { tolerance = 0.05, pieces = null } = {}) {
  const pdf = await load(bytes);
  const page = firstPage(pdf);
  const body = pdf.raw(page);

  const media = pdf.numbers(body, "MediaBox");
  if (!media || media.length !== 4) {
    throw new PdfError("This page has no usable /MediaBox.");
  }

  // Land everything in millimetres: the page `cm` maps content units to
  // points, and this converts points to mm.
  const unit = [
    MM_PER_POINT, 0, 0, MM_PER_POINT,
    -media[0] * MM_PER_POINT, -media[1] * MM_PER_POINT,
  ];
  const interp = new Interpreter(pdf, tolerance, toUnicode(pdf));
  interp.runPage(page, unit);

  const pageW = (media[2] - media[0]) * MM_PER_POINT;
  const pageH = (media[3] - media[1]) * MM_PER_POINT;

  const unknown = new Map();
  for (const s of interp.strokes) {
    s.kind = classify.lineType(s.rgb);
    if (s.kind === classify.UNKNOWN) {
      const key = s.rgb.map((v) => v.toFixed(6)).join(" ");
      unknown.set(key, (unknown.get(key) || 0) + 1);
    }
  }

  let strokes = interp.strokes;
  let labels = interp.labels;
  if (pieces && pieces.length) {
    const wanted = new Set(pieces.map((p) => p.trim().toLowerCase()).filter(Boolean));
    strokes = strokes.filter((s) => wanted.has(s.piece.toLowerCase()));
    labels = labels.filter((l) => wanted.has(l.piece.toLowerCase()));
    const found = new Set(strokes.map((s) => s.piece.toLowerCase()));
    const missing = [...wanted].filter((w) => !found.has(w));
    if (missing.length) throw new PdfError(`No such piece: ${missing.join(", ")}`);
  }

  const byName = new Map();
  for (const s of strokes) {
    if (!byName.has(s.piece)) byName.set(s.piece, { name: s.piece, strokes: [], labels: [] });
    byName.get(s.piece).strokes.push(s);
  }
  for (const l of labels) {
    if (!byName.has(l.piece)) byName.set(l.piece, { name: l.piece, strokes: [], labels: [] });
    byName.get(l.piece).labels.push(l);
  }

  const prod = /\/Producer\s*\(([^)]*)\)/.exec(pdf.text);

  const marker = {
    pageW, pageH,
    pieces: [...byName.values()],
    strokes, labels,
    unknownColors: unknown,
    fillsDropped: interp.fillsDropped,
    curves: interp.curves,
    lines: interp.lines,
    producer: prod ? prod[1] : "",
  };
  marker.bbox = g.bbox(strokes.map((s) => s.points));
  marker.counts = counts(marker);
  return marker;
}

export function counts(marker) {
  const tally = {};
  for (const k of classify.ORDER) tally[k] = 0;
  for (const s of marker.strokes) tally[s.kind] += 1;
  tally[classify.LABEL] = marker.labels.length;
  return tally;
}

function firstPage(pdf) {
  for (const num of pdf.offsets.keys()) {
    if (/\/Type\s*\/Page[^s]/.test(pdf.raw(num))) return num;
  }
  throw new PdfError("No page object found in this PDF.");
}

function toUnicode(pdf) {
  const mapping = new Map();
  for (const m of pdf.text.matchAll(/\/ToUnicode\s+(\d+)\s+\d+\s+R/g)) {
    const num = Number(m[1]);
    if (!pdf.hasStream(num)) continue;
    for (const [k, v] of parseToUnicode(pdf.stream(num))) mapping.set(k, v);
  }
  return mapping;
}
