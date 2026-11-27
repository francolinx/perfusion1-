// Headless browser check for the web client. Needs Node 22+ (built-in WebSocket) and Google Chrome; no npm packages.
//
//   node tools/browser_check.mjs                 quick: controls, views, panels, smash mode (about 30 s)
//   node tools/browser_check.mjs --full          also plays the expert case at 20x to the debrief (about 3 min)
//   node tools/browser_check.mjs --url http://localhost:9000 --gpu --shots /tmp/shots
//
// It starts its own headless Chrome with a throwaway profile, never opens a window, and exits non-zero on any
// failed check or renderer crash. It drives the page with real key and mouse events through the DevTools protocol.
// Note: the server is single-session, so this resets whatever case another tab is running.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const URL_ = arg('--url', 'http://localhost:9000'), FULL = process.argv.includes('--full');
const SHOTS = arg('--shots', null), PORT = Number(arg('--cdp-port', 9333));
const CHROME = arg('--chrome', 'google-chrome');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'p1-chrome-'));
const flags = ['--headless=new', `--user-data-dir=${profile}`, `--remote-debugging-port=${PORT}`, '--no-first-run',
  '--window-size=1600,900', 'about:blank'];
if (process.argv.includes('--gpu')) flags.push('--use-angle=gl', '--ignore-gpu-blocklist');
const chrome = spawn(CHROME, flags, { stdio: 'ignore', detached: true });   // own process group, so every Chrome child can be stopped
const killChrome = () => { try { process.kill(-chrome.pid, 'SIGKILL'); } catch {} };
process.on('exit', () => { killChrome(); fs.rmSync(profile, { recursive: true, force: true }); });
let failed = 0;
const done = (code) => { ws?.close?.(); killChrome(); setTimeout(() => { fs.rmSync(profile, { recursive: true, force: true }); process.exit(code); }, 500); };
process.on('SIGINT', () => done(130));
process.on('unhandledRejection', (e) => { console.error('FAIL', e.message); done(4); });

let ws, id = 0; const pending = new Map(), problems = [], dialogs = [];
for (let i = 0; i < 60 && !ws; i++) {
  try { const t = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); const p = t.find((x) => x.type === 'page'); if (p) ws = new WebSocket(p.webSocketDebuggerUrl); } catch {}
  if (!ws) await sleep(250);
}
if (!ws) { console.error('could not reach Chrome'); done(2); }
if (ws.readyState !== 1) await new Promise((r) => (ws.onopen = r));
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); return; }
  if (d.method === 'Page.javascriptDialogOpening') { dialogs.push(d.params.type); send('Page.handleJavaScriptDialog', { accept: true }); }
  if (d.method === 'Inspector.detached') { console.error(`FAIL renderer: ${d.params.reason}`); done(3); }
  if (d.method === 'Runtime.exceptionThrown') problems.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') problems.push(d.params.args.map((a) => a.value ?? a.description).join(' '));
};
const send = (method, params = {}) => new Promise((res, rej) => {
  const i = ++id, t = setTimeout(() => { pending.delete(i); rej(new Error(`${method} timed out`)); }, 15000);
  pending.set(i, (d) => { clearTimeout(t); d.error ? rej(new Error(d.error.message)) : res(d.result); });
  ws.send(JSON.stringify({ id: i, method, params }));
});
const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result.value; };
const KEYS = { Space: [' ', 32], KeyW: ['w', 87], KeyC: ['c', 67], KeyV: ['v', 86], KeyE: ['e', 69], KeyB: ['b', 66], KeyF: ['f', 70], Escape: ['Escape', 27], ShiftLeft: ['Shift', 16], ControlLeft: ['Control', 17], Tab: ['Tab', 9] };
const down = (code) => send('Input.dispatchKeyEvent', { type: code === 'Space' ? 'keyDown' : 'rawKeyDown', code, key: KEYS[code][0], windowsVirtualKeyCode: KEYS[code][1] });
const up = (code) => send('Input.dispatchKeyEvent', { type: 'keyUp', code, key: KEYS[code][0], windowsVirtualKeyCode: KEYS[code][1] });
const tap = async (code) => { await down(code); await sleep(40); await up(code); };
const click = async (sel) => {
  const [x, y] = await ev(`(() => { const el = document.querySelector(${JSON.stringify(sel)}); el.scrollIntoView({block: 'center'}); const r = el.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
  for (const type of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 });
};
const shot = async (name) => { if (!SHOTS) return; fs.mkdirSync(SHOTS, { recursive: true }); const r = await send('Page.captureScreenshot', { format: 'png' }); fs.writeFileSync(path.join(SHOTS, name + '.png'), Buffer.from(r.data, 'base64')); };
const check = (name, ok, detail = '') => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail ? '  (' + detail + ')' : ''}`); if (!ok) failed++; };
const P = (expr) => ev(`(() => { const p = window.P1.player; return ${expr}; })()`);
const place = (x, z, yaw, pitch) => ev(`Object.assign(window.P1.player, {x: ${x}, z: ${z}, yaw: ${yaw}, pitch: ${pitch}}), 0`);
const fps = (ms) => ev(`new Promise((res) => { let n = 0; const t0 = performance.now(); const f = () => { n++; if (performance.now() - t0 < ${ms}) requestAnimationFrame(f); else res(Math.round(n * 1000 / (performance.now() - t0))); }; requestAnimationFrame(f); })`);
const state = () => ev(`fetch('/api/state').then((r) => r.json())`);

