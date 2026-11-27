// perfusion1 walk-around sim lab client. Talks to perfusion/server.py over plain HTTP.
import * as THREE from 'three';
import { buildPanels } from './panels.js';
import { initSmash } from './smash.js';
import { buildAvatar } from './player.js';
import { initSaves } from './saves.js';
import { initGame } from './game.js';
import { recordTrend } from './panels.js';
import { initGfx, pickTier } from './gfx.js';
import { buildConsole } from './console.js';
import { MON_W, MON_H, sampleWaves, drawMonitor } from './monitor.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { initHelp } from './help.js';
import { trendCharts } from './charts.js';

const $ = (id) => document.getElementById(id);
const STATE_URL = '/api/state?c=' + Math.random().toString(36).slice(2, 10);   // per-tab id, so /dashboard can count connected clients
const post = (p, body) => fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then((r) => r.json());
export const act = (a) => post('/api/action', a);
export const state = { S: null, META: null };

// ---------------------------------------------------------------- renderer
const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
const TIER = pickTier(), HQ = TIER !== 'low', GLASS = TIER === 'high';   // materials are built for the starting tier
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.92;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1a1f26);
const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 60);
scene.add(camera);   // so things held in the hand (smash mode bat) render
// y: feet above the floor (jumping); h: eye height above the feet (crouching); view: 0 first person, 1 behind, 2 in front
const player = { x: 0.9, z: 1.6, yaw: 0.72, pitch: -0.16, h: 1.65, y: 0, vy: 0, view: 0, crouch: 0, speed: 0, sprint: false };
const EYE = 1.65, EYE_CROUCH = 1.28, GRAVITY = 24, JUMP_V = 5.4;          // jump apex about 0.6 m
const WALK = 2.3, SPRINT = 4.2, SNEAK = 0.75, FOV = 70, FOV_SPRINT = 78;

const gfx = initGfx({ renderer, scene, camera, tier: TIER, onTier: (t) => { const b = $('btn-gfx'); if (b) b.textContent = 'Graphics: ' + t; } });
function resize() {
  gfx.resize(window.innerWidth, window.innerHeight);
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();
$('btn-gfx').textContent = 'Graphics: ' + gfx.tier;
$('btn-gfx').onclick = () => gfx.next();

// ---------------------------------------------------------------- helpers
const mat = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.05, ...o });
function add(parent, geo, material, x = 0, y = 0, z = 0, shadow = true) {
  const m = new THREE.Mesh(geo, material);
  m.position.set(x, y, z);
  m.castShadow = shadow; m.receiveShadow = true;
  parent.add(m);
  return m;
}
// boxes get softened edges on the better tiers: it is what stops everything reading as a crate
function boxGeo(w, h, d) {
  const s = Math.min(w, h, d);
  return HQ && s >= 0.05 && Math.max(w, h, d) <= 2.6 ? new RoundedBoxGeometry(w, h, d, 2, Math.min(0.03, s * 0.22)) : new THREE.BoxGeometry(w, h, d);
}
const box = (p, w, h, d, m, x, y, z) => add(p, boxGeo(w, h, d), m, x, y, z);
// clear plastic: real refraction on the high tier, plain transparency elsewhere
const glass = (color, opacity, o = {}) => (GLASS
  ? new THREE.MeshPhysicalMaterial({ color, transmission: 1, thickness: 0.02, ior: 1.5, roughness: 0.05, metalness: 0, envMapIntensity: 1.4, ...o })
  : mat(color, { transparent: true, opacity, roughness: 0.08, depthWrite: false, ...o }));
const cyl = (p, rt, rb, h, m, x, y, z, seg = 28) => add(p, new THREE.CylinderGeometry(rt, rb, h, seg), m, x, y, z);
function canvasTex(w, h) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return { c, ctx: c.getContext('2d'), t };
}
function screen(parent, w, h, px, py, x, y, z) {
  const s = canvasTex(px, py);
  s.mesh = add(parent, new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: s.t, toneMapped: false }), x, y, z, false);
  return s;
}
const lerp = (a, b, t) => a + (b - a) * Math.min(1, Math.max(0, t));
const fmt = (v, d = 0) => (v === null || v === undefined ? '--' : Number(v).toFixed(d));
export const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

// ---------------------------------------------------------------- room
const ROOM = { x0: -7, x1: 7, z0: -5, z1: 5, h: 3.1 };
const obstacles = [];      // [x0, x1, z0, z1]
const block = (x0, x1, z0, z1) => obstacles.push([x0, x1, z0, z1]);

(function buildRoom() {
  // wood floor
  const f = canvasTex(1024, 1024), g = f.ctx;
  for (let row = 0; row < 16; row++) {
    let x = -((row * 137) % 200);
    while (x < 1024) {
      const len = 180 + ((row * 53 + x) % 140), l = 44 + ((row * 31 + x * 7) % 14);
      g.fillStyle = `hsl(28, 48%, ${l}%)`;
      g.fillRect(x, row * 64, len - 2, 62);
      g.fillStyle = 'rgba(60,30,10,0.10)';
      for (let k = 0; k < 6; k++) g.fillRect(x, row * 64 + 6 + k * 10 + ((x + k) % 5), len - 2, 1);
      x += len;
    }
  }
  f.t.wrapS = f.t.wrapT = THREE.RepeatWrapping; f.t.repeat.set(3.5, 2.5);
  const floor = add(scene, new THREE.PlaneGeometry(14, 10), mat(0xd6cfc6, { map: f.t, roughness: 0.36, envMapIntensity: 0.6 }), 0, 0, 0, false);
  floor.rotation.x = -Math.PI / 2;
  // ceiling tiles with light panels
  const c = canvasTex(512, 512), cg = c.ctx;
  cg.fillStyle = '#e9e9e4'; cg.fillRect(0, 0, 512, 512);
  cg.strokeStyle = '#c9c9c2'; cg.lineWidth = 3;
  for (let i = 0; i <= 4; i++) { cg.beginPath(); cg.moveTo(i * 128, 0); cg.lineTo(i * 128, 512); cg.moveTo(0, i * 128); cg.lineTo(512, i * 128); cg.stroke(); }
  c.t.wrapS = c.t.wrapT = THREE.RepeatWrapping; c.t.repeat.set(5, 3.5);
  const ceil = add(scene, new THREE.PlaneGeometry(14, 10), mat(0xffffff, { map: c.t }), 0, ROOM.h, 0, false);
  ceil.rotation.x = Math.PI / 2;
  const lightMat = new THREE.MeshBasicMaterial({ color: 0xfffdf2 }), bezel = mat(0xc9ccc8, { metalness: 0.3, roughness: 0.5 });
  for (const lx of [-4.5, -1.5, 1.5, 4.5]) for (const lz of [-3, 0, 3]) {    // recessed LED panels
    const p = add(scene, new THREE.PlaneGeometry(1.12, 0.52), lightMat, lx, ROOM.h - 0.012, lz, false);
    p.rotation.x = Math.PI / 2;
    const b = add(scene, new THREE.PlaneGeometry(1.22, 0.62), bezel, lx, ROOM.h - 0.008, lz, false); b.rotation.x = Math.PI / 2;
  }
  // walls
  const wall = mat(0xe6e2d8), navy = mat(0x1d2c4d), trim = mat(0xb9a98a);
  box(scene, 14, ROOM.h, 0.1, wall, 0, ROOM.h / 2, -5.05);
  box(scene, 14, ROOM.h, 0.1, wall, 0, ROOM.h / 2, 5.05);
  box(scene, 0.1, ROOM.h, 10, wall, -7.05, ROOM.h / 2, 0);
  box(scene, 0.1, ROOM.h, 10, wall, 7.05, ROOM.h / 2, 0);
  box(scene, 14, 0.12, 0.04, trim, 0, 0.06, -4.98);
  // control room: navy panels and a glass window with glowing monitors, like the lab in the video
  box(scene, 5.2, 1.5, 0.06, navy, -3.6, 1.75, -4.97);
  const glass = mat(0x9fc4d8, { transparent: true, opacity: 0.25, roughness: 0.1, metalness: 0.3 });
  box(scene, 3.6, 1.1, 0.03, glass, -3.6, 1.75, -4.92);
  for (let i = 0; i < 3; i++) {
    const m = screen(scene, 0.7, 0.42, 256, 160, -4.8 + i * 1.2, 1.7, -4.9);
    const x = m.ctx; x.fillStyle = '#04121c'; x.fillRect(0, 0, 256, 160);
    ['#39d98a', '#ff5a5a', '#5ab0ff', '#ffd24d'].forEach((col, k) => {
      x.strokeStyle = col; x.lineWidth = 2; x.beginPath();
      for (let px = 0; px < 256; px++) { const y = 26 + k * 36 + Math.sin(px / (5 + k * 2) + i) * 8 * ((px % 50) < 12 ? 1.6 : 0.4); px ? x.lineTo(px, y) : x.moveTo(px, y); }
      x.stroke();
    });
    m.t.needsUpdate = true;
  }
  // a second, idle pump station and chairs for the lab feel
  const steel = mat(0x9aa3ad, { metalness: 0.6, roughness: 0.35 }), chairM = mat(0x2a3a5c), white = mat(0xeef0f2);
  for (const [cx, cz] of [[-5.2, 2.6], [5.4, 2.8]]) {
    box(scene, 0.9, 0.22, 0.55, mat(0x3b4a66), cx, 0.2, cz);
    cyl(scene, 0.025, 0.025, 2.0, steel, cx - 0.3, 1.2, cz - 0.15);
    box(scene, 0.3, 0.34, 0.12, white, cx + 0.15, 1.2, cz);
    cyl(scene, 0.15, 0.11, 0.3, mat(0xf2c230, { transparent: true, opacity: 0.8 }), cx - 0.05, 0.85, cz + 0.1);
    block(cx - 0.6, cx + 0.6, cz - 0.45, cz + 0.45);
  }
  for (const [cx, cz, r] of [[-0.75, 0.55, 0.15], [-5.0, 3.6, 2.4], [5.6, 3.8, -2.2], [0.8, 3.9, 3.0]]) {
    const ch = new THREE.Group(); ch.position.set(cx, 0, cz); ch.rotation.y = r; scene.add(ch);
    box(ch, 0.46, 0.06, 0.46, chairM, 0, 0.48, 0); box(ch, 0.46, 0.5, 0.06, chairM, 0, 0.78, -0.22);
    cyl(ch, 0.03, 0.03, 0.45, steel, 0, 0.24, 0); cyl(ch, 0.26, 0.26, 0.03, steel, 0, 0.03, 0);
  }
  // supply bins along the wall
  for (let i = 0; i < 4; i++) box(scene, 0.7, 0.3, 0.45, white, 1.0 + i * 0.85, 0.15, 4.5);
  // lights
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a7a66, 0.34));
  gfx.fill = new THREE.HemisphereLight(0xffffff, 0x9a8a76, scene.environment ? 0 : 0.5); scene.add(gfx.fill);   // stands in for image-based light on the low tier
  const sun = new THREE.DirectionalLight(0xfff4e0, 0.95);
  sun.position.set(2.5, 6, 3.5); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: 0.5, far: 20 });
  sun.shadow.bias = -0.0005;
  scene.add(sun);
  const fill = new THREE.PointLight(0xfff0d8, 5, 9); fill.position.set(1, 2.8, -1); scene.add(fill);
  // set dressing: door, wall clock, baseboards
  const doorM = mat(0x8c6a4a, { roughness: 0.6 }), frameM = mat(0xd8d2c4);
  box(scene, 0.06, 2.1, 1.0, doorM, 6.99, 1.05, 2.6); box(scene, 0.08, 2.2, 0.08, frameM, 6.98, 1.1, 2.06); box(scene, 0.08, 2.2, 0.08, frameM, 6.98, 1.1, 3.14);
  box(scene, 0.08, 0.08, 1.16, frameM, 6.98, 2.2, 2.6); cyl(scene, 0.02, 0.02, 0.12, mat(0xb9bec4, { metalness: 0.8, roughness: 0.3 }), 6.93, 1.0, 2.25).rotation.z = Math.PI / 2;
  for (const [bx, bz, bw, bd] of [[0, 4.98, 14, 0.04], [-6.98, 0, 0.04, 10], [6.98, -1.2, 0.04, 6.4]]) box(scene, bw, 0.12, bd, trim, bx, 0.06, bz);
  const clock = cyl(scene, 0.17, 0.17, 0.03, mat(0xf4f4f0), -0.4, 2.45, -4.98, 36); clock.rotation.x = Math.PI / 2;
  cyl(scene, 0.18, 0.18, 0.02, mat(0x22262b), -0.4, 2.45, -4.99, 36).rotation.x = Math.PI / 2;
  box(scene, 0.012, 0.11, 0.006, mat(0x111111), -0.4, 2.49, -4.96); box(scene, 0.09, 0.012, 0.006, mat(0x111111), -0.36, 2.45, -4.96);
})();

