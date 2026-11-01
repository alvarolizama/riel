"""Shared plumbing: one loader, one worktree resolver, one envelope.

Every sibling module in this package used to carry its own copy of three things:

  * a loader dance to load a neighbour *by path* — the
    host may import this package under any name, and the repo suite imports it
    directly, so a plain relative import is not guaranteed to be the loader the
    host picked;
  * a worktree resolver (session cwd → ``TERMINAL_CWD`` → process cwd) that
    existed in ``tools.py``, ``hooks.py`` and ``section.py`` with three
    slightly different orderings;
  * a hand-built result dict, so four tools invented their own envelope and a
    consumer had to know which tool answered to know which keys to read.

This module owns all three. It imports nothing from its siblings, so it is
itself loadable by path from ``dashboard/plugin_api.py`` (which runs outside
the package's import context).

Stdlib only, no Hermes import at module level.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, Dict, Optional

PLUGIN_DIR = Path(__file__).resolve().parent
ENGINE = PLUGIN_DIR / "engine" / "run.py"

_LOADED: Dict[str, Any] = {}


def sibling(name: str, filename: str) -> Any:
    """Load ``PLUGIN_DIR/<filename>`` as module *name*, once per process.

    Cached by path: the gate runs on every turn and the prompt section renders
    once per session, and both read ``settings.py``. Re-executing that module on
    every call was waste, not isolation — it holds no mutable state.
    """
    path = PLUGIN_DIR / filename
    key = str(path)
    if key not in _LOADED:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED[key] = module
    return _LOADED[key]


def settings():
    """The package's ``settings.py`` — the live half of the group switches."""
    return sibling("riel_plugin_settings", "settings.py")


def guide():
    """The package's ``guide.py`` — the prose index and its sections."""
    return sibling("riel_plugin_guide", "guide.py")


def _recorded(key: Optional[str]) -> Optional[str]:
    """The session's recorded cwd (the terminal tool's record), when Hermes is around.

    The import is lazy and defensive on purpose: internal module paths move
    between Hermes releases and a plugin must never fail to load because of it.
    """
    try:
        from tools.terminal_tool import get_session_cwd  # internal, may move

        recorded = get_session_cwd(key)
        return str(recorded) if recorded else None
    except Exception:
        return None


def session_cwd(key: Optional[str] = None, preferred: Optional[str] = None,
                recorded: bool = True) -> Optional[str]:
    """The session's worktree, or ``None`` when nothing knows it.

    Order: an explicit caller *preferred* value (the prompt section's payload)
    → the session's recorded cwd → ``TERMINAL_CWD`` → ``None``. Blank and
    relative values are normalized to absolute paths so a subprocess never
    resolves them against its own cwd.

    ``recorded=False`` is for the prompt section: it renders for ONE session
    from a payload that already carries that session's cwd, and in a gateway
    multiplexing several profiles a `get_session_cwd(None)` could answer for
    whichever session happens to be focused.
    """
    sources = [preferred]
    if recorded:
        sources.append(_recorded(key))
    sources.append(os.environ.get("TERMINAL_CWD"))
    for raw in sources:
        text = str(raw or "").strip()
        if text:
            return os.path.abspath(os.path.expanduser(text))
    return None


def worktree(kwargs: Optional[dict] = None, explicit: Optional[str] = None,
             preferred: Optional[str] = None) -> str:
    """The worktree a call belongs to: explicit → session → process cwd."""
    text = str(explicit or "").strip()
    if text:
        return os.path.abspath(os.path.expanduser(text))
    key = (kwargs or {}).get("task_id") or (kwargs or {}).get("session_key")
    return session_cwd(key, preferred=preferred) or os.getcwd()


def envelope(tool: str, worktree: str = "", exit_code: int = 0,
             stdout: str = "", stderr: str = "", **fields) -> dict:
    """The ONE result shape every tool answers with.

    ``{tool, worktree, exit_code, passed, stdout, stderr}`` plus the tool's own
    keys. ``passed`` is derived, never passed in — a caller that folds tools
    reads the same two keys from all of them.
    """
    payload = {
        "tool": tool,
        "worktree": worktree,
        "exit_code": exit_code,
        "passed": exit_code == 0,
        "stdout": stdout,
        "stderr": stderr,
    }
    payload.update(fields)
    return payload


def error(message: str, **fields) -> dict:
    """The one refusal shape: ``{error, ...}``, with no fake exit code."""
    payload = {"error": message}
    payload.update(fields)
    return payload