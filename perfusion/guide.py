"""What the H info panel shows for each phase: why the step matters, where to do it, what goes wrong.

Teaching text only. It does not compute physiology and it does not affect the score; the steps themselves
come from Case.objectives(), the same list the HUD shows. Wording is a teaching approximation pending review
by a certified clinical perfusionist, not clinical guidance.
"""
from .scenario import CALLOUTS, EXPECTED, PHASES, PHASE_TITLES

CALLOUT_LABEL = dict(CALLOUTS)

# where: equipment panel ids (web/panels.js), in the order the steps use them
GUIDE = {
    "PRE": dict(
        why="The circuit will clot within minutes without anticoagulation, so heparin goes in and is proven "
            "to work (a long enough ACT) before any blood touches the pump.",
        where=["meds", "lab", "talk"],
        watch=["Last ACT"],
        pitfalls=["Going on bypass before the ACT is back over the target.",
                  "Dosing for the wrong weight: the dose is per kilogram."]),
    "INITIATE": dict(
        why="Going on bypass hands the circulation from the heart to the pump. The pump must push harder than "
            "the patient before the arterial line opens, or blood runs backwards out of the patient.",
        where=["timers", "pump", "venous", "vent", "talk"],
        watch=["Flow L/min", "MAP", "Reservoir mL"],
        pitfalls=["Unclamping the arterial line with the pump too slow (backflow).",
                  "Opening the venous line and letting the reservoir run dry.",
                  "Leaving the ventilator on at full flow."]),
    "STABILIZE": dict(
        why="Before anything else happens, check that the oxygenator works and the patient is getting enough "
            "oxygen: a blood gas, then sweep and FiO2, pressure and oxygen delivery.",
        where=["lab", "gas", "meds", "talk"],
        watch=["MAP", "O2 delivery", "SvO2 %", "Hct %"],
        pitfalls=["Skipping the first blood gas.",
                  "Chasing pressure with drugs when the flow is low."]),
    "COOL": dict(
        why="Cooling lowers how much oxygen the body needs, which buys a margin of safety while the heart is "
            "stopped. Cooling too fast (water much colder than blood) risks gas coming out of solution.",
        where=["hc", "talk"],
        watch=["Temp C", "MAP"],
        pitfalls=["A water-to-blood gap of more than 10 C."]),
    "CLAMP_ON": dict(
        why="The surgeon clamps the aorta. Flow comes down first so the clamp does not go onto a pressurised, "
            "full-flow aorta, then comes back up once the clamp is on.",
        where=["pump", "timers", "talk"],
        watch=["Flow L/min", "MAP"],
        pitfalls=["Staying at full flow while the clamp goes on.",
                  "Forgetting to return to full flow afterwards."]),
    "ANTEGRADE": dict(
        why="Cardioplegia stops the heart and protects it. The root vent is off during delivery so the solution "
            "goes down the coronaries instead of out of the vent.",
        where=["cp", "talk"],
        watch=["K+", "MAP"],
        pitfalls=["Root vent left on during delivery.",
                  "Delivery pressure outside the target window.",
                  "Forgetting to turn the root vent back on."]),
    "RETROGRADE": dict(
        why="Giving cardioplegia backwards through the coronary sinus reaches heart muscle that blocked arteries "
            "may starve. The coronary sinus is fragile, so its pressure stays low.",
        where=["cp", "timers", "talk"],
        watch=["K+"],
        pitfalls=["Coronary sinus pressure too high."]),
    "OPERATE": dict(
        why="The long middle of the case: hold flow, pressure and oxygen delivery steady, check gases, and "
            "re-dose cardioplegia on time so the heart stays protected.",
        where=["pump", "gas", "lab", "cp", "meds", "res"],
        watch=["MAP", "O2 delivery", "Hct %", "K+", "Clamp timer"],
        pitfalls=["Late cardioplegia re-dose.",
                  "Letting oxygen delivery drift low as the hematocrit falls."]),
    "HOTSHOT": dict(
        why="A warm dose of cardioplegia just before the clamp comes off washes out waste and helps the heart "
            "restart.",
        where=["cp", "talk"],
        watch=["Temp C"],
        pitfalls=["Giving the wrong solution.", "Not stopping at the target volume."]),
    "REWARM": dict(
        why="Rewarming brings the patient back to normal temperature. Too hot or too fast is harmful, "
            "especially to the brain.",
        where=["hc", "talk"],
        watch=["Temp C"],
        pitfalls=["Water more than 10 C above blood.", "Blood temperature over 37.5 C."]),
    "CLAMP_OFF": dict(
        why="The clamp comes off and blood reaches the heart again. Flow comes down for the moment of release, "
            "then goes back up.",
        where=["meds", "pump", "timers", "talk"],
        watch=["Flow L/min", "MAP"],
        pitfalls=["Bringing flow back up before the surgeon says the clamp is off "
                  "(the sequencing error from the lab video)."]),
    "WEAN": dict(
        why="Weaning hands the work back to the heart step by step: the lungs go back on, the heart is filled, "
            "and pump flow comes down as the heart shows it can take over.",
        where=["meds", "vent", "venous", "pump", "timers", "talk"],
        watch=["MAP", "CVP", "Flow L/min"],
        pitfalls=["Coming down from full flow with no rhythm or no pulse: that fails the run.", "Shocking a flat line.",
                  "Weaning with the ventilator still off.", "Stepping down before there is a pulse.",
                  "Coming off with the arterial line still open."]),
    "POST": dict(
        why="Off bypass: give back volume from the circuit as needed, then reverse the heparin. Suckers must be "
            "off first, or protamine-laced blood clots in the circuit.",
        where=["timers", "res", "meds", "talk"],
        watch=["MAP", "CVP", "Reservoir mL"],
        pitfalls=["Protamine with the suckers still on.", "Big volume boluses instead of 100 mL steps."]),
    "DONE": dict(why="The case is over. The debrief explains the score.", where=[], watch=[], pitfalls=[]),
}


def guide(case):
    """Everything the info panel needs, for every phase, for this patient."""
    phases = []
    for i, p in enumerate(PHASES):
        g = GUIDE[p]
        exp = EXPECTED.get(p)
        phases.append(dict(id=p, title=PHASE_TITLES[p], step=i + 1, steps_total=len(PHASES) - 1,
                           why=g["why"], objectives=case.objectives(p), where=list(g["where"]),
                           watch=list(g["watch"]), pitfalls=list(g["pitfalls"]),
                           callout=dict(id=exp, label=CALLOUT_LABEL[exp]) if exp else None))
    return dict(phases=phases,
                note="Teaching text. Numbers are approximations from the training model, not clinical reference values.")
