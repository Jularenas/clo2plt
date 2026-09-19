// HP-GL emitter. Mirrors clo2plt/hpgl.py, byte for byte.

import * as classify from "./classify.js";
import { pyRound } from "./geometry.js";

export const UNITS_PER_MM = 40; // 1 plotter unit = 0.025 mm
const TERM = "\x03";            // ETX, the default HP-GL label terminator
const MAX_LINE = 240;           // stay under a 255-byte controller buffer

function u(mm) {
  return pyRound(mm * UNITS_PER_MM);
}

export function emit(strokes, labels, pens, textMode = "label", pageAdvance = false,
                     header = null, viewerColors = false) {
  const out = [];
  if (header) for (const line of header) out.push(`CO"${toAscii(line)[0]}";`);
  out.push("IN;");
  if (viewerColors) {
    // PC is HP-GL/2. Viewers honour it instead of their default palette;
    // plotters that do not know it skip it. Opt-in, so a plain-HP-GL
    // controller never meets it unasked.
    for (const pen of [...new Set(Object.values(pens))].sort((a, b) => a - b)) {
      const rgb = classify.PEN_RGB[pen];
      if (rgb) out.push(`PC${pen},${rgb[0]},${rgb[1]},${rgb[2]};`);
    }
  }
  out.push("PA;");

  const byPen = new Map();
  for (const s of strokes) {
    const pen = pens[s.kind] ?? pens[classify.UNKNOWN];
    if (!byPen.has(pen)) byPen.set(pen, []);
    byPen.get(pen).push(s);
  }

  const labelPen = pens[classify.LABEL] ?? 6;
  if (labels.length && textMode === "label" && !byPen.has(labelPen)) {
    byPen.set(labelPen, []);
  }

  let retitled = [];
  let wantLabels = labels.length > 0 && textMode === "label";

  for (const pen of [...byPen.keys()].sort((a, b) => a - b)) {
    out.push(`SP${pen};`);
    for (const stroke of byPen.get(pen)) out.push(...polyline(stroke.points));
    if (wantLabels && pen === labelPen) {
      const [lines, changed] = labelBlock(labels);
      out.push(...lines);
      retitled = changed;
      wantLabels = false;
    }
  }

  out.push("PU;");
  out.push("SP0;");
  if (pageAdvance) out.push("PG;");
  out.push("IN;");
  return [out.join("\n") + "\n", retitled];
}

function polyline(points) {
  if (points.length < 2) return [];
  const lines = [`PU${u(points[0][0])},${u(points[0][1])};`];
  let parts = [];
  let length = 3; // "PD" plus the trailing ";"
  for (let i = 1; i < points.length; i += 1) {
    const coord = `${u(points[i][0])},${u(points[i][1])}`;
    let extra = coord.length + (parts.length ? 1 : 0);
    if (parts.length && length + extra > MAX_LINE) {
      lines.push(`PD${parts.join(",")};`);
      parts = [];
      length = 3;
      extra = coord.length;
    }
    parts.push(coord);
    length += extra;
  }
  if (parts.length) lines.push(`PD${parts.join(",")};`);
  return lines;
}

function labelBlock(labels) {
  if (!labels.length) return [[], []];
  const lines = [`DT${TERM};`];
  const retitled = [];
  for (const l of labels) {
    // SI sets the character cell in centimetres; ratios come from the
    // embedded font's metrics so plotter text matches CLO's size.
    const w = (0.6 * l.size) / 10;
    const h = (0.72 * l.size) / 10;
    const rad = (l.angle * Math.PI) / 180;
    lines.push(`SI${w.toFixed(4)},${h.toFixed(4)};`);
    lines.push(`DI${Math.cos(rad).toFixed(6)},${Math.sin(rad).toFixed(6)};`);
    const [text, changed] = toAscii(l.text);
    if (changed) retitled.push([l.text, text]);
    lines.push(`PU${u(l.origin[0])},${u(l.origin[1])};`);
    lines.push(`LB${text}${TERM};`);
  }
  lines.push("DI1,0;");
  return [lines, retitled];
}

// Plain HP-GL only guarantees ASCII, and a high byte can end a label early on
// some controllers, so accents are folded to their base letter.
export function toAscii(text) {
  const folded = text.normalize("NFKD").replace(/\p{M}/gu, "");
  let out = "";
  for (const ch of folded) {
    const code = ch.codePointAt(0);
    if (code >= 32 && code < 127 && ch !== TERM) out += ch;
  }
  return [out, out !== text];
}