// ---------------------------------------------------------------- tubing
const flowTex = (() => {
  const t = canvasTex(64, 4), g = t.ctx;
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, 64, 4);
  g.fillStyle = '#b9b9b9'; g.fillRect(0, 0, 18, 4);
  t.t.wrapS = t.t.wrapT = THREE.RepeatWrapping;
  return t.t;
})();
const tubes = {};
function tube(name, pts, r = 0.013) {
  const curve = new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(...p)));
  const map = flowTex.clone(); map.needsUpdate = true; map.repeat.set(Math.round(curve.getLength() * 9), 1);
  const tm = HQ ? new THREE.MeshPhysicalMaterial({ color: 0xe8a0a8, map, roughness: 0.22, clearcoat: 1, clearcoatRoughness: 0.08, transparent: true, opacity: 0.95 })
    : mat(0xe8a0a8, { map, roughness: 0.3, transparent: true, opacity: 0.92 });
  const m = add(scene, new THREE.TubeGeometry(curve, 96, r, 14), tm);
  (tubes[name] = tubes[name] || []).push({ m, map });
}
const PRIME = new THREE.Color(0xf0a6ae), DARK = new THREE.Color(0x5a0c1c), BRIGHT = new THREE.Color(0xe01f2d), PLEGE = new THREE.Color(0xd9722a);
function paintTubes(name, color, speed, dt) {
  for (const t of tubes[name] || []) { t.m.material.color.lerp(color, 0.08); t.map.offset.x -= speed * dt; }
}

// ---------------------------------------------------------------- heart-lung machine
const CART = new THREE.Vector3(-1.0, 0, -0.6);
const hlm = new THREE.Group(); hlm.position.copy(CART); scene.add(hlm);
const P = {};  // animated parts
// local point on the cart -> world [x, y, z], for tubing that has to meet the parts on it
const L = (x, y, z) => [CART.x + x, y, CART.z + z];
const RES = { x: 0.6, y: 1.15, z: 0.26 };          // venous reservoir centre on the cart
let consoleUI = null;
(function buildCart() {
  const steel = mat(0xaab2bb, { metalness: 0.7, roughness: 0.3 }), white = mat(0xf1f3f5, { roughness: 0.4 }), black = mat(0x15181c);
  consoleUI = buildConsole({ hlm, mat, box, cyl, add, screen, glass, text });
  // cardioplegia bags on the top bar, red-dyed like the lab
  const bag = mat(0xd8344a, { transparent: true, opacity: 0.72, roughness: 0.2 });
  for (const bx of [-0.36, -0.14]) {
    box(hlm, 0.15, 0.28, 0.035, bag, bx, 2.05, -0.22);
    box(hlm, 0.15, 0.08, 0.035, mat(0xffffff, { transparent: true, opacity: 0.35 }), bx, 2.23, -0.22);
  }
  // data screen at the top of the mast
  P.central = screen(hlm, 0.5, 0.306, 640, 392, -0.1, 1.93, -0.16);
  P.central.mesh.rotation.x = -0.12;
  box(hlm, 0.54, 0.34, 0.03, black, -0.1, 1.93, -0.18).rotation.x = -0.12;
  // gas blender + vaporizer on their own short pole
  cyl(hlm, 0.018, 0.018, 1.3, steel, 0.3, 1.03, -0.25);
  box(hlm, 0.16, 0.24, 0.1, mat(0x8fa3b8), 0.3, 1.6, -0.14);
  cyl(hlm, 0.022, 0.022, 0.03, black, 0.26, 1.63, -0.08).rotation.x = Math.PI / 2;
  cyl(hlm, 0.022, 0.022, 0.03, black, 0.34, 1.63, -0.08).rotation.x = Math.PI / 2;
  cyl(hlm, 0.045, 0.045, 0.14, mat(0x7a3fb0), 0.3, 1.38, -0.14);
  // venous reservoir on its holder: yellow lid, clear shell, yellow filter, fluid
  cyl(hlm, 0.018, 0.018, 1.0, steel, RES.x + 0.12, 0.88, RES.z - 0.22);
  box(hlm, 0.04, 0.03, 0.24, black, RES.x + 0.12, RES.y - 0.15, RES.z - 0.11);
  const tor = add(hlm, new THREE.TorusGeometry(0.165, 0.014, 10, 40), black, RES.x, RES.y - 0.15, RES.z); tor.rotation.x = Math.PI / 2;
  cyl(hlm, 0.168, 0.168, 0.06, mat(0xf2c21a, { roughness: 0.35 }), RES.x, RES.y + 0.18, RES.z);
  for (let i = 0; i < 6; i++) cyl(hlm, 0.012, 0.012, 0.04, mat(i % 2 ? 0x2f6fd1 : 0xffffff), RES.x + Math.cos(i) * 0.1, RES.y + 0.23, RES.z + Math.sin(i) * 0.1);
  const shell = glass(0xeaf3fa, 0.22, GLASS ? {} : { side: THREE.DoubleSide });
  cyl(hlm, 0.155, 0.12, 0.3, shell, RES.x, RES.y, RES.z);
  cyl(hlm, 0.12, 0.03, 0.12, shell, RES.x, RES.y - 0.21, RES.z);
  cyl(hlm, 0.07, 0.07, 0.26, mat(0xf2c21a, GLASS ? { roughness: 0.5 } : { transparent: true, opacity: 0.55 }), RES.x, RES.y + 0.02, RES.z);
  const bloodM = () => mat(0xb01828, GLASS ? { roughness: 0.12 } : { transparent: true, opacity: 0.85, roughness: 0.15 });
  P.fluid = cyl(hlm, 0.148, 0.118, 0.3, bloodM(), RES.x, RES.y, RES.z);
  P.fluidTip = cyl(hlm, 0.116, 0.03, 0.115, bloodM(), RES.x, RES.y - 0.21, RES.z);
  // oxygenator (white drum, clear end) below the reservoir
  const ox = cyl(hlm, 0.1, 0.1, 0.22, white, 0.6, 0.66, 0.38); ox.rotation.z = Math.PI / 2;
  P.oxyCap = cyl(hlm, 0.102, 0.102, 0.06, mat(0xe9a6ae, { transparent: true, opacity: 0.7 }), 0.74, 0.66, 0.38); P.oxyCap.rotation.z = Math.PI / 2;
  box(hlm, 0.2, 0.03, 0.08, steel, 0.6, 0.53, 0.3);
  // centrifugal pump head on a bracket: blue drive, clear cone, spinning impeller
  box(hlm, 0.12, 0.03, 0.12, steel, 0.42, 0.37, 0.36);
  cyl(hlm, 0.075, 0.075, 0.16, mat(0x5b84b8, { roughness: 0.4 }), 0.42, 0.46, 0.4);
  cyl(hlm, 0.03, 0.075, 0.08, glass(0xf0f4f8, 0.35), 0.42, 0.58, 0.4);
  P.impeller = new THREE.Group(); P.impeller.position.set(0.42, 0.56, 0.4); hlm.add(P.impeller);
  for (let i = 0; i < 4; i++) { const b = box(P.impeller, 0.11, 0.025, 0.012, mat(0xc0283a), 0, 0, 0); b.rotation.y = (i * Math.PI) / 4; }
  // alarm beacon on top of the centrifugal console mast
  P.beacon = add(hlm, new THREE.SphereGeometry(0.035, 16, 12), new THREE.MeshBasicMaterial({ color: 0x402020 }), -0.66, 1.54, -0.22, false);
  P.beaconLight = new THREE.PointLight(0xff2020, 0, 4); P.beaconLight.position.set(-0.66, 1.6, -0.22); hlm.add(P.beaconLight);
  // clamps on the lines
  P.venClamp = box(scene, 0.03, 0.09, 0.05, steel, -0.15, 0.92, -0.5);
  P.artClamp = box(scene, 0.03, 0.09, 0.05, steel, -0.16, 0.56, -0.28);
  block(CART.x - 0.78, CART.x + 0.82, CART.z - 0.36, CART.z + 0.47);
})();

