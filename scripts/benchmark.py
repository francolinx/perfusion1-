#!/usr/bin/env python3
"""Benchmark the simulator: every persona x N runs.

The model is deterministic, so identical expert runs would all match. Run 0 for each
persona is the clean expert; the rest are seeded "simulated students" of three skill
bands who react slower, miss callouts, hold flow off target and make realistic errors.
That tests two things at once: whether the physiology stays plausible under sloppy
control, and whether the grader separates good runs from bad ones.

    python3 scripts/benchmark.py            # 10 runs per persona, writes docs/BENCHMARK.md
    python3 scripts/benchmark.py --runs 4   # quicker
"""
import argparse
import json
import os
import random
import statistics as st
import sys
import time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from perfusion.autopilot import Autopilot
from perfusion.model import load_personas
from perfusion.scenario import Case, PHASES

MISTAKES = ["flow_up_early", "vent_on_antegrade", "cp_fast", "retro_fast", "no_redose", "vent_off_early",
            "vent_late_on_wean", "protamine_half", "sucker_on_protamine", "overcool", "hot_rewarm", "ignore_gases"]
BANDS = dict(strong=dict(period=(0.5, 1.0), n=(0, 1), skip=0.05, bias=0.02, gas_every=2),
             average=dict(period=(1.0, 2.0), n=(1, 3), skip=0.3, bias=0.05, gas_every=10),
             novice=dict(period=(2.0, 3.5), n=(3, 5), skip=0.6, bias=0.09, gas_every=30))


class StudentPilot(Autopilot):
    """The expert policy degraded by a seeded skill profile."""

    def __init__(self, case, rng, band):
        b = BANDS[band]
        self.rng, self.band = rng, band
        self.period = rng.uniform(*b["period"])
        self.skip = b["skip"]
        self.bias = rng.uniform(-b["bias"], b["bias"])
        self.gas_every = b["gas_every"]
        self.errs = set(rng.sample(MISTAKES, rng.randint(*b["n"])))
        super().__init__(case, mistake="flow_up_early" if "flow_up_early" in self.errs else None)
        self.gas_t = 0.0

    def step(self):
        case = self.case
        if case.t < self.next_t or case.phase == "DONE":
            return
        super().step()
        self.next_t = max(self.next_t, case.t + self.period)

    def keep_gases(self):
        if "ignore_gases" in self.errs or self.case.t - self.gas_t < self.gas_every:
            return
        self.gas_t = self.case.t
        super().keep_gases()

    def call(self, cid):
        key = "skipdec_" + self.case.phase + cid
        if key not in self.mem:
            self.mem[key] = self.rng.random() < self.skip
        if not self.mem[key]:
            super().call(cid)

    def flow_to(self, target):
        super().flow_to(target * (1.0 + self.bias) if target > 0.05 else target)

    def set(self, key, value):
        ph, e = self.case.phase, self.errs
        if key == "root_vent" and value is False and ph == "ANTEGRADE" and "vent_on_antegrade" in e:
            return
        if key == "cp_flow" and "cp_fast" in e and self.case.sim.c["cp_route"] == "ante" and ph == "ANTEGRADE":
            value = 400.0
        if key == "cp_flow" and "retro_fast" in e and ph == "RETROGRADE":
            value = 260.0
        if key == "cp_on" and value and ph == "OPERATE" and "no_redose" in e:
            return
        if key == "ventilator" and value and ph == "WEAN" and "vent_late_on_wean" in e and self.case.t - self.case.phase_t0 < 40:
            return
        if key == "sucker" and value is False and ph == "POST" and "sucker_on_protamine" in e:
            return
        if key == "water_set":
            if ph == "COOL" and "overcool" in e:
                value = max(15.0, value - 6.0)
            if ph == "REWARM" and "hot_rewarm" in e:
                value = 40.0
        super().set(key, value)

    def act(self, **a):
        if a.get("type") == "protamine" and "protamine_half" in self.errs:
            a["mg"] = round(a["mg"] * 0.5)
        super().act(**a)

    def p_INITIATE(self, s, tf):
        if "vent_off_early" in self.errs and self.once("early_vent"):
            self.act(type="set", key="ventilator", value=False)
        super().p_INITIATE(s, tf)


