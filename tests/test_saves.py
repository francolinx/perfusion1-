"""Save / load and session logs. Run with:  python3 -m unittest discover -s tests -v"""
import json, os, shutil, sys, tempfile, threading, unittest, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from perfusion import server
from perfusion.model import load_personas
from perfusion.saves import AUTO_KEEP, capture, restore
from perfusion.server import ApiError, Session

P = load_personas()
STEPS_60S = int(60 / 0.02)


def rj(path):
    with open(path) as f:
        return json.load(f)


def wj(path, doc):
    with open(path, "w") as f:
        json.dump(doc, f)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1test-")
        self.saves, self.logs = os.path.join(self.tmp, "saves"), os.path.join(self.tmp, "logs")
        self.s = Session(saves_dir=self.saves, logs_dir=self.logs)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def play(self, until_phase=None, steps=None, persona="standard_adult", mistake=None, fresh=True):
        s = self.s
        if fresh:
            s.reset(persona, mistake=mistake)
            s.act(dict(type="autopilot", on=True))
        n = 0
        with s.lock:
            while (steps is None or n < steps) and (until_phase is None or s.case.phase != until_phase) and n < 300000:
                s.advance(500); n += 500
        return s

    def frozen(self):
        """The full observable state plus every internal field, for exact comparison."""
        with self.s.lock:
            return json.dumps(dict(snap=self.s.case.snapshot(), state=capture(self.s.case, self.s.pilot)), sort_keys=True)


class TestSaveLoad(Base):
    def test_load_reproduces_the_exact_same_run(self):
        # save mid-case, run 60 s, reload, run 60 s again: identical, field for field
        self.play(until_phase="OPERATE")
        self.play(steps=1500, fresh=False)            # well into the clamp time, autopilot driving
        self.s.save("mid case", "sixty second test")
        with self.s.lock:
            self.s.advance(STEPS_60S)
        first = self.frozen()
        self.s.load("mid-case")
        with self.s.lock:
            self.s.advance(STEPS_60S)
        second = self.frozen()
        self.assertEqual(first, second)

    def test_every_persona_round_trips_through_json(self):
        for pid in P:
            with self.subTest(persona=pid):
                self.play(steps=40000, persona=pid)   # about 13 minutes in
                with self.s.lock:
                    state = json.loads(json.dumps(capture(self.s.case, self.s.pilot)))
                    case, pilot = restore(state)
                    self.assertEqual(json.dumps(capture(case, pilot), sort_keys=True),
                                     json.dumps(capture(self.s.case, self.s.pilot), sort_keys=True))
                    for _ in range(2000):
                        for c, p in ((case, pilot), (self.s.case, self.s.pilot)):
                            p.step(); c.tick()
                    self.assertEqual(case.snapshot(), self.s.case.snapshot())

    def test_save_details_are_filled_in(self):
        self.play(until_phase="COOL")
        d = self.s.save("Before clamp", "about to cool")
        self.assertEqual(d["id"], "before-clamp")
        row = next(r for r in self.s.saves.list() if r["id"] == "before-clamp")
        for k in ("name", "description", "persona", "phase", "phase_title", "case_time", "score", "saved_at", "build"):
            self.assertIn(k, row)
        self.assertEqual(row["description"], "about to cool")
        self.assertEqual(row["persona"]["id"], "standard_adult")
        self.assertEqual(row["phase"], "COOL")
        self.assertGreater(row["case_time"], 0)
        self.assertTrue(row["same_build"])

    def test_overwrite_needs_confirmation(self):
        self.s.save("slot", "first")
        with self.assertRaises(ApiError) as cm:
            self.s.save("slot", "second")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.body["confirm"], "overwrite")
        self.assertEqual(cm.exception.body["existing"]["description"], "first")
        self.s.save("slot", "second", overwrite=True)
        self.assertEqual(self.s.saves.read("slot")["description"], "second")

    def test_save_needs_a_name(self):
        with self.assertRaises(ApiError):
            self.s.save("   ")

    def test_different_build_warns_instead_of_loading(self):
        self.play(steps=3000)
        self.s.save("old build")
        path = os.path.join(self.saves, "old-build.json")
        doc = rj(path); doc["build"] = dict(commit="0000000", branch="old"); wj(path, doc)
        before = self.s.case
        with self.assertRaises(ApiError) as cm:
            self.s.load("old-build")
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.body["confirm"], "build")
        self.assertIs(self.s.case, before)            # nothing changed until the student confirms
        self.s.load("old-build", force=True)
        self.assertIsNot(self.s.case, before)

    def test_broken_saves_never_crash_the_session(self):
        os.makedirs(self.saves, exist_ok=True)
        with open(os.path.join(self.saves, "garbage.json"), "w") as f:
            f.write("{not json")
        self.s.save("good")
        doc = rj(os.path.join(self.saves, "good.json"))
        del doc["state"]["sim"]["vr"]                 # a field this model needs
        wj(os.path.join(self.saves, "missing-field.json"), doc)
        before = self.s.case
        for sid in ("garbage", "missing-field", "does-not-exist"):
            with self.subTest(save=sid), self.assertRaises(ApiError) as cm:
                self.s.load(sid, force=True)
            self.assertIn(cm.exception.status, (400, 404))
        self.assertIs(self.s.case, before)
        self.assertTrue(any(r.get("broken") for r in self.s.saves.list()))   # listed, flagged, not fatal

    def test_bad_ids_are_rejected(self):
        for bad in ("../etc/passwd", "a/b", "", "UPPER"):
            with self.subTest(id=bad), self.assertRaises(ApiError):
                self.s.delete_save(bad)

    def test_delete(self):
        self.s.save("gone soon")
        self.s.delete_save("gone-soon")
        self.assertFalse(any(r["id"] == "gone-soon" for r in self.s.saves.list()))

    def test_autosave_every_phase_keeps_last_ten(self):
        self.play(until_phase="DONE")
        autos = [r for r in self.s.saves.list() if r["auto"]]
        self.assertEqual(len(autos), AUTO_KEEP)
        self.assertTrue(all(r["name"].startswith("Auto: ") for r in autos))
        self.assertEqual(autos[0]["phase"], "POST")   # newest first: the last phase before the debrief


