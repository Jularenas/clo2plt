"""SVG proof sheet.

Drawn from the same flattened, placed, pen-mapped geometry the HP-GL emitter
consumes, so what you see here is what the plotter receives -- not a re-render
of the source PDF. Line types can be toggled to check each one in isolation
before committing metres of paper.
"""

import html

from . import classify

# Stroke widths in screen pixels, paired with vector-effect:non-scaling-stroke
# below. Widths in millimetres go sub-pixel once a 3-metre marker is scaled to
# fit a screen, which washes the lines out; these stay legible at any zoom.
_WIDTHS = {
    classify.LABEL: 0.9,
    classify.CUT: 1.7,
    classify.SEAM: 1.2,
    classify.NOTCH: 1.5,
    classify.GRAIN: 1.2,
    classify.INTERNAL: 1.2,
    classify.UNKNOWN: 2.0,
}

_CSS = """
:root{color-scheme:light dark}
body{margin:0;font:13px/1.5 system-ui,-apple-system,sans-serif;
     background:#f4f4f5;color:#18181b}
@media (prefers-color-scheme:dark){body{background:#18181b;color:#f4f4f5}}
header{position:sticky;top:0;z-index:2;padding:.6rem 1rem;
       background:inherit;border-bottom:1px solid #8886;
       display:flex;gap:.5rem 1rem;align-items:center;flex-wrap:wrap}
h1{font-size:14px;margin:0;font-weight:600}
.meta{opacity:.7;font-size:12px}
label{display:inline-flex;align-items:center;gap:.3rem;cursor:pointer;
      font-size:12px;white-space:nowrap}
.sw{width:11px;height:11px;border-radius:2px;display:inline-block}
.wrap{padding:1rem}
svg{background:#fff;width:100%;height:auto;
    box-shadow:0 1px 6px #0003;display:block}
.page{fill:none;stroke:#94a3b8;stroke-width:1.5;stroke-dasharray:9 7;
      vector-effect:non-scaling-stroke}
svg [data-kind]{vector-effect:non-scaling-stroke}
"""

_JS = """
document.querySelectorAll('input[data-kind]').forEach(function(box){
  box.addEventListener('change',function(){
    document.querySelectorAll('[data-kind="'+box.dataset.kind+'"]')
      .forEach(function(g){ g.style.display = box.checked ? '' : 'none'; });
  });
});
"""


# Pen colours for previewing a .plt, where only pen numbers survive. Ordered to
# match clo2plt's default map so a file it produced reads at a glance.
PEN_COLORS = {
    1: "#000000", 2: "#8e1a93", 3: "#d10000", 4: "#4b5563",
    5: "#9a2f2f", 6: "#0050a8", 7: "#047857", 8: "#9a6b00",
}
PEN_WIDTHS = {1: 1.7, 2: 1.2, 3: 1.5, 4: 1.2, 5: 1.2, 6: 0.9}


def _shell(title, meta, legend, body, w, h, pad):
    """The common page wrapper for both the PDF proof and the .plt preview."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>
<header><h1>{html.escape(title)}</h1>
<span class="meta">{meta}</span>{"".join(legend)}</header>
<div class="wrap">
<svg xmlns="http://www.w3.org/2000/svg"
     viewBox="0 0 {w + 2 * pad:.2f} {h + 2 * pad:.2f}"
     data-mm-width="{w + 2 * pad:.1f}" data-mm-height="{h + 2 * pad:.1f}"
     preserveAspectRatio="xMidYMid meet">
{chr(10).join(body)}
</svg></div><script>{_JS}</script></body></html>
"""


