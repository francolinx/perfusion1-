"""Zero-dependency server: runs the simulation and serves the 3D client.

    python3 -m perfusion.server --port 8080

One shared session (single student) for now. State is polled at ~10 Hz as JSON,
actions are POSTed. Everything is Python standard library so it installs
anywhere, including aarch64 DGX Spark, with no pip step.
"""
import argparse
import errno
import json
import mimetypes
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .autopilot import Autopilot
from .model import load_personas
from .saves import SaveStore, restore, slug
from .scenario import CALLOUTS, PHASES, PHASE_TITLES, Case
from .sessionlog import SessionLog, SessionStore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
TICK = 0.05


class ApiError(Exception):
    """An error with an HTTP status and a body the client can act on (409 asks for confirmation)."""
    def __init__(self, status, **body):
        super().__init__(body.get("error", ""))
        self.status, self.body = status, body


class Session:
    def __init__(self, saves_dir=None, logs_dir=None):
        self.personas = load_personas()
        self.lock = threading.Lock()
        self.saves = SaveStore(saves_dir or os.path.join(ROOT, "saves"))
        self.sessions = SessionStore(logs_dir or os.path.join(ROOT, "logs"))
        self.log = None
        self.reset("standard_adult")

    # ---- case lifecycle ---------------------------------------------------------------------
    def _install(self, case, pilot, practice=False, resumed_from=None, reason="new case"):
        """Swap in a case and start its session log. Caller holds the lock."""
        if self.log:
            self.log.end(self.case, reason)
        self.case, self.pilot = case, pilot
        self.debt = 0.0
        self.log = SessionLog(self.sessions.folder, case.persona, self.saves.build, practice=practice, resumed_from=resumed_from)
        pilot.on_act = lambda a: self.log.add("action", self.case.t, source="autopilot", action=dict(a))
        self._seen = (case.phase, len(case.lines), len(case.findings))
        self._done_logged = case.phase == "DONE"

    def reset(self, persona_id, operate_minutes=22.0, mistake=None):
        with self.lock:
            case = Case(self.personas[persona_id], operate_minutes=float(operate_minutes))
            pilot = Autopilot(case, mistake=mistake)
            case.speed = 0.0          # paused until the student presses start
            self._install(case, pilot)
            self.log.add("start", case.t, persona=persona_id, operate_minutes=float(operate_minutes))
            self.log.add("line", case.t, text=case.lines[-1]["text"])

    def _observe(self):
        """Log what the last model step changed: phase, surgeon lines, findings. Caller holds the lock."""
        c = self.case
        phase, nl, nf = self._seen
        if len(c.lines) != nl:
            for ln in c.lines[nl:]:
                self.log.add("line", ln["t"], text=ln["text"])
        if len(c.findings) != nf:
            for f in c.findings[nf:]:
                self.log.add("finding", f["t"], code=f["code"], sev=f["sev"], msg=f["msg"], phase=f["phase"])
        if c.phase != phase:
            self.log.add("phase", c.t, to=c.phase, **{"from": phase})
            if c.phase not in ("PRE", "DONE"):
                try:
                    d = self.saves.autosave(c, self.pilot, None, session=self.log.id)
                    self.log.add("save", c.t, id=d["id"], name=d["name"], auto=True)
                except (OSError, TypeError) as e:
                    self.log.add("save_failed", c.t, error=str(e))
        self._seen = (c.phase, len(c.lines), len(c.findings))
        if c.phase == "DONE" and not self._done_logged:
            self._done_logged = True
            self.log.end(c, "case complete")

    def advance(self, n):
        """Run n model steps (the expert first, if it is driving). Caller holds the lock."""
        case = self.case
        for _ in range(n):
            if case.autopilot:
                self.pilot.step()
            case.tick()
            if case.phase != self._seen[0] or len(case.lines) != self._seen[1] or len(case.findings) != self._seen[2]:
                self._observe()

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
                self.advance(min(n, 2000))
                log = self.log
            try:
                log.flush()
            except OSError:
                pass

    def state(self):
        with self.lock:
            d = self.case.snapshot()
            d["session"] = dict(id=self.log.id, practice=self.log.doc["practice"], resumed_from=self.log.doc["resumed_from"],
                                autopilot_used=self.log.doc["autopilot_used"])
            return d

    def act(self, a):
        with self.lock:
            self.case.action(a)
            self.log.add("action", self.case.t, source="student", action=dict(a))

    # ---- saves --------------------------------------------------------------------------------
    def save(self, name, description="", overwrite=False):
        name = (name or "").strip()
        if not name:
            raise ApiError(400, error="A save needs a name.")
        sid = slug(name)
        with self.lock:
            if self.saves.exists(sid) and not overwrite:
                try:
                    old = self.saves.summary(self.saves.read(sid))
                except (OSError, ValueError):
                    old = dict(id=sid, name=name)
                raise ApiError(409, error="A save with this name already exists.", confirm="overwrite", existing=old)
            d = self.saves.write(sid, name, description or "", self.case, self.pilot, session=self.log.id)
            self.log.add("save", self.case.t, id=sid, name=d["name"], auto=False, overwrite=bool(overwrite))
        self.log.flush(force=True)
        return d

    def load(self, sid, force=False):
        try:
            doc = self.saves.read(sid)
        except FileNotFoundError:
            raise ApiError(404, error="No save with that id.")
        except (OSError, ValueError) as e:
            raise ApiError(400, error=f"That save cannot be read: {e}")
        saved_build = doc.get("build") or dict(commit="unknown", branch="")
        if saved_build.get("commit") != self.saves.build["commit"] and not force:
            raise ApiError(409, error="This save was made by a different version of the simulator.",
                           confirm="build", saved_build=saved_build, current_build=self.saves.build)
        try:
            if "state" not in doc:
                raise ValueError("the save has no case state in it")
            case, pilot = restore(doc["state"])        # build the new case before touching the running one
        except ValueError as e:
            raise ApiError(400, error=str(e))
        case.speed = 0.0                               # paused, so the student can get their bearings
        with self.lock:
            self.log.add("load", self.case.t, id=sid, name=doc["name"], left_for_save=True)
            self._install(case, pilot, practice=True, resumed_from=dict(id=sid, name=doc["name"]), reason="loaded a save")
            self.log.add("load", case.t, id=sid, name=doc["name"], phase=case.phase, saved_build=saved_build,
                         build_differs=saved_build.get("commit") != self.saves.build["commit"])
        self.log.flush(force=True)
        return self.saves.summary(doc)

    def delete_save(self, sid):
        try:
            self.saves.delete(sid)
        except FileNotFoundError:
            raise ApiError(404, error="No save with that id.")
        except ValueError as e:
            raise ApiError(400, error=str(e))

    # ---- sessions -----------------------------------------------------------------------------
    def session_list(self):
        with self.lock:
            cur = self.log.listing() if self.log.active else None
        rows = self.sessions.list()
        if cur and not any(r["id"] == cur["id"] for r in rows):
            rows.insert(0, cur)
        return rows

    def session_detail(self, sid):
        from .sessionlog import summarize
        with self.lock:
            if sid == self.log.id:
                doc = self.log.snapshot()
                if not doc["summary"]:
                    doc["summary"] = summarize(doc, objectives=self.case.objectives)
                return doc
        try:
            return self.sessions.read(sid)
        except FileNotFoundError:
            raise ApiError(404, error="No session with that id.")
        except (OSError, ValueError) as e:
            raise ApiError(400, error=str(e))


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

    def _api(self, fn, *a):
        try:
            return self._send(200, fn(*a))
        except ApiError as e:
            return self._send(e.status, e.body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._send(200, SESSION.state())
        if path == "/api/meta":
            return self._send(200, dict(
                personas=[dict(id=p.id, name=p.name, desc=p.desc, weight=p.weight, height=p.height,
                               hct=round(p.hct * 100)) for p in SESSION.personas.values()],
                callouts=[dict(id=i, label=l) for i, l in CALLOUTS],
                phases=[dict(id=p, title=PHASE_TITLES[p]) for p in PHASES],
                build=SESSION.saves.build))
        if path == "/api/saves":
            return self._send(200, dict(saves=SESSION.saves.list(), build=SESSION.saves.build))
        if path == "/api/sessions":
            return self._send(200, dict(sessions=SESSION.session_list()))
        if path.startswith("/api/sessions/"):
            return self._api(SESSION.session_detail, path[len("/api/sessions/"):])
        rel = "index.html" if path == "/" else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
            return self._send(404, dict(error="not found"))
        with open(full, "rb") as f:
            self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/saves/"):
            return self._api(lambda sid: (SESSION.delete_save(sid), dict(ok=True))[1], path[len("/api/saves/"):])
        return self._send(404, dict(error="not found"))

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
            elif self.path == "/api/save":
                return self._api(SESSION.save, body.get("name"), body.get("description", ""), bool(body.get("overwrite")))
            elif self.path == "/api/load":
                return self._api(SESSION.load, body.get("id"), bool(body.get("force")))
            else:
                return self._send(404, dict(error="not found"))
            self._send(200, dict(ok=True))
        except Exception as e:      # bad input should never kill the session
            self._send(400, dict(error=str(e)))


def bind(host, port):
    """Open the HTTP server, or exit with a plain message if the port is taken."""
    try:
        srv = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        raise SystemExit(f"Port {port} is already in use by another program. "
                         f"Start on a free port instead, for example:  PORT={port + 920} ./run.sh")
    srv.daemon_threads = True
    return srv


def main():
    global SESSION
    ap = argparse.ArgumentParser(description="perfusion1 simulator server")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--open", action="store_true", help="open a browser on this machine")
    ap.add_argument("--saves-dir", help="where saves go (default: saves/ in the repo)")
    ap.add_argument("--logs-dir", help="where session logs go (default: logs/ in the repo)")
    a = ap.parse_args()
    srv = bind(a.host, a.port)
    SESSION = Session(saves_dir=a.saves_dir, logs_dir=a.logs_dir)
    threading.Thread(target=SESSION.loop, daemon=True).start()
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
