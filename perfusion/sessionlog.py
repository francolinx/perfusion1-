"""Session logs and the plain-English session summary. Standard library only.

Every session writes one JSON file under logs/: who and when, every action with its case time,
every surgeon line, phase change, finding, save and load, and the final score and checklist.
The summary is built from that log by fixed rules, so the same session always reads the same.
A language model may later polish the wording; it never changes the facts or the score.
"""
import json
import os
import re
import threading
import time

from .scenario import CALLOUTS, EXPECTED, PHASE_TITLES, PHASES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9_]+(-[0-9]+)?$")
CALLOUT_LABEL = dict(CALLOUTS)
SEV_RANK = dict(critical=0, major=1, minor=2)


def mmss(t):
    t = int(t or 0)
    return f"{t // 60}:{t % 60:02d}"


class SessionLog:
    def __init__(self, folder, persona, build, practice=False, resumed_from=None):
        self.folder = folder
        stamp = time.strftime("%Y%m%d-%H%M%S")
        sid, n = f"{stamp}-{persona.id}", 1
        while os.path.exists(os.path.join(folder, sid + ".json")):
            n += 1; sid = f"{stamp}-{persona.id}-{n}"
        self.doc = dict(id=sid, persona=dict(id=persona.id, name=persona.name, weight=persona.weight),
                        started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), started_ts=time.time(),
                        ended_at=None, ended_ts=None, status="running", end_reason=None,
                        practice=practice, resumed_from=resumed_from, autopilot_used=False, build=build,
                        case_time_start=None, case_time_end=None, final=None, events=[], summary=None)
        self.active = False          # nothing is written until the session actually starts
        self._lock = threading.Lock()  # the sim loop and HTTP threads both append and flush
        self.dirty = False
        self.last_flush = 0.0

    @property
    def id(self):
        return self.doc["id"]

    def add(self, kind, t, **kw):
        with self._lock:
            self._add(kind, t, kw)

    def _add(self, kind, t, kw):
        e = dict(t=round(t, 1), kind=kind, wall=round(time.time(), 2)); e.update(kw)
        self.doc["events"].append(e)
        if self.doc["case_time_start"] is None:
            self.doc["case_time_start"] = e["t"]
        self.doc["case_time_end"] = e["t"]
        if kind == "action" and kw.get("source") == "autopilot":
            self.doc["autopilot_used"] = True
        if kind in ("save", "load") or (kind == "action" and kw.get("action", {}).get("type") != "speed"):
            self.active = True       # a speed change alone (pause, 20x) does not make a session worth keeping
        self.dirty = True

    def flush(self, force=False):
        with self._lock:
            if not self.active or not (self.dirty or force):
                return
            if not force and time.time() - self.last_flush < 2.0:
                return
            os.makedirs(self.folder, exist_ok=True)
            path = os.path.join(self.folder, self.id + ".json")
            tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
            with open(tmp, "w") as f:
                json.dump(self.doc, f, separators=(",", ":"))
            os.replace(tmp, path)
            self.dirty, self.last_flush = False, time.time()

    def snapshot(self):
        with self._lock:
            return json.loads(json.dumps(self.doc))

    def end(self, case, reason):
        if self.doc["status"] != "running":
            return
        sc = case.score()
        self.doc.update(status="complete" if case.phase == "DONE" else "stopped", end_reason=reason,
                        ended_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), ended_ts=time.time(),
                        case_time_end=round(case.t, 1),
                        final=dict(phase=case.phase, score=sc["score"], critical=sc["critical"], checklist=sc["checklist"],
                                   callouts=sc["callouts"], map_in_range=sc["map_in_range"], do2_in_range=sc["do2_in_range"],
                                   findings=sc["findings"]))
        self.add("end", case.t, reason=reason, score=sc["score"])
        self.doc["summary"] = summarize(self.doc, objectives=case.objectives)
        self.flush(force=True)

    def listing(self):
        return listing(self.doc)


def listing(doc):
    fin = doc.get("final") or {}
    return dict(id=doc["id"], started_at=doc["started_at"], started_ts=doc["started_ts"], persona=doc["persona"],
                status=doc["status"], practice=doc["practice"], resumed_from=doc.get("resumed_from"),
                autopilot_used=doc.get("autopilot_used", False), score=fin.get("score"), phase=fin.get("phase"),
                case_minutes=round(((doc.get("case_time_end") or 0) - (doc.get("case_time_start") or 0)) / 60, 1),
                wall_minutes=round(((doc.get("ended_ts") or time.time()) - doc["started_ts"]) / 60, 1))


