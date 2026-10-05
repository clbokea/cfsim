// cfsim room editor: turns a floor plan image into a cfsim world (.txt map).
//
// The simple flow: open a plan -> the building is found automatically (the
// largest group of thick dark lines) -> type its width (that gives the scale)
// -> click the start -> save. Everything else is under "Fine-tune".
//
// Everything the user does is kept in image pixel coordinates (scale points,
// area, paint strokes, start spots), so changing the cell size or the
// darkness settings never loses work. The grid of walls is recomputed from
// that whenever something changes:
//   1. the image is converted to brightness once (at most 2000 px wide),
//   2. dark pixels are cleaned up: a morphological opening removes every line
//      thinner than the clean-up size (text, door swings, furniture, dimension
//      lines) and keeps walls,
//   3. a summed-area table of the cleaned pixels counts dark pixels quickly,
//   4. a cell is a wall if enough of it is dark; small leftover specks are
//      removed; then the paint/erase strokes apply.
'use strict';

const $ = (id) => document.getElementById(id);
const canvas = $('canvas');
const ctx = canvas.getContext('2d');
const WORK_MAX = 2000;            // brightness image size limit (px)
const EXPORT_MAX = 2400;          // saved floor plan image size limit (px)
const MAX_CELLS = 2e6;

const S = {
  img: null, fileName: '', type: 'image/png',
  lum: null, ww: 0, wh: 0, ws: 1,          // brightness image and its scale
  satKey: '', sat: null,                   // summed-area table of cleaned dark pixels
  comps: null,                             // connected groups of dark pixels
  building: -1, wallT: null,               // the building's group, its wall thickness (px)
  scale: null,                             // metres per image pixel
  measure: [],                             // up to two points
  crop: null,                              // {x, y, w, h}
  edits: [],                               // {x, y, r (m), v: 1 wall / 0 free}
  starts: [],                              // {x, y, ch: 'S' | '1'..'9'}
  grid: null, overlay: null,
  tool: null,
  view: { z: 1, x: 0, y: 0 },              // screen = image * z + (x, y)
};

const HINTS = {
  null: 'Drag to move the plan, wheel to zoom.',
  measure: 'Click two points whose distance you know, then enter the distance on the left.',
  crop: 'Drag a rectangle around the area to use.',
  wall: 'Click or drag to paint walls. Right-drag moves the plan.',
  erase: 'Click or drag to erase walls (text, furniture, door swings). Right-drag moves the plan.',
  start: 'Click where the drone takes off.',
  extra: 'Click to add start spots 1–9 for more drones.',
};

// ------------------------------------------------------------------ image
function loadImage(src, fileName, type) {
  const img = new Image();
  img.onload = () => {
    S.img = img;
    S.fileName = fileName;
    S.type = type === 'image/jpeg' ? 'image/jpeg' : 'image/png';
    S.scale = null;
    S.measure = [];
    S.crop = { x: 0, y: 0, w: img.naturalWidth, h: img.naturalHeight };
    S.edits = [];
    S.starts = [];
    S.ws = Math.min(1, WORK_MAX / Math.max(img.naturalWidth, img.naturalHeight));
    S.ww = Math.max(1, Math.round(img.naturalWidth * S.ws));
    S.wh = Math.max(1, Math.round(img.naturalHeight * S.ws));
    const c = document.createElement('canvas');
    c.width = S.ww; c.height = S.wh;
    const cc = c.getContext('2d');
    cc.fillStyle = '#fff';                   // transparent parts count as white paper
    cc.fillRect(0, 0, S.ww, S.wh);
    cc.drawImage(img, 0, 0, S.ww, S.wh);
    const px = cc.getImageData(0, 0, S.ww, S.wh).data;
    S.lum = new Uint8Array(S.ww * S.wh);
    for (let i = 0; i < S.lum.length; i++) {
      S.lum[i] = (0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2]) | 0;
    }
    S.satKey = '';
    S.comps = null;
    const box = detectBuilding();
    if (box) S.crop = box;
    $('widthHelp').innerHTML = box
      ? 'The blue box shows the building the editor found. Type its width from the ' +
        'measurements on the plan.'
      : '<span class="error">No building found automatically.</span> Type the width of the ' +
        'whole image, or select the area by hand under <b>Fine-tune</b>.';
    $('widthM').value = '';
    $('scaleInfo').textContent = '';
    $('saveResult').textContent = '';
    const base = fileName.replace(/\.[^.]*$/, '').replace(/[^A-Za-z0-9_-]+/g, '_') || 'my_room';
    $('name').value = base;
    $('fileInfo').textContent = `${fileName}: ${img.naturalWidth} × ${img.naturalHeight} px`;
    $('legend').hidden = false;
    fitView();
    update();
    setTool(null);
    $('hint').textContent = 'Type the width of the building on the left (step 2).';
    $('widthM').focus();
  };
  img.onerror = () => { $('fileInfo').innerHTML = '<span class="error">Could not read this image.</span>'; };
  img.src = src;
}