def run_one(persona, seed, band, max_minutes=150):
    case = Case(persona)
    rng = random.Random(seed)
    pilot = Autopilot(case) if band == "expert" else StudentPilot(case, rng, band)
    s = case.sim
    m = dict(min_res=9e9, min_map=9e9, max_map=0, min_do2i=9e9, min_svo2=9e9, max_k=0, min_hct=9e9, max_line=0,
             max_lactate=0, min_ph=9, max_paco2=0, min_paco2=999, min_flow=0.0, phase_t={})
    last = None
    t0 = time.perf_counter()
    steps = 0
    for _ in range(int(max_minutes * 60 / s.DT)):
        pilot.step()
        case.tick()
        steps += 1
        if case.phase != last:
            m["phase_t"][case.phase] = case.t
            last = case.phase
        m["min_flow"] = min(m["min_flow"], s.qa)
        if s.on_bypass and case.phase not in ("INITIATE", "CLAMP_ON", "CLAMP_OFF", "WEAN"):
            m["min_res"] = min(m["min_res"], s.vr); m["min_map"] = min(m["min_map"], s.pa); m["max_map"] = max(m["max_map"], s.pa)
            m["max_line"] = max(m["max_line"], s.line_p); m["min_hct"] = min(m["min_hct"], s.hct_p)
            if case.phase not in ("STABILIZE",):
                m["min_do2i"] = min(m["min_do2i"], s.do2i); m["min_svo2"] = min(m["min_svo2"], s.svo2)
                m["max_paco2"] = max(m["max_paco2"], s.paco2); m["min_paco2"] = min(m["min_paco2"], s.paco2)
        m["max_k"] = max(m["max_k"], s.k); m["max_lactate"] = max(m["max_lactate"], s.lactate); m["min_ph"] = min(m["min_ph"], s.ph)
        if case.phase == "DONE":
            break
    wall = time.perf_counter() - t0
    sc = case.score()
    pt = m.pop("phase_t")
    dur = {PHASES[i]: (pt[PHASES[i + 1]] - pt[PHASES[i]]) / 60 for i in range(len(PHASES) - 1) if PHASES[i] in pt and PHASES[i + 1] in pt}
    return dict(persona=persona.id, band=band, seed=seed, finished=case.phase == "DONE", stuck_in=None if case.phase == "DONE" else case.phase,
                score=sc["score"], critical=sc["critical"], findings=[(f["sev"], f["code"], f["phase"]) for f in sc["findings"]],
                missed=[c["id"] for c in sc["checklist"] if not c["done"]], callouts=sc["callouts"],
                map_in=sc["map_in_range"], do2_in=sc["do2_in_range"], case_min=case.t / 60, bypass_min=s.bypass_time / 60,
                clamp_min=s.clamp_time / 60, end_map=s.pa, end_cvp=s.cvp, end_res=s.vr, injury=s.injury, dur=dur,
                errs=sorted(getattr(pilot, "errs", [])), wall_s=wall, steps=steps, **m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "benchmark.json"))
    a = ap.parse_args()
    bands = ["expert"] + [["strong", "average", "novice"][i * 3 // max(1, a.runs - 1)] for i in range(a.runs - 1)]
    rows = []
    for pid, persona in load_personas().items():
        for i, band in enumerate(bands):
            r = run_one(persona, seed=sum(map(ord, pid)) * 31 + i, band=band)
            rows.append(r)
            print(f"{pid:<22} run {i} {band:<8} {'ok ' if r['finished'] else 'STUCK ' + str(r['stuck_in']):<6} score {r['score']:>3} crit {r['critical']} "
                  f"{r['case_min']:5.1f} min  errs {','.join(r['errs'])}")
    with open(a.out, "w") as f:
        json.dump(rows, f, indent=1)
    tot_steps = sum(r["steps"] for r in rows); tot_wall = sum(r["wall_s"] for r in rows)
    print(f"\n{len(rows)} runs, {tot_steps/1e6:.1f}M model steps in {tot_wall:.0f} s: {tot_steps/tot_wall:,.0f} steps/s, "
          f"{tot_steps*0.02/tot_wall:,.0f}x real time. Mean score by band: "
          + ", ".join(f"{b} {st.mean(r['score'] for r in rows if r['band']==b):.0f}" for b in ["expert", "strong", "average", "novice"]))


if __name__ == "__main__":
    main()
