#!/usr/bin/env python3
"""clo2plt -- convert CLO 3D marker PDFs to HP-GL plotter files.

Preserves every line type CLO exports: cut lines, seam lines, notches, grain
lines, internal/fold lines and piece labels, each on its own pen.
"""

import argparse
import sys

from clo2plt import classify, hpgl, layout, svgproof
from clo2plt import document
from clo2plt.pdfread import PdfError


def build_parser():
    p = argparse.ArgumentParser(
        prog="clo2plt",
        description="Convert a CLO 3D marker PDF to HP-GL (.plt), full detail intact.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  clo2plt.py marker.pdf -o marker.plt --svg proof.html
  clo2plt.py marker.pdf --list
  clo2plt.py marker.pdf -o test.plt --pieces "pretina pantalon"
""",
    )
    p.add_argument("input", help="CLO 3D marker PDF")
    p.add_argument("-o", "--output", help="HP-GL output path (.plt)")
    p.add_argument("--svg", metavar="FILE", help="write an SVG proof sheet")
    p.add_argument("--list", action="store_true",
                   help="list pieces and element counts, convert nothing")
    p.add_argument("--tolerance", type=float, default=0.05, metavar="MM",
                   help="Bezier flattening tolerance in mm (default: 0.05)")
    p.add_argument("--text", choices=("label", "outline", "none"), default="label",
                   help="labels as plotter text, vector outlines, or omitted")
    p.add_argument("--pieces", metavar="NAMES",
                   help="comma-separated piece names to include")
    p.add_argument("--pens", metavar="FILE", help="JSON pen map override")
    p.add_argument("--rotate", type=int, choices=layout.ROTATIONS, default=0,
                   help="rotate the marker by this many degrees")
    p.add_argument("--scale", type=float, default=1.0, metavar="F",
                   help="multiply all coordinates by F. Escape hatch for "
                        "software that rescales: if a 200 mm square prints at "
                        "206 mm, pass --scale 0.9709 (200/206)")
    p.add_argument("--origin", choices=("fit", "page"), default="fit",
                   help="'fit' shifts geometry to its own bbox (default), "
                        "'page' keeps CLO page coordinates")
    p.add_argument("--page-advance", action="store_true",
                   help="append PG; to advance the page when finished")
    p.add_argument("--comment", action="store_true",
                   help="prepend HP-GL/2 CO provenance comments (off by "
                        "default: plain HP-GL has no comment instruction)")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress the report")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if not args.list and not args.output and not args.svg:
        build_parser().error("nothing to do: pass -o/--output, --svg, or --list")

    if args.tolerance <= 0:
        build_parser().error("--tolerance must be greater than 0")

    if args.scale <= 0:
        build_parser().error("--scale must be greater than 0")

    try:
        pens = classify.load_pens(args.pens)
    except (OSError, ValueError) as exc:
        return _fail(f"pen map: {exc}")

    names = args.pieces.split(",") if args.pieces else None

    try:
        marker = document.read(args.input, tolerance=args.tolerance, pieces=names)
    except PdfError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(f"cannot read {args.input}: {exc}")

    if args.list:
        _list(marker)
        return 0

    strokes, labels, extent, shift = layout.place(
        marker, args.rotate, args.origin, args.scale)

    if args.text == "none":
        labels = []
    elif args.text == "outline":
        from clo2plt import glyphs
        from clo2plt.pdfread import load

        try:
            outlines, missing = glyphs.outline_labels(
                load(args.input), labels, args.tolerance
            )
        except PdfError as exc:
            return _fail(str(exc))
        if missing:
            print("clo2plt: warning: the embedded font has no glyph for "
                  + ", ".join(repr(c) for c in missing)
                  + "; those characters are blank in the labels",
                  file=sys.stderr)
        strokes = strokes + outlines
        labels = []

    retitled = []
    if args.output:
        header = None
        if args.comment:
            header = [
                f"clo2plt {args.input.rsplit('/', 1)[-1]}",
                f"{extent[2] - extent[0]:.1f}x{extent[3] - extent[1]:.1f}mm "
                f"tol={args.tolerance}mm rot={args.rotate}",
            ]
        text_mode = "label" if args.text == "label" else "none"
        data, retitled = hpgl.emit(strokes, labels, pens, text_mode,
                                   args.page_advance, header)
        try:
            with open(args.output, "w", encoding="ascii", newline="\r\n") as fh:
                fh.write(data)
        except OSError as exc:
            return _fail(f"cannot write {args.output}: {exc}")

    if args.svg:
        title = args.input.rsplit("/", 1)[-1]
        svg = svgproof.emit(strokes, labels, extent, marker, pens, title)
        try:
            with open(args.svg, "w", encoding="utf-8") as fh:
                fh.write(svg)
        except OSError as exc:
            return _fail(f"cannot write {args.svg}: {exc}")

    if not args.quiet:
        _report(marker, strokes, labels, extent, shift, pens, args, retitled)
    return 0


def _list(marker):
    print(f"{marker.path}")
    print(f"  producer : {marker.producer or 'unknown'}")
    print(f"  page     : {marker.page_w:.1f} x {marker.page_h:.1f} mm")
    print(f"  pieces   : {len(marker.pieces)}")
    print()
    width = max((len(p.name) for p in marker.pieces), default=4)
    print(f"  {'piece'.ljust(width)}  " + "".join(k[:5].rjust(7) for k in classify.ORDER))
    for piece in sorted(marker.pieces, key=lambda p: p.name):
        tally = {k: 0 for k in classify.ORDER}
        for s in piece.strokes:
            tally[s.kind] += 1
        tally[classify.LABEL] = len(piece.labels)
        print(f"  {piece.name.ljust(width)}  "
              + "".join(str(tally[k]).rjust(7) for k in classify.ORDER))
    totals = marker.counts()
    print(f"  {'TOTAL'.ljust(width)}  "
          + "".join(str(totals[k]).rjust(7) for k in classify.ORDER))


def _report(marker, strokes, labels, extent, shift, pens, args, retitled=()):
    counts = marker.counts()
    pts = sum(len(s.points) for s in strokes)
    out = sys.stderr
    print(f"read   {marker.path}", file=out)
    print(f"       {len(marker.pieces)} pieces, {marker.curves} curves, "
          f"{marker.lines} lines -> {pts:,} points at {args.tolerance} mm", file=out)
    if marker.fills_dropped:
        print(f"       {marker.fills_dropped} fabric-texture fills dropped "
              "(not plottable)", file=out)
    print("       " + ", ".join(
        f"{k}={counts[k]}" for k in classify.ORDER if counts[k]), file=out)

    w, h = extent[2] - extent[0], extent[3] - extent[1]
    print(f"output {w:.1f} x {h:.1f} mm  (page {marker.page_w:.1f} x "
          f"{marker.page_h:.1f} mm)", file=out)
    if args.scale != 1.0:
        print(f"       scaled by {args.scale:g} -- output is deliberately NOT "
              "true size", file=out)

    overruns = (
        marker.bbox
        and (marker.bbox[0] < -0.01 or marker.bbox[1] < -0.01
             or marker.bbox[2] > marker.page_w + 0.01
             or marker.bbox[3] > marker.page_h + 0.01)
    )
    if overruns:
        b = marker.bbox
        detail = (f"geometry spans x {b[0]:.1f}..{b[2]:.1f}, y {b[1]:.1f}..{b[3]:.1f} mm "
                  f"on a {marker.page_w:.1f} x {marker.page_h:.1f} mm page")
        if args.origin == "fit":
            print(f"note   {detail};", file=out)
            print(f"       shifted by ({shift[0]:.1f}, {shift[1]:.1f}) mm so nothing "
                  "is clipped (--origin page keeps CLO coordinates)", file=out)
        else:
            print(f"WARN   {detail};", file=out)
            print("       --origin page keeps these coordinates, so the plotter will "
                  "clip what falls outside. Use --origin fit to keep it all.", file=out)

    if marker.unknown_colors:
        print("WARN   unrecognised stroke colours, sent to the catch-all pen "
              f"{pens[classify.UNKNOWN]}:", file=out)
        for rgb, n in sorted(marker.unknown_colors.items(), key=lambda x: -x[1]):
            print(f"       rgb{rgb}  x{n}", file=out)

    if retitled:
        print(f"note   {len(retitled)} label(s) folded to ASCII for plotter text "
              "(--text=outline keeps the exact spelling):", file=out)
        for before, after in retitled:
            print(f"       {before!r} -> {after!r}", file=out)

    if args.output:
        print(f"wrote  {args.output}", file=out)
    if args.svg:
        print(f"wrote  {args.svg}", file=out)


def _fail(message):
    print(f"clo2plt: error: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