$('file').addEventListener('change', (e) => {
  const f = e.target.files[0];
  if (f) loadImage(URL.createObjectURL(f), f.name, f.type);
});
$('sample').addEventListener('click', () =>
  loadImage('/static/sample-floorplan.png', 'sample-floorplan.png', 'image/png'));

// ------------------------------------------------------------------- grid
// Summed-area table of a 0/1 image (ww x wh): count of ones in any rectangle.
function summed(mask) {
  const W = S.ww + 1;
  const sat = new Int32Array(W * (S.wh + 1));
  for (let y = 0; y < S.wh; y++) {
    let row = 0;
    for (let x = 0; x < S.ww; x++) {
      row += mask[y * S.ww + x];
      sat[(y + 1) * W + x + 1] = sat[y * W + x + 1] + row;
    }
  }
  return sat;
}

// Ones in the (2r+1) x (2r+1) square around (x, y), and the size of that
// square cut off at the image border.
function around(sat, x, y, r) {
  const W = S.ww + 1;
  const x0 = Math.max(0, x - r), x1 = Math.min(S.ww, x + r + 1);
  const y0 = Math.max(0, y - r), y1 = Math.min(S.wh, y + r + 1);
  return [sat[y1 * W + x1] - sat[y0 * W + x1] - sat[y1 * W + x0] + sat[y0 * W + x0],
    (x1 - x0) * (y1 - y0)];
}

function darkMask(thr) {
  const m = new Uint8Array(S.ww * S.wh);
  for (let i = 0; i < m.length; i++) m[i] = S.lum[i] < thr ? 1 : 0;
  return m;
}

// Erosion: keep a pixel only if the whole square around it is dark.
function erode(mask, r) {
  const sat = summed(mask);
  const out = new Uint8Array(mask.length);
  for (let y = 0; y < S.wh; y++) {
    for (let x = 0; x < S.ww; x++) {
      const [n, area] = around(sat, x, y, r);
      out[y * S.ww + x] = n === area ? 1 : 0;
    }
  }
  return out;
}

// Dilation: a pixel is dark if any pixel in the square around it is dark.
function dilate(mask, r) {
  const sat = summed(mask);
  const out = new Uint8Array(mask.length);
  for (let y = 0; y < S.wh; y++) {
    for (let x = 0; x < S.ww; x++) out[y * S.ww + x] = around(sat, x, y, r)[0] > 0 ? 1 : 0;
  }
  return out;
}

// Connected groups of dark pixels (8-connected) for a darkness threshold,
// with the bounding box, pixel count and mean line thickness of each group.
// The thickness of a line through a pixel is the shorter of its horizontal
// and vertical dark runs.
function components(thr) {
  if (S.comps && S.comps.thr === thr) return S.comps;
  const W = S.ww, H = S.wh, N = W * H;
  const mask = darkMask(thr);
  const thick = new Uint16Array(N);
  for (let y = 0; y < H; y++) {              // horizontal runs
    let x = 0;
    while (x < W) {
      if (!mask[y * W + x]) { x++; continue; }
      let e = x;
      while (e < W && mask[y * W + e]) e++;
      for (let k = x; k < e; k++) thick[y * W + k] = Math.min(65535, e - x);
      x = e;
    }
  }
  for (let x = 0; x < W; x++) {              // vertical runs: keep the shorter one
    let y = 0;
    while (y < H) {
      if (!mask[y * W + x]) { y++; continue; }
      let e = y;
      while (e < H && mask[e * W + x]) e++;
      for (let k = y; k < e; k++) thick[k * W + x] = Math.min(thick[k * W + x], e - y);
      y = e;
    }
  }
  const label = new Int32Array(N).fill(-1);
  const stack = new Int32Array(N);
  const list = [];
  for (let start = 0; start < N; start++) {
    if (!mask[start] || label[start] >= 0) continue;
    const id = list.length;
    let n = 0, sumT = 0, top = 0;
    let x0 = W, y0 = H, x1 = 0, y1 = 0;
    stack[top++] = start;
    label[start] = id;
    while (top) {
      const i = stack[--top];
      const x = i % W, y = (i / W) | 0;
      n++;
      sumT += thick[i];
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
      for (let dy = -1; dy <= 1; dy++) {
        const yy = y + dy;
        if (yy < 0 || yy >= H) continue;
        for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx;
          if (xx < 0 || xx >= W) continue;
          const j = yy * W + xx;
          if (mask[j] && label[j] < 0) { label[j] = id; stack[top++] = j; }
        }
      }
    }
    list.push({ n, t: sumT / n, x0, y0, x1, y1, w: x1 - x0 + 1, h: y1 - y0 + 1 });
  }
  S.comps = { thr, mask, label, thick, list };
  return S.comps;
}

