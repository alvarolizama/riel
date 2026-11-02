#!/usr/bin/env python3
"""Latency of the engine, in-process vs subprocess — the tools' two paths.

Measures N `seam --mode json` calls against one seeded worktree, both ways:

    python3 scripts/bench-engine.py            # N = 200

The numbers land in the ledger's ✓ checkpoints (P4 of the simplification
contract) and in the README's efficiency note.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.path.join(REPO, "hermes_plugin", "riel", "engine", "run.py")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 200


def seed(worktree):
    d = os.path.join(worktree, ".riel")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "ledger.md"), "w", encoding="utf-8") as fh:
        fh.write("# Riel ledger\n\n## Goal\nbench\n\n## Next\nn\n")


def in_process(n):
    spec = importlib.util.spec_from_file_location("riel_engine", ENGINE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    argv = ["seam", "--mode", "json"]
    t0 = time.perf_counter()
    for _ in range(n):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            module.run_verb(argv, worktree=WORKTREE)
    return (time.perf_counter() - t0) / n * 1000


def via_subprocess(n):
    argv = [sys.executable, ENGINE, "--worktree", WORKTREE, "seam", "--mode", "json"]
    t0 = time.perf_counter()
    for _ in range(n):
        subprocess.run(argv, capture_output=True, text=True)
    return (time.perf_counter() - t0) / n * 1000


if __name__ == "__main__":
    WORKTREE = tempfile.mkdtemp(prefix="riel-bench-")
    try:
        seed(WORKTREE)
        ip = in_process(N)
        sp = via_subprocess(N)
        print("seam --mode json x{}:".format(N))
        print("  in-process: {:6.2f} ms/call".format(ip))
        print("  subprocess: {:6.2f} ms/call".format(sp))
        print("  speedup:    {:6.1f}x".format(sp / ip if ip else float("inf")))
    finally:
        shutil.rmtree(WORKTREE, ignore_errors=True)
