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
