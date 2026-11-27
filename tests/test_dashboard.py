"""The /dashboard page and its readings. Run with:  python3 -m unittest discover -s tests -v"""
import json, os, shutil, socket, sys, tempfile, threading, unittest, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from perfusion import monitor, server
from perfusion.server import Session


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


class FakeService:
    """A tiny /health server that replies with whatever body and status it is given."""
    def __init__(self, body, status=200):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                data = outer.body if isinstance(outer.body, bytes) else json.dumps(outer.body).encode()
                self.send_response(outer.status if self.path == "/health" else 404)
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        self.body, self.status = body, status
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown(); self.srv.server_close()


def svc(port, sid="asr"):
    return dict(id=sid, label=sid.upper(), port=port)


class TestServices(unittest.TestCase):
    def test_nothing_listening_shows_not_running(self):
        r = monitor.probe(svc(free_port()))
        self.assertEqual(r["status"], "not running")
        self.assertIsNone(r["model"])

    def test_health_reply_is_read(self):
        f = FakeService(dict(model="parakeet-tdt-0.6b-v2", loaded=True, memory_mb=2100, latency_ms=80.5,
                             tokens_per_s=None, requests=7, last_error=None, extra="ignored"))
        try:
            r = monitor.probe(svc(f.port))
        finally:
            f.close()
        self.assertEqual(r["status"], "loaded")
        self.assertEqual((r["model"], r["memory_mb"], r["requests"], r["port"]), ("parakeet-tdt-0.6b-v2", 2100, 7, f.port))
        self.assertNotIn("extra", r)

    def test_loading_and_errors_never_raise(self):
        cases = [(dict(model="m", loaded=False), 200, "loading"), (b"not json", 200, "error"),
                 (b"[1,2]", 200, "error"), (dict(error="x"), 500, "error"),
                 (dict(model={"nested": 1}, loaded=True, last_error=["a"]), 200, "loaded")]
        for body, status, want in cases:
            f = FakeService(body, status)
            try:
                r = monitor.probe(svc(f.port))
            finally:
                f.close()
            self.assertEqual(r["status"], want, body)
            self.assertTrue(all(isinstance(v, (str, int, float, bool, type(None))) for v in r.values()))

    def test_url_can_be_overridden(self):
        with mock.patch.dict(os.environ, {"PERFUSION_TTS_URL": "http://127.0.0.1:9999/"}):
            r = monitor.probe_placeholder(svc(9204, "tts"))
        self.assertEqual((r["url"], r["port"]), ("http://127.0.0.1:9999", 9999))


class TestSystem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1dash-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_meminfo(self):
        p = self.write("meminfo", "MemTotal:       131072000 kB\nMemFree:  1000 kB\nMemAvailable:   65536000 kB\n")
        m = monitor.read_meminfo(p)
        self.assertEqual((m["total_gb"], m["used_pct"]), (125.0, 50.0))

    def test_cpu_percent(self):
        a = monitor.read_cpu_times(self.write("s1", "cpu  100 0 100 800 0 0 0 0 0 0\n"))
        b = monitor.read_cpu_times(self.write("s2", "cpu  150 0 150 900 0 0 0 0 0 0\n"))
        self.assertEqual(monitor.cpu_percent(a, b), 50.0)
        self.assertIsNone(monitor.cpu_percent(a, a))

    def test_nvidia_smi_parsing_handles_not_available(self):
        g = monitor.parse_nvidia_smi("NVIDIA GB10, 37, 51, [N/A], [N/A], 12.34\n\ngarbage\n")
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["util_pct"], g[0]["temp_c"], g[0]["mem_used_mb"], g[0]["power_w"]), (37.0, 51.0, None, 12.34))

    def test_missing_nvidia_smi(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(monitor.query_gpu(), dict(available=False, error="nvidia-smi not found"))

    def test_snapshot_survives_every_reading_failing(self):
        m = monitor.Monitor(services=[svc(free_port())])
        with mock.patch.object(monitor, "read_meminfo", side_effect=OSError), \
             mock.patch.object(monitor, "read_cpu_times", side_effect=OSError), \
             mock.patch("shutil.disk_usage", side_effect=OSError), \
             mock.patch.object(monitor, "query_gpu", side_effect=RuntimeError("boom")):
            m.refresh_once()
            d = m.snapshot(sim=lambda: 1 / 0, build=None, features=None)
        json.dumps(d)
        self.assertIn("error", d["sim"])
        self.assertIsNone(d["system"]["memory"])
        self.assertFalse(d["system"]["gpu"]["available"])
        self.assertEqual(d["services"][0]["status"], "not running")

    def test_test_status_file(self):
        self.assertIsNone(monitor.read_test_status(os.path.join(self.tmp, "nope.json")))
        self.assertIsNone(monitor.read_test_status(self.write("bad.json", "{")))
        self.assertEqual(monitor.read_test_status(self.write("ok.json", '{"ok": true}')), {"ok": True})


class TestMeters(unittest.TestCase):
    def test_sim_meter(self):
        m = monitor.SimMeter()
        self.assertIsNone(m.read()["steps_per_s"])
        for i in range(21):                       # 20 ticks of 0.05 s, 50 steps of 0.02 s each = 20x real time
            m.record(100 + i * 0.05, 50, 0.02, 0.002)
        r = m.read()
        self.assertAlmostEqual(r["steps_per_s"], 1000, delta=1)
        self.assertAlmostEqual(r["real_time_factor"], 20, delta=0.05)
        self.assertEqual(r["tick_lag_ms"], 2.0)

    def test_clients_expire(self):
        c = monitor.Clients()
        c.touch("a", now=0); c.touch("b", now=3); c.touch("a", now=4)
        self.assertEqual(c.count(now=6), 2)
        self.assertEqual(c.count(now=8.5), 1)


class TestHttp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="p1dash-")
        server.SESSION = Session(saves_dir=os.path.join(self.tmp, "s"), logs_dir=os.path.join(self.tmp, "l"))
        self.srv = server.bind("127.0.0.1", 0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def test_dashboard_page_and_api(self):
        code, ctype, body = self.get("/dashboard")
        self.assertEqual((code, ctype), (200, "text/html"))
        self.assertIn(b"perfusion1 dashboard", body)
        self.get("/api/state?c=tab1"); self.get("/api/state?c=tab2"); self.get("/api/state?c=tab1")
        code, _, body = self.get("/api/dashboard")
        d = json.loads(body)
        self.assertEqual(d["sim"]["clients"], 2)
        self.assertEqual(d["sim"]["phase"], "PRE")
        self.assertEqual(d["sim"]["speed"], 0.0)
        self.assertEqual([s["id"] for s in d["services"]], ["asr", "surgeon", "medical", "tts"])
        self.assertIn("commit", d["build"]["version"])
        self.assertIn("dashboard", d["build"]["features"])

    def test_simulation_loop_feeds_the_meter(self):
        s = server.SESSION
        s.act(dict(type="speed", x=20))
        t = threading.Thread(target=s.loop, daemon=True); t.start()
        import time
        time.sleep(1.2)
        r = s.sim_status()
        s.stopped.set(); t.join(1)
        self.assertGreater(r["steps_per_s"], 300)       # 20x real time is 1000 steps per second
        self.assertGreater(r["real_time_factor"], 5)


if __name__ == "__main__":
    unittest.main()
