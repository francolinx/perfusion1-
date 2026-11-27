"""Component rubric for a bypass run: six sections, 100 points, pass at 80.

The layout follows the kind of component checklist a perfusion programme uses for a final
simulator examination: A setup and air-free prime (30), B calculations and readiness (10),
C going on bypass (15), D management on bypass (15), E cardioplegia delivery (15), F weaning
and coming off (15). Each component earns full, half or zero of its points.

Everything here is decided by rules over the case record (credits, callouts, findings, flags),
so the same run always gets the same score. A component the simulator cannot observe yet is
"not observed": it earns nothing and is left out of the total, and the report says how many
points that is. The score is the share of observable points earned.

Educational use only. This is a teaching score, not a clinical or examination record.
"""

PASS_SCORE = 80.0
ORDER = ["PRE", "INITIATE", "STABILIZE", "COOL", "CLAMP_ON", "ANTEGRADE", "RETROGRADE",
         "OPERATE", "HOTSHOT", "REWARM", "CLAMP_OFF", "WEAN", "POST", "DONE"]

SECTIONS = [("A", "Setup and air-free prime", 30), ("B", "Calculations and readiness", 10),
            ("C", "Going on bypass", 15), ("D", "Management on bypass", 15),
            ("E", "Cardioplegia delivery", 15), ("F", "Weaning and coming off", 15)]

NOT_BUILT = "The simulator starts with the circuit already built and primed."
NO_CALC = "The simulator works this out for you, so there is nothing to grade yet."
TOL = 60.0      # seconds a timer may be off (scenario.TIME_TOLERANCE)
NO_VENOUS = "There is no venous sample to draw yet; venous saturation is shown continuously."

CREDIT_WHY = dict(
    heparin="Heparin dose was under about 300 units per kg.",
    act="No ACT over 400 seconds was confirmed after heparin.",
    full_flow="Full flow was never reached.",
    abg="No blood gas was run after going on bypass.",
    cooled="The patient was not cooled to the target temperature.",
    rewarmed="The patient was not rewarmed to 36 C.",
    antegrade="The antegrade induction dose was not completed.",
    retrograde="The retrograde dose was not completed.",
    vent_on="The ventilator was not turned back on for weaning.",
    wean_0="Three-quarter flow was not held with the heart ejecting and pressure over 50.",
    wean_1="Half flow was not held with the heart ejecting and pressure over 50.",
    wean_2="Quarter flow was not held with the heart ejecting and pressure over 50.",
    off_bypass="Did not come off with flow at zero and both lines clamped.",
    protamine_dose="Protamine was not about 1 mg per 100 units of heparin.",
)
CALL_WHY = dict(
    PRE="Did not tell the surgeon the ACT was good and you were ready.",
    INITIATE="Did not call out 'on bypass, full flow'.",
    STABILIZE="Did not report that bypass and gases looked good.",
    COOL="Did not call out 'at temperature'.",
    CLAMP_ON="Did not call out 'back at full flow' after the clamp went on.",
    ANTEGRADE="Did not call out that the cardioplegia was in.",
    RETROGRADE="Did not call out that the heart was arrested.",
    OPERATE="Did not call out the maintenance dose.",
    HOTSHOT="Did not call out that the hot shot was in.",
    REWARM="Did not call out that the patient was warm.",
    CLAMP_OFF="Did not call out 'back at full flow' after the clamp came off.",
    WEAN="Did not call out 'off bypass'.",
)


def _c(cid, label, mx, due=None, credits=(), calls=(), flags=(), lose=None, fn=None, na=None):
    return dict(id=cid, label=label, max=mx, due=due, credits=credits, calls=calls, flags=flags,
                lose=lose or {}, fn=fn, na=na)


def _na(cid, label, mx, why):
    return _c(cid, label, mx, na=why)


# ---- custom checks: return (fraction of the points, [reasons]) ----------------
def _first_gas(key, lo, hi, what, knob):
    def fn(case):
        first, end = case.flags.get("abg1"), case.flags.get("gas_end")
        if first and lo <= first[key] <= hi:
            return 1.0, []
        if first is None:
            return 0.0, ["No blood gas was run on bypass, so the " + knob + " setting was never checked."]
        if end and lo <= end[key] <= hi:
            return 0.5, [f"First gas on bypass showed {what} {first[key]:.0f} (target {lo} to {hi}); you corrected the {knob} afterwards."]
        return 0.0, [f"{what} was {first[key]:.0f} on the first gas and still outside {lo} to {hi} when the surgeon moved on: adjust the {knob}."]
    return fn


