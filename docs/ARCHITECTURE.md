# Architecture

```
            +---------------------------- one Python process ----------------------------+
 browser    |  server.py        scenario.py              model.py                        |
 three.js   |  GET /api/state   Case: phases, surgeon,   Sim: patient + circuit,         |
 client  <--+  POST /api/action grader, objectives  -->  step() at 50 Hz                 |
            |  POST /api/reset  autopilot.py (expert)    personas.json                   |
            +-----------------------------------------------------------------------------+
```

## The contract any renderer uses

- `GET /api/meta`: personas, callouts, phase list.
- `GET /api/state`: one JSON snapshot (poll at about 10 Hz). Patient and circuit values, the
  student's control settings, alarms, phase, surgeon lines, objectives, score.
- `POST /api/action`: one student action.
  - `{"type":"set","key":K,"value":V}` with K in `rpm_set, art_clamp, ven_occl, sweep, fio2,
    iso, water_set, cp_route, cp_type, cp_flow, cp_on, root_vent, sucker, ventilator, epi`
  - `{"type":"heparin","units":N}`, `{"type":"protamine","mg":N}`, `{"type":"phenylephrine","mcg":N}`
  - `{"type":"volume","ml":N,"kind":"crystalloid"|"prbc"}`, `{"type":"transfuse","ml":N}`
  - `{"type":"measure","what":"act"|"abg"}`, `{"type":"callout","id":ID}`
  - `{"type":"speed","x":N}` (0 pauses), `{"type":"autopilot","on":bool}`
- `POST /api/reset`: `{"persona":ID,"operate_minutes":N}` starts a new case, paused.

- `GET /api/state` also carries `session`: `{id, practice, resumed_from, autopilot_used}` (added with saves).

Saves (one JSON file each under `saves/`, git-ignored):
- `POST /api/save` `{"name", "description", "overwrite"?}`: saves the whole case now. A name that is already
  taken answers 409 with `confirm: "overwrite"` and the existing save's details; send again with `overwrite: true`.
- `GET /api/saves`: every save with name, description, persona, phase, case time, score, date and build.
- `POST /api/load` `{"id", "force"?}`: replaces the running case with the save, paused. A save from a different
  build (git commit) answers 409 with `confirm: "build"` and both versions; send `force: true` to load anyway.
  A damaged or incompatible save answers 400 and the running case is untouched.
- `DELETE /api/saves/{id}`.
- An automatic save is written at the start of every phase from "Go on bypass" to "Off bypass", labelled
  `Auto: <phase>`; the last 10 are kept.

Session logs (one JSON file each under `logs/`, git-ignored):
- `GET /api/sessions`: date, persona, score, case and real duration, status, practice flag.
- `GET /api/sessions/{id}`: the full event log (every action with its case time and source, surgeon lines,
  phase changes, findings, saves and loads, final score and checklist) and the summary.
- The summary is built from the event log by fixed rules (`perfusion/sessionlog.py`): what was done in each
  phase, what went well, what was flagged and when, three things to improve. A language model may polish the
  wording later; it never changes the facts or the score.
- A session that loaded a save is marked practice (resumed from save), so its score is not compared with clean
  start-to-finish runs. A session is only written once the student (or the expert) does something.

Saves are exact: a save holds every field of the case, the model and the expert autopilot, and loading it then
running gives identical numbers to never having stopped (`tests/test_saves.py`).

Dashboard (`perfusion/monitor.py`, page `web/dashboard.html`):
- `GET /dashboard`: the status page. It polls `GET /api/dashboard` once a second.
- `GET /api/dashboard`: `{sim, services, system, build}`. `sim` has steps/s, real-time factor, tick lag (how
  late the 20 Hz server loop wakes, in ms), speed, phase and connected clients (tabs that polled `/api/state`
  in the last 5 s; the client tags its polls with `?c=<tab id>`). `system` reads `/proc/stat`, `/proc/meminfo`,
  the disk holding the repo and `nvidia-smi`. `build` has the git branch and commit (read from `.git`, no git
  program needed), the last `./run.sh --test` result (`logs/last_test.json`) and the live features.
