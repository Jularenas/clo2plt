// Stroke colour -> pattern line type. Mirrors clo2plt/classify.py.

export const CUT = "cut";
export const SEAM = "seam";
export const NOTCH = "notch";
export const GRAIN = "grain";
export const INTERNAL = "internal";
export const LABEL = "label";
export const UNKNOWN = "unknown";

// Measured from CLO 3D 2026.1.224 exports.
const CLO_COLORS = [
  [[0.0, 0.0, 0.0], CUT],
  [[0.572549, 0.0, 0.592157], SEAM],
  [[1.0, 0.0, 0.0], NOTCH],
  [[0.2, 0.2, 0.2], NOTCH],
  [[0.784314, 0.784314, 0.784314], GRAIN],
  [[0.54902, 0.2, 0.2], INTERNAL],
];

// Viewers colour lines by pen number using the standard HP-GL/2 palette,
// where pen 4 is yellow and pen 7 cyan -- both near-invisible on white. Every
// line type sits on a dark slot (1 black, 2 red, 3 green, 5 blue, 6 magenta);
// pens 4 and 7 are left unused. On a single-ink plotter this costs nothing.
export const DEFAULT_PENS = {
  [CUT]: 1, [SEAM]: 2, [NOTCH]: 3, [GRAIN]: 5,
  [INTERNAL]: 6, [LABEL]: 1, [UNKNOWN]: 3,
};

export const PEN_APPEARANCE = {
  1: "black", 2: "red", 3: "green", 4: "yellow",
  5: "blue", 6: "magenta", 7: "cyan",
};

export const PEN_RGB = {
  1: [0, 0, 0], 2: [200, 0, 0], 3: [0, 130, 0],
  5: [0, 60, 200], 6: [160, 0, 160],
};

export const PROOF_COLORS = {
  [CUT]: "#000000", [SEAM]: "#8e1a93", [NOTCH]: "#d10000",
  [GRAIN]: "#4b5563", [INTERNAL]: "#9a2f2f", [LABEL]: "#0050a8",
  [UNKNOWN]: "#047857",
};

export const ORDER = [CUT, SEAM, NOTCH, GRAIN, INTERNAL, LABEL, UNKNOWN];

const EPS = 0.01;

export function lineType(rgb) {
  for (const [ref, kind] of CLO_COLORS) {
    if (ref.every((v, i) => Math.abs(v - rgb[i]) <= EPS)) return kind;
  }
  return UNKNOWN;
}
