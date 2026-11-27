"""Run with:  python3 -m unittest discover -s tests -v"""
import os, sys, unittest
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from perfusion.model import Sim, load_personas, o2_sat
from perfusion.scenario import Case, EXPECTED
from play_case import run

P = load_personas()


def settle(sim, seconds):
    for _ in range(int(seconds / sim.DT)):
        sim.step()


def on_bypass(pid="standard_adult", rpm=3000):
    s = Sim(P[pid])
    s.give_heparin(400 * s.p.weight)
    s.cannulated = True
    s.set("rpm_set", 1500); settle(s, 3)
    s.set("art_clamp", False); s.set("ven_occl", 0.0); s.set("rpm_set", rpm)
    settle(s, 120)
    return s


class TestModel(unittest.TestCase):
    def test_baseline_is_stable(self):
        s = Sim(P["standard_adult"]); settle(s, 60)
        self.assertAlmostEqual(s.pa, 78, delta=6)
        self.assertAlmostEqual(s.cvp, 6, delta=1)
        self.assertGreater(s.svo2, 0.65)

    def test_full_bypass(self):
        s = on_bypass()
        self.assertAlmostEqual(s.qa, s.target_flow, delta=0.4)
        self.assertLess(s.qh, 0.3)                 # heart empty, non-pulsatile
        self.assertTrue(40 < s.pa < 85)
        self.assertTrue(140 < s.line_p < 300)
        self.assertGreater(s.do2i, 280)
        self.assertLess(s.hct_c, s.p.hct)          # hemodilution by the prime

    def test_flow_falls_when_resistance_rises(self):
        s = on_bypass(); q0 = s.qa
        s.give_phenylephrine(400); settle(s, 20)
        self.assertLess(s.qa, q0 - 0.1)            # same RPM, higher afterload, less flow

    def test_retrograde_flow_if_pump_stops_unclamped(self):
        s = on_bypass(); s.set("rpm_set", 0)
        worst = 0.0
        for _ in range(250):
            s.step(); worst = min(worst, s.qa)
        self.assertLess(worst, -0.3)
        self.assertTrue(any(e["code"] == "retrograde" for e in s.events))

    def test_reservoir_empties_into_air(self):
        s = on_bypass(); s.set("ven_occl", 1.0); settle(s, 60)
        self.assertTrue(s.air)

    def test_cooling_lowers_oxygen_demand(self):
        s = on_bypass(); v0 = s.vo2
        s.set("water_set", 26); settle(s, 600)
        self.assertLess(s.temp, 34.5)
        self.assertLess(s.vo2, v0 * 0.9)

    def test_sweep_controls_co2(self):
        s = on_bypass(); s.set("sweep", 1.0); settle(s, 240); hi = s.paco2
        s.set("sweep", 5.0); settle(s, 240)
        self.assertGreater(hi, s.paco2 + 15)

    def test_cardioplegia_arrests_only_with_clamp(self):
        s = on_bypass()
        s.set("cp_on", True); settle(s, 60)
        self.assertNotEqual(s.rhythm, "asystole")
        s.set("cp_on", False); s.xclamp = True
        s.set("cp_on", True); settle(s, 240)
        self.assertEqual(s.rhythm, "asystole")
        self.assertGreater(s.k, s.p.k0 + 0.3)

    def test_cardioplegia_washes_out_without_a_redose(self):
        s = on_bypass(); s.xclamp = True
        s.set("root_vent", True); s.set("cp_route", "retro"); s.set("cp_flow", 190); s.set("cp_on", True); settle(s, 400)
        s.set("cp_on", False); self.assertEqual(s.rhythm, "asystole")
        settle(s, 14 * 60); self.assertEqual(s.rhythm, "asystole")      # still protected at 14 minutes
        settle(s, 11 * 60); self.assertNotEqual(s.rhythm, "asystole")   # activity back by 25 minutes
        self.assertTrue(any(e["code"] == "activity_returning" for e in s.events))

    def test_heparin_resistance(self):
        a, b = Sim(P["standard_adult"]), Sim(P["heparin_resistant"])
        a.give_heparin(400 * a.p.weight); b.give_heparin(400 * b.p.weight)
        self.assertGreater(a.act_true, 480)
        self.assertLess(b.act_true, 400)

    def test_protamine_on_bypass_clots_circuit(self):
        s = on_bypass(); s.give_protamine(300)
        self.assertTrue(s.clotted)

    def test_saturation_curve(self):
        self.assertAlmostEqual(o2_sat(27), 0.5, delta=0.03)
        self.assertGreater(o2_sat(100), 0.97)


