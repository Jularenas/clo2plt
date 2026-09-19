// Affine transforms and adaptive Bezier flattening.
// Mirrors clo2plt/geometry.py; the two must stay in step, since the Python
// side is the reference implementation the tests verify against.

export const IDENTITY = [1, 0, 0, 1, 0, 0];

export function multiply(m, n) {
  const [a, b, c, d, e, f] = m;
  const [A, B, C, D, E, F] = n;
  return [
    a * A + b * C,
    a * B + b * D,
    c * A + d * C,
    c * B + d * D,
    e * A + f * C + E,
    e * B + f * D + F,
  ];
}

export function apply(m, x, y) {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
}

export function scaleOf(m) {
  return (Math.hypot(m[0], m[1]) + Math.hypot(m[2], m[3])) / 2;
}

export function rotationOf(m) {
  return (Math.atan2(m[1], m[0]) * 180) / Math.PI;
}

// Python's round() uses banker's rounding; JS Math.round() does not. Plotter
// coordinates land on exact .5 often enough that this changes bytes, so the
// Python behaviour is reproduced here to keep outputs identical.
export function pyRound(value) {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

export function flattenCubic(p0, p1, p2, p3, tol, out, depth = 0) {
  if (depth >= 24) {
    out.push(p3);
    return;
  }
  const [x0, y0] = p0;
  const [x3, y3] = p3;
  const dx = x3 - x0;
  const dy = y3 - y0;
  const chord = Math.hypot(dx, dy);

  if (chord < 1e-12) {
    const spread = Math.max(
      Math.hypot(p1[0] - x0, p1[1] - y0),
      Math.hypot(p2[0] - x0, p2[1] - y0)
    );
    if (spread <= tol) {
      out.push(p3);
      return;
    }
  } else {
    const d1 = Math.abs((p1[0] - x0) * dy - (p1[1] - y0) * dx) / chord;
    const d2 = Math.abs((p2[0] - x0) * dy - (p2[1] - y0) * dx) / chord;
    if (Math.max(d1, d2) <= tol) {
      out.push(p3);
      return;
    }
  }

  const p01 = [(x0 + p1[0]) / 2, (y0 + p1[1]) / 2];
  const p12 = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
  const p23 = [(p2[0] + x3) / 2, (p2[1] + y3) / 2];
  const p012 = [(p01[0] + p12[0]) / 2, (p01[1] + p12[1]) / 2];
  const p123 = [(p12[0] + p23[0]) / 2, (p12[1] + p23[1]) / 2];
  const mid = [(p012[0] + p123[0]) / 2, (p012[1] + p123[1]) / 2];

  flattenCubic(p0, p01, p012, mid, tol, out, depth + 1);
  flattenCubic(mid, p123, p23, p3, tol, out, depth + 1);
}

export function bbox(polylines) {
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const pts of polylines) {
    for (const [x, y] of pts) {
      if (x < minx) minx = x;
      if (x > maxx) maxx = x;
      if (y < miny) miny = y;
      if (y > maxy) maxy = y;
    }
  }
  if (minx === Infinity) return null;
  return [minx, miny, maxx, maxy];
}

export function dedupe(points, eps = 1e-9) {
  const out = [];
  for (const p of points) {
    const last = out[out.length - 1];
    if (!last || Math.abs(p[0] - last[0]) > eps || Math.abs(p[1] - last[1]) > eps) {
      out.push(p);
    }
  }
  return out;
}
