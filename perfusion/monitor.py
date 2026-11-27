"""What the /dashboard page shows: simulator speed, AI services, the machine, the build. Standard library only.

Every reading is wrapped so that a missing file, a missing program or a service that is down shows up as
"not running" or "unavailable" on the page instead of an error. Slow readings (nvidia-smi, the services'
/health endpoints) are refreshed by a background thread, so a dashboard request never waits on them.
"""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_STATUS = os.path.join(ROOT, "logs", "last_test.json")

# The local AI services. Each one runs on its own (see voice/) and answers GET /health with JSON such as
#   {"model": "...", "loaded": true, "memory_mb": 1234, "latency_ms": 85, "tokens_per_s": 40,
#    "requests": 12, "last_error": null}
# Override a URL with an environment variable, for example PERFUSION_ASR_URL=http://127.0.0.1:9301
SERVICES = [
    dict(id="asr", label="Speech recognition (ASR)", port=9201),
    dict(id="surgeon", label="Surgeon LLM", port=9202),
    dict(id="medical", label="Medical LLM (info button)", port=9203),
    dict(id="tts", label="Voice (TTS)", port=9204),
]
HEALTH_FIELDS = ("model", "loaded", "memory_mb", "latency_ms", "tokens_per_s", "requests", "last_error")


def service_url(svc):
    return os.environ.get(f"PERFUSION_{svc['id'].upper()}_URL", f"http://127.0.0.1:{svc['port']}").rstrip("/")


