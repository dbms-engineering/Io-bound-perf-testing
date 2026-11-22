#!/usr/bin/env python3
"""Checks the internal consistency of the numbers published in the paper.

All relative-difference matrices in the paper are derived from a single
execution time per configuration, so the off-diagonal cells are not
independent: given the published values in row 0, the remaining cells are
*determined* by the formula. This makes it possible to identify which formula
was actually used.

The Table II caption states  rel = (t_row - t_col) / min(t_row, t_col) * 100.
The configuration times are fitted under three hypotheses for the denominator
(min, as stated in the caption; max; and t_row), and the script reports how
well each hypothesis reproduces every published cell of Tables II and III.

The script also re-checks the Bonferroni arithmetic quoted in Sec. V-C and Table V.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
from pipeline import bonferroni, relative_difference  # noqa: E402

# Upper-triangular cells: (row, col) mapped to the published value in percent.
TABLE_II = {  # Order: process pool, thread pool, epoll.
    "names": ["process", "thread", "epoll"],
    "cells": {(0, 1): 2.2, (0, 2): 4.4, (1, 2): 2.3},
    "decimals": 1,
}
T3_NAMES = ["noTB,noHT", "TB,noHT", "noTB,HT", "TB,HT"]
TABLE_III = {
    "epoll": {(0, 1): 16.95, (0, 2): 13.68, (1, 2): -3.79, (0, 3): 29.63, (1, 3): 15.27, (2, 3): 18.48},
    "thread pool": {(0, 1): 16.28, (0, 2): 15.35, (1, 2): -1.2, (0, 3): 29.23, (1, 3): 15.43, (2, 3): 16.44},
    "process pool": {(0, 1): 16.49, (0, 2): 15.38, (1, 2): -1.32, (0, 3): 29.55, (1, 3): 15.64, (2, 3): 16.75},
}


def fit(cells: dict, n: int, denominator: str) -> tuple[np.ndarray, dict]:
    """Least-squares fit of log-times (t_0 = 1) to the published cells."""
    def resid(logt):
        t = np.exp(np.concatenate([[0.0], logt]))
        return [relative_difference(t[i], t[j], denominator) - v for (i, j), v in cells.items()]

    sol = least_squares(resid, np.zeros(n - 1))
    t = np.exp(np.concatenate([[0.0], sol.x]))
    pred = {k: relative_difference(t[k[0]], t[k[1]], denominator) for k in cells}
    return t, pred


def report_table(title: str, names: list[str], cells: dict, decimals: int) -> dict[str, float]:
    print(f"\n### {title}\n")
    print("| cell | published | " + " | ".join(f"fit: {d}" for d in ("min", "max", "row")) + " |")
    print("|---|---|---|---|---|")
    preds = {d: fit(cells, len(names), d)[1] for d in ("min", "max", "row")}
    for k, v in cells.items():
        cols = " | ".join(f"{preds[d][k]:+.{decimals + 1}f}" for d in ("min", "max", "row"))
        print(f"| {names[k[0]]} -> {names[k[1]]} | {v:+.{decimals}f} | {cols} |")
    rms = {d: float(np.sqrt(np.mean([(preds[d][k] - v) ** 2 for k, v in cells.items()]))) for d in preds}
    print("| **RMS error (pct points)** | | " + " | ".join(f"**{rms[d]:.3f}**" for d in ("min", "max", "row"))
          + " |")
    return rms


def main() -> int:
    print("# Consistency check of the paper's published tables\n")
    print("Hypotheses for the denominator of the relative difference: "
          "`min(t_row,t_col)` (stated in the Table II caption), `max(t_row,t_col)`, `t_row`.")
    all_rms = {"min": [], "max": [], "row": []}
    r = report_table("Table II - crawler implementations", TABLE_II["names"], TABLE_II["cells"], 1)
    for d in r:
        all_rms[d].append(r[d])
    for crawler, cells in TABLE_III.items():
        r = report_table(f"Table III - Turbo Boost / Hyper-threading, {crawler}", T3_NAMES, cells, 2)
        for d in r:
            all_rms[d].append(r[d])

    t3 = {d: max(v[1:]) for d, v in all_rms.items()}  # Worst Table III fit for each hypothesis.
    best = min(t3, key=t3.get)
    print("\n## Verdict\n")
    print(f"- worst-case RMS over Table III: min = {t3['min']:.2f}, max = {t3['max']:.3f}, row = {t3['row']:.2f} "
          "percentage points")
    print(f"- best-fitting denominator: **{best}**")
    if best != "min":
        print("- => the published matrices are consistent with dividing by the *slower* time (max), not by "
              "min(t_row, t_col) as the Table II caption says (dividing by t_row fits almost as well; the only "
              "cell that separates the two is `TB,noHT -> noTB,HT`, where the row is the faster one). "
              "Taking the first row of Table III as given, the caption formula would put epoll "
              "`TB,noHT -> TB,HT` at +10.8% instead of the published +15.27%. The ranking and significance conclusions are unaffected; only the effect sizes "
              "change meaning (\"X% less time\" vs \"X% faster\").")

    print("\n## Bonferroni arithmetic quoted in the paper\n")
    checks = [
        ("Sec. V-C: 0.1% difference, p = 2e-5, still significant for m = 100", 2e-5, 100, True),
        ("Table V: epoll -march=native, p = 0.26, 'statistically insignificant'", 0.26, 1, False),
        ("Table V: thread pool -march=native, p = 3e-7", 3e-7, 100, True),
        ("Table V: process pool -march=native, p = 2e-14", 2e-14, 100, True),
        ("Table III: all differences p < 1e-7 (m = 6 pairs x 3 crawlers = 18)", 1e-7, 18, True),
    ]
    ok_all = True
    for text, p, m, expected in checks:
        a_c = bonferroni(0.05, m)
        sig = p < a_c
        ok = sig == expected
        ok_all &= ok
        print(f"- {'OK ' if ok else 'BAD'} {text}: alpha_c = 0.05/{m} = {a_c:.1e} -> "
              f"{'significant' if sig else 'not significant'}")

    print("\n## Textual consistency\n")
    print("- The abstract names the *Wilcoxon signed-rank* test (paired samples), while Sec. III-A-6 uses the "
          "*Wilcoxon rank-sum* test (independent samples). Runs of different configurations are independent "
          "and unpaired, so the rank-sum (Mann-Whitney U) test is the correct one; this project uses it.")
    print("- Sec. V-A says the distributions 'are normal with p-value = 0.01'. A normality test can only fail "
          "to reject normality; read it as 'H0 of normality not rejected at alpha = 0.01'. This project uses "
          "alpha_normal = 0.01 for that reason.")
    # Exit code 0 when the arithmetic checks pass and the max hypothesis fits best (the expected result).
    return 0 if ok_all and best == "max" else 1


if __name__ == "__main__":
    sys.exit(main())
