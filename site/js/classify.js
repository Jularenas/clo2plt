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

export const DEFAULT_PENS = {
  [CUT]: 1, [SEAM]: 2, [NOTCH]: 3, [GRAIN]: 4,
  [INTERNAL]: 5, [LABEL]: 6, [UNKNOWN]: 7,
};

export const PROOF_COLORS = {
  [CUT]: "#000000", [SEAM]: "#922097", [NOTCH]: "#e00000",
  [GRAIN]: "#8c8c8c", [INTERNAL]: "#8c3333", [LABEL]: "#0057b8",
  [UNKNOWN]: "#00a000",
};

export const ORDER = [CUT, SEAM, NOTCH, GRAIN, INTERNAL, LABEL, UNKNOWN];

const EPS = 0.01;

export function lineType(rgb) {
  for (const [ref, kind] of CLO_COLORS) {
    if (ref.every((v, i) => Math.abs(v - rgb[i]) <= EPS)) return kind;
  }
  return UNKNOWN;
}
