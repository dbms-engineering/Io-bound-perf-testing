# Experiment 3 - target-cpu=native at opt-level 0 (paper Table V, -march=native)

- machine: Apple M3 (arm64, 8 logical CPUs), macOS-27.0.1-arm64-arm-64bit
- toolchain `stable`: rustc 1.90.0 (1159e78c4 2025-09-14)
- rounds: 60 measured (+3 warm-up), master seed 3770795579, server {"start": true, "root": "data/pages", "host": "127.0.0.1", "port": 18080, "delay_us": 1000}
- alpha = 0.05, Bonferroni m = 3 -> alpha_c = 1.67e-02; normality alpha = 0.01; outliers: 1.5 x IQR, fences `pooled`

## 1. Per-configuration summary (after outlier removal)

| configuration | n raw | outliers | mean ms | std ms | CV % | min ms | median ms | normaltest p | normal? | drift rho (p) |
|---|---|---|---|---|---|---|---|---|---|---|
| event-native | 60 | 1 | 409.186 | 59.084 | 14.44 | 342.325 | 389.160 | 0.002 | no | -0.01 (0.968) |
| thread-native | 60 | 5 | 380.082 | 34.768 | 9.15 | 331.155 | 369.305 | 0.010 | no | -0.06 (0.673) |
| process | 60 | 4 | 388.747 | 40.120 | 10.32 | 340.348 | 376.533 | 0.008 | no | -0.02 (0.871) |
| thread | 60 | 4 | 384.431 | 38.443 | 10.00 | 337.406 | 373.673 | 0.008 | no | -0.00 (0.974) |
| event | 60 | 3 | 400.281 | 51.100 | 12.77 | 344.087 | 380.590 | 0.011 | yes | -0.09 (0.477) |
| process-native | 60 | 4 | 392.236 | 36.864 | 9.40 | 340.124 | 392.207 | 0.150 | yes | +0.09 (0.484) |

## 2. Pairwise hypothesis tests

| row | column | n row/col | normal row/col | test | p-value | significant (p < alpha_c) | compared | rel. diff | rank-sum p (double check) |
|---|---|---|---|---|---|---|---|---|---|
| process | process-native | 56/58 | no/yes | Wilcoxon rank-sum | 0.351 | no | min | +0.066% | 0.351 |
| thread | thread-native | 55/56 | yes/no | Wilcoxon rank-sum | 0.802 | no | min | +1.888% | 0.802 |
| event | event-native | 57/58 | yes/no | Wilcoxon rank-sum | 0.483 | no | min | +0.515% | 0.483 |

## 3. Relative-performance matrices (paper Table II format)

Cell = how the *column* configuration performs relative to the *row*: ((t_row - t_col) / min(t_row, t_col)) x 100; positive = column faster; "No diff." = not significant after Bonferroni correction.

| row \ column | process | process-native |
|---|---|---|
| **process** | 0 | No diff. |
| **process-native** |  | 0 |

| row \ column | thread | thread-native |
|---|---|---|
| **thread** | 0 | No diff. |
| **thread-native** |  | 0 |

| row \ column | event | event-native |
|---|---|---|
| **event** | 0 | No diff. |
| **event-native** |  | 0 |

