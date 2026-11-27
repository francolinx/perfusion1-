"""Leaderboard, levels and student names. Standard library only.

Built from the session logs in logs/, so there is no second store to keep in step. Only clean,
student-flown runs count: finished, not resumed from a save, no autopilot, and a name given.
Ranking is a fixed rule, so the same set of runs always produces the same board.
"""
import json
import os
import re
import time

PASS_SCORE = 80      # the rubric's pass mark (rubric.PASS_SCORE)
LEVELS = [
    dict(n=1, title="Level 1: the routine case", personas=["standard_adult"]),
    dict(n=2, title="Level 2: size and blood", personas=["small_anemic", "obese_adult", "jehovah_witness"]),
    dict(n=3, title="Level 3: pressure and potassium", personas=["vasoplegic", "hypertensive", "ckd"]),
    dict(n=4, title="Level 4: hard hearts and clotting", personas=["low_ef", "heparin_resistant", "aortic_insufficiency"]),
]
_cache = {}      # path -> (mtime, row)


def clean_name(name):
    """Display name: printable, no markup characters, 1 to 24 characters. Empty string if unusable."""
    name = re.sub(r"[\x00-\x1f<>&\"'`\\]", "", str(name or ""))
    return re.sub(r"\s+", " ", name).strip()[:24]


def row_of(doc):
    """The leaderboard's view of one session log, or None if the run does not count."""
    fin = doc.get("final") or {}
    student = clean_name(doc.get("student"))
    if doc.get("status") != "complete" or fin.get("phase") != "DONE" or doc.get("practice") \
            or doc.get("autopilot_used") or doc.get("instructor_used") or not student:
        return None
    f = fin.get("findings") or []
    co = fin.get("callouts") or {}
    return dict(id=doc["id"], student=student, persona=doc["persona"]["id"], persona_name=doc["persona"]["name"],
                score=fin.get("score", 0), critical=fin.get("critical", 0), findings=len(f),
                major=sum(1 for x in f if x["sev"] == "major"), minor=sum(1 for x in f if x["sev"] == "minor"),
                map_in=fin.get("map_in_range", 0), do2_in=fin.get("do2_in_range", 0),
                callouts_made=co.get("made", 0), callouts_due=co.get("due", 0),
                case_minutes=round(((doc.get("case_time_end") or 0) - (doc.get("case_time_start") or 0)) / 60, 1),
                started_at=doc.get("started_at"), started_ts=doc.get("started_ts", 0),
                quiz=(doc.get("quiz") or {}).get("score"), quiz_total=(doc.get("quiz") or {}).get("total"))


def rank_key(r):
    """Higher score first; ties break on fewer criticals, fewer findings, more time in range,
    more callouts, shorter case, then the earlier run."""
    return (-r["score"], r["critical"], r["findings"], -(r["map_in"] + r["do2_in"]), -r["callouts_made"],
            r["case_minutes"], r["started_ts"])


def load_rows(folder):
    rows = []
    if not os.path.isdir(folder):
        return rows
    for fn in os.listdir(folder):
        if not fn.endswith(".json") or fn == "last_test.json":
            continue
        path = os.path.join(folder, fn)
        try:
            mt = os.path.getmtime(path)
            hit = _cache.get(path)
            if hit and hit[0] == mt:
                row = hit[1]
            else:
                with open(path) as f:
                    row = row_of(json.load(f))
                _cache[path] = (mt, row)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if row:
            rows.append(row)
    return rows


def board(rows, persona=None, since_ts=None, student=None, limit=50):
    """Ranked rows for one filter, plus the named student's best run and its rank."""
    student = clean_name(student).lower()
    rows = [r for r in rows if (not persona or r["persona"] == persona) and (not since_ts or r["started_ts"] >= since_ts)]
    rows = sorted(rows, key=rank_key)
    ranked = [dict(r, rank=i + 1, mine=bool(student) and r["student"].lower() == student) for i, r in enumerate(rows)]
    mine = [r for r in ranked if r["mine"]]
    return dict(rows=ranked[:limit], total=len(ranked), best=mine[0] if mine else None, runs=len(mine))


def levels(rows, student):
    """Which levels the named student has unlocked. Level 1 is always open; each later level opens
    after one passing run (score at least PASS_SCORE, no critical finding) on the level before."""
    student = clean_name(student).lower()
    mine = [r for r in rows if r["student"].lower() == student] if student else []
    out, prev_passed = [], True
    for lv in LEVELS:
        runs = [r for r in mine if r["persona"] in lv["personas"]]
        best = {}
        for r in sorted(runs, key=rank_key):
            best.setdefault(r["persona"], r["score"])
        passed = any(r["score"] >= PASS_SCORE and r["critical"] == 0 for r in runs)
        out.append(dict(n=lv["n"], title=lv["title"], personas=lv["personas"], unlocked=prev_passed, passed=passed, best=best))
        prev_passed = prev_passed and passed
    return out


def today_ts(now=None):
    lt = time.localtime(now or time.time())
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
