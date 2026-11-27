"""Expert autopilot: plays the routine case correctly through the same action
API a student uses. Used by the tests and by the demo's 'watch the expert' mode."""


class Autopilot:
    def __init__(self, case, mistake=None):
        self.case = case
        self.mistake = mistake      # None | "flow_up_early"
        self.next_t = 0.0
        self.mem = {}
        self.mult = 1.0

    def act(self, **a):
        self.case.action(a)

    def set(self, key, value):
        if self.case.sim.c[key] != value:
            self.act(type="set", key=key, value=value)

    def once(self, key):
        if key in self.mem:
            return False
        self.mem[key] = self.case.t
        return True

    def call(self, cid):
        if self.once("call_" + self.case.phase + cid):
            self.act(type="callout", id=cid)

    def flow_to(self, target):
        s = self.case.sim
        if target >= 0.9 * s.target_flow:
            target *= self.mult
        err = target - s.qa
        if target <= 0.05:
            self.set("rpm_set", 0.0)
        elif abs(err) > 0.05:
            floor = 1000.0 * ((s.pa + 8.0) / 45.0) ** 0.5      # never let pump head fall below patient pressure
            self.set("rpm_set", max(floor, min(4500.0, s.c["rpm_set"] + 220.0 * err)))

    def keep_gases(self):
        s = self.case.sim
        if s.on_bypass:
            sw = s.c["sweep"]
            if s.paco2 > 42.5:
                self.set("sweep", round(min(8.0, sw + 0.1), 2))
            elif s.paco2 < 37.5:
                self.set("sweep", round(max(0.5, sw - 0.1), 2))
            if s.pao2 > 350:
                self.set("fio2", round(max(0.3, s.c["fio2"] - 0.02), 2))
            elif s.pao2 < 180:
                self.set("fio2", round(min(1.0, s.c["fio2"] + 0.02), 2))
            t = self.case.t
            if s.pa > 80 and t - self.mem.get("iso", -99) > 15:
                self.mem["iso"] = t
                self.set("iso", round(min(3.0, s.c["iso"] + 0.25), 2))
            elif s.pa < 56 and s.c["iso"] > 0.5 and t - self.mem.get("iso", -99) > 15:
                self.mem["iso"] = t
                self.set("iso", round(max(0.5, s.c["iso"] - 0.25), 2))
            elif s.pa < 52 and t - self.mem.get("neo", -99) > 60:
                self.mem["neo"] = t
                self.act(type="phenylephrine", mcg=100)
            if s.do2i < 290 and s.qa > 0.8 * s.target_flow:
                self.mult = min(1.2, self.mult + 0.01)
            if s.do2i < 290 and s.hct_c < 0.24 and not s.p.no_transfusion and self.case.t - self.mem.get("prbc", -999) > 45:
                self.mem["prbc"] = self.case.t
                self.act(type="volume", ml=300, kind="prbc")
            if s.vr < 450 and self.case.t - self.mem.get("vol", -99) > 30:
                self.mem["vol"] = self.case.t
                self.act(type="volume", ml=250, kind="crystalloid")

    def step(self):
        """Call every sim tick; acts twice per simulated second."""
        case = self.case
        if case.t < self.next_t or case.phase == "DONE":
            return
        self.next_t = case.t + 0.5
        s, ph, tf = case.sim, case.phase, case.sim.target_flow
        getattr(self, "p_" + ph)(s, tf)
        if ph not in ("PRE", "WEAN", "POST"):
            self.keep_gases()
        elif ph == "WEAN" and s.vr < 500 and case.t - self.mem.get("vol", -99) > 15:
            self.mem["vol"] = case.t
            self.act(type="volume", ml=250, kind="crystalloid")

    def p_PRE(self, s, tf):
        if self.once("hep"):
            self.act(type="heparin", units=round(400 * s.p.weight / 1000) * 1000)
            self.act(type="measure", what="act")
        elif s.last_act is None and not s.pending and self.case.t - self.mem.get("hep2", 0) > 8:
            self.mem["hep2"] = self.case.t          # ACT came back low: give more and recheck
            self.act(type="heparin", units=round(300 * s.p.weight / 1000) * 1000)
            self.act(type="measure", what="act")
        if s.last_act:
            self.call("act_good")

    def p_INITIATE(self, s, tf):
        self.call("act_good")
        if s.c["art_clamp"]:
            need = max(1600.0, round(1000.0 * ((s.pa + 30.0) / 45.0) ** 0.5, -1))   # pump head must beat patient pressure
            self.set("rpm_set", need)
            if s.rpm > need - 60:
                self.set("art_clamp", False)
                self.set("sucker", True)
        else:
            self.set("ven_occl", 0.0)
            self.flow_to(tf)
            if s.qa >= 0.9 * tf:
                self.set("ventilator", False)
                self.call("on_bypass")

    def p_STABILIZE(self, s, tf):
        self.flow_to(tf)
        if self.once("abg1"):
            self.act(type="measure", what="abg")
        if 35 <= s.paco2 <= 45:
            self.call("gases_good")

    def p_COOL(self, s, tf):
        self.flow_to(tf)
        self.set("water_set", max(s.p.target_temp - 4.0, round(s.temp - 9.5, 1)))
        if s.temp <= s.p.target_temp + 0.5:
            self.call("at_temp")

    def hold_temp(self, s):
        self.set("water_set", s.p.target_temp)

    def p_CLAMP_ON(self, s, tf):
        self.hold_temp(s)
        if not s.xclamp:
            self.flow_to(0.25 * tf)
        else:
            self.flow_to(tf)
            if s.qa >= 0.9 * tf:
                self.call("full_flow")

    def p_ANTEGRADE(self, s, tf):
        self.flow_to(tf)
        self.call("full_flow")
        given = s.cp_total - self.case.flags["cp_mark"]
        if given < 1000 and not s.p.ai:
            self.set("root_vent", False)
            self.set("cp_route", "ante")
            self.set("cp_type", "highK")
            self.set("cp_flow", 250.0)
            self.set("cp_on", True)
        elif given < 1000:      # aortic insufficiency: go retrograde for most of the dose
            self.set("root_vent", True)
            self.set("cp_route", "retro")
            self.set("cp_type", "highK")
            self.set("cp_flow", 190.0)
            self.set("cp_on", True)
        else:
            self.set("cp_on", False)
            self.set("root_vent", True)
            self.call("cp_in")

    def p_RETROGRADE(self, s, tf):
        self.flow_to(tf)
        given = s.cp_total - self.case.flags["cp_mark"]
        if given < 250:
            self.set("cp_route", "retro")
            self.set("cp_flow", 190.0)
            self.set("cp_on", True)
        else:
            self.set("cp_on", False)
            if s.rhythm == "asystole":
                self.call("arrested")

    def p_OPERATE(self, s, tf):
        self.flow_to(tf)
        self.hold_temp(s)
        el = self.case.t - self.case.phase_t0
        if el > 120 and self.once("abg2"):
            self.act(type="measure", what="abg")
        if s.since_cp > 15 * 60 and "redose_mark" not in self.mem:
            self.mem["redose_mark"] = s.cp_total
            self.call("redose")
        if "redose_mark" in self.mem and not self.mem.get("redose_done"):
            if s.cp_total - self.mem["redose_mark"] < 300:
                self.set("cp_route", "retro")
                self.set("cp_type", "lowK")
                self.set("cp_flow", 190.0)
                self.set("cp_on", True)
            else:
                self.set("cp_on", False)
                self.mem["redose_done"] = True

    def p_HOTSHOT(self, s, tf):
        self.flow_to(tf)
        given = s.hot_shot_ml - self.case.flags["hs_mark"]
        if given < 500:
            self.set("cp_route", "retro")
            self.set("cp_type", "hot")
            self.set("cp_flow", 190.0)
            self.set("cp_on", True)
        else:
            self.set("cp_on", False)
            self.call("hotshot_in")
            if self.once("abg3"):
                self.act(type="measure", what="abg")
                self.act(type="measure", what="act")

    def p_REWARM(self, s, tf):
        self.flow_to(tf)
        self.set("water_set", min(38.0, round(s.temp + 9.5, 1)))
        if s.temp >= 35.9:
            self.call("warm")

    def p_CLAMP_OFF(self, s, tf):
        self.set("water_set", 37.0)
        if s.xclamp:
            if self.mistake == "flow_up_early" and "down_t" in self.case.flags and not self.mem.get("oops") \
                    and self.case.t - self.case.flags["down_t"] > 2:
                self.mem["oops"] = True
                self.set("rpm_set", 3000.0)       # the error from the video
                self.next_t = self.case.t + 4.0
                return
            self.flow_to(0.25 * tf)
        else:
            self.flow_to(tf)
            if s.qa >= 0.9 * tf:
                self.call("full_flow")

    def p_WEAN(self, s, tf):
        self.set("ventilator", True)
        self.set("root_vent", False)
        if s.p.ef < 0.7:
            self.set("epi", True)
        i = self.case.flags["wean_i"]
        if i < 3:
            target = self.case.WEAN_STEPS[i][0]
            # fill the heart first by restricting venous return, then come down
            want_cvp = 2.6 + 1.1 * (i + 1)
            if s.cvp < want_cvp:
                self.set("ven_occl", round(min(0.97, s.c["ven_occl"] + 0.05), 2))
            elif s.cvp > want_cvp + 1.5:
                self.set("ven_occl", round(max(0.0, s.c["ven_occl"] - 0.03), 2))
            if s.pulse >= 6 + 6 * i or s.qa > (target + 0.1) * tf:
                if s.pulse >= 4 + 6 * i:
                    self.flow_to(target * tf)
        else:
            self.set("ven_occl", 1.0)
            if s.qa > 1.0:
                self.flow_to(max(0.6, s.qa - 0.6))
            else:
                self.set("art_clamp", True)
                self.set("rpm_set", 0.0)
                self.call("off_bypass")

    def p_POST(self, s, tf):
        if not self.case.flags.get("prot_asked"):
            if s.pa < 68 and s.transfuse_left <= 0 and s.vr > 100 and self.case.t - self.mem.get("tx", -99) > 6:
                self.mem["tx"] = self.case.t
                self.act(type="transfuse", ml=100)
        else:
            self.set("sucker", False)
            if self.once("prot") is False and self.case.t - self.mem["prot"] > 2 and self.once("prot2"):
                self.act(type="protamine", mg=round(s.hep_total / 100.0))
                self.call("prot_in")
