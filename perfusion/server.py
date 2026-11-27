"""Zero-dependency server: runs the simulation and serves the 3D client.

    python3 -m perfusion.server --port 8080

One shared session (single student) for now. State is polled at ~10 Hz as JSON,
actions are POSTed. Everything is Python standard library so it installs
anywhere, including aarch64 DGX Spark, with no pip step.
"""
import argparse
import json
import mimetypes
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .autopilot import Autopilot
from .model import load_personas
from .scenario import CALLOUTS, PHASES, PHASE_TITLES, Case

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
TICK = 0.05


class Session:
    def __init__(self):
        self.personas = load_personas()
        self.lock = threading.Lock()
        self.reset("standard_adult")

    def reset(self, persona_id, operate_minutes=22.0, mistake=None):
        with self.lock:
            self.case = Case(self.personas[persona_id], operate_minutes=float(operate_minutes))
            self.pilot = Autopilot(self.case, mistake=mistake)
            self.case.speed = 0.0          # paused until the student presses start
            self.debt = 0.0

    def loop(self):
        last = time.monotonic()
        while True:
            time.sleep(TICK)
            now = time.monotonic()
            real, last = min(now - last, 0.25), now
            with self.lock:
                case = self.case
                self.debt += real * case.speed / case.sim.DT
                n = int(self.debt)
                self.debt -= n
                for _ in range(min(n, 2000)):
                    if case.autopilot:
                        self.pilot.step()
                    case.tick()

    def state(self):
        with self.lock:
            return self.case.snapshot()

    def act(self, a):
        with self.lock:
            self.case.action(a)


SESSION = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._send(200, SESSION.state())
        if path == "/api/meta":
            return self._send(200, dict(
                personas=[dict(id=p.id, name=p.name, desc=p.desc, weight=p.weight, height=p.height,
                               hct=round(p.hct * 100)) for p in SESSION.personas.values()],
                callouts=[dict(id=i, label=l) for i, l in CALLOUTS],
                phases=[dict(id=p, title=PHASE_TITLES[p]) for p in PHASES]))
        rel = "index.html" if path == "/" else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
            return self._send(404, dict(error="not found"))
        with open(full, "rb") as f:
            self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 65536:
                return self._send(413, dict(error="too large"))
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/action":
                SESSION.act(body)
            elif self.path == "/api/reset":
                pid = body.get("persona", "standard_adult")
                if pid not in SESSION.personas:
                    return self._send(400, dict(error="unknown persona"))
                SESSION.reset(pid, body.get("operate_minutes", 22.0), body.get("mistake"))
            else:
                return self._send(404, dict(error="not found"))
            self._send(200, dict(ok=True))
        except Exception as e:      # bad input should never kill the session
            self._send(400, dict(error=str(e)))


def main():
    global SESSION
    ap = argparse.ArgumentParser(description="perfusion1 simulator server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--open", action="store_true", help="open a browser on this machine")
    a = ap.parse_args()
    SESSION = Session()
    threading.Thread(target=SESSION.loop, daemon=True).start()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    url = f"http://localhost:{a.port}"
    print(f"perfusion1 running. Open {url} (or http://<this machine's IP>:{a.port} from another device).")
    if a.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
