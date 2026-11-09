# NeurIPS 2026 Smart Buildings, round 1: local evaluation results

Local harness, 8,640-step (30-day) episodes on the 30 shipped training scenarios. The leaderboard metric is the MAE of the mean per-step reward against zero; lower is better. The reward is never positive, so the MAE is the absolute value of the mean per-step reward.

Scenarios completed: 30 of 30.

## Leaderboard metric (MAE of mean per-step reward, lower is better)

| policy | scenarios | mean MAE | best scenario MAE | worst scenario MAE |
|---|---|---|---|---|
| bang_bang | 30 | 0.22453 | 0.07283 | 0.30828 |
| fixed_setpoint | 30 | 0.06550 | 0.01709 | 0.20181 |
| pid | 30 | 0.06782 | 0.01703 | 0.19294 |
| pid_water | 30 | 0.05496 | 0.01689 | 0.21392 |
| guarded | 30 | 0.05604 | 0.00722 | 0.26904 |

## Reward breakdown (mean per scenario, 8,640 steps)

Comfort is the total normalized productivity regret (negative: a cost). Energy and carbon are total normalized costs. The per-step reward is 0.6 * comfort + 0.2 * energy + 0.2 * carbon, all as regret/cost terms.

| policy | comfort regret | energy cost | carbon emission |
|---|---|---|---|
| bang_bang | -1652.60 | 2621.37 | 2120.56 |
| fixed_setpoint | -484.84 | 759.40 | 615.72 |
| pid | -606.69 | 619.57 | 490.36 |
| pid_water | -502.35 | 496.96 | 370.17 |
| guarded | -319.60 | 811.90 | 650.24 |

## Guarded policy vs best baseline (pid_water)

Guarded mean MAE 0.05604 against pid_water 0.05496: a difference of -0.00108 (-1.97%). Lower is better, so the guarded policy is behind by that margin.

## Per-scenario MAE

| scenario | bang_bang | fixed_setpoint | pid | pid_water | guarded |
|---|---|---|---|---|---|
| building_train_1/atlanta_2 | 0.18020 | 0.02695 | 0.02655 | 0.02491 | 0.01786 |
| building_train_1/denver_7 | 0.07283 | 0.03201 | 0.03184 | 0.03100 | 0.00919 |
| building_train_1/fairbanks_1 | 0.28791 | 0.14910 | 0.15060 | 0.21392 | 0.26904 |
| building_train_1/phoenix_5 | 0.26785 | 0.12978 | 0.15312 | 0.13649 | 0.10391 |
| building_train_1/singapore_8 | 0.24924 | 0.02666 | 0.02989 | 0.02835 | 0.04639 |
| building_train_2/atlanta_3 | 0.25433 | 0.02006 | 0.02020 | 0.01998 | 0.01278 |
| building_train_2/denver_8 | 0.20820 | 0.09575 | 0.07052 | 0.04064 | 0.03022 |
| building_train_2/fairbanks_2 | 0.18573 | 0.10143 | 0.09244 | 0.07929 | 0.09059 |
| building_train_2/phoenix_6 | 0.29336 | 0.13920 | 0.10150 | 0.07499 | 0.05707 |
| building_train_2/singapore_1 | 0.27830 | 0.02242 | 0.04613 | 0.02590 | 0.02767 |
| building_train_4/atlanta_5 | 0.24793 | 0.02784 | 0.03013 | 0.02894 | 0.02959 |
| building_train_4/denver_2 | 0.15083 | 0.05917 | 0.06169 | 0.05456 | 0.03361 |
| building_train_4/fairbanks_4 | 0.13766 | 0.03191 | 0.03321 | 0.03280 | 0.00974 |
| building_train_4/phoenix_8 | 0.14816 | 0.03003 | 0.03053 | 0.03026 | 0.00966 |
| building_train_4/singapore_3 | 0.24572 | 0.02840 | 0.04145 | 0.03430 | 0.03176 |
| building_train_5/atlanta_6 | 0.29183 | 0.02054 | 0.04211 | 0.03076 | 0.06315 |
| building_train_5/denver_3 | 0.18275 | 0.11748 | 0.07461 | 0.04410 | 0.03258 |
| building_train_5/fairbanks_5 | 0.20071 | 0.01709 | 0.01703 | 0.01689 | 0.00722 |
| building_train_5/phoenix_1 | 0.12991 | 0.03709 | 0.04449 | 0.03327 | 0.01969 |
| building_train_5/singapore_4 | 0.30072 | 0.02396 | 0.18205 | 0.10990 | 0.12187 |
| building_train_7/atlanta_8 | 0.20763 | 0.06325 | 0.07681 | 0.04829 | 0.03456 |
| building_train_7/denver_5 | 0.24385 | 0.13841 | 0.04465 | 0.03688 | 0.04365 |
| building_train_7/fairbanks_7 | 0.18799 | 0.07352 | 0.07967 | 0.05407 | 0.04938 |
| building_train_7/phoenix_3 | 0.27283 | 0.15897 | 0.05018 | 0.04483 | 0.05187 |
| building_train_7/singapore_6 | 0.26770 | 0.02634 | 0.04581 | 0.03019 | 0.06789 |
| building_train_8/atlanta_1 | 0.20714 | 0.03913 | 0.06337 | 0.03095 | 0.03680 |
| building_train_8/denver_6 | 0.23953 | 0.02044 | 0.02055 | 0.02048 | 0.02587 |
| building_train_8/fairbanks_8 | 0.19752 | 0.08210 | 0.08247 | 0.07740 | 0.15475 |
| building_train_8/phoenix_4 | 0.30828 | 0.20181 | 0.19294 | 0.16021 | 0.12926 |
| building_train_8/singapore_7 | 0.28931 | 0.02420 | 0.09818 | 0.05419 | 0.06358 |

