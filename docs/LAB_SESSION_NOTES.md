# What the students actually do and say in the lab

Source: an automatic transcript of about two hours of practice runs in the school's simulation lab on
27 November 2026 (several students taking turns as perfusionist and as surgeon, plus a senior student giving
feedback). The raw transcript is not in this repository: it contains names and unrelated conversation. This
file keeps only the procedure, the call-and-response and the feedback, with no names. Automatic transcription
garbles words, so anything marked (unclear) should be checked with a student before it is built.

Educational use only. Doses and thresholds here are what was said in a teaching lab, recorded so the simulator
can rehearse the same script. They are not clinical reference values.

## The run, in the order it was performed

**Before the surgeon starts**
- Prime within the limit (45 minutes on the exam; one student took about 32). Advice given: go slowly,
  because rushing is when air gets in. The two failures everyone named: air in the circuit, and letting the
  reservoir drain.
- Draw up the drugs first: lidocaine 100 mg, magnesium 2 g, calcium 1 g, esmolol 50 mg (the surgeon may decline
  the esmolol). Know the volume for each dose from the vial concentration; a student was caught not knowing it.
- Set the pressure limit (about 400 was agreed), keep alarms on (required on the final), check the level
  sensor, check the cardioplegia pump occlusion, close the shunts, reset the timers.

**Lines up and anticoagulation**
- Surgeon: "Can I divide the AV loop?" Perfusionist passes the lines, confirms, runs an ACT on the sample from
  anesthesia.
- Surgeon asks for height and weight, then **high flow and low flow**. Example given: 170 cm, 70 kg, body
  surface area 1.81, high flow 4.34 L/min (index 2.4), low flow about 3.25 L/min (index 1.8).
- Heparin dose stated and confirmed (28,000 units for 70 kg), then anesthesia gives it.
- Surgeon may ask for the **hematocrit after dilution**: weight x 70 x starting hematocrit, divided by
  (weight x 70 + prime volume). With 36% and 1,500 mL of prime the answer given was about 27.5%.
- ACT over 300 to cannulate; over 480 to go on bypass. Suckers on.
- "Advance the arterial line": bring it up slowly, stop on "off".
- "How is the pressure?" Expected answer: the line pressure matches the patient's mean pressure and is
  pulsatile.
- **Line test**: push a small volume (100 to 200 mL), watch for flow, and report that mean pressure and CVP
  rose slightly. That confirms the cannula position.

**Going on bypass**
- The order the students drill: **timer, sweep gas, then the pump**. Start the bypass timer, turn the sweep gas
  on, confirm venous drainage, open the arterial line, come up to full flow. Forgetting the sweep gas was one
  student's worst error of the day.
- Root vent on when asked. Draw a venous gas and an arterial gas, read potassium and saturation aloud, adjust.
- Only then ask anesthesia to stop ventilating, and ask the surgeon what temperature to cool to (34 C each time).
- "How is your bypass?" Expected answer: ACT good, pressure non-pulsatile, CVP near zero. If the trace is still
  pulsatile the heart is not empty: adjust flow and drainage (index 2.2 to 2.4).
- Prime the cardioplegia line with high-potassium solution before the clamp.

**Cross-clamp and cardioplegia**
- "Flow down" / "clamp on" / "flow up", then **start the clamp timer**. The timer was forgotten in most runs.
- The surgeon chooses the dose each time: 1 L, 800 mL, 500 mL or 400 mL of high-potassium antegrade were all
  asked for. Root vent must be **off** for antegrade; leaving it on twice stopped the heart arresting.
  Delivery ran at about 250 rising to 400 mL/min with line pressure 230 to 250, called out as it rose.
- Retrograde 300 to 400 mL with the root vent on, about 200 mL/min, line pressure 90 to 130. The perfusionist
  must **ask to see the coronary sinus pressure** before starting, because anesthesia has to switch the
  display; target about 40.
- Call the arrest, start the cardioplegia timer, draw a gas after every dose (potassium about 6 after the
  high-potassium dose), and report protection: flat ECG, heart cold.
- Call out time since the last dose (10 and 20 minutes). Re-doses are low-potassium unless told otherwise,
  given until the ECG is flat. Asking "high or low K?" before giving was praised.
