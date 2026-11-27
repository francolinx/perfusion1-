"""Instructor controls: they change the physiology, never the score directly, and take the run off the board."""
import os, sys, tempfile, unittest
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from perfusion import instructor, leaderboard
from perfusion.model import Sim, load_personas
from perfusion.scenario import Case
from perfusion.server import Session
from test_sim import on_bypass, settle

P = load_personas()


class TestInstructorModel(unittest.TestCase):
    def test_neutral_controls_change_nothing(self):
        a, b = on_bypass(), on_bypass()
        instructor.apply(Case(P["standard_adult"]), dict(op="neutral"))
        b.inst.update(instructor.NEUTRAL)
        settle(a, 30); settle(b, 30)
        self.assertEqual((a.pa, a.qa, a.vr, a.svo2), (b.pa, b.qa, b.vr, b.svo2))
        self.assertEqual(set(Sim(P["standard_adult"]).inst), set(instructor.KNOBS))

    def test_low_resistance_drops_pressure_at_the_same_flow(self):
        a, b = on_bypass(), on_bypass()
        b.inst["svr"] = 0.5
        settle(a, 90); settle(b, 90)
        self.assertLess(b.pa, a.pa - 10)

    def test_kinked_arterial_line_raises_line_pressure_and_cuts_flow(self):
        a, b = on_bypass(), on_bypass()
        b.inst["art_kink"] = 4.0
        settle(a, 30); settle(b, 30)
        self.assertLess(b.qa, a.qa - 0.3)

    def test_venous_obstruction_drains_the_reservoir(self):
        a, b = on_bypass(), on_bypass()
        b.inst["ven_block"] = 0.8
        settle(a, 20); settle(b, 20)
        self.assertLess(b.vr, a.vr - 150)

    def test_higher_oxygen_demand_lowers_venous_saturation(self):
        a, b = on_bypass(), on_bypass()
        b.inst["metabolic"] = 1.8
        settle(a, 120); settle(b, 120)
        self.assertLess(b.svo2, a.svo2 - 0.05)

    def test_failing_oxygenator_lowers_arterial_oxygen(self):
        a, b = on_bypass(), on_bypass()
        c = Case(P["standard_adult"]); c.sim = b
        instructor.apply(c, dict(op="knob", id="oxy", value=0.4))
        settle(a, 90); settle(b, 90)
        self.assertLess(b.pao2, a.pao2 - 100)

    def test_bleeding_loses_volume(self):
        a, b = on_bypass(), on_bypass()
        b.inst["bleed"] = 400
        settle(a, 60); settle(b, 60)
        self.assertLess(b.vp + b.vr, a.vp + a.vr - 300)

    def test_weak_heart_ejects_less(self):
        a, b = Sim(P["standard_adult"]), Sim(P["standard_adult"])
        b.inst["contract"] = 0.4
        settle(a, 60); settle(b, 60)
        self.assertLess(b.pa, a.pa - 10)


class TestInstructorOps(unittest.TestCase):
    def test_values_are_clamped_and_unknown_things_refused(self):
        c = Case(P["standard_adult"])
        instructor.apply(c, dict(op="knob", id="svr", value=99))
        self.assertEqual(c.sim.inst["svr"], instructor.KNOBS["svr"][2])
        for bad in (dict(op="knob", id="nope", value=1), dict(op="rhythm", value="disco"), dict(op="event", id="x"),
                    dict(op="say", text="   "), dict(op="launch")):
            with self.assertRaises(ValueError):
                instructor.apply(c, bad)

    def test_events_rhythm_and_voice(self):
        c = Case(P["standard_adult"])
        c.sim.give_heparin(30000); hep = c.sim.hep
        instructor.apply(c, dict(op="event", id="act_drop"))
        self.assertLess(c.sim.hep, hep)
        instructor.apply(c, dict(op="rhythm", value="vf"))
        self.assertEqual(c.sim.rhythm, "vf")
        instructor.apply(c, dict(op="say", text="Pressure is dropping.  What is going on?"))
        self.assertEqual(c.lines[-1]["text"], "Pressure is dropping. What is going on?")
        self.assertTrue(c.flags["instructor"])

    def test_pace_alone_does_not_mark_the_run(self):
        c = Case(P["standard_adult"])
        instructor.apply(c, dict(op="speed", value=10))
        self.assertEqual(c.speed, 10)
        self.assertFalse(c.flags.get("instructor"))

    def test_instructor_never_writes_findings_or_credits(self):
        c = Case(P["standard_adult"])
        for op in (dict(op="knob", id="svr", value=0.5), dict(op="event", id="k_up"), dict(op="rhythm", value="brady"), dict(op="neutral")):
            instructor.apply(c, op)
        self.assertEqual((c.findings, c.credits), ([], set()))

    def test_describe_matches_the_knobs(self):
        d = instructor.describe()
        self.assertEqual({k["id"] for k in d["knobs"]}, set(instructor.KNOBS))
        for k in d["knobs"]:
            self.assertTrue(k["min"] <= k["neutral"] <= k["max"] and k["help"])


class TestInstructorSession(unittest.TestCase):
    def test_instructor_led_runs_are_logged_and_not_ranked(self):
        with tempfile.TemporaryDirectory() as d:
            s = Session(saves_dir=os.path.join(d, "saves"), logs_dir=os.path.join(d, "logs"))
            s.reset("standard_adult", student="Ana")
            self.assertFalse(s.state()["session"]["instructor_used"])
            r = s.instruct(dict(op="knob", id="svr", value=0.6))
            self.assertIn("Vascular resistance", r["note"])
            st = s.state()
            self.assertTrue(st["session"]["instructor_used"])
            v = s.instructor_view()
            self.assertEqual(v["instructor"]["knobs"]["svr"], 0.6)
            self.assertEqual(v["session"]["notes"][-1]["note"], r["note"])
            doc = dict(s.log.doc, status="complete", final=dict(phase="DONE", score=100, critical=0, findings=[], callouts={}))
            self.assertIsNone(leaderboard.row_of(doc))
            doc["instructor_used"] = False
            self.assertIsNotNone(leaderboard.row_of(doc))


if __name__ == "__main__":
    unittest.main()