// heater-cooler
const hc = new THREE.Group(); hc.position.set(-2.4, 0, -1.5); scene.add(hc);
box(hc, 0.5, 0.9, 0.45, mat(0xdfe3e8, { roughness: 0.4 }), 0, 0.45, 0);
P.hc = screen(hc, 0.3, 0.16, 256, 136, 0, 0.72, 0.228);
tube('water', [[-2.2, 0.5, -1.4], [-1.9, 0.12, -1.25], L(-0.5, 0.1, -0.5), L(0.85, 0.2, -0.1), L(0.86, 0.5, 0.3), L(0.78, 0.6, 0.38)], 0.016);
block(-2.7, -2.1, -1.78, -1.22);

// drug cart
const meds = new THREE.Group(); meds.position.set(-3.7, 0, -2.6); scene.add(meds);
box(meds, 0.8, 0.95, 0.5, mat(0xc0392b, { roughness: 0.5 }), 0, 0.48, 0);
for (let i = 0; i < 4; i++) box(meds, 0.74, 0.02, 0.01, mat(0x222222), 0, 0.2 + i * 0.2, 0.255);
for (let i = 0; i < 5; i++) cyl(meds, 0.022, 0.022, 0.09, mat([0x3fa7ff, 0xffffff, 0xffd24d, 0x9b59b6, 0x2ecc71][i]), -0.25 + i * 0.12, 1.0, 0.05);
block(-4.15, -3.25, -2.9, -2.3);

// ACT / blood gas analyzer bench
const lab = new THREE.Group(); lab.position.set(-3.7, 0, 0.9); scene.add(lab);
box(lab, 1.2, 0.9, 0.6, mat(0xd9d4c7), 0, 0.45, 0);
box(lab, 0.34, 0.3, 0.3, mat(0xf4f5f7), -0.3, 1.05, 0);
box(lab, 0.3, 0.22, 0.26, mat(0x2b3440), 0.28, 1.01, 0);
P.lab = screen(lab, 0.3, 0.18, 320, 192, -0.3, 1.08, 0.152);
block(-4.35, -3.05, 0.55, 1.25);

// ---------------------------------------------------------------- OR table, patient, team
const TABLE = new THREE.Vector3(2.4, 0, -1.2);
const tableG = new THREE.Group(); tableG.position.copy(TABLE); scene.add(tableG);
(function buildTable() {
  const steel = mat(0x8e98a3, { metalness: 0.7, roughness: 0.35 }), drape = mat(0x2f7fb8, { roughness: 0.9 }), skin = mat(0xd9a784);
  box(tableG, 0.5, 0.12, 0.5, steel, 0, 0.06, 0); cyl(tableG, 0.09, 0.09, 0.7, steel, 0, 0.47, 0);
  box(tableG, 2.05, 0.08, 0.62, mat(0x22262b), 0, 0.86, 0);
  P.body = new THREE.Group(); P.body.position.set(0, 0.9, 0); tableG.add(P.body);
  box(P.body, 1.75, 0.24, 0.56, drape, -0.1, 0.12, 0);
  box(P.body, 0.5, 0.3, 0.6, drape, 0.1, 0.16, 0);
  add(P.body, new THREE.SphereGeometry(0.11, 20, 16), skin, 0.92, 0.14, 0);
  box(P.body, 0.2, 0.06, 0.24, mat(0x7fc3d8), 0.93, 0.24, 0);
  // open chest window with the heart
  box(P.body, 0.26, 0.02, 0.22, mat(0x5a0f17), 0.1, 0.32, 0);
  P.heart = add(P.body, new THREE.SphereGeometry(0.07, 24, 18), mat(0xb5292f, { roughness: 0.35 }), 0.1, 0.36, 0);
  P.heart.scale.set(1, 0.8, 0.85);
  P.aorta = cyl(P.body, 0.016, 0.016, 0.12, mat(0xd24a4a), 0.19, 0.38, -0.02); P.aorta.rotation.z = -0.9;
  P.xclamp = box(P.body, 0.012, 0.1, 0.03, steel, 0.2, 0.42, -0.02); P.xclamp.rotation.z = -0.9;
  P.body.traverse((m) => { m.userData.person = 'patient'; });
  block(TABLE.x - 1.15, TABLE.x + 1.15, TABLE.z - 0.4, TABLE.z + 0.4);
})();
function person(x, z, rotY, scrub, name) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rotY; scene.add(g);
  const s = mat(scrub, { roughness: 0.85 }), skin = mat(0xcf9a76), sh = mat(0x1d1d1f);
  box(g, 0.16, 0.8, 0.18, s, -0.1, 0.4, 0); box(g, 0.16, 0.8, 0.18, s, 0.1, 0.4, 0);
  box(g, 0.44, 0.62, 0.24, s, 0, 1.11, 0);
  g.armL = box(g, 0.13, 0.56, 0.14, s, -0.3, 1.12, 0.06); g.armR = box(g, 0.13, 0.56, 0.14, s, 0.3, 1.12, 0.06);
  g.armL.rotation.x = g.armR.rotation.x = -0.9; g.armL.position.z = g.armR.position.z = 0.22;
  // head with cap, mask and eyes as its children, so they turn together
  g.head = add(g, new THREE.SphereGeometry(0.135, 24, 18), skin, 0, 1.57, 0); g.head.scale.set(0.94, 1.06, 1);
  const capM = mat(0x6fb7cf, { roughness: 0.9 });
  add(g.head, new THREE.SphereGeometry(0.142, 24, 12, 0, Math.PI * 2, 0, Math.PI * 0.46), capM, 0, 0.012, -0.004);
  const mask = add(g.head, new THREE.SphereGeometry(0.139, 24, 10, Math.PI * 0.22, Math.PI * 0.56, Math.PI * 0.52, Math.PI * 0.3), mat(0xdfeef5, { roughness: 0.95 }), 0, 0, 0.004);
  mask.rotation.y = -Math.PI / 2;
  for (const ex of [-0.05, 0.05]) add(g.head, new THREE.SphereGeometry(0.014, 10, 8), sh, ex, 0.03, 0.124, false);
  cyl(g, 0.055, 0.065, 0.08, skin, 0, 1.44, 0, 14);          // neck
  block(x - 0.3, x + 0.3, z - 0.25, z + 0.25);
  g.name = name; g.traverse((m) => { m.userData.person = name; });
  return g;
}
// surgical lights on ceiling arms, a mayo stand with instruments and an IV pole
(function dressOR() {
  const steel = mat(0xb4bcc5, { metalness: 0.85, roughness: 0.25 }), white = mat(0xf2f4f6, { roughness: 0.35 });
  const lamp = new THREE.MeshBasicMaterial({ color: 0xf1ede0 });
  for (const [lx, lz, tilt] of [[1.95, -0.95, 0.28], [2.95, -1.5, -0.22]]) {
    cyl(scene, 0.04, 0.04, 0.5, steel, lx, ROOM.h - 0.25, lz);
    cyl(scene, 0.025, 0.025, 0.36, steel, lx, 2.52, lz);
    const head = new THREE.Group(); head.position.set(lx, 2.3, lz); head.rotation.z = tilt; scene.add(head);
    cyl(head, 0.34, 0.3, 0.09, white, 0, 0, 0, 40);
    const face = add(head, new THREE.CircleGeometry(0.28, 40), lamp, 0, -0.047, 0, false); face.rotation.x = Math.PI / 2;
    cyl(head, 0.03, 0.03, 0.14, steel, 0, -0.1, 0, 12);
    const spot = new THREE.SpotLight(0xfff6e6, 7, 5, 0.5, 0.7, 1.4);
    spot.position.set(lx, 2.22, lz); spot.target.position.set(TABLE.x + 0.1, 1.05, TABLE.z);
    if (HQ && lx < 2.5) { spot.castShadow = true; spot.shadow.mapSize.set(1024, 1024); spot.shadow.bias = -0.0008; }
    scene.add(spot, spot.target);
  }
  const mayo = new THREE.Group(); mayo.position.set(3.25, 0, -0.35); scene.add(mayo);
  cyl(mayo, 0.02, 0.02, 1.0, steel, 0.22, 0.5, 0); box(mayo, 0.5, 0.03, 0.06, steel, 0, 0.03, 0); box(mayo, 0.06, 0.03, 0.4, steel, -0.22, 0.03, 0);
  box(mayo, 0.62, 0.025, 0.42, steel, -0.05, 1.01, 0); box(mayo, 0.58, 0.012, 0.38, mat(0x2f7fb8, { roughness: 0.95 }), -0.05, 1.028, 0);
  for (let i = 0; i < 6; i++) box(mayo, 0.012, 0.008, 0.16 + (i % 3) * 0.02, steel, -0.26 + i * 0.07, 1.04, 0.02 * (i % 2));
  block(2.9, 3.55, -0.6, -0.1);
  const iv = new THREE.Group(); iv.position.set(4.95, 0, -0.55); scene.add(iv);
  cyl(iv, 0.015, 0.015, 2.0, steel, 0, 1.0, 0); for (let i = 0; i < 5; i++) { const leg = box(iv, 0.3, 0.02, 0.03, steel, 0, 0.03, 0); leg.rotation.y = (i * Math.PI * 2) / 5; leg.translateX(0.14); }
  box(iv, 0.3, 0.012, 0.012, steel, 0, 1.98, 0);
  for (const bx of [-0.12, 0.12]) box(iv, 0.11, 0.2, 0.035, glass(0xdff1fb, 0.55), bx, 1.83, 0);
  cyl(scene, 0.17, 0.14, 0.26, steel, 1.35, 0.17, -0.2, 24);       // kick bucket
})();
const surgeon = person(2.5, -1.95, 0, 0x2e8b6f, 'surgeon');
const assistant = person(1.75, -1.95, 0.15, 0x3b6ea8, 'assistant');
const anesth = person(4.35, -2.05, -0.6, 0x7b5aa6, 'anesthesia');
const bubble = canvasTex(768, 224);
const bubbleSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: bubble.t, transparent: true, depthTest: false }));
bubbleSprite.scale.set(1.9, 0.55, 1); bubbleSprite.position.set(2.5, 2.25, -1.95); bubbleSprite.renderOrder = 10; scene.add(bubbleSprite);

