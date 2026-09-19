# clo2plt

Convert CLO 3D marker PDFs to HP-GL (`.plt`) for plotting and cutting, keeping
every line type CLO exports.

CLO encodes the meaning of each line in its stroke colour and wraps every
pattern piece in its own named layer. Generic PDF→PLT converters throw that
away — they rasterize, flatten everything onto one pen, or choke on a page
measured in metres. This reads the structure directly and puts each line type
on its own pen.

| Line type | Pen | Source |
|---|---|---|
| Cut line | 1 | black stroke, one per piece |
| Seam line | 2 | purple stroke, one per piece |
| Notches | 3 | red / dark-grey ticks |
| Grain line | 4 | light-grey arrow |
| Internal / fold | 5 | dark-red stroke |
| Piece label | 6 | text, `LB` or vector outlines |

Fabric-texture fills are dropped — they carry no plotter meaning. The count of
dropped fills is reported so you can see it happened.

## Two ways to run it

**Web page** (`site/`) — drag PDFs in, preview, download. Runs entirely in the
browser; nothing is uploaded. Deployable to GitHub Pages as-is.

```bash
python3 -m http.server 8765 --directory site
```

**Command line** (`clo2plt.py`) — scriptable, batchable, the reference
implementation.

The two are verified to emit **byte-identical** HP-GL across rotation, scaling,
tolerance and piece-filter settings (`tests/test_parity.py`). Change one, change
the other.

## Requirements

Python 3.9+. Nothing else for normal use — the PDF reader is pure standard
library. `--text=outline` additionally needs `fonttools`.

## Usage

```bash
python3 clo2plt.py marker.pdf -o marker.plt --svg proof.html
```

Inspect before converting:

```bash
python3 clo2plt.py marker.pdf --list
```

Test one piece on the plotter before committing metres of paper:

```bash
python3 clo2plt.py marker.pdf -o test.plt --pieces "pretina pantalon"
```

### Options

| Flag | Default | Notes |
|---|---|---|
| `-o, --output` | — | HP-GL output path |
| `--svg FILE` | — | proof sheet; line types toggle on/off |
| `--list` | — | pieces and element counts, converts nothing |
| `--tolerance MM` | `0.05` | Bézier flattening; smaller = more points |
| `--text` | `label` | `label` (plotter text), `outline` (vectors), `none` |
| `--pieces` | all | comma-separated piece names |
| `--pens FILE` | built-in | JSON pen map, see `profiles/` |
| `--rotate` | `0` | `90`/`180`/`270` to match the roll direction |
| `--origin` | `fit` | `fit` shifts to the geometry bbox; `page` keeps CLO coordinates |
| `--page-advance` | off | append `PG;` |
| `--comment` | off | HP-GL/2 `CO` provenance comments |

## Before the first job: check the scale

```bash
python3 caltest.py -o calibration.plt
```

Writes a small target — a 200 mm outer square, a 100 mm inner square, a 100 mm
bar, ticks every 50 mm, and diagonals that must cross dead centre. Print it and
measure the outer square with a tape.

If it does not read exactly 200 mm, something in the chain is rescaling, and a
full marker would be wrong by that same factor. That is the one failure worth
catching before it reaches fabric — paper is cheap.

It also puts one shape on each of the six pens, so you can see whether your
setup distinguishes pens at all. On a single-ink inkjet marker plotter it will
not: every pen prints the same colour. That is expected, and pen assignment
still lets you drop line types you do not want (see **Pen maps**).

## Sending files to someone else's plotter

```bash
python3 handover.py out/*.plt -o "READ ME - plotter spec.txt"
```

Writes a plain-text spec sheet to send alongside the files: format, units,
scale, per-file dimensions, what each pen means, and the paper width required.
It reads the actual files rather than restating defaults, and it works out
whether the job can be rotated at all — for a marker several metres long it
usually cannot, and saying so stops an operator from rotating it to fit.

Worth including when you do not operate the machine yourself and cannot
iterate on a failed print.

## Viewing a .plt

`pltview.py` opens the plotter file itself, so you are inspecting the bytes the
plotter will read rather than a re-derivation from the PDF. It works on any
HP-GL, not only output from this tool.

