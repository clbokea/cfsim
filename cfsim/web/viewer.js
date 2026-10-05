// cfsim browser view: draws the world and the drones with three.js.
// The simulator sends the same JSON messages as to the window viewer
// (world / state / msg / end) as Server-Sent Events on /events.
//
// Coordinates: the simulator uses x right, y "up on the map", z up.
// three.js uses y up, so a simulator point (x, y, z) is drawn at (x, z, -y).
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const $ = (id) => document.getElementById(id);
const P = (x, y, z) => new THREE.Vector3(x, z, -y);
const RAD = Math.PI / 180;
const TRAIL_MAX = 3000;
const RAYS = { front: 0, left: 90, back: 180, right: -90 };

// ------------------------------------------------------------------ scene
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
$('view').appendChild(renderer.domElement);

const scene = new THREE.Scene();
const css = getComputedStyle(document.documentElement);
scene.background = new THREE.Color(css.getPropertyValue('--bg').trim() || '#f4f5f7');
const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;

// 3D and Follow use a perspective camera; Top uses an orthographic camera,
// so the top view is a true map (no perspective) that matches the floor plan.
const perspCam = new THREE.PerspectiveCamera(50, 1, 0.02, 500);
const orthoCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 500);
let camera = perspCam;
let controls = makeControls(perspCam);

function makeControls(cam) {
  const c = new OrbitControls(cam, renderer.domElement);
  c.enableDamping = true;
  if (cam === orthoCam) {
    c.enableRotate = false;          // a map: only move and zoom
    c.screenSpacePanning = true;
    c.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
  }
  return c;
}

scene.add(new THREE.HemisphereLight(0xffffff, 0x8890a0, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(4, 10, 6);
scene.add(sun);

let worldGroup = null;          // everything that belongs to the current world
let world = null;
let session = null;
let span = 6;                   // size of the world in metres (for the camera)
const drones = new Map();       // id -> {group, body, trail, rays, card, ...}
const show = { trails: true, rays: true, plan: true, walls: true };
let camMode = '3d';
let ended = false;
let lastState = null;

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h);
  perspCam.aspect = w / h;
  perspCam.updateProjectionMatrix();
  fitOrtho();
}
window.addEventListener('resize', resize);
resize();

// ------------------------------------------------------------------ world
function buildWorld(w) {
  if (worldGroup) {
    scene.remove(worldGroup);
    worldGroup.traverse((o) => { o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose?.(); });
  }
  for (const d of drones.values()) { scene.remove(d.group, d.trail, d.rays, d.stalk); d.card.remove(); }
  drones.clear();

  world = w;
  worldGroup = new THREE.Group();
  const [xmin, xmax, ymin, ymax] = w.bounds;
  const cx = (xmin + xmax) / 2, cy = (ymin + ymax) / 2;
  span = Math.max(xmax - xmin, ymax - ymin, 2);
  const h = w.height;

  // Floor
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(xmax - xmin, ymax - ymin),
    new THREE.MeshStandardMaterial({ color: dark ? 0x2a2f38 : 0xeceef2, roughness: 1 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.copy(P(cx, cy, 0));
  worldGroup.add(floor);
  const grid = new THREE.GridHelper(Math.ceil(span) + 2, Math.ceil(span) + 2,
    dark ? 0x4a5160 : 0xc3c8d0, dark ? 0x353b46 : 0xd9dde3);
  grid.position.copy(P(cx, cy, 0.002));
  worldGroup.add(grid);

  // Floor plan image (worlds made with the room editor)
  $('planBtn').hidden = !w.image;
  if (w.image) {
    const [x1, y1, x2, y2] = w.image_box;
    const tex = new THREE.TextureLoader().load('/world-image?s=' + session);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    const plan = new THREE.Mesh(new THREE.PlaneGeometry(x2 - x1, y2 - y1),
      new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: dark ? 0.75 : 0.95 }));
    plan.rotation.x = -Math.PI / 2;
    plan.position.copy(P((x1 + x2) / 2, (y1 + y2) / 2, 0.004));
    plan.name = 'plan';
    plan.visible = show.plan;
    worldGroup.add(plan);
  }

  // Walls: one instanced box per wall box, plus their outline on top
  if (w.boxes.length) {
    const mat = new THREE.MeshStandardMaterial({
      color: dark ? 0x7d8796 : 0xaab2be, roughness: 0.9, transparent: true, opacity: 0.35,
      depthWrite: false });
    const walls = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, w.boxes.length);
    const m = new THREE.Matrix4();
    const tops = [];
    w.boxes.forEach(([x1, y1, x2, y2], i) => {
      m.compose(P((x1 + x2) / 2, (y1 + y2) / 2, h / 2), new THREE.Quaternion(),
        new THREE.Vector3(x2 - x1, h, y2 - y1));
      walls.setMatrixAt(i, m);
      const c = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
      for (let k = 0; k < 4; k++) {
        const [ax, ay] = c[k], [bx, by] = c[(k + 1) % 4];
        tops.push(...P(ax, ay, h).toArray(), ...P(bx, by, h).toArray());
        tops.push(...P(ax, ay, 0.01).toArray(), ...P(bx, by, 0.01).toArray());
      }
    });
    walls.name = 'walls';
    worldGroup.add(walls);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(tops, 3));
    const outline = new THREE.LineSegments(g, new THREE.LineBasicMaterial({
      color: dark ? 0xaeb6c4 : 0x5c6672 }));
    outline.name = 'outline';
    worldGroup.add(outline);
  }

  // Radio beacon and start spots
  const beacon = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.16, 16),
    new THREE.MeshStandardMaterial({ color: 0x2a9d8f }));
  beacon.position.copy(P(w.beacon[0], w.beacon[1], 0.08));
  worldGroup.add(beacon);
  for (const [sx, sy] of w.starts || []) {
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.1, 0.13, 32),
      new THREE.MeshBasicMaterial({ color: 0x3949ab, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.copy(P(sx, sy, 0.006));
    worldGroup.add(ring);
  }

  scene.add(worldGroup);
  applyToggles();
  $('world').textContent = `world '${w.name}'`;
  setCamera(camMode, true);
}

