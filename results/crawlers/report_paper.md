# Experiment 1 - crawler implementations (paper Table II)

- machine: Apple M3 (arm64, 8 logical CPUs), macOS-27.0.1-arm64-arm-64bit
- toolchain `stable`: rustc 1.90.0 (1159e78c4 2025-09-14)
- rounds: 60 measured (+3 warm-up), master seed 1069861129, server {"start": true, "root": "data/pages", "host": "127.0.0.1", "port": 18080, "delay_us": 1000}
- alpha = 0.05, Bonferroni m = 3 -> alpha_c = 1.67e-02; normality alpha = 0.01; outliers: 1.5 x IQR, fences `per-group`

## 1. Per-configuration summary (after outlier removal)

| configuration | n raw | outliers | mean ms | std ms | CV % | min ms | median ms | normaltest p | normal? | drift rho (p) |
|---|---|---|---|---|---|---|---|---|---|---|
| thread | 60 | 9 | 307.847 | 6.918 | 2.25 | 301.501 | 305.641 | 1.75e-04 | no | -0.79 (7.68e-14) |
| event | 60 | 8 | 308.497 | 8.739 | 2.83 | 301.022 | 305.441 | 2.03e-06 | no | -0.69 (1.08e-09) |
| process | 60 | 7 | 317.432 | 11.061 | 3.48 | 305.788 | 313.772 | 3.19e-04 | no | -0.77 (7.79e-13) |

## 2. Pairwise hypothesis tests

| row | column | n row/col | normal row/col | test | p-value | significant (p < alpha_c) | compared | rel. diff | rank-sum p (double check) |
|---|---|---|---|---|---|---|---|---|---|
| process | thread | 53/51 | no/no | Wilcoxon rank-sum | 2.51e-08 | **yes** | min | +1.422% | 2.51e-08 |
| process | event | 53/52 | no/no | Wilcoxon rank-sum | 1.19e-08 | **yes** | min | +1.583% | 1.19e-08 |
| thread | event | 51/52 | no/no | Wilcoxon rank-sum | 0.961 | no | min | +0.159% | 0.961 |

## 3. Relative-performance matrices (paper Table II format)

Cell = how the *column* configuration performs relative to the *row*: ((t_row - t_col) / min(t_row, t_col)) x 100; positive = column faster; "No diff." = not significant after Bonferroni correction.

| row \ column | process | thread | event |
|---|---|---|---|
| **process** | 0 | +1.42% | +1.58% |
| **thread** |  | 0 | No diff. |
| **event** |  |  | 0 |

