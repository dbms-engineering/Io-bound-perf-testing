# Control - A/A test: three identical configurations (must show no difference)

- machine: Apple M3 (arm64, 8 logical CPUs), macOS-27.0.1-arm64-arm-64bit
- toolchain `stable`: rustc 1.90.0 (1159e78c4 2025-09-14)
- rounds: 60 measured (+3 warm-up), master seed 1349543229, server {"start": true, "root": "data/pages", "host": "127.0.0.1", "port": 18080, "delay_us": 1000}
- alpha = 0.05, Bonferroni m = 3 -> alpha_c = 1.67e-02; normality alpha = 0.01; outliers: 1.5 x IQR, fences `pooled`

## 1. Per-configuration summary (after outlier removal)

| configuration | n raw | outliers | mean ms | std ms | CV % | min ms | median ms | normaltest p | normal? | drift rho (p) |
|---|---|---|---|---|---|---|---|---|---|---|
| thread-C | 60 | 7 | 316.575 | 18.540 | 5.86 | 301.846 | 309.170 | 2.10e-06 | no | +0.44 (4.26e-04) |
| thread-A | 60 | 10 | 312.764 | 11.556 | 3.69 | 301.774 | 308.312 | 1.12e-06 | no | +0.37 (0.003) |
| thread-B | 60 | 9 | 313.459 | 10.842 | 3.46 | 301.961 | 309.318 | 5.24e-05 | no | +0.37 (0.004) |

## 2. Pairwise hypothesis tests

| row | column | n row/col | normal row/col | test | p-value | significant (p < alpha_c) | compared | rel. diff | rank-sum p (double check) |
|---|---|---|---|---|---|---|---|---|---|
| thread-A | thread-B | 50/51 | no/no | Wilcoxon rank-sum | 0.495 | no | min | -0.062% | 0.495 |
| thread-A | thread-C | 50/50 | no/no | Wilcoxon rank-sum | 0.796 | no | min | -0.024% | 0.796 |
| thread-B | thread-C | 51/52 | no/no | Wilcoxon rank-sum | 0.642 | no | min | +0.038% | 0.642 |

## 3. Relative-performance matrices (paper Table II format)

Cell = how the *column* configuration performs relative to the *row*: ((t_row - t_col) / min(t_row, t_col)) x 100; positive = column faster; "No diff." = not significant after Bonferroni correction.

| row \ column | thread-A | thread-B | thread-C |
|---|---|---|---|
| **thread-A** | 0 | No diff. | No diff. |
| **thread-B** |  | 0 | No diff. |
| **thread-C** |  |  | 0 |