await send('Runtime.enable'); send('Inspector.enable'); await send('Page.enable');
await send('Page.navigate', { url: URL_ }); await sleep(3000);
check('page loads, patient list shows', (await ev(`document.querySelectorAll('#persona-list .persona').length`)) === 10);
const renderer = await ev(`(() => { const g = document.createElement('canvas').getContext('webgl2'); const e = g && g.getExtension('WEBGL_debug_renderer_info'); return g ? (e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'webgl2') : 'none'; })()`);
check('WebGL2 available', renderer !== 'none', renderer);
check('browser voice starts off on desktop Linux', !/Linux/.test(await ev('navigator.userAgent')) || (await ev(`document.getElementById('btn-voice').textContent`)) === 'Voice: off');

// ---- start a manual case; controls
await click('#btn-start'); await sleep(1500);
check('start screen closes', await ev(`document.getElementById('start').classList.contains('hidden')`));
await place(0.9, 1.6, 0.72, -0.16);
await ev(`document.querySelector('#hud-bottom [data-speed="20"]').focus()`);
await down('Space'); await sleep(120); const yMid = await P('p.y'); await up('Space'); await sleep(700);
check('Space jumps and lands', yMid > 0.2 && (await P('p.y')) === 0, `height ${yMid.toFixed(2)} m mid-jump`);
check('Space does not press the focused button', (await state()).speed === 1);
await down('KeyC'); await sleep(400); const hC = await P('p.h'); await up('KeyC'); await sleep(400);
check('C crouches and stands', hC < 1.35 && (await P('p.h')) > 1.6, `eye ${hC.toFixed(2)} m crouched`);
await down('ControlLeft'); await sleep(400); const hK = await P('p.h'); await up('ControlLeft'); await sleep(400);
check('Ctrl crouches', hK < 1.35);
const speedOf = async (codes) => { await place(0, 0, Math.PI / 2, 0); for (const c of codes) await down(c); await sleep(400); const v = await P('p.speed'); for (const c of codes.reverse()) await up(c); await sleep(200); return v; };
const walk = await speedOf(['KeyW']), run = await speedOf(['ShiftLeft', 'KeyW']), sneak = await speedOf(['KeyC', 'KeyW']);
check('Shift sprints, C sneaks', run > walk && sneak < walk, `walk ${walk} m/s, sprint ${run}, sneak ${sneak}`);
await place(0, 0, Math.PI / 2, 0); await tap('KeyW'); await sleep(80); await down('KeyW'); await sleep(300); const dbl = await P('p.speed'); await up('KeyW');
check('double-tap W sprints', dbl > walk, `${dbl} m/s`);
await sleep(300);

// ---- third person
check('avatar hidden in first person', !(await ev('window.P1.avatar.root.visible')));
await tap('KeyV'); await sleep(300);
const camDist = await ev(`(() => { const p = window.P1.player, c = window.P1.camera.position; return Math.hypot(c.x - p.x, c.z - p.z); })()`);
check('V: third person behind, avatar visible', (await P('p.view')) === 1 && (await ev('window.P1.avatar.root.visible')) && camDist > 1, `camera ${camDist.toFixed(1)} m away`);
await shot('third_person_behind');
await tap('KeyV'); await sleep(300); check('V again: third person in front', (await P('p.view')) === 2); await shot('third_person_front');
await place(-6.6, 4.6, Math.PI * 0.75, 0); await tap('KeyV'); await tap('KeyV'); await sleep(300);   // back up into a corner
const c = await ev('[window.P1.camera.position.x, window.P1.camera.position.z]');
check('third-person camera stays inside the room', c[0] > -7 && c[0] < 7 && c[1] > -5 && c[1] < 5, c.map((v) => v.toFixed(2)).join(', '));
await place(-2.4, -0.3, 0, -0.45); await sleep(300);
check('E target found in third person', (await ev('window.P1.focused()')) === 'hc');
await tap('KeyE'); await sleep(400);
check('E opens the equipment panel in third person', await ev(`!document.getElementById('panel').classList.contains('hidden')`), await ev(`document.getElementById('panel-title').textContent`));
await tap('Escape'); await sleep(200);
check('Esc closes the panel', await ev(`document.getElementById('panel').classList.contains('hidden')`));
await tap('KeyV'); await tap('KeyV'); await sleep(200);
check('V cycles back to first person', (await P('p.view')) === 0);
check('frame rate', (await fps(2000)) >= 30, `${await fps(2000)} fps`);