- Each AI service runs on its own and answers `GET /health` with JSON:
  `{"model", "loaded", "memory_mb", "latency_ms", "tokens_per_s", "requests", "last_error"}` (any may be null).
  Default addresses: ASR `127.0.0.1:9201`, surgeon LLM `:9202`, medical LLM `:9203`, TTS `:9204`; override with
  `PERFUSION_ASR_URL`, `PERFUSION_SURGEON_URL`, `PERFUSION_MEDICAL_URL`, `PERFUSION_TTS_URL`. The server probes
  them from a background thread with a 0.5 s timeout, so a slow or missing service never delays a page. Nothing
  listening shows "not running"; a bad reply shows "error" with the reason.

The surgeon owns two things the student cannot set: cannulation and the aortic cross-clamp.

## Game layer

- `POST /api/reset` takes `student`; the cleaned name is stored on the session log.
- The session log also records a time series every 5 seconds of case time (`series_keys`, `series`).
- `GET /api/leaderboard?persona=&since=today&student=`: ranked rows, the student's best and rank, and levels.
  Only finished, named, hand-flown runs that were not resumed from a save are ranked. Order: score, then
  fewer criticals, fewer findings, more time in range, more callouts, shorter case, earlier run.
- `GET /api/quiz/<session>` returns four questions without answers; `POST` grades them once and stores the
  result on the session log. Items are chosen by the run's findings, worst first, then by a hash of the id.
- Pages: `/leaderboard`, `/run?id=<session>`.

## Rendering tiers (web/gfx.js)

high: ambient occlusion, bloom, 4x MSAA, refractive clear plastic. med: bloom and MSAA. low: plain render at a
reduced pixel ratio, no lighting bake. The tier drops one step after 4 seconds under about 33 fps unless the
URL pins it with `?gfx=`. All of it is display only; nothing here touches the model or the score.

## Model (perfusion/model.py)

Lumped parameters, explicit Euler at 20 ms. Flows in L/min, volumes in mL, pressures in mmHg.

- **Venous drainage**: gravity siphon head plus CVP over line resistance, scaled by clamp
  occlusion, collapsing as the patient empties. Cannula resistance scales with body size.
- **Reservoir**: volume integrator. Empty with the pump running means air embolism.
- **Centrifugal pump**: head = a*rpm^2 - b*Q^2 solved against circuit and cannula resistance and
  patient arterial pressure, so flow falls when afterload rises and runs backward if the pump is
  slower than patient pressure with the arterial line open.
- **Patient circulation**: venous compliance gives CVP from volume; a Starling-type heart ejects
  from CVP, contractility, rhythm and injury; a one-compartment arterial Windkessel gives MAP.
  SVR depends on hematocrit (viscosity), temperature, phenylephrine and anesthetic vapor.
- **Blood**: red-cell volume is tracked separately in patient and circuit, so hemodilution by the
  prime, cardioplegia crystalloid and added fluid emerges from the flows.
- **Gas exchange**: PaO2 from FiO2 and oxygenator efficiency, PaCO2 from CO2 production over sweep,
  mixed with lung blood by flow. DO2i, VO2 (Q10 2.2 with temperature), SvO2, lactate from O2 debt.
- **Heat**: heater-cooler water relaxes to set point, heat exchanger effectiveness 0.65, patient as
  one thermal mass. A second water circuit feeds cardioplegia (`cp_water_set`); either circuit's pump can be
  switched off (`hc_on`, `cp_hc_on`), and its water then drifts toward room temperature.
- **Monitor values**: PA pressure is CVP plus `PVR` times the heart's own output, so it falls to CVP and goes
  flat on full bypass; arterial and PA systolic/diastolic come from the pulse; pulse oximetry reads only with
  a pulse. Urine is about 1 mL/kg/h at normal pressure and temperature, scaled by the persona's `renal`
  factor, and is part of the patient's volume loss. The ACT result has a second, deterministic channel.
