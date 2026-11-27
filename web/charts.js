// Trend charts from the session log's "vitals" points (one every 15 s of case time). Plain SVG, no library.
// Target bands are the teaching ranges the case asks for; they are training-model values, not clinical references.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const SERIES = [
  { key: 'map', label: 'Pressure (MAP, mmHg)', band: [50, 80], min: 20, max: 110, color: '#ff8a65', bypassOnly: true },
  { key: 'do2i', label: 'Oxygen delivery (DO2i)', band: [280, null], min: 150, max: 500, color: '#64b5f6', bypassOnly: true },
  { key: 'temp', label: 'Temperature (C)', band: null, min: 28, max: 38.5, color: '#ffd54f' },
  { key: 'flow', label: 'Pump flow (L/min)', band: null, min: 0, max: 6.5, color: '#81c784' },
];

export function trendCharts(events) {
  const pts = (events || []).filter((e) => e.kind === 'vitals');
  if (pts.length < 3) return '<p class="sub">Not enough of the case was run for trend charts.</p>';
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t, span = Math.max(60, t1 - t0);
  const W = 600, H = 96, L = 34, R = 6, T = 16, B = 14;
  const x = (t) => L + ((t - t0) / span) * (W - L - R);
  return SERIES.map((s) => {
    const y = (v) => T + (1 - (Math.min(s.max, Math.max(s.min, v)) - s.min) / (s.max - s.min)) * (H - T - B);
    let band = '';
    if (s.band) {
      const hi = s.band[1] === null ? s.max : s.band[1];
      band = `<rect x="${L}" y="${y(hi).toFixed(1)}" width="${W - L - R}" height="${(y(s.band[0]) - y(hi)).toFixed(1)}" fill="#2e7d32" opacity="0.18"/>`;
    }
    // break the line where a value is missing or (for bypass-only series) off bypass
    let d = '', pen = false;
    for (const p of pts) {
      const v = p[s.key];
      if (v === null || v === undefined || (s.bypassOnly && !p.on_bypass)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(v).toFixed(1)}`; pen = true;
    }
    const ticks = [s.min, (s.min + s.max) / 2, s.max].map((v) => `<text x="${L - 4}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${Math.round(v * 10) / 10}</text>`).join('');
    const mins = Math.floor(span / 60), step = mins > 40 ? 10 : 5;
    let xt = '';
    for (let m = 0; m <= mins; m += step) xt += `<text x="${x(t0 + m * 60).toFixed(1)}" y="${H - 2}" text-anchor="middle">${Math.round(t0 / 60) + m}</text>`;
    return `<figure class="trend"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(s.label)}">
      <text x="${L}" y="11" class="tl">${esc(s.label)}${s.band ? ' <tspan class="band">green: target</tspan>' : ''}</text>${band}
      <line x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}" class="axis"/>${ticks}${xt}
      <path d="${d}" fill="none" stroke="${s.color}" stroke-width="1.8" stroke-linejoin="round"/></svg></figure>`;
  }).join('') + '<p class="sub">Minutes of case time. Bands are the targets this training case asks for, not clinical reference values.</p>';
}
