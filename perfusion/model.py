"""Real-time lumped-parameter model of a patient on cardiopulmonary bypass.

Educational model. Parameters are chosen to give plausible, teachable behaviour
and have NOT been clinically validated. Units: flows L/min unless noted,
volumes mL, pressures mmHg, temperatures deg C, time seconds.
"""
import json
import math
import os
from dataclasses import dataclass, asdict

HERE = os.path.dirname(os.path.abspath(__file__))


@dataclass
class Persona:
    id: str
    name: str
    desc: str
    weight: float
    height: float
    hct: float
    ef: float = 1.0
    svr_mult: float = 1.0
    renal: float = 1.0
    hep_sens: float = 1.0
    ai: bool = False
    k0: float = 4.0
    bv_per_kg: float = 70.0
    target_temp: float = 34.0

    @property
    def bsa(self):
        return math.sqrt(self.height * self.weight / 3600.0)


def load_personas():
    with open(os.path.join(HERE, "personas.json")) as f:
        return {p["id"]: Persona(**p) for p in json.load(f)}


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def o2_sat(po2):
    """Severinghaus oxygen dissociation curve (fraction)."""
    p = max(po2, 1.0)
    return 1.0 / (1.0 + 23400.0 / (p ** 3 + 150.0 * p))


# ---- circuit constants -------------------------------------------------
PUMP_A = 45.0        # shut-off head, mmHg per (krpm)^2
PUMP_B = 7.0         # pump internal loss, mmHg per (L/min)^2
R_CIRC = 20.0        # oxygenator + filter + tubing, mmHg per L/min
R_CANN = 4.5         # arterial cannula, mmHg per (L/min)^2
R_RETRO = 40.0       # resistance to backflow through a slow pump
SIPHON = 30.0        # venous siphon head, mmHg
R_VEN = 5.8          # venous line + cannula, mmHg per L/min
C_VEN = 100.0        # patient venous compliance, mL/mmHg
C_ART = 0.00167      # arterial compliance, L/mmHg
V_STATIC = 500.0     # oxygenator + tubing volume, mL
V_RES0 = 900.0       # reservoir level after priming, mL
RES_MAX = 4000.0
CP_K = {"highK": 20.0, "lowK": 8.0, "hot": 8.0}