class TestLabState(unittest.TestCase):
    """State added for the pump console and patient monitor (docs/LAB_FIDELITY.md sections 1 and 2)."""

    def test_pa_and_arterial_pulsatile_before_bypass_flat_on_full_bypass(self):
        s = Sim(P["standard_adult"]); settle(s, 30); d = s.snapshot()
        self.assertGreater(d["art_sys"] - d["art_dia"], 25)
        self.assertGreater(d["pap_sys"] - d["pap_dia"], 8)
        self.assertTrue(d["cvp"] < d["pap"] < 30, d["pap"])
        self.assertIsNotNone(d["spo2"])
        s = on_bypass(); d = s.snapshot()
        self.assertLess(d["art_sys"] - d["art_dia"], 2)          # flat arterial line on full bypass
        self.assertLess(d["pap_sys"] - d["pap_dia"], 2)
        self.assertAlmostEqual(d["pap"], d["cvp"], delta=1.0)     # no output through the lungs
        self.assertIsNone(d["spo2"])                              # pulse oximetry loses its signal

    def test_monitor_mode_label(self):
        s = Sim(P["standard_adult"]); self.assertEqual(s.mode, "before")
        s = on_bypass(); self.assertEqual(s.snapshot()["mode"], "full")
        s.set("rpm_set", 2000); settle(s, 20); self.assertEqual(s.mode, "partial")
        s.set("art_clamp", True); s.set("rpm_set", 0); settle(s, 5); self.assertEqual(s.mode, "after")

    def test_urine_output(self):
        s = Sim(P["standard_adult"]); settle(s, 600); d = s.snapshot()
        self.assertAlmostEqual(d["urine_rate"] / s.p.weight, 1.3, delta=0.5)   # about 1 mL/kg/h
        self.assertAlmostEqual(d["urine_ml"], d["urine_rate"] / 6, delta=4)
        low = Sim(P["ckd"]); settle(low, 600)
        self.assertLess(low.urine_ml / low.p.weight, s.urine_ml / s.p.weight)   # poor kidneys make less
        s.pa = 40.0; s.step(); self.assertEqual(s.urine_rate, 0.0)             # none below 45 mmHg

    def test_second_act_channel(self):
        a, b = on_bypass(), on_bypass()
        for s in (a, b):
            s.measure("act"); settle(s, 200)
        self.assertIsNotNone(a.last_act2)
        self.assertEqual(a.last_act2, b.last_act2)                # deterministic
        self.assertAlmostEqual(a.last_act2[1], a.last_act[1], delta=0.04 * a.last_act[1])
        self.assertEqual(a.last_act2[0], a.last_act[0])

    def test_heater_cooler_circuits(self):
        s = Sim(P["standard_adult"]); settle(s, 5)
        self.assertAlmostEqual(s.t_cp_water, 4.0, delta=0.1)
        s.set("cp_water_set", 37); settle(s, 300)
        self.assertAlmostEqual(s.t_cp_water, 37, delta=0.3)       # warmed for a hot shot
        s.set("cp_hc_on", False); settle(s, 600)
        self.assertLess(s.t_cp_water, 32)                         # drifts toward the room
        s.set("water_set", 30); s.set("hc_on", False); settle(s, 120)
        self.assertGreater(s.t_water, 33)                         # patient circuit no longer follows its set point

    def test_sucker_and_vent_speeds(self):
        a, b = on_bypass(), on_bypass()
        for s in (a, b):
            s.set("sucker", True)
        b.set("sucker_max", 10); settle(a, 60); settle(b, 60)
        self.assertAlmostEqual(a.q_suck, 30.0, delta=0.1)         # default speed returns all the field blood
        self.assertAlmostEqual(b.q_suck, 10.0, delta=0.1)         # too slow: the rest is lost
        self.assertLess(b.vp + b.vr, a.vp + a.vr)
        a.xclamp = True; a.set("root_vent", True); a.step()
        self.assertAlmostEqual(a.q_vent, 25.0)
        a.set("vent_max", 8); a.step(); self.assertAlmostEqual(a.q_vent, 8.0)
        d = a.snapshot()
        self.assertAlmostEqual(d["vent_return"], 0.008); self.assertAlmostEqual(d["sucker_return"], 0.03)

    def test_roller_pumps(self):
        s = Sim(P["standard_adult"]); r = s.snapshot()["rollers"]
        self.assertEqual(set(r), {"arterial", "cardioplegia", "sucker", "vent"})
        self.assertTrue(all(not x["on"] and x["rpm"] == 0 for x in r.values()))
        s.set("cp_on", True); s.set("cp_flow", 252); s.set("sucker", True)
        r = s.snapshot()["rollers"]
        self.assertEqual((r["cardioplegia"]["flow"], r["cardioplegia"]["rpm"], r["cardioplegia"]["tubing"]), (0.252, 20.0, '1/4"'))
        self.assertAlmostEqual(r["cardioplegia"]["pct"], 8.0)
        self.assertEqual(r["sucker"]["flow"], 0.1)
        self.assertEqual(r["arterial"]["rpm"], 0)                 # idle: the centrifugal pump is the arterial pump
        s.set("cp_on", False)
        self.assertEqual(s.snapshot()["rollers"]["cardioplegia"]["rpm"], 0)
        self.assertEqual(s.snapshot()["rollers"]["cardioplegia"]["set"], 252)   # the dial keeps its setting

    def test_alarm_limits_are_the_ones_shown(self):
        s = Sim(P["standard_adult"]); lim = s.snapshot()["limits"]
        s.line_p = lim["line_p"] + 1
        self.assertIn(("critical", "Arterial line pressure high"), s.alarms())
        s.line_p = lim["line_p"] - 1
        self.assertNotIn(("critical", "Arterial line pressure high"), s.alarms())

    def test_every_persona_has_age_and_sex(self):
        for pid, p in P.items():
            self.assertTrue(18 <= p.age <= 100 and p.sex in ("F", "M"), pid)
        snap = Case(P["small_anemic"]).snapshot()["persona"]
        self.assertEqual((snap["age"], snap["sex"]), (78, "F"))

    def test_older_saves_without_the_new_fields_still_load(self):
        from perfusion.saves import capture, restore
        from perfusion.autopilot import Autopilot
        c = Case(P["standard_adult"]); state = capture(c, Autopilot(c))
        for k in ("t_cp_water", "urine_ml", "urine_rate", "q_suck", "q_vent", "last_act2"):
            del state["sim"][k]
        for k in ("sucker_max", "vent_max", "hc_on", "cp_water_set", "cp_hc_on"):
            del state["sim"]["c"][k]
        del state["persona"]["age"], state["persona"]["sex"]
        case, _ = restore(state)
        self.assertEqual(case.sim.c["sucker_max"], 100.0)
        self.assertEqual(case.sim.urine_ml, 0.0)
        del state["sim"]["vp"]
        with self.assertRaises(ValueError):                       # anything else missing is still refused
            restore(state)


