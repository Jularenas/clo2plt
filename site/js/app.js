// UI wiring. Conversion happens entirely in the page; nothing is uploaded.

import * as classify from "./classify.js";
import { build as buildCal } from "./caltest.js";
import { read } from "./document.js";
import { emit, UNITS_PER_MM } from "./hpgl.js";
import { specSheet } from "./handover.js";
import { place } from "./layout.js";
import { makeZip } from "./zip.js";
import { svg as renderSvg } from "./svgproof.js";

const $ = (id) => document.getElementById(id);
const docs = [];           // { name, bytes, marker, error }
let selected = null;       // index of the doc shown in the preview
let hiddenKinds = new Set();

const opts = () => ({
  rotate: Number($("rotate").value),
  tolerance: Number($("tolerance").value),
  scale: Number($("scale").value) || 1,
  text: $("text").value,
  origin: $("origin").value,
  pieces: chosenPieces(),
});

function chosenPieces() {
  const boxes = [...document.querySelectorAll("#pieces input:checked")];
  const all = document.querySelectorAll("#pieces input").length;
  if (!all || boxes.length === all) return null;
  return boxes.map((b) => b.value);
}

// -- loading ---------------------------------------------------------------

async function addFiles(fileList) {
  const pdfs = [...fileList].filter((f) => /\.pdf$/i.test(f.name));
  const skipped = [...fileList].filter((f) => !/\.pdf$/i.test(f.name));
  if (skipped.length) {
    showErrors(skipped.map((f) => `${f.name} is not a PDF, skipped.`));
  }
  if (!pdfs.length) return;

  $("workspace").hidden = false;
  drop.classList.add("compact");
  $("dropline").textContent = "Drop more PDFs, or";
  for (const file of pdfs) {
    const entry = { name: file.name.replace(/\.pdf$/i, ""), bytes: null, marker: null, error: null };
    docs.push(entry);
    render();
    try {
      entry.bytes = new Uint8Array(await file.arrayBuffer());
      entry.marker = await read(entry.bytes, { tolerance: Number($("tolerance").value) });
    } catch (err) {
      entry.error = err.message || String(err);
    }
    if (selected === null && entry.marker) selected = docs.indexOf(entry);
    render();
  }
  refreshPieces();
  updatePreview();
}

// -- conversion ------------------------------------------------------------

async function convert(entry, overrides = {}) {
  const o = { ...opts(), ...overrides };
  const marker = await read(entry.bytes, { tolerance: o.tolerance, pieces: o.pieces });
  const placed = place(marker, o.rotate, o.origin, o.scale);
  const [text, retitled] = emit(
    placed.strokes,
    o.text === "none" ? [] : placed.labels,
    classify.DEFAULT_PENS,
    o.text === "none" ? "none" : "label"
  );
  return { marker, placed, text, retitled };
}

