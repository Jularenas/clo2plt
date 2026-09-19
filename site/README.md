# clo2plt web

The browser build of the converter. Everything runs client-side: PDFs are read
with `FileReader`, inflated with the browser's native `DecompressionStream`, and
converted in JavaScript. Nothing is uploaded, which matters because these are
proprietary pattern files.

## Run it locally

```bash
python3 -m http.server 8765 --directory site
```

Then open <http://localhost:8765>. A server is required — ES modules do not load
over `file://`.

## Relationship to the Python CLI

`clo2plt/*.py` is the reference implementation; `site/js/*.js` mirrors it
module for module. They are verified to produce **byte-identical** HP-GL:

```bash
python3 tests/test_parity.py
```

If you change one side, change the other and re-run that check. A silent
divergence between them would be the worst kind of bug here — the tested
implementation and the shipped one disagreeing about pattern dimensions.
