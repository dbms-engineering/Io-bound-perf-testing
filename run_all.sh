#!/usr/bin/env bash
# Reproduces all results: generates the dataset, runs the verification suite,
# runs the four experiments on this machine, and performs the analyses.
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
if [ "$(uname -s)" = Darwin ] && [ -d /Library/Developer/CommandLineTools/usr/bin ]; then
  export DEVELOPER_DIR="${DEVELOPER_DIR:-/Library/Developer/CommandLineTools}"
fi

[ -f data/urls.txt ] || $PY dataset/generate.py --pages 4000

echo "== unit tests"; cargo test --release --quiet
$PY -m unittest discover -s verification -p 'test_*.py'
echo "== paper table check"; $PY verification/check_paper_tables.py > results/verification/paper_tables.md || true

for exp in aa_test crawlers optimization target_cpu; do
  echo "== experiment $exp"
  $PY bench/run_experiment.py "experiments/$exp.json"
  $PY analysis/pipeline.py "results/$exp" > /dev/null                                   # Default: pooled outlier fences.
  $PY analysis/pipeline.py "results/$exp" --outliers per-group --suffix _paper > /dev/null # Per-group fences, as described in the paper.
  $PY analysis/plots.py "results/$exp" > /dev/null                                    # Distribution plots.
done

echo "== Monte Carlo verification"; $PY verification/simulate.py --trials 1000