def _gases_corrected(case):
    end = case.flags.get("gas_end")
    if not end or "abg" not in case.credits:
        return 0.0, ["No blood gas was run, so there was nothing to respond to."]
    bad = []
    if not 35 <= end["paco2"] <= 45:
        bad.append(f"CO2 {end['paco2']:.0f} (target 35 to 45, change the sweep gas)")
    if not 150 <= end["pao2"] <= 400:
        bad.append(f"PaO2 {end['pao2']:.0f} (target 150 to 400, change the oxygen fraction)")
    return (1.0, []) if not bad else (0.5 if len(bad) == 1 else 0.0, ["Still out of range when the surgeon moved on: " + "; ".join(bad) + "."])


def _patient_response(case):
    end = case.flags.get("gas_end")
    if not end:
        return 0.0, ["Bypass was never assessed."]
    bad = []
    if not 50 <= end["map"] <= 80:
        bad.append(f"pressure {end['map']:.0f} (target 50 to 80)")
    if end["do2i"] < 280:
        bad.append(f"oxygen delivery {end['do2i']:.0f} (target 280 or more)")
    return (1.0, []) if not bad else (0.5 if len(bad) == 1 else 0.0, ["Not corrected before cooling: " + "; ".join(bad) + "."])


def _ongoing(case):
    tot = case.in_range["total"] or 1.0
    m, d = 100 * case.in_range["map"] / tot, 100 * case.in_range["do2"] / tot
    lo = min(m, d)
    frac = 1.0 if lo >= 90 else 0.5 if lo >= 75 else 0.0
    why = [] if frac == 1.0 else [f"Pressure was in range {m:.0f}% and oxygen delivery on target {d:.0f}% of bypass time (90% of each for full points)."]
    return frac, why


def _calls(phases, what):
    def fn(case):
        missed = [p for p in phases if p not in case.callouts_done]
        frac = 1.0 if not missed else 0.5 if len(missed) < len(phases) else 0.0
        return frac, [CALL_WHY[p] for p in missed]
    return fn


def _arrest(case):
    if "retrograde" not in case.credits:
        return 0.0, [CREDIT_WHY["retrograde"]]
    if "arrest" not in case.credits:
        return 0.5, ["The dose went in but the heart was not arrested when delivery stopped."]
    return 1.0, []


# ---- student timers (scenario.CLOCKS) ------------------------------------------------
def _started_on_time(mark, what, event):
    """The timer was running and read about right 30 s after the event (started at most a minute early)."""
    def check(case):
        m = case.flags.get(mark)
        if m and m["run"] and 0 < m["read"] <= 30 + TOL:
            return True, None
        if not m or not m["run"]:
            return False, f"The {what} timer was not running 30 seconds after {event}."
        if m["read"] <= 0:
            return False, f"The {what} timer was not running 30 seconds after {event}."
        return False, f"The {what} timer read {m['read'] // 60}:{m['read'] % 60:02d} 30 seconds after {event}: it was started too early or not reset."
    return check


def _answer(case, name, label):
    """The student's answer when the surgeon asked for this time: right within a minute of the true time."""
    if not case.flags.get("asked_" + name):
        return True, None                     # never asked (for example the case ended first)
    r = case.answered(name)
    if r is None:
        return False, f"The surgeon asked for the {label} and got no answer."
    if abs(r["said"] - r["true"]) <= TOL:
        return True, None
    return False, (f"You gave the {label} as {r['said'] // 60}:{r['said'] % 60:02d}; it was {r['true'] // 60}:{r['true'] % 60:02d}. "
                   "Read it off a timer you started at the right moment.")


def _bypass_timer_started(case):
    ok, why = _started_on_time("bp_clock_30", "bypass", "going on bypass")(case)
    if ok:
        return 1.0, []
    if case.flags.get("bp_timer_late"):
        return 0.5, ["The bypass timer was started late, after you were already on bypass."]
    return 0.0, [why]


def _clamp_and_events(case):
    parts = [_started_on_time("clamp_clock_30", "clamp", "the clamp went on")(case),
             _answer(case, "clamp", "clamp time"), _answer(case, "cp", "time since the last dose")]
    return sum(ok for ok, _ in parts) / 3.0, [w for ok, w in parts if not ok]


