"""Affine transforms and adaptive Bezier flattening.

Flattening quality is the main lever on cut accuracy: the plotter reproduces
exactly the polyline we hand it, so the chord tolerance here becomes real
deviation on fabric. Subdivision is recursive with a flatness test, which bounds
the error, rather than a fixed step count, which does not.
"""

import math

# PDF matrix [a b c d e f] == [[a b 0],[c d 0],[e f 1]]
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(m, n):
    """Return m concatenated with n (apply m first, then n)."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (
        a * A + b * C,
        a * B + b * D,
        c * A + d * C,
        c * B + d * D,
        e * A + f * C + E,
        e * B + f * D + F,
    )


def apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def scale_of(m):
    """Mean linear scale of a matrix, for converting tolerances across spaces."""
    a, b, c, d, _, _ = m
    return (math.hypot(a, b) + math.hypot(c, d)) / 2.0


def rotation_of(m):
    """Rotation angle in degrees implied by a matrix's x-axis."""
    a, b = m[0], m[1]
    return math.degrees(math.atan2(b, a))


def flatten_cubic(p0, p1, p2, p3, tol, out, depth=0):
    """Append points after p0 approximating the cubic within `tol`.

    Flatness test measures control-point deviation from the p0->p3 chord, which
    upper-bounds the true curve deviation.
    """
    if depth >= 24:
        out.append(p3)
        return

    x0, y0 = p0
    x3, y3 = p3
    dx, dy = x3 - x0, y3 - y0
    chord = math.hypot(dx, dy)

    if chord < 1e-12:
        # Degenerate chord (closed loop): fall back to control-hull extent so a
        # curve that returns to its origin still gets subdivided rather than
        # collapsing to a point.
        spread = max(
            math.hypot(p1[0] - x0, p1[1] - y0), math.hypot(p2[0] - x0, p2[1] - y0)
        )
        if spread <= tol:
            out.append(p3)
            return
    else:
        d1 = abs((p1[0] - x0) * dy - (p1[1] - y0) * dx) / chord
        d2 = abs((p2[0] - x0) * dy - (p2[1] - y0) * dx) / chord
        if max(d1, d2) <= tol:
            out.append(p3)
            return

    # de Casteljau split at t=0.5
    p01 = ((x0 + p1[0]) / 2, (y0 + p1[1]) / 2)
    p12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    p23 = ((p2[0] + x3) / 2, (p2[1] + y3) / 2)
    p012 = ((p01[0] + p12[0]) / 2, (p01[1] + p12[1]) / 2)
    p123 = ((p12[0] + p23[0]) / 2, (p12[1] + p23[1]) / 2)
    mid = ((p012[0] + p123[0]) / 2, (p012[1] + p123[1]) / 2)

    flatten_cubic(p0, p01, p012, mid, tol, out, depth + 1)
    flatten_cubic(mid, p123, p23, p3, tol, out, depth + 1)


def bbox(polylines):
    """Bounding box (minx, miny, maxx, maxy) over an iterable of point lists."""
    minx = miny = math.inf
    maxx = maxy = -math.inf
    for pts in polylines:
        for x, y in pts:
            if x < minx:
                minx = x
            if x > maxx:
                maxx = x
            if y < miny:
                miny = y
            if y > maxy:
                maxy = y
    if minx is math.inf:
        return None
    return (minx, miny, maxx, maxy)


def dedupe(points, eps=1e-9):
    """Drop consecutive duplicate points, which plotters render as pen jitter."""
    out = []
    for p in points:
        if not out or abs(p[0] - out[-1][0]) > eps or abs(p[1] - out[-1][1]) > eps:
            out.append(p)
    return out
