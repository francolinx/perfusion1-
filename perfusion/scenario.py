"""Routine bypass case: scripted surgeon, phase logic and deterministic grading.

The case follows the run in the lab video: heparin and ACT, go on bypass,
checks, cool, cross-clamp, antegrade and retrograde cardioplegia, maintenance,
hot shot, rewarm, clamp off, wean, come off, give volume, protamine.
Grading is rule-based from the event log so the same run always scores the same.
"""
from .model import Sim, Persona
from . import rubric

PHASES = ["PRE", "INITIATE", "STABILIZE", "COOL", "CLAMP_ON", "ANTEGRADE", "RETROGRADE",
          "OPERATE", "HOTSHOT", "REWARM", "CLAMP_OFF", "WEAN", "POST", "DONE"]

PHASE_TITLES = dict(
    PRE="Before bypass", INITIATE="Go on bypass", STABILIZE="Bypass checks", COOL="Cool",
    CLAMP_ON="Cross-clamp on", ANTEGRADE="Antegrade cardioplegia", RETROGRADE="Retrograde cardioplegia",
    OPERATE="Surgeon operating", HOTSHOT="Hot shot", REWARM="Rewarm", CLAMP_OFF="Cross-clamp off",
    WEAN="Wean", POST="Off bypass", DONE="Debrief")

CALLOUTS = [
    ("act_good", "ACT is good, ready for bypass"), ("on_bypass", "On bypass, full flow"),
    ("gases_good", "Bypass and gases look good"), ("at_temp", "At temperature"),
    ("flow_down", "Flow is down"), ("full_flow", "Back at full flow"),
    ("cp_in", "Cardioplegia is in"), ("arrested", "Heart is arrested"),
    ("redose", "Re-dosing cardioplegia"), ("hotshot_in", "Hot shot is in"),
    ("warm", "Patient is warm"), ("wean_step", "At the flow you asked for"),
    ("off_bypass", "Off bypass"), ("volume_in", "Volume is in"), ("prot_in", "Protamine is in"),
]
EXPECTED = dict(PRE="act_good", INITIATE="on_bypass", STABILIZE="gases_good", COOL="at_temp",
                CLAMP_ON="full_flow", ANTEGRADE="cp_in", RETROGRADE="arrested", OPERATE="redose",
                HOTSHOT="hotshot_in", REWARM="warm", CLAMP_OFF="full_flow", WEAN="off_bypass",
                POST="prot_in")
PENALTY = dict(minor=2, major=6, critical=20)
SMALL_TALK = ["How are the kids?", "Did you catch anything on that fishing trip?",
              "Somebody brought a banana on the boat. Bad luck.", "Going on vacation anytime soon?"]


