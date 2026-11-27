#!/usr/bin/env python3
"""The test gate behind ./run.sh --test: the unit tests, then a headless expert case that must finish with
score 100 and no critical findings. Writes the result to logs/last_test.json for the /dashboard page.
Exits non-zero if anything fails."""
import json, os, sys, time, unittest
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from perfusion.saves import build_version  # noqa: E402
import play_case  # noqa: E402

t0 = time.time()
suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"), top_level_dir=os.path.join(ROOT, "tests"))
res = unittest.TextTestRunner(verbosity=1).run(suite)
print()
case = play_case.run(verbose=True)
sc = case.score()
print(f"\nphase {case.phase}  score {sc['score']}  critical {sc['critical']}  callouts {sc['callouts']}  "
      f"MAP in range {sc['map_in_range']}%  DO2 in range {sc['do2_in_range']}%")
expert_ok = case.phase == "DONE" and sc["score"] == 100 and sc["critical"] == 0
ok = res.wasSuccessful() and expert_ok
status = dict(ok=ok, at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), ts=time.time(), seconds=round(time.time() - t0, 1),
              tests_run=res.testsRun, failures=len(res.failures), errors=len(res.errors), skipped=len(res.skipped),
              expert=dict(phase=case.phase, score=sc["score"], critical=sc["critical"]), build=build_version())
try:
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    tmp = os.path.join(ROOT, "logs", "last_test.json.tmp")
    with open(tmp, "w") as f:
        json.dump(status, f, indent=1)
    os.replace(tmp, os.path.join(ROOT, "logs", "last_test.json"))
except OSError as e:
    print("could not write logs/last_test.json:", e)
print("\nGATE", "PASS" if ok else "FAIL", f"({res.testsRun} tests, expert score {sc['score']}, critical {sc['critical']})")
sys.exit(0 if ok else 1)
