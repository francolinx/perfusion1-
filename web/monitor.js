// Patient monitor: scrolling ECG, arterial, pulmonary artery and CVP traces with their numbers, plus the boxes a
// bypass room shows around them (pulse oximetry, temperature, urine, two-channel ACT, heater-cooler circuits,
// coloured blood tiles, reservoir level, alarm banner). One canvas, shown on the monitor by the table and on the
// wall repeater. Display only: every number comes from /api/state. The waveform shapes are drawing, not physiology:
// their height comes from the systolic and diastolic values the model reports, so a flat arterial line on full
// bypass and a pulsatile one when the heart ejects both come from the model.
export const MON_W = 1280, MON_H = 720;
const N = 560;                       // samples across a trace
const wave = { ecg: new Float32Array(N), art: new Float32Array(N), pa: new Float32Array(N), cvp: new Float32Array(N), i: 0, ph: 0 };

function ecgShape(p, rhythm, t) {
  if (rhythm === 'asystole') return Math.sin(t * 2) * 0.01;
  if (rhythm === 'vf') return (Math.sin(t * 31) + Math.sin(t * 43.7) * 0.7 + Math.sin(t * 17.3) * 0.5) * 0.25;
  const gs = (c, w, a) => a * Math.exp(-((p - c) ** 2) / (2 * w * w));
  return gs(0.18, 0.025, 0.12) - gs(0.27, 0.008, 0.12) + gs(0.29, 0.01, 1.0) - gs(0.315, 0.01, 0.22) + gs(0.5, 0.045, 0.25);
}
// 0..1 pressure pulse with a dicrotic notch; the PA pulse is rounder and a little later
const artShape = (p) => (p < 0.12 ? p / 0.12 : Math.exp(-(p - 0.12) * 3.2)) + 0.12 * Math.exp(-((p - 0.42) ** 2) / 0.002);
const paShape = (p) => (p < 0.16 ? p / 0.16 : Math.exp(-(p - 0.16) * 2.6)) + 0.06 * Math.exp(-((p - 0.45) ** 2) / 0.003);

export function sampleWaves(S, dt) {
  const hr = S.hr || 60, t = performance.now() / 1000;
  const n = Math.max(1, Math.round(dt * 120)), beating = S.rhythm === 'sinus' || S.rhythm === 'brady';
  const artPP = S.art_sys - S.art_dia, paPP = S.pap_sys - S.pap_dia;
  for (let k = 0; k < n; k++) {
    const i = wave.i = (wave.i + 1) % N, p = (wave.ph + ((k + 1) / n) * ((dt * hr) / 60)) % 1;
    wave.ecg[i] = ecgShape(p, S.rhythm, t + k * 0.008);
    // mean + pulse pressure x (shape - its mean): the trace's peak and trough sit near systolic and diastolic
    wave.art[i] = S.map + (beating ? artPP * (artShape(p) - 0.42) : 0) + Math.sin(t * 40 + k) * 0.25;
    wave.pa[i] = S.pap + (beating ? paPP * (paShape(p) - 0.40) : 0) + Math.sin(t * 3.1 + k * 0.05) * 0.3;
    wave.cvp[i] = S.cvp + (beating ? Math.sin(p * 6.28) * 0.8 : 0);
  }
  wave.ph = (wave.ph + (dt * hr) / 60) % 1;
}

const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? '--' : Number(v).toFixed(d));
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const COL = { ecg: '#39d98a', art: '#ff5a5a', pa: '#ffd84d', cvp: '#5ab0ff', spo2: '#5fe3ff', temp: '#f0f0f0', dim: '#7f8b97' };
const MODE = { before: ['BEFORE BYPASS', '#3a4452'], partial: ['PARTIAL BYPASS', '#8a5a12'], full: ['ON BYPASS', '#1f6b45'], after: ['AFTER BYPASS', '#3a4452'] };

