// Calibration target. Mirrors caltest.py.

import * as classify from "./classify.js";

function stroke(points, kind) {
  return { points, rgb: [0, 0, 0], width: 0, piece: "calibration", kind };
}

export function build(size = 200, margin = 10) {
  const x0 = margin, y0 = margin;
  const x1 = x0 + size, y1 = y0 + size;
  const half = size / 2;
  const strokes = [];
  const labels = [];

  strokes.push(stroke(
    [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], classify.CUT));

  const q = size / 4;
  strokes.push(stroke(
    [[x0 + q, y0 + q], [x1 - q, y0 + q], [x1 - q, y1 - q],
     [x0 + q, y1 - q], [x0 + q, y0 + q]], classify.SEAM));

  const step = 50;
  const n = Math.floor(size / step);
  for (let i = 0; i <= n; i += 1) {
    const d = i * step;
    strokes.push(stroke([[x0 + d, y0], [x0 + d, y0 + 10]], classify.NOTCH));
    strokes.push(stroke([[x0, y0 + d], [x0 + 10, y0 + d]], classify.NOTCH));
  }

  strokes.push(stroke([[x0, y0], [x1, y1]], classify.GRAIN));
  strokes.push(stroke([[x0, y1], [x1, y0]], classify.GRAIN));

  strokes.push(stroke(
    [[x0 + half - 50, y0 + half], [x0 + half + 50, y0 + half]], classify.INTERNAL));

  const label = (text, origin, size_) => ({
    text, origin, angle: 0, size: size_, piece: "calibration",
  });
  labels.push(label(`OUTER SQUARE = ${size.toFixed(0)} mm`, [x0 + 6, y1 + 6], 8));
  labels.push(label(`INNER = ${(size / 2).toFixed(0)} mm`, [x0 + q + 4, y0 + q + 6], 6));
  labels.push(label("BAR = 100 mm", [x0 + half - 46, y0 + half + 4], 6));
  labels.push(label("ticks every 50 mm", [x0 + 6, y0 - 8], 6));

  return { strokes, labels };
}
