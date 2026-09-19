"""Verification against the two reference CLO 3D exports.

The expected numbers are measured from the source PDFs, so a change here means
the parser drifted, not that the fixtures moved.
"""

import math
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clo2plt import classify, document, hpgl, hpglread, layout  # noqa: E402
from clo2plt import geometry as g  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")
DESPIECE = os.path.join(SAMPLES, "despiece.pdf")
RIB = os.path.join(SAMPLES, "rib.pdf")


def parse_plt(text):
    """Read HP-GL back via the shipped reader: {pen: [polyline, ...]}, all."""
    drawing = hpglread.parse(text)
    pens = {}
    for poly in drawing.polylines:
        pens.setdefault(poly.pen, []).append(poly.points)
    return pens, [p.points for p in drawing.polylines]


@unittest.skipUnless(os.path.exists(DESPIECE), "samples/despiece.pdf not present")
class Despiece(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = document.read(DESPIECE)

    def test_page_is_a_1560mm_marker(self):
        self.assertAlmostEqual(self.m.page_w, 1560.0, places=1)
        self.assertAlmostEqual(self.m.page_h, 3163.1, places=1)

    def test_all_42_pieces_found_and_named(self):
        self.assertEqual(len(self.m.pieces), 42)
        names = {p.name for p in self.m.pieces}
        for expected in ("pretina pantalon", "espalda", "capota", "manga delantera"):
            self.assertIn(expected, names)

    def test_element_counts_match_source(self):
        self.assertEqual(
            self.m.counts(),
            {"cut": 42, "seam": 42, "notch": 576, "grain": 42,
             "internal": 21, "label": 42, "unknown": 0},
        )

    def test_every_colour_is_recognised(self):
        self.assertEqual(self.m.unknown_colors, {})

    def test_fabric_fills_are_dropped(self):
        self.assertEqual(self.m.fills_dropped, 42)

    def test_curve_and_line_totals(self):
        self.assertEqual(self.m.curves, 10902)
        self.assertEqual(self.m.lines, 1652)

    def test_waistband_keeps_its_real_dimensions(self):
        piece = next(p for p in self.m.pieces if p.name == "pretina pantalon")
        cut = g.bbox([s.points for s in piece.strokes if s.kind == "cut"])
        seam = g.bbox([s.points for s in piece.strokes if s.kind == "seam"])
        self.assertAlmostEqual(cut[2] - cut[0], 996.60, places=1)
        self.assertAlmostEqual(cut[3] - cut[1], 100.00, places=2)
        # Seam allowance is a uniform 10 mm on all four sides.
        for gap in (seam[0] - cut[0], cut[2] - seam[2],
                    seam[1] - cut[1], cut[3] - seam[3]):
            self.assertAlmostEqual(gap, 10.0, places=3)

    def test_notches_are_7mm(self):
        for s in (s for s in self.m.strokes if s.kind == "notch"):
            length = math.dist(s.points[0], s.points[-1])
            self.assertGreater(length, 6.9)
            self.assertLess(length, 7.6)

    def test_labels_decode_with_geometry(self):
        self.assertEqual(len(self.m.labels), 42)
        for l in self.m.labels:
            self.assertTrue(l.text)
            self.assertEqual(l.text, l.piece)
            self.assertTrue(-180.0 <= l.angle <= 180.0)
        # CLO shrinks the label to fit narrow pieces, so sizes vary by design;
        # preserving that per-piece sizing is the point.
        sizes = sorted({round(l.size, 2) for l in self.m.labels})
        self.assertEqual(sizes, [6.0, 7.0, 11.0])
        self.assertEqual(sum(1 for l in self.m.labels if round(l.size, 2) == 11.0), 38)

    def test_tighter_tolerance_adds_points_and_keeps_bbox(self):
        coarse = document.read(DESPIECE, tolerance=0.5)
        fine = document.read(DESPIECE, tolerance=0.005)
        n_coarse = sum(len(s.points) for s in coarse.strokes)
        n_fine = sum(len(s.points) for s in fine.strokes)
        self.assertGreater(n_fine, n_coarse)
        for a, b in zip(coarse.bbox, fine.bbox):
            self.assertAlmostEqual(a, b, places=0)


@unittest.skipUnless(os.path.exists(RIB), "samples/rib.pdf not present")
class Rib(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = document.read(RIB)

    def test_three_rib_pieces(self):
        self.assertEqual(len(self.m.pieces), 3)
        self.assertEqual(
            {p.name for p in self.m.pieces},
            {"rib cintura", "rib puños", "rib puños_1"},
        )

    def test_rib_has_no_curves(self):
        self.assertEqual(self.m.curves, 0)

    def test_counts(self):
        self.assertEqual(
            self.m.counts(),
            {"cut": 3, "seam": 3, "notch": 20, "grain": 3,
             "internal": 3, "label": 3, "unknown": 0},
        )


@unittest.skipUnless(os.path.exists(DESPIECE), "samples/despiece.pdf not present")
class RoundTrip(unittest.TestCase):
    """Re-read the emitted HP-GL and compare it to the source geometry."""

    @classmethod
    def setUpClass(cls):
        cls.m = document.read(DESPIECE)
        cls.strokes, cls.labels, cls.extent, _ = layout.place(cls.m, 0, "fit")
        pens = classify.load_pens()
        cls.text, _ = hpgl.emit(cls.strokes, cls.labels, pens)
        cls.pens, cls.polys = parse_plt(cls.text)

    def test_every_stroke_survives(self):
        self.assertEqual(len(self.polys), len(self.strokes))

    def test_bbox_matches_within_one_plotter_unit(self):
        emitted = g.bbox(self.polys)
        for a, b in zip(emitted, self.extent):
            self.assertAlmostEqual(a, b, delta=1.0 / hpgl.UNITS_PER_MM)

    def test_pens_carry_the_line_types(self):
        # cut=1 seam=2 notch=3 grain=4 internal=5 label=6
        self.assertEqual(len(self.pens[1]), 42)
        self.assertEqual(len(self.pens[2]), 42)
        self.assertEqual(len(self.pens[3]), 576)
        self.assertEqual(len(self.pens[4]), 42)
        self.assertEqual(len(self.pens[5]), 21)

    def test_waistband_dimensions_survive_to_hpgl(self):
        widest = max(self.pens[1], key=lambda p: g.bbox([p])[2] - g.bbox([p])[0])
        box = g.bbox([widest])
        self.assertAlmostEqual(box[2] - box[0], 996.60, places=1)

    def test_all_42_labels_emitted(self):
        self.assertEqual(self.text.count("LB"), 42)

    def test_output_is_pure_ascii(self):
        self.text.encode("ascii")

    def test_no_line_exceeds_the_controller_limit(self):
        # Measured as written to disk (CRLF), against a 255-byte input buffer.
        for line in self.text.splitlines():
            self.assertLessEqual(len(line) + 2, 255)

    def test_document_is_framed_correctly(self):
        self.assertTrue(self.text.startswith("IN;"))
        self.assertTrue(self.text.rstrip().endswith("IN;"))
        self.assertIn("SP0;", self.text)


@unittest.skipUnless(os.path.exists(DESPIECE), "samples/despiece.pdf not present")
class HpglReader(unittest.TestCase):
    """The reader behind pltview, checked against the file it just wrote."""

    @classmethod
    def setUpClass(cls):
        m = document.read(DESPIECE)
        strokes, labels, cls.extent, _ = layout.place(m, 0, "fit")
        text, _ = hpgl.emit(strokes, labels, classify.load_pens())
        cls.drawing = hpglread.parse(text)

    def test_reads_back_every_pen(self):
        self.assertEqual(sorted(self.drawing.pens), [1, 2, 3, 4, 5, 6])

    def test_reads_back_the_extent(self):
        for a, b in zip(self.drawing.bbox, self.extent):
            self.assertAlmostEqual(a, b, delta=1.0 / hpgl.UNITS_PER_MM)

    def test_reads_back_all_labels(self):
        self.assertEqual(len(self.drawing.texts), 42)
        self.assertIn("pretina pantalon", [t.text for t in self.drawing.texts])

    def test_label_rotation_survives(self):
        angles = {round(t.angle) for t in self.drawing.texts}
        self.assertIn(-90, angles)
        self.assertIn(90, angles)

    def test_nothing_unsupported_in_our_own_output(self):
        self.assertEqual(self.drawing.unsupported, {})

    def test_relative_mode_is_honoured(self):
        d = hpglread.parse("IN;SP1;PA0,0;PD400,0;PR;PD0,400;PD-400,0;")
        self.assertEqual(len(d.polylines), 1)
        self.assertEqual(
            [(round(x, 3), round(y, 3)) for x, y in d.polylines[0].points],
            [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        )

    def test_unknown_instructions_are_surfaced(self):
        d = hpglread.parse("IN;SP1;PU0,0;CI500;PD400,400;ZZ1;")
        self.assertIn("CI", d.unsupported)
        self.assertIn("ZZ", d.unsupported)


@unittest.skipUnless(os.path.exists(RIB), "samples/rib.pdf not present")
class Outlines(unittest.TestCase):
    """--text=outline, which needs fontTools. Skipped when it is absent."""

    @classmethod
    def setUpClass(cls):
        from clo2plt import glyphs

        if not glyphs.available():
            raise unittest.SkipTest("fontTools not installed")
        cls.glyphs = glyphs
        cls.m = document.read(RIB)

    def test_every_glyph_resolves(self):
        from clo2plt.pdfread import load

        strokes, missing = self.glyphs.outline_labels(load(RIB), self.m.labels)
        self.assertEqual(missing, [])
        self.assertTrue(strokes)

    def test_accented_names_survive_as_geometry(self):
        """LB folds 'puños' to ASCII; outlines must keep the real glyph."""
        from clo2plt.pdfread import load

        strokes, _ = self.glyphs.outline_labels(load(RIB), self.m.labels)
        punos = [s for s in strokes if s.piece == "rib puños"]
        plain = [s for s in strokes if s.piece == "rib cintura"]
        # The tilde is its own contour, so the accented name carries more of
        # them per character than the unaccented one.
        self.assertGreater(len(punos) / len("rib puños"),
                           len(plain) / len("rib cintura"))

    def test_outlines_land_on_the_label_pen(self):
        from clo2plt.pdfread import load

        strokes, _ = self.glyphs.outline_labels(load(RIB), self.m.labels)
        self.assertTrue(all(s.kind == "label" for s in strokes))


class Calibration(unittest.TestCase):
    """The calibration target is only useful if its dimensions are exact."""

    @classmethod
    def setUpClass(cls):
        import caltest

        strokes, labels = caltest.build(200.0)
        text, _ = hpgl.emit(strokes, labels, classify.load_pens())
        cls.drawing = hpglread.parse(text)
        cls.by_pen = {}
        for poly in cls.drawing.polylines:
            cls.by_pen.setdefault(poly.pen, []).append(poly.points)

    def test_outer_square_is_exactly_200mm(self):
        box = g.bbox(self.by_pen[1])
        self.assertAlmostEqual(box[2] - box[0], 200.0, places=4)
        self.assertAlmostEqual(box[3] - box[1], 200.0, places=4)

    def test_inner_square_is_exactly_100mm(self):
        box = g.bbox(self.by_pen[2])
        self.assertAlmostEqual(box[2] - box[0], 100.0, places=4)
        self.assertAlmostEqual(box[3] - box[1], 100.0, places=4)

    def test_bar_is_exactly_100mm(self):
        box = g.bbox(self.by_pen[5])
        self.assertAlmostEqual(box[2] - box[0], 100.0, places=4)

    def test_ticks_are_10mm_and_every_50mm(self):
        ticks = self.by_pen[3]
        self.assertEqual(len(ticks), 10)
        for pts in ticks:
            self.assertAlmostEqual(math.dist(pts[0], pts[-1]), 10.0, places=4)

    def test_diagonals_cross_at_the_centre(self):
        a, b = self.by_pen[4]
        mid_a = ((a[0][0] + a[-1][0]) / 2, (a[0][1] + a[-1][1]) / 2)
        mid_b = ((b[0][0] + b[-1][0]) / 2, (b[0][1] + b[-1][1]) / 2)
        self.assertAlmostEqual(mid_a[0], mid_b[0], places=4)
        self.assertAlmostEqual(mid_a[1], mid_b[1], places=4)

    def test_every_pen_is_exercised(self):
        self.assertEqual(sorted(self.drawing.pens), [1, 2, 3, 4, 5, 6])

    def test_labels_state_the_true_sizes(self):
        texts = " ".join(t.text for t in self.drawing.texts)
        self.assertIn("200 mm", texts)
        self.assertIn("100 mm", texts)

    def test_label_height_is_inside_the_bbox(self):
        """A label at the top edge must not be clipped by the preview box."""
        top_label = max(self.drawing.texts, key=lambda t: t.origin[1])
        self.assertGreater(self.drawing.bbox[3], top_label.origin[1])


@unittest.skipUnless(os.path.exists(DESPIECE), "samples/despiece.pdf not present")
class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "clo2plt.py"), *args],
            capture_output=True, text=True, cwd=ROOT,
        )

    def test_list_reports_every_piece(self):
        r = self.run_cli(DESPIECE, "--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pretina pantalon", r.stdout)
        self.assertIn("TOTAL", r.stdout)

    def test_single_piece_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "one.plt")
            r = self.run_cli(DESPIECE, "-o", out, "--pieces", "pretina pantalon")
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out) as fh:
                _, polys = parse_plt(fh.read())
            box = g.bbox(polys)
            self.assertAlmostEqual(box[2] - box[0], 996.60, places=1)

    def test_unknown_piece_is_an_error(self):
        r = self.run_cli(DESPIECE, "-o", os.devnull, "--pieces", "no such piece")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such piece", r.stderr)

    def test_scale_multiplies_geometry_and_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = os.path.join(tmp, "full.plt")
            half = os.path.join(tmp, "half.plt")
            self.run_cli(RIB, "-o", full, "-q")
            self.run_cli(RIB, "-o", half, "--scale", "0.5", "-q")
            with open(full) as fh:
                a = hpglread.parse(fh.read())
            with open(half) as fh:
                b = hpglread.parse(fh.read())
            ba, bb = a.bbox, b.bbox
            self.assertAlmostEqual((bb[2] - bb[0]) * 2, ba[2] - ba[0], places=1)
            self.assertAlmostEqual((bb[3] - bb[1]) * 2, ba[3] - ba[1], places=1)
            self.assertAlmostEqual(b.texts[0].size * 2, a.texts[0].size, places=2)

    def test_bad_scale_is_an_error(self):
        r = self.run_cli(RIB, "-o", os.devnull, "--scale", "0")
        self.assertEqual(r.returncode, 2)

    def test_rotation_swaps_extent(self):
        with tempfile.TemporaryDirectory() as tmp:
            flat = os.path.join(tmp, "a.plt")
            turned = os.path.join(tmp, "b.plt")
            self.run_cli(DESPIECE, "-o", flat, "-q")
            self.run_cli(DESPIECE, "-o", turned, "--rotate", "90", "-q")
            with open(flat) as fh:
                a = g.bbox(parse_plt(fh.read())[1])
            with open(turned) as fh:
                b = g.bbox(parse_plt(fh.read())[1])
            self.assertAlmostEqual(a[2] - a[0], b[3] - b[1], places=1)
            self.assertAlmostEqual(a[3] - a[1], b[2] - b[0], places=1)

    def test_no_output_target_is_an_error(self):
        r = self.run_cli(DESPIECE)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