function txt(g, s, x, y, size, color = '#fff', align = 'left', weight = 600) {
  g.font = `${weight} ${size}px system-ui, sans-serif`; g.fillStyle = color; g.textAlign = align; g.textBaseline = 'alphabetic'; g.fillText(s, x, y);
}
function trace(g, buf, x0, y0, w, h, lo, hi, color) {
  g.strokeStyle = 'rgba(255,255,255,0.06)'; g.lineWidth = 1; g.beginPath(); g.moveTo(x0, y0 + h); g.lineTo(x0 + w, y0 + h); g.stroke();
  g.strokeStyle = color; g.lineWidth = 2.6; g.beginPath();
  for (let k = 0; k < N; k++) {
    const v = buf[(wave.i + 1 + k) % N], y = Math.max(y0, Math.min(y0 + h, y0 + h - ((v - lo) / (hi - lo)) * h));
    k ? g.lineTo(x0 + (k / N) * w, y) : g.moveTo(x0, y);
  }
  g.stroke();
}
function panel(g, x, y, w, h) { g.fillStyle = '#0b1219'; g.fillRect(x, y, w, h); g.strokeStyle = 'rgba(255,255,255,0.08)'; g.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1); }
function tile(g, x, y, w, h, label, value, bg) {
  g.fillStyle = bg; g.fillRect(x, y, w, h);
  txt(g, label, x + 10, y + 24, 18, 'rgba(255,255,255,0.85)', 'left', 600); txt(g, value, x + w - 10, y + h - 14, 40, '#fff', 'right', 700);
}

