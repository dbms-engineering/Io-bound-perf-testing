# Experiment 1 - crawler implementations (paper Table II)

- machine: Apple M3 (arm64, 8 logical CPUs), macOS-27.0.1-arm64-arm-64bit
- toolchain `stable`: rustc 1.90.0 (1159e78c4 2025-09-14)
- rounds: 60 measured (+3 warm-up), master seed 3910748527, server {"start": true, "root": "data/pages", "host": "127.0.0.1", "port": 18080, "delay_us": 1000}
- alpha = 0.05, Bonferroni m = 3 -> alpha_c = 1.67e-02; normality alpha = 0.01; outliers: 1.5 x IQR, fences `per-group`

## 1. Per-configuration summary (after outlier removal)

| configuration | n raw | outliers | mean ms | std ms | CV % | min ms | median ms | normaltest p | normal? | drift rho (p) |
|---|---|---|---|---|---|---|---|---|---|---|
| process | 60 | 1 | 324.758 | 15.968 | 4.92 | 305.248 | 319.859 | 0.014 | yes | -0.32 (0.013) |
| event | 60 | 7 | 311.579 | 7.632 | 2.45 | 301.209 | 311.037 | 0.043 | yes | -0.27 (0.037) |
| thread | 60 | 4 | 315.082 | 11.059 | 3.51 | 301.220 | 313.701 | 0.003 | no | -0.16 (0.218) |

## 2. Pairwise hypothesis tests

| row | column | n row/col | normal row/col | test | p-value | significant (p < alpha_c) | compared | rel. diff | rank-sum p (double check) |
|---|---|---|---|---|---|---|---|---|---|
| process | thread | 59/56 | yes/no | Wilcoxon rank-sum | 4.19e-04 | **yes** | min | +1.337% | 4.19e-04 |
| process | event | 59/53 | yes/yes | Student t-test | 2.83e-07 | **yes** | mean | +4.230% | 5.73e-07 |
| thread | event | 56/53 | no/yes | Wilcoxon rank-sum | 0.133 | no | min | +0.004% | 0.133 |

## 3. Relative-performance matrices (paper Table II format)

Cell = how the *column* configuration performs relative to the *row*: ((t_row - t_col) / min(t_row, t_col)) x 100; positive = column faster; "No diff." = not significant after Bonferroni correction.

| row \ column | process | thread | event |
|---|---|---|---|
| **process** | 0 | +1.34% | +4.23% |
| **thread** |  | 0 | No diff. |
| **event** |  |  | 0 |