def emit_drawing(drawing, title="plt preview", pen_names=None):
    """Render a parsed HP-GL Drawing -- the file as the plotter will read it."""
    box = drawing.bbox or (0.0, 0.0, 1.0, 1.0)
    minx, miny, maxx, maxy = box
    w = max(maxx - minx, 1.0)
    h = max(maxy - miny, 1.0)
    pad = max(w, h) * 0.01
    names = pen_names or {}

    def pt(x, y):
        return f"{x - minx + pad:.3f},{maxy - y + pad:.3f}"

    by_pen = {}
    for poly in drawing.polylines:
        by_pen.setdefault(poly.pen, []).append(poly)
    for t in drawing.texts:
        by_pen.setdefault(t.pen, [])

    body = []
    for pen in sorted(by_pen):
        colour = PEN_COLORS.get(pen, "#555555")
        body.append(
            f'<g data-kind="pen{pen}" fill="none" stroke="{colour}"'
            f' stroke-width="{PEN_WIDTHS.get(pen, 1.2)}"'
            ' vector-effect="non-scaling-stroke"'
            ' stroke-linecap="round" stroke-linejoin="round">'
        )
        for poly in by_pen[pen]:
            body.append(
                f'<polyline points="{" ".join(pt(x, y) for x, y in poly.points)}"/>'
            )
        for t in (t for t in drawing.texts if t.pen == pen):
            sx, sy = (t.origin[0] - minx + pad), (maxy - t.origin[1] + pad)
            body.append(
                f'<text x="0" y="0" fill="{colour}" stroke="none"'
                f' font-size="{t.size:.2f}" font-family="system-ui,sans-serif"'
                f' transform="translate({sx:.3f},{sy:.3f}) rotate({-t.angle:.3f})">'
                f"{html.escape(t.text)}</text>"
            )
        body.append("</g>")

    legend = []
    for pen in sorted(by_pen):
        n = len(by_pen[pen])
        ntext = sum(1 for t in drawing.texts if t.pen == pen)
        what = f"{n} lines" + (f", {ntext} labels" if ntext else "")
        tag = f" &middot; {names[pen]}" if pen in names else ""
        legend.append(
            f'<label><input type="checkbox" data-kind="pen{pen}" checked>'
            f'<span class="sw" style="background:{PEN_COLORS.get(pen, "#555")}"></span>'
            f"pen {pen}{tag} ({what})</label>"
        )

    points = sum(len(p.points) for p in drawing.polylines)
    meta = (f"{w:.1f} &times; {h:.1f} mm &middot; {len(drawing.polylines)} polylines "
            f"&middot; {points:,} points &middot; {len(drawing.texts)} labels")
    return _shell(title, meta, legend, body, w, h, pad)


def emit(strokes, labels, extent, marker, pens, title="marker proof"):
    minx, miny, maxx, maxy = extent
    w = max(maxx - minx, 1.0)
    h = max(maxy - miny, 1.0)
    pad = max(w, h) * 0.01

    # SVG's y axis points down; flip so the proof matches plotter orientation.
    def pt(x, y):
        return f"{x - minx + pad:.3f},{maxy - y + pad:.3f}"

    groups = {}
    for s in strokes:
        groups.setdefault(s.kind, []).append(s)

    body = []
    body.append(
        f'<rect class="page" x="{pad - minx:.2f}" y="{maxy - marker.page_h + pad:.2f}"'
        f' width="{marker.page_w:.2f}" height="{marker.page_h:.2f}"/>'
    )

    for kind in classify.ORDER:
        if kind not in groups:
            continue
        colour = classify.PROOF_COLORS[kind]
        body.append(
            f'<g data-kind="{kind}" fill="none" stroke="{colour}"'
            f' stroke-width="{_WIDTHS.get(kind, 1.2)}"'
            ' vector-effect="non-scaling-stroke"'
            ' stroke-linecap="round" stroke-linejoin="round">'
        )
        for s in groups[kind]:
            pts = " ".join(pt(x, y) for x, y in s.points)
            name = html.escape(s.piece, quote=True)
            body.append(f'<polyline data-piece="{name}" points="{pts}"/>')
        body.append("</g>")

    if labels:
        colour = classify.PROOF_COLORS[classify.LABEL]
        body.append(f'<g data-kind="label" fill="{colour}" stroke="none">')
        for l in labels:
            x, y = l.origin
            sx, sy = (x - minx + pad), (maxy - y + pad)
            body.append(
                f'<text x="0" y="0" font-size="{l.size:.2f}"'
                f' font-family="system-ui,sans-serif"'
                f' transform="translate({sx:.3f},{sy:.3f}) rotate({-l.angle:.3f})">'
                f"{html.escape(l.text)}</text>"
            )
        body.append("</g>")

    legend = []
    for kind in classify.ORDER:
        n = len(groups.get(kind, []))
        if kind == classify.LABEL:
            n = n or len(labels)
        if not n:
            continue
        legend.append(
            f'<label><input type="checkbox" data-kind="{kind}" checked>'
            f'<span class="sw" style="background:{classify.PROOF_COLORS[kind]}"></span>'
            f"{kind} ({n}) &middot; pen {pens.get(kind, '-')}</label>"
        )

    meta = (
        f"{marker.page_w:.1f} &times; {marker.page_h:.1f} mm page &middot; "
        f"{w:.1f} &times; {h:.1f} mm drawn &middot; "
        f"{len(marker.pieces)} pieces &middot; "
        f"{sum(len(s.points) for s in strokes):,} points"
    )

    return _shell(title, meta, legend, body, w, h, pad)
