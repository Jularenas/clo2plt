#!/usr/bin/env python3
"""caltest -- emit a small HP-GL calibration target.

Load this in the plotter software, print it, and measure the squares with a
tape. If the outer square is not exactly 200 mm the software or the machine is
rescaling, and a full marker would be wrong by the same factor -- the one
failure that ruins fabric rather than just paper.

It also prints one shape per pen, so you can see whether your setup
distinguishes pens at all.
"""

import argparse
import sys

from clo2plt import classify, hpgl
from clo2plt.content import Label, Stroke


def _stroke(points, kind):
    s = Stroke(points, (0.0, 0.0, 0.0), 0.0, "calibration")
    s.kind = kind
    return s


def build(size=200.0, margin=10.0):
    """A nested-square target with 50 mm ticks, one feature per pen."""
    x0 = y0 = margin
    x1, y1 = x0 + size, y0 + size
    half = size / 2.0
    strokes, labels = [], []

    # pen 1 -- outer square, the measurement that matters
    strokes.append(_stroke(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], classify.CUT))

    # pen 2 -- inner square at half size, a second independent check
    q = size / 4.0
    strokes.append(_stroke(
        [(x0 + q, y0 + q), (x1 - q, y0 + q), (x1 - q, y1 - q),
         (x0 + q, y1 - q), (x0 + q, y0 + q)], classify.SEAM))

    # pen 3 -- 50 mm ticks along the bottom and left edges
    step = 50.0
    n = int(size // step)
    for i in range(n + 1):
        d = i * step
        strokes.append(_stroke([(x0 + d, y0), (x0 + d, y0 + 10.0)], classify.NOTCH))
        strokes.append(_stroke([(x0, y0 + d), (x0 + 10.0, y0 + d)], classify.NOTCH))

    # pen 4 -- diagonals; they must cross exactly at the centre
    strokes.append(_stroke([(x0, y0), (x1, y1)], classify.GRAIN))
    strokes.append(_stroke([(x0, y1), (x1, y0)], classify.GRAIN))

    # pen 5 -- a 100 mm horizontal bar through the middle
    strokes.append(_stroke(
        [(x0 + half - 50.0, y0 + half), (x0 + half + 50.0, y0 + half)],
        classify.INTERNAL))

    # pen 6 -- labels stating the true dimensions
    labels.append(Label(f"OUTER SQUARE = {size:.0f} mm", (x0 + 6.0, y1 + 6.0),
                        0.0, 8.0, "calibration"))
    labels.append(Label(f"INNER = {size / 2:.0f} mm", (x0 + q + 4.0, y0 + q + 6.0),
                        0.0, 6.0, "calibration"))
    labels.append(Label("BAR = 100 mm", (x0 + half - 46.0, y0 + half + 4.0),
                        0.0, 6.0, "calibration"))
    labels.append(Label("ticks every 50 mm", (x0 + 6.0, y0 - 8.0),
                        0.0, 6.0, "calibration"))
    return strokes, labels


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="caltest",
        description="Emit an HP-GL calibration target to verify 1:1 scale.")
    p.add_argument("-o", "--output", default="calibration.plt",
                   help="output path (default: calibration.plt)")
    p.add_argument("--size", type=float, default=200.0, metavar="MM",
                   help="outer square size in mm (default: 200)")
    p.add_argument("--pens", metavar="FILE", help="JSON pen map override")
    args = p.parse_args(argv)

    if args.size < 50.0:
        p.error("--size must be at least 50 mm")

    try:
        pens = classify.load_pens(args.pens)
    except (OSError, ValueError) as exc:
        print(f"caltest: error: pen map: {exc}", file=sys.stderr)
        return 1

    strokes, labels = build(args.size)
    data, _ = hpgl.emit(strokes, labels, pens)
    try:
        with open(args.output, "w", encoding="ascii", newline="\r\n") as fh:
            fh.write(data)
    except OSError as exc:
        print(f"caltest: error: cannot write {args.output}: {exc}", file=sys.stderr)
        return 1

    print(f"wrote  {args.output}", file=sys.stderr)
    print(f"       outer square {args.size:.0f} x {args.size:.0f} mm, "
          f"inner {args.size / 2:.0f} mm, 100 mm bar", file=sys.stderr)
    print("       print it, measure the outer square: it must read "
          f"{args.size:.0f} mm exactly.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