// The building: the group of dark lines with the largest outline. The walls
// enclose the rooms, so they win against text, door swings and dimension
// lines; a frame around the whole sheet is skipped. Also measures the
// thickness of its walls (S.wallT, brightness image px). Returns the
// building's box in image pixels, or null.
function detectBuilding() {
  const c = components(+$('thr').value);
  let best = -1, bestArea = 0;
  c.list.forEach((g, i) => {
    if (g.w >= 0.97 * S.ww && g.h >= 0.97 * S.wh) return;       // sheet frame
    if (g.w < 0.05 * S.ww || g.h < 0.05 * S.wh) return;          // a line or a word
    if (g.w * g.h > bestArea) { best = i; bestArea = g.w * g.h; }
  });
  S.building = best;
  S.wallT = null;
  S.satKey = '';
  if (best < 0) return null;
  // wall thickness: the median line thickness of the building's pixels
  const hist = new Uint32Array(256);
  for (let i = 0; i < c.label.length; i++) {
    if (c.label[i] === best) hist[Math.min(255, c.thick[i])]++;
  }
  const half = c.list[best].n / 2;
  let sum = 0;
  for (let t = 0; t < 256; t++) { sum += hist[t]; if (sum >= half) { S.wallT = Math.max(1, t); break; } }
  const g = c.list[best];
  return { x: g.x0 / S.ws, y: g.y0 / S.ws, w: g.w / S.ws, h: g.h / S.ws };
}

// Summed-area table of the pixels that are walls (cached). With clean-up on:
//  - keep the building's lines, and other groups that look like walls (at
//    least 40 cm long and about as thick as the building's walls) or like
//    pillars (a solid block of at least 10 cm); this drops text, dashed door
//    swings, dimension lines and other thin or small things,
//  - then remove lines thinner than the clean-up size with an opening - but
//    never thinner than 70 % of the walls, so thin walls are kept.
function wallTable(thr) {
  const clean = +$('clean').value;
  const key = [thr, clean, S.scale, S.building].join('/');
  if (S.satKey === key) return S.sat;
  const c = components(thr);
  let mask = c.mask;
  if (clean && S.scale) {
    const T = S.wallT || 1;
    const mPerPx = S.scale / S.ws;                             // metres per brightness px
    const keep = c.list.map((g, i) => {
      if (i === S.building) return true;
      const wallLike = Math.max(g.w, g.h) * mPerPx >= 0.4 && g.t >= 0.6 * T;
      const pillarLike = g.n >= 0.75 * g.w * g.h && Math.min(g.w, g.h) >= Math.max(T, 0.1 / mPerPx);
      return wallLike || pillarLike;
    });
    mask = new Uint8Array(c.mask.length);
    for (let i = 0; i < mask.length; i++) if (c.label[i] >= 0 && keep[c.label[i]]) mask[i] = 1;
    const k = Math.min(clean / mPerPx, 0.7 * T);               // opening square size (px)
    const r = Math.floor((k - 1) / 2);
    if (r >= 1) mask = dilate(erode(mask, r), r);
  }
  S.sat = summed(mask);
  S.satKey = key;
  return S.sat;
}