// ----------------------------------------------------------------- drones
function droneScale() { return Math.min(4, Math.max(2, span / 3)); }

function makeDrone(d) {
  const color = new THREE.Color(d.color);
  const group = new THREE.Group();
  const bodyMat = new THREE.MeshStandardMaterial({ color, roughness: 0.6 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.02, 0.05), bodyMat);
  group.add(body);
  const armMat = new THREE.MeshStandardMaterial({ color: 0x30343c });
  const rotorMat = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.55 });
  for (const a of [45, 135]) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.008, 0.01), armMat);
    arm.rotation.y = a * RAD;
    group.add(arm);
  }
  for (const a of [45, 135, 225, 315]) {
    const rotor = new THREE.Mesh(new THREE.CylinderGeometry(0.023, 0.023, 0.004, 20), rotorMat);
    rotor.position.set(0.065 * Math.cos(a * RAD), 0.008, -0.065 * Math.sin(a * RAD));
    group.add(rotor);
  }
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.012, 0.04, 12),
    new THREE.MeshStandardMaterial({ color: 0xd62828 }));
  nose.rotation.z = -Math.PI / 2;          // points along +x = the drone's front
  nose.position.set(0.045, 0, 0);
  group.add(nose);
  group.rotation.order = 'YZX';
  group.scale.setScalar(droneScale());
  scene.add(group);

  // vertical line to the floor + a dot on the floor: shows the height
  const stalkGeom = new THREE.BufferGeometry();
  stalkGeom.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(6), 3));
  const stalk = new THREE.LineSegments(stalkGeom, new THREE.LineBasicMaterial({
    color, transparent: true, opacity: 0.5 }));
  scene.add(stalk);

  const trailGeom = new THREE.BufferGeometry();
  trailGeom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TRAIL_MAX * 3), 3));
  trailGeom.setDrawRange(0, 0);
  const trail = new THREE.Line(trailGeom, new THREE.LineBasicMaterial({ color }));
  trail.frustumCulled = false;
  scene.add(trail);

  const rayGeom = new THREE.BufferGeometry();
  rayGeom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6 * 2 * 3), 3));
  const rays = new THREE.LineSegments(rayGeom, new THREE.LineBasicMaterial({
    color: 0x2a9d8f, transparent: true, opacity: 0.8 }));
  rays.frustumCulled = false;
  scene.add(rays);

  const card = document.createElement('div');
  card.className = 'card drone';
  $('drones').appendChild(card);

  const obj = { group, body, bodyMat, color, stalk, trail, trailN: 0, rays, card,
    target: null, yaw: 0, roll: 0, pitch: 0 };
  drones.set(d.id, obj);
  return obj;
}

