// The student's own body: a blocky figure in scrubs, seen in third-person view (V).
// Cosmetic only. It reads the player's position and pose; it never touches the case.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

export function buildAvatar(scene) {
  const mat = (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, metalness: 0.02 });
  const scrub = mat(0x2f6f9f), scrubDark = mat(0x285f88), skin = mat(0xcf9a76), shoe = mat(0x1d1d1f);
  const root = new THREE.Group(); root.name = 'player'; scene.add(root);
  const part = (parent, w, h, d, m, x, y, z) => {
    const mesh = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 2, Math.min(0.035, Math.min(w, h, d) * 0.25)), m);
    mesh.position.set(x, y, z); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh;
  };
  // a pivot is an empty group at a joint, so limbs swing from the hip or shoulder, not their middle
  const pivot = (parent, x, y, z) => { const g = new THREE.Group(); g.position.set(x, y, z); parent.add(g); return g; };

  const hips = pivot(root, 0, 0.82, 0);
  const legL = pivot(hips, -0.1, 0, 0), legR = pivot(hips, 0.1, 0, 0);
  for (const leg of [legL, legR]) { part(leg, 0.16, 0.74, 0.18, scrubDark, 0, -0.37, 0); part(leg, 0.17, 0.08, 0.24, shoe, 0, -0.78, 0.03); }
  const torso = pivot(hips, 0, 0, 0);
  part(torso, 0.44, 0.62, 0.24, scrub, 0, 0.31, 0);
  part(torso, 0.12, 0.16, 0.02, mat(0xe8eef2), 0.1, 0.45, 0.125);              // badge
  const armL = pivot(torso, -0.29, 0.58, 0), armR = pivot(torso, 0.29, 0.58, 0);
  for (const arm of [armL, armR]) { part(arm, 0.13, 0.42, 0.14, scrub, 0, -0.2, 0); part(arm, 0.12, 0.16, 0.13, skin, 0, -0.5, 0); }
  const head = pivot(torso, 0, 0.62, 0);
  part(head, 0.26, 0.28, 0.26, skin, 0, 0.14, 0);
  part(head, 0.28, 0.09, 0.28, mat(0x3f8fb8), 0, 0.31, 0);                     // scrub cap
  part(head, 0.05, 0.035, 0.01, shoe, -0.06, 0.17, 0.131); part(head, 0.05, 0.035, 0.01, shoe, 0.06, 0.17, 0.131);
  // smash mode must never treat the student's own (hidden) body as something to break
  root.traverse((m) => { m.userData.self = true; m.userData.person = 'player'; });

  let walk = 0;
  // p: {x, y, z, yaw, pitch, crouch (0..1), speed (m/s on the ground), airborne}
  function update(p, dt, visible) {
    root.visible = visible;
    if (!visible) return;
    root.position.set(p.x, p.y, p.z);
    root.rotation.y = p.yaw + Math.PI;                 // the model faces +z, the camera looks down -z
    walk += dt * Math.min(p.speed, 5) * 3.2;
    const amp = p.airborne ? 0.15 : Math.min(1, p.speed / 2.3) * 0.7;
    const swing = Math.sin(walk) * amp;
    legL.rotation.x = swing; legR.rotation.x = -swing;
    armL.rotation.x = -swing * 0.8; armR.rotation.x = swing * 0.8;
    if (p.airborne) { armL.rotation.x = armR.rotation.x = -0.5; }
    // crouch: drop the hips, lean the torso forward, bend the knees back
    hips.position.y = 0.82 - 0.16 * p.crouch;
    torso.rotation.x = 0.45 * p.crouch;
    legL.rotation.x += -0.35 * p.crouch; legR.rotation.x += -0.35 * p.crouch;
    head.rotation.x = Math.max(-0.7, Math.min(0.7, -p.pitch)) - 0.45 * p.crouch;
  }
  return { root, update };
}
