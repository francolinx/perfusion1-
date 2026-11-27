"""Leaderboard ranking, levels, quiz and the run time series."""
import json, os, sys, tempfile, unittest
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from perfusion import leaderboard as lb, quiz
from perfusion.server import ApiError, Session
from perfusion.sessionlog import SERIES_KEYS


def doc(sid, student="Ana", persona="standard_adult", score=100, findings=(), map_in=98, do2_in=99, made=13,
        minutes=50.0, ts=1000.0, **kw):
    f = [dict(sev=s, code=c, t=10.0 * i, msg="", phase="OPERATE") for i, (s, c) in enumerate(findings)]
    d = dict(id=sid, student=student, persona=dict(id=persona, name=persona), status="complete", practice=False,
             autopilot_used=False, started_at="2026-11-27T09:00:00", started_ts=ts, case_time_start=0.0,
             case_time_end=minutes * 60, final=dict(phase="DONE", score=score, critical=sum(1 for s, _ in findings if s == "critical"),
             findings=f, callouts=dict(made=made, due=13), map_in_range=map_in, do2_in_range=do2_in, checklist=[]))
    d.update(kw)
    return d


class TestBoard(unittest.TestCase):
    def test_only_clean_student_runs_count(self):
        self.assertIsNotNone(lb.row_of(doc("a")))
        self.assertIsNone(lb.row_of(doc("b", practice=True)))
        self.assertIsNone(lb.row_of(doc("c", autopilot_used=True)))
        self.assertIsNone(lb.row_of(doc("d", student="")))
        self.assertIsNone(lb.row_of(doc("e", status="stopped")))

    def test_rank_and_tie_breaks(self):
        rows = [lb.row_of(d) for d in [
            doc("low", student="Lo", score=88, findings=[("major", "x"), ("major", "y")]),
            doc("top_slow", student="B", minutes=55),
            doc("top_fast", student="A", minutes=48),
            doc("top_fewer_callouts", student="C", made=10, minutes=40),
            doc("top_less_in_range", student="D", map_in=80, minutes=30),
            doc("top_with_finding", student="E", score=100, findings=[("minor", "z")], minutes=20),
        ]]
        order = [r["id"] for r in lb.board(rows)["rows"]]
        self.assertEqual(order, ["top_fast", "top_slow", "top_fewer_callouts", "top_less_in_range", "top_with_finding", "low"])
        b = lb.board(rows, student="lo")
        self.assertEqual((b["best"]["rank"], b["runs"], b["total"]), (6, 1, 6))

    def test_filters(self):
        rows = [lb.row_of(doc("a", persona="ckd", ts=5.0)), lb.row_of(doc("b", ts=lb.today_ts() + 60))]
        self.assertEqual([r["id"] for r in lb.board(rows, persona="ckd")["rows"]], ["a"])
        self.assertEqual([r["id"] for r in lb.board(rows, since_ts=lb.today_ts())["rows"]], ["b"])

    def test_names_are_cleaned(self):
        self.assertEqual(lb.clean_name("  <b>Ana</b>   Lee\n"), "bAna/b Lee")
        self.assertEqual(len(lb.clean_name("x" * 80)), 24)
        self.assertEqual(lb.clean_name(None), "")

    def test_levels_unlock_in_order(self):
        self.assertEqual([l["unlocked"] for l in lb.levels([], "Ana")], [True, False, False, False])
        rows = [lb.row_of(doc("a", score=65))]
        self.assertFalse(lb.levels(rows, "Ana")[1]["unlocked"])                 # below the pass score
        rows = [lb.row_of(doc("a", score=90, findings=[("critical", "air_embolism")]))]
        self.assertFalse(lb.levels(rows, "Ana")[1]["unlocked"])                 # a critical never passes
        rows = [lb.row_of(doc("a", score=84))]
        lv = lb.levels(rows, "ana")
        self.assertEqual([l["unlocked"] for l in lv], [True, True, False, False])
        self.assertEqual(lv[0]["best"], {"standard_adult": 84})
        self.assertFalse(lb.levels(rows, "Someone else")[1]["unlocked"])
        every = {p for l in lb.LEVELS for p in l["personas"]}
        from perfusion.model import load_personas
        self.assertEqual(every, set(load_personas()))                           # every patient sits in exactly one level


