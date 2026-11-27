"""Post-run quiz. Standard library only.

Questions are picked by fixed rules from what happened in the run: first the items tagged with the
run's own findings (worst first), then general items chosen by a hash of the session id, so the
same run always gets the same quiz. Every answer restates a rule or constant this simulator itself
enforces. Teaching approximations, not clinical reference values.
"""
import hashlib

SEV = dict(critical=0, major=1, minor=2)
BANK = [
    dict(id="clamp_flow", tags=["flow_up_early", "clamp_full_flow"],
         q="The surgeon says \"flow down\" for the cross-clamp. When do you bring flow back up?",
         options=["As soon as flow has been down for five seconds", "When the surgeon says the clamp is on (or off)",
                  "When the pressure starts to fall", "When the reservoir starts to fill"], answer=1,
         why="Flow stays down until the surgeon calls the clamp. Coming up early puts full pressure on the aorta while it is being clamped or unclamped."),
    dict(id="unclamp_head", tags=["retrograde", "unclamp_no_rpm"],
         q="Before you open the arterial line on a centrifugal pump, what must be true?",
         options=["The venous line is clamped", "The pump is spinning fast enough that its pressure beats the patient's arterial pressure",
                  "The pump is stopped so the line fills slowly", "The oxygen fraction is at 100%"], answer=1,
         why="A centrifugal pump is non-occlusive. If its head is below the patient's pressure when the line opens, blood runs backward out of the patient."),
    dict(id="rpm_afterload", tags=["map_high", "line_p"],
         q="Pump speed is fixed at 3,000 RPM and the patient's vascular resistance rises. What happens to flow?",
         options=["Flow rises", "Flow stays the same because RPM is the same", "Flow falls", "Flow reverses"], answer=2,
         why="A centrifugal pump generates pressure, not a fixed volume. More resistance at the same RPM means less flow, which is why RPM and L/min are shown side by side."),
    dict(id="protamine_math", tags=["protamine_dose"],
         q="The patient received 30,000 units of heparin. At 1 mg of protamine per 100 units, what is the dose?",
         options=["30 mg", "150 mg", "300 mg", "3,000 mg"], answer=2,
         why="30,000 / 100 = 300 mg. Always say the units."),
    dict(id="protamine_when", tags=["protamine_on_bypass", "sucker_after_protamine", "protamine_early"],
         q="What must be true before protamine is given?",
         options=["The patient is off bypass, the pump is stopped and the pump suckers are off",
                  "The cross-clamp is on", "Flow is at half", "The ACT is above 480"], answer=0,
         why="Protamine reverses heparin. Any blood still moving through the pump or suckers will clot the circuit."),
    dict(id="csp_limit", tags=["csp_high"],
         q="During retrograde cardioplegia, coronary sinus pressure should stay at or below:",
         options=["20 mmHg", "40 mmHg", "80 mmHg", "150 mmHg"], answer=1,
         why="This simulator flags sinus pressure above 45 mmHg; the working limit it teaches is 40."),
    dict(id="redose", tags=["cp_interval", "activity_returning"],
         q="How long can the clamped heart go between cardioplegia doses in this simulator before it is flagged?",
         options=["5 minutes", "10 minutes", "20 minutes", "45 minutes"], answer=2,
         why="Cardioplegia washes out. Past 20 minutes without a dose the interval is flagged, and electrical activity returns soon after."),
    dict(id="vent_timing", tags=["vent_off_early", "wean_no_vent"],
         q="When is the ventilator off during the case?",
         options=["From induction until the chest is closed", "Only while the pump is carrying full flow; back on before weaning",
                  "Only during cardioplegia delivery", "It is never turned off"], answer=1,
         why="Off once the pump does all the work, back on before the heart starts ejecting again, or it pumps unoxygenated blood."),
    dict(id="gradient", tags=["gradient"],
         q="While cooling or warming, the heater-cooler water should stay within how many degrees of the blood?",
         options=["2 C", "10 C", "20 C", "It does not matter"], answer=1,
         why="A gradient over 10 C is flagged: gas comes out of solution when cold blood is warmed too fast."),
    dict(id="rewarm_max", tags=["hyperthermia"],
         q="During rewarming, arterial blood returning to the patient should never exceed:",
         options=["35.0 C", "36.0 C", "37.5 C", "40.0 C"], answer=2,
         why="Blood hotter than 37.5 C is flagged as hyperthermia, a brain-injury risk."),
    dict(id="do2", tags=["do2_low", "unstable_bypass"],
         q="Indexed oxygen delivery on bypass is flagged when it stays below about:",
         options=["100 mL/min/m2", "270 mL/min/m2", "500 mL/min/m2", "800 mL/min/m2"], answer=1,
         why="This simulator targets 280 and flags sustained delivery under 270, the threshold linked to kidney injury."),
    dict(id="empty_res", tags=["res_low", "air_embolism"],
         q="What is the immediate danger if the venous reservoir runs empty with the pump running?",
         options=["The oxygenator overheats", "The pump sends air to the patient", "The ACT falls", "Potassium rises"], answer=1,
         why="An empty reservoir means the pump draws air and pushes it down the arterial line."),
    dict(id="act_min", tags=["act_marginal", "circuit_clotting"],
         q="What ACT does this simulator want before going on bypass?",
         options=["Over 120 seconds", "Over 250 seconds", "Over 480 seconds", "Over 900 seconds"], answer=2,
         why="480 seconds is the target; under 400 the surgeon will not proceed, and under 300 on bypass the circuit clots."),
    dict(id="map_range", tags=["map_low"],
         q="What mean arterial pressure range does this simulator treat as in range on bypass?",
         options=["20 to 40 mmHg", "50 to 80 mmHg", "90 to 120 mmHg", "Any value if flow is on target"], answer=1,
         why="50 to 80 mmHg is scored as in range; under 40 or over 95 for 30 seconds is flagged."),
    dict(id="sweep", tags=["co2_range"],
         q="Arterial CO2 is 52 mmHg on bypass. Which control fixes it?",
         options=["Raise the oxygen fraction", "Raise the sweep gas flow", "Lower the pump speed", "Warm the water"], answer=1,
         why="Sweep gas flow removes CO2. Oxygen fraction sets PaO2."),
    dict(id="wean_pulse", tags=["wean_before_ejecting", "failed_wean", "unstable_off_bypass"],
         q="While weaning, what do you look for before stepping flow down further?",
         options=["A flat arterial trace", "A pulse on the arterial trace: the heart is ejecting",
                  "A falling reservoir level", "A rising water temperature"], answer=1,
         why="You partly clamp the venous line to fill the heart, then wait for it to eject before reducing pump support."),
    dict(id="root_vent", tags=["vent_on_antegrade", "vent_stealing", "lv_distension", "vent_off_after_cp"],
         q="How should the aortic root vent be set around an antegrade cardioplegia dose?",
         options=["On during the dose, off afterwards", "Off during the dose, back on afterwards",
                  "On the whole time", "Off the whole time"], answer=1,
         why="On during delivery it steals the dose; off afterwards the ventricle can distend."),
    dict(id="no_clamp_cp", tags=["cp_no_clamp", "hyperkalemia"],
         q="What happens if high-potassium cardioplegia runs with no cross-clamp on?",
         options=["The heart arrests faster", "Nothing: it only reaches the heart", "The potassium goes to the whole body and the heart does not arrest",
                  "The reservoir fills"], answer=2,
         why="Without the clamp the dose is washed into the systemic circulation."),
    dict(id="heparin_math", tags=[],
         q="A 75 kg patient needs heparin at 400 units per kg. What is the dose?",
         options=["3,000 units", "7,500 units", "30,000 units", "300,000 units"], answer=2,
         why="75 x 400 = 30,000 units."),
    dict(id="hot_shot", tags=["hotshot_wrong", "vf"],
         q="What is the hot shot?",
         options=["A bolus of heparin before bypass", "A warm, low-potassium dose given just before the clamp comes off",
                  "A cold high-potassium induction dose", "A dose of protamine"], answer=1,
         why="It washes out potassium and warms the heart so it restarts in a normal rhythm."),
    dict(id="refusal", tags=["transfusion_refused"],
         q="A patient has refused blood products and oxygen delivery is low. Which option is still open?",
         options=["Give one unit of red cells", "Raise pump flow and limit further dilution", "Stop the pump", "Give protamine"], answer=1,
         why="The refusal stands. Delivery is protected with flow and by avoiding more crystalloid."),
    dict(id="drainage", tags=[],
         q="How does blood get from the patient to the venous reservoir on this circuit?",
         options=["The arterial pump sucks it", "Gravity siphon, controlled by the venous clamp", "The heart pumps it", "Sweep gas pressure"], answer=1,
         why="Venous drainage is a siphon. Partly closing the clamp keeps blood in the patient."),
]
BY_ID = {b["id"]: b for b in BANK}


