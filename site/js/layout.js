// Rotation, scaling and origin handling. Mirrors clo2plt/layout.py.

import * as g from "./geometry.js";

export const ROTATIONS = [0, 90, 180, 270];

export function place(marker, rotate = 0, origin = "fit", scale = 1) {
  if (!ROTATIONS.includes(rotate)) throw new Error(`rotate must be one of ${ROTATIONS}`);
  if (scale <= 0) throw new Error("scale must be greater than 0");

  const rad = (rotate * Math.PI) / 180;
  const cos = Math.round(Math.cos(rad));
  const sin = Math.round(Math.sin(rad));
  const rot = [cos * scale, sin * scale, -sin * scale, cos * scale, 0, 0];

  let strokes = marker.strokes.map((s) => ({
    ...s,
    points: s.points.map(([x, y]) => g.apply(rot, x, y)),
  }));
  let labels = marker.labels.map((l) => ({
    ...l,
    origin: g.apply(rot, l.origin[0], l.origin[1]),
    angle: norm(l.angle + rotate),
    size: l.size * scale,
  }));

  const box = g.bbox(strokes.map((s) => s.points)) || [0, 0, 0, 0];
  let dx, dy;
  if (origin === "fit") {
    dx = -box[0];
    dy = -box[1];
  } else if (origin === "page") {
    const corners = [
      [0, 0], [marker.pageW, 0], [marker.pageW, marker.pageH], [0, marker.pageH],
    ].map(([x, y]) => g.apply(rot, x, y));
    dx = -Math.min(...corners.map((c) => c[0]));
    dy = -Math.min(...corners.map((c) => c[1]));
  } else {
    throw new Error("origin must be 'fit' or 'page'");
  }

  if (dx || dy) {
    strokes = strokes.map((s) => ({
      ...s,
      points: s.points.map(([x, y]) => [x + dx, y + dy]),
    }));
    labels = labels.map((l) => ({
      ...l,
      origin: [l.origin[0] + dx, l.origin[1] + dy],
    }));
  }

  const extent = g.bbox(strokes.map((s) => s.points)) || [0, 0, 0, 0];
  return { strokes, labels, extent, shift: [dx, dy] };
}

function norm(deg) {
  const d = ((deg % 360) + 360) % 360;
  return d > 180 ? d - 360 : d;
}