class TestSessionLogs(Base):
    def test_log_records_the_whole_session(self):
        self.play(until_phase="COOL", mistake="flow_up_early")
        self.s.act(dict(type="measure", what="abg"))  # one student action among the expert's
        self.s.save("cool start")
        self.play(until_phase="DONE", fresh=False)
        sid = self.s.log.id
        doc = rj(os.path.join(self.logs, sid + ".json"))
        kinds = {e["kind"] for e in doc["events"]}
        for k in ("start", "action", "line", "phase", "finding", "save", "end"):
            self.assertIn(k, kinds)
        sources = {e["source"] for e in doc["events"] if e["kind"] == "action"}
        self.assertEqual(sources, {"student", "autopilot"})
        self.assertEqual(doc["status"], "complete")
        self.assertEqual(doc["final"]["score"], self.s.case.score()["score"])
        self.assertEqual(len(doc["final"]["checklist"]), len(self.s.case.CHECKLIST))
        self.assertTrue(all("t" in e for e in doc["events"]))
        self.assertIn("flow_up_early", [e["code"] for e in doc["events"] if e["kind"] == "finding"])
        self.assertTrue(doc["autopilot_used"])

    def test_summary_is_rule_based_and_repeatable(self):
        texts = []
        for _ in range(2):
            self.play(until_phase="DONE", persona="ckd", mistake="flow_up_early")
            doc = rj(os.path.join(self.logs, self.s.log.id + ".json"))
            texts.append(doc["summary"]["text"])
        self.assertEqual(texts[0], texts[1])
        summ = doc["summary"]
        for part in ("What was done:", "What went well:", "What was flagged:", "Three things to improve:"):
            self.assertIn(part, summ["text"])
        self.assertIn("Flow was brought back up", summ["improve"][0]["what"])
        self.assertLessEqual(len(summ["improve"]), 3)
        self.assertTrue(any(p["phase"] == "COOL" for p in summ["phases"]))

    def test_summary_agrees_with_the_grader_on_callouts(self):
        # the expert makes some callouts just after the phase changes; the grader credits those
        for pid in ("standard_adult", "small_anemic"):
            with self.subTest(persona=pid):
                self.play(until_phase="DONE", persona=pid)
                summ = rj(os.path.join(self.logs, self.s.log.id + ".json"))["summary"]
                made = self.s.case.score()["callouts"]
                self.assertEqual(made["made"], made["due"])
                self.assertNotIn("did not call", summ["text"])
                self.assertFalse([x for x in summ["improve"] if "callout" in x["what"]])

    def test_load_marks_the_session_as_practice(self):
        self.play(until_phase="COOL")
        self.s.save("practice me")
        old = self.s.log.id
        self.s.load("practice-me")
        st = self.s.state()["session"]
        self.assertTrue(st["practice"])
        self.assertEqual(st["resumed_from"]["id"], "practice-me")
        self.play(until_phase="DONE", fresh=False)
        new = rj(os.path.join(self.logs, self.s.log.id + ".json"))
        self.assertTrue(new["practice"])
        self.assertIn("Practice (resumed from save)", new["summary"]["text"])
        oldlog = rj(os.path.join(self.logs, old + ".json"))
        self.assertEqual(oldlog["end_reason"], "loaded a save")
        self.assertIn("load", [e["kind"] for e in oldlog["events"]])
        self.assertFalse(oldlog["practice"])

    def test_log_survives_flushes_from_many_threads(self):
        # the sim loop and HTTP threads flush the same log; on the Spark this raced and broke Load
        self.play(steps=3000)
        log, errors = self.s.log, []
        def hammer():
            try:
                for i in range(200):
                    log.add("action", i, source="student", action=dict(type="measure", what="abg"))
                    log.flush(force=True)
            except Exception as e:
                errors.append(e)
        ts = [threading.Thread(target=hammer) for _ in range(6)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(errors, [])
        doc = rj(os.path.join(self.logs, log.id + ".json"))
        self.assertGreaterEqual(len(doc["events"]), 1200)
        self.assertFalse([f for f in os.listdir(self.logs) if f.endswith(".tmp")])

    def test_untouched_sessions_leave_no_files(self):
        self.s.reset("ckd"); self.s.act(dict(type="speed", x=20)); self.s.reset("standard_adult")
        self.assertFalse(os.path.isdir(self.logs) and os.listdir(self.logs))

    def test_sessions_list_and_detail(self):
        self.play(until_phase="DONE")
        rows = self.s.session_list()
        self.assertEqual(rows[0]["id"], self.s.log.id)
        for k in ("started_at", "persona", "score", "case_minutes", "wall_minutes", "practice", "status"):
            self.assertIn(k, rows[0])
        d = self.s.session_detail(rows[0]["id"])
        self.assertTrue(d["summary"]["text"])
        self.assertTrue(d["events"])
        with self.assertRaises(ApiError):
            self.s.session_detail("../../etc/passwd")


class TestHttp(Base):
    def setUp(self):
        super().setUp()
        server.SESSION = self.s
        self.srv = server.bind("127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
        super().tearDown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_save_load_delete_over_http(self):
        self.s.act(dict(type="heparin", units=30000))
        self.assertEqual(self.call("POST", "/api/save", dict(name="http one", description="via api"))[0], 200)
        self.assertEqual(self.call("POST", "/api/save", dict(name="http one"))[0], 409)
        code, body = self.call("GET", "/api/saves")
        self.assertEqual(code, 200); self.assertEqual(body["saves"][0]["description"], "via api")
        self.assertEqual(self.call("POST", "/api/load", dict(id="http-one"))[0], 200)
        self.assertTrue(self.call("GET", "/api/state")[1]["session"]["practice"])
        self.assertEqual(self.call("DELETE", "/api/saves/http-one")[0], 200)
        self.assertEqual(self.call("DELETE", "/api/saves/http-one")[0], 404)
        code, body = self.call("GET", "/api/sessions")
        self.assertEqual(code, 200); self.assertTrue(body["sessions"])
        self.assertEqual(self.call("GET", "/api/sessions/" + body["sessions"][0]["id"])[0], 200)


if __name__ == "__main__":
    unittest.main()