def probe(svc, timeout=0.5):
    """One service's row. Never raises."""
    row = probe_placeholder(svc)
    url = row["url"]
    try:
        with urllib.request.urlopen(url + "/health", timeout=timeout) as r:
            data = json.loads(r.read(65536) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("health reply is not a JSON object")
    except urllib.error.HTTPError as e:                  # something answers, but not with a health reply
        row.update(status="error", last_error=f"/health answered HTTP {e.code}")
        return row
    except ValueError as e:                              # bad JSON
        row.update(status="error", last_error=f"bad /health reply: {e}"[:200])
        return row
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        if not isinstance(reason, ConnectionRefusedError):
            row.update(status="not responding", detail=str(reason)[:120])
        return row
    for k in HEALTH_FIELDS:
        v = data.get(k)
        row[k] = v if isinstance(v, (str, int, float, bool)) or v is None else str(v)[:200]
    row["status"] = "loaded" if data.get("loaded") else "loading"
    return row


# ---- the machine ------------------------------------------------------------------------------
def read_meminfo(path="/proc/meminfo"):
    out = {}
    with open(path) as f:
        for line in f:
            k, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                out[k] = int(parts[0])            # kB
    total, avail = out["MemTotal"], out.get("MemAvailable", out.get("MemFree", 0))
    return dict(total_gb=round(total / 1048576, 1), used_gb=round((total - avail) / 1048576, 1),
                available_gb=round(avail / 1048576, 1), used_pct=round(100 * (total - avail) / total, 1))


def read_cpu_times(path="/proc/stat"):
    with open(path) as f:
        parts = f.readline().split()
    vals = [int(x) for x in parts[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals), idle


def cpu_percent(prev, cur):
    dt, di = cur[0] - prev[0], cur[1] - prev[1]
    return round(100.0 * (dt - di) / dt, 1) if dt > 0 else None


def parse_nvidia_smi(text):
    """Rows of 'name, util, temp, mem used, mem total, power' -> list of dicts. [N/A] becomes None."""
    def num(s):
        s = s.strip()
        try:
            return float(s)
        except ValueError:
            return None
    gpus = []
    for line in text.strip().splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 6:
            continue
        gpus.append(dict(name=f[0], util_pct=num(f[1]), temp_c=num(f[2]), mem_used_mb=num(f[3]),
                         mem_total_mb=num(f[4]), power_w=num(f[5])))
    return gpus


def query_gpu(timeout=3):
    exe = shutil.which("nvidia-smi")
    if not exe:
        return dict(available=False, error="nvidia-smi not found")
    try:
        r = subprocess.run([exe, "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(available=False, error=str(e)[:200])
    if r.returncode != 0:
        return dict(available=False, error=(r.stderr or r.stdout).strip()[:200])
    return dict(available=True, gpus=parse_nvidia_smi(r.stdout))


def read_test_status(path=TEST_STATUS):
    try:
        with open(path) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


class SimMeter:
    """Rolling steps/s, real-time factor and tick lag, fed by the server loop."""
    WINDOW = 3.0

    def __init__(self):
        self.lock = threading.Lock()
        self.samples = deque()                 # (wall, steps_total, sim_seconds_total, tick_lag_s)
        self.steps = 0
        self.sim_s = 0.0

    def record(self, wall, steps, dt, lag):
        with self.lock:
            self.steps += steps
            self.sim_s += steps * dt
            self.samples.append((wall, self.steps, self.sim_s, lag))
            while self.samples and wall - self.samples[0][0] > self.WINDOW:
                self.samples.popleft()

    def read(self):
        with self.lock:
            s = list(self.samples)
        if len(s) < 2 or s[-1][0] <= s[0][0]:
            return dict(steps_per_s=None, real_time_factor=None, tick_lag_ms=None, steps_total=self.steps)
        span = s[-1][0] - s[0][0]
        lags = [x[3] for x in s]
        return dict(steps_per_s=round((s[-1][1] - s[0][1]) / span, 1),
                    real_time_factor=round((s[-1][2] - s[0][2]) / span, 2),
                    tick_lag_ms=round(1000 * sum(lags) / len(lags), 1),
                    tick_lag_max_ms=round(1000 * max(lags), 1), steps_total=self.steps)


class Clients:
    """Browsers that polled /api/state in the last few seconds."""
    TTL = 5.0

    def __init__(self):
        self.lock = threading.Lock()
        self.seen = {}

    def touch(self, key, now=None):
        with self.lock:
            self.seen[key] = now if now is not None else time.monotonic()

    def count(self, now=None):
        now = now if now is not None else time.monotonic()
        with self.lock:
            for k in [k for k, t in self.seen.items() if now - t > self.TTL]:
                del self.seen[k]
            return len(self.seen)


class Monitor:
    """Background refresh of the slow readings; snapshot() is cheap and never raises."""

    def __init__(self, interval=1.0, services=SERVICES):
        self.interval, self.services = interval, services
        self.lock = threading.Lock()
        self.cache = dict(services=[probe_placeholder(s) for s in services], gpu=dict(available=False, error="starting"))
        self._cpu_prev = None
        self._gpu_at = 0.0
        self.started = time.time()

    def refresh_once(self):
        rows = []
        for s in self.services:
            try:
                rows.append(probe(s))
            except Exception as e:                      # a bad service must not stop the others
                r = probe_placeholder(s)
                r.update(status="error", last_error=str(e)[:200])
                rows.append(r)
        gpu = None
        if time.monotonic() - self._gpu_at > 2.0:
            self._gpu_at = time.monotonic()
            try:
                gpu = query_gpu()
            except Exception as e:
                gpu = dict(available=False, error=str(e)[:200])
        with self.lock:
            self.cache["services"] = rows
            if gpu is not None:
                self.cache["gpu"] = gpu

    def run(self):
        while True:
            self.refresh_once()
            time.sleep(self.interval)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
        return self

    def system(self):
        out = {}
        try:
            cur = read_cpu_times()
            out["cpu_pct"] = cpu_percent(self._cpu_prev, cur) if self._cpu_prev else None
            self._cpu_prev = cur
        except (OSError, ValueError, IndexError):
            out["cpu_pct"] = None
        out["cpu_count"] = os.cpu_count()
        try:
            out["load"] = [round(x, 2) for x in os.getloadavg()]
        except OSError:
            out["load"] = None
        try:
            out["memory"] = read_meminfo()
        except (OSError, ValueError, KeyError, ZeroDivisionError):
            out["memory"] = None
        try:
            du = shutil.disk_usage(ROOT)
            out["disk"] = dict(path=ROOT, total_gb=round(du.total / 1e9, 1), used_gb=round(du.used / 1e9, 1),
                               free_gb=round(du.free / 1e9, 1), used_pct=round(100 * du.used / du.total, 1))
        except OSError:
            out["disk"] = None
        with self.lock:
            out["gpu"] = self.cache["gpu"]
        return out

    def snapshot(self, sim=None, build=None, features=None):
        def safe(fn):
            try:
                return fn()
            except Exception as e:                      # the page must never break
                return dict(error=str(e)[:200])
        with self.lock:
            services = [dict(r) for r in self.cache["services"]]
        return dict(time=time.time(), uptime_s=round(time.time() - self.started),
                    sim=safe(sim) if sim else None, services=services, system=safe(self.system),
                    build=dict(version=build or {}, tests=read_test_status(), features=features or []))


def probe_placeholder(svc):
    url = service_url(svc)
    try:
        port = urllib.parse.urlsplit(url).port or svc["port"]
    except ValueError:
        port = None
    row = dict(id=svc["id"], label=svc["label"], url=url, port=port, status="not running")
    row.update({k: None for k in HEALTH_FIELDS})
    return row
