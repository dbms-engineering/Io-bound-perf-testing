#!/usr/bin/env python3
"""Plots the wall-time distribution of every configuration and classifies its shape.

Usage:

    .venv/bin/python analysis/plots.py results/crawlers [results/aa_test ...]

For each configuration, the figure shows a histogram of all runs with the
fitted normal density and a normal Q-Q plot. Outliers are the runs outside the
per-configuration 1.5 IQR fences, as in section 1 of report.md. The shape is
determined from the runs that remain after outlier removal:

- "Normal (bell-shaped)": the D'Agostino-Pearson test does not reject
  normality at alpha_normal = 0.01 (the same rule that analysis/pipeline.py
  uses to select the t-test), and the sample is roughly symmetric with
  normal tails.
- "Borderline normal": the test does not reject normality, but the sample is
  skewed (|skewness| > 0.5) or has heavy or light tails (|excess kurtosis| > 1).
  The pipeline still treats it as normal.
- "Non-Gaussian": the test rejects normality. The label states the reason:
  right- or left-skewed, heavy- or light-tailed.

Writes results/<exp>/distributions.png and results/<exp>/distributions.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy import stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline as P  # noqa: E402

# Reference palette (light mode) from the data-visualization guidelines.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
KEPT = "#2a78d6"  # Categorical slot 1.
OUTLIER = "#eb6834"  # Categorical slot 2.

SKEW_LIMIT = 0.5
KURT_LIMIT = 1.0


@dataclass
class Shape:
    name: str
    n: int
    n_outliers: int
    skewness: float
    excess_kurtosis: float
    normaltest_p: float | None
    normal: bool
    label: str
    reasons: list[str]


def classify(name: str, raw: np.ndarray, alpha_normal: float = 0.01) -> Shape:
    kept, removed = P.iqr_filter(raw)
    n = len(kept)
    g1 = float(stats.skew(kept, bias=False))
    g2 = float(stats.kurtosis(kept, bias=False))
    nt = P.normality(kept, alpha_normal)
    reasons = []
    if g1 > SKEW_LIMIT:
        reasons.append("right-skewed")
    elif g1 < -SKEW_LIMIT:
        reasons.append("left-skewed")
    if g2 > KURT_LIMIT:
        reasons.append("heavy-tailed")
    elif g2 < -KURT_LIMIT:
        reasons.append("light-tailed")
    if nt.note:
        reasons.append(nt.note)
    if nt.normal:
        label = "Borderline normal: " + ", ".join(reasons) if reasons else "Normal (bell-shaped)"
    else:
        label = "Non-Gaussian: " + ", ".join(reasons or ["mild deviations from normality"])
    return Shape(name, len(raw), len(removed), g1, g2, nt.p_value, nt.normal, label, reasons)


def style_axis(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def draw_config(fig_cell, name: str, raw_ms: np.ndarray, shape: Shape) -> None:
    ax_h, ax_q = fig_cell.subplots(2, 1, gridspec_kw={"height_ratios": [3, 2], "hspace": 0.45})
    kept, removed = P.iqr_filter(raw_ms)

    # Bin width from the kept runs, so that distant outliers do not coarsen the bulk.
    width = np.diff(np.histogram_bin_edges(kept, bins="fd"))[0]
    edges = np.arange(raw_ms.min(), raw_ms.max() + width, width)
    if len(edges) > 61:
        edges = np.linspace(raw_ms.min(), raw_ms.max(), 61)
    ax_h.hist(kept, bins=edges, color=KEPT, edgecolor=SURFACE, linewidth=1.2, label="runs")
    if len(removed):
        ax_h.hist(removed, bins=edges, color=OUTLIER, edgecolor=SURFACE, linewidth=1.2, label="outliers")
    mu, sd = kept.mean(), kept.std(ddof=1)
    xs = np.linspace(edges[0], edges[-1], 400)
    width = edges[1] - edges[0]
    ax_h.plot(xs, stats.norm.pdf(xs, mu, sd) * len(kept) * width, color=INK, linewidth=2,
              linestyle="--", label="normal fit")
    style_axis(ax_h)
    ax_h.set_xlabel("wall time (ms)", fontsize=8, color=INK_2)
    ax_h.set_ylabel("runs", fontsize=8, color=INK_2)
    p_text = "-" if shape.normaltest_p is None else f"{shape.normaltest_p:.2g}"
    ax_h.set_title(f"{name}\n{shape.label}", fontsize=9, color=INK, loc="left", wrap=True)
    ax_h.text(0.99, 0.97, f"n = {len(kept)} (+{len(removed)} outliers)\nskew {shape.skewness:+.2f}, "
              f"ex. kurt {shape.excess_kurtosis:+.2f}\nnormality p = {p_text}",
              transform=ax_h.transAxes, ha="right", va="top", fontsize=7, color=INK_2)

    (osm, osr), (slope, intercept, _) = stats.probplot(kept, dist="norm")
    ax_q.scatter(osm, osr, s=14, color=KEPT, edgecolors=SURFACE, linewidths=0.8, zorder=3)
    ax_q.plot(osm, slope * osm + intercept, color=INK, linewidth=2, linestyle="--")
    style_axis(ax_q)
    ax_q.set_xlabel("normal quantile", fontsize=8, color=INK_2)
    ax_q.set_ylabel("ms", fontsize=8, color=INK_2)


def plot_experiment(rdir: Path, alpha_normal: float) -> list[Shape]:
    samples, _ = P.load_runs(rdir / "runs.csv")
    meta_path = rdir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    exp = meta.get("experiment_config", {})
    names = [c["name"] for c in exp.get("configs", [])] or sorted(samples)
    names = [n for n in names if n in samples]
    title = exp.get("title") or rdir.name

    shapes = [classify(n, samples[n] / 1e6, alpha_normal) for n in names]
    ncols = min(len(names), 4)
    nrows = math.ceil(len(names) / ncols)
    fig = plt.figure(figsize=(3.8 * ncols, 5.0 * nrows + 1.2), facecolor=SURFACE)
    header, body = fig.subfigures(2, 1, height_ratios=[1.2, 5.0 * nrows])
    header.set_facecolor(SURFACE)
    body.set_facecolor(SURFACE)
    header.text(0.01, 0.85, title, fontsize=12, color=INK, ha="left", va="center")
    header.text(0.01, 0.55, "Wall-time distribution per configuration: histogram with fitted normal "
                "density (top) and normal Q-Q plot of the kept runs (bottom)", fontsize=9, color=INK_2,
                ha="left", va="center")
    cells = body.subfigures(nrows, ncols, squeeze=False, wspace=0.04, hspace=0.06)
    for i, (n, s) in enumerate(zip(names, shapes)):
        cell = cells[i // ncols][i % ncols]
        cell.set_facecolor(SURFACE)
        draw_config(cell, n, samples[n] / 1e6, s)
    for j in range(len(names), nrows * ncols):
        cells[j // ncols][j % ncols].set_facecolor(SURFACE)

    handles = [plt.Rectangle((0, 0), 1, 1, color=KEPT), plt.Rectangle((0, 0), 1, 1, color=OUTLIER),
               plt.Line2D([0], [0], color=INK, linewidth=2, linestyle="--")]
    header.legend(handles, ["runs kept", "outliers (outside 1.5 IQR)", "fitted normal and Q-Q reference"],
                  loc="lower left", bbox_to_anchor=(0.0, 0.0), ncol=3, frameon=False, fontsize=8,
                  labelcolor=INK_2)
    fig.savefig(rdir / "distributions.png", dpi=130, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)

    rows = ["| configuration | n | outliers | skewness | excess kurtosis | normality p | shape |",
            "|---|---|---|---|---|---|---|"]
    for s in shapes:
        p_text = "-" if s.normaltest_p is None else P.fmt_p(s.normaltest_p)
        rows.append(f"| {s.name} | {s.n} | {s.n_outliers} | {s.skewness:+.2f} | {s.excess_kurtosis:+.2f} | "
                    f"{p_text} | {s.label} |")
    (rdir / "distributions.md").write_text(
        f"# {title}: distribution shapes\n\n![Distributions](distributions.png)\n\n" + "\n".join(rows) + "\n")
    return shapes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("result_dirs", nargs="+")
    ap.add_argument("--alpha-normal", type=float, default=0.01)
    args = ap.parse_args()
    for d in args.result_dirs:
        rdir = Path(d)
        print(f"== {rdir.name}")
        for s in plot_experiment(rdir, args.alpha_normal):
            print(f"  {s.name:16s} {s.label}")
        print(f"  wrote {rdir / 'distributions.png'}")


if __name__ == "__main__":
    main()
