# A Small Guard in Front of the Controller

Adaptive HVAC control with a safety guard, for the NeurIPS 2026 Smart Buildings Competition.

Most building controllers only work on the building they were tuned for, so the energy waste in every other building goes untouched because retuning a controller for each new building costs more than the energy it would save. This policy reads each new building from its metadata and live sensor stream at runtime and needs no retuning.

## What it is

An adaptive, rule-based controller built on the strongest shipped baseline, PID with hot water reset, plus a small safety guard ported from a policy engine for autonomous agents.

The controller:

- drives each air handler from its worst zone, not the average, because the comfort penalty is unbounded in the worst zone's deviation
- reads the comfort band from each zone's own heating and cooling setpoint sensors
- shuts air handlers down when the building is unoccupied and comfort mode is not due within the hour, and pre-conditions when comfort mode is due within the hour

The guard checks every action before it is issued:

- per-action cap: supply-air temperature may move at most 0.5 normalized units per step
- daily energy budget cap: at most 80 percent of the maximum possible daily commanded effort, forcing eco mode when spent unless a zone is more than 5 K outside its band
- allowlist: every continuous channel clipped to [-1, 1], and never heats a zone that is already hot
- confirm threshold: a proposal pushing against the measured zone error by more than 0.8 normalized units is replaced with the safe baseline's action
- unsafe-off prevention, with a shadow pid_water baseline as the safe fallback
- a JSONL ledger of every intervention, with step, day, rule, device, field, proposed and issued values, and a reason

## Results (local validation, 30 training scenarios)

Mean absolute error of mean per-step reward, lower is better, 8,640 steps per scenario:

| Policy | Mean MAE |
|---|---|
| bang-bang | 0.22453 |
| fixed setpoint | 0.06550 |
| PID | 0.06782 |
| PID + water | 0.05496 |
| Guarded (ours) | 0.05604 |

The guarded policy trails the best baseline by 0.00108, about 2 percent. It has the lowest comfort regret of any policy tested, -319.60 against -502.35 for PID + water, but higher energy cost, 811.90 against 496.96, and carbon, 650.24 against 370.17. Outside Fairbanks it beats PID + water on average, 0.04585 against 0.04893 across the other 24 scenarios. In Fairbanks it averages 0.09679 against 0.07906. The guard intervened 148,924 times, 148,921 slew clamps and 3 budget trips, all in building_train_1 in Fairbanks.

These are local results only. The shipped baseline returns bundled with the starter kit are stale by about 1 percent because of a tracker fix that landed after they were generated, so the comparison here is local against local. See `results.md` and `BUILD_REPORT.md` for the full tables and the reproduction gap.

## Paper

The round 1 poster paper is in `paper/paper.pdf` (4 pages excluding references, NeurIPS style, anonymized). It reports these real local numbers only.

## Files

- `guarded_hvac/policy.py` - `GuardedPolicy`, the adaptive controller
- `guarded_hvac/guard.py` - `Guard`, the policy guard and ledger
- `run_evaluation.py` - bulk runner over the 30 shipped scenarios
- `aggregate_results.py` - builds `results.md` from the summary files
- `results.md` - aggregated local results
- `BUILD_REPORT.md` - full build report, including the two guard rules that were tried and removed
- `paper/` - the poster paper (PDF and HTML source)

The starter kit itself is not included. Clone it from https://github.com/smart-buildings-2026/starter-kit, copy `guarded_hvac/` into it, register `"guarded"` in `POLICY_MAP` in `smart_buildings/evaluate.py`, and run `run_evaluation.py`.

## Competition

NeurIPS 2026 Smart Buildings Competition: https://www.kaggle.com/competitions/neurips-2026-smart-buildings/
Competition paper: https://arxiv.org/abs/2610.18511
