# perfusion1: guide for Claude Code

Open 3D cardiopulmonary bypass trainer. Read `README.md`, `docs/ARCHITECTURE.md` and
`docs/ROADMAP.md` first.

## Commands

- Run: `./run.sh` (serves http://localhost:8080; `PORT=9000 ./run.sh` to change port)
- Test: `./run.sh --test` (the gate: all tests pass and the expert case scores 100 on the rubric; writes `logs/last_test.json`)
  or `python3 -m unittest discover -s tests -v`
- Dashboard: `http://localhost:9000/dashboard` (simulator, AI services, machine, build)
- Browser check (headless, no window, needs Node 22 and Chrome): `node tools/browser_check.mjs --url http://localhost:9000 --gpu`
  (`--full` also plays the expert case to the debrief). Keep browser tests headless. Point it at a
  scratch server (`--port 9100 --saves-dir ... --logs-dir ...`): it resets the shared case.
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
- The leaderboard ranks only clean student runs (finished, named, no autopilot, not resumed from a save) by a
  fixed rule in `leaderboard.rank_key`. Quiz answers must restate rules or constants the simulator enforces,
  and every quiz tag must be a finding code the simulator can raise (a test checks this).
- Do not copy another product's screens, wording, scenarios or art. Match features only.
- Educational use only. Do not present model numbers as clinical reference values. Constants are
  teaching approximations pending review by a certified clinical perfusionist.
- Use `Co-Authored-By` trailers as configured; commit on a branch and open a pull request.

## Where things are

- Patient + circuit model: `perfusion/model.py` (constants at the top, `Sim.step`)
- Patients: `perfusion/personas.json`
- Case flow, surgeon script, grading rules: `perfusion/scenario.py`; rubric that turns them into the score
  (sections, points, reasons for lost points, pass at 80): `perfusion/rubric.py`, report shared by the debrief and
  run page: `web/rubric.js`
- Expert policy: `perfusion/autopilot.py`
- Instructor controls (patient and circuit changes, pace, surgeon voice; instructor-led runs are not ranked):
  `perfusion/instructor.py`, page `web/instructor.html`, `GET/POST /api/instructor`. What the real lab has and what
  to build to match it: `docs/LAB_FIDELITY.md`. The lab's spoken script, common errors and the build list that
  follows from them: `docs/LAB_SESSION_NOTES.md`
- Server and API: `perfusion/server.py`
- 3D room, HUD, input: `web/main.js`; equipment control panels: `web/panels.js`
- Smash mode (cosmetic rage room, client only, never graded): `web/smash.js`
- Rendering quality (image-based light, bloom, ambient occlusion, tiers that step down when slow): `web/gfx.js`;
  three.js addon modules are vendored in `web/vendor/addons/` and resolved by the importmap in `web/index.html`
- Student name, level locks, rank and quiz in the debrief: `web/game.js`; leaderboard ranking and levels:
  `perfusion/leaderboard.py`; quiz bank and grading: `perfusion/quiz.py`; pages `web/leaderboard.html`,
  `web/run.html` (run analysis charts from the session log's time series), shared `web/pages.css`
- Player avatar and third-person body (cosmetic, client only): `web/player.js`
- Save / load (exact case state, saves/ folder): `perfusion/saves.py`; session logs and the rule-based
  summary (logs/ folder): `perfusion/sessionlog.py`; their screens: `web/saves.js`
- Dashboard readings (stdlib: /proc, nvidia-smi, service /health): `perfusion/monitor.py`; page: `web/dashboard.html`

## Next work

See `docs/ROADMAP.md`. Items 6 to 8 (Isaac Sim room, local voice, synthetic data) need the
DGX Spark and should be developed there against the same API.
