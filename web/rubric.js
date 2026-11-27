// Rubric report shared by the debrief and the run analysis page. Display only: every number comes from the server.
(function () {
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const MARK = { full: 'full', half: 'half', zero: 'none', not_observed: 'not observed', pending: 'not reached' };
  window.rubricHTML = function (rb) {
    if (!rb) return '';
    const cls = rb.outcome === 'PASS' ? 'good' : rb.outcome === 'FAIL' ? 'critical' : 'minor';
    const lost = rb.missed.length
      ? rb.missed.map((m) => `<div class="find ${m.lost >= m.max ? 'major' : 'minor'}"><b>-${m.lost}</b> ${esc(m.id)} ${esc(m.label)} <span class="rb-sec">(${esc(m.section)})</span><br>${m.why.map(esc).join('<br>')}</div>`).join('')
      : '<div class="find good">No points lost on anything the simulator can observe.</div>';
    const other = rb.other_findings.length
      ? `<h3>Also flagged (no rubric points attached)</h3>` + rb.other_findings.map((f) => `<div class="find ${esc(f.sev)}"><b>${esc(f.sev)}</b>: ${esc(f.msg)}</div>`).join('') : '';
    const rows = rb.sections.map((s) => `<details class="rb-sec-d"><summary><span>${esc(s.id)} ${esc(s.title)}</span><span class="rb-n">${s.observed_max ? `${s.earned} / ${s.observed_max}` : 'not observed'}${s.not_observed ? ` <i>(${s.not_observed} of ${s.max} not simulated)</i>` : ''}</span></summary>
      ${s.items.map((i) => `<div class="rb-item ${i.status}"><span>${esc(i.id)} ${esc(i.label)}${i.why.length && i.status !== 'full' ? `<small>${i.why.map(esc).join(' ')}</small>` : ''}</span><span class="rb-n">${i.earned == null ? MARK[i.status] : `${i.earned} / ${i.max}`}</span></div>`).join('')}</details>`).join('');
    return `<div id="rubric-report">
      <div class="find ${cls}" id="rb-outcome"><b>${esc(rb.outcome)}</b>: ${esc(rb.outcome_reason)} Earned <b>${rb.earned} of ${rb.possible}</b> points the simulator can observe (pass mark ${rb.pass_score}).
        ${rb.not_observed ? `${rb.not_observed} of the 100 rubric points (mostly circuit setup and priming) are not simulated yet, so this is not a complete examination total.` : ''}</div>
      <h3>Where you lost points, and why</h3>${lost}${other}
      <h3>Rubric by section</h3>${rows}</div>`;
  };
})();