function toBytes(text) {
  const crlf = text.replace(/\n/g, "\r\n");
  const out = new Uint8Array(crlf.length);
  for (let i = 0; i < crlf.length; i += 1) out[i] = crlf.charCodeAt(i) & 0xff;
  return out;
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// -- rendering -------------------------------------------------------------

function render() {
  const host = $("files");
  host.replaceChildren();
  docs.forEach((entry, i) => {
    const card = document.createElement("div");
    card.className = "card" + (i === selected ? " active" : "");

    const h = document.createElement("h3");
    h.textContent = entry.name;
    card.append(h);

    if (entry.error) {
      const p = document.createElement("p");
      p.className = "note bad";
      p.textContent = entry.error;
      card.append(p);
      host.append(card);
      return;
    }
    if (!entry.marker) {
      const p = document.createElement("p");
      p.className = "meta";
      p.innerHTML = '<span class="spin"></span> reading…';
      card.append(p);
      host.append(card);
      return;
    }

    const m = entry.marker;
    const meta = document.createElement("p");
    meta.className = "meta";
    meta.textContent =
      `${m.pieces.length} pieces · page ${m.pageW.toFixed(1)} × ${m.pageH.toFixed(1)} mm` +
      (m.producer ? ` · ${m.producer}` : "");
    card.append(meta);

    const tags = document.createElement("div");
    tags.className = "tags";
    for (const kind of classify.ORDER) {
      const n = m.counts[kind];
      if (!n) continue;
      const t = document.createElement("span");
      t.className = "tag";
      t.innerHTML =
        `<span class="dot" style="background:${classify.PROOF_COLORS[kind]}"></span>` +
        `${kind} ${n} · pen ${classify.DEFAULT_PENS[kind]}`;
      tags.append(t);
    }
    card.append(tags);

    const acts = document.createElement("div");
    acts.className = "cardacts";
    const dl = document.createElement("button");
    dl.className = "primary";
    dl.textContent = "Download .plt";
    dl.onclick = () => downloadOne(i);
    const show = document.createElement("button");
    show.className = "ghost";
    show.textContent = i === selected ? "Previewing" : "Preview";
    show.disabled = i === selected;
    show.onclick = () => {
      selected = i;
      render();
      refreshPieces();
      updatePreview();
    };
    acts.append(dl, show);
    card.append(acts);

    if (m.unknownColors.size) {
      const p = document.createElement("p");
      p.className = "note";
      p.textContent =
        `${m.unknownColors.size} unrecognised stroke colour(s) sent to pen ` +
        `${classify.DEFAULT_PENS[classify.UNKNOWN]} — nothing was dropped, but check the preview.`;
      card.append(p);
    }
    host.append(card);
  });

  const ready = docs.some((d) => d.marker);
  $("dlAll").disabled = !ready;
  $("dlSpec").disabled = !ready;
}

function refreshPieces() {
  const box = $("pieceBox");
  const entry = docs[selected];
  if (!entry || !entry.marker) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const host = $("pieces");
  host.replaceChildren();
  for (const p of [...entry.marker.pieces].sort((a, b) => a.name.localeCompare(b.name))) {
    const l = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = p.name;
    cb.checked = true;
    cb.onchange = updatePreview;
    l.append(cb, document.createTextNode(p.name));
    host.append(l);
  }
}

let previewToken = 0;
async function updatePreview() {
  const entry = docs[selected];
  const box = $("previewBox");
  if (!entry || !entry.marker) {
    box.hidden = true;
    return;
  }
  const token = ++previewToken;
  box.hidden = false;
  $("stage").innerHTML = '<p class="meta"><span class="spin"></span> rendering…</p>';
  try {
    const { marker, placed } = await convert(entry);
    if (token !== previewToken) return;
    const o = opts();
    $("stage").innerHTML = renderSvg(
      placed.strokes,
      o.text === "none" ? [] : placed.labels,
      placed.extent,
      marker
    );
    drawLegend(placed, marker);
    applyHidden();
  } catch (err) {
    if (token !== previewToken) return;
    $("stage").innerHTML = `<p class="note bad">${err.message || err}</p>`;
    $("legend").replaceChildren();
  }
}

function drawLegend(placed, marker) {
  const host = $("legend");
  host.replaceChildren();
  const [minx, miny, maxx, maxy] = placed.extent;

  const size = document.createElement("span");
  size.className = "meta";
  size.textContent =
    `${(maxx - minx).toFixed(1)} × ${(maxy - miny).toFixed(1)} mm · ` +
    `${placed.strokes.reduce((a, s) => a + s.points.length, 0).toLocaleString()} points`;
  host.append(size);

  const counts = new Map();
  for (const s of placed.strokes) counts.set(s.kind, (counts.get(s.kind) || 0) + 1);
  for (const kind of classify.ORDER) {
    const n = kind === classify.LABEL ? placed.labels.length : counts.get(kind) || 0;
    if (!n) continue;
    const l = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !hiddenKinds.has(kind);
    cb.onchange = () => {
      if (cb.checked) hiddenKinds.delete(kind);
      else hiddenKinds.add(kind);
      applyHidden();
    };
    const sw = document.createElement("span");
    sw.className = "sw";
    sw.style.background = classify.PROOF_COLORS[kind];
    l.append(cb, sw, document.createTextNode(`${kind} (${n})`));
    host.append(l);
  }
}

function applyHidden() {
  for (const g of document.querySelectorAll("#stage [data-kind]")) {
    g.style.display = hiddenKinds.has(g.dataset.kind) ? "none" : "";
  }
}

function showErrors(messages) {
  const box = $("errors");
  box.hidden = !messages.length;
  box.replaceChildren(
    ...messages.map((m) => {
      const p = document.createElement("p");
      p.textContent = m;
      return p;
    })
  );
}

// -- downloads -------------------------------------------------------------

async function downloadOne(i) {
  const entry = docs[i];
  try {
    const { text } = await convert(entry);
    download(new Blob([toBytes(text)], { type: "application/octet-stream" }), `${entry.name}.plt`);
  } catch (err) {
    showErrors([`${entry.name}: ${err.message || err}`]);
  }
}

async function downloadAll() {
  const o = opts();
  const entries = [];
  const specFiles = [];
  const problems = [];

  const cal = buildCal(200);
  const [calText] = emit(cal.strokes, cal.labels, classify.DEFAULT_PENS);
  const calName = "1 - CALIBRATION 200mm.plt";
  entries.push({ name: calName, bytes: toBytes(calText) });
  specFiles.push(describe(calName, cal, calText));

  for (const entry of docs) {
    if (!entry.marker) continue;
    try {
      const main = await convert(entry);
      const name = `${entry.name}.plt`;
      entries.push({ name, bytes: toBytes(main.text) });
      specFiles.push(describePlaced(name, main.placed));

      // The alternate orientation, so a wrong axis mapping at the plotter is
      // a file swap rather than another trip.
      const alt = await convert(entry, { rotate: (o.rotate + 90) % 360 });
      const altName = `${entry.name} ROTATED 90.plt`;
      entries.push({ name: altName, bytes: toBytes(alt.text) });
      specFiles.push(describePlaced(altName, alt.placed));
    } catch (err) {
      problems.push(`${entry.name}: ${err.message || err}`);
    }
  }

  entries.push({
    name: "0 - technical spec for operator.txt",
    bytes: new TextEncoder().encode(specSheet(specFiles)),
  });

  showErrors(problems);
  if (entries.length <= 2) return;
  download(await makeZip(entries), "plotter-files.zip");
}

function describePlaced(name, placed) {
  return {
    name,
    extent: placed.extent,
    polylines: placed.strokes.length,
    points: placed.strokes.reduce((a, s) => a + s.points.length, 0),
    labels: placed.labels.length,
  };
}

function describe(name, built, text) {
  const xs = [];
  const ys = [];
  for (const s of built.strokes) for (const [x, y] of s.points) { xs.push(x); ys.push(y); }
  return {
    name,
    extent: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
    polylines: built.strokes.length,
    points: built.strokes.reduce((a, s) => a + s.points.length, 0),
    labels: built.labels.length,
  };
}

// -- events ----------------------------------------------------------------

const drop = $("drop");
$("browse").onclick = () => $("picker").click();
$("picker").onchange = (e) => addFiles(e.target.files);
["dragenter", "dragover"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); })
);
["dragleave", "drop"].forEach((ev) =>
  drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); })
);
drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

