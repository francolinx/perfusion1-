# Benchmark: 10 patients x 10 runs

Reproduce with `python3 scripts/benchmark.py` (about 3 minutes, writes `docs/benchmark.json`).
`--runs N` with any other N is a quick check and writes nothing unless you pass `--out`.

The model is deterministic, so ten identical expert runs would match exactly. Each patient
therefore gets one clean expert run plus nine seeded simulated students in three skill bands.
Students react slower, hold flow off target, skip callouts and make 0 to 5 injected errors
(flow up before clamp off, fast cardioplegia, no re-dose, ventilator mistakes, wrong protamine
dose, suckers on at protamine, over-cooling, hot rewarming, ignoring gases). They are a stress
test of the model and grader, not a substitute for real student data.

## Results after fixes (100 runs)

| Band | Runs | Mean score | Lowest | Highest |
|---|---|---|---|---|
| Expert | 10 | 100 | 100 | 100 |
| Strong (0-1 errors) | 30 | 97 | 80 | 100 |
| Average (1-3 errors) | 30 | 84 | 50 | 100 |
| Novice (3-5 errors) | 30 | 66 | 32 | 92 |

All 100 runs finish. Speed: about 89,000 model steps per second on one core, roughly 1,800 times
real time, so a 50 minute case replays in under 2 seconds. (x86 Linux, where v0.1 was built.)

On a DGX Spark (GB10, aarch64, DGX OS, Python 3.12.3), `--runs 4` (40 runs) finished every run in
41 s at about 153,000 steps per second on one core, roughly 3,000 times real time, with mean scores
expert 100, strong 97, average 81, novice 68.

Mean score per patient over all ten runs: standard adult 83, small anemic 76, large adult 91,
low EF 86, kidney disease 88, heparin resistance 89, aortic insufficiency 82, vasoplegia 83,
hypertension 82, Jehovah's Witness 84.

## What the first pass found, and what was fixed

| Finding in the first pass | Fix |
|---|---|
| 11 of 100 runs never finished: the surgeon waited forever in the bypass-checks phase | Surgeon now proceeds after 7 minutes with a major finding; same for an unstable patient off bypass |
| Skipping the maintenance cardioplegia dose was never penalised (0 of 11) | Washout retuned so a re-dose is needed, and the interval rule fires at 20 minutes (15 of 15 caught) |
| One error (suckers on at protamine) was charged twice, 40 points | One error, one penalty |
| The expert caused backflow going on bypass in the hypertensive patient | Expert spins the pump until its head beats patient pressure; on-screen guidance says the same |
| Displayed hematocrit and oxygen delivery dipped to unreal values for a few seconds at initiation | Tissue oxygen delivery now uses the patient's mixed blood |
| Repeating findings could drive a score to 0 | A repeating problem is penalised at most three times |

## Still open

1. **A critical error does not fail the run.** One critical costs 20 points, so 80 still reads as a pass.
2. **Checklist misses and callouts do not move the score.** Novices made 39% of callouts at no cost.
3. **Some errors are nearly free**: fast cardioplegia 0 to 2 points, over-cooling 2 points.
4. **The expert scores 100 on every patient**, so the score has no headroom to rank good runs.
   Lowest oxygen delivery of 253 in the anemic patient still scored 100.
5. **Pressure control is too hard in two patients**: the expert held pressure in range only 79%
   (hypertension) and 85% (low EF) of bypass time. A vasodilator is missing.
6. **Pacing is too fast**: weaning takes under a minute, lab results 6 seconds.
7. **One injected error never took effect** (root vent on during antegrade), because the case does
   not require the vent to be on between clamp and cardioplegia. That is a gap in the case script.
8. **Case order**: hot shot before rewarming follows the lab video and should be checked with a perfusionist.
9. **Validation**: nothing here has been compared with real patient or real student data.