function setTrail(o, pts) {
  const arr = o.trail.geometry.attributes.position.array;
  const start = Math.max(0, pts.length - TRAIL_MAX);
  let n = 0;
  for (let i = start; i < pts.length; i++, n++) {
    const [x, y, z] = pts[i];
    arr[n * 3] = x; arr[n * 3 + 1] = z; arr[n * 3 + 2] = -y;
  }
  o.trailN = n;
  o.trail.geometry.setDrawRange(0, n);
  o.trail.geometry.attributes.position.needsUpdate = true;
}

function extendTrail(o, x, y, z) {
  const arr = o.trail.geometry.attributes.position.array;
  const n = o.trailN;
  if (n > 0) {
    const dx = arr[(n - 1) * 3] - x, dy = arr[(n - 1) * 3 + 1] - z, dz = arr[(n - 1) * 3 + 2] + y;
    if (dx * dx + dy * dy + dz * dz < 0.03 * 0.03) return;
  }
  if (n >= TRAIL_MAX) {                     // full: drop the oldest point
    arr.copyWithin(0, 3);
    o.trailN = n - 1;
  }
  const k = o.trailN;
  arr[k * 3] = x; arr[k * 3 + 1] = z; arr[k * 3 + 2] = -y;
  o.trailN = k + 1;
  o.trail.geometry.setDrawRange(0, o.trailN);
  o.trail.geometry.attributes.position.needsUpdate = true;
}

function setRays(o, d) {
  const arr = o.rays.geometry.attributes.position.array;
  arr.fill(0);
  const r = d.ranges;
  if (!r) { o.rays.geometry.attributes.position.needsUpdate = true; return; }
  let k = 0;
  const seg = (a, b) => { arr.set(a.toArray(), k); arr.set(b.toArray(), k + 3); k += 6; };
  const from = P(d.x, d.y, d.z);
  for (const [name, ang] of Object.entries(RAYS)) {
    const dist = r[name];
    if (dist == null) continue;
    const a = (d.yaw + ang) * RAD;
    seg(from, P(d.x + dist * Math.cos(a), d.y + dist * Math.sin(a), d.z));
  }
  if (r.up != null) seg(from, P(d.x, d.y, d.z + r.up));
  if (r.zrange != null) seg(from, P(d.x, d.y, Math.max(0, d.z - r.zrange)));
  o.rays.geometry.attributes.position.needsUpdate = true;
}

function updateCard(o, d) {
  const status = d.crashed ? '<span class="badge bad">crashed</span>'
    : d.motors ? '<span class="badge">flying</span>' : '<span class="badge">on the ground</span>';
  o.card.classList.toggle('crashed', d.crashed);
  o.card.innerHTML = `
    <div><span class="swatch" style="background:${d.color}"></span><span class="name">${d.label}</span>
      ${status}</div>
    <div class="muted small">${d.model}</div>
    <div class="grid">
      <span class="muted">x, y, z</span><span>${d.x.toFixed(2)}, ${d.y.toFixed(2)}, ${d.z.toFixed(2)} m</span>
      <span class="muted">yaw</span><span>${d.yaw.toFixed(0)}°</span>
      <span class="muted">battery</span><span>${d.vbat.toFixed(2)} V</span>
    </div>`;
}

let cardTime = 0;
function onState(msg) {
  lastState = msg;
  $('clock').textContent = `t = ${msg.t.toFixed(1)} s`;
  const now = performance.now();
  const cards = now - cardTime > 200;
  if (cards) cardTime = now;
  for (const d of msg.drones) {
    const o = drones.get(d.id) || makeDrone(d);
    o.target = P(d.x, d.y, d.z);
    if (!o.group.visible || o.group.position.lengthSq() === 0) o.group.position.copy(o.target);
    o.yaw = d.yaw; o.roll = d.roll; o.pitch = d.pitch;
    o.bodyMat.color.set(d.crashed ? 0xd62828 : o.color);
    if (msg.trails && msg.trails[d.id]) setTrail(o, msg.trails[d.id]);
    else extendTrail(o, d.x, d.y, d.z);
    setRays(o, d);
    const s = o.stalk.geometry.attributes.position.array;
    s.set([d.x, d.z, -d.y, d.x, 0, -d.y]);
    o.stalk.geometry.attributes.position.needsUpdate = true;
    if (cards) updateCard(o, d);
  }
  $('waiting').hidden = true;
  applyToggles();
}

