"""Guarded adaptive HVAC policy for the NeurIPS 2026 Smart Buildings
Competition, round 1.

This is an adaptive, rule-based controller, not a reinforcement-learning
agent. It is built on the strongest shipped baseline, ``pid_water``, with
three adaptive improvements and the Recall policy engine wrapped around it
as a safety guard (see guard.py).

Adaptive improvements over ``pid_water``:

1. Worst-zone tracking. ``pid_water`` drives each air handler from the
   average temperature of its zones, but the comfort penalty is unbounded
   in the worst zone's deviation. One zone 10 K out costs far more than ten
   zones 1 K out, and an average can hide exactly that. This policy drives
   each handler from its worst zone instead.

2. Sensor band. The reward judges each zone against its own heating and
   cooling setpoint sensors, so this policy reads the band from those
   sensors instead of rebuilding it from the hour of day. Where a
   reconstructed band disagrees with the sensors, the controller either
   conditions a zone the reward already considers comfortable, which is
   cost for no benefit, or neglects one it does not.

3. Occupancy-aware scheduling. The comfort charge is weighted by occupancy,
   so conditioning an empty building is pure cost. When the building is
   unoccupied and comfort mode is not due within the hour, the air handlers
   shut down. When comfort mode is due within the hour, the controller
   pre-conditions against the comfort band instead of waiting for the band
   to snap over at the start of work hours.

The guard (guard.py) then checks every proposed action against the
remembered rules before it is issued: an allowlist per device, a slew-rate
cap on the air handlers' supply-air temperature while running, a daily
energy budget, a confirm threshold against the measured zone error, and an
unsafe-off rule. A shadow instance of the shipped ``pid_water`` baseline
runs alongside and supplies the safe fallback action.

Occupancy note: the local harness normalizes the occupancy sensor as
(n - 125) / 126, so the occupant count is recovered as obs * 126 + 125.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np

from smart_buildings.baselines.pid_plus import PIDWaterResetPolicy

from guarded_hvac.guard import Guard


class GuardedPolicy(PIDWaterResetPolicy):
    """Adaptive controller with the Recall policy engine as a safety guard."""

    # Turn on the two refinements the shipped chain leaves off: worst-zone
    # tracking in the air-handler loop, and the per-zone sensor band.
    USE_WORST_ZONE = True
    USE_SENSOR_BAND = True

    def __init__(self, building_meta_data, action_spec):
        super().__init__(building_meta_data, action_spec)
        self._meta = building_meta_data

        names = list(self.field_names)
        self._occ_idx = names.index("num_occupants") if "num_occupants" in names else None
        self._comfort_now_idx = (
            names.index("comfort_mode_now") if "comfort_mode_now" in names else None
        )
        self._comfort_soon_idx = (
            names.index("comfort_mode_soon") if "comfort_mode_soon" in names else None
        )

        # Shadow baseline: the shipped pid_water controller, run in parallel
        # on the same observation stream, so the guard always has a safe
        # fallback action to fall back to.
        self._baseline = PIDWaterResetPolicy(building_meta_data, action_spec)

        ledger_path = os.environ.get("GUARDED_LEDGER_PATH")
        scenario = os.environ.get("GUARDED_SCENARIO", "unknown")
        if ledger_path is None:
            ledger_path = f"guarded_hvac/ledger/{scenario}.jsonl"
        self.guard = Guard(
            n_discrete=self.n_discrete,
            n_continuous=self.n_continuous,
            temp_indices=self.temp_indices,
            pressure_indices=self.pressure_indices,
            recirculation_indices=self.recirculation_indices,
            water_indices=self.water_indices,
            zone_action_indices=self.zone_action_indices,
            n_ahus=self.n_ahu,
            daily_budget_fraction=float(
                os.environ.get("GUARDED_DAILY_BUDGET", "0.8")
            ),
            confirm_threshold=float(os.environ.get("GUARDED_CONFIRM", "0.8")),
            ledger_path=ledger_path,
        )

    @property
    def name(self) -> str:
        return "guarded"

    def _occupancy(self, obs: np.ndarray) -> float:
        if self._occ_idx is None:
            return 1.0
        return float(obs[self._occ_idx]) * 126.0 + 125.0

    def _zone_errors(self, obs: np.ndarray, low: float, high: float):
        """Per-zone signed deadband error in K, and per-AHU worst errors.

        Positive means the zone is below its heating setpoint (needs heat),
        negative means above its cooling setpoint (needs cooling). The band
        is each zone's own sensor band where available, else the schedule
        band passed in.
        """
        zone_errors: dict[str, float] = {}
        ahu_errors: list[float] = []
        worst = 0.0
        for ctrl in self.ahu_controllers:
            ahu_worst = 0.0
            for vav_id, obs_idx, _ in ctrl["zones"]:
                lo, hi = self._zone_band(obs, vav_id, low, high)
                err = self._deadband_error(
                    self._denormalize_zone_temp(obs[obs_idx]), lo, hi
                )
                zone_errors[vav_id] = err
                if abs(err) > abs(ahu_worst):
                    ahu_worst = err
                if abs(err) > abs(worst):
                    worst = err
            ahu_errors.append(ahu_worst)
        return zone_errors, ahu_errors, worst

    def get_action(self, obs: np.ndarray) -> dict[str, Any]:
        hour, day = self._get_hour_and_day(obs)
        is_work = day < 5 and self.morning_start_hour <= hour < self.evening_start_hour
        low, high = self.comfort_temp_window if is_work else self.eco_temp_window

        comfort_soon = (
            bool(obs[self._comfort_soon_idx] > 0.5)
            if self._comfort_soon_idx is not None
            else False
        )
        occupants = self._occupancy(obs)

        # Pre-conditioning: when comfort mode is due within the hour, run
        # against the comfort band now instead of waiting for the band to
        # snap over at the start of work hours.
        if comfort_soon and not is_work:
            saved_eco = self.eco_temp_window
            self.eco_temp_window = self.comfort_temp_window
            try:
                proposed = super().get_action(obs)
            finally:
                self.eco_temp_window = saved_eco
            low, high = self.comfort_temp_window
        else:
            proposed = super().get_action(obs)

        # Occupancy-aware shutdown: an empty building with no comfort due
        # is pure cost. Propose the plant off; the guard still enforces its
        # own rules on top, and the unsafe-off rule exempts this case.
        if occupants < 1.0 and not comfort_soon:
            continuous = np.zeros(self.n_continuous, dtype=np.float32)
            discrete = np.zeros(self.n_discrete, dtype=np.int32)
            for idx in self.temp_indices:
                continuous[idx] = -1.0
            for idx in self.pressure_indices:
                continuous[idx] = -1.0
            for idx in self.recirculation_indices:
                continuous[idx] = 1.0
            for fields in self.zone_action_indices.values():
                d = fields.get("supply_air_damper_percentage_command")
                if d is not None:
                    continuous[d] = -1.0
                r = fields.get("reheat_valve_percentage_command")
                if r is not None:
                    continuous[r] = -1.0
            proposed = {
                "continuous_action": continuous,
                "discrete_action": discrete,
            }

        baseline = self._baseline.get_action(obs)

        zone_errors, ahu_errors, worst = self._zone_errors(obs, low, high)

        continuous, discrete = self.guard.check(
            proposed_continuous=proposed["continuous_action"],
            proposed_discrete=proposed["discrete_action"],
            baseline_continuous=baseline["continuous_action"],
            baseline_discrete=baseline["discrete_action"],
            zone_errors=zone_errors,
            ahu_errors=ahu_errors,
            worst_zone_error=worst,
            occupants=occupants,
            comfort_soon=comfort_soon,
        )
        return {"continuous_action": continuous, "discrete_action": discrete}
