"""Tool handlers — machinery for the Riel plugin.

Every handler runs the **vendored** `rielctl` in a fresh subprocess whose cwd
is the session's worktree. `rielctl` stays the sole writer of
`.riel/ledger.md`: this module adds no ledger semantics, no format, no state of
its own.

Why a subprocess instead of importing rielctl in-process: rielctl resolves
`.riel/` relative to the process cwd, and its `DEFAULT_TEMPLATE_DIRS` freezes
`os.getcwd()` at import time. Inside a long-lived Hermes process (a gateway
serving several sessions) an `os.chdir` would be global state shared by every
session; a subprocess gives each call its own cwd, so concurrent sessions
cannot write into each other's ledger.

Stdlib only, and importable outside Hermes: nothing here imports Hermes at
module level, so the repo's test suite can exercise these handlers directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent
RIELCTL = _PLUGIN_DIR / "vendor" / "riel-cli" / "scripts" / "rielctl"
TIMEOUT_SECS = 60

_STR_FLAGS = {
    "goal": "--goal",
    "next": "--next",
    "source": "--source",
    "phase": "--phase",
    "core": "--core",
    "claim": "--claim",
    "verify_with": "--verify-with",
    "check": "--check",
    "by": "--by",
    "covering": "--covering",
    "open": "--open",
    "settled_by": "--settled-by",
}
_INT_FLAGS = {
    "core_slot": "--core-slot",
    "confidence": "--confidence",
    "close": "--close",
}


def _error(message: str, **extra) -> str:
    payload = {"error": message}
    payload.update(extra)
    return json.dumps(payload)


def _session_worktree(kwargs: dict) -> str:
    """The worktree this call belongs to.

    Order: the session's recorded cwd (the same record the terminal tool uses,
    so both routes agree on where `.riel/` lives) → ``TERMINAL_CWD`` → the
    process cwd. The Hermes import is lazy and defensive: internal module paths
    move between releases and a plugin must never fail to load because of it.
    """
    key = kwargs.get("task_id") or kwargs.get("session_key")
    try:
        from tools.terminal_tool import get_session_cwd  # internal, may move

        recorded = get_session_cwd(key)
        if recorded:
            return str(recorded)
    except Exception:
        pass
    env = (os.environ.get("TERMINAL_CWD") or "").strip()
    if env:
        # Hermes sets this absolute; abspath keeps a hand-set relative value safe
        # (the subprocess would otherwise resolve it against the process cwd).
        return os.path.abspath(os.path.expanduser(env))
    return os.getcwd()


def _worktree(args: dict, kwargs: dict) -> str:
    explicit = str(args.get("worktree") or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    return _session_worktree(kwargs)


def _run(argv: list, args: dict, kwargs: dict) -> str:
    """Run rielctl in the worktree; always return a JSON string, never raise."""
    worktree = _worktree(args, kwargs)
    if not os.path.isdir(worktree):
        return _error(f"worktree is not a directory: {worktree}", worktree=worktree)
    if not RIELCTL.exists():
        return _error(
            "vendored rielctl is missing — the plugin package was built without it",
            path=str(RIELCTL),
            hint="from the repo checkout: make plugin-vendor",
        )
    try:
        proc = subprocess.run(
            [sys.executable, str(RIELCTL), *argv],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        return _error(f"rielctl timed out after {TIMEOUT_SECS}s", command=argv, worktree=worktree)
    except OSError as exc:
        return _error(f"rielctl could not be executed: {exc}", command=argv, worktree=worktree)
    return json.dumps(
        {
            "command": ["rielctl", *argv],
            "worktree": worktree,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    )


def _flag_args(args: dict) -> list:
    """Map tool arguments onto rielctl's flags (values only, no interpretation)."""
    argv: list = []
    for key, flag in _STR_FLAGS.items():
        value = args.get(key)
        if value is None or str(value).strip() == "":
            continue
        argv += [flag, str(value)]
    for key, flag in _INT_FLAGS.items():
        value = args.get(key)
        if value is None or value == "":
            continue
        try:
            argv += [flag, str(int(value))]
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer, got {value!r}")
    return argv


def _from_contract_args(args: dict) -> list:
    raw = args.get("from_contract")
    if raw is None:
        return []
    value = str(raw).strip()
    if value == "" or value.lower() in {"false", "no", "0"}:
        return []
    if value.lower() in {"true", "yes", "1"}:
        return ["--from-contract"]
    return ["--from-contract", os.path.expanduser(value)]


def riel_note(args: dict, **kwargs) -> str:
    """Append/update ledger entries via `rielctl note`."""
    try:
        argv = _flag_args(args) + _from_contract_args(args)
    except ValueError as exc:
        return _error(str(exc))
    if not argv:
        keys = ", ".join(sorted([*_STR_FLAGS, *_INT_FLAGS, "from_contract"]))
        return _error(
            "riel_note needs at least one content flag (or from_contract)",
            accepted=keys,
            note="with no flags rielctl note just re-prints the ledger; use riel_seam for that",
        )
    return _run(["note", *argv], args, kwargs)


def _passthrough(verb: str):
    def handler(args: dict, **kwargs) -> str:
        return _run([verb], args, kwargs)

    return handler


riel_seam = _passthrough("seam")
riel_resume = _passthrough("resume")
riel_todo = _passthrough("todo")

HANDLERS = {
    "riel_note": riel_note,
    "riel_seam": riel_seam,
    "riel_resume": riel_resume,
    "riel_todo": riel_todo,
}
