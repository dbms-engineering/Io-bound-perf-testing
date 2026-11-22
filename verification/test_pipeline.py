"""Unit tests for analysis/pipeline.py. Each step is tested against data with a known result.

Usage:

    .venv/bin/python -m unittest discover -s verification -v
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import pipeline as P  # noqa: E402


class TestOutliers(unittest.TestCase):
    def test_iqr_removes_spikes_and_keeps_bulk(self):
        rng = np.random.default_rng(1)
        x = rng.normal(100, 1, 200)
        spikes = np.array([150.0, 160.0, 40.0])
        kept, removed = P.iqr_filter(np.concatenate([x, spikes]))
        self.assertTrue(set(spikes).issubset(set(removed)))
        self.assertGreater(len(kept), 195)  # About 0.7% of a normal sample lies outside the fences.

    def test_iqr_fences_exact(self):
        # Values 1 to 12 plus 40: Q1 = 4, Q3 = 10, and IQR = 6, so the fences are
        # [-5, 19] and only 40 lies outside them.
        kept, removed = P.iqr_filter(np.append(np.arange(1, 13, dtype=float), 40.0))
        self.assertEqual(removed.tolist(), [40.0])
        self.assertEqual(len(kept), 12)


class TestNormality(unittest.TestCase):
    def test_normal_sample_not_rejected(self):
        x = np.random.default_rng(2).normal(10, 1, 300)
        self.assertTrue(P.normality(x).normal)

    def test_skewed_sample_rejected(self):
        x = np.random.default_rng(3).exponential(1, 300)
        self.assertFalse(P.normality(x).normal)

    def test_small_sample_goes_nonparametric(self):
        nt = P.normality(np.random.default_rng(4).normal(size=10))
        self.assertFalse(nt.normal)
        self.assertIn("n=10", nt.note)


class TestFormulae(unittest.TestCase):
    def test_bonferroni(self):
        self.assertAlmostEqual(P.bonferroni(0.05, 10), 0.005)
        self.assertAlmostEqual(P.bonferroni(0.05, 0), 0.05)

    def test_relative_difference_matches_caption(self):
        # The row takes 104.4 s and the column takes 100 s, so the column is 4.4% faster.
        self.assertAlmostEqual(P.relative_difference(104.4, 100.0), 4.4)
        self.assertAlmostEqual(P.relative_difference(100.0, 104.4), -4.4)  # Antisymmetric when the denominator is min.
        self.assertAlmostEqual(P.relative_difference(104.4, 100.0, "max"), 4.4 / 104.4 * 100)

    def test_pairs(self):
        self.assertEqual(P.pairs_from_groups([["a", "b", "c"], ["a", "b"]]), [("a", "b"), ("a", "c"), ("b", "c")])


class TestTestSelection(unittest.TestCase):
    def test_normal_uses_t_test_and_means(self):
        rng = np.random.default_rng(5)
        a, b = rng.normal(100, 1, 60), rng.normal(98, 1, 60)
        c = P.compare("a", a, "b", b, 0.05, True, True)
        self.assertEqual((c.test, c.location), ("Student t-test", "mean"))
        self.assertTrue(c.significant)
        self.assertAlmostEqual(c.rel_diff_pct, (a.mean() - b.mean()) / b.mean() * 100)

    def test_non_normal_uses_rank_sum_and_minimums(self):
        rng = np.random.default_rng(6)
        a, b = 100 + rng.exponential(2, 60), 97 + rng.exponential(2, 60)
        c = P.compare("a", a, "b", b, 0.05, False, True)
        self.assertEqual((c.test, c.location), ("Wilcoxon rank-sum", "min"))
        self.assertAlmostEqual(c.rel_diff_pct, (a.min() - b.min()) / b.min() * 100)


class TestEndToEnd(unittest.TestCase):
    def test_aa_no_difference_and_real_difference_found(self):
        rng = np.random.default_rng(7)
        samples = {
            "A1": rng.normal(1e8, 1e6, 50),       # 100 ms with a 1% standard deviation.
            "A2": rng.normal(1e8, 1e6, 50),       # Identical to A1.
            "B": rng.normal(0.98e8, 1e6, 50),     # 2% faster than A1.
        }
        res = P.analyze(samples, P.pairs_from_groups([["A1", "A2", "B"]]))
        by = {(c.row, c.col): c for c in res["comparisons"]}
        self.assertEqual(res["m"], 3)
        self.assertFalse(by[("A1", "A2")].significant)
        self.assertTrue(by[("A1", "B")].significant)
        self.assertGreater(by[("A1", "B")].rel_diff_pct, 1.0)  # B (the column) is faster, so the difference is positive.

    def test_report_renders(self):
        rng = np.random.default_rng(8)
        s = {"x": rng.normal(10, 1, 30), "y": rng.normal(12, 1, 30)}
        res = P.analyze(s, [("x", "y")])
        md = P.render_report("t", res, [["x", "y"]], None)
        self.assertIn("| **x** |", md)
        self.assertIn("%", md)


if __name__ == "__main__":
    unittest.main()
