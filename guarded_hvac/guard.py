"""The safety guard: a port of the Recall policy engine to HVAC control.

The Recall engine, as built for Recall Wallet, Recall Vault and Otari Guard,
checks every proposed action against remembered rules before it is issued:

  - a per-transaction cap (here: a per-action cap, a slew-rate limit on how
    far an air handler's supply-air temperature may move in one step while
    running),
  - a daily cap (here: a daily energy budget cap on commanded plant effort),
  - an allowlist (here: safe ranges per device, and rules about which
    actions are ever allowed),
  - a confirm threshold (here: if the proposed action pushes against the
    measured zone error beyond the threshold, the guard falls back to the
    safe baseline action instead),
  - a ledger (here: every intervention is written to a JSONL ledger with
    its reason, so the paper can report exactly what the guard did).

The guard never invents an action. It only clamps, replaces with the safe
baseline, or forces the plant to idle. Every intervention is logged.

Two design decisions, stated plainly. First, the guard judges a proposal
against the measured zone error, not against the baseline controller: the
baseline is mean-based and can sit idle while one zone runs away, so
disagreeing with the baseline is exactly what the adaptive layer is for.
Second, the slew cap applies only to an air handler's supply-air
temperature while that handler is already running; a cold start is allowed
its full move, because blunting a start is how a zone ends up in the
quadratic penalty region. The hot-water temperature is excluded from the
cap: the shipped water reset switches it between -1 when the loop is idle
and the reset value when it is heating, so a per-step cap on it would fight
the mode switch instead of catching hunting.
"""

from __future__ import annotations

import json
from pathlib import Path