def rubric_items(case):
    return {i["id"]: i for sec in case.score()["rubric"]["sections"] for i in sec["items"]}


class TestStudentTimers(unittest.TestCase):
    """docs/LAB_SESSION_NOTES.md item 1: bypass, clamp and cardioplegia timers the student runs (rubric C1b, D4, F5b)."""

    def test_timer_start_stop_reset_follow_case_time(self):
        c = Case(P["standard_adult"])
        c.action(dict(type="timer", which="bypass", op="start"))
        for _ in range(500):
            c.tick()                                              # 10 s
        self.assertAlmostEqual(c.clock("bypass"), 10.0, delta=0.05)
        c.action(dict(type="timer", which="bypass", op="stop"))
        for _ in range(250):
            c.tick()
        self.assertAlmostEqual(c.clock("bypass"), 10.0, delta=0.05)   # stopped: holds its reading
        c.action(dict(type="timer", which="bypass", op="start"))
        for _ in range(250):
            c.tick()
        self.assertAlmostEqual(c.clock("bypass"), 15.0, delta=0.05)   # restart continues from the reading
        c.action(dict(type="timer", which="bypass", op="reset"))
        self.assertAlmostEqual(c.clock("bypass"), 0.0, delta=0.05)
        snap = c.snapshot()["clocks"]
        self.assertTrue(snap["bypass"]["run"]); self.assertFalse(snap["clamp"]["run"])
        for bad in (dict(which="lunch", op="start"), dict(which="clamp", op="explode")):
            with self.assertRaises(ValueError):
                c.action(dict(type="timer", **bad))

    def test_expert_runs_the_timers_and_answers_the_surgeon(self):
        case = run("standard_adult")
        items = rubric_items(case)
        for k in ("C1b", "D4", "F5b"):
            self.assertEqual(items[k]["status"], "full", (k, items[k]["why"]))
        asked = [l["text"] for l in case.lines]
        for q in ("What was the clamp time?", "What is the bypass time?", "How long since the last dose?"):
            self.assertIn(q, asked)
        self.assertEqual({r["what"] for r in case.reports}, {"clamp_time", "bypass_time", "cp_time"})
        self.assertTrue(all(abs(r["said"] - r["true"]) <= 5 and r["asked"] for r in case.reports))

    def test_no_timers_loses_c1b_d4_f5b_with_reasons(self):
        case = run("standard_adult", mistake="no_timers")
        items = rubric_items(case)
        for k in ("C1b", "D4", "F5b"):
            self.assertEqual(items[k]["status"], "zero", k)
            self.assertTrue(items[k]["why"], k)
        self.assertIn("not running 30 seconds after going on bypass", " ".join(items["C1b"]["why"]))
        self.assertIn("got no answer", " ".join(items["D4"]["why"]))
        self.assertEqual(case.score()["critical"], 0)
        self.assertGreaterEqual(case.score()["score"], 80)        # missing timers alone does not fail the run

    def test_late_bypass_timer_is_half(self):
        c = Case(P["standard_adult"]); c.goto("INITIATE"); c.sim.cannulated = True
        c.flags["bp_on_t"] = c.t
        for _ in range(int(40 / c.sim.DT)):
            c.tick()
        c.action(dict(type="timer", which="bypass", op="start"))   # 40 s after going on
        c.flags.setdefault("bp_clock_30", dict(run=False, read=0))
        c.goto("COOL")
        frac, why = __import__("perfusion.rubric", fromlist=["x"])._bypass_timer_started(c)
        self.assertEqual(frac, 0.5); self.assertIn("late", why[0])

    def test_wrong_reported_time_is_explained(self):
        c = Case(P["standard_adult"])
        c.sim.clamp_time = 2400.0
        c.ask("clamp", "What was the clamp time?")
        c.action(dict(type="timer", which="clamp", op="start"))    # started now: reads 0
        c.action(dict(type="report", what="clamp_time"))
        self.assertIn("Is your cross-clamp timer running?", c.lines[-1]["text"])
        from perfusion.rubric import _answer
        ok, why = _answer(c, "clamp", "clamp time")
        self.assertFalse(ok); self.assertIn("it was 40:00", why)
        self.assertIsNone(c.flags.get("ask_clamp"))             # the question is answered, even if wrongly

    def test_older_saves_load_with_timers_reset(self):
        from perfusion.saves import capture, restore
        from perfusion.autopilot import Autopilot
        c = Case(P["standard_adult"]); state = capture(c, Autopilot(c))
        for k in ("clocks", "clock_log", "reports"):
            del state["case"][k]
        case, _ = restore(state)
        self.assertEqual(case.clock("bypass"), 0.0)
        self.assertEqual(case.snapshot()["clocks"]["clamp"]["run"], False)


