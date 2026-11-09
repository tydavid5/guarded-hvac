#!/usr/bin/env python3
"""Aggregate the NeurIPS Smart Buildings round 1 evaluation results.

Reads every results/<building>/<weather>/<policy>/summary.json produced by
the shipped evaluate.py harness, plus the guard ledgers, and writes
results.md with the exact numbers: the leaderboard metric (MAE of mean
per-step reward against zero, lower is better) per policy, the comfort,
energy and carbon breakdowns, and the guard intervention counts.

The leaderboard metric is the absolute value of the mean per-step reward
(avg_reward in summary.json), because the reward is never positive and
the MAE is taken against zero. score_leaderboard.py computes the same
quantity from the same summary files; this script reproduces it so the
table can be built without re-running the scorer.

Usage: python3 aggregate_results.py [--results-dir results] [--out results.md]
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICIES = ["bang_bang", "fixed_setpoint", "pid", "pid_water", "guarded"]


def load_summaries(results_dir: Path):
    rows = []
    for summary_path in sorted(results_dir.glob("*/*/*/summary.json")):
        building, weather, policy = summary_path.parts[-4:-1]
        with open(summary_path) as f:
            s = json.load(f)
        rows.append(
            {
                "building": building,
                "weather": weather,
                "policy": policy,
                "total_reward": s["total_reward"],
                "steps": s["total_steps"],
                "avg_reward": s["avg_reward"],
                "mae": abs(s["avg_reward"]),
                "comfort_regret": s["total_normalized_productivity_regret"],
                "energy_cost": s["total_normalized_energy_cost"],
                "carbon": s["total_normalized_carbon_emission"],
                "avg_occupancy": s["avg_occupancy"],
            }
        )
    return rows


def load_ledger_counts(ledger_dir: Path):
    counts = collections.Counter()
    per_scenario = {}
    for path in sorted(ledger_dir.glob("*.jsonl")):
        scenario = path.stem
        c = collections.Counter()
        for line in open(path):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            c[row["rule"]] += 1
        per_scenario[scenario] = dict(c)
        counts.update(c)
    return counts, per_scenario


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default=str(HERE / "results"))
    parser.add_argument("--ledger-dir", default=str(HERE / "guarded_hvac" / "ledger"))
    parser.add_argument("--out", default=str(HERE / "results.md"))
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    rows = load_summaries(results_dir)
    scenarios = sorted({(r["building"], r["weather"]) for r in rows})
    print(f"{len(rows)} policy runs across {len(scenarios)} scenarios")

    shipped = {}
    shipped_path = HERE / "baseline_returns.json"
    if shipped_path.exists():
        with open(shipped_path) as f:
            shipped = json.load(f)

    lines = []
    lines.append("# NeurIPS 2026 Smart Buildings, round 1: local evaluation results")
    lines.append("")
    lines.append(
        "Local harness, 8,640-step (30-day) episodes on the 30 shipped training "
        "scenarios. The leaderboard metric is the MAE of the mean per-step "
        "reward against zero; lower is better. The reward is never positive, "
        "so the MAE is the absolute value of the mean per-step reward."
    )
    lines.append("")
    lines.append(f"Scenarios completed: {len(scenarios)} of 30.")
    lines.append("")

    # Per-policy table.
    lines.append("## Leaderboard metric (MAE of mean per-step reward, lower is better)")
    lines.append("")
    lines.append("| policy | scenarios | mean MAE | best scenario MAE | worst scenario MAE |")
    lines.append("|---|---|---|---|---|")
    policy_stats = {}
    for policy in POLICIES:
        pr = [r for r in rows if r["policy"] == policy]
        if not pr:
            lines.append(f"| {policy} | 0 | not run | | |")
            continue
        maes = [r["mae"] for r in pr]
        policy_stats[policy] = {
            "n": len(pr),
            "mean_mae": mean(maes),
            "best": min(maes),
            "worst": max(maes),
            "mean_comfort_regret": mean([r["comfort_regret"] for r in pr]),
            "mean_energy": mean([r["energy_cost"] for r in pr]),
            "mean_carbon": mean([r["carbon"] for r in pr]),
        }
        lines.append(
            f"| {policy} | {len(pr)} | {mean(maes):.5f} | {min(maes):.5f} | {max(maes):.5f} |"
        )
    lines.append("")

    # Breakdown table.
    lines.append("## Reward breakdown (mean per scenario, 8,640 steps)")
    lines.append("")
    lines.append(
        "Comfort is the total normalized productivity regret (negative: a cost). "
        "Energy and carbon are total normalized costs. The per-step reward is "
        "0.6 * comfort + 0.2 * energy + 0.2 * carbon, all as regret/cost terms."
    )
    lines.append("")
    lines.append("| policy | comfort regret | energy cost | carbon emission |")
    lines.append("|---|---|---|---|")
    for policy in POLICIES:
        st = policy_stats.get(policy)
        if not st:
            lines.append(f"| {policy} | not run | | |")
            continue
        lines.append(
            f"| {policy} | {st['mean_comfort_regret']:.2f} | "
            f"{st['mean_energy']:.2f} | {st['mean_carbon']:.2f} |"
        )
    lines.append("")

    # Guarded vs best baseline.
    if "guarded" in policy_stats and "pid_water" in policy_stats:
        g = policy_stats["guarded"]["mean_mae"]
        b = policy_stats["pid_water"]["mean_mae"]
        diff = b - g
        pct = 100.0 * diff / b if b else 0.0
        lines.append("## Guarded policy vs best baseline (pid_water)")
        lines.append("")
        lines.append(
            f"Guarded mean MAE {g:.5f} against pid_water {b:.5f}: "
            f"a difference of {diff:+.5f} ({pct:+.2f}%). "
            + ("Lower is better, so the guarded policy wins by that margin."
               if diff > 0 else
               "Lower is better, so the guarded policy is behind by that margin.")
        )
        lines.append("")

    # Per-scenario table.
    lines.append("## Per-scenario MAE")
    lines.append("")
    header = "| scenario | " + " | ".join(POLICIES) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(POLICIES) + 1))
    for building, weather in scenarios:
        cells = []
        for policy in POLICIES:
            match = [r for r in rows if r["building"] == building
                     and r["weather"] == weather and r["policy"] == policy]
            cells.append(f"{match[0]['mae']:.5f}" if match else "not run")
        lines.append(f"| {building}/{weather} | " + " | ".join(cells) + " |")
    lines.append("")

    # Shipped baseline comparison (reproduction check).
    if shipped:
        lines.append("## Shipped baseline returns vs local reproduction")
        lines.append("")
        lines.append(
            "baseline_returns.json ships with the starter kit. The local runs "
            "below are the same policies on the same scenarios with the current "
            "code. A gap is expected: the kit's git history shows a tracker fix "
            "(occupancy queried with VAV IDs, which consumed random draws) "
            "landed after the shipped returns were generated, so the random "
            "stream, and therefore the trajectories, shifted slightly."
        )
        lines.append("")
        lines.append("| policy | shipped mean MAE | local mean MAE | gap |")
        lines.append("|---|---|---|---|")
        for policy in ["bang_bang", "fixed_setpoint", "pid", "pid_water"]:
            shipped_maes = []
            for key, vals in shipped.items():
                if policy in vals:
                    shipped_maes.append(abs(vals[policy] / 8640.0))
            local = policy_stats.get(policy, {})
            if shipped_maes and local:
                sm = mean(shipped_maes)
                lm = local["mean_mae"]
                lines.append(
                    f"| {policy} | {sm:.5f} | {lm:.5f} | {lm - sm:+.5f} |"
                )
        lines.append("")

    # Guard ledger.
    ledger_dir = Path(args.ledger_dir)
    counts, per_scenario = load_ledger_counts(ledger_dir)
    lines.append("## Guard interventions")
    lines.append("")
    total = sum(counts.values())
    lines.append(f"Total interventions across all scenarios: {total}.")
    lines.append("")
    lines.append("| rule | count |")
    lines.append("|---|---|")
    for rule, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {rule} | {n} |")
    lines.append("")
    if per_scenario:
        lines.append("### Interventions per scenario")
        lines.append("")
        lines.append("| scenario | " + " | ".join(sorted(counts)) + " | total |")
        lines.append("|" + "---|" * (len(counts) + 2))
        for scenario in sorted(per_scenario):
            c = per_scenario[scenario]
            cells = [str(c.get(rule, 0)) for rule in sorted(counts)]
            lines.append(
                f"| {scenario} | " + " | ".join(cells) + f" | {sum(c.values())} |"
            )
        lines.append("")

    out = Path(args.out)
    out.write_text("\n".join(lines))
    print(f"Wrote {out} ({len(rows)} runs, {len(scenarios)} scenarios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
