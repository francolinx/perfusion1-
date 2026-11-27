#!/usr/bin/env python3
"""Play a full case headless with the expert autopilot and print the debrief."""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from perfusion.model import load_personas
from perfusion.scenario import Case
from perfusion.autopilot import Autopilot


def run(persona_id="standard_adult", mistake=None, max_minutes=120, verbose=False):
    case = Case(load_personas()[persona_id])
    pilot = Autopilot(case, mistake=mistake)
    last, n = None, int(max_minutes * 60 / case.sim.DT)
    for _ in range(n):
        pilot.step()
        case.tick()
        if verbose and case.phase != last:
            s = case.sim
            print(f"{case.t/60:6.1f} min  {case.phase:<10} MAP {s.pa:5.1f}  flow {s.qa:4.2f}  T {s.temp:4.1f}  "
                  f"res {s.vr:5.0f}  Hct {s.hct_c*100:4.1f}  DO2i {s.do2i:4.0f}  K {s.k:3.1f}  rhythm {s.rhythm}")
            last = case.phase
        if case.phase == "DONE":
            break
    return case


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="standard_adult")
    ap.add_argument("--mistake", default=None)
    a = ap.parse_args()
    c = run(a.persona, a.mistake, verbose=True)
    sc = c.score()
    print(f"\nphase {c.phase}  score {sc['score']}  critical {sc['critical']}  callouts {sc['callouts']}  "
          f"MAP in range {sc['map_in_range']}%  DO2 in range {sc['do2_in_range']}%")
    for f in sc["findings"]:
        print(f"  [{f['sev']}] {f['t']/60:5.1f} min {f['phase']}: {f['msg']}")
    rb = sc["rubric"]
    print(f"\nrubric: {rb['outcome']}  {rb['earned']} of {rb['possible']} observable points ({rb['not_observed']} of 100 not simulated)")
    for m in rb["missed"]:
        print(f"  -{m['lost']} {m['id']} {m['label']}: {' '.join(m['why'])}")
    missing = [x["label"] for x in sc["checklist"] if not x["done"]]
    if missing:
        print("  not done:", "; ".join(missing))
