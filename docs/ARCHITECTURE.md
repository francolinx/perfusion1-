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

The surgeon owns two things the student cannot set: cannulation and the aortic cross-clamp.

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
  one thermal mass.
- **Cardioplegia**: arrest level rises with delivered volume and potassium, washes out over about
  22 minutes while clamped and in about a minute once the clamp is off. Root vent, aortic
  insufficiency, missing clamp, coronary sinus pressure and systemic potassium load are modeled.
- **Anticoagulation**: heparin with a 100 minute half-life, ACT linear in units/kg with a
  per-patient sensitivity, protamine 1 mg per 100 units. Protamine with the pump or suckers
  running clots the circuit.

Constants are at the top of the file. Each is a teaching approximation; `docs/ROADMAP.md` lists
the validation work.

## Grading (perfusion/scenario.py)

Deterministic. The score starts at 100 and loses 2, 6 or 20 points per minor, major or critical
finding. Findings come from model events (air, retrograde flow, clotting, distension) and from
scenario rules (sequence, ranges held over time, doses). Language models are never the grader of
record; when voice is added they only map speech to callout IDs and write the debrief prose.
