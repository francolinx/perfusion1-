# Matching the real simulation lab

Source: photos of the school's perfusion simulation lab taken on 27 November 2026 (a heart-lung machine driven
by a commercial patient simulator, the instructor's laptop, the wall monitor, a blood gas report) and one
screenshot of the browser trainer the students use today. This file lists what the lab has, what perfusion1
has, and what to build so a student who learns here is at home there.

Rules that apply to everything below: match the function and layout of real equipment, never copy a vendor's
screen, wording, logo or art. Name equipment by what it is ("centrifugal pump console"), not by brand.
Renderers still never compute physiology.

## 1. Pump console (highest value for students)

The lab machine is not one panel. It is:

- A **centrifugal pump console** on its own mast: large flow (L/min), RPM, cardiac index, arterial line
  pressure, a row of status icons, one speed dial with a light ring.
- A row of **roller pump modules** on the base, each with its own small screen, a dial with a light ring and a
  stop button: an arterial roller (idle when the centrifugal pump is used), a cardioplegia pump (L/min, percent,
  tubing size, RPM) and a double module for sucker and vent/root. The roller heads sit above them under clear
  covers and visibly turn.
- A **mast column of three small displays**: pressures with limits, timers, temperatures.
- A tray with tubing clamps, syringes and drug vials.

perfusion1 today: one flat panel per device, opened with E. Build: a console scene with the modules laid out as
above, each dial turnable with the mouse wheel or drag, roller heads that spin at their RPM, per-pump stop
buttons, and the mast displays. Add RPM and tubing size to the cardioplegia, sucker and vent readouts
(the model already has cardioplegia flow; sucker and vent flows need an L/min value in `/api/state`).

## 2. Patient monitor

The lab shows one large monitor, repeated on a wall screen, with: ECG, arterial pressure (systolic/diastolic and
mean), pulmonary artery pressure and CVP as scrolling traces with numbers; pulse oximetry; esophageal
temperature; urine output; a mode label (before bypass / on bypass); a header with age, sex, weight and body
surface area; a two-channel ACT box; heater-cooler water temperature with pump on/off for the patient circuit
and for cardioplegia; coloured tiles for arterial saturation, venous saturation, hematocrit and arterial flow;
reservoir level bars; an alarm banner.

perfusion1 today: a HUD list of vitals and one arterial trace. Build: a monitor screen in the room and a wall
repeater that draw scrolling ECG, arterial, PA and CVP traces from `/api/state` (flat arterial line on full
bypass, pulsatile when ejecting, as in the photos), plus the tiles and boxes above. New state needed: PA
pressure, urine output, a second ACT channel, cardioplegia water temperature. Each is a model change and needs
a test.

## 3. Blood gas report

The lab analyzer returns a printed-style report: accepted status, time, sample source (for example
post-oxygenator), values at 37 C: pH, pCO2, pO2, sodium, potassium, ionised calcium, glucose, lactate,
hematocrit, then derived bicarbonate, base excess and saturation.

perfusion1 today: pH, pO2, pCO2, saturations, hematocrit, potassium, lactate, arterial only. Build: a report
card in that order with a sample source choice (arterial, venous, post-oxygenator), sample number and time, and
the missing analytes (sodium, calcium, glucose, bicarbonate, base excess) from simple rules. A venous sample to
draw and act on also unlocks rubric items D1b and D2 (4.5 points, see `docs/ROADMAP.md`).

## 4. Circuit and room

Lab: a yellow-tinted hard-shell venous reservoir with printed level marks low on the cart, oxygenator beside
it, a sampling manifold with syringes, tubing coiled on an IV pole, hanging prime and cardioplegia bags, a
heater-cooler on the floor. Room: wood-look floor, blue accent wall and cabinets, an operating table with a
draped mannequin, an instructor desk with a laptop, a numbered wall monitor, a headwall with gas outlets,
ceiling cameras, a supply shelf.

Build: retint and re-place the existing room to this layout (it is a teaching lab, not a full operating room),
add the reservoir level marks so the level can be read off the shell, and seat the student at the console by
default with a key to stand and walk.

## 5. Instructor panel

Done in this change (`/instructor`, `perfusion/instructor.py`): live true values, patient controls (vascular
resistance, contractility, oxygen demand, blood loss, rhythm), circuit faults (oxygenator performance, arterial
line obstruction, venous obstruction), one-off events (ACT falls, potassium rises, vasodilation, pressure
surge), time factor and pause, speaking as the surgeon, a log of every change, and the student's score so far.
Instructor-led runs are logged and not ranked.

Still to build, all seen on the lab's instructor screen: a scenario step list the instructor can jump between
(before bypass, heparin, on bypass, antegrade, retrograde, hot shot, weaning); advance the clock by N minutes;
edit blood chemistry directly; pulmonary and ventilator pages; saved scenarios an instructor can author and
replay; a choice of voices for spoken lines. Jumping between steps must go through the scenario so grading
stays consistent, and a jumped run stays unranked.

## 6. Where perfusion1 should beat the browser trainer the students use now

That trainer shows a fixed camera, hand-held plus/minus pump controllers, timers the student starts, blender
flowmeters and a health bar. perfusion1 should keep its advantages and add the two things it lacks:

- Keep: a physiological model that reacts continuously, the rubric with the reason for every lost point, run
  charts, the leaderboard, the instructor panel, walking the room.
- Add: timers the student starts and stops (heparin in, bypass, cross-clamp, cardioplegia), which also unlocks
  rubric items C1b, D4 and F5b; and gas flowmeters with a blender dial in place of two number fields.