// anesthesia machine with ventilator bellows
const an = new THREE.Group(); an.position.set(4.5, 0, -1.2); scene.add(an);
box(an, 0.6, 1.25, 0.55, mat(0xcfd6dd, { roughness: 0.45 }), 0, 0.63, 0);
cyl(an, 0.09, 0.09, 0.26, glass(0xffffff, 0.3), -0.15, 1.4, 0.05);
P.bellows = cyl(an, 0.075, 0.075, 0.2, mat(0x222a33), -0.15, 1.37, 0.05);
P.anScreen = screen(an, 0.3, 0.2, 256, 170, 0.12, 1.42, 0.05); P.anScreen.mesh.rotation.y = -Math.PI / 2 + 0.5;
block(4.15, 4.85, -1.52, -0.88);

// patient monitor on a stand at the head of the table, turned toward the pump, and the same picture repeated on
// the wall screen (one canvas, two meshes)
const monStand = new THREE.Group(); monStand.position.set(1.05, 0, -2.25); monStand.rotation.y = -0.89; scene.add(monStand);
cyl(monStand, 0.2, 0.24, 0.05, mat(0x2a2f36), 0, 0.025, 0); cyl(monStand, 0.025, 0.025, 1.45, mat(0xaab2bb, { metalness: 0.7, roughness: 0.3 }), 0, 0.75, 0);
box(monStand, 0.98, 0.58, 0.05, mat(0x101215), 0, 1.62, 0);
P.monitor = screen(monStand, 0.92, 0.5175, MON_W, MON_H, 0, 1.62, 0.028);
block(0.8, 1.3, -2.5, -2.0);
P.repeater = add(scene, new THREE.PlaneGeometry(2.0, 1.125), P.monitor.mesh.material, 2.4, 2.05, -4.96, false);   // wall repeater
box(scene, 2.1, 1.22, 0.04, mat(0x101215), 2.4, 2.05, -4.99);

// tubing between patient and machine
const chest = [TABLE.x + 0.05, 1.22, TABLE.z];
tube('ven', [chest, [1.9, 1.05, -1.0], [1.0, 0.35, -0.8], [0.15, 0.35, -0.72], [-0.15, 0.92, -0.5], [-0.3, 1.42, -0.36], L(RES.x, RES.y + 0.22, RES.z)], 0.017);
tube('res', [L(RES.x, RES.y - 0.27, RES.z), L(0.55, 0.74, 0.32), L(0.44, 0.72, 0.38), L(0.42, 0.63, 0.4)], 0.015);
tube('res', [L(0.49, 0.5, 0.4), L(0.5, 0.56, 0.42), L(0.48, 0.64, 0.4), L(0.5, 0.66, 0.38)], 0.013);
tube('art', [L(0.72, 0.66, 0.38), L(0.84, 0.56, 0.32), [-0.16, 0.56, -0.28], [0.2, 0.15, -0.9], [1.3, 0.3, -1.45], [2.0, 1.02, -1.38], [2.55, 1.24, -1.24]], 0.013);
tube('cp', [L(-0.3, 1.92, -0.22), L(-0.35, 1.2, -0.27), L(-0.28, 0.66, -0.02), L(-0.23, 0.64, 0.1), L(-0.1, 0.68, -0.25), [0.0, 0.45, -1.0], [1.3, 0.6, -1.5], [1.8, 1.0, -1.5], [2.5, 1.27, -1.26]], 0.008);
tube('vent', [[2.52, 1.27, -1.16], [2.0, 1.1, -0.75], [0.6, 0.6, -0.85], L(0.5, 0.7, -0.3), L(0.21, 0.64, 0.1), L(0.4, 0.9, -0.15), L(RES.x - 0.08, RES.y + 0.22, RES.z - 0.06)], 0.007);
// ---------------------------------------------------------------- interactables and name tags
const interact = [];
function tag(text) {
  const t = canvasTex(512, 96), g = t.ctx;
  g.font = '600 44px system-ui, sans-serif'; const w = Math.min(500, g.measureText(text).width + 40);
  g.fillStyle = 'rgba(10,14,20,0.82)'; g.beginPath(); g.roundRect((512 - w) / 2, 12, w, 72, 18); g.fill();
  g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(text, 256, 50);
  t.t.needsUpdate = true;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t.t, transparent: true, depthTest: false }));
  s.scale.set(0.62, 0.116, 1); s.renderOrder = 9; scene.add(s);
  return s;
}
function addInteract(id, label, x, y, z, ty) {
  const sprite = tag(label); sprite.position.set(x, ty ?? y + 0.3, z);
  interact.push({ id, label, pos: new THREE.Vector3(x, y, z), sprite });
}
addInteract('pump', 'Pump console', CART.x - 0.6, 1.3, CART.z - 0.1, 1.55);
addInteract('venous', 'Venous clamp', -0.15, 0.92, -0.5, 1.1);
addInteract('gas', 'Gas blender', CART.x + 0.3, 1.55, CART.z - 0.12, 1.8);
addInteract('cp', 'Cardioplegia', CART.x - 0.23, 0.5, CART.z + 0.29, 1.0);
addInteract('timers', 'Timers', CART.x - 0.1, 1.39, CART.z - 0.19, 1.27);
addInteract('res', 'Reservoir', CART.x + RES.x, RES.y, CART.z + RES.z, RES.y + 0.42);
addInteract('hc', 'Heater-cooler', -2.4, 0.75, -1.5, 1.08);
addInteract('meds', 'Drug cart', -3.7, 1.0, -2.6, 1.3);
addInteract('lab', 'ACT and blood gas', -3.7, 1.05, 0.9, 1.4);
addInteract('vent', 'Ventilator', 4.5, 1.3, -1.2, 1.72);
addInteract('talk', 'Surgeon', 2.5, 1.5, -1.95, 1.95);

