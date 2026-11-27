"""Instructor controls: change the patient and the circuit while a student runs the case.

The instructor never touches the student's controls or the score directly. They change what the
student has to deal with (resistance, contractility, oxygen demand, rhythm, bleeding, a failing
oxygenator, a kinked line, a falling ACT), set the pace, and speak as the surgeon. The model reacts
and the usual rules grade the student's response. A run the instructor changed is marked
instructor-led in its log and is kept off the leaderboard, like a run resumed from a save.

Educational use only. The ranges are teaching ranges, not clinical limits.
"""

# knob -> (label, low, high, neutral, unit, group, help)
KNOBS = dict(
    svr=("Vascular resistance", 0.4, 2.5, 1.0, "x", "patient", "Below 1 is a dilated patient (low pressure at full flow); above 1 is a clamped-down one."),
    contract=("Heart contractility", 0.2, 1.5, 1.0, "x", "patient", "How well the heart ejects once it is filled. Low makes weaning hard."),
    metabolic=("Oxygen demand", 0.5, 2.0, 1.0, "x", "patient", "Raises or lowers oxygen consumption, so venous saturation and CO2 move."),
    bleed=("Blood loss", 0.0, 500.0, 0.0, "mL/min", "patient", "Blood leaving the patient and not returned by the suckers."),
    oxy=("Oxygenator performance", 0.3, 1.0, 1.0, "x", "circuit", "Below 1 the oxygenator transfers less gas: PaO2 falls and CO2 rises."),
    art_kink=("Arterial line obstruction", 0.0, 6.0, 0.0, "x", "circuit", "A kink or a malpositioned cannula: line pressure climbs and flow drops at the same RPM."),
    ven_block=("Venous return obstruction", 0.0, 0.95, 0.0, "", "circuit", "An air lock or a lifted heart: drainage falls and the reservoir level drops."),
)
NEUTRAL = {k: v[3] for k, v in KNOBS.items()}
RHYTHMS = ("sinus", "brady", "vf", "asystole")
SPEEDS = (0, 1, 2, 5, 10, 30)


def describe():
    return dict(knobs=[dict(id=k, label=v[0], min=v[1], max=v[2], neutral=v[3], unit=v[4], group=v[5], help=v[6]) for k, v in KNOBS.items()],
                rhythms=list(RHYTHMS), speeds=list(SPEEDS),
                events=[dict(id="act_drop", label="ACT falls", help="Removes about 40% of the circulating heparin."),
                        dict(id="k_up", label="Potassium rises", help="Adds 1.5 mmol/L to the potassium."),
                        dict(id="vasoplegia", label="Sudden vasodilation", help="Sets vascular resistance to 0.55 of normal."),
                        dict(id="pump_surge", label="Pressure surge", help="Sets vascular resistance to 1.8 of normal.")])


def apply(case, op):
    """Carry out one instructor operation on a case. Returns a short plain-English record of what changed."""
    s, kind = case.sim, op.get("op")
    if kind == "knob":
        k = op.get("id")
        if k not in KNOBS:
            raise ValueError(f"unknown instructor control {k}")
        lo, hi = KNOBS[k][1], KNOBS[k][2]
        v = min(hi, max(lo, float(op.get("value"))))
        s.inst[k] = v
        if k == "oxy":
            s.oxy_eff = v
        note = f"{KNOBS[k][0]} set to {v:g}{' ' + KNOBS[k][4] if KNOBS[k][4] not in ('x', '') else ''}"
    elif kind == "rhythm":
        r = op.get("value")
        if r not in RHYTHMS:
            raise ValueError(f"unknown rhythm {r}")
        s.rhythm, s.vf_timer = r, 0.0
        note = f"Rhythm set to {r}"
    elif kind == "event":
        e = op.get("id")
        if e == "act_drop":
            s.hep *= 0.6; note = "ACT made to fall"
        elif e == "k_up":
            s.k = min(9.0, s.k + 1.5); note = "Potassium raised by 1.5"
        elif e == "vasoplegia":
            s.inst["svr"] = 0.55; note = "Sudden vasodilation"
        elif e == "pump_surge":
            s.inst["svr"] = 1.8; note = "Pressure surge"
        else:
            raise ValueError(f"unknown instructor event {e}")
    elif kind == "say":
        text = " ".join(str(op.get("text", "")).split())[:200]
        if not text:
            raise ValueError("nothing to say")
        case.say(text)
        note = "Surgeon line: " + text
    elif kind == "speed":
        case.speed = min(30.0, max(0.0, float(op.get("value", 1))))
        note = "Paused" if case.speed == 0 else f"Time factor {case.speed:g}x"
    elif kind == "neutral":
        s.inst.update(NEUTRAL)
        s.oxy_eff = 1.0
        note = "All instructor controls back to neutral"
    else:
        raise ValueError(f"unknown instructor operation {kind}")
    if kind != "speed":
        case.flags["instructor"] = True
    return note


def view(case):
    """What the instructor sees that the student does not: true values behind the monitors."""
    s = case.sim
    return dict(knobs=dict(s.inst), used=bool(case.flags.get("instructor")),
                true=dict(act=round(s.act_true), svr=round(s.svr * 80) if hasattr(s, "svr") else None, vo2=round(s.vo2),
                          do2=round(s.do2i * s.bsa), hep=round(s.hep), oxy=round(s.oxy_eff, 2), arrest=round(s.arrest, 2),
                          injury=round(s.injury, 3), blood_volume=round(s.vp), lactate=round(s.lactate, 1)))