def reperfuse(pid="standard_adult", hot_shot=500.0, temp=36.5, k=4.5):
    """A sim whose clamp has just come off after cardioplegia; one step decides the rhythm it comes back in."""
    s = Sim(P[pid])
    s.cp_total, s.hot_shot_ml, s.temp, s.k = 1300.0, hot_shot, temp, k
    s.rhythm, s.arrest, s.xclamp = "asystole", 0.4, False
    s.step()
    return s


def case_at_wean():
    """An expert run stopped as weaning is announced (restored fresh for each test)."""
    if not hasattr(case_at_wean, "state"):
        from perfusion.saves import capture
        from perfusion.autopilot import Autopilot
        c = Case(P["standard_adult"]); pilot = Autopilot(c)
        while not (c.phase == "WEAN" and c.sim.rhythm == "sinus" and c.sim.c["ventilator"]):
            pilot.step(); c.tick()
        assert not c.flags.get("wean_started")
        case_at_wean.state = capture(c, pilot)
    from perfusion.saves import restore
    import copy
    return restore(copy.deepcopy(case_at_wean.state))[0]


def drop_flow(c, rpm=1900, seconds=8):
    c.sim.set("rpm_set", rpm)
    for _ in range(int(seconds / c.sim.DT)):
        c.tick()


