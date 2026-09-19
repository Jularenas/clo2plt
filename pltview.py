#!/usr/bin/env python3
"""pltview -- inspect and preview an HP-GL plotter file.

Reads the .plt itself, so what you see is the file the plotter receives. Works
on any HP-GL, not only output from clo2plt.
"""

import argparse
import os
import sys

from clo2plt import classify, hpglread, svgproof


def build_parser():
    p = argparse.ArgumentParser(
        prog="pltview",
        description="Preview an HP-GL (.plt) file as a scrollable proof sheet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  pltview.py marker.plt              # writes marker.plt.html next to it
  pltview.py marker.plt -o view.html
  pltview.py marker.plt --report     # numbers only, no file written
""",
    )
    p.add_argument("input", help="HP-GL file (.plt)")
    p.add_argument("-o", "--output", help="HTML output path "
                                          "(default: <input>.html)")
    p.add_argument("--report", action="store_true",
                   help="print the summary only, write nothing")
    p.add_argument("--units", type=float, default=hpglread.MM_PER_UNIT and 40.0,
                   metavar="N", help="plotter units per mm (default: 40)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        with open(args.input, "r", encoding="latin-1") as fh:
            data = fh.read()
    except OSError as exc:
        print(f"pltview: error: cannot read {args.input}: {exc}", file=sys.stderr)
        return 1

    if args.units <= 0:
        build_parser().error("--units must be greater than 0")

    drawing = hpglread.parse(data, units_per_mm=args.units)

    if not drawing.polylines and not drawing.texts:
        print(f"pltview: error: no drawable geometry found in {args.input}; "
              "is it HP-GL?", file=sys.stderr)
        return 1

    # Name the pens when they match clo2plt's default map, so a converted
    # marker reads as cut/seam/notch rather than 1/2/3.
    names = {pen: kind for kind, pen in classify.DEFAULT_PENS.items()}

    _report(args.input, drawing, names)

    if args.report:
        return 0

    out = args.output or (args.input + ".html")
    html = svgproof.emit_drawing(drawing, os.path.basename(args.input), names)
    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
    except OSError as exc:
        print(f"pltview: error: cannot write {out}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote  {out}", file=sys.stderr)
    return 0


def _report(path, drawing, names):
    out = sys.stderr
    box = drawing.bbox
    points = sum(len(p.points) for p in drawing.polylines)
    print(f"read   {path}", file=out)
    print(f"       {box[2] - box[0]:.1f} x {box[3] - box[1]:.1f} mm, "
          f"origin at ({box[0]:.1f}, {box[1]:.1f})", file=out)
    print(f"       {len(drawing.polylines)} polylines, {points:,} points, "
          f"{len(drawing.texts)} labels", file=out)

    by_pen = {}
    for poly in drawing.polylines:
        by_pen[poly.pen] = by_pen.get(poly.pen, 0) + 1
    for t in drawing.texts:
        by_pen.setdefault(t.pen, 0)
    for pen in sorted(by_pen):
        label = f" ({names[pen]})" if pen in names else ""
        ntext = sum(1 for t in drawing.texts if t.pen == pen)
        extra = f", {ntext} labels" if ntext else ""
        print(f"       pen {pen}{label}: {by_pen[pen]} lines{extra}", file=out)

    if drawing.unsupported:
        print("WARN   instructions this preview does not draw: "
              + ", ".join(f"{k} x{v}" for k, v in
                          sorted(drawing.unsupported.items())), file=out)
        print("       the plotter still honours them; only the preview "
              "omits them.", file=out)


if __name__ == "__main__":
    sys.exit(main())
