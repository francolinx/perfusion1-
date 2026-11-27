// H info panel: what to do now, why, where, what to tell the surgeon, what to watch, common mistakes.
// Built from GET /api/guide (the same objectives the HUD shows, plus teaching text). It reads state only and
// never changes the case.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

export function initHelp({ getState, panelTitle, openPanel, vitals }) {
  const box = $('help'), body = $('help-body');
  let guide = null, guideFor = '', viewing = null, timer = null;

  async function load() {
    const S = getState();
    const key = S ? `${S.persona.id}` : '';
    if (!guide || guideFor !== key) {
      guide = await fetch('/api/guide').then((r) => r.json());
      guideFor = key;
    }
  }

  const calloutStatus = (S) => (S.callout_made ? '<span class="ok">said</span>' : '<span class="due">not said yet</span>');
  const watchHtml = (S, g) => vitals(S).filter((v) => g.watch.includes(v.k))
    .map((v) => `<div class="v ${v.cls}"><div class="k">${esc(v.k)}</div><div class="n">${esc(v.v)}</div></div>`).join('');

  function render() {
    const S = getState();
    if (!guide || !S) { body.innerHTML = '<p>Loading...</p>'; return; }
    const now = S.phase, pid = viewing || now;
    const g = guide.phases.find((p) => p.id === pid) || guide.phases[0];
    const isNow = pid === now;
    const nowIdx = guide.phases.findIndex((p) => p.id === now);
    const watch = g.watch;
    const objs = isNow ? S.objectives : g.objectives;
    let callout = '';
    if (g.callout) {
      callout = `<h3>Tell the surgeon</h3><p>"${esc(g.callout.label)}" <span id="help-callout">${isNow ? calloutStatus(S) : ''}</span> <button data-panel="talk">Talk (T)</button></p>`;
    }
    body.innerHTML = `
      <div class="row"><div><div class="sub">${isNow ? 'Now' : 'Preview'}: step ${g.step} of ${g.steps_total}${isNow ? `, ${mmss(S.phase_elapsed)} in this step` : ''}</div>
        <h1>${esc(g.title)}</h1></div><button id="help-close">Close (H)</button></div>
      ${isNow ? '' : '<p><button id="help-now">Back to the current step</button></p>'}
      <p class="why">${esc(g.why)}</p>
      <h3>Do this</h3><ol class="steps">${objs.map((o) => `<li>${esc(o)}</li>`).join('')}</ol>
      ${g.where.length ? `<h3>Use</h3><div class="where">${g.where.map((id) => `<button data-panel="${esc(id)}">${esc(panelTitle(id))}</button>`).join('')}</div>` : ''}
      ${callout}
      ${isNow && watch.length ? `<h3>Watch</h3><div class="grid" id="help-watch">${watchHtml(S, g)}</div>` : ''}
      ${g.pitfalls.length ? `<h3>Common mistakes</h3><ul>${g.pitfalls.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : ''}
      ${isNow && S.lines.length ? `<h3>Surgeon said</h3>${S.lines.slice(-3).map((l) => `<div class="said"><span>${mmss(l.t)}</span> ${esc(l.text)}</div>`).join('')}` : ''}
      <h3>The whole case</h3><div class="road">${guide.phases.filter((p) => p.id !== 'DONE').map((p, i) =>
        `<button data-phase="${p.id}" class="${p.id === now ? 'cur' : i < nowIdx ? 'past' : ''}${p.id === pid ? ' sel' : ''}">${i + 1}. ${esc(p.title)}</button>`).join('')}</div>
      <p class="sub">${esc(guide.note)}</p>`;
    $('help-close').onclick = close;
    if ($('help-now')) $('help-now').onclick = () => { viewing = null; render(); };
    body.querySelectorAll('[data-panel]').forEach((b) => (b.onclick = () => { close(); openPanel(b.dataset.panel); }));
    body.querySelectorAll('[data-phase]').forEach((b) => (b.onclick = () => { viewing = b.dataset.phase === now ? null : b.dataset.phase; render(); }));
  }

  async function open() {
    document.exitPointerLock?.();
    box.classList.remove('hidden');
    viewing = null;
    try { await load(); } catch (e) { body.innerHTML = '<p>The guide could not be loaded. Is the simulator server running?</p>'; return; }
    render();
    clearInterval(timer);
    let shown = getState()?.phase;
    timer = setInterval(() => {               // keep "Watch" and the callout status live; follow the case to the next step
      const S = getState();
      if (!isOpen() || !S) return;
      if (S.phase !== shown) { shown = S.phase; if (viewing === S.phase) viewing = null; render(); return; }
      if (viewing) return;
      const g = guide.phases.find((p) => p.id === S.phase);
      if ($('help-watch') && g) $('help-watch').innerHTML = watchHtml(S, g);
      if ($('help-callout')) $('help-callout').innerHTML = calloutStatus(S);
    }, 500);
  }
  function close() { box.classList.add('hidden'); clearInterval(timer); }
  const isOpen = () => !box.classList.contains('hidden');
  return { open, close, isOpen, toggle: () => (isOpen() ? close() : open()) };
}
