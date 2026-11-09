# NeurIPS 2026 Smart Buildings, round 1: build report

## What was built

A guarded adaptive HVAC policy for the NeurIPS 2026 Smart Buildings
Competition, round 1 (poster paper, treated as due Thu Nov 12, 2026; the
Nov 13 date carries no published time).

The policy is an adaptive, rule-based controller, not a reinforcement
learning agent. It is built on the strongest shipped baseline, `pid_water`,
with three adaptive improvements, and the Recall policy engine wrapped
around it as a safety guard.

## Files

- `guarded_hvac/policy.py` - `GuardedPolicy`, the adaptive controller.
- `guarded_hvac/guard.py` - `Guard`, the Recall policy engine ported to HVAC.
- `guarded_hvac/__init__.py` - package marker.
- `guarded_hvac/ledger/` - one JSONL ledger per scenario, every guard
  intervention with its reason.
- `run_evaluation.py` - bulk runner over the 30 shipped scenarios.
- `aggregate_results.py` - builds `results.md` from the summary files.
- `results/` - per-scenario harness output (summary.json, charts, CSVs).
- `results.md` - the aggregated numbers (written when the run finishes).

The starter kit itself is untouched except for one line in
`smart_buildings/evaluate.py`, registering `"guarded"` in `POLICY_MAP`.

## The controller

`GuardedPolicy` subclasses the shipped `PIDWaterResetPolicy` and turns on
the two refinements the shipped chain leaves off:

1. **Worst-zone tracking.** `pid_water` drives each air handler from the
   average temperature of its zones, but the comfort penalty is unbounded
   in the worst zone's deviation. One zone 10 K out costs far more than ten
   zones 1 K out, and an average can hide exactly that. This policy drives
   each handler from its worst zone instead.
2. **Sensor band.** The reward judges each zone against its own heating and
   cooling setpoint sensors, so this policy reads the band from those
   sensors instead of rebuilding it from the hour of day.

On top of that, two occupancy-aware behaviours:

3. **Occupancy-aware shutdown.** The comfort charge is weighted by
   occupancy, so conditioning an empty building is pure cost. When the
   building is unoccupied and comfort mode is not due within the hour, the
   air handlers shut down. When comfort mode is due within the hour, the
   controller pre-conditions against the comfort band instead of waiting
   for the band to snap over at the start of work hours.

The policy reads the building metadata at construction (AHU-to-zone map,
action indices, water indices) and the live sensor stream at every step
(zone temperatures, occupancy, comfort mode flags). It adapts to a new
building without retuning: nothing in it is keyed to a building ID, a
floor plan, or a climate.

## The guard

`Guard` ports the Recall policy engine's four rules to this setting, plus
a ledger:

- **Per-action cap (slew rate).** An air handler's supply-air temperature
  may move at most 0.5 normalized units per step, and only while the
  handler was already running and stays running. A cold start and a
  shutdown get their full move.
- **Daily energy budget cap.** The plant may spend at most 80% of the
  maximum possible daily commanded effort in one simulated day. When the
  budget is spent, the guard forces eco mode, unless a zone is more than
  5 K outside its band (the quadratic penalty region), in which case
  comfort wins.
- **Allowlist.** Every continuous channel is clipped to the normalized
  range [-1, 1]. The guard never heats a zone that is already hot: if a
  zone is above its cooling setpoint, its reheat valve is forced closed
  and its damper is forced to minimum.
- **Confirm threshold.** If a proposed supply-air temperature pushes
  against the measured zone error by more than 0.8 normalized units, the
  guard replaces that handler's action with the safe baseline's action.
- **Unsafe-off prevention.** The proposal must not switch an air handler
  off while its own zones are outside their band. An empty building with
  no comfort due is exempt.
- **Ledger.** Every intervention is appended to a JSONL ledger with the
  step, day, rule, device, field, proposed and issued values, and a
  human-readable reason.

A shadow instance of the shipped `pid_water` baseline runs alongside on
the same observation stream and supplies the safe fallback action.

### Two rules that were removed, and why

- **Minimum on/off time.** An early version held each handler on or off
  for at least 6 steps. In a 288-step smoke test it fired 47 times, and it
  interacted badly with the slew cap: holding a handler on with its idle
  setpoints left it "running" at the coldest supply temperature, and the
  slew cap then throttled its recovery for several steps. A guard rule
  must not manufacture the violation the next rule has to catch, so the
  hold was removed rather than patched around. The simulator also models
  no restart cost, so the hold could only cost score.