class TestQuiz(unittest.TestCase):
    def test_quiz_follows_the_runs_findings_and_is_fixed(self):
        d = doc("20261127-090000-standard_adult", findings=[("minor", "gradient"), ("critical", "protamine_on_bypass"), ("major", "csp_high")])
        ids = quiz.pick(d)
        self.assertEqual(ids[:3], ["protamine_when", "csp_limit", "gradient"])     # worst finding first
        self.assertEqual(len(ids), 4)
        self.assertEqual(ids, quiz.pick(d))
        self.assertNotIn("answer", quiz.questions(d)[0])                           # answers never go to the client

    def test_grading(self):
        d = doc("20261127-090000-standard_adult")
        ids = quiz.pick(d)
        right = [quiz.BY_ID[i]["answer"] for i in ids]
        self.assertEqual(quiz.grade(d, right)["score"], 4)
        self.assertEqual(quiz.grade(d, [9, "x"])["score"], 0)
        self.assertEqual(quiz.grade(d, [])["total"], 4)

    def test_bank_is_well_formed(self):
        from perfusion import model, scenario
        from pathlib import Path
        src = Path(model.__file__).read_text() + Path(scenario.__file__).read_text()
        for b in quiz.BANK:
            self.assertEqual(len(b["options"]), 4)
            self.assertTrue(0 <= b["answer"] < 4)
            for tag in b["tags"]:
                self.assertIn(f'"{tag}"', src, f"quiz tag {tag} is not a finding code the simulator can raise")
        self.assertEqual(len(quiz.BY_ID), len(quiz.BANK))


class TestServerSide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = Session(saves_dir=os.path.join(self.tmp.name, "saves"), logs_dir=os.path.join(self.tmp.name, "logs"))

    def tearDown(self):
        self.tmp.cleanup()

    def finish(self, student, autopilot=True):
        self.s.reset("standard_adult", student=student)
        with self.s.lock:
            self.s.case.autopilot = autopilot
            for _ in range(400):
                self.s.advance(1000)
                if self.s.case.phase == "DONE":
                    break
        return self.s.log.id

    def test_student_and_series_are_logged(self):
        sid = self.finish("  Ana <Lee> ")
        d = self.s.session_detail(sid)
        self.assertEqual(d["student"], "Ana Lee")
        self.assertEqual(self.s.state()["session"]["student"], "Ana Lee")
        self.assertEqual(d["series_keys"], list(SERIES_KEYS))
        self.assertGreater(len(d["series"]), 400)                       # one row per 5 s of a 50 minute case
        self.assertTrue(all(len(r) == len(SERIES_KEYS) for r in d["series"]))
        rpm = [r[2] for r in d["series"]]
        self.assertGreater(max(rpm), 2500)
        self.assertEqual(d["status"], "complete")

    def test_autopilot_runs_stay_off_the_board_and_a_hand_flown_run_goes_on(self):
        sid = self.finish("Ana")
        self.assertEqual(self.s.leaderboard(student="Ana")["total"], 0)       # the expert flew it
        path = os.path.join(self.s.sessions.folder, sid + ".json")
        with open(path) as f:
            d = json.load(f)
        d["autopilot_used"] = False; d["id"] = sid[:-1] + "x"                 # the same run, flown by hand
        with open(os.path.join(self.s.sessions.folder, d["id"] + ".json"), "w") as f:
            json.dump(d, f)
        b = self.s.leaderboard(student="Ana")
        self.assertEqual((b["total"], b["best"]["rank"], b["best"]["score"]), (1, 1, 100))
        self.assertTrue(b["levels"][1]["unlocked"])
        with self.assertRaises(ApiError):
            self.s.leaderboard(persona="nope")

    def test_quiz_is_one_attempt_and_stored(self):
        sid = self.finish("Ana")
        q = self.s.quiz_get(sid)
        self.assertEqual(len(q["questions"]), 4)
        r1 = self.s.quiz_post(sid, [0, 0, 0, 0])["result"]
        r2 = self.s.quiz_post(sid, [1, 1, 1, 1])
        self.assertTrue(r2["already"]); self.assertEqual(r2["result"], r1)
        self.s.reset("ckd", student="Ana")                                # the finished run is now only on disk
        self.assertEqual(self.s.quiz_get(sid)["result"], r1)
        with self.assertRaises(ApiError):
            self.s.quiz_get(self.s.log.id)                                # not finished yet


if __name__ == "__main__":
    unittest.main()
