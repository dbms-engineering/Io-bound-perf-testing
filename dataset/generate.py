#!/usr/bin/env python3
"""Generates a deterministic synthetic HTML corpus and its URL list.

The paper crawls a fixed set of 130,000 real HTML pages served from a RAM disk.
That dataset is available only through a link shortener, so this script
generates a reproducible substitute: page sizes follow a log-normal
distribution (as is typical of real web pages), and each page consists of
randomly nested common tags.

Usage:

    python dataset/generate.py --pages 4000 --out data
    # -> data/pages/000000.html ... and data/urls.txt (/pages/000000.html per line)

To use the original dataset from the paper instead, extract it to data/pages
and run
    python dataset/generate.py --index-only --out data
which only writes data/urls.txt for the existing files.
"""
from __future__ import annotations

import argparse
import math
import os
import random
from pathlib import Path

TAGS = ["div", "span", "p", "a", "li", "ul", "img", "td", "tr", "table", "h1", "h2", "h3",
        "section", "article", "header", "footer", "nav", "strong", "em", "code", "pre", "button",
        "input", "form", "label", "script", "meta", "link"]
WORDS = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
         "incididunt ut labore et dolore magna aliqua edge computing africa latency").split()


def make_page(rng: random.Random, target_bytes: int, idx: int) -> str:
    parts = [f"<!DOCTYPE html>\n<html><head><title>Page {idx}</title>",
             '<meta charset="utf-8"><link rel="stylesheet" href="/s.css"></head><body>\n']
    size = sum(len(p) for p in parts)
    stack: list[str] = []
    while size < target_bytes:
        r = rng.random()
        if r < 0.45 or not stack:
            tag = rng.choice(TAGS)
            attrs = f' class="c{rng.randrange(50)}"' if rng.random() < 0.6 else ""
            if tag == "a":
                attrs += f' href="/pages/{rng.randrange(1_000_000):06d}.html"'
            chunk = f"<{tag}{attrs}>"
            if tag in ("img", "input", "meta", "link"):
                chunk = f"<{tag}{attrs} />"
            else:
                stack.append(tag)
        elif r < 0.75:
            chunk = " ".join(rng.choices(WORDS, k=rng.randrange(3, 25))) + " "
        elif r < 0.78:
            chunk = "<!-- generated comment -->"
        else:
            chunk = f"</{stack.pop()}>\n"
        parts.append(chunk)
        size += len(chunk)
    while stack:
        parts.append(f"</{stack.pop()}>")
    parts.append("\n</body></html>\n")
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pages", type=int, default=4000, help="number of pages (paper: 130000)")
    ap.add_argument("--median-kb", type=float, default=8.0, help="median page size in KiB")
    ap.add_argument("--sigma", type=float, default=0.8, help="log-normal sigma of the page size")
    ap.add_argument("--seed", type=int, default=2022)
    ap.add_argument("--out", default="data")
    ap.add_argument("--index-only", action="store_true", help="only (re)write urls.txt for existing pages")
    args = ap.parse_args()

    out = Path(args.out)
    pages = out / "pages"
    pages.mkdir(parents=True, exist_ok=True)

    if not args.index_only:
        rng = random.Random(args.seed)
        mu = math.log(args.median_kb * 1024)
        total = 0
        for i in range(args.pages):
            target = int(min(max(rng.lognormvariate(mu, args.sigma), 512), 2_000_000))
            html = make_page(rng, target, i)
            (pages / f"{i:06d}.html").write_text(html, encoding="utf-8")
            total += len(html)
        print(f"wrote {args.pages} pages, {total / 2**20:.1f} MiB, into {pages}")

    names = sorted(n for n in os.listdir(pages) if not n.startswith("."))
    with open(out / "urls.txt", "w", encoding="utf-8") as f:
        for n in names:
            f.write(f"/pages/{n}\n")
    print(f"wrote {len(names)} URLs to {out / 'urls.txt'}")


if __name__ == "__main__":
    main()
