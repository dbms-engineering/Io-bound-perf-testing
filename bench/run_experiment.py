#!/usr/bin/env python3
"""Runs an experiment: builds the variants, starts the server, and collects randomized runs.

Usage:

    .venv/bin/python bench/run_experiment.py experiments/crawlers.json [--reps 40]

Implements steps 1 and 2 of the pipeline in the paper (Sec. III):

1. Input randomization: each run receives a new random seed, which the crawler
   uses to shuffle its URL list. The seed is recorded for each run, so any run
   can be replayed exactly.
2. Experiment execution: all configurations are *interleaved*. Each round runs
   every configuration once in a newly shuffled order, so slow drifts in the
   machine state (thermal state, background jobs, etc.) affect all
   configurations equally instead of biasing whichever was measured last.

Before measurement, each configuration is run once as a correctness check: all
configurations must download the same number of pages, bytes, and tags with
zero errors.

Output: results/<experiment>/runs.csv and results/<experiment>/meta.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import ROOT, Variant, build_server, build_variant, toolchain_version  # noqa: E402

FIELDS = ["round", "position", "config", "variant", "mode", "seed", "wall_ns", "pages", "bytes", "tags",
          "errors", "unix_time"]


def wait_for_port(host: str, port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"server {host}:{port} did not come up")


def crawler_cmd(binary: Path, cfg: dict, urls: str, host: str, port: int, seed: int) -> list[str]:
    cmd = [str(binary), "--mode", cfg["mode"], "--urls", urls, "--host", host, "--port", str(port),
           "--seed", str(seed)]
    for k, v in cfg.get("args", {}).items():
        cmd += [f"--{k}", str(v)]
    return cmd


def run_once(cmd: list[str], pre_cmd: str | None) -> dict:
    if pre_cmd:  # For example, toggling Turbo Boost or SMT on Linux (requires root).
        subprocess.run(pre_cmd, shell=True, check=True)
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode not in (0, 3):
        raise RuntimeError(f"crawler failed ({out.returncode}): {' '.join(cmd)}\n{out.stderr}")
    return json.loads(out.stdout.strip().splitlines()[-1])


def system_info(variants: list[Variant]) -> dict:
    info = {
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "toolchains": {t: toolchain_version(t) for t in sorted({v.toolchain for v in variants})},
    }
    try:
        if sys.platform == "darwin":
            info["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                         text=True).stdout.strip()
        else:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--reps", type=int, help="measured rounds (overrides the config)")
    ap.add_argument("--warmup", type=int, help="discarded warm-up rounds (overrides the config)")
    ap.add_argument("--seed", type=int, help="master seed (default: random, recorded in meta.json)")
    ap.add_argument("--out", help="output directory (default results/<config name>)")
    ap.add_argument("--no-build", action="store_true", help="reuse binaries already in build/")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    exp = json.loads(cfg_path.read_text())
    name = exp.get("name", cfg_path.stem)
    reps = args.reps or exp.get("reps", 40)
    warmup = args.warmup if args.warmup is not None else exp.get("warmup", 3)
    master_seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2**32)
    rng = random.Random(master_seed)
    out_dir = Path(args.out) if args.out else ROOT / "results" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    urls = str(ROOT / exp.get("urls", "data/urls.txt"))

    variants = {v["name"]: Variant.from_dict(v) for v in exp["variants"]}
    configs = exp["configs"]
    for c in configs:
        if c["variant"] not in variants:
            sys.exit(f"config {c['name']} uses unknown variant {c['variant']}")

    binaries: dict[str, Path] = {}
    for vname, v in variants.items():
        if args.no_build and (ROOT / "build" / vname / "crawler").exists():
            binaries[vname] = ROOT / "build" / vname / "crawler"
        else:
            print(f"[build] {v}", flush=True)
            binaries[vname] = build_variant(v)

    srv_cfg = exp.get("server", {"start": True})
    host, port = srv_cfg.get("host", "127.0.0.1"), int(srv_cfg.get("port", 18080))
    server = None
    if srv_cfg.get("start", True):
        server_bin = build_server()
        cmd = [str(server_bin), "--root", str(ROOT / srv_cfg.get("root", "data/pages")), "--bind", host,
               "--port", str(port), "--delay-us", str(srv_cfg.get("delay_us", 1000)),
               "--max-requests", str(srv_cfg.get("max_requests", 0))]
        server = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
        print(f"[server] {' '.join(cmd)}", flush=True)
    try:
        wait_for_port(host, port)

        # Correctness check: every configuration must perform identical work.
        print("[check] one run per configuration", flush=True)
        reference = None
        for c in configs:
            r = run_once(crawler_cmd(binaries[c["variant"]], c, urls, host, port, 1), c.get("pre_cmd"))
            work = (r["pages"], r["bytes"], r["tags"])
            if r["errors"] or (reference and work != reference):
                sys.exit(f"[check] FAILED for {c['name']}: {r} (expected pages/bytes/tags {reference})")
            reference = work
        print(f"[check] ok: all {len(configs)} configurations fetched pages/bytes/tags = {reference}")

        meta = {"experiment": name, "config_file": str(cfg_path), "master_seed": master_seed, "reps": reps,
                "warmup": warmup, "server": srv_cfg, "system": system_info(list(variants.values())),
                "experiment_config": exp}
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))

        total = (reps + warmup) * len(configs)
        done = 0
        t_start = time.monotonic()
        with open(out_dir / "runs.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for rnd in range(-warmup, reps):  # Negative rounds are warm-up rounds and are not recorded.
                order = configs[:]
                rng.shuffle(order)
                for pos, c in enumerate(order):
                    seed = rng.randrange(2**63)
                    r = run_once(crawler_cmd(binaries[c["variant"]], c, urls, host, port, seed), c.get("pre_cmd"))
                    done += 1
                    if rnd >= 0:
                        w.writerow({"round": rnd, "position": pos, "config": c["name"], "variant": c["variant"],
                                    "mode": c["mode"], "seed": seed, "wall_ns": r["wall_ns"], "pages": r["pages"],
                                    "bytes": r["bytes"], "tags": r["tags"], "errors": r["errors"],
                                    "unix_time": f"{time.time():.3f}"})
                    if r["errors"]:
                        print(f"  warning: {c['name']} round {rnd}: {r['errors']} errors", flush=True)
                f.flush()
                elapsed = time.monotonic() - t_start
                print(f"\r[run] {done}/{total} runs, {elapsed:.0f}s elapsed, "
                      f"~{elapsed / done * (total - done):.0f}s left   ", end="", flush=True)
        print(f"\n[done] {out_dir / 'runs.csv'}")
    finally:
        if server:
            server.terminate()
            server.wait()


if __name__ == "__main__":
    main()