export function drawMonitor(g, S) {
  g.fillStyle = '#02070b'; g.fillRect(0, 0, MON_W, MON_H);
  // header: mode, patient, clock
  const [mode, mcol] = MODE[S.mode] || MODE.before, pe = S.persona || {};
  g.fillStyle = '#0d151d'; g.fillRect(0, 0, MON_W, 52);
  g.fillStyle = mcol; g.beginPath(); g.roundRect(10, 8, 230, 36, 8); g.fill();
  txt(g, mode, 125, 34, 22, '#fff', 'center', 700);
  txt(g, `${pe.age ?? '--'} y   ${pe.sex === 'F' ? 'Female' : pe.sex === 'M' ? 'Male' : '--'}   ${fmt(pe.weight)} kg   ${fmt(pe.height)} cm   BSA ${fmt(S.bsa, 2)} m²`, 262, 34, 22, '#dfe6ee', 'left', 500);
  txt(g, `case ${mmss(S.t)}`, MON_W - 14, 34, 22, '#9fb0c0', 'right', 500);
  // alarm banner
  const crit = S.alarms.filter(([s]) => s === 'critical'), warn = S.alarms.filter(([s]) => s !== 'critical');
  const top = crit[0] || warn[0];
  g.fillStyle = top ? (crit.length ? '#8a1616' : '#7a5a10') : '#070c11'; g.fillRect(0, 52, MON_W, 38);
  if (top) txt(g, top[1].toUpperCase() + (S.alarms.length > 1 ? `   (+${S.alarms.length - 1} more)` : ''), 14, 80, 22, '#fff', 'left', 700);
  else txt(g, 'No active alarms', 14, 80, 18, '#4b5966', 'left', 500);

  // traces (left) with their numbers (middle column)
  const TX = 10, TW = 760, rows = [
    ['ECG  II', wave.ecg, -0.4, 1.2, COL.ecg], ['ART', wave.art, 0, 160, COL.art],
    ['PA', wave.pa, 0, 50, COL.pa], ['CVP', wave.cvp, -5, 25, COL.cvp]];
  const RH = 122;
  rows.forEach(([label, buf, lo, hi, col], r) => {
    const y = 98 + r * RH;
    txt(g, label, TX + 4, y + 18, 17, col, 'left', 600);
    if (r > 0) txt(g, `${hi}`, TX + TW - 4, y + 16, 13, COL.dim, 'right', 500);
    trace(g, buf, TX, y + 22, TW, RH - 30, lo, hi, col);
  });
  const NX = 790, NW = 230;
  const num = (r, label, big, small, col) => {
    const y = 98 + r * RH; panel(g, NX, y + 2, NW, RH - 8);
    txt(g, label, NX + 10, y + 26, 18, col, 'left', 600);
    txt(g, big, NX + NW - 10, y + 82, big.length > 6 ? 46 : 60, col, 'right', 700);
    if (small) txt(g, small, NX + NW - 10, y + 108, 22, col, 'right', 500);
  };
  num(0, 'HR', String(S.hr), S.rhythm === 'sinus' ? '' : S.rhythm.toUpperCase(), COL.ecg);
  num(1, 'ART  mmHg', `${fmt(S.art_sys)}/${fmt(S.art_dia)}`, `(${fmt(S.map)})`, COL.art);
  num(2, 'PA  mmHg', `${fmt(S.pap_sys)}/${fmt(S.pap_dia)}`, `(${fmt(S.pap)})`, COL.pa);
  num(3, 'CVP  mmHg', fmt(S.cvp), '', COL.cvp);

  // right column: SpO2, esophageal temperature, urine, ACT
  const RX = 1030, RW = 240;
  panel(g, RX, 100, RW, 96);
  txt(g, 'SpO₂ %', RX + 10, 124, 18, COL.spo2); txt(g, S.spo2 === null ? '--' : String(S.spo2), RX + RW - 10, 180, 54, COL.spo2, 'right', 700);
  if (S.spo2 === null) txt(g, 'no pulse signal', RX + 10, 184, 15, COL.dim, 'left', 500);
  panel(g, RX, 202, RW, 82);
  txt(g, 'Temp eso °C', RX + 10, 226, 18, COL.temp); txt(g, fmt(S.temp, 1), RX + RW - 10, 272, 44, COL.temp, 'right', 700);
  panel(g, RX, 290, RW, 82);
  txt(g, 'Urine', RX + 10, 314, 18, '#e6d27a'); txt(g, `${fmt(S.urine_ml)} mL`, RX + RW - 10, 352, 34, '#e6d27a', 'right', 700);
  txt(g, `${fmt(S.urine_rate)} mL/h`, RX + 10, 364, 16, '#b8a85e', 'left', 500);
  panel(g, RX, 378, RW, 110);
  txt(g, 'ACT  s', RX + 10, 402, 18, '#f2a2ff');
  const act = (lbl, v, y) => { txt(g, lbl, RX + 14, y, 18, COL.dim, 'left', 500); txt(g, v ? String(v[1]) : '--', RX + 140, y, 32, v && v[1] < 400 ? '#ff7a7a' : '#f2a2ff', 'right', 700);
    txt(g, v ? mmss(v[0]) : '', RX + RW - 10, y, 16, COL.dim, 'right', 500); };
  act('Ch 1', S.last_act, 438); act('Ch 2', S.last_act2, 474);

  // bottom strip: heater-cooler circuits, blood tiles, reservoir level
  const BY = 592, BH = 120;
  panel(g, 10, BY, 300, BH);
  txt(g, 'Heater-cooler water', 20, BY + 24, 17, COL.dim, 'left', 600);
  const hc = (lbl, t, on, y) => { txt(g, lbl, 20, y, 18, '#cfd8e1', 'left', 500); txt(g, `${fmt(t, 1)} °C`, 220, y, 28, t < 30 ? '#6fc8ff' : '#ff9d5a', 'right', 700);
    txt(g, on ? 'ON' : 'OFF', 296, y, 18, on ? '#6fe3a1' : '#ffb84d', 'right', 700); };
  hc('Patient', S.t_water, S.controls.hc_on, BY + 66); hc('Cardioplegia', S.t_cp_water, S.controls.cp_hc_on, BY + 104);
  const tw = 170, tx0 = 320;
  tile(g, tx0, BY, tw, BH, 'SaO₂ %', fmt(S.sao2), S.sao2 < 92 ? '#9b2020' : '#b3262f');
  tile(g, tx0 + tw + 6, BY, tw, BH, 'SvO₂ %', fmt(S.svo2), S.svo2 < 60 ? '#8a4a10' : '#2a4f9a');
  tile(g, tx0 + 2 * (tw + 6), BY, tw, BH, 'Hct %', fmt(S.hct), S.hct < 21 ? '#7a5a10' : '#6a2f7a');
  tile(g, tx0 + 3 * (tw + 6), BY, tw, BH, 'Art flow L/min', fmt(S.flow, 2), S.flow < -0.1 ? '#9b2020' : '#1f6b55');
  const rx = tx0 + 4 * (tw + 6) + 6, rw = MON_W - 10 - rx;
  panel(g, rx, BY, rw, BH);
  txt(g, 'Reservoir', rx + 10, BY + 24, 17, COL.dim, 'left', 600);
  const frac = Math.max(0, Math.min(1, S.res_frac)), bx = rx + 14, bw = rw - 120, byy = BY + 40, bh = 64;
  g.strokeStyle = '#4b5966'; g.lineWidth = 2; g.strokeRect(bx, byy, bw, bh);
  g.fillStyle = S.res < 300 ? '#d13a3a' : S.res < 600 ? '#d69a2a' : '#c0283a'; g.fillRect(bx + 2, byy + 2, (bw - 4) * frac, bh - 4);
  for (const m of [0.25, 0.5, 0.75]) { g.fillStyle = 'rgba(255,255,255,0.25)'; g.fillRect(bx + bw * m, byy, 1, bh); }
  txt(g, `${fmt(S.res)} mL`, rx + rw - 10, BY + 84, 26, '#fff', 'right', 700);
}
