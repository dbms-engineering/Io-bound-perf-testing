# Running io-bound-perf-testing

This guide explains how to set up the project, run the experiments and read the results. Every
command below has been tested on an Apple M3 running macOS. The same commands work on Linux,
except where noted.

## What a run does

The project compares three Rust web crawlers (a process pool, a thread pool and an event loop).
Each one downloads the same 4,000 pages from a local server, many times and in a randomized order,
and a statistical pipeline then decides which speed differences are real and which are noise.

An experiment goes through these stages:

1. **Dataset.** `dataset/generate.py` creates 4,000 synthetic HTML pages in `data/pages`.
2. **Build.** `bench/build.py` compiles one crawler binary per variant (toolchain, opt-level,
   compiler flags).
3. **Serve.** A local HTTP server (`static_server`) serves the pages, with a 1 ms delay per
   request so the workload is I/O-bound.
4. **Check.** Every configuration runs once, and all of them must fetch identical pages, bytes and
   tags with zero errors.
5. **Measure.** 60 measured rounds, after 3 warm-up rounds. Each round runs every configuration
   once, in a newly shuffled order. The results go to `runs.csv`.
6. **Analyze.** `analysis/pipeline.py` removes outliers, tests for normality, picks a t-test or a
   rank-sum test, applies the Bonferroni correction and writes `report.md`.
7. **Plot.** `analysis/plots.py` plots the distribution of each configuration and labels its
   shape.

## One-time setup

You need:

- macOS or Linux;
- a Rust toolchain from [rustup.rs](https://rustup.rs), with both `stable` and `nightly`
  installed (the optimization experiment compares the two);
- Python 3.10 or later.

From the project folder:

```bash
rustup toolchain install stable nightly
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # numpy, scipy and matplotlib
.venv/bin/python dataset/generate.py           # writes data/pages and data/urls.txt
cargo build --release
cargo test --release                           # 5 Rust unit tests
```

On macOS, if `cargo build` reports an Xcode license error, run this in the same terminal first:

```bash
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
```

## Option 1: quick demo (about 40 seconds)

Good for showing the project in a meeting. It runs the crawler comparison with 30 rounds instead
of 60 and writes to `results/demo`, so the saved results are not overwritten.

```bash
.venv/bin/python bench/run_experiment.py experiments/crawlers.json --reps 30 --warmup 1 --out results/demo
.venv/bin/python analysis/pipeline.py results/demo
.venv/bin/python analysis/plots.py results/demo
open results/demo/distributions.png            # on Linux, use xdg-open
```

The second command prints the full report in the terminal. Delete the folder afterward:

```bash
rm -rf results/demo
```

A short run can rank the crawlers differently from a full one. In testing, a 20-round demo put the
event loop ahead of the thread pool, while the saved 60-round run could not separate them. That is
the reason the method uses many rounds.

## Option 2: one full experiment

```bash
.venv/bin/python bench/run_experiment.py experiments/crawlers.json
.venv/bin/python analysis/pipeline.py results/crawlers
.venv/bin/python analysis/plots.py results/crawlers
```

Replace `crawlers` with any of the experiments below. Each run overwrites the saved results for
that experiment. To keep them, add `--out results/<new-folder>` to the first command and use the
same folder in the other two.

| Experiment | Question it answers | Runs | Time on an M3 |
|---|---|---|---|
| `aa_test` | Control: three identical configurations. The analysis must report no difference. | 189 | 1 to 2 min |
| `crawlers` | Process pool, thread pool or event loop: which is fastest? | 189 | 1 to 2 min |
| `optimization` | Do opt-levels 0 to 3, or the stable and nightly compilers, change the speed? | 504 | about 3 min, plus builds |
| `target_cpu` | Does `-C target-cpu=native` help at opt-level 0? | 378 | about 3 min, plus builds |

Useful options for `bench/run_experiment.py`:

| Option | Effect |
|---|---|
| `--reps N` | Number of measured rounds (default 60 in the experiment files) |
| `--warmup N` | Number of warm-up rounds that are discarded (default 3) |
| `--out DIR` | Write results to `DIR` instead of `results/<experiment>` |
| `--seed N` | Fix the master seed, so the whole run order can be reproduced |
| `--no-build` | Reuse the crawler binaries already in `build/` |

To also write the report with the paper's original outlier procedure, for comparison:

```bash
.venv/bin/python analysis/pipeline.py results/crawlers --outliers per-group --suffix _paper
```

## Option 3: everything

```bash
./run_all.sh
```

This runs the Rust and Python unit tests, the consistency check of the paper's tables, all four
experiments with both reports and the plots, and the Monte Carlo study. Expect roughly 10 to 15
minutes, plus compile time on the first run. It creates the Python environment and the dataset if
they are missing. It overwrites all saved results.

## Running only the tests

```bash
cargo test --release
.venv/bin/python -m unittest discover -s verification -v
.venv/bin/python verification/check_paper_tables.py
.venv/bin/python verification/simulate.py --quick     # Monte Carlo study, about 15 seconds
```

`simulate.py --trials 1000` is the full Monte Carlo study (about a minute) and writes
`results/verification/simulation.md`.

## Running a crawler by hand

Useful for showing what a single measurement looks like:

```bash
./target/release/static_server --root data/pages --port 8080 --delay-us 1000 &
./target/release/crawler --mode event --urls data/urls.txt --port 8080 --seed 42
./target/release/crawler --mode thread --urls data/urls.txt --port 8080 --seed 42
./target/release/crawler --mode process --urls data/urls.txt --port 8080 --seed 42
kill $!                                        # stops the server started above
```

Each crawler prints one JSON line, for example:

```json
{"crawler":"event-kqueue","build":"dev","seed":42,"urls":4000,"wall_ns":394406875,"pages":4000,"bytes":45600114,"tags":587962,"errors":0}
```

`wall_ns` is the crawl time in nanoseconds (here about 394 ms). `pages`, `bytes` and `tags` show
the work done, and they must be the same for all three crawlers. A single run like this says
nothing about which crawler is faster; that is what the experiments are for.

## Reading the results

Each experiment writes its output to `results/<experiment>/`:

| File | Contents |
|---|---|
| `report.md` | The main result: a summary per configuration, every pairwise test, and the comparison matrix |
| `report_paper.md` | The same analysis with the paper's original outlier step, for comparison |
| `distributions.png` | Histogram and Q-Q plot of each configuration, labeled with its shape |
| `distributions.md` | The numbers behind those labels (skewness, kurtosis, normality p-value) |
| `runs.csv` | One row per run, including its random seed |
| `meta.json` | Machine, toolchain versions, seeds and settings |

In `report.md`:

- **Section 1** summarizes each configuration: mean, standard deviation, CV (noise as a
  percentage of the mean), minimum, median, the normality p-value and the drift ρ. A CV above a
  few percent means the machine was busy.
- **Section 2** lists every pairwise test: which test was used, the p-value, whether it is
  significant after the Bonferroni correction, and the relative difference.
- **Section 3** is the matrix in the paper's format. `+1.34%` means the column configuration is
  1.34% faster than the row configuration. `No diff.` means the difference was not significant.

Two rules to keep in mind:

- `No diff.` does not mean the two are equal. It means this many runs could not tell them apart.
- A significant difference can still be too small to matter in practice.

Results also vary from one session to the next, because the load on the machine changes. A
rerun of the crawler experiment on a different day found the event loop about 4% faster than the
other two, whereas the saved run found the process pool about 1.3% slower and could not separate
the thread pool from the event loop. Each run's conclusions are valid for the conditions it was
measured under; comparisons across sessions are not.

## Getting reliable numbers

- Close heavy applications (IDEs, browsers with many tabs, builds) before measuring. One early
  attempt at the target-cpu experiment, made while an IDE was indexing, had 30 to 50% noise and
  had to be repeated.
- Keep the laptop on mains power, and do not let it sleep during a run.
- Check the CV column in `report.md` after each run. Around 2 to 3% is typical for this laptop.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Xcode license error during `cargo build` | Run `export DEVELOPER_DIR=/Library/Developer/CommandLineTools` first. |
| `toolchain 'nightly' is not installed` | Run `rustup toolchain install nightly`. |
| `server 127.0.0.1:18080 did not come up` | Another process is using port 18080, often a server left over from an interrupted run. Find it with `lsof -i :18080` and stop it with `kill <PID>`. |
| Port 8080 is busy when running a crawler by hand | A server from an earlier session is still running. Find it with `lsof -i :8080` and stop it with `kill <PID>`. |
| `[check] FAILED` | The configurations did different work or had errors. Make sure `data/pages` and `data/urls.txt` match; rerun `dataset/generate.py` if in doubt. |
| Everything comes out as `No diff.` | Look at the CV column in `report.md`. If it is high, the machine is too noisy to resolve small effects; close other applications and rerun. |
| `No module named matplotlib` | Run `.venv/bin/pip install -r requirements.txt` again. |

For the background on the method, the verification results and the differences from the original
paper, see [README.md](README.md).