- **Water-temperature slew cap.** An early version capped the hot-water
  temperature at 0.3 per step. In the smoke test it fired 92 times in
  288 steps, mostly with large clamps, because the shipped water reset
  switches the temperature between -1 when the loop is idle and the reset
  value when it is heating. A per-step cap on it fights the mode switch
  instead of catching hunting, so the water temperature is excluded from
  the cap. The air-handler supply-air temperature keeps the cap.

After both removals, a 288-step smoke test on
building_train_1/fairbanks_1 produced 27 interventions, all genuine
air-handler slew clamps, and a total reward of -3.51, better than -3.98
with the water cap and -3.65 with the cycle hold.

## Baseline scores (shipped)

From `baseline_returns.json`, 30 scenarios, 8,640 steps each, MAE of mean
per-step reward against zero (lower is better):

| policy | mean MAE |
|---|---|
| bang_bang | 0.22520 |
| fixed_setpoint | 0.06592 |
| pid | 0.06736 |
| pid_water | 0.05414 |

`pid_water` is the best shipped baseline and the one to beat.

## Reproduction gap: the shipped numbers are stale

A calibration run reproduced one shipped scenario locally:
`pid_water` on building_train_1/fairbanks_1, 8,640 steps. Local total
reward -1848.31 against the shipped -1828.90, a gap of about 1% (MAE
0.21392 local vs 0.21168 shipped). The simulator is deterministic, so a
gap means the code changed after the shipped returns were generated.

The cause is in the kit's git history: a merge commit "Fix simulation
tracker querying occupancy with VAV IDs" landed after the initial commit
that shipped the returns. The tracker was querying occupancy with VAV
zone IDs, which created fictitious populations and consumed random draws;
fixing it changed the random stream, and therefore the trajectories.
The shipped returns were generated with the pre-fix code and are not
reproducible with the current code.

Consequence: the paper must compare the guarded policy against baselines
run locally with the same code, not against the shipped numbers. The
shipped numbers are reported in `results.md` only as a reference, with
the gap stated. This is also why the evaluation runs all four baselines
locally on all 30 scenarios instead of reusing the shipped table.

## Evaluation

- Harness: the shipped `smart_buildings/evaluate.py`, 8,640 steps per
  scenario, all 30 shipped training scenarios (the exact pairs in
  `smart_buildings/training_set.yaml`, not a cross product: each building
  sees one strip per station, atlanta, denver, fairbanks, phoenix,
  singapore, and no strip is used twice).
- Policies: bang_bang, fixed_setpoint, pid, pid_water, guarded.
- One full 8,640-step episode takes about 9.5 minutes on this machine
  (about 0.063 s per step). Five policies times 30 scenarios is 150
  episodes, about 24 hours of single-core compute.
- Two workers run in parallel (each about 450 MB; the machine has about
  1.1 GB usable, so two is the safe limit). Each worker handles 15
  scenarios. Expected wall time about 12 hours from the 16:52 WAT start
  on Sun Nov 8, 2026, finishing around 04:30 WAT Mon Nov 9.
- The runner is resumable: a scenario is skipped when all five
  summary.json files exist. Re-running is safe because the simulator is
  deterministic.
- Progress logs: `eval_workerA.log` (buildings 1, 2, 4) and
  `eval_workerB.log` (buildings 5, 7, 8).

**VM restart, Sun Nov 8 ~20:17 WAT.** The VM restarted (uptime reset to
1 min), killing both workers and the watcher. No results were lost: 5
scenarios (25 summary files) were already on disk. The in-progress
scenarios (building_train_1/phoenix_5, building_train_5/fairbanks_5) had
written nothing and were restarted from scratch. Both workers were
relaunched at 20:19 WAT and resumed correctly (A: 3 done, 12 to run; B:
2 done, 13 to run). The watcher was relaunched too. `/tmp/calib` (the
calibration output) was wiped by the restart because /tmp is ephemeral,
but the calibration number is recorded in this report and the entry note,
so nothing was lost.

**Revised ETA.** Per-scenario time is slower than the 50-minute estimate:
worker A takes about 66 minutes per scenario (building_train_1, 39 zones,
4 AHUs, 0.089 s/step under contention vs 0.063 s/step single-worker), and
worker B takes about 95 minutes per scenario (building_train_5, 79 zones,
8 AHUs, 0.128 s/step). The remaining 25 scenarios should finish Mon Nov 9,
late morning to afternoon, not 05:00 as first estimated. The paper
deadline (Nov 12) still leaves Tue/Wed to write the paper.