def pick(doc, n=4):
    """Item ids for this session's quiz: fixed for a given log."""
    findings = sorted((doc.get("final") or {}).get("findings") or [], key=lambda f: (SEV.get(f["sev"], 9), f["t"]))
    chosen = []
    for f in findings:
        for b in BANK:
            if f["code"] in b["tags"] and b["id"] not in chosen:
                chosen.append(b["id"])
                break
        if len(chosen) >= n:
            break
    rest = sorted((b["id"] for b in BANK if b["id"] not in chosen),
                  key=lambda i: hashlib.sha256((doc["id"] + ":" + i).encode()).hexdigest())
    return (chosen + rest)[:n]


def questions(doc, n=4):
    """Questions without the answers, for the client."""
    return [dict(id=i, q=BY_ID[i]["q"], options=BY_ID[i]["options"]) for i in pick(doc, n)]


def grade(doc, answers, n=4):
    ids = pick(doc, n)
    items = []
    for k, i in enumerate(ids):
        b = BY_ID[i]
        a = answers[k] if k < len(answers) and isinstance(answers[k], int) else None
        items.append(dict(id=i, q=b["q"], your=a, answer=b["answer"], correct=a == b["answer"],
                          answer_text=b["options"][b["answer"]], why=b["why"]))
    return dict(score=sum(1 for x in items if x["correct"]), total=len(items), items=items)