class TestRhythmBeforeWeaning(unittest.TestCase):
    """docs/LAB_SESSION_NOTES.md item 2: the heart may come back flat, fibrillating or in sinus rhythm."""

    def test_reperfusion_rhythm_is_decided_by_conduct_potassium_and_patient(self):
        self.assertEqual(reperfuse().rhythm, "sinus")
        s = reperfuse(hot_shot=0.0)
        self.assertEqual(s.rhythm, "vf"); self.assertIn("vf", [e["code"] for e in s.events])
        self.assertEqual(reperfuse(temp=33.0).rhythm, "vf")
        self.assertEqual(reperfuse(k=6.0).rhythm, "asystole")             # hyperkalemic heart comes back flat
        self.assertEqual(reperfuse("low_ef").rhythm, "vf")                  # this patient's heart fibrillates
        self.assertEqual(reperfuse().reperf_rhythm, reperfuse().reperf_rhythm)   # deterministic

    def test_shock_energy_and_antiarrhythmics(self):
        s = reperfuse(hot_shot=0.0)
        self.assertFalse(s.defibrillate(10)); self.assertEqual(s.rhythm, "vf")   # 10 J is not enough on its own
        self.assertTrue(s.defibrillate(20)); self.assertEqual(s.rhythm, "sinus")
        s = reperfuse(hot_shot=0.0); s.give_drug("lidocaine"); s.give_drug("magnesium")
        self.assertTrue(s.defibrillate(10))                                    # lidocaine and magnesium lower the energy
        s = reperfuse(temp=33.0)
        self.assertFalse(s.defibrillate(20)); self.assertTrue(s.defibrillate(30))   # a cold heart needs more
        s = reperfuse(k=6.0)
        self.assertFalse(s.defibrillate(30)); self.assertEqual(s.rhythm, "asystole")   # a flat line does not convert

    def test_flat_heart_restarts_with_calcium_or_epinephrine_not_by_itself(self):
        s = reperfuse(k=6.0); settle(s, 60)
        self.assertEqual(s.rhythm, "asystole")
        s.give_drug("calcium"); settle(s, 25); self.assertEqual(s.rhythm, "asystole")
        settle(s, 10); self.assertEqual(s.rhythm, "sinus")
        s = reperfuse(k=6.0); s.set("epi", True); settle(s, 65)
        self.assertEqual(s.rhythm, "sinus")
        with self.assertRaises(ValueError):
            s.give_drug("aspirin")

    def test_shocking_a_flat_line_is_refused_and_scored(self):
        c = case_at_wean(); c.sim.rhythm, c.sim.reperf_t = "asystole", c.t
        c.action(dict(type="defib", joules=20))
        self.assertEqual(c.sim.rhythm, "asystole")
        self.assertIn("not a shockable rhythm", c.lines[-1]["text"])
        self.assertEqual(c.findings[-1]["code"], "shock_no_vf")
        with self.assertRaises(ValueError):
            c.action(dict(type="defib", joules=200))

    def test_calcium_waits_ten_minutes_unless_the_heart_is_flat(self):
        c = case_at_wean(); off = c.flags["clamp_off_t"]
        c.action(dict(type="drug", name="calcium"))
        self.assertEqual(c.findings[-1]["code"], "calcium_early")
        c = case_at_wean(); c.sim.rhythm = "asystole"                      # reperfused and flat
        c.action(dict(type="drug", name="calcium"))
        self.assertNotIn("calcium_early", [f["code"] for f in c.findings])
        c = case_at_wean(); c.flags["clamp_off_t"] = off - 601
        c.action(dict(type="drug", name="calcium"))
        self.assertNotIn("calcium_early", [f["code"] for f in c.findings])

    def test_weaning_without_a_rhythm_is_critical(self):
        c = case_at_wean(); c.sim.rhythm = "vf"
        drop_flow(c)
        codes = [f["code"] for f in c.findings]
        self.assertIn("wean_no_rhythm", codes)
        self.assertNotIn("wean_before_ejecting", codes)                    # one error, one penalty
        self.assertEqual(c.score()["rubric"]["outcome"], "FAIL")

    def test_weaning_without_a_pulse_is_critical(self):
        c = case_at_wean(); c.sim.set("ven_occl", 0.0)                      # heart left empty: no pulsatile pressure
        settle(c.sim, 20)
        self.assertLess(c.sim.pulse, 3)
        drop_flow(c)
        self.assertIn("wean_no_pulse", [f["code"] for f in c.findings])

    def test_weaning_needs_lidocaine_and_magnesium(self):
        c = case_at_wean(); c.sim.drugs = {}
        c.sim.set("ven_occl", 0.9); settle(c.sim, 40)
        drop_flow(c, rpm=2600)
        f = [f for f in c.findings if f["code"] == "drugs_missing"]
        self.assertTrue(f); self.assertIn("lidocaine 100 mg and magnesium 2 g", f[0]["msg"])
        self.assertNotIn("wean_no_pulse", [x["code"] for x in c.findings])
        f1c = rubric_items(c)["F1c"]
        self.assertEqual(f1c["status"], "half"); self.assertIn(f[0]["msg"], f1c["why"])   # scored under the clamp-off sequence

    def test_untreated_fibrillation_is_shocked_by_the_surgeon_and_scored(self):
        c = case_at_wean(); c.sim.rhythm, c.sim.reperf_t = "vf", c.t
        for _ in range(int(35 / c.sim.DT)):
            c.tick()
        self.assertIn("Do you want the paddles?", c.lines[-1]["text"])
        for _ in range(int(90 / c.sim.DT)):
            c.tick()
        self.assertIn("vf_untreated", [f["code"] for f in c.findings])
        self.assertEqual(c.sim.rhythm, "sinus")


