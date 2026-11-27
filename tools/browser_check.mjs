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
if (process.getuid?.() === 0) flags.push('--no-sandbox');      // Chrome refuses to run as root otherwise (containers, CI)
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
const KEYS = { F5: ['F5', 116], F9: ['F9', 120], Enter: ['Enter', 13], Space: [' ', 32], KeyW: ['w', 87], KeyS: ['s', 83], KeyC: ['c', 67], KeyV: ['v', 86], KeyE: ['e', 69], KeyB: ['b', 66], KeyF: ['f', 70], KeyH: ['h', 72], Escape: ['Escape', 27], ShiftLeft: ['Shift', 16], ControlLeft: ['Control', 17], Tab: ['Tab', 9] };
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
const act = (a) => ev(`fetch('/api/action', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: ${JSON.stringify(JSON.stringify(a))}}).then((r) => r.json())`);

await send('Runtime.enable'); send('Inspector.enable'); await send('Page.enable');
// without a GPU the high tier is a slideshow in software rendering, so the timing checks pin the plain tier
const MAIN = URL_ + (process.argv.includes('--gpu') ? '/' : '/?gfx=low');
await send('Page.navigate', { url: MAIN }); await sleep(3000);
check('page loads, patient list shows', (await ev(`document.querySelectorAll('#persona-list .persona').length`)) === 10);
const renderer = await ev(`(() => { const g = document.createElement('canvas').getContext('webgl2'); const e = g && g.getExtension('WEBGL_debug_renderer_info'); return g ? (e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'webgl2') : 'none'; })()`);
check('WebGL2 available', renderer !== 'none', renderer);
check('browser voice starts off on desktop Linux', !/Linux/.test(await ev('navigator.userAgent')) || (await ev(`document.getElementById('btn-voice').textContent`)) === 'Voice: off');

// ---- name is required, levels gate the harder patients
const setName = (n) => ev(`(() => { const e = document.getElementById('student-name'); e.value = ${JSON.stringify(n)}; e.dispatchEvent(new Event('input')); })()`);
await setName(''); await sleep(500);
await click('#btn-start'); await sleep(600);
check('a run cannot start without a name', !(await ev(`document.getElementById('start').classList.contains('hidden')`)) && /name/i.test(await ev(`document.getElementById('start-error').textContent`)));
await setName('Check Bot ' + Date.now().toString(36).slice(-4)); await sleep(900);
check('patients are grouped into levels with later levels locked', (await ev(`document.querySelectorAll('#persona-list .lvl-head').length`)) === 4 && (await ev(`document.querySelectorAll('#persona-list .persona.locked').length`)) === 9);
await click('#persona-list .persona.locked'); await sleep(200); await click('#btn-start'); await sleep(600);
check('a locked patient cannot be started', !(await ev(`document.getElementById('start').classList.contains('hidden')`)) && /locked/i.test(await ev(`document.getElementById('start-error').textContent`)));
await click('#persona-list .persona:not(.locked)'); await sleep(200);
check('graphics tier is shown and the addon modules loaded', /^Graphics: (low|med|high)$/.test(await ev(`document.getElementById('btn-gfx').textContent`)) && (await ev(`!!window.P1.gfx`)));

// ---- start a manual case; controls
await click('#btn-start'); await sleep(1500);
check('the student name is on the session', /^Check Bot/.test((await state()).session.student));
check('pump RPM is in the always-on readouts', (await ev(`[...document.querySelectorAll('#vitals .k')].map((e) => e.textContent).join('|')`)).includes('Pump RPM'));
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