// ---------------------------------------------------------------- screens
function text(g, s, x, y, size, color = '#fff', align = 'left', weight = 600) {
  g.font = `${weight} ${size}px system-ui, sans-serif`; g.fillStyle = color; g.textAlign = align; g.textBaseline = 'alphabetic'; g.fillText(s, x, y);
}
function drawScreens(S) {
  drawMonitor(P.monitor.ctx, S); P.monitor.t.needsUpdate = true;
  consoleUI.draw(S);
  // heart-lung machine data screen
  let { ctx: g, t } = P.central;
  g.fillStyle = '#0a1622'; g.fillRect(0, 0, 640, 392);
  const cell = (label, val, unit, x, y, col = '#e8f1ff') => { text(g, label, x, y, 18, '#7f93a8', 'left', 500); text(g, val, x, y + 46, 44, col); text(g, unit, x, y + 68, 16, '#7f93a8', 'left', 500); };
  cell('FLOW', fmt(S.flow, 2), `L/min   CI ${fmt(S.ci, 2)}`, 20, 30, S.flow < 0 ? '#ff5a5a' : '#6fe3a1');
  cell('RPM', fmt(S.rpm), 'rev/min', 230, 30);
  cell('LINE P', fmt(S.line_p), 'mmHg', 440, 30, S.line_p > 300 ? '#ff5a5a' : '#e8f1ff');
  cell('RESERVOIR', fmt(S.res), 'mL', 20, 130, S.res < 300 ? '#ff5a5a' : '#e8f1ff');
  cell('SvO2', fmt(S.svo2), '%', 230, 130, S.svo2 < 60 ? '#ffb84d' : '#e8f1ff');
  cell('DO2i', fmt(S.do2i), 'mL/min/m2', 440, 130, S.do2i < 270 ? '#ffb84d' : '#e8f1ff');
  cell('ART TEMP', fmt(S.t_art, 1), `C   pt ${fmt(S.temp, 1)}`, 20, 230, '#ffd24d');
  cell('HCT', fmt(S.hct), '%', 230, 230);
  cell('PaCO2 / PaO2', `${fmt(S.paco2)} / ${fmt(S.pao2)}`, 'mmHg', 400, 230);
  text(g, `YOUR TIMERS  BYPASS ${mmss(S.clocks.bypass.s)}   CLAMP ${mmss(S.clocks.clamp.s)}   CPG ${mmss(S.clocks.cp.s)}`, 20, 360, 22, '#9fd0ff');
  t.needsUpdate = true;
  // heater-cooler
  ({ ctx: g, t } = P.hc);
  g.fillStyle = '#0d1a14'; g.fillRect(0, 0, 256, 136);
  const hcRow = (lbl, tw, set, on, y) => { text(g, lbl, 10, y - 30, 16, '#9fb7a8', 'left', 600); text(g, on ? 'ON' : 'OFF', 246, y - 30, 16, on ? '#6fe3a1' : '#ffb84d', 'right', 700);
    text(g, `${fmt(tw, 1)} C`, 150, y, 30, tw < 30 ? '#6fc8ff' : '#ff9d5a', 'right'); text(g, `set ${fmt(set, 1)}`, 246, y, 16, '#9fb7a8', 'right', 500); };
  hcRow('PATIENT', S.t_water, S.controls.water_set, S.controls.hc_on, 62); hcRow('CARDIOPLEGIA', S.t_cp_water, S.controls.cp_water_set, S.controls.cp_hc_on, 128);
  t.needsUpdate = true;
  // analyzer
  ({ ctx: g, t } = P.lab);
  g.fillStyle = '#0f1720'; g.fillRect(0, 0, 320, 192);
  text(g, S.labs_pending ? 'RUNNING...' : 'READY', 12, 28, 20, S.labs_pending ? '#ffb84d' : '#6fe3a1');
  text(g, `ACT ${S.last_act ? S.last_act[1] : '--'} / ${S.last_act2 ? S.last_act2[1] : '--'} s`, 12, 80, 34, '#fff');
  const a = S.last_abg && S.last_abg[1];
  text(g, a ? `pH ${a.ph}  CO2 ${a.paco2}  O2 ${a.pao2}` : 'no blood gas yet', 12, 124, 22, '#c9d1d9');
  text(g, a ? `K ${a.k}  Hct ${a.hct}  Lac ${a.lactate}` : '', 12, 156, 22, '#c9d1d9');
  t.needsUpdate = true;
  // anesthesia screen
  ({ ctx: g, t } = P.anScreen);
  g.fillStyle = '#081018'; g.fillRect(0, 0, 256, 170);
  text(g, 'VENTILATOR', 12, 34, 22, '#8b97a3'); text(g, S.controls.ventilator ? 'ON' : 'OFF', 12, 110, 72, S.controls.ventilator ? '#6fe3a1' : '#ffb84d');
  t.needsUpdate = true;
}
let lastLineN = -1;
function drawBubble(line) {
  const g = bubble.ctx; g.clearRect(0, 0, 768, 224);
  if (!line) { bubble.t.needsUpdate = true; return; }
  g.fillStyle = 'rgba(255,255,255,0.95)'; g.beginPath(); g.roundRect(8, 8, 752, 176, 26); g.fill();
  g.beginPath(); g.moveTo(350, 182); g.lineTo(384, 220); g.lineTo(418, 182); g.fill();
  g.fillStyle = '#12202b'; g.font = '600 34px system-ui, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  const words = line.split(' '), rows = []; let cur = '';
  for (const w of words) { if (g.measureText(cur + ' ' + w).width > 700) { rows.push(cur); cur = w; } else cur = cur ? cur + ' ' + w : w; }
  rows.push(cur);
  rows.slice(0, 4).forEach((r, i) => g.fillText(r, 384, 96 + (i - (Math.min(rows.length, 4) - 1) / 2) * 40));
  bubble.t.needsUpdate = true;
}