def _bypass_timer_stopped(case):
    off = case.flags.get("off_t")
    stops = [e["t"] for e in case.clock_log if e["clock"] == "bypass" and e["op"] == "stop"]
    stopped = off is not None and any(off - 15 <= t <= off + TOL for t in stops)
    parts = [(stopped, None if stopped else "The bypass timer was not stopped as you came off bypass."),
             _answer(case, "bypass", "bypass time")]
    return sum(ok for ok, _ in parts) / 2.0, [w for ok, w in parts if not ok]


COMPONENTS = dict(
    A=[_na("A1", "Packaging, sterility, components and prime solution checked", 3, NOT_BUILT),
       _na("A2", "Circuit assembled: raceways, flow direction, loop, recirculation, connections, clamps", 6, NOT_BUILT),
       _na("A3", "Cardioplegia circuit assembled with its transducer", 4, NOT_BUILT),
       _na("A4", "Reservoir, pump, oxygenator, filter and loop primed", 7, NOT_BUILT),
       _na("A5", "Every part of the circuit de-aired and checked air-free", 7, NOT_BUILT),
       _na("A6", "Occlusion, pressure zero and limits, final checklist", 3, NOT_BUILT)],
    B=[_na("B1", "Body surface area, target flow and units worked out", 3, NO_CALC),
       _c("B2a", "Protamine dose worked out from the heparin given", 1, "POST", credits=("protamine_dose",)),
       _c("B2b", "Heparin dosed by weight", 1, "PRE", credits=("heparin",)),
       _na("B2c", "Units written down with each dose", 1, "The simulator fixes the units on each drug."),
       _c("B3a", "ACT checked against the requirement", 1, "PRE", credits=("act",), lose=dict(act_marginal=0.5)),
       _c("B3b", "ACT drawn after the heparin went in", 1, "PRE", credits=("act",)),
       _na("B3c", "Cannula connections and shunts checked", 1, "The surgeon places the cannulas; there is nothing to inspect yet."),
       _c("B3d", "Told the surgeon you were ready", 1, "PRE", calls=("PRE",))],
    C=[_c("C1a", "Closed-loop call with the surgeon on going on", 2, "INITIATE", calls=("INITIATE",)),
       _c("C1b", "Bypass timer started", 1, "INITIATE", fn=_bypass_timer_started),
       _c("C2a", "Sweep gas running as flow came up", 1, "INITIATE", flags=(("sweep_at_init", "Sweep gas was off as you went on bypass."),)),
       _c("C2b", "Oxygen blender set correctly", 1, "STABILIZE", fn=_first_gas("pao2", 150, 400, "PaO2", "oxygen fraction")),
       _c("C2c", "Sweep gas flow set correctly", 1, "STABILIZE", fn=_first_gas("paco2", 35, 45, "CO2", "sweep gas")),
       _c("C3a", "Lines opened in the right order", 2, "INITIATE",
          lose={"unclamp_no_rpm": 1.0, "retrograde@INITIATE": 0.5, "vent_off_early": 0.5}),
       _c("C3b", "Arterial flow brought up under control", 2, "INITIATE", credits=("full_flow",), lose=dict(air_embolism=1.0)),
       _na("C4a", "Venous drainage assessed", 1, "There is no venous drainage check to observe yet."),
       _c("C4b", "Reservoir level kept safe", 1, "COOL", lose={"res_low@STABILIZE": 1.0, "res_low@COOL": 1.0}),
       _c("C4c", "Line pressure kept safe", 1, "COOL", lose={"line_p@STABILIZE": 1.0, "line_p@COOL": 1.0}),
       _c("C4d", "Patient's pressure and oxygen delivery assessed and corrected", 2, "STABILIZE",
          fn=_patient_response, lose=dict(unstable_bypass=0.5))],
    D=[_c("D1a", "Arterial blood gas drawn", 0.5, "STABILIZE", credits=("abg",)),
       _na("D1b", "Sample labelled", 0.5, "Samples are not labelled in the simulator."),
       _c("D1c", "Gas results read and reported", 2, "STABILIZE", credits=("abg",), calls=("STABILIZE",)),
       _c("D1d", "Gases corrected after the result", 2, "STABILIZE", fn=_gases_corrected, lose=dict(co2_range=0.5)),
       _na("D2", "Venous sample drawn, labelled, read and acted on", 4, NO_VENOUS),
       _c("D3a", "Flow, pressure and oxygen delivery held through the case", 1, "REWARM", fn=_ongoing,
          lose={"flow_up_early@CLAMP_ON": 1.0, "clamp_full_flow@CLAMP_ON": 1.0, "map_low": 0.5, "do2_low": 0.5, "cp_interval": 0.5, "hyperkalemia": 0.5, "activity_returning": 0.5, "res_low@OPERATE": 0.5,
                "res_low@HOTSHOT": 0.5, "res_low@REWARM": 0.5, "line_p@OPERATE": 0.5}),
       _c("D3b", "Changes called out to the team", 1, "HOTSHOT", fn=_calls(("CLAMP_ON", "OPERATE", "HOTSHOT"), "changes")),
       _c("D4", "Clamp timer started and key events recorded", 1, "CLAMP_OFF", fn=_clamp_and_events),
       _c("D5a", "Cooled to the assigned temperature", 1, "COOL", credits=("cooled",), lose={"gradient@COOL": 0.5}),
       _c("D5b", "Rewarmed safely", 1, "REWARM", credits=("rewarmed",), lose={"hyperthermia": 1.0, "gradient@REWARM": 0.5}),
       _c("D5c", "Temperature called out", 1, "REWARM", fn=_calls(("COOL", "REWARM"), "temperature"))],
    E=[_na("E1a", "Cardioplegia set-up rechecked just before use", 1, "There is no set-up recheck to observe yet."),
       _na("E1b", "Delivery connections verified", 1, "The delivery lines are already connected."),
       _c("E1c", "Safety checks before delivery", 1, "ANTEGRADE", lose=dict(vent_on_antegrade=1.0, cp_no_clamp=1.0)),
       _c("E2a", "Antegrade dose called out", 1, "ANTEGRADE", calls=("ANTEGRADE",)),
       _c("E2b", "Antegrade route selected", 1, "ANTEGRADE", lose=dict(wrong_route=1.0, ai_antegrade=1.0)),
       _c("E2c", "Antegrade solution and dose delivered", 2, "ANTEGRADE", credits=("antegrade",),
          lose=dict(wrong_solution=0.5, cp_overdose=0.5)),
       _c("E2d", "Antegrade pressure and flow managed", 2, "ANTEGRADE",
          lose={"cp_pressure@ANTEGRADE": 0.5, "vent_stealing": 0.5, "lv_distension": 0.5}),
       _c("E3a", "Retrograde dose called out", 1, "RETROGRADE", calls=("RETROGRADE",)),
       _c("E3b", "Retrograde route selected", 1, "RETROGRADE", lose=dict(wrong_route_retro=1.0)),
       _c("E3c", "Retrograde dose delivered and arrest achieved", 2, "RETROGRADE", fn=_arrest),
       _c("E3d", "Retrograde pressure and flow managed", 2, "RETROGRADE",
          lose={"csp_high": 1.0, "cp_pressure@RETROGRADE": 0.5, "vent_off_after_cp": 0.5})],
    F=[_c("F1a", "Rewarming confirmed before weaning", 1, "WEAN", credits=("rewarmed",), lose=dict(wean_cold=1.0)),
       _c("F1b", "Ventilation confirmed before weaning", 1, "WEAN", credits=("vent_on",), lose=dict(wean_no_vent=1.0)),
       _c("F1c", "Clamp-off sequence coordinated and called out", 1, "CLAMP_OFF", calls=("CLAMP_OFF",),
          lose={"flow_up_early@CLAMP_OFF": 1.0, "clamp_full_flow@CLAMP_OFF": 1.0}),
       _c("F2a", "Heart filled until it ejected", 1, "WEAN", credits=("wean_0",)),
       _c("F2b", "Came down to three-quarter flow", 1, "WEAN", credits=("wean_0",)),
       _c("F2c", "Held and assessed at three-quarter flow", 1, "WEAN", credits=("wean_0",), lose={"wean_before_ejecting#0": 1.0}),
       _c("F3a", "Came down to half flow", 1, "WEAN", credits=("wean_1",)),
       _c("F3b", "Held and assessed at half flow", 2, "WEAN", credits=("wean_1",), lose={"wean_before_ejecting#1": 0.5}),
       _c("F4a", "Came down to quarter flow", 1, "WEAN", credits=("wean_2",)),
       _c("F4b", "Held and assessed at quarter flow", 2, "WEAN", credits=("wean_2",), lose={"wean_before_ejecting#2": 0.5}),
       _c("F5a", "Came off and clamped in the right order", 2, "WEAN", credits=("off_bypass",),
          lose={"retrograde@WEAN": 0.5, "retrograde@POST": 0.5}),
       _c("F5b", "Bypass timer stopped", 0.5, "POST", fn=_bypass_timer_stopped),
       _c("F5c", "Off-bypass status reported", 0.5, "WEAN", calls=("WEAN",))],
)


