# Roadmap

Ordered. Each item says where it has to be built.

## Next, buildable anywhere

1. **Clinical review pass.** Sit with a certified clinical perfusionist, walk every constant in
   `model.py` and every rule in `scenario.py`, and record the changes. Wrong teaching is worse
   than no teaching.
2. **Crisis scenarios** (scheduled or conditional faults on top of the routine case):
   reservoir emptying, massive air, venous air lock, oxygenator failure and change-out,
   heater-cooler failure, pump failure and hand crank, power failure, heparin resistance,
   protamine reaction with return to bypass, cannula malposition.
3. **More patients**: pediatric (12 kg), Jehovah's Witness blood conservation, VA-ECMO.
   Pediatric needs circuit constants per size, not only persona fields.
4. **Per-student sessions and saved logs** (the server is single-session today).
5. **Swap the patient model for the Pulse Physiology Engine** (Apache-2.0) behind the same
   `Sim` interface, keeping the circuit, cardioplegia and anticoagulation code here.

## Needs the DGX Spark

6. **Isaac Sim / Omniverse Kit room.** A Kit Python extension that builds the same room in USD
   and drives it from `GET /api/state`, sending `POST /api/action` on interaction. Check the
   current Isaac Sim release notes for aarch64 limits first: at the time of the research brief,
   XR and livestreaming were not supported on DGX Spark, which is why the web client stays as the
   path to laptops and headsets.
7. **Local voice surgeon.** Speech recognition to callout IDs, a small local language model for
   the surgeon's replies and the debrief prose, text to speech for the voice. The browser's
   built-in speech synthesis is the placeholder today.
   On the development Spark the local model library is at `~/ssd/GB10_ARSENAL/models` (internal disk).
   Starting set: `speech/parakeet-tdt-0.6b-v2` (speech recognition), `reasoning/nemotron-3-nano-30b-a3b-nvfp4`
   (surgeon), `speech/kokoro-82m` (voice) and `healthcare/medgemma-4b-it` (info button). MedGemma 27B text
   is a later upgrade.
8. **Synthetic data export** for decision-support research: labeled trajectories from the
   autopilot with injected faults.

## Evidence

9. Face and content validity study with perfusionists, then a study of time to competency.
   Nothing published yet shows a simulator reduces the clinical cases a student needs; this
   project should measure it rather than claim it.