# ---- summary ---------------------------------------------------------------------------------
def _describe_actions(acts):
    """Turn a phase's actions into short phrases, in a fixed order."""
    out, counts = [], {}
    for a in acts:
        k = a.get("type")
        if k == "set":
            counts["set"] = counts.get("set", 0) + 1
        elif k in ("heparin", "protamine", "phenylephrine", "volume", "transfuse", "measure"):
            counts.setdefault(k, []).append(a)
    hep = counts.get("heparin", [])
    if hep:
        out.append(f"gave heparin {sum(a.get('units', 0) for a in hep):,.0f} units")
    prot = counts.get("protamine", [])
    if prot:
        out.append(f"gave protamine {sum(a.get('mg', 0) for a in prot):,.0f} mg")
    neo = counts.get("phenylephrine", [])
    if neo:
        out.append(f"gave phenylephrine {len(neo)} time{'s' * (len(neo) > 1)}")
    for kind, label in (("crystalloid", "crystalloid"), ("prbc", "red cells")):
        ml = sum(a.get("ml", 0) for a in counts.get("volume", []) if a.get("kind", "crystalloid") == kind)
        if ml:
            out.append(f"added {ml:,.0f} mL {label} to the reservoir")
    tx = sum(a.get("ml", 0) for a in counts.get("transfuse", []))
    if tx:
        out.append(f"transfused {tx:,.0f} mL from the reservoir")
    meas = counts.get("measure", [])
    for what, label in (("act", "ACT"), ("abg", "blood gas")):
        n = sum(1 for a in meas if a.get("what") == what)
        if n:
            out.append(f"ran {n} {label}{'s' * (n > 1)}")
    if counts.get("set"):
        out.append(f"made {counts['set']} control change{'s' * (counts['set'] > 1)}")
    return out