def tick_until(c, cond, seconds=300, pilot=None):
    for _ in range(int(seconds / c.sim.DT)):
        if cond():
            return True
        if pilot:
            pilot.step()
        c.tick()
    return cond()


class TestWeanByVolume(unittest.TestCase):
    """docs/LAB_SESSION_NOTES.md item 3: fill in bites until the dicrotic notch, CVP and pressure targets, volume back."""

    def test_dicrotic_notch_needs_an_ejecting_heart(self):
        c = case_at_wean(); s = c.sim
        self.assertFalse(s.notch)                                       # empty heart on full bypass
        s.set("ven_occl", 0.45); s.transfuse(150); settle(s, 20)
        self.assertTrue(s.pulse >= 8 and s.notch and s.snapshot()["notch"])
        s.rhythm = "vf"; s.step(); self.assertFalse(s.notch)

    def test_take_back_returns_volume_to_the_reservoir(self):
        s = Sim(P["standard_adult"]); v0, r0 = s.vp, s.vr
        s.take_back(200); settle(s, 40)
        self.assertAlmostEqual(s.vr - r0, 200, delta=2)
        self.assertAlmostEqual(v0 - s.vp, 200, delta=5)                 # plus a little urine
        self.assertEqual(s.takeback_left, 0)
        s.vp = s.vu - 50; s.take_back(300); s.step()
        self.assertEqual(s.takeback_left, 0)                            # nothing to drain from an empty patient
        with self.assertRaises(ValueError):
            Case(P["standard_adult"]).action(dict(type="take_back", ml=5000))

    def test_big_bites_are_scored(self):
        c = case_at_wean()
        c.action(dict(type="transfuse", ml=150))
        self.assertNotIn("big_bite", [f["code"] for f in c.findings])
        c.action(dict(type="transfuse", ml=150))                        # a second bite before the first is in
        self.assertEqual(c.findings[-1]["code"], "big_bite")
        c = case_at_wean(); c.action(dict(type="transfuse", ml=400))
        self.assertIn("Gave 400 mL at once", c.findings[-1]["msg"])

    def test_coming_down_before_the_notch_is_scored(self):
        c = case_at_wean(); s = c.sim
        s.set("ven_occl", 0.3)
        self.assertTrue(tick_until(c, lambda: s.pulse >= 3.5, 60))
        s.set("rpm_set", 1200)
        self.assertTrue(tick_until(c, lambda: c.flags.get("wean_started"), 30))
        codes = [f["code"] for f in c.findings]
        self.assertIn("wean_no_notch", codes); self.assertNotIn("wean_no_pulse", codes)

    def test_overfilling_brings_take_200_back_then_a_finding(self):
        c = case_at_wean(); s = c.sim
        s.set("ven_occl", 0.7)
        for _ in range(4):
            s.transfuse(200); settle(s, 1)
        self.assertTrue(tick_until(c, lambda: c.flags.get("tb_ask"), 120))
        self.assertIn("Take 200 back", c.lines[-1]["text"])
        c.action(dict(type="take_back", ml=200))
        self.assertIsNone(c.flags.get("tb_ask"))
        self.assertTrue(tick_until(c, lambda: any(f["code"] == "overfilled" for f in c.findings), 120))

    def test_skipping_a_hold_level_is_scored(self):
        from perfusion.autopilot import Autopilot
        c = case_at_wean(); pilot = Autopilot(c)
        self.assertTrue(tick_until(c, lambda: c.flags.get("wean_started"), 300, pilot))
        c.sim.set("ven_occl", 0.75); c.sim.set("rpm_set", 1750)         # heart kept full, straight past three-quarter flow
        self.assertTrue(tick_until(c, lambda: any(f["code"] == "wean_skipped_step" for f in c.findings), 60))
        f = [f for f in c.findings if f["code"] == "wean_skipped_step"][0]
        self.assertEqual(f["step"], 0)
        self.assertIn("I asked for three-quarter flow", " ".join(l["text"] for l in c.lines[-3:]))

    def test_expert_fills_in_bites_and_holds_each_level(self):
        case = run("standard_adult")
        items = rubric_items(case)
        for k in ("F2a", "F2b", "F2c", "F3a", "F3b", "F4a", "F4b"):
            self.assertEqual(items[k]["status"], "full", (k, items[k]["why"]))
        self.assertFalse([f for f in case.findings if f["code"] in ("big_bite", "overfilled", "wean_no_notch", "wean_skipped_step")])


