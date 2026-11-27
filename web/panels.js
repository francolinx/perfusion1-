// Control panels for each piece of equipment. Each panel builds DOM controls that send
// actions to the server and refresh from the polled state.

const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

// rolling 2 minute history of pump speed and flow for the pump panel, sampled once a second
const trend = { t: 0, rpm: [], flow: [] };
export function recordTrend(S) {
  const now = Date.now();
  if (now - trend.t < 1000 || !(S.speed > 0)) return;
  trend.t = now; trend.rpm.push(S.rpm); trend.flow.push(S.flow);
  if (trend.rpm.length > 120) { trend.rpm.shift(); trend.flow.shift(); }
}

export function buildPanels(act, state) {
  const set = (key, value) => act({ type: 'set', key, value });

  function slider(body, label, key, min, max, step, show, scale = 1) {
    const w = el('div', 'ctl'), top = el('div', 'top', `<span>${label}</span><b></b>`), inp = el('input');
    Object.assign(inp, { type: 'range', min, max, step });
    let busy = 0, sent = 0;
    inp.oninput = () => {
      busy = Date.now(); top.lastChild.textContent = show(Number(inp.value));
      if (Date.now() - sent > 70) { sent = Date.now(); set(key, Number(inp.value) / scale); }
    };
    inp.onchange = () => set(key, Number(inp.value) / scale);
    w.append(top, inp); body.appendChild(w);
    return { update: (S) => { if (Date.now() - busy > 600) { inp.value = S.controls[key] * scale; top.lastChild.textContent = show(Number(inp.value)); } } };
  }
  function buttons(body, defs) {
    const w = el('div', 'btns'); body.appendChild(w);
    const items = defs.map(([label, fn, isOn, cls]) => { const b = el('button', cls || '', label); b.onclick = fn; w.appendChild(b); return { b, isOn }; });
    return { update: (S) => items.forEach(({ b, isOn }) => isOn && b.classList.toggle('on', !!isOn(S))) };
  }
  function read(body, fn) {
    const w = el('div', 'read'); body.appendChild(w);
    return { update: (S) => { w.innerHTML = fn(S).map(([k, v, c]) => `<div class="v ${c || ''}"><div class="k">${k}</div><div class="n">${v}</div></div>`).join(''); } };
  }
  // the two numbers a centrifugal console shows side by side, plus their recent history
  function pumpFace(body) {
    const w = el('div', 'pumpface', '<div class="seg"><div class="k">RPM</div><div class="n" data-k="rpm">0</div></div><div class="seg"><div class="k">L/min</div><div class="n" data-k="flow">0.00</div></div>');
    const cv = el('canvas', 'trend'); cv.width = 840; cv.height = 180;
    const st = el('div', 'pumpstatus');
    body.append(w, st, cv);
    const g = cv.getContext('2d');
    return { update: (S) => {
      w.querySelector('[data-k=rpm]').textContent = Math.round(S.rpm);
      const f = w.querySelector('[data-k=flow]'); f.textContent = S.flow.toFixed(2); f.classList.toggle('bad', S.flow < -0.1);
      st.textContent = S.flow < -0.1 ? 'BACKFLOW' : S.controls.art_clamp ? (S.rpm > 300 ? 'LINE CLAMPED, PUMP SPINNING' : 'LINE CLAMPED') : S.line_p > 300 ? 'PRESSURE HIGH' : `CI ${S.ci.toFixed(2)}  target ${S.target_flow.toFixed(1)} L/min`;
      st.className = 'pumpstatus' + (S.flow < -0.1 || S.line_p > 300 ? ' bad' : '');
      g.fillStyle = '#0c1f3f'; g.fillRect(0, 0, 840, 180);
      g.strokeStyle = 'rgba(255,255,255,0.1)'; for (let i = 1; i < 4; i++) { g.beginPath(); g.moveTo(0, i * 45); g.lineTo(840, i * 45); g.stroke(); }
      const line = (arr, max, col) => { g.strokeStyle = col; g.lineWidth = 3; g.beginPath(); arr.forEach((v, i) => { const x = 840 - (arr.length - 1 - i) * 7, y = 172 - Math.max(0, Math.min(1, v / max)) * 160; i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); };
      line(trend.rpm, 4500, '#8ab4ff'); line(trend.flow, 7, '#6fe3a1');
      g.font = '22px system-ui, sans-serif'; g.fillStyle = '#8ab4ff'; g.fillText('RPM', 10, 24); g.fillStyle = '#6fe3a1'; g.fillText('L/min', 70, 24); g.fillStyle = '#7f93a8'; g.fillText('last 2 min', 730, 24);
    } };
  }
  function note(body, text) { body.appendChild(el('div', 'note', text)); return {}; }
  function number(body, label, value, unit, go, btn) {
    const w = el('div', 'btns'), inp = el('input'); Object.assign(inp, { type: 'number', value, min: 0 });
    const b = el('button', 'primary', btn); b.onclick = () => { const v = Number(inp.value); if (v > 0) go(v); };
    w.append(el('span', '', label), inp, el('span', 'note', unit), b); body.appendChild(w);
    return { inp };
  }

  return {
    pump: { title: 'Pump console', build: (b) => [
      pumpFace(b),
      read(b, (S) => [['Flow L/min', S.flow.toFixed(2), S.flow < -0.1 ? 'bad' : ''], ['Target', S.target_flow.toFixed(1)], ['Line pressure', S.line_p, S.line_p > 300 ? 'bad' : '']]),
      slider(b, 'Pump speed', 'rpm_set', 0, 4500, 10, (v) => `${v} RPM`),
      buttons(b, [['-100', () => set('rpm_set', state.S.controls.rpm_set - 100)], ['+100', () => set('rpm_set', state.S.controls.rpm_set + 100)],
        ['-500', () => set('rpm_set', state.S.controls.rpm_set - 500)], ['+500', () => set('rpm_set', state.S.controls.rpm_set + 500)]]),
      buttons(b, [['Arterial line clamped', () => set('art_clamp', true), (S) => S.controls.art_clamp], ['Arterial line open', () => set('art_clamp', false), (S) => !S.controls.art_clamp]]),
      note(b, 'A centrifugal pump only makes pressure, so RPM is what you set and L/min is what you get. The same RPM gives less flow when resistance rises. Spin it up before you open the arterial line, and clamp the line before you stop, or blood runs backward.'),
    ] },
    venous: { title: 'Venous clamp', build: (b) => [
      read(b, (S) => [['Drainage L/min', S.qv.toFixed(2)], ['CVP', S.cvp.toFixed(1)], ['Reservoir mL', S.res, S.res < 300 ? 'bad' : '']]),
      slider(b, 'Venous line occlusion', 'ven_occl', 0, 100, 1, (v) => `${v}% closed`, 100),
      buttons(b, [['Fully open', () => set('ven_occl', 0)], ['Half', () => set('ven_occl', 0.5)], ['Fully clamped', () => set('ven_occl', 1)]]),
      note(b, 'Closing this keeps blood in the patient. That fills the heart for weaning, and it drops your reservoir.'),
    ] },
    gas: { title: 'Gas blender and vaporizer', build: (b) => [
      read(b, (S) => [['PaCO2', Math.round(S.paco2), S.paco2 > 45 || S.paco2 < 35 ? 'warn' : ''], ['PaO2', S.pao2, S.pao2 < 150 ? 'warn' : ''], ['MAP', Math.round(S.map)]]),
      slider(b, 'Sweep gas flow (removes CO2)', 'sweep', 0, 80, 1, (v) => `${(v / 10).toFixed(1)} L/min`, 10),
      slider(b, 'Oxygen fraction (sets PaO2)', 'fio2', 21, 100, 1, (v) => `${v}%`, 100),
      slider(b, 'Anesthetic vaporizer (lowers pressure)', 'iso', 0, 30, 1, (v) => `${(v / 10).toFixed(1)}%`, 10),
    ] },
    hc: { title: 'Heater-cooler', build: (b) => [
      read(b, (S) => [['Water C', S.t_water.toFixed(1)], ['Arterial blood C', S.t_art.toFixed(1), S.t_art > 37.5 ? 'bad' : ''], ['Patient C', S.temp.toFixed(1)]]),
      slider(b, 'Water set point', 'water_set', 150, 400, 5, (v) => `${(v / 10).toFixed(1)} C`, 10),
      note(b, 'Keep the water within 10 C of the blood, and never send blood back over 37.5 C.'),
    ] },
    cp: { title: 'Cardioplegia', build: (b) => [
      read(b, (S) => [['This dose mL', S.cp_dose], ['Line pressure', S.cp_pressure, S.cp_pressure > 300 ? 'bad' : ''], ['Sinus pressure', S.csp.toFixed(0), S.csp > 40 ? 'bad' : ''],
        ['Total mL', S.cp_total], ['Since last dose', S.xclamp ? mmss(S.since_cp) : '--', S.since_cp > 1200 ? 'warn' : ''], ['Rhythm', S.rhythm]]),
      buttons(b, [['Antegrade (aortic root)', () => set('cp_route', 'ante'), (S) => S.controls.cp_route === 'ante'], ['Retrograde (coronary sinus)', () => set('cp_route', 'retro'), (S) => S.controls.cp_route === 'retro']]),
      buttons(b, [['High-K cold', () => set('cp_type', 'highK'), (S) => S.controls.cp_type === 'highK'], ['Low-K cold', () => set('cp_type', 'lowK'), (S) => S.controls.cp_type === 'lowK'],
        ['Hot shot', () => set('cp_type', 'hot'), (S) => S.controls.cp_type === 'hot']]),
      slider(b, 'Delivery flow', 'cp_flow', 0, 500, 10, (v) => `${v} mL/min`),
      buttons(b, [['Start delivery', () => set('cp_on', true), (S) => S.controls.cp_on], ['Stop', () => set('cp_on', false), (S) => !S.controls.cp_on]]),
      buttons(b, [['Root vent on', () => set('root_vent', true), (S) => S.controls.root_vent], ['Root vent off', () => set('root_vent', false), (S) => !S.controls.root_vent]]),
      note(b, 'Vent off while giving antegrade so it does not steal the dose. Vent on the rest of the clamp time so the ventricle stays empty.'),
    ] },
    res: { title: 'Reservoir and suckers', build: (b) => [
      read(b, (S) => [['Reservoir mL', S.res, S.res < 300 ? 'bad' : ''], ['Hct %', S.hct.toFixed(0)], ['MAP', Math.round(S.map)]]),
      buttons(b, [['Transfuse 100 mL to patient', () => act({ type: 'transfuse', ml: 100 })], ['Add 250 mL crystalloid', () => act({ type: 'volume', ml: 250, kind: 'crystalloid' })],
        ['Add 1 unit red cells', () => act({ type: 'volume', ml: 300, kind: 'prbc' })]]),
      buttons(b, [['Suckers on', () => set('sucker', true), (S) => S.controls.sucker], ['Suckers off', () => set('sucker', false), (S) => !S.controls.sucker]]),
      note(b, 'If this runs empty the pump sends air to the patient. Suckers must be off before protamine.'),
    ] },
    meds: { title: 'Drug cart', build: (b) => {
      const w = state.S ? state.S.persona.weight : 75;
      return [
        read(b, (S) => [['Heparin given', S.hep_total + ' U'], ['Protamine given', S.prot_total + ' mg'], ['Last ACT', S.last_act ? S.last_act[1] + ' s' : '--']]),
        number(b, 'Heparin', '', 'units', (v) => act({ type: 'heparin', units: v }), 'Give'),
        number(b, 'Protamine', '', 'mg', (v) => act({ type: 'protamine', mg: v }), 'Give'),
        buttons(b, [['Phenylephrine 100 mcg (raises pressure)', () => act({ type: 'phenylephrine', mcg: 100 })],
          ['Epinephrine infusion', () => set('epi', !state.S.controls.epi), (S) => S.controls.epi]]),
        note(b, `Patient weight ${w} kg. Say the units out loud: 300 what?`),
      ];
    } },
    lab: { title: 'ACT and blood gas analyzer', build: (b) => [
      buttons(b, [['Run ACT', () => act({ type: 'measure', what: 'act' }), null, 'primary'], ['Run blood gas', () => act({ type: 'measure', what: 'abg' }), null, 'primary']]),
      read(b, (S) => {
        const a = S.last_abg && S.last_abg[1];
        return [['ACT s', S.last_act ? S.last_act[1] : '--', S.last_act && S.last_act[1] < 400 ? 'bad' : ''], ['Status', S.labs_pending ? 'running' : 'ready'], ['pH', a ? a.ph : '--'],
          ['PaCO2', a ? a.paco2 : '--'], ['PaO2', a ? a.pao2 : '--'], ['K+', a ? a.k : '--', a && a.k > 6 ? 'bad' : ''],
          ['Hct %', a ? a.hct : '--'], ['SvO2 %', a ? a.svo2 : '--'], ['Lactate', a ? a.lactate : '--']];
      }),
      note(b, 'Results take a few seconds. ACT over 480 before bypass; under 400 on bypass is an emergency.'),
    ] },
    vent: { title: 'Ventilator', build: (b) => [
      buttons(b, [['Ventilator on', () => set('ventilator', true), (S) => S.controls.ventilator], ['Ventilator off', () => set('ventilator', false), (S) => !S.controls.ventilator]]),
      read(b, (S) => [['SaO2 %', S.sao2.toFixed(0), S.sao2 < 92 ? 'bad' : ''], ['Pump flow', S.flow.toFixed(2)], ['Heart output', S.qh.toFixed(2)]]),
      note(b, 'Off once the pump is doing all the work. Back on before you wean, or the heart pumps blue blood.'),
    ] },
    talk: { title: 'Talk to the surgeon', build: (b) => {
      const S = state.S, items = [note(b, 'Closed-loop communication is graded. Say what you did when you have done it.')];
      const w = el('div', 'btns'); b.appendChild(w);
      state.META.callouts.forEach((c) => {
        const btn = el('button', S && S.expected_callout === c.id ? 'primary' : '', c.label);
        btn.onclick = () => { act({ type: 'callout', id: c.id }); btn.classList.add('on'); };
        w.appendChild(btn);
      });
      const log = el('div', 'note'); b.appendChild(log);
      items.push({ update: (S2) => { log.innerHTML = S2.lines.slice(-4).map((l) => `Surgeon: ${l.text}`).join('<br>'); } });
      return items;
    } },
  };
}
