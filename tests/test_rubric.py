"""Rubric scoring: section weights, full/half/zero, reasons for every lost point, outcome rules."""
import os, sys, unittest
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from perfusion import rubric
from perfusion.model import load_personas
from perfusion.scenario import Case, EXPECTED, PHASES
from play_case import run

P = load_personas()


class TestRubric(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean = run("standard_adult")
        cls.early = run("standard_adult", mistake="flow_up_early")

    def test_sections_add_to_100_and_match_their_components(self):
        self.assertEqual(sum(mx for _, _, mx in rubric.SECTIONS), 100)
        for sid, _, mx in rubric.SECTIONS:
            self.assertEqual(sum(c["max"] for c in rubric.COMPONENTS[sid]), mx, sid)
        ids = [c["id"] for sid in rubric.COMPONENTS for c in rubric.COMPONENTS[sid]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(rubric.ORDER, PHASES)

    def test_every_rule_points_at_something_the_simulator_records(self):
        for sid in rubric.COMPONENTS:
            for c in rubric.COMPONENTS[sid]:
                for p in c["calls"]:
                    self.assertIn(p, EXPECTED, c["id"])
                for k in c["credits"]:
                    self.assertIn(k, [x for x, _ in Case.CHECKLIST], c["id"])
                if not c["na"]:
                    self.assertIn(c["due"], PHASES, c["id"])

    def test_expert_passes_every_patient_and_is_perfect_on_the_standard_one(self):
        for pid in P:
            with self.subTest(persona=pid):
                rb = run(pid).score()["rubric"]
                self.assertEqual(rb["outcome"], "PASS")
                self.assertGreaterEqual(rb["score"], 95)
                self.assertEqual(rb["possible"] + rb["not_observed"], 100)
        rb = self.clean.score()["rubric"]
        self.assertEqual((rb["score"], rb["missed"], rb["earned"]), (100, [], rb["possible"]))

    def test_unsimulated_work_is_reported_not_scored(self):
        rb = self.clean.score()["rubric"]
        a = rb["sections"][0]
        self.assertEqual((a["id"], a["earned"], a["observed_max"], a["not_observed"]), ("A", 0, 0, 30))
        self.assertTrue(all(i["status"] == "not_observed" and i["why"] for i in a["items"]))

    def test_a_lost_point_always_comes_with_its_reason(self):
        rb = self.early.score()["rubric"]
        self.assertLess(rb["score"], 100)
        hit = [m for m in rb["missed"] if m["id"] == "F1c"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0]["lost"], 1)
        self.assertIn("before the surgeon called the clamp", " ".join(hit[0]["why"]))
        for m in rb["missed"]:
            self.assertTrue(m["why"], m["id"])
        self.assertAlmostEqual(rb["earned"] + sum(m["lost"] for m in rb["missed"]), rb["possible"], places=2)

    def test_components_are_full_half_or_zero(self):
        c = Case(P["standard_adult"])
        c.phase = "DONE"                      # nothing done at all: every observable item is graded
        rb = c.score()["rubric"]
        for s in rb["sections"]:
            for i in s["items"]:
                if i["earned"] is not None:
                    self.assertIn(i["earned"], (0, i["max"] / 2, i["max"]), i["id"])
        self.assertEqual(rb["outcome"], "FAIL")
        self.assertLess(rb["score"], 80)

    def test_marginal_act_is_half_credit(self):
        c = run("standard_adult")
        c.findings.append(dict(code="act_marginal", sev="minor", msg="Went on bypass with ACT 430; most centres want 480.", t=60.0, phase="PRE"))
        b3a = [i for s in c.score()["rubric"]["sections"] for i in s["items"] if i["id"] == "B3a"][0]
        self.assertEqual((b3a["status"], b3a["earned"]), ("half", 0.5))

    def test_critical_event_fails_whatever_the_points(self):
        c = run("standard_adult")
        c.findings.append(dict(code="air_embolism", sev="critical", msg="Air went to the patient.", t=100.0, phase="INITIATE"))
        rb = c.score()["rubric"]
        self.assertEqual(rb["outcome"], "FAIL")
        self.assertIn("Critical event", rb["outcome_reason"])
        self.assertGreaterEqual(rb["score"], 80)

    def test_only_finished_phases_are_graded(self):
        c = Case(P["standard_adult"])
        rb = c.score()["rubric"]
        self.assertEqual((rb["score"], rb["possible"], rb["outcome"]), (100, 0, "IN PROGRESS"))

    def test_findings_outside_the_rubric_are_still_listed(self):
        c = run("standard_adult")
        c.findings.append(dict(code="hotshot_wrong", sev="major", msg="Hot shot requested but a cold solution was delivered.", t=2000.0, phase="HOTSHOT"))
        rb = c.score()["rubric"]
        self.assertEqual([f["code"] for f in rb["other_findings"]], ["hotshot_wrong"])

    def test_same_run_same_rubric(self):
        self.assertEqual(run("ckd").score()["rubric"], run("ckd").score()["rubric"])


if __name__ == "__main__":
    unittest.main()
