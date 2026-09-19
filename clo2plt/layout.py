"""Place marker geometry for output: rotation and origin handling."""

import math

from . import geometry as g

ROTATIONS = (0, 90, 180, 270)


def place(marker, rotate=0, origin="fit", scale=1.0):
    """Return (strokes, labels, extent, shift) positioned for the plotter.

    `origin='fit'` translates geometry so its own bounding box starts at (0,0),
    which matters because CLO lets grain-line arrows run past the page edge;
    'page' keeps CLO's page coordinates and lets the plotter clip them.

    `scale` is an escape hatch for plotter software that rescales despite being
    told not to: measure a known length, pass the reciprocal, and the error
    cancels. It is not a substitute for turning the software's scaling off.
    """
    if rotate not in ROTATIONS:
        raise ValueError(f"rotate must be one of {ROTATIONS}")
    if scale <= 0:
        raise ValueError("scale must be greater than 0")

    rad = math.radians(rotate)
    cos, sin = round(math.cos(rad)), round(math.sin(rad))
    rot = (cos * scale, sin * scale, -sin * scale, cos * scale, 0.0, 0.0)

    strokes = [
        _moved(s, [g.apply(rot, x, y) for x, y in s.points]) for s in marker.strokes
    ]
    labels = [
        _label(l, g.apply(rot, *l.origin), l.angle + rotate, l.size * scale)
        for l in marker.labels
    ]

    box = g.bbox([s.points for s in strokes]) or (0.0, 0.0, 0.0, 0.0)
    if origin == "fit":
        dx, dy = -box[0], -box[1]
    elif origin == "page":
        # Rotation about the origin can swing the page into negative space;
        # re-anchor to the rotated page rectangle, not to the geometry.
        corners = [
            g.apply(rot, x, y)
            for x, y in (
                (0, 0),
                (marker.page_w, 0),
                (marker.page_w, marker.page_h),
                (0, marker.page_h),
            )
        ]
        dx = -min(c[0] for c in corners)
        dy = -min(c[1] for c in corners)
    else:
        raise ValueError("origin must be 'fit' or 'page'")

    if dx or dy:
        strokes = [
            _moved(s, [(x + dx, y + dy) for x, y in s.points]) for s in strokes
        ]
        labels = [
            _label(l, (l.origin[0] + dx, l.origin[1] + dy), l.angle, l.size)
            for l in labels
        ]

    extent = g.bbox([s.points for s in strokes]) or (0.0, 0.0, 0.0, 0.0)
    return strokes, labels, extent, (dx, dy)


def _moved(stroke, points):
    from .content import Stroke

    out = Stroke(points, stroke.rgb, stroke.width, stroke.piece)
    out.kind = stroke.kind
    return out


def _label(label, origin, angle, size):
    from .content import Label

    return Label(label.text, origin, _norm(angle), size, label.piece)


def _norm(deg):
    d = deg % 360.0
    return d - 360.0 if d > 180.0 else d
