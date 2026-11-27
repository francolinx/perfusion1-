// Smash mode: a just-for-fun rage room. Pick up a bat and wreck the lab.
// Purely cosmetic and client-side: the case is paused, nothing here is graded or sent to the model.
import * as THREE from 'three';

const QUIPS = {
  gear: ['Hey! That is a forty thousand dollar oxygenator.', 'That was the only pump we had.', 'I am calling biomed.',
    'This is going in your evaluation.', 'The warranty does not cover baseball.', 'Somebody page security.'],
  patient: ['That is not in the protocol.', 'The mannequin did nothing to you.', 'We do not treat low pressure that way.',
    'I am going to need you to step away from the patient.'],
  staff: ['Ow. I have a mortgage.', 'I will remember this at your review.', 'HR is going to hear about this.'],
};

export function initSmash({ scene, camera, room, onQuip, pause }) {
  const S = { on: false, swingT: -1, hitDone: false, debris: [], shake: 0, bill: 0, count: 0, quipAt: 0 };
  const hud = document.getElementById('smash-hud');
  const ray = new THREE.Raycaster(); ray.far = 2.7; ray.camera = camera;
  const tmp = new THREE.Vector3(), dir = new THREE.Vector3();

  // ---- the bat, held in the lower right of the view
  const bat = new THREE.Group(); bat.visible = false; camera.add(bat);
  const wood = new THREE.MeshStandardMaterial({ color: 0xc9975b, roughness: 0.55 });
  const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.036, 0.02, 0.62, 16), wood); barrel.position.y = 0.45;
  const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.016, 0.3, 12), new THREE.MeshStandardMaterial({ color: 0x2a2a2e, roughness: 0.9 })); handle.position.y = 0.0;
  const knob = new THREE.Mesh(new THREE.SphereGeometry(0.026, 12, 10), wood); knob.position.y = -0.16;
  [barrel, handle, knob].forEach((m) => { m.userData.bat = true; bat.add(m); });
  const REST = { p: [0.34, -0.36, -0.5], r: [-0.5, 0, -0.45] };
  bat.position.set(...REST.p); bat.rotation.set(...REST.r);

  // ---- sound, synthesized so there are no audio files to ship
  let ac = null, noiseBuf = null;
  function audio() {
    if (ac) return ac;
    const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return null;
    ac = new AC(); noiseBuf = ac.createBuffer(1, ac.sampleRate, ac.sampleRate);
    const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return ac;
  }
  function burst(type, freq, q, dur, vol, sweepTo) {
    const a = audio(); if (!a) return; const t = a.currentTime;
    const src = a.createBufferSource(); src.buffer = noiseBuf; src.loop = true;
    const f = a.createBiquadFilter(); f.type = type; f.frequency.setValueAtTime(freq, t); f.Q.value = q;
    if (sweepTo) f.frequency.exponentialRampToValueAtTime(sweepTo, t + dur);
    const g = a.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(f).connect(g).connect(a.destination); src.start(t, Math.random() * 0.5); src.stop(t + dur + 0.02);
  }
  function tone(freq, dur, vol, type = 'sine', dropTo) {
    const a = audio(); if (!a) return; const t = a.currentTime;
    const o = a.createOscillator(); o.type = type; o.frequency.setValueAtTime(freq, t);
    if (dropTo) o.frequency.exponentialRampToValueAtTime(dropTo, t + dur);
    const g = a.createGain(); g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g).connect(a.destination); o.start(t); o.stop(t + dur + 0.02);
  }
  const SOUND = {
    whoosh: () => burst('bandpass', 500, 1.2, 0.22, 0.25, 1800),
    thud: () => { tone(140, 0.22, 0.7, 'sine', 45); burst('lowpass', 400, 0.7, 0.12, 0.5); },
    plastic: () => { tone(180, 0.14, 0.5, 'triangle', 70); burst('bandpass', 1800, 1.5, 0.16, 0.6); burst('highpass', 3500, 0.7, 0.07, 0.3); },
    metal: () => { [523, 1187, 1873, 2741].forEach((f, i) => tone(f * (0.95 + Math.random() * 0.1), 0.9 - i * 0.15, 0.22 - i * 0.04)); burst('bandpass', 2500, 2, 0.08, 0.5); tone(120, 0.15, 0.5, 'sine', 50); },
    glass: () => { burst('highpass', 4200, 0.8, 0.5, 0.55); for (let i = 0; i < 6; i++) setTimeout(() => tone(2400 + Math.random() * 4200, 0.12 + Math.random() * 0.2, 0.12), 20 + i * 45 + Math.random() * 40); tone(160, 0.12, 0.4, 'sine', 60); },
    body: () => { tone(110, 0.25, 0.7, 'sine', 40); burst('lowpass', 300, 0.8, 0.18, 0.6); setTimeout(() => tone(320, 0.22, 0.18, 'sawtooth', 150), 60); },
    floor: () => { tone(90, 0.1, 0.25, 'sine', 50); burst('lowpass', 900, 0.8, 0.05, 0.2); },
  };

  // ---- what can break, and what it sounds like
  function breakable(m) {
    if (!m.isMesh || !m.visible || m.userData.bat || m.userData.self) return false;
    if (m.userData.debris) return true;
    const g = m.geometry; if (!g.boundingSphere) g.computeBoundingSphere();
    return g.boundingSphere.radius * Math.max(m.scale.x, m.scale.y, m.scale.z) < 1.6;   // walls, floor and ceiling stay up
  }
  function kindOf(m) {
    if (m.userData.person) return 'body';
    const mt = m.material;
    if (mt.isMeshBasicMaterial || mt.transmission > 0 || (mt.transparent && mt.opacity < 0.9)) return 'glass';
    if (mt.metalness > 0.5) return 'metal';
    return 'plastic';
  }
  const shardGeo = new THREE.BoxGeometry(0.035, 0.035, 0.035);
  function addShards(at, color, n, speed) {
    for (let i = 0; i < n; i++) {
      const s = new THREE.Mesh(shardGeo, new THREE.MeshStandardMaterial({ color, roughness: 0.5 }));
      s.position.copy(at); s.scale.setScalar(0.5 + Math.random() * 1.2); s.castShadow = true;
      s.userData = { debris: true, shard: true }; scene.add(s);
      S.debris.push({ m: s, v: new THREE.Vector3((Math.random() - 0.5) * speed, Math.random() * speed, (Math.random() - 0.5) * speed).addScaledVector(dir, speed * 0.5),
        w: new THREE.Vector3(Math.random() * 12, Math.random() * 12, Math.random() * 12), r: 0.02, life: 14 });
    }
    while (S.debris.length > 420) { const i = S.debris.findIndex((d) => d.m.userData.shard); if (i < 0) break; scene.remove(S.debris[i].m); S.debris.splice(i, 1); }
  }
  function launch(m, from, power) {
    const c = m.geometry.boundingSphere.center.clone(); m.localToWorld(c);
    let d = S.debris.find((x) => x.m === m);
    if (!d) {
      scene.attach(m); m.userData.debris = true;
      const r = Math.max(0.03, Math.min(0.3, m.geometry.boundingSphere.radius * m.scale.y * 0.45));
      d = { m, v: new THREE.Vector3(), w: new THREE.Vector3(), r, life: 1e9, tube: m.geometry.type === 'TubeGeometry', off: c.clone().sub(m.position) };
      S.debris.push(d);
      S.count++; S.bill += Math.round((200 + Math.random() * 3800) * (kindOf(m) === 'glass' ? 2.5 : 1) / 10) * 10;
      addShards(c, m.material.color ? m.material.color.getHex() : 0xcccccc, d.tube ? 10 : 5, 3.2);
    }
    d.sleep = false;
    const away = c.clone().sub(from); away.y = 0; away.normalize();
    d.v.addScaledVector(away, power * (0.6 + Math.random() * 0.8)).addScaledVector(dir, power * 0.8);
    d.v.y += 1.8 + Math.random() * 2.2;
    if (!d.tube) d.w.set((Math.random() - 0.5) * 14, (Math.random() - 0.5) * 14, (Math.random() - 0.5) * 14);
  }
  function strike() {
    camera.getWorldDirection(dir);
    ray.set(camera.getWorldPosition(tmp), dir);
    const hit = ray.intersectObjects(scene.children, true).find((h) => breakable(h.object));
    if (!hit) return;
    const p = hit.point, victims = new Set([hit.object]);
    scene.traverse((m) => {
      if (victims.size >= 14 || !breakable(m) || m.userData.shard) return;
      const c = m.geometry.boundingSphere.center.clone(); m.localToWorld(c);
      if (c.distanceTo(p) < 0.34) victims.add(m);
    });
    const kinds = new Set();
    victims.forEach((m) => { kinds.add(kindOf(m)); launch(m, tmp, 4.2); });
    ['glass', 'metal', 'body', 'plastic'].filter((k) => kinds.has(k)).slice(0, 2).forEach((k) => SOUND[k]());
    SOUND.thud(); S.shake = 0.12;
    const who = hit.object.userData.person;
    const now = performance.now();
    if (now - S.quipAt > 2600) {
      S.quipAt = now;
      const list = who === 'patient' ? QUIPS.patient : who ? QUIPS.staff : QUIPS.gear;
      onQuip(list[Math.floor(Math.random() * list.length)]);
    }
    hud.textContent = `Smash mode. Damage bill: $${S.bill.toLocaleString()} (${S.count} parts). Click or F to swing.`;
  }

  // ---- public controls
  function swing() {
    if (!S.on || S.swingT >= 0) return;
    audio()?.resume?.(); S.swingT = 0; S.hitDone = false; SOUND.whoosh();
  }
  function toggle() {
    if (S.on) { location.reload(); return; }       // leaving smash mode rebuilds the lab
    S.on = true; bat.visible = true; pause();
    hud.classList.remove('hidden');
    hud.textContent = 'Smash mode. The case is paused and nothing here is graded. Click or F to swing.';
    document.getElementById('btn-smash').textContent = 'Repair the lab (B)';
    document.getElementById('btn-smash').classList.add('danger');
    onQuip('Why are you holding a baseball bat?');
  }
  function update(dt) {
    if (!S.on) return;
    if (S.swingT >= 0) {
      S.swingT += dt; const k = Math.min(1, S.swingT / 0.3), e = Math.sin(k * Math.PI);
      bat.position.set(REST.p[0] - 0.42 * e, REST.p[1] + 0.16 * e, REST.p[2] - 0.12 * e);
      bat.rotation.set(REST.r[0] - 0.9 * e, 0.5 * e, REST.r[2] + 1.9 * e);
      if (k > 0.45 && !S.hitDone) { S.hitDone = true; strike(); }
      if (k >= 1) { S.swingT = -1; bat.position.set(...REST.p); bat.rotation.set(...REST.r); }
    }
    if (S.shake > 0) { S.shake -= dt; camera.position.x += (Math.random() - 0.5) * 0.03; camera.position.y += (Math.random() - 0.5) * 0.03; }
    for (let i = S.debris.length - 1; i >= 0; i--) {
      const d = S.debris[i], m = d.m, off = d.off ? d.off.y : 0;
      d.life -= dt; if (d.life <= 0) { scene.remove(m); S.debris.splice(i, 1); continue; }
      if (d.sleep) continue;
      d.v.y -= 9.8 * dt; m.position.addScaledVector(d.v, dt);
      m.rotation.x += d.w.x * dt; m.rotation.y += d.w.y * dt; m.rotation.z += d.w.z * dt;
      const floorY = d.r - off, cx = m.position.x + (d.off ? d.off.x : 0), cz = m.position.z + (d.off ? d.off.z : 0);
      if (m.position.y < floorY) {
        m.position.y = floorY;
        if (d.v.y < -2.2 && !m.userData.shard) SOUND.floor();
        d.v.y *= -0.32; d.v.x *= 0.7; d.v.z *= 0.7; d.w.multiplyScalar(0.6);
        if (Math.abs(d.v.y) < 0.5 && d.v.lengthSq() < 0.3) d.sleep = true;
      }
      if (cx < room.x0 + d.r || cx > room.x1 - d.r) { d.v.x *= -0.4; m.position.x += cx < 0 ? 0.02 : -0.02; }
      if (cz < room.z0 + d.r || cz > room.z1 - d.r) { d.v.z *= -0.4; m.position.z += cz < 0 ? 0.02 : -0.02; }
      if (m.position.y > room.h - d.r) { m.position.y = room.h - d.r; d.v.y = -Math.abs(d.v.y) * 0.3; }
    }
  }
  return { state: S, swing, toggle, update };
}
