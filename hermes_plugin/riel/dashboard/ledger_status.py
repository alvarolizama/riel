"""The worktree's CONTRACTS for the desktop chip — safe, bounded reads.

Stdlib only, and importable without FastAPI so the repo suite can test it
directly. Contracts live in `.riel/runs/<slug>.md` and are executed in place;
several may be active at once (parallel tracks in one worktree).

Two answers, two shapes:

* `read_runs(worktree)` → the LISTING the chip's counter and dialog list use:
  `{present, worktree, contracts, active, pending, total, …}`. Each contract
  carries its slug, path, engine status and pending counts — no markdown, so
  the listing stays light however many tracks there are.
* `read_run(worktree, slug)` → ONE contract: its verbatim markdown (capped)
  for the dialog plus the engine's own status object.

The engine is reached the SAFE way — in-process, through the tools' loader
(explicit worktree, explicit sinks) — never a subprocess, and never a raw
path: the worktree is symlink-resolved and every contract file must land
inside it after resolution.

Never raises: the caller is an HTTP route and the chip must degrade to
"no contracts" instead of a 500.
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
# A contract is working memory for the task in flight, not a book — if it ever
# grows past this, the dialog still opens, it just stops at the cap.
MAX_RUN_CHARS = 262_144
_RUNS_PARTS = (".riel", "runs")


def _blank(worktree: str) -> dict:
    return {"present": False, "worktree": worktree, "markdown": "", "chars": 0,
            "status": None, "updated": None, "stale_secs": None}


def _blank_listing(worktree: str) -> dict:
    return {"present": False, "worktree": worktree, "contracts": [],
            "active": 0, "pending": 0, "total": 0,
            "updated": None, "stale_secs": None}


def _resolve(worktree: str) -> tuple:
    """(root, error) — the worktree symlink-resolved, or the reason it is junk."""
    raw = str(worktree or "").strip()
    if not raw:
        # An empty value must NOT fall back to the gateway's cwd: that would
        # silently report some unrelated directory's contracts.
        return "", "worktree is required"
    try:
        root = os.path.realpath(os.path.abspath(os.path.expanduser(raw)))
    except (OSError, ValueError) as exc:
        return "", f"worktree is unusable: {exc}"
    if not os.path.isdir(root):
        return root, "worktree is not a directory"
    return root, ""


def _contract_path(root: str, slug: str):
    """(path, error) — one contract, refusing to escape the worktree via symlinks."""
    name = str(slug or "").strip()
    if name.endswith(".md"):
        name = name[:-3]
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return None, "slug must be a bare contract name"
    folder = Path(root).joinpath(*_RUNS_PARTS)
    candidate = folder / (name + ".md")
    try:
        if candidate.is_symlink() or folder.is_symlink():
            return None, "the contract path contains a symlink"
        resolved = Path(os.path.realpath(candidate))
    except (OSError, ValueError) as exc:
        return None, f"contract path is unusable: {exc}"
    if not str(resolved).startswith(str(root) + os.sep):
        return None, "the contract path escapes the worktree (symlink)"
    if not resolved.is_file():
        return None, ""
    return resolved, ""


def _contract_paths(root: str) -> list:
    """[(slug, path)] for every contract in .riel/runs/ — backups are not contracts."""
    folder = Path(root).joinpath(*_RUNS_PARTS)
    try:
        if folder.is_symlink() or not folder.is_dir():
            return []
        names = sorted(p.name for p in folder.iterdir())
    except (OSError, ValueError):
        return []
    out = []
    for name in names:
        if not name.endswith(".md") or name.endswith(".bak.md"):
            continue
        path, error = _contract_path(root, name[:-3])
        if path is not None and not error:
            out.append((name[:-3], path))
    return out


def _engine_list(root: str) -> dict:
    """The engine's `run list` object, `{}` with `error` when it fails."""
    try:
        payload = json.loads(tools.riel_run({"verb": "list", "worktree": root}))
    except Exception as exc:
        return {"error": f"the engine's list call failed: {exc}"}
    if payload.get("error"):
        return {"error": payload["error"]}
    if payload.get("exit_code") != 0:
        return {"error": (payload.get("stderr") or "").strip() or "the engine's list call failed"}
    try:
        listing = json.loads(payload.get("stdout") or "{}")
    except ValueError:
        return {"error": "the engine's list call did not return JSON"}
    return listing if isinstance(listing, dict) else {
        "error": "the engine's list call did not return an object"}