// ---- pump console: roller modules, dials with light rings, stop buttons, roller heads (docs/LAB_FIDELITY.md 1)
// stand in front of the cart and aim the centre of the view at a control
const aimAt = async (id) => {
  const [x, y, z] = await ev(`(() => { const c = window.P1.console.controls.find((k) => k.id === '${id}'); const v = c.hit.getWorldPosition(c.hit.position.clone()); return [v.x, v.y, v.z]; })()`);
  const px = x, pz = z + 0.75, eyeY = await P('p.h');
  await place(px, pz, Math.atan2(-(x - px), -(z - pz)), Math.atan2(y - eyeY, Math.hypot(x - px, z - pz))); await sleep(350);
};
const ctlIds = await ev(`window.P1.console.controls.map((c) => c.id).sort().join(',')`);
check('console has centrifugal dial and roller modules with dials and stop buttons', ctlIds === 'art_dial,art_stop,cf_dial,cp_dial,cp_stop,suck_dial,suck_stop,vent_dial,vent_stop', ctlIds);
await aimAt('cp_dial');
check('aiming at a dial names it and says how to turn it', (await ev('window.P1.control()')) === 'cp_dial' && /Cardioplegia pump.*wheel or drag/.test(await ev(`document.getElementById('hint').textContent`)));
const cp0 = (await state()).controls.cp_flow;
for (let i = 0; i < 3; i++) { await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 800, y: 450, deltaX: 0, deltaY: -100 }); await sleep(60); }
await sleep(500);
check('mouse wheel turns the cardioplegia dial', (await state()).controls.cp_flow === cp0 + 30, `${cp0} -> ${(await state()).controls.cp_flow} mL/min`);
await aimAt('cf_dial');
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 800, y: 450, button: 'left', clickCount: 1 });
for (let i = 1; i <= 8; i++) { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 800, y: 450 - i * 10, button: 'left', buttons: 1 }); await sleep(30); }
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 800, y: 370, button: 'left', clickCount: 1 }); await sleep(500);
const rpmSet = (await state()).controls.rpm_set;
check('dragging the centrifugal dial turns it, not the view', rpmSet > 0 && (await ev('window.P1.control()')) === 'cf_dial', `rpm set ${rpmSet}`);
await act({ type: 'set', key: 'rpm_set', value: 0 }); await act({ type: 'set', key: 'cp_flow', value: cp0 });
await aimAt('suck_stop');
const spin0 = await ev(`window.P1.console.heads.find((h) => h.name === 'sucker').rotor.rotation.y`);
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 800, y: 450, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 800, y: 450, button: 'left', clickCount: 1 }); await sleep(900);
const sOn = await state();
check('clicking a stop button starts and stops that pump', sOn.controls.sucker && sOn.rollers.sucker.rpm > 0, `sucker ${sOn.rollers.sucker.rpm} RPM, ${sOn.rollers.sucker.tubing}`);
check('the roller head turns at its pump speed', Math.abs((await ev(`window.P1.console.heads.find((h) => h.name === 'sucker').rotor.rotation.y`)) - spin0) > 0.2);
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 800, y: 450, button: 'left', clickCount: 1 });
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 800, y: 450, button: 'left', clickCount: 1 }); await sleep(500);
check('...and clicking it again stops it', !(await state()).controls.sucker);
// ---- patient monitor (docs/LAB_FIDELITY.md 2)
const mon = await ev(`(() => { const c = window.P1.monitor.canvas, d = c.getContext('2d').getImageData(10, 98 + 2 * 122 + 22, 760, 92).data; let pa = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i] > 200 && d[i + 1] > 180 && d[i + 2] < 120) pa++; return { pa, shared: window.P1.monitor.shared() }; })()`);
const ms = await state();
check('patient monitor draws the PA trace and the wall repeats it', mon.pa > 200 && mon.shared, `${mon.pa} PA trace pixels`);
check('monitor values come from the model', ['pap', 'pap_sys', 'art_sys', 'urine_ml', 't_cp_water', 'mode'].every((k) => k in ms) && 'last_act2' in ms && ms.persona.age > 0, `PA ${ms.pap_sys}/${ms.pap_dia} (${ms.pap}), mode ${ms.mode}`);

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

// ---- save / load and sessions (unique names per run; never overwrites a save it did not make)
const saves = () => ev(`fetch('/api/saves').then((r) => r.json()).then((d) => d.saves)`);
const visible = (id) => ev(`!document.getElementById('${id}').classList.contains('hidden')`);
const TAG = 'Browser check ' + Date.now().toString(36), TAG_ID = TAG.toLowerCase().replace(/[^a-z0-9]+/g, '-');
const rowOf = (text) => ev(`[...document.querySelectorAll('#saves-body .sv-row')].findIndex((r) => r.textContent.includes(${JSON.stringify(text)}))`);
await click('#btn-start'); await sleep(1000);
await ev(`fetch('/api/action', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({type: 'heparin', units: 30000})})`);
await ev('window.__marker = 42');
const hadQuick = (await saves()).some((x) => x.id === 'quick-save');
if (hadQuick) {
  await tap('F5'); await sleep(600);
  check('F5 with an existing quick save asks before overwriting (kept yours: cancelled)', await visible('confirm'));
  await tap('Escape'); await sleep(300);
  check('F5 did not reload the page', (await ev('window.__marker')) === 42);
} else {
  await tap('F5'); await sleep(800);
  check('F5 quick-saves without reloading the page', (await ev('window.__marker')) === 42 && (await saves()).some((x) => x.id === 'quick-save'),
    await ev(`document.getElementById('toast').textContent`));
  await tap('F5'); await sleep(600);
  check('F5 again asks before overwriting', await visible('confirm'), (await ev(`document.getElementById('confirm-body').innerText`)).split('\n')[0]);
  await tap('Enter'); await sleep(600);
  check('confirming overwrites the quick save', !(await visible('confirm')) && (await saves()).filter((x) => x.id === 'quick-save').length === 1);
}
await tap('F9'); await sleep(800);
check('F9 opens Save / Load', await visible('saves'));
await ev(`document.getElementById('sv-name').value = ${JSON.stringify(TAG)}; document.getElementById('sv-desc').value = 'typed description'`);
await click('#sv-save'); await sleep(900);
check('save with a typed description', (await saves()).some((x) => x.id === TAG_ID && x.description === 'typed description') && !(await visible('confirm')));
const meta = await ev(`[...document.querySelectorAll('#saves-body .sv-row')].find((r) => r.textContent.includes(${JSON.stringify(TAG)})).querySelector('.sv-meta').textContent`);
check('saves list shows name, persona, phase, case time, date', /Standard adult CABG · Before bypass · case time \d+:\d\d · score [\d.]+ · /.test(meta), meta);
await ev(`document.getElementById('sv-name').focus()`);   // Save / Load is still open
const before = await P('[p.x, p.z]'); await down('KeyW'); await sleep(400); await up('KeyW'); await down('KeyS'); await sleep(300); await up('KeyS');
const after = await P('[p.x, p.z]');
check('keys typed while Save / Load is open do not move the player', before[0] === after[0] && before[1] === after[1]);
await click(`#saves-body .sv-row:nth-child(${(await rowOf(TAG)) + 1}) [data-load]`); await sleep(1200);
const st = await state();
check('Load restores the save and marks the run as practice', !(await visible('saves')) && st.session.practice && st.session.resumed_from.id === TAG_ID && st.speed === 0,
  await ev(`document.getElementById('toast').textContent`));