- A slow low-potassium infusion while the surgeon sews a graft was also asked for (unclear: called
  "vein speed"; rate not captured).

**Rewarming and clamp off**
- Rewarm to 37 C, recirculate the hot shot, recheck ACT, draw a gas. The surgeon picks the hot shot route
  (retrograde or antegrade) and volume (about 400 mL).
- "Flow down" / "clamp off" / "flow up", stop the clamp timer and report the clamp time.
- Give the drugs: lidocaine, magnesium, esmolol if wanted; calcium **10 minutes later** (the instructor
  shortened the wait in simulator time).

**Weaning**
- Before weaning: a gas, ventilator back on, another gas to prove the ventilator is working, patient warm, and a
  **rhythm on the ECG**. Asked "which two organs are you supporting?" the answer is heart and lungs.
- If the heart is still flat after the hot shot: drugs. If it fibrillates or goes into ventricular
  tachycardia: shock, raising the energy if it persists. A flat line is not shocked.
- **Do not start weaning without a rhythm and a pulsatile pressure.** This was named as the one thing that
  would fail an otherwise passing run.
- Fill in small bites, 100 to 200 mL at a time, until the dicrotic notch appears on the arterial trace, then
  come down to three-quarter flow and hold the level; bigger bite, half flow, hold; quarter flow, hold. The
  rubric expects all three holds; skipping straight to half was questioned.
- What the surgeon wants while filling: 400 to 600 mL in total is usually enough to fill the heart, CVP no
  more than about 14, mean pressure about 75 to 80. "Take 200 back" when the heart is too full.
- Off bypass at a low flow, close the shunts, protamine 300 mg, suckers off, **stop the bypass timer** and
  report the bypass time. Keep the cardioplegia cooler ready in case of going back on.

## Feedback the students gave each other

- Timers: bypass, clamp and cardioplegia timers were missed more than anything else.
- Sweep gas forgotten at initiation.
- Clamp configuration that left the pump pulling against a closed line and cavitating: one of two lines must
  be open.
- Root vent left on during antegrade.
- Say more, not less: "I would rather you communicate more than less."
- Rushing. "Once you are above 80 a few times, then you can speed up."

## What they said about the browser trainer they use now

It teaches the order of steps, but it deducts points for holding levels to a very exact value, it is slow to
get through, and the student cannot choose or change the patient.

## What perfusion1 should build from this

Ordered by how often it came up in the runs. Each needs its rule, its test and, where noted, a rubric item.

1. **Student-run timers** for bypass, cross-clamp and cardioplegia, with the surgeon asking for the times.
   Unlocks rubric C1b, D4 and F5b. *Built: `timer` and `report` actions, console timer buttons, Timers panel,
   surgeon asks for clamp time, time since the last dose and bypass time; graded against the true times.*
2. **Rhythm before weaning**: after the clamp comes off the heart may be flat, fibrillating or in sinus rhythm.
   Drugs (lidocaine, magnesium, esmolol, calcium at 10 minutes) and a defibrillator the student calls for.
   Starting to wean with no rhythm or no pulse is a critical finding.
3. **Weaning by volume**: fill in bites, watch for the dicrotic notch, the surgeon asks for volume back,
   CVP and pressure targets, holds at three-quarter, half and quarter flow.
4. **Surgeon questions that are scored**: height and weight, high and low flow, heparin dose, hematocrit after
   dilution, current flow, clamp time, bypass time, reservoir volume. Unlocks rubric B1.
5. **Before bypass**: divide the loop, ACT over 300 to cannulate, advance the arterial line, the pulsatile line
   pressure check and the line test. Unlocks rubric B3c.
6. **Cardioplegia as the lab does it**: the surgeon varies route, solution and volume; prime the line first; ask
   for the coronary sinus pressure display; root vent off for antegrade; a gas after each dose.
7. **Sweep gas off by default** so that turning it on at initiation is a real step (today it starts on).
8. **Drug doses in millilitres**: the student draws up a volume from a stated concentration. Unlocks rubric B2c.
9. In the instructor panel: one-click "wrenches" seen in these runs (flat heart after the hot shot, ventricular
   tachycardia on reperfusion, poor arrest needing another dose).
