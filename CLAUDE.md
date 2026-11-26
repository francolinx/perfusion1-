# perfusion1: guide for Claude Code

Open 3D cardiopulmonary bypass trainer. Read `README.md`, `docs/ARCHITECTURE.md` and
`docs/ROADMAP.md` first.

## Commands

- Run: `./run.sh` (serves http://localhost:8080; `PORT=9000 ./run.sh` to change port)
- Test: `./run.sh --test` or `python3 -m unittest discover -s tests -v`
- Play a case headless: `python3 scripts/play_case.py --persona ckd`
  (`--mistake flow_up_early` replays the sequencing error from the lab video)

## Rules for this repo

- The core (`perfusion/`) is Python standard library only. Do not add dependencies to it;
  "one pull and run" on an aarch64 DGX Spark is a requirement. Optional features that need
  packages go in their own top-level folder with their own requirements file.
- The web client has no build step and no CDN. three.js is vendored in `web/vendor/`.
- Renderers never compute physiology. They read `/api/state` and post `/api/action`.
- Grading stays deterministic and rule-based. Language models may classify speech and write
  debrief prose, never decide the score.
- Every model or rule change needs a test in `tests/test_sim.py`, and the expert autopilot must
  still finish every persona with no critical findings.
- Educational use only. Do not present model numbers as clinical reference values. Constants are
  teaching approximations pending review by a certified clinical perfusionist.
- Use `Co-Authored-By` trailers as configured; commit on a branch and open a pull request.

## Where things are

- Patient + circuit model: `perfusion/model.py` (constants at the top, `Sim.step`)
- Patients: `perfusion/personas.json`
- Case flow, surgeon script, grading rules: `perfusion/scenario.py`
- Expert policy: `perfusion/autopilot.py`
- Server and API: `perfusion/server.py`
- 3D room, HUD, input: `web/main.js`; equipment control panels: `web/panels.js`

## Next work

See `docs/ROADMAP.md`. Items 6 to 8 (Isaac Sim room, local voice, synthetic data) need the
DGX Spark and should be developed there against the same API.