```bash
python3 pltview.py marker.plt                 # writes marker.plt.html
python3 pltview.py marker.plt -o view.html
python3 pltview.py marker.plt --report        # numbers only, writes nothing
```

Open the HTML in any browser. Each pen has a checkbox, so you can confirm one
layer at a time — notches alone, or cut lines alone. When the pen numbers match
the default map, the legend names them (`pen 3 · notch`) instead of just
numbering them.

```
read   marker.plt
       1560.0 x 3203.1 mm, origin at (0.0, 0.0)
       723 polylines, 12,779 points, 42 labels
       pen 1 (cut): 42 lines
       pen 2 (seam): 42 lines
       pen 3 (notch): 576 lines
       pen 4 (grain): 42 lines
       pen 5 (internal): 21 lines
       pen 6 (label): 0 lines, 42 labels
```

Other ways to view a `.plt`: **Inkscape** imports HP-GL directly
(File → Import), and most plotter RIP software previews before sending. Both
are useful cross-checks — if Inkscape and `pltview` agree, the file is sound.

## Checking the output before you plot

`--svg proof.html` renders the *converted* geometry — post-flattening,
post-pen-mapping — before it is written out. Together with `pltview.py` that
gives you both ends: what the converter produced, and what the file contains.
Each line type has a checkbox, so you can confirm notches or grain lines in
isolation.

The conversion report goes to stderr and names anything that needs a decision:

```
read   marker.pdf
       42 pieces, 10902 curves, 1652 lines -> 12,779 points at 0.05 mm
       42 fabric-texture fills dropped (not plottable)
       cut=42, seam=42, notch=576, grain=42, internal=21, label=42
output 1560.0 x 3203.1 mm  (page 1560.0 x 3163.1 mm)
note   geometry spans x 0.0..1560.0, y -40.0..3163.1 mm on a 1560.0 x 3163.1 mm page;
       shifted by (-0.0, 40.0) mm so nothing is clipped
```

### Geometry outside the page

CLO draws grain-line arrows past the edge of the piece, and sometimes past the
edge of the page. `--origin fit` (the default) shifts everything so nothing is
lost; the shift is along the roll, so piece positions relative to each other
and to the fabric width are unchanged. `--origin page` keeps CLO's coordinates
and lets the plotter clip, and warns when that would discard something.

### Labels

Default `--text=label` emits HP-GL `LB` text using the plotter's built-in font,
sized and rotated to match CLO. Plain HP-GL only guarantees ASCII, so accented
characters are folded (`puños` → `punos`) and every fold is reported.

`--text=outline` vectorises the embedded font instead, so labels match CLO
exactly, accents included. It needs fonttools:

```bash
python3 -m venv .venv && .venv/bin/pip install fonttools
.venv/bin/python clo2plt.py marker.pdf -o marker.plt --text=outline
```

### Pen maps

```bash
python3 clo2plt.py marker.pdf -o marker.plt --pens profiles/cut-only.json
```

A JSON object of `{line_type: pen}`. Line types are fixed (`cut`, `seam`,
`notch`, `grain`, `internal`, `label`, `unknown`); pen numbers are yours, and
several types may share one. Keys starting with `_` are treated as comments.

## Output format

Generic HP-GL — `IN` / `PA` / `SP` / `PU` / `PD` / `LB` — in plotter units of
1/40 mm, absolute, origin bottom-left. No HP-GL/2-only instructions, so it
should be accepted by essentially any garment plotter. Strokes are grouped by
pen to minimise tool changes, and command lines are capped at 240 characters
for older serial controllers.

## Unrecognised colours

A future CLO release could introduce a line type this tool doesn't know. Those
strokes go to the catch-all pen (7 by default) and are reported with their RGB
values rather than silently dropped. If you see that warning, add the colour to
`CLO_COLORS` in `clo2plt/classify.py`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_parity.py` additionally runs the JavaScript build under node and
diffs its output against the Python byte for byte. It skips if node is absent.

The suite checks the two reference exports in `samples/` against numbers
measured from the source PDFs: piece and element counts, the waistband's real
996.60 × 100.00 mm size with its uniform 10 mm seam allowance, 7 mm notches,
and a round-trip that re-reads the emitted HP-GL with `pltview`'s parser and
compares its bounding box to the source.

Outline-mode tests skip automatically when fonttools is absent.