$("tolerance").oninput = () => {
  $("tolOut").textContent = `${Number($("tolerance").value).toFixed(3)} mm`;
  schedulePreview();
};
for (const id of ["rotate", "scale", "text", "origin"]) {
  $(id).onchange = updatePreview;
}
$("allPieces").onclick = () => {
  document.querySelectorAll("#pieces input").forEach((b) => (b.checked = true));
  updatePreview();
};
$("nonePieces").onclick = () => {
  document.querySelectorAll("#pieces input").forEach((b) => (b.checked = false));
  updatePreview();
};

let timer = null;
function schedulePreview() {
  clearTimeout(timer);
  timer = setTimeout(updatePreview, 250);
}

$("dlAll").onclick = downloadAll;
$("dlCal").onclick = () => {
  const cal = buildCal(200);
  const [text] = emit(cal.strokes, cal.labels, classify.DEFAULT_PENS);
  download(new Blob([toBytes(text)], { type: "application/octet-stream" }),
           "CALIBRATION 200mm.plt");
};
$("dlSpec").onclick = async () => {
  const files = [];
  for (const entry of docs) {
    if (!entry.marker) continue;
    const { placed } = await convert(entry);
    files.push(describePlaced(`${entry.name}.plt`, placed));
  }
  download(new Blob([specSheet(files)], { type: "text/plain" }),
           "technical spec for operator.txt");
};
$("reset").onclick = () => {
  docs.length = 0;
  selected = null;
  hiddenKinds = new Set();
  $("workspace").hidden = true;
  $("errors").hidden = true;
  $("picker").value = "";
  drop.classList.remove("compact");
  $("dropline").textContent = "Drop CLO 3D marker PDFs here";
  render();
};

$("tolOut").textContent = "0.050 mm";
