// Heart-lung machine console laid out like the lab's (docs/LAB_FIDELITY.md section 1), by function, not by any
// vendor's design: a centrifugal pump console on its own mast (flow, RPM, cardiac index, line pressure, status
// icons, one speed dial with a light ring), a row of roller pump modules on the base (arterial roller idle,
// cardioplegia, a double module for sucker and vent), each with its own screen, dial, light ring and stop button,
// roller heads under clear covers that turn at the speed the model reports, a mast column of three small displays
// (pressures with limits, timers, temperatures) and a tray of clamps, syringes and vials.
// Display and input only: values come from /api/state, dials and buttons post the same 'set' actions the panels do.
import * as THREE from 'three';

const fmt = (v, d = 0) => (v === null || v === undefined ? '--' : Number(v).toFixed(d));
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const SWEEP = Math.PI * 1.5;                       // a dial turns through 270 degrees from 0 to full scale

export function buildConsole({ hlm, mat, box, cyl, add, screen, glass, text }) {
  const steel = mat(0xaab2bb, { metalness: 0.7, roughness: 0.3 }), white = mat(0xeef1f4, { roughness: 0.4 }),
    grey = mat(0x5d6670, { roughness: 0.5 }), black = mat(0x15181c), base = mat(0x3d4f72, { roughness: 0.5 }),
    knobM = mat(0x2a2f36, { roughness: 0.35 }), red = mat(0xc62828, { roughness: 0.4 }), trayM = mat(0xc9ced4, { metalness: 0.5, roughness: 0.35 });
  const controls = [], heads = [], screens = {};
  const hitM = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false });

  // base and wheels
  box(hlm, 1.5, 0.34, 0.66, base, 0, 0.21, 0);
  for (const [wx, wz] of [[-0.66, -0.27], [0.66, -0.27], [-0.66, 0.27], [0.66, 0.27]]) cyl(hlm, 0.05, 0.05, 0.04, black, wx, 0.05, wz).rotation.z = Math.PI / 2;

  // a dial on a front face (axis toward the student), its light ring and an invisible, easier-to-aim hit disk
  function dial(parent, x, y, z, r, def) {
    const knob = cyl(parent, r, r * 1.05, 0.026, knobM, x, y, z + 0.013); knob.rotation.x = Math.PI / 2;
    const mark = box(parent, 0.004, r * 0.8, 0.004, mat(0xffffff), 0, 0, 0); knob.add(mark); mark.position.set(0, 0.014, -r * 0.45); mark.rotation.x = -Math.PI / 2;
    const back = add(parent, new THREE.TorusGeometry(r * 1.42, r * 0.11, 6, 40), mat(0x1c2a3a), x, y, z + 0.004, false);
    const ringM = new THREE.MeshBasicMaterial({ color: def.color || 0x4fb3ff, toneMapped: false });
    const ring = add(parent, new THREE.TorusGeometry(r * 1.42, r * 0.13, 6, 40, 0.001), ringM, x, y, z + 0.006, false);
    const hit = add(parent, new THREE.CircleGeometry(r * 1.9, 16), hitM, x, y, z + 0.03, false);
    const c = { ...def, kind: 'dial', knob, ring, back, hit, r, frac: -1 };
    hit.userData.control = c; controls.push(c); return c;
  }
  function stopButton(parent, x, y, z, r, def, m = red) {
    const b = cyl(parent, r, r, 0.014, m.clone(), x, y, z + 0.007); b.rotation.x = Math.PI / 2;
    const hit = add(parent, new THREE.CircleGeometry(r * 1.8, 12), hitM, x, y, z + 0.02, false);
    const c = { ...def, kind: 'button', mesh: b, hit }; hit.userData.control = c; controls.push(c); return c;
  }
  // a roller head on top of a module: raceway, two-roller rotor, clear cover
  function rollerHead(x, z, r, name) {
    const y = 0.56;
    const race = add(hlm, new THREE.CylinderGeometry(r, r, 0.05, 32, 1, true), grey, x, y + 0.025, z); race.material.side = THREE.DoubleSide;
    cyl(hlm, r, r, 0.006, black, x, y + 0.003, z, 32);
    const rotor = new THREE.Group(); rotor.position.set(x, y + 0.03, z); hlm.add(rotor);
    box(rotor, r * 1.7, 0.012, 0.028, steel, 0, 0, 0);
    for (const s of [-1, 1]) cyl(rotor, 0.016, 0.016, 0.036, mat(0xe8eaed, { roughness: 0.3 }), s * r * 0.78, 0, 0, 16);
    cyl(rotor, 0.018, 0.018, 0.03, steel, 0, 0.004, 0, 16);
    cyl(hlm, r + 0.008, r + 0.008, 0.07, glass(0xf2f6fa, 0.22), x, y + 0.04, z, 32);   // clear cover
    heads.push({ name, rotor });
  }
  // a roller module: housing, small screen, dial with light ring, stop button
  function module(x, w, defs) {
    box(hlm, w - 0.01, 0.18, 0.34, white, x, 0.47, 0.12);
    const half = defs.length === 2 ? w / 2 : w;
    defs.forEach((d, k) => {
      const hx = defs.length === 2 ? x - w / 4 + k * half : x, small = defs.length === 2;
      const sw = small ? 0.085 : 0.12, sh = small ? 0.058 : 0.072;
      box(hlm, sw + 0.012, sh + 0.012, 0.006, black, hx - (small ? 0.032 : 0.055), 0.505, 0.291);
      screens[d.name] = screen(hlm, sw, sh, 256, 176, hx - (small ? 0.032 : 0.055), 0.505, 0.295);
      d.dial = dial(hlm, hx + (small ? 0.048 : 0.07), 0.47, 0.29, small ? 0.02 : 0.026, d.dialDef);
      d.stop = stopButton(hlm, hx - (small ? 0.032 : 0.055), 0.423, 0.29, small ? 0.011 : 0.013, d.stopDef);
      rollerHead(hx, 0.1, small ? 0.068 : 0.092, d.name);
    });
  }
  const set = (key) => ({ key });
  module(-0.55, 0.3, [{ name: 'arterial',
    dialDef: { id: 'art_dial', label: 'Arterial roller pump', inert: 'idle: the centrifugal pump is the arterial pump' },
    stopDef: { id: 'art_stop', label: 'Arterial roller stop', inert: 'idle: the centrifugal pump is the arterial pump' } }]);
  module(-0.23, 0.3, [{ name: 'cardioplegia',
    dialDef: { id: 'cp_dial', label: 'Cardioplegia pump', ...set('cp_flow'), min: 0, max: 500, step: 10, unit: 'mL/min', color: 0xff9a3c },
    stopDef: { id: 'cp_stop', label: 'Cardioplegia', toggle: 'cp_on' } }]);
  module(0.12, 0.36, [
    { name: 'sucker', dialDef: { id: 'suck_dial', label: 'Sucker pump', ...set('sucker_max'), min: 0, max: 500, step: 10, unit: 'mL/min' },
      stopDef: { id: 'suck_stop', label: 'Sucker pump', toggle: 'sucker' } },
    { name: 'vent', dialDef: { id: 'vent_dial', label: 'Vent pump', ...set('vent_max'), min: 0, max: 500, step: 5, unit: 'mL/min' },
      stopDef: { id: 'vent_stop', label: 'Vent pump', toggle: 'root_vent' } }]);

  // centrifugal pump console on its own mast
  cyl(hlm, 0.022, 0.022, 1.12, steel, -0.66, 0.94, -0.22);
  const cc = new THREE.Group(); cc.position.set(-0.6, 1.3, -0.12); cc.rotation.x = -0.14; hlm.add(cc);
  box(cc, 0.36, 0.3, 0.1, white, 0, 0, 0);
  box(cc, 0.31, 0.175, 0.008, black, 0, 0.045, 0.05);
  screens.centrifugal = screen(cc, 0.29, 0.16, 512, 284, 0, 0.045, 0.055);
  dial(cc, 0.115, -0.093, 0.05, 0.033, { id: 'cf_dial', label: 'Centrifugal pump speed', ...set('rpm_set'), min: 0, max: 4500, step: 50, unit: 'RPM' });
  // mast column: three small displays, and the data screen above them
  cyl(hlm, 0.025, 0.025, 1.95, steel, -0.1, 1.33, -0.25);
  cyl(hlm, 0.012, 0.012, 0.62, steel, -0.12, 2.25, -0.22).rotation.z = Math.PI / 2;
  const mastY = [1.58, 1.39, 1.2];
  ['pressures', 'timers', 'temps'].forEach((n, k) => {
    const g = new THREE.Group(); g.position.set(-0.1, mastY[k], -0.19); g.rotation.x = -0.1; hlm.add(g);
    box(g, 0.24, 0.16, 0.03, black, 0, 0, -0.012);
    screens[n] = screen(g, 0.22, 0.14, 352, 224, 0, 0, 0.005);
    if (n !== 'timers') return;
    // the student's timers: start/stop (green) and reset (grey) beside each line
    box(g, 0.07, 0.15, 0.03, black, 0.152, 0, -0.012);
    [['bypass', 'Bypass timer', 0.019], ['clamp', 'Clamp timer', -0.016], ['cp', 'Cardioplegia timer', -0.051]].forEach(([k, label, y]) => {
      stopButton(g, 0.136, y, 0.004, 0.009, { id: 'tm_' + k, label, timer: k, op: 'toggle' }, mat(0x2e9e5b, { roughness: 0.4 }));
      stopButton(g, 0.168, y, 0.004, 0.009, { id: 'tm_' + k + '_reset', label, timer: k, op: 'reset' }, mat(0x8a939c, { roughness: 0.4 }));
    });
  });
  // tray: tubing clamps, syringes, drug vials
  box(hlm, 0.32, 0.02, 0.2, trayM, 0.52, 0.395, -0.17);
  for (const [cx, rz] of [[0.42, 0.5], [0.47, -0.3]]) {
    const cl = new THREE.Group(); cl.position.set(cx, 0.415, -0.2); cl.rotation.y = rz; hlm.add(cl);
    box(cl, 0.11, 0.008, 0.014, steel, 0, 0, 0); box(cl, 0.035, 0.012, 0.03, mat(0x2b2f35), -0.05, 0, 0);
  }
  for (const sx of [0.56, 0.6]) {
    const sy = cyl(hlm, 0.009, 0.009, 0.12, mat(0xf4f6f8, { transparent: true, opacity: 0.8 }), sx, 0.416, -0.12); sy.rotation.z = Math.PI / 2;
    const pl = cyl(hlm, 0.004, 0.004, 0.05, mat(0xffffff), sx + 0.08, 0.416, -0.12); pl.rotation.z = Math.PI / 2;
  }
  [0x3fa7ff, 0xffd24d, 0x2ecc71].forEach((c, k) => { cyl(hlm, 0.012, 0.012, 0.04, mat(0xeef6ff, { transparent: true, opacity: 0.7 }), 0.62 + k * 0.03, 0.425, -0.22, 14); cyl(hlm, 0.0125, 0.0125, 0.008, mat(c), 0.62 + k * 0.03, 0.449, -0.22, 14); });

  // ---- live values -----------------------------------------------------------------
  const local = {};                                   // a value just set by this client, shown until the server agrees
  const valueOf = (c, S) => { const l = local[c.key]; return l && performance.now() - l.t < 900 ? l.v : S.controls[c.key]; };
  function setRing(c, frac) {
    if (Math.abs(frac - c.frac) < 0.004) return;
    c.frac = frac; c.ring.geometry.dispose();
    c.ring.geometry = new THREE.TorusGeometry(c.r * 1.42, c.r * 0.13, 6, 40, Math.max(0.001, frac * SWEEP));
    c.ring.rotation.z = 1.25 * Math.PI - frac * SWEEP;   // the arc grows clockwise from lower left, like the pointer
    c.ring.visible = frac > 0.002;
  }
  function update(S, dt) {
    for (const c of controls) {
      if (c.kind === 'dial') {
        const frac = c.inert ? 0 : Math.max(0, Math.min(1, (valueOf(c, S) - c.min) / (c.max - c.min)));
        c.knob.rotation.y = SWEEP / 2 - frac * SWEEP;        // pointer at lower left at zero, lower right at full scale
        setRing(c, frac);
      } else if (c.toggle) {
        c.mesh.material.emissive?.setHex(S.controls[c.toggle] ? 0x000000 : 0x550000);
      } else if (c.timer && c.op === 'toggle') {
        c.mesh.material.emissive?.setHex(S.clocks[c.timer].run ? 0x1f7a3f : 0x000000);
      }
    }
    const R = S.rollers;
    for (const h of heads) h.rotor.rotation.y -= (R[h.name].rpm / 60) * 2 * Math.PI * dt;
  }

  // ---- screens -------------------------------------------------------------------
  const lim = (v, l) => (v > l ? '#ff5a5a' : '#e8f1ff');
  function icon(g, x, y, on, warn, draw, label) {
    g.fillStyle = on ? (warn ? '#c62828' : '#1f6b45') : '#16233a'; g.beginPath(); g.roundRect(x, y, 84, 52, 8); g.fill();
    g.strokeStyle = on ? '#fff' : '#3e5476'; g.fillStyle = on ? '#fff' : '#3e5476'; g.lineWidth = 3; draw(g, x + 42, y + 21);
    text(g, label, x + 42, y + 48, 13, on ? '#fff' : '#566b8c', 'center', 600);
  }
  function draw(S) {
    // centrifugal console
    let { ctx: g, t } = screens.centrifugal;
    g.fillStyle = '#0f2a57'; g.fillRect(0, 0, 512, 284);
    text(g, 'L/min', 18, 34, 22, '#9fbbe8', 'left', 600); text(g, fmt(S.flow, 2), 330, 118, 92, S.flow < -0.1 ? '#ff6b6b' : '#fff', 'right', 700);
    text(g, 'RPM', 350, 34, 22, '#9fbbe8', 'left', 600); text(g, fmt(S.rpm), 496, 88, 46, '#e6eeff', 'right', 700);
    text(g, 'CI', 350, 118, 18, '#9fbbe8', 'left', 600); text(g, fmt(S.ci, 2), 496, 118, 30, '#e6eeff', 'right', 700);
    text(g, 'ART LINE P', 18, 162, 18, '#9fbbe8', 'left', 600); text(g, `${fmt(S.line_p)} mmHg`, 330, 164, 34, lim(S.line_p, S.limits.line_p), 'right', 700);
    text(g, `limit ${S.limits.line_p}`, 496, 162, 16, '#7f9bc8', 'right', 500);
    const ic = [
      [S.controls.art_clamp, false, (c, x, y) => { c.beginPath(); c.moveTo(x - 14, y - 10); c.lineTo(x + 14, y + 10); c.moveTo(x + 14, y - 10); c.lineTo(x - 14, y + 10); c.stroke(); }, 'CLAMP'],
      [S.res < 300 && S.cannulated, true, (c, x, y) => { c.strokeRect(x - 10, y - 12, 20, 24); c.fillRect(x - 10, y + 4, 20, 8); }, 'LEVEL'],
      [S.line_p > S.limits.line_p, true, (c, x, y) => { c.beginPath(); c.moveTo(x, y - 13); c.lineTo(x + 13, y + 11); c.lineTo(x - 13, y + 11); c.closePath(); c.stroke(); }, 'PRESS'],
      [S.alarms.some(([, m]) => /Air/.test(m)), true, (c, x, y) => { c.beginPath(); c.arc(x - 5, y, 6, 0, 6.3); c.moveTo(x + 13, y - 5); c.arc(x + 8, y - 5, 5, 0, 6.3); c.stroke(); }, 'AIR'],
      [S.flow < -0.1, true, (c, x, y) => { c.beginPath(); c.moveTo(x + 13, y); c.lineTo(x - 13, y); c.moveTo(x - 5, y - 8); c.lineTo(x - 13, y); c.lineTo(x - 5, y + 8); c.stroke(); }, 'BACK'],
    ];
    ic.forEach(([on, warn, fn, label], k) => icon(g, 14 + k * 98, 214, !!on, warn, fn, label));
    t.needsUpdate = true;
    // roller modules
    for (const name of ['arterial', 'cardioplegia', 'sucker', 'vent']) {
      ({ ctx: g, t } = screens[name]); const r = S.rollers[name];
      g.fillStyle = r.on ? '#0e2f22' : '#121a22'; g.fillRect(0, 0, 256, 176);
      text(g, { arterial: 'ARTERIAL', cardioplegia: 'CARDIOPLEGIA', sucker: 'SUCKER', vent: 'VENT' }[name], 12, 30, 22, '#9fb7c8', 'left', 700);
      if (name === 'arterial') { text(g, 'IDLE', 244, 100, 50, '#56677a', 'right', 700); text(g, `${r.tubing}  0 RPM`, 12, 160, 22, '#6f8193'); }
      else {
        text(g, fmt(r.flow, 2), 200, 100, 56, r.on ? '#fff' : '#6f8193', 'right', 700); text(g, 'L/min', 206, 100, 20, '#9fb7c8');
        text(g, `${fmt(r.rpm)} RPM  ${fmt(r.pct)}%`, 12, 136, 22, r.on ? '#cfe' : '#6f8193');
        text(g, `${r.tubing}  set ${r.set}`, 12, 166, 20, '#9fb7c8', 'left', 500);
        text(g, r.on ? 'RUN' : 'STOP', 244, 30, 20, r.on ? '#6fe3a1' : '#ffb84d', 'right', 700);
      }
      t.needsUpdate = true;
    }
    // mast: pressures with limits
    ({ ctx: g, t } = screens.pressures);
    g.fillStyle = '#0a1622'; g.fillRect(0, 0, 352, 224); text(g, 'PRESSURES  mmHg', 14, 30, 20, '#7f93a8', 'left', 700);
    [['Art line', S.line_p, S.limits.line_p], ['CPG line', S.cp_pressure, S.limits.cp_pressure], ['Sinus', S.csp, S.limits.csp]].forEach(([k, v, l], i) => {
      const y = 76 + i * 58; text(g, k, 14, y, 20, '#b8c6d4', 'left', 500); text(g, fmt(v), 250, y, 34, lim(v, l), 'right', 700);
      text(g, `lim ${l}`, 340, y, 16, '#7f93a8', 'right', 500);
      g.fillStyle = '#1b2a38'; g.fillRect(14, y + 10, 324, 6); g.fillStyle = v > l ? '#ff5a5a' : '#4fb3ff'; g.fillRect(14, y + 10, 324 * Math.min(1, v / (l * 1.25)), 6);
      g.fillStyle = '#fff'; g.fillRect(14 + 324 / 1.25, y + 6, 2, 14);
    });
    t.needsUpdate = true;
    // mast: timers
    ({ ctx: g, t } = screens.timers);           // the student's own timers: nothing here runs unless they start it
    g.fillStyle = '#0a1622'; g.fillRect(0, 0, 352, 224); text(g, 'TIMERS', 14, 30, 20, '#7f93a8', 'left', 700);
    [['Bypass', 'bypass'], ['Cross-clamp', 'clamp'], ['Since CPG', 'cp']].forEach(([k, id], i) => {
      const c = S.clocks[id], y = 82 + i * 56;
      text(g, k, 14, y, 22, '#b8c6d4', 'left', 500);
      text(g, mmss(c.s), 338, y, 38, c.run ? (id === 'cp' && c.s > 1200 ? '#ffb84d' : '#6fe3a1') : '#7f93a8', 'right', 700);
      if (S.asked.includes(id)) text(g, 'ASKED', 150, y, 16, '#ffb84d', 'left', 700);
    });
    t.needsUpdate = true;
    // mast: temperatures
    ({ ctx: g, t } = screens.temps);
    g.fillStyle = '#0a1622'; g.fillRect(0, 0, 352, 224); text(g, 'TEMPERATURES  °C', 14, 30, 20, '#7f93a8', 'left', 700);
    [['Water', S.t_water], ['Art blood', S.t_art], ['Patient', S.temp], ['CPG water', S.t_cp_water]].forEach(([k, v], i) => {
      const y = 72 + i * 44; text(g, k, 14, y, 22, '#b8c6d4', 'left', 500);
      text(g, fmt(v, 1), 338, y, 32, k === 'Art blood' && v > 37.5 ? '#ff5a5a' : v < 30 ? '#6fc8ff' : '#ffcf8a', 'right', 700);
    });
    t.needsUpdate = true;
  }

  // ---- input -----------------------------------------------------------------------
  const hits = controls.map((c) => c.hit);
  const pick = (ray) => { const h = ray.intersectObjects(hits, false)[0]; return h && h.distance < 1.9 ? h.object.userData.control : null; };
  function describe(c, S) {
    if (c.inert) return `${c.label}: ${c.inert}`;
    if (c.timer) return c.op === 'reset' ? `${c.label} ${mmss(S.clocks[c.timer].s)}: click to reset to zero`
      : `${c.label} ${mmss(S.clocks[c.timer].s)}: ${S.clocks[c.timer].run ? 'running, click to stop' : 'stopped, click to start'}`;
    if (c.kind === 'button') return `${c.label}: ${S.controls[c.toggle] ? 'running, click to stop' : 'stopped, click to start'}`;
    return `${c.label} ${fmt(valueOf(c, S))} ${c.unit}: mouse wheel or drag to turn`;
  }
  // turn a dial by n steps (wheel notches, or drag distance converted to steps); returns [key, value] to send
  function turn(c, S, n) {
    if (c.inert || c.kind !== 'dial') return null;
    const v = Math.max(c.min, Math.min(c.max, Math.round((valueOf(c, S) + n * c.step) / c.step) * c.step));
    local[c.key] = { v, t: performance.now() };
    return [c.key, v];
  }
  return { controls, update, draw, pick, describe, turn, heads };
}