// ----------------------------------------------------------------- camera
function fitOrtho() {
  const aspect = window.innerWidth / window.innerHeight;
  const half = (world ? Math.max((world.bounds[1] - world.bounds[0]) / aspect,
    world.bounds[3] - world.bounds[2]) : span) * 0.6;
  orthoCam.left = -half * aspect; orthoCam.right = half * aspect;
  orthoCam.top = half; orthoCam.bottom = -half;
  orthoCam.updateProjectionMatrix();
}

function useCamera(cam) {
  if (camera === cam) return;
  controls.dispose();
  camera = cam;
  controls = makeControls(cam);
}

function setCamera(mode, reset = false) {
  camMode = mode;
  document.querySelectorAll('[data-cam]').forEach((b) => b.classList.toggle('on', b.dataset.cam === mode));
  if (!world) return;
  const [xmin, xmax, ymin, ymax] = world.bounds;
  const c = P((xmin + xmax) / 2, (ymin + ymax) / 2, 0);
  useCamera(mode === 'top' ? orthoCam : perspCam);
  $('help').textContent = mode === 'top' ? 'Drag: move · Wheel: zoom'
    : 'Drag: rotate · Right-drag: move · Wheel: zoom';
  if (mode === 'top') {
    fitOrtho();
    orthoCam.zoom = 1;
    orthoCam.updateProjectionMatrix();
    controls.target.copy(c);
    camera.position.set(c.x, span * 3, c.z + 0.0001);
  } else if (mode === '3d' || reset) {
    controls.target.copy(c);
    camera.position.set(c.x + span * 0.5, span * 1.0, c.z + span * 1.25);
  }
  controls.update();
}
document.querySelectorAll('[data-cam]').forEach((b) =>
  b.addEventListener('click', () => setCamera(b.dataset.cam)));

function applyToggles() {
  for (const o of drones.values()) {
    o.trail.visible = show.trails;
    o.rays.visible = show.rays;
  }
  if (worldGroup) {
    const plan = worldGroup.getObjectByName('plan');
    if (plan) plan.visible = show.plan;
    for (const n of ['walls', 'outline']) {
      const w = worldGroup.getObjectByName(n);
      if (w) w.visible = show.walls;
    }
  }
}
document.querySelectorAll('[data-toggle]').forEach((b) =>
  b.addEventListener('click', () => {
    show[b.dataset.toggle] = !show[b.dataset.toggle];
    b.classList.toggle('on', show[b.dataset.toggle]);
    applyToggles();
  }));

// ---------------------------------------------------------- render loop
function animate() {
  requestAnimationFrame(animate);
  for (const o of drones.values()) {
    if (!o.target) continue;
    o.group.position.lerp(o.target, 0.35);
    o.group.rotation.set(-o.roll * RAD, o.yaw * RAD, o.pitch * RAD);
  }
  if (camMode === 'follow' && drones.size) {
    const first = drones.values().next().value;
    const delta = first.group.position.clone().sub(controls.target).multiplyScalar(0.1);
    controls.target.add(delta);
    camera.position.add(delta);
  }
  controls.update();
  renderer.render(scene, camera);
}
animate();

// ------------------------------------------------------------- messages
function setStatus(kind, text) {
  $('dot').className = 'status-dot ' + kind;
  $('status').textContent = text;
}

function showMessages(list) {
  $('msgs').innerHTML = '';
  for (const t of list) {
    const div = document.createElement('div');
    div.className = 'card';
    div.textContent = t;
    $('msgs').appendChild(div);
  }
}

let msgs = [];
const events = new EventSource('/events');
events.onopen = () => { if (!ended) setStatus('live', 'live'); };
events.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === 'world') {
    if (msg.session !== session) {
      session = msg.session;
      ended = false;
      msgs = [];
      showMessages(msgs);
      buildWorld(msg.world);
      setStatus('live', 'live');
    }
  } else if (msg.type === 'state') {
    onState(msg);
  } else if (msg.type === 'msg') {
    msgs = [...msgs, msg.text].slice(-3);
    showMessages(msgs);
  } else if (msg.type === 'end') {
    ended = true;
    setStatus('ended', 'script finished – run it again and this page updates');
  }
};
events.onerror = () => {
  if (ended) setStatus('ended', 'script finished – run it again and this page updates');
  else if (session) setStatus('lost', 'connection lost – is the script still running?');
};
