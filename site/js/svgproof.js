// Preview renderer. Draws the flattened, placed, pen-mapped geometry -- the
// same data the HP-GL emitter consumes -- so the preview proves the .plt
// rather than re-rendering the PDF.

import * as classify from "./classify.js";

// Stroke widths in screen pixels, paired with vector-effect:non-scaling-stroke.
// Widths in millimetres go sub-pixel once a 3-metre marker is scaled to fit a
// screen, which washes the lines out; these stay legible at any zoom.
const WIDTHS = {
  [classify.LABEL]: 0.9,
  [classify.CUT]: 1.7,
  [classify.SEAM]: 1.2,
  [classify.NOTCH]: 1.5,
  [classify.GRAIN]: 1.2,
  [classify.INTERNAL]: 1.2,
  [classify.UNKNOWN]: 2.0,
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

/** Returns SVG markup for the converted geometry. */
export function svg(strokes, labels, extent, marker, { showPage = true } = {}) {
  const [minx, miny, maxx, maxy] = extent;
  const w = Math.max(maxx - minx, 1);
  const h = Math.max(maxy - miny, 1);
  const pad = Math.max(w, h) * 0.01;

  const pt = (x, y) => `${(x - minx + pad).toFixed(3)},${(maxy - y + pad).toFixed(3)}`;

  const groups = new Map();
  for (const s of strokes) {
    if (!groups.has(s.kind)) groups.set(s.kind, []);
    groups.get(s.kind).push(s);
  }

  const body = [];
  if (showPage && marker) {
    body.push(
      `<rect class="pagebox" x="${(pad - minx).toFixed(2)}" ` +
        `y="${(maxy - marker.pageH + pad).toFixed(2)}" ` +
        `width="${marker.pageW.toFixed(2)}" height="${marker.pageH.toFixed(2)}"/>`
    );
  }

  for (const kind of classify.ORDER) {
    const list = groups.get(kind);
    if (!list) continue;
    body.push(
      `<g data-kind="${kind}" fill="none" stroke="${classify.PROOF_COLORS[kind]}" ` +
        `stroke-width="${WIDTHS[kind] ?? 1.2}" vector-effect="non-scaling-stroke" ` +
        `stroke-linecap="round" stroke-linejoin="round">`
    );
    for (const s of list) {
      body.push(
        `<polyline data-piece="${esc(s.piece)}" points="${s.points
          .map(([x, y]) => pt(x, y))
          .join(" ")}"/>`
      );
    }
    body.push("</g>");
  }

  if (labels.length) {
    body.push(`<g data-kind="label" fill="${classify.PROOF_COLORS[classify.LABEL]}" stroke="none">`);
    for (const l of labels) {
      const sx = l.origin[0] - minx + pad;
      const sy = maxy - l.origin[1] + pad;
      body.push(
        `<text x="0" y="0" font-size="${l.size.toFixed(2)}" ` +
          `font-family="system-ui,sans-serif" ` +
          `transform="translate(${sx.toFixed(3)},${sy.toFixed(3)}) rotate(${(-l.angle).toFixed(3)})">` +
          `${esc(l.text)}</text>`
      );
    }
    body.push("</g>");
  }

  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${(w + 2 * pad).toFixed(2)} ` +
    `${(h + 2 * pad).toFixed(2)}" preserveAspectRatio="xMidYMid meet">\n${body.join("\n")}\n</svg>`
  );
}