// ---------------------------------------------------------------- HUD
const VITALS = [
  ['MAP', (S) => fmt(S.map), (S) => (S.on_bypass && (S.map < 45 || S.map > 90) ? 'warn' : '')],
  ['Flow L/min', (S) => fmt(S.flow, 2), (S) => (S.flow < -0.1 ? 'bad' : '')],
  ['Pump RPM', (S) => fmt(S.rpm), (S) => (S.rpm > 4000 ? 'warn' : '')],
  ['Cardiac index', (S) => fmt(S.ci, 2), () => ''],
  ['SvO2 %', (S) => fmt(S.svo2), (S) => (S.svo2 < 60 ? 'warn' : '')],
  ['O2 delivery', (S) => fmt(S.do2i), (S) => (S.on_bypass && S.do2i < 270 ? 'warn' : '')],
  ['Temp C', (S) => fmt(S.temp, 1), () => ''],
  ['Reservoir mL', (S) => fmt(S.res), (S) => (S.cannulated && S.res < 150 ? 'bad' : S.cannulated && S.res < 300 ? 'warn' : '')],
  ['CVP', (S) => fmt(S.cvp, 1), () => ''],
  ['Hct %', (S) => fmt(S.hct), (S) => (S.hct < 21 ? 'warn' : '')],
  ['K+', (S) => fmt(S.k, 1), (S) => (S.k > 6 ? 'bad' : S.k > 5.5 ? 'warn' : '')],
  ['Last ACT', (S) => (S.last_act ? String(S.last_act[1]) : '--'), (S) => (S.last_act && S.last_act[1] < 400 && S.on_bypass ? 'bad' : '')],
  ['Clamp timer', (S) => mmss(S.clocks.clamp.s) + (S.clocks.clamp.run ? '' : ' ■'), () => ''],
];
const vitEls = VITALS.map(([k]) => {
  const d = document.createElement('div'); d.className = 'v'; d.innerHTML = `<div class="k">${k}</div><div class="n">--</div>`;
  $('vitals').appendChild(d); return d;
});
// Browser speech is a placeholder until the local voice service replaces it. It is off by default on desktop
// Linux, where headed Chrome crashed on a DGX Spark right as the first surgeon line was spoken, and every
// call is guarded so a speech failure stays inside these functions.
const LINUX_DESKTOP = /Linux/.test(navigator.userAgent) && !/Android/.test(navigator.userAgent);
let voiceOn = !LINUX_DESKTOP, debriefShown = false, started = false;
function speechCancel() { try { window.speechSynthesis?.cancel(); } catch (e) { /* voice is optional */ } }
function say(textLine) {
  if (!voiceOn || !('speechSynthesis' in window)) return;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(textLine); u.rate = 1.05; u.pitch = 0.9;
    u.onerror = () => {};                       // a failed utterance is not worth an error in the console
    speechSynthesis.speak(u);
  } catch (e) { voiceOn = false; setVoiceLabel(); }
}
function setVoiceLabel() { const b = $('btn-voice'); if (b) b.textContent = 'Voice: ' + (voiceOn ? 'on' : 'off'); }
setVoiceLabel();
function updateHud(S) {
  $('phase-title').textContent = S.phase_title;
  const chip = $('score-chip'); chip.textContent = S.score.score; chip.className = 'chip' + (S.score.score < 80 ? ' bad' : S.score.score < 90 ? ' mid' : '');
  const line = S.lines.length ? S.lines[S.lines.length - 1].text : '';
  $('surgeon-line').textContent = line ? 'Surgeon: ' + line : '';
  if (S.n_lines !== lastLineN) { if (lastLineN >= 0 || started) { drawBubble(line); if (started && S.n_lines > lastLineN) say(line); } else drawBubble(line); lastLineN = S.n_lines; }
  $('objectives').innerHTML = S.objectives.map((o) => `<li>${o}</li>`).join('');
  VITALS.forEach(([, f, c], i) => { vitEls[i].lastChild.textContent = f(S); vitEls[i].className = 'v ' + c(S); });
  $('alarms').innerHTML = S.alarms.map(([sev, msg]) => `<div class="alarm ${sev}">${msg}</div>`).join('');
  document.querySelectorAll('#hud-bottom [data-speed]').forEach((b) => b.classList.toggle('on', Number(b.dataset.speed) === S.speed));
  $('btn-auto').textContent = 'Expert autopilot: ' + (S.autopilot ? 'on' : 'off'); $('btn-auto').classList.toggle('on', S.autopilot);
  $('clock').textContent = 'case ' + mmss(S.t);
  if (S.phase === 'DONE' && !debriefShown) showDebrief(S);
}
const escH = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function showDebrief(S) {
  debriefShown = true; document.exitPointerLock?.();
  const sc = S.score;
  $('debrief-body').innerHTML = `
    <div class="row"><div><h1>Debrief</h1><p class="sub">${escH(S.persona.name)}, ${mmss(S.t)} case time, ${mmss(S.bypass_time)} on bypass, ${mmss(S.clamp_time)} clamp time</p></div>
    <div class="big">${sc.score}</div></div>
    <p>Pressure in range ${sc.map_in_range}% of bypass time. Oxygen delivery on target ${sc.do2_in_range}%. Closed-loop callouts ${sc.callouts.made} of ${sc.callouts.due}.</p>
    ${S.session && S.session.practice ? `<div class="find minor"><b>Practice (resumed from save${S.session.resumed_from ? ': ' + escH(S.session.resumed_from.name) : ''})</b>. This score is kept out of comparisons with clean start-to-finish runs.</div>` : ''}
    ${window.rubricHTML(sc.rubric)}
    <div id="db-more"><p class="sub">Loading the phase-by-phase review...</p></div>
    <h3>Checklist</h3>
    <div class="check">${sc.checklist.map((c) => `<div class="${c.done ? 'yes' : 'no'}">${c.done ? 'done' : 'missed'}: ${escH(c.label)}</div>`).join('')}</div>
    <div class="row gap"><button class="primary" id="btn-again">Run another case</button><button id="btn-summary">Session summary and timeline</button></div>`;
  $('debrief').classList.remove('hidden');
  $('btn-again').onclick = () => { $('debrief').classList.add('hidden'); $('start').classList.remove('hidden'); started = false; };
  $('btn-summary').onclick = () => savesUI.openSessions(S.session && S.session.id);
  game.debrief(S);
  extendDebrief(S).catch(() => { const m = $('db-more'); if (m) m.innerHTML = '<p class="sub">The phase-by-phase review could not be loaded.</p>'; });
}
async function extendDebrief(S) {
  const sid = S.session && S.session.id;
  const [doc, bench] = await Promise.all([
    sid ? fetch('/api/sessions/' + encodeURIComponent(sid)).then((r) => (r.ok ? r.json() : null)).catch(() => null) : null,
    fetch('/api/benchmark?persona=' + encodeURIComponent(S.persona.id)).then((r) => r.json()).catch(() => null),
  ]);
  const sum = doc && doc.summary, sc = S.score;
  let html = '';
  if (sum && sum.improve) {
    html += `<h3>Three things to improve</h3>${sum.improve.length ? `<ol class="improve">${sum.improve.map((x) => `<li>${escH(x.what)}${x.how ? `<div class="sub">${escH(x.how)}</div>` : ''}</li>`).join('')}</ol>` : '<p>Nothing to improve on this run.</p>'}`;
    if (sum.went_well && sum.went_well.length) html += `<h3>What went well</h3><ul>${sum.went_well.map((w) => `<li>${escH(w)}</li>`).join('')}</ul>`;
  }
  if (sum && sum.phases && sum.phases.length) {
    html += `<h3>Phase by phase</h3><div class="scroll"><table class="phases"><tr><th>Step</th><th>From</th><th>Took</th><th>Callout</th><th>Problems</th></tr>
      ${sum.phases.map((p) => `<tr><td>${escH(p.title)}</td><td>${mmss(p.start)}</td><td>${p.end === null || p.end === undefined ? '-' : mmss(p.end - p.start)}</td>
        <td>${p.callout ? (p.called ? `<span class="ok">said</span>` : `<span class="bad">missed</span>`) : '-'}</td>
        <td>${p.findings && p.findings.length ? p.findings.map((f) => `<span class="sev ${f.sev}">${escH(f.msg)}</span>`).join('<br>') : 'none'}</td></tr>`).join('')}</table></div>`;
  }
  if (bench && bench.available) {
    const mins = (s) => (s / 60).toFixed(1);
    const rows = [['Pressure in range', sc.map_in_range + '%', bench.map_in_range + '%'],
      ['Oxygen delivery on target', sc.do2_in_range + '%', bench.do2_in_range + '%'], ['Time on bypass (min)', mins(S.bypass_time), bench.bypass_min],
      ['Clamp time (min)', mins(S.clamp_time), bench.clamp_min], ['Callouts', `${sc.callouts.made} of ${sc.callouts.due}`, 'all']];
    html += `<h3>You and the expert benchmark</h3><table class="bench"><tr><th></th><th>You</th><th>Expert autopilot</th></tr>
      ${rows.map(([k, a, b]) => `<tr><td>${k}</td><td>${escH(a)}</td><td>${escH(b)}</td></tr>`).join('')}</table>
      <p class="sub">Expert: the autopilot on this patient, average of ${bench.runs} runs (docs/BENCHMARK.md). Training-model numbers, not clinical reference values.${S.session && S.session.practice ? ' This run is practice, so compare with care.' : ''}</p>`;
  }
  if (doc && doc.events) html += `<h3>Trends</h3>${trendCharts(doc.events)}`;
  const m = $('db-more'); if (m) m.innerHTML = html || '<p class="sub">No session log for this run.</p>';
}

// ---------------------------------------------------------------- panels, input
const panels = buildPanels(act, state);
let openId = null;
function openPanel(id) {
  const p = panels[id]; if (!p) return;
  openId = id; document.exitPointerLock?.();
  $('panel-title').textContent = p.title; const body = $('panel-body'); body.innerHTML = ''; p.items = p.build(body);
  $('panel').classList.remove('hidden'); $('tablet').classList.add('hidden');
  if (state.S) p.items.forEach((it) => it.update && it.update(state.S));
}
function closePanel() { openId = null; $('panel').classList.add('hidden'); }
$('panel-close').onclick = closePanel;
const tablet = $('tablet');
Object.entries(panels).forEach(([id, p]) => { const b = document.createElement('button'); b.textContent = p.title; b.onclick = () => openPanel(id); tablet.appendChild(b); });
$('btn-tablet').onclick = () => tablet.classList.toggle('hidden');
$('btn-talk').onclick = () => openPanel('talk');
$('btn-auto').onclick = () => act({ type: 'autopilot', on: !(state.S && state.S.autopilot) });
$('btn-voice').onclick = () => { voiceOn = !voiceOn; setVoiceLabel(); if (!voiceOn) speechCancel(); };
document.querySelectorAll('#hud-bottom [data-speed]').forEach((b) => (b.onclick = () => act({ type: 'speed', x: Number(b.dataset.speed) })));