class Case:
    def __init__(self, persona: Persona, operate_minutes=22.0):
        self.sim = Sim(persona)
        self.persona = persona
        self.phase = "PRE"
        self.prev_phase = None
        self.phase_t0 = 0.0
        self.lines = []           # surgeon speech log
        self.findings = []        # graded events
        self.credits = set()      # objectives achieved
        self.callouts_done = set()
        self.callout_log = []
        self.flags = {}
        self.timers = {}
        self.operate_s = operate_minutes * 60.0
        self.in_range = dict(map=0.0, do2=0.0, total=0.0)
        self._seen_events = 0
        self.speed = 1.0
        self.autopilot = False
        self.say(f"Patient is {persona.weight:.0f} kilos. Give heparin, check your ACT, and tell me when you are ready.")

    # ---- utilities ---------------------------------------------------------
    @property
    def t(self):
        return self.sim.t

    def say(self, text):
        self.lines.append(dict(t=round(self.sim.t, 1), text=text))

    def find(self, code, sev, msg, once=True, cooldown=120.0, **extra):
        key = "f_" + code
        last = self.timers.get(key)
        if last is not None and (once or self.t - last < cooldown):
            return
        n = self.timers.get("n_" + code, 0)
        if n >= 3:                      # a repeating problem is penalised at most three times
            return
        self.timers["n_" + code] = n + 1
        self.timers[key] = self.t
        self.findings.append(dict(code=code, sev=sev, msg=msg, t=round(self.t, 1), phase=self.phase, **extra))

    def held(self, name, cond, seconds):
        """True once cond has been continuously true for `seconds` of sim time."""
        if not cond:
            self.timers.pop(name, None)
            return False
        t0 = self.timers.setdefault(name, self.t)
        return self.t - t0 >= seconds

    def goto(self, phase):
        self.prev_phase = self.phase
        self.phase = phase
        self.phase_t0 = self.t
        for k in [k for k in self.timers if k.startswith("h_")]:
            del self.timers[k]

    @property
    def frac(self):
        return max(self.sim.qa, 0.0) / self.sim.target_flow

    # ---- student actions ----------------------------------------------------
    def action(self, a):
        s, kind = self.sim, a.get("type")
        if kind == "set":
            key, val = a["key"], a["value"]
            if key == "ventilator" and not val and self.frac < 0.5 and self.phase in ("PRE", "INITIATE"):
                self.find("vent_off_early", "major", "Ventilator turned off before the pump was supporting the patient.")
            if key == "art_clamp" and not val and s.cannulated and s.rpm < 1000 and s.pa > 30:
                self.find("unclamp_no_rpm", "major", "Arterial line unclamped before the pump was spinning: backflow.")
            s.set(key, val)
        elif kind == "heparin":
            s.give_heparin(a.get("units", 0))
        elif kind == "protamine":
            # the model raises its own critical event if the pump or suckers are running, so only
            # add a scenario finding when it would not (one error, one penalty)
            will_clot = s.qa > 0.2 or s.c["sucker"] or s.rpm > 300
            if self.phase != "POST" and not will_clot:
                self.find("protamine_early", "critical", "Protamine given before the patient was off bypass.")
            s.give_protamine(a.get("mg", 0))
        elif kind == "phenylephrine":
            s.give_phenylephrine(a.get("mcg", 100))
        elif kind == "volume":
            if a.get("kind") == "prbc" and self.persona.no_transfusion:
                self.find("transfusion_refused", "critical", "Red cells given to a patient who refused blood products.")
            s.add_volume(a.get("ml", 250), a.get("kind", "crystalloid"))
        elif kind == "transfuse":
            s.transfuse(a.get("ml", 100))
            self.flags["tx_given"] = self.flags.get("tx_given", 0) + a.get("ml", 100)
        elif kind == "measure":
            s.measure(a.get("what", "abg"))
        elif kind == "callout":
            cid = a.get("id")
            self.callout_log.append(dict(t=round(self.t, 1), id=cid, phase=self.phase))
            if EXPECTED.get(self.phase) == cid:
                self.callouts_done.add(self.phase)
            elif EXPECTED.get(self.prev_phase) == cid and self.t - self.phase_t0 < 20:
                self.callouts_done.add(self.prev_phase)
        elif kind == "speed":
            self.speed = min(30.0, max(0.0, float(a.get("x", 1))))
        elif kind == "autopilot":
            self.autopilot = bool(a.get("on"))
        else:
            raise ValueError(f"unknown action {kind}")

    # ---- main tick ----------------------------------------------------------
    def tick(self):
        """Advance one model step and run phase logic."""
        if self.phase == "DONE":
            return
        s = self.sim
        s.step()
        for ev in s.events[self._seen_events:]:
            self.findings.append(dict(code=ev["code"], sev=ev["sev"], msg=ev["msg"], t=ev["t"], phase=self.phase))
        self._seen_events = len(s.events)
        self._global_rules()
        getattr(self, "ph_" + self.phase)()

    def _global_rules(self):
        s = self.sim
        if not s.on_bypass:
            return
        dt = s.DT
        self.in_range["total"] += dt
        if 50 <= s.pa <= 80:
            self.in_range["map"] += dt
        if s.do2i >= 280:
            self.in_range["do2"] += dt
        if self.phase in ("INITIATE", "CLAMP_ON", "CLAMP_OFF", "WEAN"):
            return   # transitional phases: flow is deliberately off target
        if self.held("g_res", s.vr < 200, 3):
            self.find("res_low", "major", "Reservoir fell below 200 mL: one breath away from pumping air.", once=False)
        if self.held("g_map_lo", s.pa < 40, 30):
            self.find("map_low", "major", "Mean arterial pressure under 40 for more than 30 seconds.", once=False)
        if self.held("g_map_hi", s.pa > 95, 30):
            self.find("map_high", "minor", "Mean arterial pressure over 95 for more than 30 seconds.", once=False)
        if self.held("g_do2", s.do2i < 270, 90):
            self.find("do2_low", "major", "Oxygen delivery stayed under 270 mL/min/m2: kidney injury risk.", once=False, cooldown=300)
        if self.held("g_line", s.line_p > 350, 3):
            self.find("line_p", "major", "Arterial line pressure over 350 mmHg.", once=False)
        if self.held("g_grad", abs(s.t_water - s.temp) > 10.5, 20):
            self.find("gradient", "minor", "Water to blood temperature gradient over 10 C.", once=False, cooldown=600)
        if self.held("g_k", s.k > 6.0, 30):
            self.find("hyperkalemia", "major", "Potassium over 6.0 mmol/L.")
        if self.held("g_co2", s.paco2 > 50 or s.paco2 < 30, 120):
            self.find("co2_range", "minor", "Arterial CO2 out of range for two minutes: adjust sweep gas.", once=False, cooldown=600)
        if self.held("g_csp", s.csp > 45, 3):
            self.find("csp_high", "major", "Coronary sinus pressure over 45 mmHg during retrograde delivery.")
        if self.held("g_cpp", s.cp_pressure > 320, 3):
            self.find("cp_pressure", "minor", "Cardioplegia line pressure over 320 mmHg.")

    # ---- phases -------------------------------------------------------------
    def ph_PRE(self):
        s = self.sim
        dose = s.hep_total / self.persona.weight
        if dose >= 280:
            self.credits.add("heparin")
        act = s.last_act[1] if s.last_act else 0
        if s.last_act and s.hep_total > 0 and not self.flags.get("act_checked"):
            self.flags["act_checked"] = True
            if act < 400:
                self.say(f"ACT is only {act}. That will not do. Fix it before we go on.")
                self.flags["act_checked"] = False
                s.last_act = None
        if self.flags.get("act_checked"):
            self.credits.add("act")
            if act < 480:
                self.find("act_marginal", "minor", f"Went on bypass with ACT {act}; most centres want 480.")
            s.cannulated = True
            self.say("Cannulas are in. Go on bypass when you are ready.")
            self.goto("INITIATE")

    def ph_INITIATE(self):
        s = self.sim
        if self.frac >= 0.5 and "sweep_at_init" not in self.flags:
            self.flags["sweep_at_init"] = s.c["sweep"] > 0      # rubric C2a: gas on as flow comes up
        if self.frac >= 0.9:
            self.credits.add("full_flow")
        if not s.c["ventilator"] and self.frac >= 0.8:
            self.credits.add("vent_off")
        if self.held("h_full", self.frac >= 0.9 and not s.c["ventilator"], 5):
            self.say("How does your bypass look? Check your gases.")
            self.flags["abg_t"] = self.t
            self.goto("STABILIZE")
        elif self.held("h_vent", self.frac >= 0.9 and s.c["ventilator"], 25):
            if not self.flags.get("vent_nag"):
                self.flags["vent_nag"] = True
                self.say("There is one thing you have not done.")

    def ph_STABILIZE(self):
        s = self.sim
        if s.last_abg and s.last_abg[0] > self.flags["abg_t"]:
            self.credits.add("abg")
            self.flags.setdefault("abg1", dict(pao2=s.last_abg[1]["pao2"], paco2=s.last_abg[1]["paco2"]))
        # what the rubric grades when the surgeon moves on: gases, pressure and oxygen delivery as they stand
        self.flags["gas_end"] = dict(pao2=round(s.pao2), paco2=round(s.paco2), map=round(s.pa), do2i=round(s.do2i))
        ok = 35 <= s.paco2 <= 45 and 150 <= s.pao2 <= 400 and 50 <= s.pa <= 80 and s.do2i >= 280
        if self.held("h_ok", ok and "abg" in self.credits, 5):
            self.credits.add("gases_in_range")
            self.say(f"Good. Cool to {self.persona.target_temp:.0f} degrees.")
            self.goto("COOL")
        elif self.t - self.phase_t0 > 180 and not self.flags.get("stab_nag"):
            self.flags["stab_nag"] = True
            self.say("I need gases in range, pressure between 50 and 80, and good oxygen delivery before we cool.")
        elif self.t - self.phase_t0 > 420:
            self.find("unstable_bypass", "major", "Bypass was never stabilised: the surgeon went ahead without gases, pressure and oxygen delivery in range.")
            self.say(f"We cannot wait any longer. Cool to {self.persona.target_temp:.0f} degrees.")
            self.goto("COOL")

    def ph_COOL(self):
        s = self.sim
        if s.temp <= self.persona.target_temp + 0.3:
            self.credits.add("cooled")
            self.say("Ready for cross-clamp. Flow down.")
            self.goto("CLAMP_ON")

    def _clamp_dance(self, apply):
        """Shared flow-down / clamp / flow-up logic. Returns True when complete."""
        s = self.sim
        done_flag = "clamp_moved"
        if not self.flags.get(done_flag):
            if self.frac <= 0.35:
                self.flags.setdefault("down_t", self.t)
                if self.t - self.flags["down_t"] >= 6.0:
                    s.xclamp = apply
                    self.flags[done_flag] = True
                    self.credits.add("flow_down_on" if apply else "flow_down_off")
                    self.say("Clamp is on. Come back up." if apply else "Clamp is off. Flow back up.")
            else:
                if "down_t" in self.flags and self.frac > 0.6:
                    self.find("flow_up_early", "major",
                              "Flow was brought back up before the surgeon called the clamp "
                              + ("on." if apply else "off. This is the sequencing error from the lab video."))
                    self.flags.pop("down_t")
                    self.say("Hold on. I am not done. Flow back down.")
                if self.t - self.phase_t0 > 45 and "down_t" not in self.flags:
                    s.xclamp = apply
                    self.flags[done_flag] = True
                    self.find("clamp_full_flow", "major",
                              "Cross-clamp " + ("applied" if apply else "removed") + " at full flow: aortic injury risk.")
                    self.say("I could not wait. Clamp is " + ("on." if apply else "off."))
            return False
        if self.frac >= 0.9:
            self.flags.pop(done_flag)
            self.flags.pop("down_t", None)
            return True
        return False

    def ph_CLAMP_ON(self):
        if self._clamp_dance(True):
            self.say("Give me one liter of high-potassium antegrade.")
            self.flags["cp_mark"] = self.sim.cp_total
            self.goto("ANTEGRADE")

    def ph_ANTEGRADE(self):
        s = self.sim
        given = s.cp_total - self.flags["cp_mark"]
        if s.c["cp_on"]:
            if s.c["cp_route"] != "ante" and not self.persona.ai:
                self.find("wrong_route", "minor", "Surgeon asked for antegrade but retrograde was delivered.")
            if s.c["cp_type"] != "highK":
                self.find("wrong_solution", "major", "Induction dose was not the high-potassium solution.")
            if s.c["root_vent"] and s.c["cp_route"] == "ante":
                self.find("vent_on_antegrade", "minor", "Root vent left on during antegrade delivery.")
        if given >= 950 and not s.c["cp_on"]:
            self.credits.add("antegrade")
            if s.c["root_vent"]:
                self.credits.add("vent_back_on")
            if given > 1300:
                self.find("cp_overdose", "minor", f"Gave {given:.0f} mL when one liter was requested.")
            self.say("Give 250 retrograde. Watch that sinus pressure.")
            self.flags["cp_mark"] = s.cp_total
            self.goto("RETROGRADE")

    def ph_RETROGRADE(self):
        s = self.sim
        given = s.cp_total - self.flags["cp_mark"]
        if s.c["cp_on"] and s.c["cp_route"] != "retro":
            self.find("wrong_route_retro", "minor", "Surgeon asked for retrograde but antegrade was delivered.")
        if given >= 240 and not s.c["cp_on"]:
            self.credits.add("retrograde")
            if s.rhythm == "asystole":
                self.credits.add("arrest")
            if not s.c["root_vent"]:
                self.find("vent_off_after_cp", "minor", "Root vent not turned back on after cardioplegia.")
            self.say("Good arrest. I am working. Keep me posted.")
            self.flags["talk_i"] = 0
            self.flags["op_abg_t"] = self.t
            self.goto("OPERATE")

    def ph_OPERATE(self):
        s = self.sim
        el = self.t - self.phase_t0
        i = self.flags["talk_i"]
        if i < len(SMALL_TALK) and el > 150 + i * 240:
            self.say(SMALL_TALK[i])
            self.flags["talk_i"] = i + 1
        if s.last_abg and s.last_abg[0] > self.flags["op_abg_t"]:
            self.credits.add("abg_clamped")
        if s.c["cp_on"] and el > 300:
            self.flags["redosed"] = True
        if self.flags.get("redosed") and not s.c["cp_on"]:
            self.credits.add("redose")
        if self.held("h_cp_late", s.since_cp > 1200, 1):
            self.find("cp_interval", "major", "More than 20 minutes since the last cardioplegia dose.")
            if not self.flags.get("cp_nag"):
                self.flags["cp_nag"] = True
                self.say("This heart is starting to move. How long since the last dose?")
        if el >= self.operate_s and not s.c["cp_on"]:
            self.say("I am about done up here. Give the hot shot.")
            self.flags["hs_mark"] = s.hot_shot_ml
            self.goto("HOTSHOT")

    def ph_HOTSHOT(self):
        s = self.sim
        given = s.hot_shot_ml - self.flags["hs_mark"]
        if s.c["cp_on"] and s.c["cp_type"] != "hot":
            self.find("hotshot_wrong", "major", "Hot shot requested but a cold solution was delivered.")
        if given >= 450 and not s.c["cp_on"]:
            self.credits.add("hotshot")
            self.say("Start rewarming.")
            self.goto("REWARM")

    def ph_REWARM(self):
        s = self.sim
        if s.t_art > 37.6:
            self.find("hyperthermia", "major", "Arterial blood temperature over 37.5 C during rewarming.")
        if s.temp >= 36.0:
            self.credits.add("rewarmed")
            self.say("Ready for the clamp to come off. Flow down.")
            self.goto("CLAMP_OFF")

    def ph_CLAMP_OFF(self):
        s = self.sim
        if s.rhythm == "vf" and s.vf_timer > 15:
            s.defibrillate()
            self.say("Fibrillating. Shocking. Sinus rhythm.")
        if not self.flags.get("after_unclamp") and self._clamp_dance(False):
            self.flags["after_unclamp"] = True
        if self.flags.get("after_unclamp") and s.rhythm == "sinus" and not s.xclamp:
            self.flags["wean_i"] = 0
            self.say("Let's wean. Come down to three-quarter flow and give the heart some volume.")
            self.goto("WEAN")

    WEAN_STEPS = [(0.75, "Half flow."), (0.5, "Quarter flow."), (0.25, "Looking stable. Come off bypass.")]

    def ph_WEAN(self):
        s = self.sim
        i = self.flags["wean_i"]
        if s.c["ventilator"]:
            self.credits.add("vent_on")
        elif self.frac < 0.7:
            self.find("wean_no_vent", "critical", "Weaned from bypass with the ventilator still off.")
        if s.temp < 35.5:
            self.find("wean_cold", "minor", "Weaning below 35.5 C.")
        if i < 3:
            target, line = self.WEAN_STEPS[i]
            near = abs(self.frac - target) <= 0.12
            if self.frac < target - 0.2 and s.pulse < 8:
                self.find("wean_before_ejecting", "major",
                          "Flow reduced before the heart was ejecting: wait for the pulse on the arterial trace.", once=False, step=i)
            if self.held("h_w%d" % i, near and s.pulse >= 6 + 6 * i and s.pa >= 50, 10):
                self.credits.add("wean_%d" % i)
                self.flags["wean_i"] = i + 1
                self.say(line)
        else:
            if self.held("h_off", s.qa < 0.1 and s.qa > -0.1 and s.c["art_clamp"] and s.c["ven_occl"] >= 0.98, 3):
                self.credits.add("off_bypass")
                self.say("We are off. Give me 100 at a time until the pressure is where I want it.")
                self.goto("POST")

    def ph_POST(self):
        s = self.sim
        el = self.t - self.phase_t0
        if not self.flags.get("prot_asked"):
            if self.held("h_stable", s.pa >= 65 and s.rhythm == "sinus", 8) and el > 15:
                self.flags["prot_asked"] = True
                self.credits.add("stable_off")
                self.say("Hemodynamics look good. Suckers off, give protamine.")
            elif self.held("h_hypo", s.pa < 60, 12):
                self.timers.pop("h_hypo", None)
                self.say("Patient is looking hypotensive. Give more volume." if s.vr > 100 else "Pressure is low and you are out of volume.")
            if el > 480:
                self.flags["prot_asked"] = True
                self.find("unstable_off_bypass", "major", "Patient was still unstable eight minutes after coming off bypass.")
                self.say("We are not getting anywhere. Suckers off, give protamine, and we will sort the pressure out.")
            if self.held("h_fail", s.pa < 45, 90):
                self.find("failed_wean", "major", "Patient did not tolerate coming off bypass: consider inotrope before weaning.")
                self.timers.pop("h_fail", None)
        else:
            if s.prot_total > 0:
                ratio = s.prot_total / max(s.hep_total / 100.0, 1.0)
                if not self.flags.get("prot_graded") and self.held("h_prot", True, 4):
                    self.flags["prot_graded"] = True
                    if 0.8 <= ratio <= 1.3:
                        self.credits.add("protamine_dose")
                    else:
                        self.find("protamine_dose", "major",
                                  f"Protamine dose {s.prot_total:.0f} mg for {s.hep_total:.0f} units of heparin "
                                  f"(expected about {s.hep_total/100:.0f} mg).")
                    if not s.c["sucker"]:
                        self.credits.add("suckers_off")
                    self.say("Thank you. Good case." if self.score()["score"] >= 80 else "We need to talk about that one.")
                    self.goto("DONE")

    # ---- reporting ----------------------------------------------------------
    CHECKLIST = [
        ("heparin", "Heparin dosed by weight"), ("act", "ACT confirmed before bypass"),
        ("full_flow", "Reached full flow"), ("vent_off", "Ventilator off once on full flow"),
        ("abg", "Blood gas checked on bypass"), ("gases_in_range", "Gases, pressure and oxygen delivery in range"),
        ("cooled", "Cooled to target"), ("flow_down_on", "Flow down for clamp on"),
        ("antegrade", "Antegrade induction dose delivered"), ("retrograde", "Retrograde dose delivered"),
        ("arrest", "Arrest achieved"), ("abg_clamped", "Blood gas checked during clamp time"),
        ("redose", "Maintenance dose given"), ("hotshot", "Hot shot delivered"),
        ("rewarmed", "Rewarmed"), ("flow_down_off", "Flow down for clamp off"),
        ("vent_on", "Ventilator on before weaning"), ("wean_0", "Three-quarter flow"),
        ("wean_1", "Half flow"), ("wean_2", "Quarter flow"), ("off_bypass", "Came off with lines clamped"),
        ("stable_off", "Stable off bypass"), ("suckers_off", "Suckers off before protamine"),
        ("protamine_dose", "Protamine dose correct"),
    ]

    def score(self, detail=True):
        rb = rubric.evaluate(self)
        idx = PHASES.index(self.phase)
        due = [k for k in EXPECTED if PHASES.index(k) < idx]
        tot = self.in_range["total"] or 1.0
        return dict(
            score=rb["score"], outcome=rb["outcome"], rubric=rb if detail else None,
            critical=sum(1 for f in self.findings if f["sev"] == "critical"),
            checklist=[dict(id=k, label=l, done=k in self.credits) for k, l in self.CHECKLIST],
            callouts=dict(made=len([k for k in due if k in self.callouts_done]), due=len(due)),
            map_in_range=round(100 * self.in_range["map"] / tot),
            do2_in_range=round(100 * self.in_range["do2"] / tot),
            findings=self.findings,
        )

    def objectives(self, phase=None):
        s, p = self.sim, phase or self.phase
        tf = s.target_flow
        o = {
            "PRE": [f"Give heparin: 300 to 400 units per kg ({300*self.persona.weight:.0f} to {400*self.persona.weight:.0f} units)",
                    "Run an ACT at the analyzer and confirm it is over 480 seconds"],
            "INITIATE": ["Spin the pump until its pressure beats the patient's (about 1500 RPM, more if pressure is high), then unclamp the arterial line",
                         "Open the venous clamp", f"Bring flow up to about {tf:.1f} L/min",
                         "Turn the ventilator off once you are at full flow"],
            "STABILIZE": ["Run a blood gas", "Sweep gas: CO2 35 to 45. Oxygen: PaO2 150 to 400",
                          "Pressure 50 to 80 (vaporizer down or phenylephrine to raise it, vaporizer up to lower it)", "Oxygen delivery over 280: more flow or red cells"],
            "COOL": [f"Set the heater-cooler to cool the patient to {self.persona.target_temp:.0f} C",
                     "Keep the water within 10 C of the blood"],
            "CLAMP_ON": ["Drop flow to under a third and hold it there", "Wait for 'clamp is on', then return to full flow"],
            "ANTEGRADE": ["Root vent off", "Deliver 1000 mL high-K antegrade at 150 to 300 mmHg", "Stop, then root vent back on"],
            "RETROGRADE": ["Switch route to retrograde", "Deliver 250 mL, coronary sinus pressure 40 or less"],
            "OPERATE": ["Hold flow, pressure and oxygen delivery in range", "Run a blood gas",
                        "Re-dose cardioplegia (low-K, about 300 mL) before 20 minutes",
                        "Speed up time with the clock control if you like"],
            "HOTSHOT": ["Select the hot shot solution", "Deliver 500 mL, then stop"],
            "REWARM": ["Warm the water, at most 10 C above blood and blood never over 37.5 C", "Reach 36 C"],
            "CLAMP_OFF": ["Drop flow to under a third", "Stay down until you hear 'clamp is off'", "Then back to full flow"],
            "WEAN": ["Ventilator back on", "Partly clamp the venous line to fill the heart",
                     "Step flow down as the surgeon asks, once you see a pulse",
                     "To come off: venous clamp shut, flow to zero, arterial line clamped"],
            "POST": ["Transfuse 100 mL at a time from the reservoir", "Suckers off, then protamine: 1 mg per 100 units of heparin"],
            "DONE": ["Case complete"],
        }
        return o[p]

    def snapshot(self):
        d = self.sim.snapshot()
        d.update(phase=self.phase, phase_title=PHASE_TITLES[self.phase], phase_index=PHASES.index(self.phase),
                 phase_elapsed=round(self.t - self.phase_t0), operate_s=self.operate_s,
                 lines=self.lines[-6:], n_lines=len(self.lines), objectives=self.objectives(),
                 expected_callout=EXPECTED.get(self.phase), callout_made=self.phase in self.callouts_done,
                 speed=self.speed, autopilot=self.autopilot,
                 persona=dict(id=self.persona.id, name=self.persona.name, weight=self.persona.weight,
                              height=self.persona.height, age=self.persona.age, sex=self.persona.sex),
                 score=self.score(detail=self.phase == "DONE"))     # the full rubric report only once the case is over
        return d
