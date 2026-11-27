"""The H info panel guide, the extended debrief data and the vitals trend log.
Run with:  python3 -m unittest discover -s tests -v"""
import json, os, re, shutil, sys, tempfile, threading, unittest, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from perfusion import server
from perfusion.guide import GUIDE, guide
from perfusion.model import load_personas
from perfusion.scenario import EXPECTED, PENALTY, PHASES, Case
from perfusion.server import VITALS_EVERY, Session, expert_benchmark

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
P = load_personas()


def read(rel):
    with open(os.path.join(ROOT, rel)) as f:
        return f.read()


class TestGuide(unittest.TestCase):
    def test_every_phase_has_a_guide(self):
        self.assertEqual(set(GUIDE), set(PHASES))
        for p in PHASES:
            if p != "DONE":
                self.assertTrue(GUIDE[p]["why"] and GUIDE[p]["where"] and GUIDE[p]["watch"], p)

    def test_guide_names_real_panels_and_hud_values(self):
        panels = set(re.findall(r"^\s{4}(\w+): \{ title:", read("web/panels.js"), re.M))
        vitals = set(re.findall(r"^\s+\['([^']+)', \(S\)", read("web/main.js"), re.M))
        self.assertIn("pump", panels); self.assertIn("MAP", vitals)
        for p, g in GUIDE.items():
            self.assertLessEqual(set(g["where"]), panels, p)
            self.assertLessEqual(set(g["watch"]), vitals, p)

    def test_guide_uses_the_case_objectives_and_callouts(self):
        for pid in ("standard_adult", "small_anemic"):
            case = Case(P[pid])
            g = guide(case)
            self.assertEqual(g["penalty"], PENALTY)
            self.assertEqual([x["id"] for x in g["phases"]], PHASES)
            for x in g["phases"]:
                self.assertEqual(x["objectives"], case.objectives(x["id"]))
                self.assertEqual(x["callout"]["id"] if x["callout"] else None, EXPECTED.get(x["id"]))
            json.dumps(g)

    def test_reading_the_guide_never_changes_the_case(self):
        case = Case(P["standard_adult"])
        before = json.dumps(case.snapshot(), sort_keys=True)
        guide(case)
        self.assertEqual(json.dumps(case.snapshot(), sort_keys=True), before)


class TestBenchmark(unittest.TestCase):
    def test_expert_benchmark_for_a_patient(self):
        b = expert_benchmark("standard_adult")
        self.assertTrue(b["available"])
        self.assertEqual(b["score"], 100)
        self.assertGreater(b["runs"], 0)
        self.assertIn("not clinical", b["note"].lower())

    def test_missing_or_broken_benchmark(self):
        self.assertFalse(expert_benchmark("nobody")["available"])
        tmp = tempfile.mkdtemp()
        try:
            for text in ("{", "[]", '{"a": 1}', '[{"persona": "x", "band": "expert", "finished": true}]'):
                p = os.path.join(tmp, "b.json")
                with open(p, "w") as f:
                    f.write(text)
                self.assertFalse(expert_benchmark("x", path=p)["available"], text)
            self.assertFalse(expert_benchmark("x", path=os.path.join(tmp, "none.json"))["available"])
        finally:
            shutil.rmtree(tmp)


class TestDebriefData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1guide-")
        self.s = Session(saves_dir=os.path.join(self.tmp, "s"), logs_dir=os.path.join(self.tmp, "l"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_expert(self, mistake=None):
        s = self.s
        s.reset("standard_adult", mistake=mistake)
        s.act(dict(type="autopilot", on=True))
        with s.lock:
            for _ in range(400):
                s.advance(500)
                if s.case.phase == "DONE":
                    break
        return s.session_detail(s.log.id)

    def test_vitals_are_logged_every_15_seconds(self):
        doc = self.run_expert()
        v = [e for e in doc["events"] if e["kind"] == "vitals"]
        self.assertGreater(len(v), 150)                      # a 50-minute case
        gaps = [b["t"] - a["t"] for a, b in zip(v, v[1:])]
        self.assertTrue(all(VITALS_EVERY - 0.15 <= g <= VITALS_EVERY + 0.15 for g in gaps), (min(gaps), max(gaps)))
        self.assertTrue(all(k in v[50] for k in ("map", "flow", "do2i", "temp", "hct", "on_bypass", "phase")))
        self.assertTrue(any(e["on_bypass"] for e in v) and not v[0]["on_bypass"])

    def test_vitals_alone_do_not_make_a_session_worth_keeping(self):
        s = self.s
        s.act(dict(type="speed", x=1))
        with s.lock:
            s.advance(5000)                                  # 100 s of an untouched case
        self.assertTrue(any(e["kind"] == "vitals" for e in s.log.doc["events"]))
        self.assertFalse(s.log.active)

    def test_summary_phases_agree_with_the_score(self):
        for mistake in (None, "flow_up_early"):
            doc = self.run_expert(mistake)
            sc = doc["final"]
            phases = [p for p in doc["summary"]["phases"] if p["callout"]]
            self.assertEqual(sum(p["called"] for p in phases), sc["callouts"]["made"], mistake)
            self.assertEqual(sum(len(p["findings"]) for p in doc["summary"]["phases"]), len(sc["findings"]), mistake)
            # the score is exactly 100 minus the per-finding deductions the debrief shows
            self.assertEqual(sc["score"], max(0, round(100 - sum(PENALTY[f["sev"]] for f in sc["findings"]))))

    def test_expert_still_scores_100_with_the_trend_log(self):
        doc = self.run_expert()
        self.assertEqual((doc["final"]["score"], doc["final"]["critical"]), (100, 0))


class TestHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1guide-")
        server.SESSION = Session(saves_dir=os.path.join(self.tmp, "s"), logs_dir=os.path.join(self.tmp, "l"))
        self.srv = server.bind("127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return json.loads(r.read())

    def test_guide_and_benchmark_endpoints(self):
        g = self.get("/api/guide")
        self.assertEqual(len(g["phases"]), len(PHASES))
        self.assertTrue(g["phases"][0]["objectives"][0].startswith("Give heparin"))
        self.assertTrue(self.get("/api/benchmark?persona=standard_adult")["available"])
        self.assertFalse(self.get("/api/benchmark?persona=%3Cx%3E")["available"])
        self.assertFalse(self.get("/api/benchmark")["available"])


if __name__ == "__main__":
    unittest.main()