// ---- smash mode: Space jumps, F and click swing, own body is never smashed
await tap('KeyV'); await sleep(100); await tap('KeyB'); await sleep(600);
check('B enters smash mode, forces first person', (await ev('window.P1.smash.state.on')) && !(await ev('window.P1.avatar.root.visible')));
await tap('Space'); await sleep(100);
check('Space jumps in smash mode instead of swinging', (await ev('window.P1.smash.state.swingT')) < 0);
await tap('KeyF'); await sleep(60);
check('F swings the bat', (await ev('window.P1.smash.state.swingT')) >= 0);
await sleep(600);
await send('Page.reload'); await sleep(3000);
// a running case asks before the tab closes (Ctrl+W cannot be blocked, and Ctrl is a crouch key)
await click('#btn-start'); await sleep(800); await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 800, y: 400, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 800, y: 400, button: 'left', clickCount: 1 });
dialogs.length = 0; await send('Page.reload'); await sleep(3000);
check('leaving a running case asks first', dialogs.includes('beforeunload'), dialogs.join(',') || 'no dialog');

// ---- touch buttons on a phone-sized touch screen
await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
await send('Emulation.setEmitTouchEventsForMouse', { enabled: true, configuration: 'mobile' });
await send('Page.reload'); await sleep(3000);
await ev(`document.getElementById('btn-start').click()`); await sleep(1200);
check('touch buttons shown on a touch screen', await ev(`getComputedStyle(document.getElementById('touch-btns')).display === 'flex'`));
const touchAt = async (sel, type) => { const [x, y] = await ev(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`); await send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] }); };
await touchAt('[data-t="crouch"]', 'touchStart'); await touchAt('[data-t="crouch"]', 'touchEnd'); await sleep(400);
check('touch Crouch toggles crouch', (await P('p.h')) < 1.35);
await touchAt('[data-t="crouch"]', 'touchStart'); await touchAt('[data-t="crouch"]', 'touchEnd'); await sleep(400);
await touchAt('[data-t="jump"]', 'touchStart'); await sleep(120); const ty = await P('p.y'); await touchAt('[data-t="jump"]', 'touchEnd');
check('touch Jump jumps', ty > 0.1);
await touchAt('[data-t="view"]', 'touchStart'); await touchAt('[data-t="view"]', 'touchEnd'); await sleep(200);
check('touch View switches camera', (await P('p.view')) === 1);
await touchAt('[data-t="view"]', 'touchStart'); await touchAt('[data-t="view"]', 'touchEnd');
await touchAt('[data-t="view"]', 'touchStart'); await touchAt('[data-t="view"]', 'touchEnd'); await sleep(200);
await place(0.9, 1.6, Math.PI / 2, 0); const x0 = await P('p.x');   // open floor, facing -x
const [mx, my] = await ev(`(() => { const r = document.getElementById('touch-move').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()`);
await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: mx, y: my }] });
await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: mx, y: my - 40 }] }); await sleep(500);
await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
check('touch move pad still walks you forward', (await P('p.x')) < x0 - 0.3, `moved ${(x0 - (await P('p.x'))).toFixed(2)} m`);
await send('Emulation.setEmitTouchEventsForMouse', { enabled: false }); await send('Emulation.clearDeviceMetricsOverride'); await send('Emulation.setTouchEmulationEnabled', { enabled: false });
await send('Page.reload'); await sleep(3000);

// ---- full expert case
if (FULL) {
  await click('#btn-watch'); await sleep(1200); await click('#hud-bottom [data-speed="20"]');
  const t0 = Date.now(); const phases = new Set();
  while (Date.now() - t0 < 360000) {
    const s = await state(); phases.add(s.phase);
    if (await ev(`!document.getElementById('debrief').classList.contains('hidden')`)) break;
    await sleep(1000);
  }
  const s = await state();
  check('expert case at 20x reaches the debrief', await ev(`!document.getElementById('debrief').classList.contains('hidden')`), `${Math.round((Date.now() - t0) / 1000)} s, ${phases.size} phases`);
  check('expert score 100', s.score.score === 100, `score ${s.score.score}, callouts ${s.score.callouts.made}/${s.score.callouts.due}`);
  await shot('debrief');
}

check('no page errors', problems.length === 0, problems.slice(0, 3).join(' | '));
console.log(failed ? `\n${failed} check(s) failed` : '\nall checks passed');
done(failed ? 1 : 0);