## Shipped baseline returns vs local reproduction

baseline_returns.json ships with the starter kit. The local runs below are the same policies on the same scenarios with the current code. A gap is expected: the kit's git history shows a tracker fix (occupancy queried with VAV IDs, which consumed random draws) landed after the shipped returns were generated, so the random stream, and therefore the trajectories, shifted slightly.

| policy | shipped mean MAE | local mean MAE | gap |
|---|---|---|---|
| bang_bang | 0.22520 | 0.22453 | -0.00067 |
| fixed_setpoint | 0.06592 | 0.06550 | -0.00041 |
| pid | 0.06736 | 0.06782 | +0.00047 |
| pid_water | 0.05414 | 0.05496 | +0.00082 |

## Guard interventions

Total interventions across all scenarios: 148924.

| rule | count |
|---|---|
| slew_clamp | 148921 |
| budget_trip | 3 |

### Interventions per scenario

| scenario | budget_trip | slew_clamp | total |
|---|---|---|---|
| building_train_1_atlanta_2 | 0 | 1397 | 1397 |
| building_train_1_denver_7 | 0 | 1284 | 1284 |
| building_train_1_fairbanks_1 | 3 | 1485 | 1488 |
| building_train_1_phoenix_5 | 0 | 8279 | 8279 |
| building_train_1_singapore_8 | 0 | 3505 | 3505 |
| building_train_2_atlanta_3 | 0 | 1044 | 1044 |
| building_train_2_denver_8 | 0 | 7489 | 7489 |
| building_train_2_fairbanks_2 | 0 | 12195 | 12195 |
| building_train_2_phoenix_6 | 0 | 10636 | 10636 |
| building_train_2_singapore_1 | 0 | 6804 | 6804 |
| building_train_4_atlanta_5 | 0 | 3331 | 3331 |
| building_train_4_denver_2 | 0 | 6236 | 6236 |
| building_train_4_fairbanks_4 | 0 | 1669 | 1669 |
| building_train_4_phoenix_8 | 0 | 1421 | 1421 |
| building_train_4_singapore_3 | 0 | 4519 | 4519 |
| building_train_5_atlanta_6 | 0 | 8118 | 8118 |
| building_train_5_denver_3 | 0 | 7882 | 7882 |
| building_train_5_fairbanks_5 | 0 | 672 | 672 |
| building_train_5_phoenix_1 | 0 | 6047 | 6047 |
| building_train_5_singapore_4 | 0 | 15769 | 15769 |
| building_train_7_atlanta_8 | 0 | 3329 | 3329 |
| building_train_7_denver_5 | 0 | 3367 | 3367 |
| building_train_7_fairbanks_7 | 0 | 4628 | 4628 |
| building_train_7_phoenix_3 | 0 | 3475 | 3475 |
| building_train_7_singapore_6 | 0 | 5702 | 5702 |
| building_train_8_atlanta_1 | 0 | 3857 | 3857 |
| building_train_8_denver_6 | 0 | 1390 | 1390 |
| building_train_8_fairbanks_8 | 0 | 2446 | 2446 |
| building_train_8_phoenix_4 | 0 | 6220 | 6220 |
| building_train_8_singapore_7 | 0 | 4698 | 4698 |
| smoke3 | 0 | 27 | 27 |