- **Roller pumps** (`Sim.rollers()`): arterial (idle; the centrifugal pump is the arterial pump), cardioplegia,
  sucker and vent, each with flow, RPM from tubing stroke volume (`ROLLER_ML_PER_REV`), percent of full speed
  and tubing size. Sucker and vent speeds (`sucker_max`, `vent_max`) cap the blood they return; a sucker that
  is too slow leaves the rest in the field.
- **Cardioplegia**: arrest level rises with delivered volume and potassium, washes out with an 18 minute
  time constant while clamped (activity returns about 22 minutes after a full dose) and in about a minute once the clamp is off. Root vent, aortic
  insufficiency, missing clamp, coronary sinus pressure and systemic potassium load are modeled.
- **Anticoagulation**: heparin with a 100 minute half-life, ACT linear in units/kg with a
  per-patient sensitivity, protamine 1 mg per 100 units. Protamine with the pump or suckers
  running clots the circuit.

Constants are at the top of the file. Each is a teaching approximation; `docs/ROADMAP.md` lists
the validation work.

## Pump console and patient monitor (web/console.js, web/monitor.js)

The cart is laid out like the lab's machine (docs/LAB_FIDELITY.md sections 1 and 2): roller pump modules on the
base with their own screens, dials with light rings and stop buttons, roller heads that turn at the RPM in
`/api/state`, a centrifugal pump console on its own mast, a mast column of pressures with limits, timers and
temperatures, and a tray. Aim the centre of the view at a dial and use the mouse wheel or drag to turn it, or
click a stop button; both post the same `set` actions as the panels (throttled to one every 80 ms). The patient
monitor by the table and the wall repeater share one canvas. Both modules only draw state and post actions.

## Instructor (perfusion/instructor.py)

`GET /api/instructor` returns the state plus true values the student cannot see and the instructor's current
settings; `POST /api/instructor` takes one operation (`knob`, `rhythm`, `event`, `say`, `speed`, `neutral`).
Knobs are multipliers and offsets inside `Sim.step` (`Sim.inst`); at their neutral values the model is
unchanged. The instructor never writes findings, credits or the score: the model reacts and the usual rules
grade the student. Any change other than pace marks the run `instructor_used`, which keeps it off the
leaderboard. There is no login: run the simulator on a trusted network.

## Grading (perfusion/scenario.py, perfusion/rubric.py)

Student timers: bypass, cross-clamp and cardioplegia timers that the student starts, stops and resets
(`timer` action; console buttons, the Timers panel). Nothing runs by itself, and the live displays show these
timers, not the simulator's own clocks. The surgeon asks for the clamp time, the time since the last dose and
the bypass time; a `report` action answers with what the student's timer reads. Rubric C1b, D4 and F5b
compare the timers and answers with the true times (within a minute).

Deterministic. The scenario records credits (steps done), callouts and findings (errors, each with a
severity). `rubric.py` turns that record into a component rubric: six sections worth 100 points
(A setup and air-free prime 30, B calculations and readiness 10, C going on bypass 15, D management on
bypass 15, E cardioplegia delivery 15, F weaning and coming off 15). Each component earns full, half or
zero of its points, and every lost point carries the reason, taken from the finding or missed step that
cost it. The pass mark is 80. Any critical finding fails the run whatever the points.

A component the simulator cannot observe yet (all of section A, some calculations, sample labelling,
the venous sample) is marked not observed: it scores nothing and is left out of the total. The score is
the share of observable points earned (57.5 of the 100 today), and the debrief says how many points are
not simulated, so it is never presented as a complete examination total. Mid-case, only components
whose phase is over are graded. Findings with no rubric component are still listed in the debrief.
To make a component observable, add the rule and its test, then replace its `_na` entry in `COMPONENTS`.
Language models are never the grader of record; when voice is added they only map speech to callout IDs
and write the debrief prose.