class Guard:
    """Checks a proposed HVAC action against the remembered rules.

    Parameters mirror the Recall engine's four rules plus the ledger:

    - ``slew_cap``: max change per step, in normalized units, for an air
      handler's supply-air temperature while the handler is already running.
    - ``daily_budget_fraction``: fraction of the maximum possible daily
      commanded effort the plant may spend in one simulated day. When the
      budget is spent, the guard forces eco mode unless a zone is in the
      quadratic penalty region (more than 5 K outside its band).
    - ``confirm_threshold``: if the proposed supply-air temperature pushes
      against the measured zone error by more than this (normalized units),
      the guard falls back to the baseline for that air handler.
    - ``ledger_path``: JSONL file every intervention is appended to, or
      None to keep the ledger in memory only.

    Deliberately not included: a minimum on/off time. Short-cycling
    protection is real HVAC practice, but this simulator models no restart
    cost, and an early version of the guard showed the hold interacting
    badly with the slew cap: holding a handler on with its idle setpoints
    left it "running" at the coldest supply temperature, and the slew cap
    then throttled its recovery for several steps. A guard rule must not
    manufacture the violation the next rule has to catch, so the hold was
    removed rather than patched around.
    """

    SLEW_CAP_TEMP = 0.5

    # A zone this far outside its band is in the quadratic penalty region,
    # where the comfort charge grows without bound. The budget cap never
    # overrides comfort for such a zone.
    QUADRATIC_K = 5.0

    def __init__(
        self,
        n_discrete: int,
        n_continuous: int,
        temp_indices: list[int],
        pressure_indices: list[int],
        recirculation_indices: list[int],
        water_indices: list[int],
        zone_action_indices: dict,
        n_ahus: int,
        daily_budget_fraction: float = 0.8,
        confirm_threshold: float = 0.8,
        ledger_path: str | Path | None = None,
    ):
        self.n_discrete = n_discrete
        self.n_continuous = n_continuous
        self.temp_indices = list(temp_indices)
        self.pressure_indices = list(pressure_indices)
        self.recirculation_indices = list(recirculation_indices)
        self.water_indices = list(water_indices)
        self.zone_action_indices = zone_action_indices
        self.n_ahus = n_ahus
        self.daily_budget_fraction = daily_budget_fraction
        self.confirm_threshold = confirm_threshold

        # Maximum commanded effort per step, used to size the daily budget.
        n_zones = len(zone_action_indices)
        self._max_effort_per_step = self.n_ahus * 1.0 + 0.3 + n_zones * 0.1
        self._daily_budget = (
            self.daily_budget_fraction * self._max_effort_per_step * 288.0
        )

        self._prev_continuous = None
        self._prev_discrete = None
        self._step = 0
        self._day = 0
        self._day_effort = 0.0
        self._budget_tripped_today = False

        self.counters: dict[str, int] = {
            "allowlist_clamp": 0,
            "slew_clamp": 0,
            "budget_trip": 0,
            "confirm_fallback": 0,
            "unsafe_off_prevented": 0,
        }
        self.ledger: list[dict] = []
        self.ledger_path = Path(ledger_path) if ledger_path else None
        if self.ledger_path is not None:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self.ledger_path.write_text("")

    # -- ledger ---------------------------------------------------------

    def _log(self, rule: str, detail: dict) -> None:
        self.counters[rule] += 1
        entry = {"step": self._step, "day": self._day, "rule": rule, **detail}
        self.ledger.append(entry)
        if self.ledger_path is not None:
            with open(self.ledger_path, "a") as f:
                f.write(json.dumps(entry) + "\n")

    # -- effort accounting ----------------------------------------------

    def _effort(self, continuous, discrete) -> float:
        """Commanded plant effort this step, a proxy for energy use.

        One unit per running air handler scaled by its fan pressure, plus
        the water loop and a small term per open reheat valve. This is a
        proxy, not a meter reading: the guard only sees commands, not the
        reward, so it budgets what it commands.
        """
        effort = 0.0
        for i in range(self.n_ahus):
            if i < len(discrete) and discrete[i] == 1:
                p = 0.0
                if i < len(self.pressure_indices):
                    p = (float(continuous[self.pressure_indices[i]]) + 1.0) / 2.0
                effort += 0.3 + 0.7 * p
        if self.n_discrete > 0 and discrete[-1] == 1:
            effort += 0.3
        for fields in self.zone_action_indices.values():
            idx = fields.get("reheat_valve_percentage_command")
            if idx is not None:
                effort += 0.1 * (float(continuous[idx]) + 1.0) / 2.0
        return effort

    # -- the check ------------------------------------------------------

    def check(
        self,
        proposed_continuous,
        proposed_discrete,
        baseline_continuous,
        baseline_discrete,
        zone_errors: dict[str, float],
        ahu_errors: list[float],
        worst_zone_error: float,
        occupants: float = 1.0,
        comfort_soon: bool = False,
    ):
        """Check a proposed action against the rules, return the issued action.

        Args:
            proposed_continuous, proposed_discrete: the adaptive controller's
                action for this step.
            baseline_continuous, baseline_discrete: the safe baseline
                controller's action for the same observation.
            zone_errors: VAV id -> signed deadband error in K (positive means
                the zone is below its heating setpoint).
            ahu_errors: per air handler, the worst signed zone error among
                the zones it serves, in K.
            worst_zone_error: the largest-magnitude zone error in the
                building, in K.
            occupants: current building occupant count. An empty building
                with no comfort due is allowed to sit idle even with zones
                outside their band, because the comfort charge is weighted
                by occupancy.
            comfort_soon: whether comfort mode is due within the hour.

        Returns:
            (continuous, discrete) as float32 / int32 numpy arrays.
        """
        import numpy as np

        continuous = np.array(proposed_continuous, dtype=np.float32)
        discrete = np.array(proposed_discrete, dtype=np.int32)
        baseline_c = np.array(baseline_continuous, dtype=np.float32)
        baseline_d = np.array(baseline_discrete, dtype=np.int32)

        # Day rollover: 288 steps per simulated day.
        day = self._step // 288
        if day != self._day:
            self._day = day
            self._day_effort = 0.0
            self._budget_tripped_today = False

        # Rule 1, allowlist: every continuous value inside [-1, 1], and
        # never heat a zone that is above its cooling setpoint. A reheat
        # valve for a hot zone is forced shut.
        for vav, err in zone_errors.items():
            fields = self.zone_action_indices.get(vav, {})
            reheat_idx = fields.get("reheat_valve_percentage_command")
            if reheat_idx is not None and err < 0.0 and continuous[reheat_idx] > -1.0:
                self._log(
                    "allowlist_clamp",
                    {
                        "device": vav,
                        "field": "reheat",
                        "proposed": float(continuous[reheat_idx]),
                        "issued": -1.0,
                        "reason": "zone above its cooling setpoint, heating forbidden",
                    },
                )
                continuous[reheat_idx] = -1.0
        clipped = np.clip(continuous, -1.0, 1.0)
        if not np.array_equal(clipped, continuous):
            n = int(np.sum(clipped != continuous))
            self._log(
                "allowlist_clamp",
                {
                    "device": "plant",
                    "field": "range",
                    "proposed": "out of [-1, 1]",
                    "issued": "clipped",
                    "reason": f"{n} channel(s) outside the normalized range",
                },
            )
            continuous = clipped

        # Rule 2, per-action cap: slew-rate limit on the air handlers'
        # supply-air temperature, and only while the handler was already
        # running and stays running. A cold start, and a shutdown, are
        # allowed their full move: the setpoint of a device that is off is
        # inert. The hot-water temperature is deliberately NOT capped: the
        # shipped water reset switches it between -1 when the loop is idle
        # and the reset value when it is heating, so a per-step cap on it
        # would fight the mode switch instead of catching hunting.
        if self._prev_continuous is not None and self._prev_discrete is not None:
            for i, idx in enumerate(self.temp_indices):
                if (
                    i < len(self._prev_discrete)
                    and self._prev_discrete[i] == 1
                    and i < len(discrete)
                    and discrete[i] == 1
                ):
                    delta = float(continuous[idx] - self._prev_continuous[idx])
                    if abs(delta) > self.SLEW_CAP_TEMP:
                        self._log(
                            "slew_clamp",
                            {
                                "device": f"ahu_{i}",
                                "field": "supply_air_temperature",
                                "proposed": float(continuous[idx]),
                                "issued": float(
                                    self._prev_continuous[idx]
                                    + np.clip(delta, -self.SLEW_CAP_TEMP, self.SLEW_CAP_TEMP)
                                ),
                                "reason": "setpoint moved too far in one step while running",
                            },
                        )
                        continuous[idx] = self._prev_continuous[idx] + np.clip(
                            delta, -self.SLEW_CAP_TEMP, self.SLEW_CAP_TEMP
                        )

        # Rule 3, confirm threshold: the proposal must not push against the
        # measured zone error. If an air handler's proposed supply-air
        # temperature points the opposite way from its worst zone error, and
        # by more than the threshold, the guard falls back to the baseline
        # for that handler. Disagreeing with the baseline is fine; pushing
        # against the measurement is not. A handler that is off is skipped:
        # its setpoint is inert while it is off.
        for i, idx in enumerate(self.temp_indices):
            if i >= len(ahu_errors):
                continue
            if i < len(discrete) and discrete[i] == 0:
                continue
            err = ahu_errors[i]
            u = float(continuous[idx])
            if err != 0.0 and (u > 0) != (err > 0) and abs(u) > self.confirm_threshold:
                self._log(
                    "confirm_fallback",
                    {
                        "device": f"ahu_{i}",
                        "field": "supply_air_temperature",
                        "proposed": u,
                        "issued": float(baseline_c[idx]),
                        "reason": (
                            f"proposal pushes {'cooling' if u < 0 else 'heating'} "
                            f"while its worst zone is {err:.2f} K "
                            f"{'cold' if err > 0 else 'hot'}"
                        ),
                    },
                )
                continuous[idx] = baseline_c[idx]
                if i < len(self.pressure_indices):
                    continuous[self.pressure_indices[i]] = baseline_c[
                        self.pressure_indices[i]
                    ]

        # Rule 3b, unsafe off: the proposal must not switch an air handler
        # off while its own zones are outside their band. That is how a zone
        # runs away into the quadratic penalty region. An empty building
        # with no comfort due is exempt: with no occupants the comfort
        # charge is zero, so sitting idle is authorized, not unsafe.
        occupied = occupants >= 1.0 or comfort_soon
        for i in range(self.n_ahus):
            if i >= len(discrete) or i >= len(ahu_errors):
                continue
            err = ahu_errors[i]
            prev = int(self._prev_discrete[i]) if self._prev_discrete is not None else 1
            if discrete[i] == 0 and prev == 1 and err != 0.0 and occupied:
                self._log(
                    "unsafe_off_prevented",
                    {
                        "device": f"ahu_{i}",
                        "field": "run_command",
                        "proposed": 0,
                        "issued": 1,
                        "reason": (
                            f"handler off while its worst zone is {err:.2f} K "
                            "outside its band; forced on with baseline setpoints"
                        ),
                    },
                )
                discrete[i] = 1
                if i < len(self.temp_indices):
                    continuous[self.temp_indices[i]] = baseline_c[self.temp_indices[i]]
                if i < len(self.pressure_indices):
                    continuous[self.pressure_indices[i]] = baseline_c[
                        self.pressure_indices[i]
                    ]

        # Rule 4, daily energy budget: when the day's commanded effort is
        # spent, force eco mode. The budget never overrides a zone in the
        # quadratic penalty region.
        self._day_effort += self._effort(continuous, discrete)
        if self._day_effort > self._daily_budget and not self._budget_tripped_today:
            self._budget_tripped_today = True
            self._log(
                "budget_trip",
                {
                    "device": "plant",
                    "field": "daily_budget",
                    "proposed": f"day effort {self._day_effort:.1f}",
                    "issued": "eco mode",
                    "reason": (
                        f"daily budget {self._daily_budget:.1f} spent; plant "
                        "idles unless a zone enters the quadratic region"
                    ),
                },
            )
        if self._budget_tripped_today and abs(worst_zone_error) <= self.QUADRATIC_K:
            for i in range(self.n_ahus):
                discrete[i] = 0
                if i < len(self.temp_indices):
                    continuous[self.temp_indices[i]] = -1.0
                if i < len(self.pressure_indices):
                    continuous[self.pressure_indices[i]] = -1.0
            discrete[-1] = 0
            if self.water_indices:
                continuous[self.water_indices[0]] = -1.0

        # Bookkeeping for the next step.
        self._prev_continuous = np.array(continuous, dtype=np.float32)
        self._prev_discrete = np.array(discrete, dtype=np.int32)
        self._step += 1
        return continuous, discrete
