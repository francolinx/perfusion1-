"""Save and load a running case exactly, as plain JSON files. Standard library only.

A save holds every attribute of the Case, its Sim and the expert Autopilot, so loading it and
running on gives the same numbers as never having stopped. Python floats survive JSON exactly
(repr round-trips), and sets and tuples are tagged so they come back as the same types.
"""
import json
import os
import re
import time
from dataclasses import asdict

from .autopilot import Autopilot
from .model import Persona, Sim
from .scenario import PHASE_TITLES, Case, new_clocks

FORMAT = 1
AUTO_KEEP = 10
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---- build version, read from .git without needing the git program -------------------------
def build_version(root=ROOT):
    """{'commit': short sha or 'unknown', 'branch': name or ''}."""
    git = os.path.join(root, ".git")
    try:
        if os.path.isfile(git):                       # worktree: ".git" is a file pointing elsewhere
            with open(git) as f:
                git = os.path.join(root, f.read().split(":", 1)[1].strip())
        with open(os.path.join(git, "HEAD")) as f:
            head = f.read().strip()
        if not head.startswith("ref:"):
            return dict(commit=head[:7], branch="")
        ref = head[4:].strip()
        common = git
        if os.path.isfile(os.path.join(git, "commondir")):
            with open(os.path.join(git, "commondir")) as f:
                common = os.path.normpath(os.path.join(git, f.read().strip()))
        for base in (git, common):
            p = os.path.join(base, ref)
            if os.path.isfile(p):
                with open(p) as f:
                    return dict(commit=f.read().strip()[:7], branch=ref.rsplit("/", 1)[-1] if ref.startswith("refs/heads/") else ref)
        with open(os.path.join(common, "packed-refs")) as f:
            for line in f:
                if line.rstrip().endswith(" " + ref):
                    return dict(commit=line[:7], branch=ref[len("refs/heads/"):])
    except (OSError, IndexError):
        pass
    return dict(commit="unknown", branch="")


# ---- exact state <-> JSON -------------------------------------------------------------------
def _enc(v):
    if isinstance(v, set):
        return {"__set__": sorted((_enc(x) for x in v), key=repr)}
    if isinstance(v, tuple):
        return {"__tuple__": [_enc(x) for x in v]}
    if isinstance(v, list):
        return [_enc(x) for x in v]
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise TypeError("only string keys can be saved")
        if "__set__" in v or "__tuple__" in v:
            raise TypeError("reserved key in saved state")
        return {k: _enc(x) for k, x in v.items()}
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    raise TypeError(f"cannot save a value of type {type(v).__name__}")


def _dec(v):
    if isinstance(v, list):
        return [_dec(x) for x in v]
    if isinstance(v, dict):
        if set(v) == {"__set__"}:
            return set(_dec(x) for x in v["__set__"])
        if set(v) == {"__tuple__"}:
            return tuple(_dec(x) for x in v["__tuple__"])
        return {k: _dec(x) for k, x in v.items()}
    return v


# model fields added after saves were first written (lab console and monitor). A save without them still loads,
# with the field at its starting value; new controls are merged in the same way. Anything else missing is refused.
_BACKFILL_SIM = {"t_cp_water", "urine_ml", "urine_rate", "q_suck", "q_vent", "last_act2"}
# case fields added since (student timers): older saves start with the timers reset and nothing reported
_BACKFILL_CASE = dict(clocks=new_clocks, clock_log=list, reports=list)

# object references that are rebuilt on load instead of stored
_SKIP = {"case": {"sim", "persona"}, "sim": {"p"}, "pilot": {"case", "on_act"}}


def _attrs(obj, part):
    out = {}
    for k, v in vars(obj).items():
        if k in _SKIP[part]:
            continue
        try:
            out[k] = _enc(v)
        except TypeError as e:
            raise TypeError(f"{part}.{k}: {e}") from None
    return out


def capture(case, pilot):
    """Everything needed to rebuild this exact moment of the case."""
    return dict(persona=asdict(case.persona), case=_attrs(case, "case"), sim=_attrs(case.sim, "sim"),
                pilot=_attrs(pilot, "pilot"))


