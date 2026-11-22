#!/usr/bin/env python3
"""Statistical analysis pipeline from Sultanov et al. (CSIT 2022), Sec. III.

Usage:

    .venv/bin/python analysis/pipeline.py results/crawlers [--alpha 0.05] [--m N]

Applies steps 3 to 8 of the paper to results/<exp>/runs.csv:

3a. Remove outliers outside [Q1 - 1.5 IQR, Q3 + 1.5 IQR]. By default, the fences
    are computed from each compared pair (`--outliers pooled`). The
    per-configuration fences described in the paper (`--outliers per-group`)
    inflate the false-positive rate (see verification/).
3b. Apply the D'Agostino-Pearson normality test, based on skewness and kurtosis
    (scipy.stats.normaltest).
4.  Apply the Bonferroni correction: alpha_c = alpha / m, where m is the number
    of pairwise comparisons.
6.  If both samples are normal, apply a two-sided Student t-test for independent
    samples. The effect size is the relative difference of the sample MEANS.
7.  Otherwise, apply a two-sided Wilcoxon rank-sum (Mann-Whitney U) test. The
    effect size is the relative difference of the sample MINIMUMS.
8.  Double check: the rank-sum test is also run for normal samples, and any
    disagreement with the t-test is flagged.

The relative difference is defined as in the Table II caption of the paper:
    rel = (t_row - t_col) / min(t_row, t_col) * 100
A positive value means that the column configuration is faster than the row
configuration. `--denominator max` reproduces how the tables in the paper were
actually computed (see verification/check_paper_tables.py).

Writes results/<exp>/report.md and results/<exp>/analysis.json.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy import stats

MIN_N_NORMALTEST = 20  # The D'Agostino-Pearson kurtosis test requires n >= 20.


# --------------------------------------------------------------- step 3a ----

def iqr_filter(x, k: float = 1.5) -> tuple[np.ndarray, np.ndarray]:
    """Returns (kept, removed) using Tukey's fences Q1 - k*IQR, Q3 + k*IQR."""
    x = np.asarray(x, dtype=float)
    q1, q3 = np.percentile(x, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    mask = (x >= lo) & (x <= hi)
    return x[mask], x[~mask]


def iqr_filter_pooled(a, b, k: float = 1.5) -> tuple[np.ndarray, np.ndarray]:
    """Applies ONE set of Tukey fences, computed from the pooled pair, to both samples.

    Under H0 (identical distributions), the pooled fences treat every
    observation the same way, so the filtered samples remain exchangeable and
    the subsequent test retains its nominal error rate. Per-sample fences (the
    procedure described in the paper) trim each sample toward its own center,
    which reduces the estimated variance and inflates the false-positive rate
    (see verification/simulate.py, experiment E).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    q1, q3 = np.percentile(np.concatenate([a, b]), [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - k * iqr, q3 + k * iqr
    return a[(a >= lo) & (a <= hi)], b[(b >= lo) & (b <= hi)]


OUTLIER_MODES = ("pooled", "per-group", "none")


# --------------------------------------------------------------- step 3b ----

@dataclass
class Normality:
    statistic: float | None
    p_value: float | None
    normal: bool
    note: str = ""


def normality(x, alpha_normal: float = 0.01) -> Normality:
    """D'Agostino-Pearson K^2 test. H0: the sample is drawn from a normal distribution.

    In this context, "normal" means that *H0 was not rejected* at alpha_normal;
    the test cannot prove normality. Samples that are too small are treated as
    non-normal, which routes them to the distribution-free test (a conservative
    choice).
    """
    x = np.asarray(x, dtype=float)
    if len(x) < MIN_N_NORMALTEST:
        return Normality(None, None, False, f"n={len(x)} < {MIN_N_NORMALTEST}: treated as non-normal")
    if np.ptp(x) == 0:
        return Normality(None, None, False, "constant sample")
    stat, p = stats.normaltest(x)
    return Normality(float(stat), float(p), bool(p >= alpha_normal))


# ----------------------------------------------------------------- step 4 ----

def bonferroni(alpha: float, m: int) -> float:
    return alpha / max(int(m), 1)


# ------------------------------------------------------------- steps 6-7 ----

def relative_difference(t_row: float, t_col: float, denominator: str = "min") -> float:
    """Returns (t_row - t_col) / d * 100, where d is selected by `denominator`.

    A positive value means that the column is faster.
    """
    if denominator == "min":
        d = min(t_row, t_col)
    elif denominator == "max":
        d = max(t_row, t_col)
    elif denominator == "row":
        d = t_row
    else:
        raise ValueError(denominator)
    return (t_row - t_col) / d * 100.0


@dataclass
class Comparison:
    row: str
    col: str
    test: str
    statistic: float
    p_value: float
    alpha_corrected: float
    significant: bool
    location: str  # "mean" or "min"
    t_row: float
    t_col: float
    rel_diff_pct: float
    ranksum_p: float
    ranksum_agrees: bool
    notes: list[str] = field(default_factory=list)
    n_row: int = 0
    n_col: int = 0
    normal_row: bool = False
    normal_col: bool = False


def compare(row: str, a, col: str, b, alpha_c: float, normal_a: bool, normal_b: bool,
            denominator: str = "min", welch: bool = False) -> Comparison:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    rs = stats.mannwhitneyu(a, b, alternative="two-sided")
    notes = []
    if normal_a and normal_b:
        t = stats.ttest_ind(a, b, equal_var=not welch)
        test = "Welch t-test" if welch else "Student t-test"
        stat, p = float(t.statistic), float(t.pvalue)
        loc, ta, tb = "mean", float(a.mean()), float(b.mean())
    else:
        test = "Wilcoxon rank-sum"
        stat, p = float(rs.statistic), float(rs.pvalue)
        loc, ta, tb = "min", float(a.min()), float(b.min())
    significant = p < alpha_c
    rs_sig = float(rs.pvalue) < alpha_c
    agrees = rs_sig == significant
    if not agrees:
        notes.append("t-test and rank-sum test disagree")
    return Comparison(row, col, test, stat, p, alpha_c, bool(significant), loc, ta, tb,
                      relative_difference(ta, tb, denominator), float(rs.pvalue), bool(agrees), notes,
                      len(a), len(b), bool(normal_a), bool(normal_b))


# ------------------------------------------------------------ the driver ----

@dataclass
class GroupSummary:
    name: str
    n_raw: int
    n_kept: int
    n_outliers: int
    mean_ms: float
    std_ms: float
    cv_pct: float
    min_ms: float
    median_ms: float
    normality: Normality
    drift_rho: float | None = None  # Spearman rho of wall time vs. measurement order
    drift_p: float | None = None


def pairs_from_groups(groups: list[list[str]]) -> list[tuple[str, str]]:
    seen, out = set(), []
    for g in groups:
        for a, b in itertools.combinations(g, 2):
            if (a, b) not in seen and (b, a) not in seen:
                seen.add((a, b))
                out.append((a, b))
    return out


def analyze(samples: dict[str, np.ndarray], pairs: list[tuple[str, str]], alpha: float = 0.05,
            m: int | None = None, alpha_normal: float = 0.01, iqr_k: float = 1.5,
            denominator: str = "min", welch: bool = False,
            order: dict[str, np.ndarray] | None = None, outliers: str = "pooled") -> dict:
    """Runs the full pipeline. `samples` contains raw wall times in any unit.

    outliers: "pooled":    1.5 IQR fences computed from each compared pair
                           (default; preserves valid error rates).
              "per-group": fences computed per configuration, as described in the paper.
              "none":      no outlier removal.
    The per-configuration summary always uses per-group fences because it is
    descriptive only.
    """
    if outliers not in OUTLIER_MODES:
        raise ValueError(f"outliers must be one of {OUTLIER_MODES}")
    kept: dict[str, np.ndarray] = {}
    summaries: dict[str, GroupSummary] = {}
    for name, x in samples.items():
        x = np.asarray(x, dtype=float)
        k, removed = iqr_filter(x, iqr_k)
        kept[name] = k
        nt = normality(k, alpha_normal)
        s = GroupSummary(name, len(x), len(k), len(removed), k.mean() / 1e6, k.std(ddof=1) / 1e6,
                         k.std(ddof=1) / k.mean() * 100, k.min() / 1e6, float(np.median(k)) / 1e6, nt)
        if order is not None and name in order and len(x) > 3:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rho, p = stats.spearmanr(order[name], x)
            s.drift_rho, s.drift_p = float(rho), float(p)
        summaries[name] = s
    m_eff = m if m is not None else len(pairs)
    alpha_c = bonferroni(alpha, m_eff)
    comps = []
    for a, b in pairs:
        if outliers == "per-group":
            xa, xb = kept[a], kept[b]
            na, nb = summaries[a].normality.normal, summaries[b].normality.normal
        else:
            xa, xb = np.asarray(samples[a], dtype=float), np.asarray(samples[b], dtype=float)
            if outliers == "pooled":
                xa, xb = iqr_filter_pooled(xa, xb, iqr_k)
            na, nb = normality(xa, alpha_normal).normal, normality(xb, alpha_normal).normal
        comps.append(compare(a, xa, b, xb, alpha_c, na, nb, denominator, welch))
    return {"alpha": alpha, "m": m_eff, "alpha_corrected": alpha_c, "alpha_normal": alpha_normal,
            "iqr_k": iqr_k, "outliers": outliers, "denominator": denominator, "summaries": summaries,
            "comparisons": comps}


# ------------------------------------------------------------- reporting ----

def fmt_p(p: float | None) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "-"
    return f"{p:.2e}" if p < 1e-3 else f"{p:.3f}"


def matrix_markdown(names: list[str], comps: list[Comparison], denominator: str = "min") -> str:
    lookup = {(c.row, c.col): c for c in comps}
    head = "| row \\ column | " + " | ".join(names) + " |\n|---|" + "---|" * len(names) + "\n"
    rows = []
    for i, r in enumerate(names):
        cells = []
        for j, c in enumerate(names):
            if i == j:
                cells.append("0")
            elif j < i:
                cells.append("")
            else:
                comp = lookup.get((r, c))
                if comp is None and (c, r) in lookup:  # Reorient the stored pair as (row, col).
                    o = lookup[(c, r)]
                    comp = Comparison(r, c, o.test, o.statistic, o.p_value, o.alpha_corrected, o.significant,
                                      o.location, o.t_col, o.t_row,
                                      relative_difference(o.t_col, o.t_row, denominator), o.ranksum_p, o.ranksum_agrees)
                if comp is None:
                    cells.append("n/a")
                elif not comp.significant:
                    cells.append("No diff.")
                else:
                    cells.append(f"{comp.rel_diff_pct:+.2f}%")
        rows.append(f"| **{r}** | " + " | ".join(cells) + " |")
    return head + "\n".join(rows) + "\n"


def render_report(title: str, res: dict, groups: list[list[str]], meta: dict | None) -> str:
    L = [f"# {title}\n"]
    if meta:
        sysinfo = meta.get("system", {})
        L.append(f"- machine: {sysinfo.get('cpu', '?')} ({sysinfo.get('machine', '?')}, "
                 f"{sysinfo.get('cpu_count', '?')} logical CPUs), {sysinfo.get('platform', '?')}")
        for t, v in sysinfo.get("toolchains", {}).items():
            L.append(f"- toolchain `{t}`: {v}")
        L.append(f"- rounds: {meta.get('reps')} measured (+{meta.get('warmup')} warm-up), "
                 f"master seed {meta.get('master_seed')}, server {json.dumps(meta.get('server'))}")
    L.append(f"- alpha = {res['alpha']}, Bonferroni m = {res['m']} -> alpha_c = {res['alpha_corrected']:.2e}; "
             f"normality alpha = {res['alpha_normal']}; outliers: {res['iqr_k']} x IQR, "
             f"fences `{res['outliers']}`\n")

    L.append("## 1. Per-configuration summary (after outlier removal)\n")
    L.append("| configuration | n raw | outliers | mean ms | std ms | CV % | min ms | median ms | "
             "normaltest p | normal? | drift rho (p) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in res["summaries"].values():
        nt = s.normality
        drift = "-" if s.drift_rho is None else f"{s.drift_rho:+.2f} ({fmt_p(s.drift_p)})"
        L.append(f"| {s.name} | {s.n_raw} | {s.n_outliers} | {s.mean_ms:.3f} | {s.std_ms:.3f} | {s.cv_pct:.2f} | "
                 f"{s.min_ms:.3f} | {s.median_ms:.3f} | {fmt_p(nt.p_value)} | "
                 f"{'yes' if nt.normal else 'no'}{(' - ' + nt.note) if nt.note else ''} | {drift} |")

    L.append("\n## 2. Pairwise hypothesis tests\n")
    L.append("| row | column | n row/col | normal row/col | test | p-value | significant (p < alpha_c) | "
             "compared | rel. diff | rank-sum p (double check) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    yn = {True: "yes", False: "no"}
    for c in res["comparisons"]:
        L.append(f"| {c.row} | {c.col} | {c.n_row}/{c.n_col} | {yn[c.normal_row]}/{yn[c.normal_col]} | {c.test} | "
                 f"{fmt_p(c.p_value)} | {'**yes**' if c.significant else 'no'} | "
                 f"{c.location} | {c.rel_diff_pct:+.3f}% | {fmt_p(c.ranksum_p)}"
                 f"{' (disagrees!)' if not c.ranksum_agrees else ''} |")

    L.append("\n## 3. Relative-performance matrices (paper Table II format)\n")
    L.append("Cell = how the *column* configuration performs relative to the *row*: "
             f"((t_row - t_col) / {res['denominator']}(t_row, t_col)) x 100; positive = column faster; "
             "\"No diff.\" = not significant after Bonferroni correction.\n")
    for g in groups:
        L.append(matrix_markdown(g, res["comparisons"], res["denominator"]))
    return "\n".join(L) + "\n"


def to_jsonable(res: dict) -> dict:
    out = dict(res)
    out["summaries"] = {k: asdict(v) for k, v in res["summaries"].items()}
    out["comparisons"] = [asdict(c) for c in res["comparisons"]]
    return out


def load_runs(path: Path) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    samples: dict[str, list[float]] = {}
    order: dict[str, list[float]] = {}
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for idx, r in enumerate(rows):
        if int(r.get("errors", 0) or 0):
            continue  # Runs with failed downloads did different work.
        samples.setdefault(r["config"], []).append(float(r["wall_ns"]))
        order.setdefault(r["config"], []).append(idx)
    return ({k: np.array(v) for k, v in samples.items()}, {k: np.array(v) for k, v in order.items()})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result_dir")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--alpha-normal", type=float, default=0.01)
    ap.add_argument("--m", type=int, help="Bonferroni factor (default: number of pairwise comparisons)")
    ap.add_argument("--iqr-k", type=float, default=1.5)
    ap.add_argument("--denominator", choices=["min", "max", "row"], default="min")
    ap.add_argument("--welch", action="store_true", help="use Welch's t-test instead of Student's")
    ap.add_argument("--outliers", choices=OUTLIER_MODES, default="pooled",
                    help="IQR fences per compared pair (default), per configuration (paper), or none")
    ap.add_argument("--suffix", default="", help="write report<suffix>.md / analysis<suffix>.json")
    args = ap.parse_args()

    rdir = Path(args.result_dir)
    samples, order = load_runs(rdir / "runs.csv")
    meta = json.loads((rdir / "meta.json").read_text()) if (rdir / "meta.json").exists() else None
    groups = (meta or {}).get("experiment_config", {}).get("comparisons") or [sorted(samples)]
    missing = {n for g in groups for n in g} - set(samples)
    if missing:
        sys.exit(f"comparison refers to configurations without data: {sorted(missing)}")
    res = analyze(samples, pairs_from_groups(groups), args.alpha, args.m, args.alpha_normal, args.iqr_k,
                  args.denominator, args.welch, order, args.outliers)
    title = (meta or {}).get("experiment_config", {}).get("title") or f"Analysis of {rdir.name}"
    report = render_report(title, res, groups, meta)
    (rdir / f"report{args.suffix}.md").write_text(report)
    (rdir / f"analysis{args.suffix}.json").write_text(json.dumps(to_jsonable(res), indent=2))
    print(report)


if __name__ == "__main__":
    main()