class Sim:
    DT = 0.02

    def __init__(self, persona: Persona):
        p = self.p = persona
        self.t = 0.0
        self.bsa = p.bsa
        self.co_base = 2.5 * self.bsa
        self.svr0 = 72.0 / (2.5 * self.bsa) * p.svr_mult
        self.vb = p.bv_per_kg * p.weight
        self.vu = self.vb - 6.0 * C_VEN          # unstressed volume -> CVP 6 at baseline
        self.target_flow = 2.4 * self.bsa
        self.r_ven = R_VEN * (1.9 / self.bsa) ** 1.5   # venous cannula sized to the patient
        # controls (student)
        self.c = dict(rpm_set=0.0, art_clamp=True, ven_occl=1.0, sweep=2.0, fio2=0.8,
                      water_set=37.0, cp_route="ante", cp_type="highK", cp_flow=250.0,
                      cp_on=False, root_vent=False, sucker=False, ventilator=True, epi=False, iso=1.0)
        # surgeon-controlled
        self.cannulated = False
        self.xclamp = False
        # patient / circuit state
        self.vp = self.vb
        self.vr = V_RES0
        self.rbc_p = p.hct * self.vb
        self.rbc_c = 0.0
        self.pa = 6.0 + p.ef * self.co_base * self.svr0
        self.rpm = 0.0
        self.qa = self.qv = self.qh = 0.0
        self.temp = 36.6
        self.t_water = 37.0
        self.t_art = 36.6
        self.pao2, self.paco2, self.sao2, self.svo2 = 250.0, 38.0, 0.99, 0.75
        self.lactate = 1.0
        self.k = p.k0
        self.hep = 0.0
        self.hep_total = 0.0
        self.prot_total = 0.0
        self.pressor = 0.0
        self.arrest = 0.0          # cardioplegic arrest level (>=1 arrested)
        self.rhythm = "sinus"
        self.vf_timer = 0.0
        self.injury = 0.0          # myocardial injury 0..1
        self.distension = 0.0
        self.hot_shot_ml = 0.0
        self.cp_dose = 0.0         # mL in current dose
        self.cp_total = 0.0
        self.cp_pressure = 0.0
        self.csp = 0.0
        self.line_p = 0.0
        self.transfuse_left = 0.0
        self.oxy_eff = 1.0
        self.clot_risk = 0.0
        self.air = False
        self.clotted = False
        self.bypass_time = self.clamp_time = self.since_cp = 0.0
        self.do2i = self.vo2 = 0.0
        self.ph = 7.40
        self.max_gradient = 0.0
        self.last_act = None       # (time, value)
        self.last_abg = None
        self.pending = []          # (due_time, kind)
        self.events = []           # model-detected events (code, severity, msg, t)
        self._cool = {}
        self.pulse = 0.0

    # ---- helpers ---------------------------------------------------------
    @property
    def cvp(self):
        return (self.vp - self.vu) / C_VEN

    @property
    def hct_p(self):
        return self.rbc_p / max(self.vp, 1.0)

    @property
    def hct_c(self):
        return self.rbc_c / (self.vr + V_STATIC)

    @property
    def on_bypass(self):
        return self.qa > 0.5

    @property
    def act_true(self):
        return 120.0 + self.p.hep_sens * (self.hep / self.p.weight)

    def emit(self, code, sev, msg, cooldown=60.0):
        last = self._cool.get(code, -1e9)
        if self.t - last >= cooldown:
            self._cool[code] = self.t
            self.events.append(dict(code=code, sev=sev, msg=msg, t=round(self.t, 1)))

    # ---- student actions -------------------------------------------------
    LIMITS = dict(rpm_set=(0, 4500), ven_occl=(0, 1), sweep=(0, 10), fio2=(0.21, 1.0),
                  water_set=(15, 40), cp_flow=(0, 500), iso=(0, 3))

    def set(self, key, value):
        if key not in self.c:
            raise KeyError(key)
        if key in self.LIMITS:
            lo, hi = self.LIMITS[key]
            value = clamp(float(value), lo, hi)
        elif key == "cp_route":
            if value not in ("ante", "retro"):
                raise ValueError(value)
        elif key == "cp_type":
            if value not in CP_K:
                raise ValueError(value)
        else:
            value = bool(value)
        if key == "cp_on" and value and not self.c["cp_on"]:
            self.cp_dose = 0.0
        self.c[key] = value

    def give_heparin(self, units):
        units = clamp(float(units), 0, 100000)
        self.hep += units
        self.hep_total += units

    def give_protamine(self, mg):
        mg = clamp(float(mg), 0, 1000)
        self.prot_total += mg
        if self.qa > 0.2 or self.c["sucker"] or self.rpm > 300:
            self.clotted = True
            self.emit("protamine_on_bypass", "critical",
                      "Protamine given with the pump or suckers still running: the circuit clotted.", 1e9)
        self.hep = max(0.0, self.hep - mg * 100.0)
        self.pressor -= 0.08       # mild vasodilation with protamine

    def give_phenylephrine(self, mcg=100):
        self.pressor += 0.25 * clamp(float(mcg), 0, 400) / 100.0

    def add_volume(self, ml, kind="crystalloid"):
        ml = clamp(float(ml), 0, 1000)
        self.vr = min(RES_MAX, self.vr + ml)
        if kind == "prbc":
            self.rbc_c += 0.6 * ml

    def transfuse(self, ml):
        self.transfuse_left += clamp(float(ml), 0, 500)

    def measure(self, kind):
        self.pending.append((self.t + 6.0, kind))

    def defibrillate(self):
        if self.rhythm == "vf":
            self.rhythm = "sinus"
            self.injury = min(1.0, self.injury + 0.02)

    # ---- integration -----------------------------------------------------
    def step(self, dt=None):
        dt = dt or self.DT
        dtm = dt / 60.0
        c, p = self.c, self.p
        self.t += dt

        # pump speed and flow
        self.rpm += (c["rpm_set"] - self.rpm) * min(1.0, dt / 0.8)
        head = PUMP_A * (self.rpm / 1000.0) ** 2
        if not self.cannulated or c["art_clamp"] or self.clotted:
            qa = 0.0
            self.line_p = head
        elif self.vr <= 1.0 and head > self.pa:
            qa = 0.0
            self.line_p = self.pa
            if self.rpm > 500 and not self.air:
                self.air = True
                self.emit("air_embolism", "critical",
                          "Reservoir ran empty with the pump running: air entered the arterial line.", 1e9)
        else:
            dp = head - self.pa
            if dp >= 0:
                kq = PUMP_B + R_CANN
                qa = (-R_CIRC + math.sqrt(R_CIRC ** 2 + 4 * kq * dp)) / (2 * kq)
            else:
                qa = dp / R_RETRO
                if qa < -0.3:
                    self.emit("retrograde", "major",
                              "Arterial line open with the pump too slow: blood is running backward out of the patient.")
            self.line_p = self.pa + R_CANN * qa * abs(qa) + 0.35 * R_CIRC * qa
        self.qa = qa

        # venous drainage (gravity siphon)
        cvp = self.cvp
        if self.cannulated:
            qv = max(0.0, (SIPHON + cvp) / self.r_ven) * (1.0 - c["ven_occl"]) * clamp((cvp + 1.0) / 3.0, 0.0, 1.0)
        else:
            qv = 0.0
        if self.vr >= RES_MAX:
            qv = min(qv, max(qa, 0.0))
        self.qv = qv

        # heart
        self._heart(dt, dtm)
        contract = p.ef * (1.0 - self.injury) * (1.5 if c["epi"] else 1.0) * clamp(1.0 - 0.06 * (33.0 - self.temp), 0.4, 1.0)
        qh = contract * self.co_base * clamp((cvp - 2.0) / 4.0, 0.0, 1.4) if self.rhythm in ("sinus", "brady") else 0.0
        if self.rhythm == "brady":
            qh *= 0.3
        if self.xclamp:
            qh = 0.0
        self.qh = qh
        self.pulse = 40.0 * qh / self.co_base

        # systemic resistance and arterial pressure
        self.pressor += (0.0 - self.pressor) * dtm / 5.0
        hct_a = self.hct_c if qa > qh else self.hct_p
        visc = 0.55 + 0.45 * clamp(hct_a / p.hct, 0.3, 1.3)
        gas_w = max(qa, 0.0) / max(qa + qh, 0.05) if qa > 0 else 0.0     # anesthetic vapor reaches the patient via the oxygenator
        svr = self.svr0 * visc * (1.0 + 0.02 * (37.0 - self.temp)) * max(0.3, 1.0 + self.pressor) * (1.0 - 0.15 * (c["iso"] - 1.0) * gas_w)
        self.svr = svr
        self.pa += (qh + qa - (self.pa - cvp) / svr) / C_ART * dtm
        self.pa = clamp(self.pa, 3.0, 300.0)

        # cardioplegia delivery
        q_cp = self._cardioplegia(dtm)

        # volumes (mL/min)
        bleed = 30.0 if (self.cannulated and self.hep > 1000 and self.act_true > 250) else 0.0
        q_suck = bleed if c["sucker"] else 0.0
        lost = bleed - q_suck
        q_vent = 0.0
        if c["root_vent"] and self.xclamp:
            q_vent = 120.0 if (c["cp_on"] and c["cp_route"] == "ante") else 25.0
        q_tx = 0.0
        if self.transfuse_left > 0 and self.vr > 5:
            q_tx = min(400.0, self.transfuse_left / dtm, self.vr / dtm)
            self.transfuse_left -= q_tx * dtm
        hp, hc = self.hct_p, self.hct_c
        p_to_c = qv * 1000.0 + q_vent + q_suck + max(-qa, 0.0) * 1000.0
        c_to_p = max(qa, 0.0) * 1000.0 + 0.8 * q_cp + q_tx
        self.vp += (c_to_p + 0.2 * q_cp - p_to_c - lost - 1.0) * dtm
        self.vr = clamp(self.vr + (p_to_c - c_to_p) * dtm, 0.0, RES_MAX)
        self.rbc_p += (c_to_p * hc - (p_to_c + lost) * hp) * dtm
        self.rbc_c += (p_to_c * hp - c_to_p * hc) * dtm
        self.rbc_c = max(self.rbc_c, 0.0)
        if c["sucker"] and self.prot_total > 0 and self.hep < 3000 and not self.clotted:
            self.clotted = True
            self.emit("sucker_after_protamine", "critical",
                      "Pump suckers left on after protamine: clot was pulled into the reservoir.", 1e9)

        self._gas(dt, hct_a)
        self._thermal(dt, dtm)
        self._anticoag(dtm)

        # timers and delayed lab results
        if self.on_bypass:
            self.bypass_time += dt
        if self.xclamp:
            self.clamp_time += dt
            self.since_cp += dt
        for due, kind in [x for x in self.pending if x[0] <= self.t]:
            self.pending.remove((due, kind))
            if kind == "act":
                self.last_act = (round(self.t, 1), round(self.act_true))
            else:
                self.last_abg = (round(self.t, 1), self.gas_snapshot())

    def _heart(self, dt, dtm):
        c = self.c
        if self.xclamp:
            self.arrest *= math.exp(-dtm / 22.0)
            if self.arrest >= 1.0:
                self.rhythm = "asystole"
                self.injury += dtm * (0.003 if self.temp > 35.0 else 0.001)
            elif self.arrest >= 0.5:
                if self.rhythm == "asystole":
                    self.emit("activity_returning", "major",
                              "Electrical activity is returning in the clamped heart: cardioplegia has washed out.", 300)
                self.rhythm = "brady"
                self.injury += dtm * 0.008
            else:
                if self.rhythm in ("asystole", "brady"):
                    self.rhythm = "sinus"
                self.injury += dtm * 0.02
            antegrade = c["cp_on"] and c["cp_route"] == "ante"
            if not c["root_vent"] and not antegrade:
                self.distension += dtm * 0.1
            elif self.p.ai and antegrade:
                self.distension += dtm * 0.5
            else:
                self.distension = max(0.0, self.distension - dtm * 0.5)
            if self.distension > 0.5:
                self.injury += dtm * 0.02
                self.emit("lv_distension", "major", "Left ventricle is distending: it is not being vented.", 120)
        else:
            self.distension = 0.0
            self.arrest *= math.exp(-dtm / 1.0)
            if self.rhythm in ("asystole", "brady") and self.arrest < 0.5:
                ok = self.hot_shot_ml >= 300 and self.temp >= 34.0
                self.rhythm = "sinus" if (ok or self.cp_total == 0) else "vf"
                if self.rhythm == "vf":
                    self.emit("vf", "minor", "Heart came back fibrillating and needed a shock.", 1e9)
        if self.rhythm == "vf":
            self.vf_timer += dt
        else:
            self.vf_timer = 0.0
        self.injury = clamp(self.injury, 0.0, 0.8)

    def _cardioplegia(self, dtm):
        c = self.c
        if not c["cp_on"] or c["cp_flow"] <= 0 or self.vr < 20:
            self.cp_pressure = 0.0
            self.csp = 0.0
            return 0.0
        q = c["cp_flow"]
        kc = CP_K[c["cp_type"]]
        ante = c["cp_route"] == "ante"
        self.csp = 0.0 if ante else q * 0.2
        self.cp_pressure = q * 0.75 + (70.0 if ante else self.csp)
        eff = 1.0
        if not self.xclamp:
            eff = 0.0
            self.emit("cp_no_clamp", "major",
                      "Cardioplegia is running with no cross-clamp: the potassium is going to the whole body.")
        elif ante:
            if self.p.ai:
                eff *= 0.3
                self.emit("ai_antegrade", "minor",
                          "Antegrade dose is leaking through the aortic valve into the ventricle. Consider retrograde.", 300)
            if c["root_vent"]:
                eff *= 0.4
                self.emit("vent_stealing", "minor",
                          "Root vent is on during antegrade delivery and is stealing the dose.", 300)
        vol = q * dtm
        self.cp_dose += vol
        self.cp_total += vol
        self.arrest = min(3.5, self.arrest + eff * vol / 350.0 * (0.5 + 0.5 * kc / 20.0))
        if eff > 0:
            self.since_cp = 0.0
            if c["cp_type"] == "hot":
                self.hot_shot_ml += vol
        self.k += vol / 1000.0 * kc / 30.0
        return q

    def _gas(self, dt, hct_a):
        c = self.c
        vo2_demand = 110.0 * self.bsa * 2.2 ** ((self.temp - 37.0) / 10.0)
        qa = max(self.qa, 0.0)
        qtot = qa + self.qh
        # oxygenator outlet
        if c["sweep"] > 0.2:
            po2_oxy = clamp(c["fio2"] * 600.0 * self.oxy_eff, 30.0, 650.0)
            pco2_oxy = clamp(40.0 * (0.8 * vo2_demand / 167.0) * (2.3 / c["sweep"]) / self.oxy_eff, 12.0, 110.0)
        else:
            po2_oxy, pco2_oxy = 38.0, 60.0
        # lung outlet
        if c["ventilator"]:
            po2_l, pco2_l = 250.0, 38.0
        else:
            po2_l, pco2_l = 35.0, 55.0
        if qtot > 0.05:
            w = qa / qtot
            po2_t = w * po2_oxy + (1 - w) * po2_l
            pco2_t = w * pco2_oxy + (1 - w) * pco2_l
            sat_t = w * o2_sat(po2_oxy) + (1 - w) * (o2_sat(po2_l) if c["ventilator"] else self.svo2)
        else:
            po2_t, pco2_t, sat_t = self.pao2, self.paco2, self.sao2
        a = min(1.0, dt / 15.0)
        self.pao2 += (po2_t - self.pao2) * a
        self.paco2 += (pco2_t - self.paco2) * min(1.0, dt / 45.0)
        self.sao2 += (sat_t - self.sao2) * a
        hb = hct_a * 100.0 / 3.0
        cao2 = 1.34 * hb * self.sao2 + 0.003 * self.pao2
        do2 = qtot * 10.0 * cao2
        self.hb = hb
        self.do2i = do2 / self.bsa
        vo2 = min(vo2_demand, 0.75 * do2)
        self.vo2 = vo2
        debt = vo2_demand - vo2
        self.lactate = clamp(self.lactate + (debt / 100.0 * 0.25 - (self.lactate - 1.0) * 0.02) * dt / 60.0, 0.5, 15.0)
        if do2 > 1.0:
            sv_t = clamp(self.sao2 * (1.0 - vo2 / do2), 0.2, 0.99)
            self.svo2 += (sv_t - self.svo2) * min(1.0, dt / 20.0)
        else:
            self.svo2 += (0.25 - self.svo2) * min(1.0, dt / 60.0)
        self.ph = 7.40 - 0.008 * (self.paco2 - 40.0) - 0.015 * (self.lactate - 1.0)
        self.k += -(self.k - self.p.k0) * (dt / 60.0) / (25.0 / self.p.renal)

    def _thermal(self, dt, dtm):
        self.t_water += (self.c["water_set"] - self.t_water) * min(1.0, dt / 40.0)
        if self.qa > 0.3:
            self.t_art = self.temp + 0.65 * (self.t_water - self.temp)
            self.temp += self.qa * 3.6 * (self.t_art - self.temp) / (self.p.weight * 3.5 * 0.6) * dtm
            grad = abs(self.t_water - self.temp)
            self.max_gradient = max(self.max_gradient, grad)
        else:
            self.t_art = self.temp

    def _anticoag(self, dtm):
        self.hep *= math.exp(-dtm * math.log(2) / 100.0)
        if self.on_bypass and self.act_true < 300 and not self.clotted:
            self.clot_risk += dtm
            if self.clot_risk > 1.5:
                self.oxy_eff = max(0.3, self.oxy_eff - dtm * 0.2)
                self.emit("circuit_clotting", "critical",
                          "On bypass without adequate anticoagulation: the oxygenator is clotting.", 1e9)

    # ---- outputs ---------------------------------------------------------
    def gas_snapshot(self):
        return dict(ph=round(self.ph, 2), pao2=round(self.pao2), paco2=round(self.paco2),
                    sao2=round(self.sao2 * 100), svo2=round(self.svo2 * 100),
                    hct=round((self.hct_c if self.on_bypass else self.hct_p) * 100),
                    k=round(self.k, 1), lactate=round(self.lactate, 1))

    def alarms(self):
        a = []
        ob = self.on_bypass
        if self.cannulated and self.vr < 150:
            a.append(("critical", "Reservoir critically low"))
        elif self.cannulated and self.vr < 300:
            a.append(("warn", "Reservoir level low"))
        if self.line_p > 300:
            a.append(("critical", "Arterial line pressure high"))
        if self.qa < -0.1:
            a.append(("critical", "Retrograde flow"))
        if ob and self.pa < 45:
            a.append(("warn", "Mean arterial pressure low"))
        if ob and self.pa > 90:
            a.append(("warn", "Mean arterial pressure high"))
        if ob and self.do2i < 270:
            a.append(("warn", "Oxygen delivery below 270"))
        if ob and self.svo2 < 0.60:
            a.append(("warn", "Venous saturation low"))
        if ob and self.act_true < 400 and self.last_act:
            a.append(("warn", "ACT below 400 on bypass"))
        if self.csp > 40:
            a.append(("warn", "Coronary sinus pressure high"))
        if self.cp_pressure > 300:
            a.append(("warn", "Cardioplegia line pressure high"))
        if self.k > 6.0:
            a.append(("warn", "Potassium high"))
        if ob and abs(self.t_water - self.temp) > 10:
            a.append(("warn", "Water to blood gradient over 10 C"))
        if self.air:
            a.append(("critical", "Air in arterial line"))
        if self.clotted:
            a.append(("critical", "Circuit clotted"))
        return a

    def snapshot(self):
        r = round
        return dict(
            t=r(self.t, 1), map=r(self.pa, 1), cvp=r(self.cvp, 1), pulse=r(self.pulse, 1),
            rhythm=self.rhythm, hr=0 if self.rhythm in ("asystole", "vf") else (40 if self.rhythm == "brady" else 78),
            flow=r(self.qa, 2), ci=r(max(self.qa, 0) / self.bsa, 2), qh=r(self.qh, 2), qv=r(self.qv, 2),
            rpm=r(self.rpm), line_p=r(self.line_p), res=r(self.vr), res_frac=r(self.vr / RES_MAX, 3),
            temp=r(self.temp, 1), t_water=r(self.t_water, 1), t_art=r(self.t_art, 1),
            pao2=r(self.pao2), paco2=r(self.paco2, 1), sao2=r(self.sao2 * 100, 1), svo2=r(self.svo2 * 100, 1),
            ph=r(self.ph, 2), hct=r((self.hct_c if self.on_bypass else self.hct_p) * 100, 1),
            do2i=r(self.do2i), k=r(self.k, 2), lactate=r(self.lactate, 1),
            rso2=r(clamp(22 + 0.62 * self.svo2 * 100 - max(0, 45 - self.pa) * 0.5, 15, 90)),
            arrest=r(self.arrest, 2), cp_dose=r(self.cp_dose), cp_total=r(self.cp_total),
            cp_pressure=r(self.cp_pressure), csp=r(self.csp, 1),
            hep_total=r(self.hep_total), prot_total=r(self.prot_total),
            last_act=self.last_act, last_abg=self.last_abg, labs_pending=len(self.pending),
            bypass_time=r(self.bypass_time), clamp_time=r(self.clamp_time), since_cp=r(self.since_cp),
            xclamp=self.xclamp, cannulated=self.cannulated, on_bypass=self.on_bypass,
            target_flow=r(self.target_flow, 2), bsa=r(self.bsa, 2), injury=r(self.injury, 3),
            controls=dict(self.c), alarms=self.alarms(),
        )
