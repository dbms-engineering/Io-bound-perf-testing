# Control - A/A test: three identical configurations (must show no difference)

- machine: Apple M3 (arm64, 8 logical CPUs), macOS-27.0.1-arm64-arm-64bit
- toolchain `stable`: rustc 1.90.0 (1159e78c4 2025-09-14)
- rounds: 60 measured (+3 warm-up), master seed 1345564127, server {"start": true, "root": "data/pages", "host": "127.0.0.1", "port": 18080, "delay_us": 1000}
- alpha = 0.05, Bonferroni m = 3 -> alpha_c = 1.67e-02; normality alpha = 0.01; outliers: 1.5 x IQR, fences `pooled`

## 1. Per-configuration summary (after outlier removal)

| configuration | n raw | outliers | mean ms | std ms | CV % | min ms | median ms | normaltest p | normal? | drift rho (p) |
|---|---|---|---|---|---|---|---|---|---|---|
| thread-B | 60 | 3 | 314.290 | 9.175 | 2.92 | 302.127 | 312.577 | 0.048 | yes | -0.58 (9.70e-07) |
| thread-A | 60 | 6 | 313.443 | 7.415 | 2.37 | 302.324 | 311.969 | 0.019 | yes | -0.61 (2.69e-07) |
| thread-C | 60 | 2 | 314.126 | 9.411 | 3.00 | 301.486 | 311.234 | 0.038 | yes | -0.63 (5.14e-08) |

## 2. Pairwise hypothesis tests

| row | column | n row/col | normal row/col | test | p-value | significant (p < alpha_c) | compared | rel. diff | rank-sum p (double check) |
|---|---|---|---|---|---|---|---|---|---|
| thread-A | thread-B | 57/56 | no/yes | Wilcoxon rank-sum | 0.724 | no | min | +0.065% | 0.724 |
| thread-A | thread-C | 57/58 | no/yes | Wilcoxon rank-sum | 0.448 | no | min | +0.278% | 0.448 |
| thread-B | thread-C | 57/58 | yes/yes | Student t-test | 0.925 | no | mean | +0.052% | 0.851 |

## 3. Relative-performance matrices (paper Table II format)

Cell = how the *column* configuration performs relative to the *row*: ((t_row - t_col) / min(t_row, t_col)) x 100; positive = column faster; "No diff." = not significant after Bonferroni correction.

| row \ column | thread-A | thread-B | thread-C |
|---|---|---|---|
| **thread-A** | 0 | No diff. | No diff. |
| **thread-B** |  | 0 | No diff. |
| **thread-C** |  |  | 0 |