const smash = initSmash({ scene, camera, room: ROOM, onQuip: (t) => { drawBubble(t); say(t); }, pause: () => act({ type: 'speed', x: 0 }) });
$('btn-smash').onclick = () => { if (!uiBlocked()) smash.toggle(); };
const keys = {};
let focus = null;
const savesUI = initSaves({
  getState: () => state.S, isCaseRunning: () => started,
  onLoaded: async (info) => {
    const S = await fetch(STATE_URL).then((r) => r.json()); state.S = S;
    const p = state.META.personas.find((x) => x.id === S.persona.id);
    if (p) { const k = Math.cbrt(p.weight / 75); P.body.scale.set(Math.min(1.1, 0.9 + (p.height - 155) / 250), k, k); }
    $('start').classList.add('hidden'); $('debrief').classList.add('hidden');
    started = true; debriefShown = false; lastLineN = S.n_lines;
    savesUI.toast(`Loaded "${info.name}" (${info.phase_title}, ${mmss(info.case_time)}). Paused: press 1x to carry on. This run is now practice.`, 6000);
  },
});
const helpUI = initHelp({
  getState: () => state.S, panelTitle: (id) => (panels[id] ? panels[id].title : id), openPanel,
  vitals: (S) => VITALS.map(([k, f, c]) => ({ k, v: f(S), cls: c(S) })),
});
$('btn-help').onclick = () => helpUI.toggle();
const uiBlocked = () => openId || savesUI.isOpen() || helpUI.isOpen() || !$('start').classList.contains('hidden') || !$('debrief').classList.contains('hidden');
const typing = (e) => e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT';
let lastW = 0;
window.addEventListener('keydown', (e) => {
  // F5 is quick-save here, never "reload and lose the case"; F9 opens Save / Load
  if (e.code === 'F5') { e.preventDefault(); if (!savesUI.isOpen()) savesUI.quickSave(); return; }
  if (e.code === 'F9') { e.preventDefault(); savesUI.toggleSaves(); return; }
  if (e.code === 'Escape' && savesUI.isOpen()) { savesUI.close(); return; }
  if (typing(e)) return;
  if (e.code === 'Escape' && helpUI.isOpen()) { helpUI.close(); return; }
  if (e.code === 'KeyH' && !e.repeat && !savesUI.isOpen()) { if (openId) closePanel(); helpUI.toggle(); return; }
  if (e.code === 'Space') e.preventDefault();    // Space is jump, never "click the focused button" or scroll
  if (e.code === 'Tab') { e.preventDefault(); tablet.classList.toggle('hidden'); return; }
  if (e.code === 'Escape') { closePanel(); tablet.classList.add('hidden'); return; }
  if (uiBlocked()) return;
  if (e.code === 'KeyW' && !e.repeat) { const t = performance.now(); if (t - lastW < 300) player.sprint = true; lastW = t; }   // double-tap W sprints
  keys[e.code] = true;
  if (e.code === 'KeyB') { smash.toggle(); return; }
  if (e.code === 'KeyV' && !e.repeat) { cycleView(); return; }
  if (smash.state.on) { if (e.code === 'KeyF') smash.swing(); return; }
  if (e.code === 'KeyE' && focus) openPanel(focus.id);
  if (e.code === 'KeyT') openPanel('talk');
});
window.addEventListener('keyup', (e) => {
  if (e.code === 'Space' && !typing(e)) e.preventDefault();
  keys[e.code] = false;
  if (e.code === 'KeyW') player.sprint = false;
});
window.addEventListener('blur', () => { for (const k in keys) keys[k] = false; player.sprint = false; });
// Ctrl+W closes a browser tab and a page cannot block it. Ctrl is also a crouch key, so ask before leaving a running case.
window.addEventListener('beforeunload', (e) => { if (started && state.S && state.S.phase !== 'DONE' && !smash.state.on) { e.preventDefault(); e.returnValue = ''; } });
function cycleView() {
  if (smash.state.on) return;                     // the bat is held in first person
  player.view = (player.view + 1) % 3;
  const names = ['First person', 'Third person', 'Third person (front)'];
  $('view-chip').textContent = names[player.view]; $('view-chip').classList.add('show');
  clearTimeout(cycleView.t); cycleView.t = setTimeout(() => $('view-chip').classList.remove('show'), 1200);
}
// console dials and stop buttons: aim with the centre of the view; wheel or drag turns a dial, click presses a button.
// Sends go through the same 'set' action as the panels, at most every 80 ms while turning.
const ray = new THREE.Raycaster(), CENTER = new THREE.Vector2(0, 0);
let ctl = null, dialDrag = null;
const dialSend = { t: 0, kv: null, timer: 0 };
function flushDial() { clearTimeout(dialSend.timer); dialSend.timer = 0; dialSend.t = performance.now(); if (dialSend.kv) act({ type: 'set', key: dialSend.kv[0], value: dialSend.kv[1] }); dialSend.kv = null; }
function sendDial(kv) {
  if (!kv) return; dialSend.kv = kv;
  if (performance.now() - dialSend.t > 80) flushDial(); else if (!dialSend.timer) dialSend.timer = setTimeout(flushDial, 90);
}
function pressControl(c) {
  if (c.kind === 'button' && c.toggle && !c.inert) act({ type: 'set', key: c.toggle, value: !state.S.controls[c.toggle] });
  if (c.timer) act({ type: 'timer', which: c.timer, op: c.op === 'reset' ? 'reset' : state.S.clocks[c.timer].run ? 'stop' : 'start' });
}
window.addEventListener('wheel', (e) => {
  if (!ctl || ctl.kind !== 'dial' || uiBlocked() || !state.S) return;
  e.preventDefault(); sendDial(consoleUI.turn(ctl, state.S, e.deltaY < 0 ? 1 : -1));
}, { passive: false });
canvas.addEventListener('click', () => {
  if (uiBlocked()) return;
  if (smash.state.on) { if (document.pointerLockElement !== canvas) canvas.requestPointerLock?.(); smash.swing(); return; }
  if (ctl) { pressControl(ctl); return; }
  if (document.pointerLockElement === canvas) { if (focus) openPanel(focus.id); } else canvas.requestPointerLock?.();
});
let dragging = false;
canvas.addEventListener('mousedown', () => { dragging = true; if (ctl && ctl.kind === 'dial' && !uiBlocked()) dialDrag = { c: ctl, acc: 0 }; });
window.addEventListener('mouseup', () => { dragging = false; dialDrag = null; });
window.addEventListener('mousemove', (e) => {
  if (dialDrag && state.S) {                         // dragging a dial turns it (up or right is more) instead of looking
    dialDrag.acc += (e.movementX - e.movementY) / 7; const n = Math.trunc(dialDrag.acc);
    if (n) { dialDrag.acc -= n; sendDial(consoleUI.turn(dialDrag.c, state.S, n)); }
    return;
  }
  if (document.pointerLockElement === canvas || (dragging && !uiBlocked())) {
    player.yaw -= e.movementX * 0.0023; player.pitch = Math.max(-1.3, Math.min(1.3, player.pitch - e.movementY * 0.0023));
  }
});
// touch: left pad moves, dragging elsewhere looks, tapping a name tag's object opens it
const touch = { move: null, look: null, mx: 0, mz: 0, jump: false, crouch: false };
document.querySelectorAll('#touch-btns [data-t]').forEach((b) => {
  const t = b.dataset.t;
  b.addEventListener('touchstart', (e) => {
    e.preventDefault(); e.stopPropagation();
    if (t === 'jump') touch.jump = true;
    if (t === 'crouch') { touch.crouch = !touch.crouch; b.classList.toggle('on', touch.crouch); }
    if (t === 'view') cycleView();
  }, { passive: false });
  b.addEventListener('touchend', (e) => { e.preventDefault(); if (t === 'jump') touch.jump = false; }, { passive: false });
});
canvas.addEventListener('touchstart', (e) => {
  for (const t of e.changedTouches) {
    if (t.clientX < 160 && t.clientY > window.innerHeight - 260 && !touch.move) touch.move = { id: t.identifier, x: t.clientX, y: t.clientY };
    else if (!touch.look) touch.look = { id: t.identifier, x: t.clientX, y: t.clientY, moved: 0 };
  }
}, { passive: true });
canvas.addEventListener('touchmove', (e) => {
  for (const t of e.changedTouches) {
    if (touch.move && t.identifier === touch.move.id) {
      touch.mx = Math.max(-1, Math.min(1, (t.clientX - touch.move.x) / 45)); touch.mz = Math.max(-1, Math.min(1, (t.clientY - touch.move.y) / 45));
      $('touch-stick').style.transform = `translate(${touch.mx * 30}px, ${touch.mz * 30}px)`;
    } else if (touch.look && t.identifier === touch.look.id) {
      const dx = t.clientX - touch.look.x, dy = t.clientY - touch.look.y; touch.look.moved += Math.abs(dx) + Math.abs(dy);
      player.yaw -= dx * 0.005; player.pitch = Math.max(-1.3, Math.min(1.3, player.pitch - dy * 0.005));
      touch.look.x = t.clientX; touch.look.y = t.clientY;
    }
  }
}, { passive: true });
canvas.addEventListener('touchend', (e) => {
  for (const t of e.changedTouches) {
    if (touch.move && t.identifier === touch.move.id) { touch.move = null; touch.mx = touch.mz = 0; $('touch-stick').style.transform = ''; }
    if (touch.look && t.identifier === touch.look.id) { if (touch.look.moved < 8 && !uiBlocked()) { if (smash.state.on) smash.swing(); else if (focus) openPanel(focus.id); } touch.look = null; }
  }
});

function movePlayer(dt) {
  const blocked = uiBlocked();
  // vertical: crouch lowers the eyes, Space jumps from the floor, gravity brings you back
  const wantCrouch = !blocked && !!(keys.KeyC || keys.ControlLeft || keys.ControlRight || touch.crouch);
  player.crouch = lerp(player.crouch, wantCrouch ? 1 : 0, dt * 12);
  player.h = EYE + (EYE_CROUCH - EYE) * player.crouch;
  if (!blocked && (keys.Space || touch.jump) && player.y === 0 && !wantCrouch) player.vy = JUMP_V;
  player.vy -= GRAVITY * dt; player.y += player.vy * dt;
  if (player.y <= 0) { player.y = 0; player.vy = 0; }
  player.speed = 0;
  if (blocked) return;
  let f = (keys.KeyW || keys.ArrowUp ? 1 : 0) - (keys.KeyS || keys.ArrowDown ? 1 : 0) - touch.mz;
  let s = (keys.KeyD || keys.ArrowRight ? 1 : 0) - (keys.KeyA || keys.ArrowLeft ? 1 : 0) + touch.mx;
  if (!f && !s) { player.sprint = false; return; }
  const sprinting = !wantCrouch && f > 0 && (player.sprint || keys.ShiftLeft || keys.ShiftRight);
  const v = wantCrouch ? SNEAK : sprinting ? SPRINT : WALK;
  const sp = v * dt, sin = Math.sin(player.yaw), cos = Math.cos(player.yaw);
  player.speed = v * Math.min(1, Math.hypot(f, s)); player.sprinting = sprinting;
  const dx = (-sin * f + cos * s) * sp, dz = (-cos * f - sin * s) * sp, r = 0.28;
  const free = (x, z) => x > ROOM.x0 + r && x < ROOM.x1 - r && z > ROOM.z0 + r && z < ROOM.z1 - r &&
    (smash.state.on || !obstacles.some(([x0, x1, z0, z1]) => x > x0 - r && x < x1 + r && z > z0 - r && z < z1 + r));
  if (free(player.x + dx, player.z)) player.x += dx;
  if (free(player.x, player.z + dz)) player.z += dz;
}
const fwd = new THREE.Vector3(), to = new THREE.Vector3();
function findFocus() {
  if (smash.state.on) { focus = null; $('hint').textContent = ''; interact.forEach((it) => { it.sprite.visible = false; }); return; }
  fwd.copy(lookDir); let best = null, bestA = 0.3;
  for (const it of interact) {
    to.copy(it.pos).sub(eye); const d = to.length();
    it.sprite.material.opacity = d < 4.2 ? 1 : 0.14;
    if (d > 2.8) continue;
    const a = fwd.angleTo(to);
    if (a < bestA) { bestA = a; best = it; }
  }
  focus = best;
  $('hint').textContent = best && !uiBlocked() ? `${best.label}: ${matchMedia('(pointer: coarse)').matches ? 'tap to use' : 'press E or click'}` : '';
  ctl = null;
  if (state.S && !uiBlocked() && !matchMedia('(pointer: coarse)').matches) {
    ray.setFromCamera(CENTER, camera); ctl = dialDrag ? dialDrag.c : consoleUI.pick(ray);
    if (ctl) $('hint').textContent = consoleUI.describe(ctl, state.S) + (focus ? `  ·  E: ${focus.label}` : '');
  }
}

