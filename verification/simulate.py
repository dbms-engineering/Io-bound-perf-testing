#!/usr/bin/env python3
"""Monte Carlo verification of the claims of the methodology against a known ground truth.

Usage:

    .venv/bin/python verification/simulate.py [--trials 1000] [--quick]

Each experiment draws synthetic "execution times" with a controlled true
difference, passes them through analysis/pipeline.py, and measures how often
the pipeline reaches the correct conclusion:

A. Multiple comparisons: with k identical configurations, how often does at
   least one pair appear "significant"? (Family-wise error rate, with and
   without the Bonferroni correction.)
B. Sensitivity: what is the smallest true difference that is detected,
   relative to the run-to-run noise? (The paper claims that differences smaller
   than the noise can be detected.)
C. Randomization: identical configurations with slow machine drift, measured
   sequentially (all A runs, then all B runs) versus in randomly interleaved
   rounds.
D. Outlier removal: a true 0.5% difference where 5% of runs are affected by
   +30% spikes, with and without the 1.5 IQR filter.
E. Validity of the outlier step itself: the false-positive rate of a single
   comparison of identical configurations for per-configuration fences (the
   procedure described in the paper), pooled per-pair fences (the default in
   this project), and no outlier removal.

Writes results/verification/simulation.md.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))
import pipeline as P  # noqa: E402

warnings.filterwarnings("ignore")
BASE = 100.0  # Baseline execution time in milliseconds.


def draw(rng, dist: str, n: int, mean: float = BASE, cv: float = 0.01) -> np.ndarray:
    sd = mean * cv
    if dist == "normal":
        return rng.normal(mean, sd, n)
    if dist == "lognormal":
        s = np.sqrt(np.log(1 + cv**2))
        return mean * rng.lognormal(-s**2 / 2, s, n)
    if dist == "shifted-exp":  # Hard lower bound with a long right tail, typical of latency distributions.
        return (mean - sd) + rng.exponential(sd, n)
    raise ValueError(dist)


def any_significant(samples: dict, m: int | None, outliers: str = "pooled") -> bool:
    res = P.analyze(samples, P.pairs_from_groups([list(samples)]), alpha=0.05, m=m, outliers=outliers)
    return any(c.significant for c in res["comparisons"])


def exp_a(rng, trials: int, k: int = 5, n: int = 40) -> list[str]:
    pairs = k * (k - 1) // 2
    out = ["## A. Multiple comparisons (look-elsewhere effect)\n",
           f"{k} *identical* configurations, n = {n} runs each, {pairs} pairwise comparisons, alpha = 0.05, "
           f"{trials} simulated experiments. Cell = fraction of experiments that wrongly report at least one "
           "significant difference (family-wise error rate). Theory without correction: up to "
           f"1 - 0.95^{pairs} = {1 - 0.95**pairs:.2f}.\n",
           "| distribution | no correction (m = 1) | Bonferroni, per-configuration fences (paper) | "
           "Bonferroni, pooled fences (default) |", "|---|---|---|---|"]
    for dist in ("normal", "lognormal", "shifted-exp"):
        fp_raw = fp_paper = fp_bonf = 0
        for _ in range(trials):
            s = {f"c{i}": draw(rng, dist, n) for i in range(k)}
            fp_raw += any_significant(s, 1)
            fp_paper += any_significant(s, pairs, "per-group")
            fp_bonf += any_significant(s, pairs)
        out.append(f"| {dist} | {fp_raw / trials:.3f} | {fp_paper / trials:.3f} | **{fp_bonf / trials:.3f}** |")
    return out


def exp_b(rng, trials: int) -> list[str]:
    effects = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0]
    ns = [20, 40, 100]
    out = ["\n## B. Sensitivity: detection rate vs. true difference\n",
           f"Two configurations, normal noise with CV = 1% (sd = 1 ms on 100 ms), Bonferroni m = 10, "
           f"{trials} experiments per cell. Cell = fraction in which the faster configuration is detected "
           "*and* has the correct sign.\n",
           "| true difference | " + " | ".join(f"n = {n}" for n in ns) + " |", "|---|" + "---|" * len(ns)]
    for eff in effects:
        cells = []
        for n in ns:
            hit = 0
            for _ in range(trials):
                a = draw(rng, "normal", n)
                b = draw(rng, "normal", n, mean=BASE * (1 - eff / 100))
                res = P.analyze({"a": a, "b": b}, [("a", "b")], m=10)
                c = res["comparisons"][0]
                hit += c.significant and c.rel_diff_pct > 0
            cells.append(f"{hit / trials:.2f}")
        out.append(f"| {eff:g}% ({eff:g}x noise sd) | " + " | ".join(cells) + " |")
    return out


def exp_c(rng, trials: int, n: int = 40, drift: float = 0.03) -> list[str]:
    out = ["\n## C. Randomized, interleaved execution order vs. machine drift\n",
           f"Two *identical* configurations, n = {n} each, noise CV = 1%, plus a slow linear drift that makes "
           f"the machine {drift * 100:g}% slower from the first to the last run (e.g. heating up). alpha = 0.05, "
           f"one comparison, {trials} experiments. Cell = false-positive rate.\n",
           "| execution order | false-positive rate | mean reported difference |", "|---|---|---|"]
    total = 2 * n
    trend = BASE * drift * np.arange(total) / (total - 1)
    for order in ("sequential (A...A B...B)", "randomized rounds (paper)"):
        fp, diffs = 0, []
        for _ in range(trials):
            noise = draw(rng, "normal", total) + trend
            if order.startswith("sequential"):
                a, b = noise[:n], noise[n:]
            else:  # Each round runs A and B once, in random order.
                idx = np.arange(total).reshape(n, 2)
                flip = rng.random(n) < 0.5
                idx[flip] = idx[flip][:, ::-1]
                a, b = noise[idx[:, 0]], noise[idx[:, 1]]
            res = P.analyze({"A": a, "B": b}, [("A", "B")], m=1)
            c = res["comparisons"][0]
            fp += c.significant
            diffs.append(c.rel_diff_pct)
        out.append(f"| {order} | **{fp / trials:.3f}** | {np.mean(diffs):+.2f}% |")
    return out


def exp_d(rng, trials: int, n: int = 40, eff: float = 0.5, rate: float = 0.05, spike: float = 0.30) -> list[str]:
    out = ["\n## D. Outlier removal (1.5 x IQR)\n",
           f"True difference {eff}%, noise CV = 1%, n = {n}; each run has a {rate * 100:g}% chance of a "
           f"+{spike * 100:g}% spike (a background job, a page-cache miss, ...). Student t-test on the raw "
           f"data vs. the full pipeline (IQR filter, then normality test, then t-test or rank-sum). "
           f"alpha = 0.05, one comparison, {trials} experiments.\n",
           "| analysis | detection rate | mean estimated difference | false positives in an A/A test |",
           "|---|---|---|---|"]
    from scipy import stats

    def contaminate(x):
        hit = rng.random(len(x)) < rate
        return np.where(hit, x * (1 + spike), x)

    rows = {"t-test on raw data": [0, [], 0], "pipeline, per-configuration fences (paper)": [0, [], 0],
            "pipeline, pooled fences (default)": [0, [], 0]}
    for _ in range(trials):
        a = contaminate(draw(rng, "normal", n))
        b = contaminate(draw(rng, "normal", n, mean=BASE * (1 - eff / 100)))
        a2 = contaminate(draw(rng, "normal", n))
        t = stats.ttest_ind(a, b)
        r = rows["t-test on raw data"]
        r[0] += t.pvalue < 0.05
        r[1].append(P.relative_difference(a.mean(), b.mean()))
        r[2] += stats.ttest_ind(a, a2).pvalue < 0.05
        for name, mode in (("pipeline, per-configuration fences (paper)", "per-group"),
                           ("pipeline, pooled fences (default)", "pooled")):
            c = P.analyze({"a": a, "b": b}, [("a", "b")], m=1, outliers=mode)["comparisons"][0]
            r = rows[name]
            r[0] += c.significant
            r[1].append(c.rel_diff_pct)
            r[2] += P.analyze({"a": a, "a2": a2}, [("a", "a2")], m=1, outliers=mode)["comparisons"][0].significant
    for name, (hit, diffs, fp) in rows.items():
        out.append(f"| {name} | **{hit / trials:.2f}** | {np.mean(diffs):+.2f}% (sd {np.std(diffs):.2f}) | "
                   f"{fp / trials:.3f} |")
    return out


def exp_e(rng, trials: int, n: int = 40) -> list[str]:
    out = ["\n## E. Is the outlier step itself valid? (type I error of one comparison)\n",
           f"Two *identical* configurations, n = {n} each, noise CV = 1%, alpha = 0.05, {trials} experiments. "
           "A valid procedure gives ~0.05. Spikes: 5% of runs +30%.\n",
           "| distribution | per-configuration fences (paper) | pooled fences (default) | no outlier removal |",
           "|---|---|---|---|"]
    for dist in ("normal", "lognormal", "shifted-exp", "normal + spikes"):
        fp = {m: 0 for m in P.OUTLIER_MODES}
        for _ in range(trials):
            base = "normal" if dist.startswith("normal") else dist
            a, b = draw(rng, base, n), draw(rng, base, n)
            if "spikes" in dist:
                a = np.where(rng.random(n) < 0.05, a * 1.3, a)
                b = np.where(rng.random(n) < 0.05, b * 1.3, b)
            for mode in fp:
                fp[mode] += P.analyze({"a": a, "b": b}, [("a", "b")], m=1, outliers=mode)["comparisons"][0].significant
        out.append(f"| {dist} | **{fp['per-group'] / trials:.3f}** | **{fp['pooled'] / trials:.3f}** | "
                   f"{fp['none'] / trials:.3f} |")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=1000)
    ap.add_argument("--quick", action="store_true", help="200 trials (about 15 s)")
    ap.add_argument("--seed", type=int, default=20221110)
    args = ap.parse_args()
    trials = 200 if args.quick else args.trials
    rng = np.random.default_rng(args.seed)
    lines = ["# Monte Carlo verification of the methodology\n",
             f"Generated by `verification/simulate.py --trials {trials} --seed {args.seed}`.\n"]
    lines += exp_a(rng, trials)
    lines += exp_b(rng, max(trials // 2, 100))
    lines += exp_c(rng, trials)
    lines += exp_d(rng, trials)
    lines += exp_e(rng, trials * 2)
    text = "\n".join(lines) + "\n"
    out = ROOT / "results" / "verification"
    out.mkdir(parents=True, exist_ok=True)
    (out / "simulation.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
