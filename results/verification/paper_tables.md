# Consistency check of the paper's published tables

Hypotheses for the denominator of the relative difference: `min(t_row,t_col)` (stated in the Table II caption), `max(t_row,t_col)`, `t_row`.

### Table II - crawler implementations

| cell | published | fit: min | fit: max | fit: row |
|---|---|---|---|---|
| process -> thread | +2.2 | +2.15 | +2.18 | +2.18 |
| process -> epoll | +4.4 | +4.45 | +4.42 | +4.42 |
| thread -> epoll | +2.3 | +2.25 | +2.28 | +2.28 |
| **RMS error (pct points)** | | **0.049** | **0.017** | **0.017** |

### Table III - Turbo Boost / Hyper-threading, epoll

| cell | published | fit: min | fit: max | fit: row |
|---|---|---|---|---|
| noTB,noHT -> TB,noHT | +16.95 | +15.893 | +16.950 | +16.913 |
| noTB,noHT -> noTB,HT | +13.68 | +12.195 | +13.679 | +13.716 |
| TB,noHT -> noTB,HT | -3.79 | -3.297 | -3.789 | -3.848 |
| noTB,noHT -> TB,HT | +29.63 | +31.823 | +29.631 | +29.630 |
| TB,noHT -> TB,HT | +15.27 | +13.745 | +15.269 | +15.305 |
| noTB,HT -> TB,HT | +18.48 | +17.495 | +18.480 | +18.444 |
| **RMS error (pct points)** | | **1.395** | **0.001** | **0.038** |

### Table III - Turbo Boost / Hyper-threading, thread pool

| cell | published | fit: min | fit: max | fit: row |
|---|---|---|---|---|
| noTB,noHT -> TB,noHT | +16.28 | +15.145 | +16.313 | +16.310 |
| noTB,noHT -> noTB,HT | +15.35 | +13.995 | +15.316 | +15.319 |
| TB,noHT -> noTB,HT | -1.20 | -1.009 | -1.177 | -1.184 |
| noTB,noHT -> TB,HT | +29.23 | +31.400 | +29.231 | +29.231 |
| TB,noHT -> TB,HT | +15.43 | +14.116 | +15.436 | +15.440 |
| noTB,HT -> TB,HT | +16.44 | +15.268 | +16.432 | +16.429 |
| **RMS error (pct points)** | | **1.352** | **0.022** | **0.020** |

### Table III - Turbo Boost / Hyper-threading, process pool

| cell | published | fit: min | fit: max | fit: row |
|---|---|---|---|---|
| noTB,noHT -> TB,noHT | +16.49 | +15.305 | +16.492 | +16.488 |
| noTB,noHT -> noTB,HT | +15.38 | +14.016 | +15.377 | +15.381 |
| TB,noHT -> noTB,HT | -1.32 | -1.131 | -1.317 | -1.325 |
| noTB,noHT -> TB,HT | +29.55 | +31.767 | +29.551 | +29.551 |
| TB,noHT -> TB,HT | +15.64 | +14.277 | +15.639 | +15.643 |
| noTB,HT -> TB,HT | +16.75 | +15.569 | +16.750 | +16.746 |
| **RMS error (pct points)** | | **1.383** | **0.002** | **0.003** |

## Verdict

- worst-case RMS over Table III: min = 1.39, max = 0.022, row = 0.04 percentage points
- best-fitting denominator: **max**
- => the published matrices are consistent with dividing by the *slower* time (max), not by min(t_row, t_col) as the Table II caption says (dividing by t_row fits almost as well; the only cell that separates the two is `TB,noHT -> noTB,HT`, where the row is the faster one). Taking the first row of Table III as given, the caption formula would put epoll `TB,noHT -> TB,HT` at +10.8% instead of the published +15.27%. The ranking and significance conclusions are unaffected; only the effect sizes change meaning ("X% less time" vs "X% faster").

## Bonferroni arithmetic quoted in the paper

- OK  Sec. V-C: 0.1% difference, p = 2e-5, still significant for m = 100: alpha_c = 0.05/100 = 5.0e-04 -> significant
- OK  Table V: epoll -march=native, p = 0.26, 'statistically insignificant': alpha_c = 0.05/1 = 5.0e-02 -> not significant
- OK  Table V: thread pool -march=native, p = 3e-7: alpha_c = 0.05/100 = 5.0e-04 -> significant
- OK  Table V: process pool -march=native, p = 2e-14: alpha_c = 0.05/100 = 5.0e-04 -> significant
- OK  Table III: all differences p < 1e-7 (m = 6 pairs x 3 crawlers = 18): alpha_c = 0.05/18 = 2.8e-03 -> significant

## Textual consistency

- The abstract names the *Wilcoxon signed-rank* test (paired samples), while Sec. III-A-6 uses the *Wilcoxon rank-sum* test (independent samples). Runs of different configurations are independent and unpaired, so the rank-sum (Mann-Whitney U) test is the correct one; this project uses it.
- Sec. V-A says the distributions 'are normal with p-value = 0.01'. A normality test can only fail to reject normality; read it as 'H0 of normality not rejected at alpha = 0.01'. This project uses alpha_normal = 0.01 for that reason.