def restore(state):
    """Build a new (case, pilot) from capture() output. Raises ValueError if the data does not fit."""
    try:
        persona = Persona(**state["persona"])
        case = Case.__new__(Case)
        sim = Sim.__new__(Sim)
        pilot = Autopilot.__new__(Autopilot)
        for obj, part in ((case, "case"), (sim, "sim"), (pilot, "pilot")):
            fresh = vars(Sim(persona)) if part == "sim" else None
            data = {k: _dec(v) for k, v in state[part].items()}
            if fresh is not None:
                for k in _BACKFILL_SIM - set(data):      # older saves: fields added since get their starting values
                    data[k] = fresh[k]
                if isinstance(data.get("c"), dict):
                    data["c"] = {**fresh["c"], **data["c"]}
                missing = set(fresh) - set(data) - _SKIP["sim"]
                if missing:
                    raise ValueError("the save is missing model fields: " + ", ".join(sorted(missing)))
            if part == "case":
                for k, make in _BACKFILL_CASE.items():
                    data.setdefault(k, make())
            vars(obj).update(data)
        sim.p = persona
        case.sim, case.persona = sim, persona
        pilot.case = case
        pilot.on_act = None
        if case.phase not in PHASE_TITLES:
            raise ValueError(f"unknown phase {case.phase!r}")
        case.snapshot()                                 # fail now, not in the next poll, if anything is off
        return case, pilot
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"save does not match this version of the simulator ({type(e).__name__}: {e})") from None


# ---- the saves/ folder ----------------------------------------------------------------------
def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    return s or "save"


class SaveStore:
    def __init__(self, folder=os.path.join(ROOT, "saves"), build=None):
        self.folder = folder
        self.build = build or build_version()

    def _path(self, sid):
        if not ID_RE.match(sid or ""):
            raise ValueError("bad save id")
        return os.path.join(self.folder, sid + ".json")

    def exists(self, sid):
        return os.path.isfile(self._path(sid))

    def write(self, sid, name, description, case, pilot, session=None, auto=False, state=None):
        """Write a save. `state` may be passed when it was captured earlier (auto-saves)."""
        os.makedirs(self.folder, exist_ok=True)
        sc = case.score()
        doc = dict(format=FORMAT, id=sid, name=name[:80], description=description[:500], auto=auto,
                   persona=dict(id=case.persona.id, name=case.persona.name),
                   phase=case.phase, phase_title=PHASE_TITLES[case.phase], case_time=round(case.t, 1),
                   score=sc["score"], critical=sc["critical"],
                   saved_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), saved_ts=time.time(),
                   build=self.build, session=session, state=state or capture(case, pilot))
        tmp = self._path(sid) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(doc, f, separators=(",", ":"))
        os.replace(tmp, self._path(sid))                  # never leave a half-written save behind
        return self.summary(doc)

    @staticmethod
    def summary(doc):
        return {k: doc.get(k) for k in ("id", "name", "description", "auto", "persona", "phase", "phase_title",
                                        "case_time", "score", "critical", "saved_at", "saved_ts", "build")}

    def read(self, sid):
        with open(self._path(sid)) as f:
            doc = json.load(f)
        if doc.get("format") != FORMAT:
            raise ValueError(f"save format {doc.get('format')} is not supported by this version")
        return doc

    def list(self):
        out = []
        if not os.path.isdir(self.folder):
            return out
        for fn in os.listdir(self.folder):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.folder, fn)) as f:
                    out.append(self.summary(json.load(f)))
            except (OSError, ValueError):
                out.append(dict(id=fn[:-5], name=fn[:-5], description="(unreadable save file)", broken=True, saved_ts=0))
        out.sort(key=lambda d: d.get("saved_ts") or 0, reverse=True)
        for d in out:
            d["same_build"] = bool(d.get("build")) and d["build"].get("commit") == self.build["commit"]
        return out

    def delete(self, sid):
        os.remove(self._path(sid))

    def autosave(self, case, pilot, state, session=None):
        """Keep the last AUTO_KEEP automatic saves, labelled 'Auto: <phase>'."""
        autos = sorted((d for d in self.list() if d.get("auto")), key=lambda d: d.get("saved_ts") or 0)
        for d in autos[:max(0, len(autos) - AUTO_KEEP + 1)]:
            try:
                self.delete(d["id"])
            except OSError:
                pass
        sid = "auto-%d-%s" % (int(time.time() * 1000), slug(case.phase))
        return self.write(sid, "Auto: " + PHASE_TITLES[case.phase], "Saved automatically at the start of the phase.",
                          case, pilot, session=session, auto=True, state=state)
