#!/usr/bin/env python3
"""Builds crawler variants (toolchain x opt-level x RUSTFLAGS) into build/<name>/crawler.

The compile-time factors in the paper were the compiler (GCC 11 or Clang 12),
the optimization level (-O0 to -O3), and -march=native. The Rust equivalents are:

    compiler      -> toolchain           (cargo +stable / cargo +nightly)
    -O0..-O3      -> opt_level 0..3      (CARGO_PROFILE_RELEASE_OPT_LEVEL)
    -march=native -> rustflags "-C target-cpu=native"

Usage:

    python bench/build.py stable-O3:stable:3 nightly-O0-native:nightly:0:-Ctarget-cpu=native
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Variant:
    name: str
    toolchain: str = "stable"
    opt_level: int | str = 3
    rustflags: str = ""

    @staticmethod
    def from_dict(d: dict) -> "Variant":
        return Variant(d["name"], d.get("toolchain", "stable"), d.get("opt_level", 3), d.get("rustflags", ""))


def build_env() -> dict[str, str]:
    env = dict(os.environ)
    # On macOS, rustc links through `cc`. The Command Line Tools work even if the
    # full Xcode license has not been accepted.
    clt = Path("/Library/Developer/CommandLineTools/usr/bin")
    if sys.platform == "darwin" and clt.exists():
        env.setdefault("DEVELOPER_DIR", str(clt.parent.parent))
    return env


def toolchain_version(toolchain: str) -> str:
    out = subprocess.run(["rustc", f"+{toolchain}", "--version"], capture_output=True, text=True,
                         env=build_env(), cwd=ROOT)
    return out.stdout.strip() or out.stderr.strip()


def build_variant(v: Variant, quiet: bool = True) -> Path:
    env = build_env()
    env["CARGO_TARGET_DIR"] = str(ROOT / "target" / "variants" / v.name)
    env["CARGO_PROFILE_RELEASE_OPT_LEVEL"] = str(v.opt_level)
    env["RUSTFLAGS"] = v.rustflags
    env["CRAWLER_BUILD_TAG"] = v.name
    cmd = ["cargo", f"+{v.toolchain}", "build", "--release", "--bin", "crawler"]
    if quiet:
        cmd.append("--quiet")
    subprocess.run(cmd, check=True, env=env, cwd=ROOT)
    out_dir = ROOT / "build" / v.name
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "crawler"
    shutil.copy2(Path(env["CARGO_TARGET_DIR"]) / "release" / "crawler", dst)
    return dst


def build_server() -> Path:
    env = build_env()
    subprocess.run(["cargo", "build", "--release", "--quiet", "--bin", "static_server"], check=True, env=env, cwd=ROOT)
    return ROOT / "target" / "release" / "static_server"


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    for spec in sys.argv[1:]:
        parts = spec.split(":", 3)
        v = Variant(parts[0], *(parts[1:3]), *(parts[3:]))  # type: ignore[arg-type]
        print(f"building {v} ...", flush=True)
        print("  ->", build_variant(v, quiet=False))


if __name__ == "__main__":
    main()