// Remove groups of wall cells smaller than minCells (specks left by the plan).
function removeSpecks(data, rows, cols, minCells) {
  const seen = new Uint8Array(data.length);
  const group = [];
  for (let start = 0; start < data.length; start++) {
    if (!data[start] || seen[start]) continue;
    group.length = 0;
    const stack = [start];
    seen[start] = 1;
    while (stack.length) {
      const i = stack.pop();
      group.push(i);
      const r = (i / cols) | 0, c = i % cols;
      for (const [rr, cc] of [[r - 1, c], [r + 1, c], [r, c - 1], [r, c + 1]]) {
        if (rr < 0 || cc < 0 || rr >= rows || cc >= cols) continue;
        const j = rr * cols + cc;
        if (data[j] && !seen[j]) { seen[j] = 1; stack.push(j); }
      }
    }
    if (group.length < minCells) for (const i of group) data[i] = 0;
  }
}

function computeGrid() {
  S.grid = null;
  if (!S.img || !S.scale) { $('gridInfo').textContent = ''; return; }
  const cell = +$('cell').value;
  const cellPx = cell / S.scale;
  const { x: cx, y: cy, w: cw, h: ch } = S.crop;
  const cols = Math.max(1, Math.ceil(cw / cellPx - 1e-6));
  const rows = Math.max(1, Math.ceil(ch / cellPx - 1e-6));
  if (rows * cols > MAX_CELLS) {
    $('gridInfo').innerHTML = '<span class="error">Too many cells – choose a bigger cell size or a smaller area.</span>';
    return;
  }
  const sat = wallTable(+$('thr').value);
  // A thin wall line covers only a small part of a cell: lower the needed
  // coverage to 40 % of what such a line covers, so thin walls are kept.
  let fill = +$('fill').value / 100;
  if (S.wallT) fill = Math.min(fill, 0.4 * S.wallT / (cellPx * S.ws));
  const W = S.ww + 1, ws = S.ws;
  const data = new Uint8Array(rows * cols);
  for (let r = 0; r < rows; r++) {
    const iy0 = cy + r * cellPx, iy1 = Math.min(iy0 + cellPx, cy + ch);
    const y0 = Math.min(S.wh - 1, Math.floor(iy0 * ws));
    const y1 = Math.min(S.wh, Math.max(y0 + 1, Math.ceil(iy1 * ws)));
    for (let c = 0; c < cols; c++) {
      const ix0 = cx + c * cellPx, ix1 = Math.min(ix0 + cellPx, cx + cw);
      const x0 = Math.min(S.ww - 1, Math.floor(ix0 * ws));
      const x1 = Math.min(S.ww, Math.max(x0 + 1, Math.ceil(ix1 * ws)));
      const dark = sat[y1 * W + x1] - sat[y0 * W + x1] - sat[y1 * W + x0] + sat[y0 * W + x0];
      if (dark >= fill * (x1 - x0) * (y1 - y0)) data[r * cols + c] = 1;
    }
  }
  if (+$('clean').value) {                   // specks smaller than about 0.03 m²
    removeSpecks(data, rows, cols, Math.max(2, Math.round(0.03 / (cell * cell))));
  }
  for (const e of S.edits) {                 // paint and erase strokes
    const rc = Math.max(0.5, e.r / 2 / cell);
    const fc = (e.x - cx) / cellPx, fr = (e.y - cy) / cellPx;
    for (let r = Math.floor(fr - rc); r <= Math.ceil(fr + rc); r++) {
      if (r < 0 || r >= rows) continue;
      for (let c = Math.floor(fc - rc); c <= Math.ceil(fc + rc); c++) {
        if (c < 0 || c >= cols) continue;
        const dx = c + 0.5 - fc, dy = r + 0.5 - fr;
        if (dx * dx + dy * dy <= rc * rc) data[r * cols + c] = e.v;
      }
    }
  }
  S.grid = { rows, cols, cell, cellPx, data };

  const ov = document.createElement('canvas');
  ov.width = cols; ov.height = rows;
  const oc = ov.getContext('2d');
  const id = oc.createImageData(cols, rows);
  let walls = 0;
  for (let i = 0; i < data.length; i++) {
    if (!data[i]) continue;
    walls++;
    id.data.set([229, 57, 53, 170], i * 4);
  }
  oc.putImageData(id, 0, 0);
  S.overlay = ov;
  $('gridInfo').textContent = `${cols} × ${rows} cells = ${(cols * cell).toFixed(1)} × ` +
    `${(rows * cell).toFixed(1)} m, ${Math.round(100 * walls / data.length)} % walls`;
}

