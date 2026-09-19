"""Map CLO 3D stroke colours to pattern line types.

CLO encodes the meaning of every line in its stroke RGB; these constants were
measured from CLO 3D 2026.1.224 exports. Matching is within an epsilon because
the values arrive as rounded decimal text.
"""

import json

CUT = "cut"
SEAM = "seam"
NOTCH = "notch"
GRAIN = "grain"
INTERNAL = "internal"
LABEL = "label"
UNKNOWN = "unknown"

# (r, g, b) -> line type, as written by CLO 3D 2026.1.224.
CLO_COLORS = {
    (0.0, 0.0, 0.0): CUT,
    (0.572549, 0.0, 0.592157): SEAM,
    (1.0, 0.0, 0.0): NOTCH,
    (0.2, 0.2, 0.2): NOTCH,
    (0.784314, 0.784314, 0.784314): GRAIN,
    (0.54902, 0.2, 0.2): INTERNAL,
}

# Viewers and RIP previews colour lines by pen number using the standard
# HP-GL/2 palette, where pen 4 is yellow and pen 7 cyan -- both near-invisible
# on white paper. Every line type is therefore assigned to a dark slot
# (1 black, 2 red, 3 green, 5 blue, 6 magenta) and pens 4 and 7 are left
# unused. On a single-ink plotter this costs nothing: pen numbers only ever
# affect what a preview looks like.
DEFAULT_PENS = {CUT: 1, SEAM: 2, NOTCH: 3, GRAIN: 5, INTERNAL: 6,
                LABEL: 1, UNKNOWN: 3}

# What the standard palette shows each pen as, for documentation and previews.
PEN_APPEARANCE = {1: "black", 2: "red", 3: "green", 4: "yellow",
                  5: "blue", 6: "magenta", 7: "cyan"}

# Explicit RGB for --viewer-colors, chosen to stay legible on white.
PEN_RGB = {1: (0, 0, 0), 2: (200, 0, 0), 3: (0, 130, 0),
           5: (0, 60, 200), 6: (160, 0, 160)}

# Used for the SVG proof only; the plotter decides real pen colours.
PROOF_COLORS = {
    CUT: "#000000",
    SEAM: "#8e1a93",
    NOTCH: "#d10000",
    GRAIN: "#4b5563",
    INTERNAL: "#9a2f2f",
    LABEL: "#0050a8",
    UNKNOWN: "#047857",
}

ORDER = [CUT, SEAM, NOTCH, GRAIN, INTERNAL, LABEL, UNKNOWN]

_EPS = 0.01


def line_type(rgb):
    """Classify a stroke colour, returning UNKNOWN rather than discarding it."""
    for ref, kind in CLO_COLORS.items():
        if all(abs(a - b) <= _EPS for a, b in zip(rgb, ref)):
            return kind
    return UNKNOWN


def load_pens(path=None):
    """Pen map, optionally overridden by a JSON file of {line_type: pen}.

    Keys beginning with "_" are ignored, so a pen map can carry its own notes.
    """
    pens = dict(DEFAULT_PENS)
    if path:
        with open(path) as fh:
            override = json.load(fh)
        if not isinstance(override, dict):
            raise ValueError("pen map must be a JSON object of {line_type: pen}")
        override = {k: v for k, v in override.items() if not k.startswith("_")}
        unknown_keys = set(override) - set(DEFAULT_PENS)
        if unknown_keys:
            raise ValueError(
                f"unknown line types in pen map: {', '.join(sorted(unknown_keys))}. "
                f"Valid: {', '.join(ORDER)}"
            )
        try:
            pens.update({k: int(v) for k, v in override.items()})
        except (TypeError, ValueError):
            raise ValueError("pen numbers must be integers")
    return pens
