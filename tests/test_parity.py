#!/usr/bin/env python3
"""Verify the JavaScript port produces byte-identical HP-GL to the Python.

The Python side is the reference implementation the rest of the suite checks.
This asserts the browser build agrees with it exactly, so a user converting on
the web page gets the same plotter file as one running the CLI. A silent
divergence would mean two different pattern sizes from the same PDF.

Requires node. Skipped when node is unavailable.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SAMPLES = os.path.join(ROOT, "samples")
DESPIECE = os.path.join(SAMPLES, "despiece.pdf")
RIB = os.path.join(SAMPLES, "rib.pdf")

# (label, source pdf, rotate, scale, pieces)
CASES = [
    ("despiece", DESPIECE, 0, 1.0, None),
    ("rib", RIB, 0, 1.0, None),
    ("rot90", DESPIECE, 90, 1.0, None),
    ("rot270", RIB, 270, 1.0, None),
    ("scaled", RIB, 0, 0.5, None),
    ("counterscale", DESPIECE, 0, 0.9709, None),
    ("onepiece", DESPIECE, 0, 1.0, ["pretina pantalon"]),
    ("tight", RIB, 0, 1.0, None),
    ("viewercolors", RIB, 0, 1.0, None),
]

JS_DRIVER = r"""
import fs from 'fs';
import { read } from '%(root)s/site/js/document.js';
import { place } from '%(root)s/site/js/layout.js';
import { emit } from '%(root)s/site/js/hpgl.js';
import { DEFAULT_PENS } from '%(root)s/site/js/classify.js';
import { build } from '%(root)s/site/js/caltest.js';

const cases = JSON.parse(process.argv[2]);
for (const c of cases) {
  let strokes, labels;
  if (c.calibration) {
    ({ strokes, labels } = build(c.calibration));
  } else {
    const marker = await read(new Uint8Array(fs.readFileSync(c.src)),
                              { tolerance: c.tol, pieces: c.pieces });
    const p = place(marker, c.rotate, 'fit', c.scale);
    strokes = p.strokes;
    labels = p.labels;
  }
  const [text] = emit(strokes, labels, DEFAULT_PENS, 'label', false, null,
                      !!c.viewerColors);
  fs.writeFileSync(c.out, text.replace(/\n/g, '\r\n'), 'latin1');
}
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
@unittest.skipUnless(os.path.exists(DESPIECE), "samples not present")
class Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="clo2plt-parity-")
        cls.results = {}

        import json

        js_cases = []
        for name, src, rotate, scale, pieces in CASES:
            tol = 0.005 if name == "tight" else 0.05
            js_cases.append({
                "src": src, "out": os.path.join(cls.tmp, f"js_{name}.plt"),
                "rotate": rotate, "scale": scale, "tol": tol, "pieces": pieces,
                "viewerColors": name == "viewercolors",
            })
        js_cases.append({
            "calibration": 200, "out": os.path.join(cls.tmp, "js_cal.plt"),
        })

        driver = os.path.join(cls.tmp, "driver.mjs")
        with open(driver, "w") as fh:
            fh.write(JS_DRIVER % {"root": ROOT})
        proc = subprocess.run(
            ["node", driver, json.dumps(js_cases)],
            capture_output=True, text=True, cwd=ROOT,
        )
        if proc.returncode != 0:
            raise AssertionError(f"node driver failed:\n{proc.stderr}")

        for name, src, rotate, scale, pieces in CASES:
            tol = 0.005 if name == "tight" else 0.05
            out = os.path.join(cls.tmp, f"py_{name}.plt")
            argv = [src, "-o", out, "-q", "--rotate", str(rotate),
                    "--scale", str(scale), "--tolerance", str(tol)]
            if pieces:
                argv += ["--pieces", ",".join(pieces)]
            if name == "viewercolors":
                argv += ["--viewer-colors"]
            r = subprocess.run(
                [sys.executable, os.path.join(ROOT, "clo2plt.py"), *argv],
                capture_output=True, text=True, cwd=ROOT,
            )
            if r.returncode != 0:
                raise AssertionError(f"python CLI failed for {name}:\n{r.stderr}")
            cls.results[name] = (out, os.path.join(cls.tmp, f"js_{name}.plt"))

        cal_py = os.path.join(cls.tmp, "py_cal.plt")
        subprocess.run(
            [sys.executable, os.path.join(ROOT, "caltest.py"), "-o", cal_py],
            capture_output=True, text=True, cwd=ROOT,
        )
        cls.results["calibration"] = (cal_py, os.path.join(cls.tmp, "js_cal.plt"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _compare(self, name):
        py_path, js_path = self.results[name]
        with open(py_path, "rb") as fh:
            py = fh.read()
        with open(js_path, "rb") as fh:
            js = fh.read()
        self.assertGreater(len(py), 0, f"{name}: python produced nothing")
        if py != js:
            for i, (a, b) in enumerate(zip(py, js)):
                if a != b:
                    self.fail(
                        f"{name}: first difference at byte {i}\n"
                        f"  python: {py[max(0, i - 40):i + 40]!r}\n"
                        f"  js    : {js[max(0, i - 40):i + 40]!r}"
                    )
            self.fail(f"{name}: lengths differ, python {len(py)} vs js {len(js)}")


def _add(name):
    def test(self):
        self._compare(name)
    test.__name__ = f"test_{name}_is_byte_identical"
    test.__doc__ = f"JS and Python emit identical HP-GL for {name}."
    setattr(Parity, test.__name__, test)


for _case in [c[0] for c in CASES] + ["calibration"]:
    _add(_case)


if __name__ == "__main__":
    unittest.main(verbosity=2)