await tap('F9'); await sleep(800);
await click(`#saves-body .sv-row:nth-child(${(await rowOf(TAG)) + 1}) [data-del]`); await sleep(500);
check('Delete asks first', await visible('confirm'), (await ev(`document.getElementById('confirm-body').innerText`)).split('\n')[0]);
await click('#cf-ok'); await sleep(800);
check('Delete removes the save', !(await saves()).some((x) => x.id === TAG_ID));
if (!hadQuick) await ev(`fetch('/api/saves/quick-save', {method: 'DELETE'})`);   // tidy up what this run made
await tap('Escape'); await sleep(300);
check('Esc closes Save / Load', !(await visible('saves')));
await click('#btn-sessions'); await sleep(900);
check('Sessions screen lists sessions', (await ev(`document.querySelectorAll('#sessions-body .sv-row').length`)) > 0);
await click('#sessions-body [data-open="0"]'); await sleep(900);
const body = await ev(`document.getElementById('sessions-body').innerText`);
check('session opens to summary and timeline', ['What was done', 'What went well', 'What was flagged', 'Three things to improve', 'Timeline'].every((h) => body.includes(h)));
await tap('Escape'); await sleep(300);

// ---- H info panel
await tap('KeyH'); await sleep(900);
const help = await ev(`({ open: !document.getElementById('help').classList.contains('hidden'), text: document.getElementById('help-body').innerText,
  hud: [...document.querySelectorAll('#objectives li')].map((li) => li.textContent), steps: [...document.querySelectorAll('#help .steps li')].map((li) => li.textContent),
  use: document.querySelectorAll('#help [data-panel]').length, phase: document.getElementById('phase-title').textContent })`);