**Second VM restart, Sun Nov 8 ~22:38 WAT.** The VM restarted again
(uptime reset to 0 min), killing both workers and the watcher for the
second time. Progress before the restart: 42 of 150 summary files, 9
scenarios with output, building_train_1 fully complete (all 5 scenarios).
Both workers were relaunched at 22:38 WAT and resumed (A: 5 done, 10 to
run; B: 3 fully done, 12 to run). The watcher was relaunched too. The
restart pattern is now twice in about 5.5 hours, roughly every 2.5 hours.
Each restart loses the in-progress scenario's partial work and the
relaunch delay until someone notices.

**Per-policy resume.** The runner was improved after the second restart:
it now re-runs only the missing policies in a partially complete scenario
(the harness writes one summary.json per policy as each finishes), instead
of re-running all five. Verified: building_train_5/phoenix_1 was missing
only pid, pid_water and guarded after the restart (bang_bang and
fixed_setpoint had completed). The running workers use the old code
(loaded at launch); the improved resume applies from the next relaunch.

**Open risk.** If the VM keeps restarting every ~2.5 hours, the workers
will keep dying and sitting dead until someone relaunches them. A
watchdog cron that checks every 15 minutes and relaunches dead workers
would fix this, but it is a scheduled job the task did not ask for, so it
has not been created. It is flagged here for the parent to approve.

**Fourth VM restart, Mon Nov 9 ~02:49 WAT.** The VM restarted a fourth
time (uptime reset to 1 min at 02:50). Progress before this restart: 64
of 150 summary files. Building 5 is now complete (all 5 scenarios) and
worker B has moved on to building 7. The watchdog script was tested
manually at 02:49 and correctly detected both workers dead and relaunched
them (A: 6 done, 9 to run, on building_train_2_denver_8; B: 6 done, 9 to
run, on building_train_7_denver_5).

**Watchdog cron, set up Mon Nov 9 ~03:50 WAT (parent approved).**
Cron id `neurips-eval-watchdog`, every 15 minutes, runs
`~/workspace/neurips-smart-buildings/watchdog.sh`, which relaunches any
dead worker and builds results.md once all 150 summary files exist. The
cron run stays quiet while the evaluation is still running and reports
only on completion. First run Mon Nov 9 04:05 WAT. Remove this cron once
results.md is final.

When the run finishes, run `python3 aggregate_results.py` to write
`results.md` with the exact MAE table, the reward breakdowns, the
shipped-vs-local comparison, and the guard intervention counts.

## What the paper can honestly claim

- A guarded adaptive controller, built on the strongest shipped baseline,
  that reads each new building's metadata and sensor stream at runtime
  and adapts without retuning. The problem it answers is the one in the
  concept: most controllers only work on the building they were tuned
  for, and retuning costs more than the energy it would save.
- A safety guard ported from the Recall policy engine, with the four
  rules and a ledger, evaluated on the same 30 scenarios as the
  baselines. The ledger gives exact intervention counts and reasons.
- Real local numbers only: the MAE table, the comfort/energy/carbon
  breakdown, and the guard intervention counts all come from the local
  harness. No invented benchmark scores.
- The reproduction gap is disclosed, not hidden: the shipped baseline
  numbers are stale by about 1% because of the tracker fix, so the
  comparison in the paper is local-vs-local.

## What the paper cannot claim

- That the policy is reinforcement learning. It is rule-based and
  adaptive. The paper must describe it as such.
- That the policy generalizes to unseen buildings. The local evaluation
  is on the 30 training scenarios only. The evaluation set (6 unseen
  buildings, 5 unseen stations) is run by the competition, not locally.
  The paper can argue for transfer (no building-specific tuning, metadata
  driven) but cannot report an unseen-building score.
- A win over the baselines until the numbers are in. The smoke test is
  encouraging but 288 steps on one scenario is not evidence.

## Remaining work (after the evaluation finishes)

1. Run `aggregate_results.py` and read `results.md` for the exact numbers.
2. Poster paper draft from those real numbers.
3. Kaggle notebook with the policy (subclassing
   `smart_buildings_inference_server.Policy`).
4. Public repo (do not create it until the paper draft exists).
5. Submit the poster paper by the round 1 deadline, treated as due
   Thu Nov 12, 2026.
