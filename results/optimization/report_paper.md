# Experiment 2 - optimization levels x toolchain, process-pool crawler (paper Table IV)

- machine: Apple M3 (arm64, 8 logical CPUs), macOS-27.0.1-arm64-arm-64bit
- toolchain `nightly`: rustc 1.94.0-nightly (a6525d526 2025-12-21)
- toolchain `stable`: rustc 1.90.0 (1159e78c4 2025-09-14)
- rounds: 60 measured (+3 warm-up), master seed 1278199798, server {"start": true, "root": "data/pages", "host": "127.0.0.1", "port": 18080, "delay_us": 1000}
- alpha = 0.05, Bonferroni m = 12 -> alpha_c = 4.17e-03; normality alpha = 0.01; outliers: 1.5 x IQR, fences `per-group`

## 1. Per-configuration summary (after outlier removal)

| configuration | n raw | outliers | mean ms | std ms | CV % | min ms | median ms | normaltest p | normal? | drift rho (p) |
|---|---|---|---|---|---|---|---|---|---|---|
| nightly-O2 | 60 | 4 | 314.043 | 8.752 | 2.79 | 305.132 | 311.152 | 0.004 | no | -0.27 (0.036) |
| stable-O3 | 60 | 4 | 312.586 | 6.887 | 2.20 | 304.547 | 310.800 | 6.14e-04 | no | -0.29 (0.023) |
| stable-O1 | 60 | 3 | 314.334 | 8.442 | 2.69 | 305.682 | 310.556 | 0.007 | no | -0.19 (0.136) |
| stable-O0 | 60 | 5 | 340.019 | 11.505 | 3.38 | 328.574 | 335.010 | 0.005 | no | -0.22 (0.091) |
| stable-O2 | 60 | 8 | 310.614 | 4.785 | 1.54 | 304.215 | 309.423 | 0.011 | yes | -0.15 (0.262) |
| nightly-O3 | 60 | 4 | 311.285 | 6.381 | 2.05 | 303.887 | 309.374 | 0.008 | no | -0.09 (0.476) |
| nightly-O1 | 60 | 2 | 313.564 | 7.568 | 2.41 | 305.224 | 310.259 | 0.006 | no | -0.21 (0.115) |
| nightly-O0 | 60 | 5 | 332.364 | 8.535 | 2.57 | 322.537 | 330.404 | 0.002 | no | -0.16 (0.236) |

## 2. Pairwise hypothesis tests

| row | column | n row/col | normal row/col | test | p-value | significant (p < alpha_c) | compared | rel. diff | rank-sum p (double check) |
|---|---|---|---|---|---|---|---|---|---|
| stable-O0 | stable-O1 | 55/57 | no/no | Wilcoxon rank-sum | 1.06e-17 | **yes** | min | +7.489% | 1.06e-17 |
| stable-O0 | stable-O2 | 55/52 | no/yes | Wilcoxon rank-sum | 5.10e-19 | **yes** | min | +8.007% | 5.10e-19 |
| stable-O0 | stable-O3 | 55/56 | no/no | Wilcoxon rank-sum | 1.03e-18 | **yes** | min | +7.889% | 1.03e-18 |
| stable-O1 | stable-O2 | 57/52 | no/yes | Wilcoxon rank-sum | 0.038 | no | min | +0.482% | 0.038 |
| stable-O1 | stable-O3 | 57/56 | no/no | Wilcoxon rank-sum | 0.333 | no | min | +0.373% | 0.333 |
| stable-O2 | stable-O3 | 52/56 | yes/no | Wilcoxon rank-sum | 0.213 | no | min | -0.109% | 0.213 |
| nightly-O0 | nightly-O1 | 55/58 | no/no | Wilcoxon rank-sum | 1.06e-16 | **yes** | min | +5.672% | 1.06e-16 |
| nightly-O0 | nightly-O2 | 55/56 | no/no | Wilcoxon rank-sum | 2.16e-14 | **yes** | min | +5.704% | 2.16e-14 |
| nightly-O0 | nightly-O3 | 55/56 | no/no | Wilcoxon rank-sum | 1.03e-18 | **yes** | min | +6.137% | 1.03e-18 |
| nightly-O1 | nightly-O2 | 58/56 | no/no | Wilcoxon rank-sum | 0.930 | no | min | +0.030% | 0.930 |
| nightly-O1 | nightly-O3 | 58/56 | no/no | Wilcoxon rank-sum | 0.067 | no | min | +0.440% | 0.067 |
| nightly-O2 | nightly-O3 | 56/56 | no/no | Wilcoxon rank-sum | 0.067 | no | min | +0.410% | 0.067 |

## 3. Relative-performance matrices (paper Table II format)

Cell = how the *column* configuration performs relative to the *row*: ((t_row - t_col) / min(t_row, t_col)) x 100; positive = column faster; "No diff." = not significant after Bonferroni correction.

| row \ column | stable-O0 | stable-O1 | stable-O2 | stable-O3 |
|---|---|---|---|---|
| **stable-O0** | 0 | +7.49% | +8.01% | +7.89% |
| **stable-O1** |  | 0 | No diff. | No diff. |
| **stable-O2** |  |  | 0 | No diff. |
| **stable-O3** |  |  |  | 0 |

| row \ column | nightly-O0 | nightly-O1 | nightly-O2 | nightly-O3 |
|---|---|---|---|---|
| **nightly-O0** | 0 | +5.67% | +5.70% | +6.14% |
| **nightly-O1** |  | 0 | No diff. | No diff. |
| **nightly-O2** |  |  | 0 | No diff. |
| **nightly-O3** |  |  |  | 0 |

