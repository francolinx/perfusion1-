# perfusion1

An open, walk-around 3D trainer for running a heart-lung machine (cardiopulmonary bypass) case.
You stand in a sim lab, walk up to the pump, clamps, gas blender, heater-cooler, cardioplegia
and drug cart, and run a full case against a real-time physiology model while a surgeon talks
you through it. Every run is graded the same way from the event log.

**Educational software. The physiology is plausible, not clinically validated. Not for patient care.**

## Run it (DGX Spark, any Linux, macOS)

```bash
git clone https://github.com/francolinx/perfusion1-.git
cd perfusion1-
./run.sh
```

That is the whole install. It needs Python 3.9+ and a browser, nothing else: no pip, no npm,
no internet (three.js is vendored). It opens `http://localhost:8080`. From a laptop, phone or
headset on the same network, open `http://<spark-ip>:8080`.
If another program already uses port 8080, the server stops with a plain message instead of a
traceback: `Port 8080 is already in use by another program. Start on a free port instead, for
example:  PORT=9000 ./run.sh`. On the DGX Spark used for development, a local gateway holds 8080,
so the simulator runs there on port 9000.

`./run.sh --test` runs the test suite and plays a full expert case headless.

## What the first demo does

- **Watch the expert run it**: an autopilot plays the whole case through the same controls a
  student uses. Set time to 5x or 20x and walk around while it runs.
- **Start case**: you run it. Heparin and ACT, go on bypass, gases, cool to 34 C, cross-clamp,
  1 L antegrade and 250 mL retrograde cardioplegia, maintenance dose, hot shot, rewarm,
  clamp off, wean at three-quarter, half and quarter flow, come off, give volume, protamine.
- **Ten patients**: standard adult (the 75 kg case from the lab video), small anemic,
  large adult, low ejection fraction, kidney disease, heparin resistance, aortic insufficiency,
  vasoplegia, hypertension, Jehovah's Witness. `docs/BENCHMARK.md` has the 100-run benchmark.
- **Debrief**: score, checklist, time in range for pressure and oxygen delivery, callouts made,
  and every finding with its timestamp. The sequencing error from the lab video (bringing flow
  back up before the clamp is off) is one of the things it catches.

Controls: W A S D to move, mouse to look (click the room first), Space to jump, C or Ctrl to
crouch, Shift or double-tap W to sprint, V to switch between first person and third person (behind
and in front, so you can see yourself in scrubs). E or click to use equipment, T to talk to the
surgeon, Tab for every control panel, Esc to close. B toggles smash mode: a just-for-fun rage room
with a baseball bat (click or F to swing) where the equipment breaks, with sound. It pauses the
case, is never graded, and leaving it rebuilds the lab. On a phone: left pad moves, drag to look,
Jump / Crouch / View buttons, Controls button for the panels.

Saves and sessions: F5 quick-saves (it never reloads the page here), F9 opens Save / Load, where you name a
save, add a description, and see persona, phase, case time and date for each one before loading. The case also
saves itself at the start of every phase (last 10 kept). Loading a save turns that run into practice, so its
score is kept apart from clean runs. Sessions lists every past session with its plain-English summary (what you
did in each phase, what went well, what was flagged, three things to improve) and the full timeline. Saves go in
`saves/` and logs in `logs/` (both git-ignored; `--saves-dir` and `--logs-dir` change that).

Ctrl+W closes a browser tab and no page can stop that, so the page asks before leaving a running
case. C is the safer crouch key. The surgeon's browser voice is a placeholder and starts off on
desktop Linux (press Voice to turn it on); a local voice service will replace it.

## How it is built

```
perfusion/model.py      patient + circuit physiology, 50 Hz, pure Python
perfusion/personas.json patient parameter files
perfusion/scenario.py   case phases, scripted surgeon, rule-based grader
perfusion/autopilot.py  expert policy (used by tests and the demo)
perfusion/server.py     standard-library HTTP server: state polling + actions
web/                    three.js first-person client (no build step)
tests/                  unittest suite
docs/                   model notes, roadmap, research brief pointers
```

The physiology, scenario and grading core is engine-agnostic: any renderer (this web client,
an Isaac Sim / Omniverse Kit app, a headset) talks to it through two endpoints,
`GET /api/state` and `POST /api/action`. See `docs/ARCHITECTURE.md`.

## Status and limits

Version 0.1. The model is a lumped-parameter teaching model written for this project; it has
not been reviewed by a certified clinical perfusionist yet, and numbers should not be taken as
clinical reference values. One shared session per server. See `docs/ROADMAP.md` for what is next
(Pulse physiology engine, Isaac Sim room, local voice surgeon, crisis scenarios).