check('H opens the info panel on the current step', help.open && help.text.includes(help.phase) && help.text.includes('Do this'), help.phase);
check('info panel steps match the HUD objectives', help.steps.length > 0 && JSON.stringify(help.steps) === JSON.stringify(help.hud), `${help.steps.length} steps`);
check('info panel has why, use, callout, mistakes, whole case', ['Use', 'Tell the surgeon', 'Common mistakes', 'The whole case'].every((h) => help.text.includes(h)) && help.use > 0);
const hx = await P('p.x'); await down('KeyW'); await sleep(400); await up('KeyW');
check('keys typed while the info panel is open do not move the player', Math.abs((await P('p.x')) - hx) < 0.01);
await click('#help [data-phase="REWARM"]'); await sleep(300);
check('whole-case list previews another step', (await ev(`document.getElementById('help-body').innerText`)).includes('Preview: step 10'));
await click('#help-now'); await sleep(300);
await click('#help .where [data-panel]'); await sleep(500);
check('Use button opens that equipment panel', !(await visible('help')) && (await visible('panel')), await ev(`document.getElementById('panel-title').textContent`));
await tap('Escape'); await sleep(200); await tap('KeyH'); await sleep(500); await tap('Escape'); await sleep(300);
check('Esc closes the info panel', !(await visible('help')));
await shot('help');
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
  const db = await ev(`document.getElementById('debrief-body').innerText`);
  check('debrief scoring is the rubric report, with no per-finding deductions', db.includes('Where you lost points') && !db.includes('Why this score') && !db.includes('What to fix') && !/nothing deducted|minus/i.test(db));
  for (let i = 0; i < 20 && !(await ev(`document.querySelectorAll('#debrief .trend svg').length`)); i++) await sleep(250);
  const db2 = await ev(`document.getElementById('debrief-body').innerText`);
  check('debrief has phase by phase, improvements and the expert benchmark', ['Phase by phase', 'What went well', 'You and the expert benchmark', 'Expert autopilot'].every((h) => db2.includes(h)));
  check('debrief has trend charts', (await ev(`document.querySelectorAll('#debrief .trend svg path[d^="M"]').length`)) === 4);
  check('debrief phase table marks every callout said', (await ev(`document.querySelectorAll('#debrief table.phases .ok').length`)) === 13);
  await shot('debrief');
  check('debrief shows standing, leaderboard and analysis links, and a quiz', (await ev(`!!document.getElementById('btn-board') && !!document.getElementById('btn-analyze')`)) && (await ev(`document.querySelectorAll('#quiz-box .qz').length`)) === 4);
  check('debrief scores against the rubric and explains lost points', await ev(`!!document.getElementById('rb-outcome') && document.getElementById('rubric-report').innerText.includes('Where you lost points') && document.querySelectorAll('.rb-sec-d').length === 6`), await ev(`document.getElementById('rb-outcome').innerText.slice(0, 120)`));
  check('expert runs are not ranked', (await ev(`document.getElementById('debrief-game').innerText`)).includes('not ranked'));
  await click('#btn-summary'); await sleep(900);
  check('debrief links to the session summary', (await ev(`document.getElementById('sessions-body').innerText`)).includes('Three things to improve'));
  await tap('Escape'); await sleep(300);
  // resume from the last auto-save and finish: the debrief must say practice
  await tap('F9'); await sleep(900);
  const ai = await ev(`[...document.querySelectorAll('.sv-row')].findIndex((r) => r.textContent.includes('Auto: Off bypass'))`);
  check('auto-saves are labelled by phase', ai >= 0);
  await click(`.sv-row:nth-child(${ai + 1}) [data-load]`); await sleep(1200);
  await click('#hud-bottom [data-speed="20"]');
  for (let i = 0; i < 60 && !(await ev(`!document.getElementById('debrief').classList.contains('hidden')`)); i++) await sleep(1000);
  check('resumed run debrief is marked practice', (await ev(`document.getElementById('debrief-body').innerText`)).includes('Practice (resumed from save'));
  await shot('debrief_practice');
}

// ---- leaderboard and run analysis pages
await send('Page.navigate', { url: URL_ + '/leaderboard' }); await sleep(1800);
check('leaderboard page renders levels and the board', (await ev(`document.querySelectorAll('#levels .lvl').length`)) === 4 && (await ev(`!!document.getElementById('rows')`)));
const lastRun = await ev(`fetch('/api/sessions').then((r) => r.json()).then((d) => (d.sessions.find((s) => s.status === 'complete') || {}).id || '')`);
if (lastRun) {
  await send('Page.navigate', { url: URL_ + '/run?id=' + lastRun }); await sleep(2200);
  check('run analysis draws its charts and quiz', (await ev(`document.querySelectorAll('canvas.chart').length`)) === 5 && (await ev(`document.getElementById('quiz').children.length`)) > 0);
  await shot('run_analysis');
}

// ---- dashboard page (a separate page; must render with no AI services running and keep refreshing)
await send('Page.navigate', { url: URL_ + '/dashboard' }); await sleep(3500);
const dash = await ev(`({ polls: window.P1_DASH?.polls || 0, failures: window.P1_DASH?.failures, rows: document.querySelectorAll('#models tbody tr').length,
  status: [...document.querySelectorAll('#models tbody .pill')].map((p) => p.textContent), sim: document.getElementById('sim').innerText,
  sys: document.getElementById('sys').innerText, build: document.getElementById('build').innerText })`);
check('dashboard refreshes every second', dash.polls >= 3 && dash.failures === 0, `${dash.polls} polls in 3.5 s`);
check('dashboard lists the four AI services', dash.rows === 4, dash.status.join(', '));
check('dashboard shows simulator, system and build', ['Steps / s', 'Real-time factor', 'Tick lag', 'Clients'].every((k) => dash.sim.includes(k))
  && ['CPU', 'Unified memory', 'GPU', 'Disk free'].every((k) => dash.sys.includes(k)) && dash.build.includes('Commit'));
await shot('dashboard');

check('no page errors', problems.length === 0, problems.slice(0, 3).join(' | '));
console.log(failed ? `\n${failed} check(s) failed` : '\nall checks passed');
done(failed ? 1 : 0);
