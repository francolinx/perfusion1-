// Game layer on the start screen and debrief: student name, level locks, rank after a run, quiz.
// Everything here is display; ranking, levels and quiz grading are decided by the server.
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = { get: (k) => { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };

export function initGame({ $, state, onSelect }) {
  const nameEl = $('student-name'), errEl = $('start-error'), unlockEl = $('unlock-all');
  let levels = null, selected = 'standard_adult', timer = 0;
  nameEl.value = store.get('p1_student');
  unlockEl.checked = store.get('p1_unlock') === '1';
  const name = () => nameEl.value.replace(/\s+/g, ' ').trim().slice(0, 24);
  const locked = (pid) => !unlockEl.checked && levels && levels.some((l) => !l.unlocked && l.personas.includes(pid));

  function render() {
    const list = $('persona-list'), P = state.META.personas, byId = Object.fromEntries(P.map((p) => [p.id, p]));
    const groups = levels || [{ title: 'Patients', personas: P.map((p) => p.id), unlocked: true, best: {} }];
    list.innerHTML = groups.map((l) => `<div class="lvl-head">${esc(l.title)}${l.passed ? ' <span class="yes">passed</span>' : (!l.unlocked && !unlockEl.checked) ? ' <span class="lock">locked: pass the level before</span>' : ''}</div>` +
      l.personas.filter((id) => byId[id]).map((id) => { const p = byId[id], lk = locked(id);
        return `<div class="persona${id === selected ? ' sel' : ''}${lk ? ' locked' : ''}" data-id="${id}"><b>${esc(p.name)}${l.best && l.best[id] != null ? `<span class="best">best ${l.best[id]}</span>` : ''}</b><span>${esc(p.desc)}</span></div>`; }).join('')).join('');
    list.querySelectorAll('.persona').forEach((d) => (d.onclick = () => { selected = d.dataset.id; onSelect(selected); errEl.textContent = ''; render(); }));
  }
  async function refresh() {
    try {
      const d = await fetch('/api/leaderboard?student=' + encodeURIComponent(name())).then((r) => r.json());
      levels = d.levels || null;
    } catch (e) { levels = null; }
    if (state.META) render();
  }
  nameEl.oninput = () => { store.set('p1_student', name()); errEl.textContent = ''; clearTimeout(timer); timer = setTimeout(refresh, 300); };
  unlockEl.onchange = () => { store.set('p1_unlock', unlockEl.checked ? '1' : ''); render(); };
  $('btn-board-start').onclick = () => window.open('/leaderboard?student=' + encodeURIComponent(name()), '_blank');

  // Returns the name to fly under, or null after showing why the run cannot start.
  function ready() {
    if (!name()) { errEl.textContent = 'Enter your name first. It goes on the leaderboard.'; nameEl.focus(); return null; }
    if (locked(selected)) { errEl.textContent = 'That patient is locked. Pass a case on the level before it, or tick "unlock all".'; return null; }
    errEl.textContent = ''; return name();
  }

  async function debrief(S) {
    const box = document.createElement('div'); box.id = 'debrief-game'; $('debrief-body').appendChild(box);
    const sid = S.session && S.session.id, who = (S.session && S.session.student) || '';
    const ranked = who && !S.session.practice && !S.session.autopilot_used && !S.session.instructor_used;
    let rankLine = ranked ? '' : `<div class="find minor">${!who ? 'No student name on this run' : S.session.practice ? 'Practice run' : S.session.instructor_used ? 'An instructor changed the patient or circuit during this run' : 'The expert autopilot flew part of this run'}: it is not ranked.</div>`;
    if (ranked) {
      try {
        const d = await fetch(`/api/leaderboard?persona=${encodeURIComponent(S.persona.id)}&student=${encodeURIComponent(who)}`).then((r) => r.json());
        const mine = d.rows.find((r) => r.id === sid), b = d.best;
        if (b) rankLine = `<div class="rankline"><b>${esc(who)}</b>: ${mine ? `this run is <b>#${mine.rank}</b> of ${d.total} on this patient` : `your best on this patient is #${b.rank} of ${d.total}`}${b.id === sid ? ' and is your personal best' : `. Personal best ${b.score}`}.</div>`;
      } catch (e) { /* the board is optional */ }
    }
    box.innerHTML = `<h3>Where you stand</h3>${rankLine}
      <div class="row gap"><button id="btn-board">Leaderboard</button><button id="btn-analyze">Analyze this run</button></div>
      <h3>Quick quiz</h3><div id="quiz-box" class="muted">Loading...</div>`;
    $('btn-board').onclick = () => window.open('/leaderboard?student=' + encodeURIComponent(who), '_blank');
    $('btn-analyze').onclick = () => window.open('/run?id=' + encodeURIComponent(sid), '_blank');
    quiz(sid);
    refresh();
  }
  async function quiz(sid) {
    const box = $('quiz-box');
    let q;
    try { q = await fetch('/api/quiz/' + encodeURIComponent(sid)).then((r) => r.json()); } catch (e) { q = { error: 'Quiz unavailable.' }; }
    if (!box.isConnected) return;
    if (q.error) { box.textContent = q.error; return; }
    const show = (res) => { box.className = ''; box.innerHTML = `<b>${res.score} of ${res.total} correct</b>` + res.items.map((it) => `<div class="find ${it.correct ? '' : 'major'}"><b>${esc(it.q)}</b><br>${it.correct ? '<span class="yes">Correct.</span>' : '<span class="no">Not quite.</span>'} ${esc(it.answer_text)}. <span class="note">${esc(it.why)}</span></div>`).join(''); };
    if (q.result) return show(q.result);
    box.className = '';
    box.innerHTML = q.questions.map((it, i) => `<div class="qz"><b>${i + 1}. ${esc(it.q)}</b>${it.options.map((o, k) => `<label><input type="radio" name="qz${i}" value="${k}"> ${esc(o)}</label>`).join('')}</div>`).join('') +
      '<button id="quiz-send" class="primary">Check answers</button> <span id="quiz-err" class="err"></span>';
    $('quiz-send').onclick = async () => {
      const ans = q.questions.map((_, i) => { const c = box.querySelector(`input[name=qz${i}]:checked`); return c ? Number(c.value) : null; });
      if (ans.some((a) => a === null)) { $('quiz-err').textContent = 'Answer every question first.'; return; }
      try {
        const r = await fetch('/api/quiz/' + encodeURIComponent(sid), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers: ans }) }).then((x) => x.json());
        if (r.result) show(r.result); else $('quiz-err').textContent = r.error || 'Could not save the quiz.';
      } catch (e) { $('quiz-err').textContent = 'Could not reach the simulator.'; }
    };
  }
  return { name, ready, render, refresh, debrief, select: (id) => { selected = id; } };
}
