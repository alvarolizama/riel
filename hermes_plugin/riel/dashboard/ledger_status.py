"""The worktree's ACTIVE RUN for the desktop chip — one safe, bounded read.

Stdlib only, and importable without FastAPI so the repo suite can test it
directly. It answers ONE shape — `{present, worktree, markdown, status}` —
where `markdown` is `.riel/run.md` verbatim (capped) for the chip's click
dialog and `status` is the engine's own `run status` JSON object (the state
the gate folds). The engine is reached the SAFE way — in-process, through the
tools' loader (explicit worktree, explicit sinks) — never a subprocess, and
never a raw path: the worktree is symlink-resolved and the run file must land
inside it after resolution.

Never raises: the caller is an HTTP route and the chip must degrade to
"no run" instead of a 500.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

try:  # a package import when the host loaded us as one …
    from .. import tools
except ImportError:  # … a by-path load when it did not (repo suite, dashboard)
    import importlib.util as _ilu

    _spec = _ilu.spec_from_file_location(
        "riel_dashboard_load", str(Path(__file__).resolve().parent.parent / "_load.py"))
    if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("cannot load _load.py beside the dashboard")
    _load = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_load)
    tools = _load.sibling("riel_plugin_tools", "tools.py")

PLUGIN_DIR = Path(__file__).resolve().parent.parent
ENGINE = PLUGIN_DIR / "engine" / "run.py"
TIMEOUT_SECS = 15
# A run is working memory for the task in flight, not a book — if it ever
# grows past this, the dialog still opens, it just stops at the cap.
MAX_RUN_CHARS = 262_144
_RUN_PARTS = (".riel", "run.md")


def _blank(worktree: str) -> dict:
    return {"present": False, "worktree": worktree, "markdown": "", "chars": 0,
            "status": None, "updated": None, "stale_secs": None}


def _resolve(worktree: str) -> tuple:
    """(root, error) — the worktree symlink-resolved, or the reason it is junk."""
    raw = str(worktree or "").strip()
    if not raw:
        # An empty value must NOT fall back to the gateway's cwd: that would
        # silently report some unrelated directory's run.
        return "", "worktree is required"
    try:
        root = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))
    except (OSError, ValueError) as exc:
        return "", f"worktree is unusable: {exc}"
    if not os.path.isdir(root):
        return root, "worktree is not a directory"
    return root, ""


def _run_path(root: str) -> tuple:
    """(path, error) — the run file, refusing to escape the worktree via symlinks."""
    candidate = Path(root).joinpath(*_RUN_PARTS)
    try:
        if candidate.is_symlink() or candidate.parent.is_symlink():
            return None, "the run path contains a symlink"
        resolved = Path(os.path.realpath(candidate))
    except (OSError, ValueError) as exc:
        return None, f"run path is unusable: {exc}"
    if not str(resolved).startswith(str(root) + os.sep):
        return None, "the run path escapes the worktree (symlink)"
    if not resolved.is_file():
        return None, ""
    return resolved, ""


def _engine_status(root: str) -> dict:
    """The engine's `run status` object, `{}` with `error` when it fails."""
    try:
        payload = json.loads(tools.riel_run({"verb": "status", "worktree": root}))
    except Exception as exc:
        return {"error": f"the engine's status call failed: {exc}"}
    if payload.get("error"):
        return {"error": payload["error"]}
    if payload.get("exit_code") != 0:
        return {"error": (payload.get("stderr") or "").strip() or "the engine's status call failed"}
    try:
        state = json.loads(payload.get("stdout") or "{}")
    except ValueError:
        return {"error": "the engine's status call did not return JSON"}
    return state if isinstance(state, dict) else {"error": "the engine's status call did not return an object"}


def read_run(worktree: str, timeout: int = TIMEOUT_SECS) -> dict:
    """The worktree's run, verbatim + the engine's status — or `present: False`.

    `timeout` bounds the engine call (the tools layer enforces it); the read
    itself is bounded by `MAX_RUN_CHARS`. A worktree without a run is a
    normal answer, not an error.
    """
    root, error = _resolve(worktree)
    report = _blank(root)
    if error:
        report["error"] = error
        if not root:
            report["worktree"] = ""
        return report

    path, error = _run_path(root)
    if error:
        report["error"] = error
        return report
    if path is None:
        return report  # no .riel/run.md here: the normal absent case

    try:
        report["updated"] = int(path.stat().st_mtime)
        report["stale_secs"] = max(0, int(time.time()) - report["updated"])
    except OSError:
        pass
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, encoding="utf-8", errors="replace") as handle:
            text = handle.read(MAX_RUN_CHARS + 1)
    except OSError as exc:
        report["error"] = f"run unreadable: {exc}"
        return report
    if len(text) > MAX_RUN_CHARS:
        text = text[:MAX_RUN_CHARS] + "\n\n<!-- truncated at 256 KiB -->"
    report["present"] = True
    report["markdown"] = text
    report["chars"] = len(text)
    report["status"] = _engine_status(root)
    return report