// ---------------------------------------------------------------- scene update from state
const tmpC = new THREE.Color();
const blood = (sat) => tmpC.copy(DARK).lerp(BRIGHT, Math.min(1, Math.max(0, (sat - 45) / 55))).clone();
function updateScene(S, dt, now) {
  const primed = S.bypass_time < 1;
  const ven = primed ? PRIME : blood(S.svo2), art = primed ? PRIME : blood(S.sao2);
  paintTubes('ven', ven, S.qv * 0.5, dt);
  paintTubes('res', ven, S.flow * 0.5, dt);
  paintTubes('art', art, S.flow * 0.5, dt);
  paintTubes('cp', S.controls.cp_type === 'hot' ? BRIGHT : PLEGE, S.controls.cp_on ? S.controls.cp_flow / 150 : 0, dt);
  paintTubes('vent', ven, S.controls.root_vent && S.xclamp ? 0.6 : 0, dt);
  paintTubes('water', tmpC.set(S.t_water < 34 ? 0x4aa8ff : 0xff8a4a).clone(), S.on_bypass ? 1 : 0, dt);
  // reservoir level
  const lvl = Math.min(1, S.res / 3000);
  P.fluid.scale.y = Math.max(0.001, lvl); P.fluid.position.y = RES.y - 0.15 + 0.15 * lvl; P.fluid.visible = S.res > 60;
  P.fluidTip.visible = S.res > 5;
  P.fluid.material.color.lerp(ven, 0.08); P.fluidTip.material.color.lerp(ven, 0.08);
  P.oxyCap.material.color.lerp(art, 0.08);
  P.impeller.rotation.y += (S.rpm / 60) * 6.283 * dt * 0.12;
  consoleUI.update(S, dt);
  // clamps: red and rotated shut when closed
  P.artClamp.material.color.set(S.controls.art_clamp ? 0xd63b3b : 0x9aa3ad); P.artClamp.rotation.z = S.controls.art_clamp ? 0 : 0.9;
  P.venClamp.material.color.set(S.controls.ven_occl > 0.95 ? 0xd63b3b : S.controls.ven_occl > 0.05 ? 0xe0a030 : 0x9aa3ad);
  P.venClamp.rotation.z = 0.9 * (1 - S.controls.ven_occl);
  P.xclamp.visible = S.xclamp;
  // heart
  const fill = Math.min(1, Math.max(0.55, 0.55 + S.cvp / 14));
  let beat = 0;
  if (S.rhythm === 'sinus' || S.rhythm === 'brady') beat = Math.max(0, Math.sin(now * (S.hr / 60) * 6.283)) ** 3 * 0.12;
  else if (S.rhythm === 'vf') beat = Math.sin(now * 37) * 0.02 + Math.sin(now * 53) * 0.02;
  P.heart.scale.set(fill * (1 - beat), 0.8 * fill * (1 - beat * 0.6), 0.85 * fill * (1 - beat));
  P.heart.material.color.lerp(tmpC.set(S.rhythm === 'asystole' ? 0x8f6f72 : 0xb5292f), 0.05);
  // ventilator bellows
  P.bellows.scale.y = S.controls.ventilator ? 0.6 + 0.4 * (0.5 + 0.5 * Math.sin(now * 1.3)) : 0.5;
  // alarm beacon
  const crit = S.alarms.some(([sev]) => sev === 'critical'), warn = S.alarms.length > 0;
  const on = crit ? Math.sin(now * 10) > 0 : false;
  P.beacon.material.color.set(on ? 0xff2a2a : warn ? 0xb07a10 : 0x1f5f33); P.beaconLight.intensity = on ? 6 : 0;
  // people
  const working = S.xclamp ? 1 : 0.25;
  surgeon.armL.rotation.x = -1.0 + Math.sin(now * 2.1) * 0.12 * working; surgeon.armR.rotation.x = -1.0 + Math.sin(now * 2.7 + 1) * 0.14 * working;
  surgeon.head.rotation.x = 0.25 + Math.sin(now * 0.7) * 0.05; assistant.armL.rotation.x = -1.0 + Math.sin(now * 1.6) * 0.06;
  anesth.head.rotation.y = Math.sin(now * 0.4) * 0.3;
}

// ---------------------------------------------------------------- start screen
let personaSel = 'standard_adult';
const game = initGame({ $, state, onSelect: (id) => { personaSel = id; } });
async function boot() {
  state.META = await fetch('/api/meta').then((r) => r.json());
  game.render(); game.refresh();
  const begin = async (watch) => {
    const student = watch ? '' : game.ready();          // the expert's runs carry no name and are never ranked
    if (student === null) return;
    await post('/api/reset', { persona: personaSel, student });
    const p = state.META.personas.find((x) => x.id === personaSel); const k = Math.cbrt(p.weight / 75);
    P.body.scale.set(Math.min(1.1, 0.9 + (p.height - 155) / 250), k, k);
    debriefShown = false; started = true; lastLineN = -1;
    if (watch) { await act({ type: 'autopilot', on: true }); await act({ type: 'speed', x: 5 }); } else await act({ type: 'speed', x: 1 });
    $('start').classList.add('hidden');
  };
  $('btn-start').onclick = () => begin(false);
  $('btn-load-start').onclick = () => savesUI.openSaves();
  $('btn-sessions-start').onclick = () => savesUI.openSessions();
  $('btn-saves').onclick = () => savesUI.openSaves();
  $('btn-sessions').onclick = () => savesUI.openSessions();
  $('btn-watch').onclick = () => begin(true);
  poll();
}
async function poll() {
  try {
    const S = await fetch(STATE_URL).then((r) => r.json());
    state.S = S; updateHud(S); recordTrend(S);
    if (openId) panels[openId].items.forEach((it) => it.update && it.update(S));
  } catch (e) { $('surgeon-line').textContent = 'Lost connection to the simulator. Is the server still running?'; }
  setTimeout(poll, 100);
}

// ---------------------------------------------------------------- camera: first person, or third person behind / in front
const avatar = buildAvatar(scene);
const eye = new THREE.Vector3(), lookDir = new THREE.Vector3();
function placeCamera(dt) {
  eye.set(player.x, player.y + player.h, player.z);
  const cp = Math.cos(player.pitch);
  lookDir.set(-Math.sin(player.yaw) * cp, Math.sin(player.pitch), -Math.cos(player.yaw) * cp);
  const view = smash.state.on ? 0 : player.view;
  if (view === 0) {
    camera.position.copy(eye);
    camera.rotation.set(player.pitch, player.yaw, 0, 'YXZ');
  } else {
    // pull back along the view line, but never through a wall or the ceiling
    const sign = view === 1 ? -1 : 1, m = 0.2;
    let d = 3.2;
    for (; d > 0.4; d -= 0.1) {
      const x = eye.x + lookDir.x * sign * d, y = eye.y + lookDir.y * sign * d, z = eye.z + lookDir.z * sign * d;
      if (x > ROOM.x0 + m && x < ROOM.x1 - m && z > ROOM.z0 + m && z < ROOM.z1 - m && y > 0.25 && y < ROOM.h - m) break;
    }
    const lift = view === 1 ? 0.35 : 0;           // behind: sit a little above the head and aim along the line of sight
    camera.position.set(eye.x + lookDir.x * sign * d, Math.min(ROOM.h - 0.2, eye.y + lookDir.y * sign * d + lift), eye.z + lookDir.z * sign * d);
    if (view === 1) camera.lookAt(eye.x + lookDir.x * 1.5, eye.y + lookDir.y * 1.5, eye.z + lookDir.z * 1.5);
    else camera.lookAt(eye);
  }
  $('cross').style.visibility = view === 2 ? 'hidden' : '';
  const fov = lerp(camera.fov, player.sprinting && player.speed > 0 ? FOV_SPRINT : FOV, dt * 8);
  if (Math.abs(fov - camera.fov) > 0.01) { camera.fov = fov; camera.updateProjectionMatrix(); }
  avatar.update({ ...player, airborne: player.y > 0.02 }, dt, view !== 0);
}

// ---------------------------------------------------------------- main loop
let last = performance.now(), screenT = 0;
function frame(nowMs) {
  const real = (nowMs - last) / 1000, dt = Math.min(0.05, real); last = nowMs; const now = nowMs / 1000;
  movePlayer(dt);
  placeCamera(dt);
  findFocus();
  const S = state.S;
  if (S) {
    const run = S.speed > 0 ? dt : 0;
    if (!smash.state.on) updateScene(S, run, now);
    if (run) sampleWaves(S, run);
    screenT += dt;
    if (screenT > 0.07) { screenT = 0; drawScreens(S); }
  }
  smash.update(dt);
  gfx.render(dt, real);
  requestAnimationFrame(frame);
}
window.P1 = { gfx, player, camera, openPanel, closePanel, state, smash, avatar, cycleView, focused: () => focus && focus.id, savesUI,
  console: consoleUI, control: () => ctl && ctl.id, monitor: { canvas: P.monitor.c, shared: () => P.repeater.material === P.monitor.mesh.material } };
boot();
requestAnimationFrame(frame);
