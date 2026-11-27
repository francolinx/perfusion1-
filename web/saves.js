// Save / Load screen (F9, quick-save F5) and the Sessions screen. Talks to /api/save, /api/saves,
// /api/load, DELETE /api/saves/{id}, /api/sessions. All confirmations are in-page, never browser dialogs.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const mmss = (s) => `${Math.floor((s || 0) / 60)}:${String(Math.floor((s || 0) % 60)).padStart(2, '0')}`;
const when = (iso) => { if (!iso) return ''; const d = new Date(iso.replace(/([+-]\d\d)(\d\d)$/, '$1:$2')); return isNaN(d) ? iso : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }); };
async function call(method, path, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  let data = {}; try { data = await r.json(); } catch (e) { /* empty body */ }
  return { status: r.status, data };
}

export function initSaves({ getState, isCaseRunning, onLoaded }) {
  const savesEl = $('saves'), sessEl = $('sessions'), confirmEl = $('confirm');

  // ---- in-page confirm and toast
  function confirmBox(html, ok = 'OK', danger = false) {
    return new Promise((resolve) => {
      $('confirm-body').innerHTML = `<div>${html}</div><div class="row gap"><button id="cf-ok" class="${danger ? 'danger' : 'primary'}">${esc(ok)}</button><button id="cf-no">Cancel</button></div>`;
      confirmEl.classList.remove('hidden');
      const done = (v) => { confirmEl.classList.add('hidden'); document.removeEventListener('keydown', key, true); resolve(v); };
      const key = (e) => { if (e.code === 'Escape') { e.stopPropagation(); done(false); } if (e.code === 'Enter') { e.stopPropagation(); done(true); } };
      document.addEventListener('keydown', key, true);
      $('cf-ok').onclick = () => done(true); $('cf-no').onclick = () => done(false);
      $('cf-ok').focus();
    });
  }
  let toastT = 0;
  function toast(text, ms = 3500) { const t = $('toast'); t.textContent = text; t.classList.add('show'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('show'), ms); }
  const describe = (s) => `<b>${esc(s.name)}</b><br>${esc(s.persona?.name || '')}, ${esc(s.phase_title || '')}, case time ${mmss(s.case_time)}, saved ${esc(when(s.saved_at))}${s.description ? `<br><i>${esc(s.description)}</i>` : ''}`;

  // ---- saving
  async function save(name, description) {
    let r = await call('POST', '/api/save', { name, description });
    if (r.status === 409 && r.data.confirm === 'overwrite') {
      if (!(await confirmBox(`Overwrite this save?<br><br>${describe(r.data.existing)}`, 'Overwrite', true))) return null;
      r = await call('POST', '/api/save', { name, description, overwrite: true });
    }
    if (r.status !== 200) { toast('Could not save: ' + (r.data.error || r.status)); return null; }
    toast(`Saved "${r.data.name}" at ${mmss(r.data.case_time)}.`);
    return r.data;
  }
  async function quickSave() {
    if (!isCaseRunning()) { toast('Start a case before saving.'); return; }
    const S = getState();
    await save('Quick save', S ? `${S.phase_title} at ${mmss(S.t)}` : '');
  }

  // ---- loading and deleting
  async function load(id) {
    let r = await call('POST', '/api/load', { id });
    if (r.status === 409 && r.data.confirm === 'build') {
      const b = r.data;
      const ok = await confirmBox(`This save was made by a different version of the simulator (build <b>${esc(b.saved_build.commit)}</b>${b.saved_build.branch ? ' on ' + esc(b.saved_build.branch) : ''}; this is <b>${esc(b.current_build.commit)}</b>). It may not load, or may behave differently. Load it anyway?`, 'Load anyway');
      if (!ok) return;
      r = await call('POST', '/api/load', { id, force: true });
    }
    if (r.status !== 200) { toast('Could not load: ' + (r.data.error || r.status), 6000); return; }
    close();
    onLoaded(r.data);
  }
  async function remove(row) {
    if (!(await confirmBox(`Delete this save? This cannot be undone.<br><br>${describe(row)}`, 'Delete', true))) return;
    const r = await call('DELETE', '/api/saves/' + encodeURIComponent(row.id));
    if (r.status !== 200) toast('Could not delete: ' + (r.data.error || r.status));
    renderSaves();
  }

  // ---- the Save / Load screen
  async function renderSaves() {
    const S = getState(), running = isCaseRunning();
    const { data } = await call('GET', '/api/saves');
    const rows = data.saves || [];
    $('saves-body').innerHTML = `
      <div class="row"><h1>Save / Load</h1><button id="sv-close">Close (Esc)</button></div>
      ${running ? `<div class="sv-new">
        <label>Name <input id="sv-name" maxlength="80" value="${esc(S ? `${S.phase_title} ${mmss(S.t)}` : 'My save')}"></label>
        <label>Description <textarea id="sv-desc" maxlength="500" rows="2" placeholder="What is happening, what you want to practise from here"></textarea></label>
        <div class="row gap"><button id="sv-save" class="primary">Save now</button><span class="lbl">F5 quick-saves to "Quick save" at any time</span></div></div>`
        : '<p class="sub">Start a case to save it. You can load a save from here at any time.</p>'}
      <h3>Saves (${rows.length})</h3>
      <p class="sub">Loading a save makes that run practice: its score is kept out of comparisons with clean start-to-finish runs.</p>
      <div class="sv-list">${rows.length ? rows.map((s, i) => `
        <div class="sv-row${s.broken ? ' broken' : ''}">
          <div class="sv-main"><b>${esc(s.name)}</b>${s.auto ? ' <span class="tag">auto</span>' : ''}${!s.broken && !s.same_build ? ` <span class="tag warn" title="made by build ${esc(s.build?.commit)}">other build</span>` : ''}
            <div class="sv-desc">${esc(s.description)}</div>
            ${s.broken ? '' : `<div class="sv-meta">${esc(s.persona?.name)} · ${esc(s.phase_title)} · case time ${mmss(s.case_time)} · score ${s.score} · ${esc(when(s.saved_at))}</div>`}</div>
          <div class="sv-btns">${s.broken ? '' : `<button data-load="${i}" class="primary">Load</button>`}<button data-del="${i}">Delete</button></div>
        </div>`).join('') : '<div class="find">No saves yet.</div>'}</div>`;
    $('sv-close').onclick = close;
    if (running) {
      $('sv-save').onclick = async () => { if (await save($('sv-name').value.trim(), $('sv-desc').value.trim())) renderSaves(); };
      $('sv-name').onkeydown = (e) => { if (e.code === 'Enter') $('sv-save').click(); };
    }
    $('saves-body').querySelectorAll('[data-load]').forEach((b) => (b.onclick = () => load(rows[+b.dataset.load].id)));
    $('saves-body').querySelectorAll('[data-del]').forEach((b) => (b.onclick = () => remove(rows[+b.dataset.del])));
  }

  // ---- the Sessions screen
  const KIND = {
    action: (e) => { const a = e.action || {}; const who = e.source === 'autopilot' ? 'Expert' : 'You';
      const what = a.type === 'set' ? `set ${a.key} to ${a.value}` : a.type === 'callout' ? `called "${a.id}"` : a.type === 'measure' ? `ran ${a.what === 'act' ? 'an ACT' : 'a blood gas'}`
        : a.type === 'speed' ? `time ${a.x}x` : a.type === 'autopilot' ? `autopilot ${a.on ? 'on' : 'off'}` : `${a.type} ${a.units ?? a.mg ?? a.mcg ?? a.ml ?? ''}${a.units ? ' units' : a.mg ? ' mg' : a.mcg ? ' mcg' : a.ml ? ' mL' : ''}${a.kind ? ' ' + a.kind : ''}`;
      return `${who}: ${what}`; },
    line: (e) => `Surgeon: "${e.text}"`, phase: (e) => `Phase: ${e.to}`, finding: (e) => `<span class="sev ${esc(e.sev)}">${esc(e.sev)}</span> ${esc(e.msg)}`,
    save: (e) => `${e.auto ? 'Auto-saved' : 'Saved'} "${e.name}"`, load: (e) => `Loaded "${e.name}"`, start: (e) => `Case started (${e.persona})`,
    end: (e) => `Session ended: ${e.reason}, score ${e.score}`, save_failed: (e) => `Auto-save failed: ${e.error}`,
  };
  async function renderSessions() {
    const { data } = await call('GET', '/api/sessions');
    const rows = data.sessions || [];
    $('sessions-body').innerHTML = `
      <div class="row"><h1>Past sessions</h1><button id="ss-close">Close (Esc)</button></div>
      <div class="sv-list">${rows.length ? rows.map((r, i) => `
        <div class="sv-row click" data-open="${i}"><div class="sv-main"><b>${esc(when(r.started_at))}</b> · ${esc(r.persona.name)}
          ${r.practice ? '<span class="tag warn">practice (resumed from save)</span>' : ''}${r.autopilot_used ? '<span class="tag">expert</span>' : ''}${r.status === 'running' ? '<span class="tag">in progress</span>' : ''}
          <div class="sv-meta">score ${r.score ?? '--'} · ${r.case_minutes} min case time · ${r.wall_minutes} min real time · ${esc(r.status)}</div></div>
          <div class="sv-btns"><button>Open</button></div></div>`).join('') : '<div class="find">No sessions yet. A session is kept once you do something in a case.</div>'}</div>`;
    $('ss-close').onclick = close;
    $('sessions-body').querySelectorAll('[data-open]').forEach((b) => (b.onclick = () => renderSession(rows[+b.dataset.open].id)));
  }
  async function renderSession(id) {
    const { status, data: d } = await call('GET', '/api/sessions/' + encodeURIComponent(id));
    if (status !== 200) { toast('Could not open that session.'); return; }
    const sm = d.summary || {};
    const shown = (e, all) => all || !(e.kind === 'action' && ['set', 'speed'].includes(e.action?.type));
    const timeline = (all) => d.events.filter((e) => shown(e, all)).map((e) => `<div class="tl ${e.kind}"><span class="t">${mmss(e.t)}</span> ${KIND[e.kind] ? (e.kind === 'finding' ? KIND.finding(e) : esc(KIND[e.kind](e))) : esc(e.kind)}</div>`).join('');
    $('sessions-body').innerHTML = `
      <div class="row"><button id="ss-back">Back</button><button id="ss-close">Close (Esc)</button></div>
      <h1>${esc(d.persona.name)}</h1>
      <p class="sub">${esc(when(d.started_at))}${d.practice ? ' · <b>practice (resumed from save)</b>' : ''}${d.final ? ` · score ${d.final.score}` : ' · in progress'}</p>
      <p>${esc(sm.header || '')}</p>
      <h3>What was done</h3>${(sm.phases || []).map((p) => `<div class="find">${esc(p.text)}</div>`).join('') || '<div class="find">Nothing yet.</div>'}
      <h3>What went well</h3>${(sm.went_well || []).map((w) => `<div class="find good">${esc(w)}</div>`).join('') || '<div class="find">Not enough of the case was run to say.</div>'}
      <h3>What was flagged</h3>${(sm.flagged || []).map((f) => `<div class="find major">${esc(f)}</div>`).join('') || '<div class="find">Nothing.</div>'}
      <h3>Three things to improve</h3>${(sm.improve || []).map((x, i) => `<div class="find minor"><b>${i + 1}.</b> ${esc(x.what)}${x.how ? `<br><span class="sub">${esc(x.how)}</span>` : ''}</div>`).join('') || '<div class="find">Nothing to improve on this run.</div>'}
      <div class="row"><h3>Timeline</h3><label class="lbl"><input type="checkbox" id="ss-all"> show every control change</label></div>
      <div class="timeline" id="ss-tl">${timeline(false)}</div>`;
    $('ss-back').onclick = renderSessions; $('ss-close').onclick = close;
    $('ss-all').onchange = (e) => { $('ss-tl').innerHTML = timeline(e.target.checked); };
  }

  // ---- open / close
  function close() { savesEl.classList.add('hidden'); sessEl.classList.add('hidden'); }
  const isOpen = () => !savesEl.classList.contains('hidden') || !sessEl.classList.contains('hidden') || !confirmEl.classList.contains('hidden');
  function openSaves() { close(); document.exitPointerLock?.(); savesEl.classList.remove('hidden'); renderSaves(); }
  function toggleSaves() { if (!savesEl.classList.contains('hidden')) close(); else openSaves(); }
  function openSessions(id) { close(); document.exitPointerLock?.(); sessEl.classList.remove('hidden'); id ? renderSession(id) : renderSessions(); }
  return { openSaves, toggleSaves, openSessions, quickSave, close, isOpen, toast };
}
