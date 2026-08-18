#!/usr/bin/env python3
"""Extract ```mermaid blocks from a markdown file into .mmd files.

Usage: extract-mermaid.py <input.md> <out_dir>
Writes out_dir/<NNN>.mmd (one per block, order preserved).
"""
import re
import sys
import os


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, out_dir = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        content = fh.read()
    blocks = re.findall(r"```mermaid\n(.*?)```", content, re.DOTALL)
    os.makedirs(out_dir, exist_ok=True)
    for i, block in enumerate(blocks, 1):
        with open(os.path.join(out_dir, f"{i:03d}.mmd"), "w", encoding="utf-8") as fh:
            fh.write(block.strip() + "\n")
    if not blocks:
        # no mermaid in this file: emit nothing, exit 0
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