def summarize(doc, objectives=None):
    """Deterministic summary from the event log. `objectives(phase)` gives what to do in a phase."""
    ev, fin = doc["events"], doc.get("final") or {}
    phases, cur = [], None
    for e in ev:
        if e["kind"] == "phase":
            if cur:
                cur["end"] = e["t"]
            cur = dict(phase=e["to"], start=e["t"], end=None, actions=[], callouts=[], findings=[], lines=0)
            phases.append(cur)
        elif cur is None and e["kind"] in ("action", "line", "finding"):
            cur = dict(phase=e.get("phase", "PRE"), start=e["t"], end=None, actions=[], callouts=[], findings=[], lines=0)
            phases.append(cur)
        if cur is None:
            continue
        if e["kind"] == "action":
            a = e["action"]
            (cur["callouts"] if a.get("type") == "callout" else cur["actions"]).append(a)
            if a.get("type") == "callout":
                cur.setdefault("_callout_t", []).append((a, e["t"]))
        elif e["kind"] == "finding":
            cur["findings"].append(e)
        elif e["kind"] == "line":
            cur["lines"] += 1
    if cur:
        cur["end"] = doc.get("case_time_end")

    # a callout counts for a phase if it was made in that phase, or in the first 20 s of the next one:
    # the same rule the grader uses (scenario.Case.action), so the summary never disagrees with the score
    for i, p in enumerate(phases):
        said = [c.get("id") for c in p["callouts"]]
        if i + 1 < len(phases):
            nxt = phases[i + 1]
            said += [c.get("id") for c, e in nxt.get("_callout_t", []) if e - nxt["start"] < 20]
        p["said"] = said

    phase_text = []
    for p in phases:
        if p["phase"] == "DONE":
            continue
        title = PHASE_TITLES.get(p["phase"], p["phase"])
        bits = _describe_actions(p["actions"])
        exp = EXPECTED.get(p["phase"])
        if exp:
            bits.append(f"called \"{CALLOUT_LABEL[exp]}\"" if exp in p["said"] else f"did not call \"{CALLOUT_LABEL[exp]}\"")
        if p["findings"]:
            bits.append(f"{len(p['findings'])} problem{'s' * (len(p['findings']) > 1)} flagged")
        else:
            bits.append("nothing flagged")
        phase_text.append(dict(phase=p["phase"], title=title, start=p["start"], end=p["end"],
                               text=f"{title} ({mmss(p['start'])} to {mmss(p['end'])}): " + "; ".join(bits) + "."))

    findings = fin.get("findings") or [dict(code=e["code"], sev=e["sev"], msg=e["msg"], t=e["t"], phase=e["phase"]) for e in ev if e["kind"] == "finding"]
    checklist = fin.get("checklist") or []
    callouts = fin.get("callouts") or dict(made=0, due=0)
    went_well = []
    if fin:
        if fin.get("critical") == 0:
            went_well.append("No critical errors.")
        done = [c["label"] for c in checklist if c["done"]]
        if done:
            went_well.append(f"Checklist: {len(done)} of {len(checklist)} items done.")
        if callouts["due"] and callouts["made"] == callouts["due"]:
            went_well.append(f"Every closed-loop callout made ({callouts['made']} of {callouts['due']}).")
        if fin.get("map_in_range", 0) >= 90:
            went_well.append(f"Pressure held in range {fin['map_in_range']}% of bypass time.")
        if fin.get("do2_in_range", 0) >= 90:
            went_well.append(f"Oxygen delivery on target {fin['do2_in_range']}% of bypass time.")
    clean = [p["title"] for p in phase_text if p["text"].endswith("nothing flagged.")]
    if clean:
        went_well.append("Clean phases: " + ", ".join(clean) + ".")

    flagged = [f"{mmss(f['t'])} in {PHASE_TITLES.get(f['phase'], f['phase'])} ({f['sev']}): {f['msg']}" for f in findings]

    # three things to improve: worst findings first (one per kind), then missed checklist items,
    # then missed callouts, then time out of range
    improve, seen = [], set()
    for f in sorted(findings, key=lambda f: (SEV_RANK.get(f["sev"], 3), f["t"])):
        if f["code"] in seen:
            continue
        seen.add(f["code"])
        how = "; ".join(objectives(f["phase"])) if objectives else ""
        improve.append(dict(what=f"{f['msg']} ({f['sev']}, {mmss(f['t'])}, {PHASE_TITLES.get(f['phase'], f['phase'])})",
                            how=f"What that step asks for: {how}." if how else ""))
    for c in checklist:
        if not c["done"]:
            improve.append(dict(what=f"Checklist item not done: {c['label']}.", how=""))
    for p in phases:
        exp = EXPECTED.get(p["phase"])
        if exp and exp not in p["said"] and p["end"] is not None:
            improve.append(dict(what=f"Missed the callout \"{CALLOUT_LABEL[exp]}\" in {PHASE_TITLES[p['phase']]}.",
                                how="Close the loop out loud (T to talk) once the step is done, so the surgeon knows."))
    if fin and fin.get("map_in_range", 100) < 90:
        improve.append(dict(what=f"Pressure was in range only {fin['map_in_range']}% of bypass time.",
                            how="Aim for 50 to 80 mmHg: vaporizer down or phenylephrine to raise it, vaporizer up to lower it."))
    if fin and fin.get("do2_in_range", 100) < 90:
        improve.append(dict(what=f"Oxygen delivery was on target only {fin['do2_in_range']}% of bypass time.",
                            how="Keep it over 280: more flow, or red cells if the hematocrit is low."))
    improve = improve[:3]

    head = f"{doc['persona']['name']}."
    if fin:
        head += f" Score {fin['score']} with {fin['critical']} critical, ended in {PHASE_TITLES.get(fin['phase'], fin['phase'])}."
    if doc.get("practice"):
        head += " Practice (resumed from save): this score is not compared with clean start-to-finish runs."
    if doc.get("autopilot_used"):
        head += " The expert autopilot made some or all of the moves."
    lines = [head, "", "What was done:"] + ["- " + p["text"] for p in phase_text]
    lines += ["", "What went well:"] + (["- " + w for w in went_well] or ["- Not enough of the case was run to say."])
    lines += ["", "What was flagged:"] + (["- " + f for f in flagged] or ["- Nothing."])
    lines += ["", "Three things to improve:"]
    lines += [f"{i}. {x['what']}" + (f" {x['how']}" if x["how"] else "") for i, x in enumerate(improve, 1)] or ["- Nothing to improve on this run."]
    if 0 < len(improve) < 3:
        lines.append(f"(Only {len(improve)} found.)")
    return dict(header=head, phases=phase_text, went_well=went_well, flagged=flagged, improve=improve, text="\n".join(lines))


class SessionStore:
    def __init__(self, folder=os.path.join(ROOT, "logs")):
        self.folder = folder

    def list(self):
        out = []
        if os.path.isdir(self.folder):
            for fn in os.listdir(self.folder):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(self.folder, fn)) as f:
                            out.append(listing(json.load(f)))
                    except (OSError, ValueError, KeyError):
                        pass
        out.sort(key=lambda d: d["started_ts"], reverse=True)
        return out

    def read(self, sid):
        if not ID_RE.match(sid or ""):
            raise ValueError("bad session id")
        with open(os.path.join(self.folder, sid + ".json")) as f:
            return json.load(f)
