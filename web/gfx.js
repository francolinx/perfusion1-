// Rendering quality: image-based lighting, post-processing and quality tiers. Display only.
//   high: ambient occlusion + bloom + 4x MSAA, clear-plastic transmission (desktop GPUs)
//   med : bloom + MSAA
//   low : plain forward render at reduced pixel ratio (phones, software rendering)
// The tier steps down by itself if frames stay slow. ?gfx=high|med|low in the URL pins it.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const TIERS = ['low', 'med', 'high'];
const CAP = { low: 1.25, med: 1.5, high: 2 };
const stored = () => { try { return localStorage.getItem('p1_gfx'); } catch (e) { return null; } };
const pinned = new URLSearchParams(location.search).get('gfx');

export function pickTier() {
  if (TIERS.includes(pinned)) return pinned;
  if (TIERS.includes(stored())) return stored();
  return matchMedia('(pointer: coarse)').matches ? 'low' : 'high';
}

export function initGfx({ renderer, scene, camera, tier, onTier }) {
  let composer = null, slow = 0, ema = 16, w = 1, h = 1;
  const G = { tier, built: tier };          // built: the tier the scene's materials were made for
  // Image-based lighting from a generated studio scene: no image files. Skipped on the low tier, where
  // baking it stalls software renderers for seconds; a plain fill light stands in (G.fill, set by the scene).
  function lightFor(t) {
    if (t !== 'low' && !scene.environment) {
      const pmrem = new THREE.PMREMGenerator(renderer);
      scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      scene.environmentIntensity = 0.38;
      pmrem.dispose();
    }
    if (G.fill) G.fill.intensity = scene.environment ? 0 : 0.5;
  }

  function build() {
    if (composer) { composer.dispose(); composer = null; }
    const pr = Math.min(window.devicePixelRatio || 1, CAP[G.tier]);
    renderer.setPixelRatio(pr);
    renderer.setSize(w, h, false);
    if (G.tier === 'low') return;
    try {
      const rt = new THREE.WebGLRenderTarget(Math.round(w * pr), Math.round(h * pr), { type: THREE.HalfFloatType, samples: 4 });
      composer = new EffectComposer(renderer, rt);
      composer.setPixelRatio(pr); composer.setSize(w, h);
      composer.addPass(new RenderPass(scene, camera));
      if (G.tier === 'high') {
        const ao = new GTAOPass(scene, camera, w, h);
        ao.blendIntensity = 0.85;
        ao.updateGtaoMaterial({ radius: 0.32, distanceExponent: 1, thickness: 1, scale: 1.05, samples: 12 });
        composer.addPass(ao);
      }
      composer.addPass(new UnrealBloomPass(new THREE.Vector2(w, h), 0.14, 0.45, 0.93));   // only screens, lamps and alarm lights glow
      composer.addPass(new OutputPass());
    } catch (e) { composer = null; G.tier = 'low'; }     // no float render targets: fall back to a plain render
  }
  function setTier(t, save = true) {
    if (!TIERS.includes(t)) return;
    G.tier = t; slow = 0; ema = 16;
    lightFor(t);
    if (save) { try { localStorage.setItem('p1_gfx', t); } catch (e) { /* private mode */ } }
    build();
    if (onTier) onTier(t);
  }
  function resize(nw, nh) { w = nw; h = nh; lightFor(G.tier); build(); }
  function render(dt, real = dt) {                        // real: unclamped seconds since the last frame
    if (composer) composer.render(dt); else renderer.render(scene, camera);
    if (pinned || document.hidden || real > 2) return;    // a long gap is a hidden tab or a stall, not a slow GPU
    ema += (real * 1000 - ema) * (real > 0.1 ? 0.5 : 0.05);
    slow = ema > 30 ? slow + real : 0;                    // under about 33 fps
    if (slow > 4 && G.tier !== 'low') setTier(TIERS[TIERS.indexOf(G.tier) - 1], false);
  }
  return Object.assign(G, { setTier, resize, render, next: () => setTier(TIERS[(TIERS.indexOf(G.tier) + 1) % 3]) });
}
