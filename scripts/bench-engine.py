#!/usr/bin/env python3
"""Measure run status in-process and via subprocess, using an isolated worktree.

The fixture is a real contract in the current format: one bound shaping, the
frame (Objective, Context, Deliverable, Constraints, DO NOT) and ONE phase with
its own Claims, Gates and Deliverable. It is executed in place at
.riel/runs/bench.md — there is no live run file to copy.
"""
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

SHAPING = """# Shaping: bench
<!-- riel-shaping/v3 id:shp_be0c0001 -->

## Question
Can the bench restore run status?

## Answer
Yes — supported by F1

## Findings
### F1: status is derived from evidence
The status verb reads the contract and computes the cursor.
— source: repo@HEAD:src/status.py:1-5#run_verb, confidence high

## Facts
- The benchmark stays inside its own worktree.

## Not wanted
- A1: measuring through the tool layer — verdict: discarded, it adds the envelope.

## What we want
- We need: a latency number for run status.
- Claim seeds: status parses.
- Scope: in — the engine; out — the plugin surface.

## Open
- Q1: does the subprocess path dominate? — settled by: this benchmark
"""

DRAFT = """# Run: bench
<!-- riel-run/v1 -->

## Objective
A benchmark can restore run status.

## Context
### Why
Measure the real status path.

### Context keywords
- riel → code

### Shaping
- shaping: .riel/shapings/bench.md

## Deliverable
A latency measurement.

## Constraints
- Isolate all benchmark state under the benchmark worktree.

## DO NOT
- Write outside the benchmark worktree.

## Phases
### F1: record status
- CREATE the contract fixture
- READ status repeatedly

#### Claims
- P1: status parses — anchor: shaping:F1

#### Gates
- G1: bench — cmd: true

#### Deliverable
- The measured latency.
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
        runs = os.path.join(worktree, ".riel", "runs")
        shapings = os.path.join(worktree, ".riel", "shapings")
        os.makedirs(runs)
        os.makedirs(shapings)
        os.makedirs(os.path.join(worktree, "src"))
        with open(os.path.join(worktree, "src", "status.py"), "w", encoding="utf-8") as fh:
            fh.write("# status helper\n\ndef run_verb():\n    return 0\n\n# end\n")
        with open(os.path.join(shapings, "bench.md"), "w", encoding="utf-8") as fh:
            fh.write(SHAPING)
        with open(os.path.join(runs, "bench.md"), "w", encoding="utf-8") as fh:
            fh.write(DRAFT)
        execute(module, worktree, ["run", "activate", "--run", "bench"])
        output, error = io.StringIO(), io.StringIO()
        start = time.perf_counter()
        for _ in range(N):
            module.run_verb(["run", "status", "--run", "bench"], worktree=worktree,
                            out=output, err=error)
        in_process = (time.perf_counter() - start) / N * 1000
        start = time.perf_counter()
        for _ in range(N):
            subprocess.run([sys.executable, ENGINE, "--worktree", worktree,
                            "run", "status", "--run", "bench"],
                           stdout=subprocess.DEVNULL,
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
