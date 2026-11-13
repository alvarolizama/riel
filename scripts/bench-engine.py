#!/usr/bin/env python3
"""Measure run status in-process and via subprocess, using an isolated worktree."""
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(REPO, "hermes_plugin", "riel", "engine", "run.py")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
DRAFT = """# Run: bench
<!-- riel-run/v1 -->

## Objective
A benchmark can restore run status.

## Context
### Why
Measure the real status path.

### Context keywords
- riel → code

## Constraints
- Isolate all benchmark state under scratch.

## Claims
- P1: status parses — anchor: §Graph

## Graph
- F1: record status
  - RUN true

## Gates
- G1: status — phase: F1

## Deliverable
A latency measurement.

## DO NOT
- Write outside the benchmark worktree.
"""


def execute(module, worktree, argv):
    code, out, err = module.run_verb(argv, worktree=worktree)
    if code:
        raise RuntimeError(err.strip() or out.strip())


def main():
    worktree = tempfile.mkdtemp(prefix="riel-bench-")
    try:
        spec = importlib.util.spec_from_file_location("riel_bench_engine", ENGINE)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load engine")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = os.path.join(worktree, ".riel", "run.md")
        os.makedirs(os.path.dirname(target))
        with open(target, "w", encoding="utf-8") as fixture:
            fixture.write(DRAFT)
        execute(module, worktree, ["run", "activate"])
        output, error = io.StringIO(), io.StringIO()
        start = time.perf_counter()
        for _ in range(N):
            module.run_verb(["run", "status"], worktree=worktree,
                            out=output, err=error)
        in_process = (time.perf_counter() - start) / N * 1000
        start = time.perf_counter()
        for _ in range(N):
            subprocess.run([sys.executable, ENGINE, "--worktree", worktree,
                            "run", "status"], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True)
        process = (time.perf_counter() - start) / N * 1000
        print("run status x{}:".format(N))
        print("  in-process: {:6.2f} ms/call".format(in_process))
        print("  subprocess: {:6.2f} ms/call".format(process))
        print("  speedup:    {:6.1f}x".format(process / in_process))
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


if __name__ == "__main__":
    main()