def _matches(key, f):
    """A lose key is a finding code, optionally limited to a phase (code@PHASE) or a wean step (code#n)."""
    if "@" in key:
        code, ph = key.split("@")
        return f["code"] == code and f["phase"] == ph
    if "#" in key:
        code, n = key.split("#")
        return f["code"] == code and f.get("step") == int(n)
    return f["code"] == key


def _grade(case, comp, passed, used):
    if comp["na"]:
        return dict(id=comp["id"], label=comp["label"], max=comp["max"], earned=None, status="not_observed", why=[comp["na"]])
    if not passed(comp["due"]):
        return dict(id=comp["id"], label=comp["label"], max=comp["max"], earned=None, status="pending", why=[])
    frac, why = 1.0, []
    if comp["fn"]:
        frac, why = comp["fn"](case)
        why = list(why)
    for k in comp["credits"]:
        if k not in case.credits:
            frac = 0.0
            why.append(CREDIT_WHY.get(k, "Step not completed."))
    for p in comp["calls"]:
        if p not in case.callouts_done:
            frac = 0.0
            why.append(CALL_WHY[p])
    for name, msg in comp["flags"]:
        if not case.flags.get(name):
            frac = 0.0
            why.append(msg)
    for key, cut in comp["lose"].items():
        for i, f in enumerate(case.findings):
            if _matches(key, f):
                used.add(i)
                frac -= cut
                if f["msg"] not in why:
                    why.append(f["msg"])
    frac = 1.0 if frac >= 0.99 else 0.5 if frac >= 0.49 else 0.0      # full, half or zero
    why = list(dict.fromkeys(why))
    return dict(id=comp["id"], label=comp["label"], max=comp["max"], earned=round(comp["max"] * frac, 2),
                status="full" if frac == 1.0 else "half" if frac == 0.5 else "zero", why=why)