// ---------------------------------------------------------------- drawing
function fitView() {
  const r = canvas.getBoundingClientRect();
  const z = 0.95 * Math.min(r.width / S.img.naturalWidth, r.height / S.img.naturalHeight);
  S.view = { z, x: (r.width - S.img.naturalWidth * z) / 2, y: (r.height - S.img.naturalHeight * z) / 2 };
}

let dragRect = null;              // area selection while dragging
function draw() {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(r.width * dpr) || canvas.height !== Math.round(r.height * dpr)) {
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, r.width, r.height);
  if (!S.img) return;
  const { z, x, y } = S.view;
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(z, z);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(S.img, 0, 0);

  const iw = S.img.naturalWidth, ih = S.img.naturalHeight, c = S.crop;
  ctx.fillStyle = '#00000055';               // shade what is outside the area
  ctx.beginPath();
  ctx.rect(0, 0, iw, ih);
  ctx.rect(c.x, c.y, c.w, c.h);
  ctx.fill('evenodd');

  if (S.grid && S.overlay) {
    ctx.save();
    ctx.beginPath();                         // the last row/column of cells is only partly
    ctx.rect(c.x, c.y, c.w, c.h);            // inside the area: do not draw past its edge
    ctx.clip();
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(S.overlay, c.x, c.y, S.grid.cols * S.grid.cellPx, S.grid.rows * S.grid.cellPx);
    ctx.restore();
  }
  ctx.lineWidth = 1.5 / z;
  ctx.strokeStyle = '#3949ab';
  ctx.strokeRect(c.x, c.y, c.w, c.h);

  if (S.measure.length) {
    ctx.strokeStyle = '#ff9800';
    ctx.fillStyle = '#ff9800';
    ctx.lineWidth = 2.5 / z;
    ctx.beginPath();
    S.measure.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
    for (const p of S.measure) { ctx.beginPath(); ctx.arc(p.x, p.y, 5 / z, 0, 7); ctx.fill(); }
  }

  for (const s of S.starts) {
    ctx.fillStyle = s.ch === 'S' ? '#3949ab' : '#5c6bc0';
    ctx.beginPath();
    ctx.arc(s.x, s.y, 10 / z, 0, 7);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.font = `bold ${12 / z}px system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(s.ch, s.x, s.y + 0.5 / z);
  }
  if (dragRect) {
    ctx.strokeStyle = '#3949ab';
    ctx.setLineDash([6 / z, 4 / z]);
    ctx.strokeRect(dragRect.x, dragRect.y, dragRect.w, dragRect.h);
    ctx.setLineDash([]);
  }
  ctx.restore();
}

let pending = false;
function update() {               // recompute the grid and redraw (at most once per frame)
  if (pending) return;
  pending = true;
  requestAnimationFrame(() => {
    pending = false;
    computeGrid();
    draw();
    steps();
  });
}
window.addEventListener('resize', () => draw());

function steps() {
  $('step1').classList.toggle('done', !!S.img);
  $('step2').classList.toggle('done', !!S.scale);
  $('step3').classList.toggle('done', S.starts.some((s) => s.ch === 'S'));
  $('thrV').textContent = $('thr').value;
  $('fillV').textContent = $('fill').value + ' % dark';
}

// ------------------------------------------------------------------ tools
// A tool button switches its tool on and off; the steps switch tools on.
function setTool(t, toggle = false) {
  S.tool = toggle && S.tool === t ? null : t;
  document.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === S.tool));
  $('hint').textContent = S.img ? HINTS[S.tool] : 'Open a floor plan to start.';
  canvas.style.cursor = S.tool ? 'crosshair' : 'grab';
}
document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool, true)));

// Thin wall lines snap to whole cells: use 5 cm cells for them (unless the
// user has chosen a cell size), so rooms do not shrink by 10 cm per wall.
function autoCellSize() {
  if (S.cellChosen || !S.wallT || !S.scale) return;
  $('cell').value = S.wallT * S.scale / S.ws < 0.06 ? '0.05' : '0.1';
}

function scaleText() {
  const c = S.crop, w = c.w * S.scale, h = c.h * S.scale;
  const odd = w > 150 || w < 1
    ? ' <span class="error">That is an unusual size – check the unit (m, cm or mm).</span>' : '';
  return `The building is <b>${w.toFixed(2)} × ${h.toFixed(2)} m</b> ` +
    `(1 m = ${(1 / S.scale).toFixed(1)} px). Check it against the plan.${odd}`;
}

$('setWidth').addEventListener('click', () => {
  const m = parseFloat($('widthM').value) * +$('widthUnit').value;
  if (!S.img) return;
  if (!(m > 0)) {
    $('scaleInfo').innerHTML = '<span class="error">Type the width, e.g. 10 m or 400 cm.</span>';
    return;
  }
  S.scale = m / S.crop.w;
  autoCellSize();
  $('scaleInfo').innerHTML = scaleText();
  setTool('start');
  update();
});
$('widthM').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('setWidth').click(); });
$('autoCrop').addEventListener('click', () => {
  if (!S.img) return;
  const box = detectBuilding();
  if (box) S.crop = box;
  else $('hint').textContent = 'No building found – select the area by hand.';
  if (S.scale) $('scaleInfo').innerHTML = scaleText();
  update();
});
$('clean').addEventListener('input', update);

$('setScale').addEventListener('click', () => {
  const m = parseFloat($('measureM').value);
  if (S.measure.length !== 2 || !(m > 0)) {
    $('scaleInfo').innerHTML = '<span class="error">Click two points on the plan and enter their distance first.</span>';
    return;
  }
  const [a, b] = S.measure;
  S.scale = m / Math.hypot(a.x - b.x, a.y - b.y);
  $('widthM').value = (S.crop.w * S.scale).toFixed(2);
  $('widthUnit').value = '1';
  autoCellSize();
  $('scaleInfo').innerHTML = scaleText();
  S.measure = [];
  setTool(S.starts.length ? null : 'start');
  update();
});
$('measureM').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('setScale').click(); });
$('resetCrop').addEventListener('click', () => {
  if (!S.img) return;
  S.crop = { x: 0, y: 0, w: S.img.naturalWidth, h: S.img.naturalHeight };
  update();
});
$('clearEdits').addEventListener('click', () => { S.edits = []; update(); });
$('clearStarts').addEventListener('click', () => { S.starts = []; update(); });
$('cell').addEventListener('input', () => { S.cellChosen = true; update(); });
$('fill').addEventListener('input', update);
// a new threshold gives new groups of dark pixels: find the building's walls
// again (the area stays as it is)
$('thr').addEventListener('input', () => { if (S.img) detectBuilding(); update(); });

// ------------------------------------------------------------------ mouse
const toImage = (e) => {
  const r = canvas.getBoundingClientRect();
  return { x: (e.clientX - r.left - S.view.x) / S.view.z, y: (e.clientY - r.top - S.view.y) / S.view.z };
};
const inImage = (p) => p.x >= 0 && p.y >= 0 && p.x <= S.img.naturalWidth && p.y <= S.img.naturalHeight;

let drag = null;
let spaceDown = false;
window.addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === document.body) { spaceDown = true; e.preventDefault(); } });
window.addEventListener('keyup', (e) => { if (e.code === 'Space') spaceDown = false; });
canvas.addEventListener('contextmenu', (e) => e.preventDefault());

canvas.addEventListener('pointerdown', (e) => {
  if (!S.img) return;
  canvas.setPointerCapture(e.pointerId);
  const p = toImage(e);
  if (e.button !== 0 || spaceDown || !S.tool) {
    drag = { kind: 'pan', sx: e.clientX, sy: e.clientY, vx: S.view.x, vy: S.view.y };
    canvas.style.cursor = 'grabbing';
    return;
  }
  if (S.tool === 'measure') {
    if (S.measure.length >= 2) S.measure = [];
    S.measure.push(p);
    // later: the mouse-down on the canvas would take the focus away again
    if (S.measure.length === 2) setTimeout(() => $('measureM').focus(), 0);
    draw();
  } else if (S.tool === 'crop') {
    drag = { kind: 'crop', x0: p.x, y0: p.y };
  } else if (S.tool === 'wall' || S.tool === 'erase') {
    if (!S.scale) { $('hint').textContent = 'Set the scale (step 2) before painting.'; return; }
    drag = { kind: 'paint', last: p };
    paint(p);
  } else if (S.tool === 'start' || S.tool === 'extra') {
    if (!inImage(p)) return;
    if (S.tool === 'start') {
      S.starts = S.starts.filter((s) => s.ch !== 'S');
      S.starts.unshift({ x: p.x, y: p.y, ch: 'S' });
      setTool(null);
      $('hint').textContent = 'Start placed. Give the world a name and save it (step 4).';
    } else {
      const used = new Set(S.starts.map((s) => s.ch));
      const free = '123456789'.split('').find((d) => !used.has(d));
      if (!free) { $('hint').textContent = 'All nine extra start spots are used.'; return; }
      S.starts.push({ x: p.x, y: p.y, ch: free });
    }
    update();
  }
});

canvas.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const p = toImage(e);
  if (drag.kind === 'pan') {
    S.view.x = drag.vx + e.clientX - drag.sx;
    S.view.y = drag.vy + e.clientY - drag.sy;
    draw();
  } else if (drag.kind === 'crop') {
    dragRect = { x: Math.min(drag.x0, p.x), y: Math.min(drag.y0, p.y),
      w: Math.abs(p.x - drag.x0), h: Math.abs(p.y - drag.y0) };
    draw();
  } else if (drag.kind === 'paint') {
    const step = Math.max(1, (+$('brush').value / S.scale) / 4);
    const d = Math.hypot(p.x - drag.last.x, p.y - drag.last.y);
    for (let t = step; t <= d; t += step) {   // fill the gaps of a fast stroke
      paint({ x: drag.last.x + (p.x - drag.last.x) * t / d, y: drag.last.y + (p.y - drag.last.y) * t / d });
    }
    if (d >= step) drag.last = p;
  }
});

canvas.addEventListener('pointerup', () => {
  if (drag && drag.kind === 'crop' && dragRect) {
    const iw = S.img.naturalWidth, ih = S.img.naturalHeight;
    const x = Math.max(0, dragRect.x), y = Math.max(0, dragRect.y);
    const w = Math.min(iw, dragRect.x + dragRect.w) - x, h = Math.min(ih, dragRect.y + dragRect.h) - y;
    if (w > 10 && h > 10) S.crop = { x, y, w, h };
    if (S.scale) $('scaleInfo').innerHTML = scaleText();
    dragRect = null;
    update();
  }
  drag = null;
  canvas.style.cursor = S.tool ? 'crosshair' : 'grab';
});

function paint(p) {
  S.edits.push({ x: p.x, y: p.y, r: +$('brush').value, v: S.tool === 'wall' ? 1 : 0 });
  update();
}

canvas.addEventListener('wheel', (e) => {
  if (!S.img) return;
  e.preventDefault();
  const r = canvas.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  const z = Math.min(40, Math.max(0.05, S.view.z * Math.exp(-e.deltaY * 0.0015)));
  S.view.x = mx - (mx - S.view.x) * z / S.view.z;
  S.view.y = my - (my - S.view.y) * z / S.view.z;
  S.view.z = z;
  draw();
}, { passive: false });

// ------------------------------------------------------------------- save
function fmt(v) { return (Math.round(v * 1000) / 1000).toString(); }

// The world map text. Throws an Error with a message for the user.
function worldText(name, ext) {
  if (!S.img) throw new Error('Open a floor plan first (step 1).');
  if (!S.scale) throw new Error('Set the scale first (step 2).');
  if (!S.grid) throw new Error('No walls yet – check step 4.');
  const g = S.grid, cell = g.cell;
  const b = $('outline').checked ? 1 : 0;
  const R = g.rows + 2 * b, C = g.cols + 2 * b;
  const rows = [];
  for (let r = 0; r < R; r++) {
    const row = new Array(C);
    for (let c = 0; c < C; c++) {
      const gr = r - b, gc = c - b;
      const border = gr < 0 || gc < 0 || gr >= g.rows || gc >= g.cols;
      row[c] = border || g.data[gr * g.cols + gc] ? '#' : '.';
    }
    rows.push(row);
  }
  if (!S.starts.some((s) => s.ch === 'S')) throw new Error('Place the start S (step 5).');
  let sr = 0, sc = 0;
  for (const s of S.starts) {
    const c = Math.floor((s.x - S.crop.x) / g.cellPx) + b;
    const r = Math.floor((s.y - S.crop.y) / g.cellPx) + b;
    if (r < b || c < b || r >= g.rows + b || c >= g.cols + b) {
      throw new Error(`Start ${s.ch} is outside the selected area.`);
    }
    if (rows[r][c] === '#') {
      throw new Error(`Start ${s.ch} is on a wall – move it, or erase the wall there.`);
    }
    rows[r][c] = s.ch;
    if (s.ch === 'S') { sr = r; sc = c; }
  }
  // The image's top-left corner is the top-left corner of grid cell (b, b).
  // The centre of the S cell is (0, 0); x to the right, y up.
  const x1 = (b - sc) * cell - cell / 2;
  const y2 = (sr - b) * cell + cell / 2;
  const x2 = x1 + S.crop.w * S.scale;
  const y1 = y2 - S.crop.h * S.scale;
  const height = parseFloat($('height').value) || 2.5;
  return [
    `; ${name} - made with the cfsim room editor from ${S.fileName}`,
    `; one character = ${fmt(cell * 100)} cm: '#' wall, '.' free, 'S' start, '1'-'9' more starts`,
    `height: ${fmt(height)}`,
    `cell: ${fmt(cell)}`,
    `image: ${name}.${ext}`,
    `image_box: ${fmt(x1)} ${fmt(y1)} ${fmt(x2)} ${fmt(y2)}`,
    ...rows.map((r) => r.join('')),
    '',
  ].join('\n');
}

function exportImage() {
  const c = S.crop;
  const k = Math.min(1, EXPORT_MAX / Math.max(c.w, c.h));
  const out = document.createElement('canvas');
  out.width = Math.max(1, Math.round(c.w * k));
  out.height = Math.max(1, Math.round(c.h * k));
  const oc = out.getContext('2d');
  oc.fillStyle = '#fff';
  oc.fillRect(0, 0, out.width, out.height);
  oc.drawImage(S.img, c.x, c.y, c.w, c.h, 0, 0, out.width, out.height);
  const ext = S.type === 'image/jpeg' ? 'jpg' : 'png';
  return { ext, dataUrl: out.toDataURL(S.type, 0.9) };
}

function prepare() {
  computeGrid();                    // save exactly what the settings give now
  const name = $('name').value.trim();
  if (!/^[A-Za-z0-9_-]{1,60}$/.test(name)) throw new Error('Use only letters, digits, - and _ in the name.');
  const img = exportImage();
  return { name, img, text: worldText(name, img.ext) };
}

function result(html) { $('saveResult').innerHTML = html; }
const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

async function save(overwrite = false) {
  let p;
  try { p = prepare(); } catch (err) { result(`<span class="error">${esc(err.message)}</span>`); return; }
  result('Saving…');
  const res = await fetch('/api/save-world', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: p.name, text: p.text, image_ext: p.img.ext,
      image_b64: p.img.dataUrl.split(',')[1], overwrite }),
  }).catch((err) => ({ ok: false, status: 0, json: async () => ({ error: String(err) }) }));
  const out = await res.json().catch(() => ({}));
  if (res.status === 409) {
    result(`<span class="error">${esc(out.files.join(' and '))} already exist${out.files.length > 1 ? '' : 's'}.</span> ` +
      '<button id="overwrite">Overwrite</button>');
    $('overwrite').addEventListener('click', () => save(true));
    return;
  }
  if (!res.ok) {
    result(`<span class="error">Could not save: ${esc(out.error || 'is cfsim still running?')}</span> ` +
      'Use <b>Download</b> instead.');
    return;
  }
  result(`Saved ${esc(out.files.join(' and '))} in\n<code>${esc(out.folder)}</code>\n\nFly in it:\n` +
    `<code>python -m cfsim --viewer browser --world ${esc(p.name)}.txt my_script.py</code>`);
}

function download() {
  let p;
  try { p = prepare(); } catch (err) { result(`<span class="error">${esc(err.message)}</span>`); return; }
  const links = [[URL.createObjectURL(new Blob([p.text], { type: 'text/plain' })), p.name + '.txt'],
    [p.img.dataUrl, `${p.name}.${p.img.ext}`]];
  for (const [href, file] of links) {
    const a = document.createElement('a');
    a.href = href;
    a.download = file;
    a.click();
  }
  result(`Downloaded ${esc(p.name)}.txt and ${esc(p.name)}.${p.img.ext}. Keep both files in the same ` +
    `folder, then:\n<code>python -m cfsim --viewer browser --world ${esc(p.name)}.txt my_script.py</code>`);
}

$('save').addEventListener('click', () => save(false));
$('download').addEventListener('click', download);

setTool(null);
steps();