def _engine_status(root: str, slug: str) -> dict:
    """One contract's `run status` object, `{}` with `error` when it fails."""
    try:
        payload = json.loads(tools.riel_run(
            {"verb": "status", "worktree": root, "run": slug}))
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
    return state if isinstance(state, dict) else {
        "error": "the engine's status call did not return an object"}


def _pending(state: dict, key: str, done_value: str) -> int:
    register = state.get(key)
    if isinstance(register, dict):
        return sum(1 for v in register.values() if v != done_value)
    if isinstance(register, list):
        return sum(1 for v in register
                   if not (isinstance(v, dict) and v.get("status") == done_value))
    return 0


def _is_active(state: dict) -> bool:
    if state.get("status") == "active":
        return True
    return bool(state.get("active") is True or state.get("revision"))


def _mtime(path) -> tuple:
    try:
        updated = int(path.stat().st_mtime)
        return updated, max(0, int(time.time()) - updated)
    except OSError:
        return None, None


def read_runs(worktree: str, timeout: int = TIMEOUT_SECS) -> dict:
    """Every contract in the worktree — the chip's counter and dialog list.

    `active` counts activated contracts; `pending` counts those with claims or
    gates still lacking evidence, so the chip shows `pending/active`. A
    worktree without contracts is a normal `present: false`, not an error.
    """
    root, error = _resolve(worktree)
    report = _blank_listing(root)
    if error:
        report["error"] = error
        if not root:
            report["worktree"] = ""
        return report
    paths = _contract_paths(root)
    if not paths:
        return report
    listing = _engine_list(root)
    if listing.get("error"):
        report["error"] = listing["error"]
        return report
    by_slug = {c.get("slug"): c for c in (listing.get("contracts") or [])
               if isinstance(c, dict)}
    newest, rows = None, []
    for slug, path in paths:
        state = by_slug.get(slug) or {}
        updated, stale = _mtime(path)
        if updated is not None and (newest is None or updated > newest):
            newest = updated
        rows.append({
            "slug": slug,
            "run": os.path.relpath(path, root),
            "status": state,
            "active": _is_active(state),
            "done": bool(state.get("done")),
            "pending_claims": _pending(state, "claims", "covered"),
            "pending_gates": _pending(state, "gates", "passed"),
            "current_phase": state.get("current_phase"),
            "next": state.get("next"),
            "revision": state.get("revision"),
            "updated": updated,
            "stale_secs": stale,
        })
    report["present"] = True
    report["contracts"] = rows
    report["total"] = len(rows)
    report["active"] = sum(1 for r in rows if r["active"])
    report["pending"] = sum(1 for r in rows
                            if r["active"] and (r["pending_claims"] or r["pending_gates"]))
    report["updated"] = newest
    report["stale_secs"] = max(0, int(time.time()) - newest) if newest else None
    return report


def read_run(worktree: str, slug: str = "", timeout: int = TIMEOUT_SECS) -> dict:
    """ONE contract, verbatim + the engine's status — or `present: False`.

    `timeout` bounds the engine call (the tools layer enforces it); the read
    itself is bounded by `MAX_RUN_CHARS`. A worktree without that contract is
    a normal answer, not an error.
    """
    root, error = _resolve(worktree)
    report = _blank(root)
    if error:
        report["error"] = error
        if not root:
            report["worktree"] = ""
        return report
    if not str(slug or "").strip():
        report["error"] = "slug query parameter is required"
        return report
    path, error = _contract_path(root, slug)
    if error:
        report["error"] = error
        return report
    if path is None:
        return report  # no such contract here: the normal absent case

    report["updated"], report["stale_secs"] = _mtime(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, encoding="utf-8", errors="replace") as handle:
            text = handle.read(MAX_RUN_CHARS + 1)
    except OSError as exc:
        report["error"] = f"contract unreadable: {exc}"
        return report
    if len(text) > MAX_RUN_CHARS:
        text = text[:MAX_RUN_CHARS] + "\n\n<!-- truncated at 256 KiB -->"
    name = path.name[:-3]
    report["present"] = True
    report["slug"] = name
    report["markdown"] = text
    report["chars"] = len(text)
    report["status"] = _engine_status(root, name)
    return report