def _num(x):
    x = int(x * 100 + 1e-6) / 100.0          # two decimals, never rounded up
    return int(x) if x == int(x) else x


def evaluate(case):
    """Score a case against the rubric. Works mid-case: only components whose phase is over are graded."""
    idx = ORDER.index(case.phase)
    passed = lambda due: idx > ORDER.index(due)
    used, sections, missed = set(), [], []
    earned = possible = hidden = 0.0
    for sid, title, mx in SECTIONS:
        items = [_grade(case, c, passed, used) for c in COMPONENTS[sid]]
        got = sum(i["earned"] for i in items if i["earned"] is not None)
        seen = sum(i["max"] for i in items if i["earned"] is not None)
        off = sum(i["max"] for i in items if i["status"] == "not_observed")
        earned, possible, hidden = earned + got, possible + seen, hidden + off
        sections.append(dict(id=sid, title=title, max=mx, earned=_num(got), observed_max=_num(seen), not_observed=_num(off), items=items))
        missed += [dict(id=i["id"], section=title, label=i["label"], lost=_num(i["max"] - i["earned"]), max=i["max"], why=i["why"])
                   for i in items if i["status"] in ("half", "zero")]
    other = [f for i, f in enumerate(case.findings) if i not in used]
    critical = [f for f in case.findings if f["sev"] == "critical"]
    pct = 100.0 * earned / possible if possible else 100.0
    done = case.phase == "DONE"
    if critical:
        outcome, reason = "FAIL", "Critical event: " + critical[0]["msg"]
    elif not done:
        outcome, reason = "IN PROGRESS", "The case is not finished."
    elif pct < PASS_SCORE:
        outcome, reason = "FAIL", f"Scored {_num(pct)}; the pass mark is {PASS_SCORE:.0f}."
    else:
        outcome, reason = "PASS", f"Scored {_num(pct)} with no critical event."
    missed.sort(key=lambda m: -m["lost"])
    return dict(score=_num(pct), earned=_num(earned), possible=_num(possible), not_observed=_num(hidden),
                pass_score=PASS_SCORE, outcome=outcome, outcome_reason=reason, sections=sections,
                missed=missed, other_findings=other)
