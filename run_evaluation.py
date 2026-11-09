#!/usr/bin/env python3
"""Bulk evaluation runner for the NeurIPS 2026 Smart Buildings round 1.

Runs the shipped evaluate.py harness over the 30 shipped training
scenarios, all five policies per scenario (bang_bang, fixed_setpoint, pid,
pid_water, guarded), one process per scenario so a crash loses at most one
scenario.

The 30 scenarios are the exact pairs from smart_buildings/training_set.yaml,
not a cross product: each building sees one strip per station (atlanta,
denver, fairbanks, phoenix, singapore) and no strip is used twice. The
pairs are hard-coded here from that file so the runner cannot drift from
it; if training_set.yaml changes, update SCENARIOS to match.

Resume: a scenario is skipped when all five summary.json files already
exist under the results dir, and a partially complete scenario re-runs
only its missing policies, because the harness writes one summary.json
per policy as each policy finishes. Re-running is safe: the simulator is
deterministic, so a re-run reproduces the same numbers.

Usage:
    python3 run_evaluation.py <buildings...>
    python3 run_evaluation.py building_train_1 building_train_2 building_train_4

Two workers run in parallel, each with its own half of the buildings and
its own progress log. The machine has about 1.1 GB of usable memory and
each evaluation process takes about 450 MB, so two workers is the safe
limit; a third risks an out-of-memory kill.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICIES = ["bang_bang", "fixed_setpoint", "pid", "pid_water", "guarded"]

# Exact pairs from smart_buildings/training_set.yaml.
SCENARIOS = [
    ("building_train_1", "atlanta_2"),
    ("building_train_1", "denver_7"),
    ("building_train_1", "fairbanks_1"),
    ("building_train_1", "phoenix_5"),
    ("building_train_1", "singapore_8"),
    ("building_train_2", "atlanta_3"),
    ("building_train_2", "denver_8"),
    ("building_train_2", "fairbanks_2"),
    ("building_train_2", "phoenix_6"),
    ("building_train_2", "singapore_1"),
    ("building_train_4", "atlanta_5"),
    ("building_train_4", "denver_2"),
    ("building_train_4", "fairbanks_4"),
    ("building_train_4", "phoenix_8"),
    ("building_train_4", "singapore_3"),
    ("building_train_5", "atlanta_6"),
    ("building_train_5", "denver_3"),
    ("building_train_5", "fairbanks_5"),
    ("building_train_5", "phoenix_1"),
    ("building_train_5", "singapore_4"),
    ("building_train_7", "atlanta_8"),
    ("building_train_7", "denver_5"),
    ("building_train_7", "fairbanks_7"),
    ("building_train_7", "phoenix_3"),
    ("building_train_7", "singapore_6"),
    ("building_train_8", "atlanta_1"),
    ("building_train_8", "denver_6"),
    ("building_train_8", "fairbanks_8"),
    ("building_train_8", "phoenix_4"),
    ("building_train_8", "singapore_7"),
]


def missing_policies(results_dir: Path, building: str, weather: str) -> list[str]:
    """Policies in this scenario that do not have a summary.json yet.

    The harness writes one summary.json per policy as each policy finishes,
    so a scenario interrupted by a VM restart keeps the policies that
    completed. Only the missing ones are re-run.
    """
    return [
        p
        for p in POLICIES
        if not (results_dir / building / weather / p / "summary.json").exists()
    ]


def scenario_done(results_dir: Path, building: str, weather: str) -> bool:
    return not missing_policies(results_dir, building, weather)


def run_scenario(
    building: str, weather: str, policies: list[str], results_dir: Path, log
) -> bool:
    scenario = f"{building}_{weather}"
    env = dict(os.environ)
    env["GUARDED_SCENARIO"] = scenario
    env["GUARDED_LEDGER_PATH"] = str(
        HERE / "guarded_hvac" / "ledger" / f"{scenario}.jsonl"
    )
    cmd = [
        str(HERE / ".venv" / "bin" / "python"),
        "-m",
        "smart_buildings.evaluate",
        "--policies",
        *policies,
        "--buildings",
        building,
        "--weathers",
        weather,
        "--steps",
        "8640",
        "--results-dir",
        str(results_dir),
    ]
    start = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] START {scenario}", flush=True)
    log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] START {scenario}\n")
    log.flush()
    proc = subprocess.run(
        cmd,
        cwd=HERE,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    elapsed = time.time() - start
    if proc.returncode == 0 and scenario_done(results_dir, building, weather):
        print(
            f"[{time.strftime('%H:%M:%S')}] DONE  {scenario} in {elapsed/60:.1f} min",
            flush=True,
        )
        log.write(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] DONE {scenario} in {elapsed/60:.1f} min\n"
        )
        log.flush()
        return True
    print(
        f"[{time.strftime('%H:%M:%S')}] FAIL  {scenario} rc={proc.returncode}",
        flush=True,
    )
    log.write(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FAIL {scenario} rc={proc.returncode}\n"
        f"{proc.stderr[-2000:]}\n"
    )
    log.flush()
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("buildings", nargs="+")
    parser.add_argument("--results-dir", default=str(HERE / "results"))
    parser.add_argument("--log", default=None)
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log) if args.log else HERE / f"eval_{args.buildings[0]}.log"
    log = open(log_path, "a")

    jobs = [(b, w) for b, w in SCENARIOS if b in args.buildings]
    done = sum(1 for b, w in jobs if scenario_done(results_dir, b, w))
    print(
        f"{len(jobs)} scenarios, {done} already complete, {len(jobs)-done} to run",
        flush=True,
    )
    log.write(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {len(jobs)} scenarios, "
        f"{done} done, {len(jobs)-done} to run\n"
    )
    log.flush()

    failed = []
    for building, weather in jobs:
        missing = missing_policies(results_dir, building, weather)
        if not missing:
            continue
        if not run_scenario(building, weather, missing, results_dir, log):
            failed.append(f"{building}_{weather}")

    log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] FINISHED. Failed: {failed}\n")
    log.close()
    print(f"FINISHED. Failed: {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