class TestCase_(unittest.TestCase):
    def test_expert_plays_clean_case_every_persona(self):
        for pid in P:
            with self.subTest(persona=pid):
                c = run(pid); sc = c.score()
                self.assertEqual(c.phase, "DONE")
                self.assertEqual(sc["critical"], 0)
                self.assertGreaterEqual(sc["score"], 90)
                self.assertTrue(all(x["done"] for x in sc["checklist"]), [x["id"] for x in sc["checklist"] if not x["done"]])
                self.assertEqual(set(EXPECTED), c.callouts_done)

    def test_video_sequencing_error_is_caught(self):
        c = run("standard_adult", mistake="flow_up_early")
        self.assertIn("flow_up_early", [f["code"] for f in c.findings])
        self.assertLess(c.score()["score"], 100)

    def test_grading_is_deterministic(self):
        a, b = run("ckd"), run("ckd")
        self.assertEqual(a.score(), b.score())
        self.assertEqual(a.t, b.t)

    def test_protamine_before_coming_off_is_critical(self):
        c = Case(P["standard_adult"])
        c.action(dict(type="protamine", mg=300))
        self.assertEqual(c.score()["critical"], 1)

    def test_transfusion_refusal_is_enforced(self):
        c = Case(P["jehovah_witness"])
        c.action(dict(type="volume", ml=300, kind="prbc"))
        self.assertIn("transfusion_refused", [f["code"] for f in c.findings])

    def test_surgeon_does_not_wait_forever_for_stable_bypass(self):
        c = Case(P["standard_adult"])
        c.sim.give_heparin(30000); c.sim.cannulated = True; c.phase = "STABILIZE"; c.flags["abg_t"] = 0.0
        for _ in range(int(430 / c.sim.DT)):
            c.tick()
        self.assertEqual(c.phase, "COOL")
        self.assertIn("unstable_bypass", [f["code"] for f in c.findings])

    def test_surgeon_does_not_wait_forever_off_bypass(self):
        c = Case(P["vasoplegic"]); c.phase = "POST"; c.sim.pressor = -0.5
        c.sim.vp -= 900                       # empty, hypotensive patient that never stabilises
        for _ in range(int(490 / c.sim.DT)):
            c.sim.pressor = -0.5; c.tick()
        self.assertTrue(c.flags.get("prot_asked"))
        self.assertIn("unstable_off_bypass", [f["code"] for f in c.findings])

    def test_one_error_one_penalty_for_protamine_with_suckers(self):
        c = Case(P["standard_adult"]); c.phase = "POST"; c.sim.set("sucker", True)
        c.action(dict(type="protamine", mg=300)); c.tick()
        self.assertEqual(c.score()["critical"], 1)

    def test_bad_action_rejected(self):
        c = Case(P["standard_adult"])
        with self.assertRaises(Exception):
            c.action(dict(type="set", key="nope", value=1))
        c.action(dict(type="set", key="rpm_set", value=99999))
        self.assertEqual(c.sim.c["rpm_set"], 4500)


if __name__ == "__main__":
    unittest.main()
