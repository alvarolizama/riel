"""`pre_verify` — the Riel checkpoint rule, enforced by the runtime.

Riel's own rule (`riel-ledger`): a ✓ checkpoint exists only with the real gate
output behind it. Until now that was prose in a skill; this hook makes the turn
loop hold the line — after a turn that edited code inside a Riel-tracked
worktree, if the ledger carries claims and no verified checkpoint with evidence,
the plugin answers `{"action": "continue", "message": …}` and the agent keeps
going instead of closing the turn.

Bounds that keep it honest:

  * **Opt-in per worktree.** No `.riel/ledger.md` anywhere above the edited
    files → never nudge. This hook is not a global nag.
  * **Self-throttled.** At most `gate_attempts` nudges per turn (default 1), on
    top of Hermes' own cap (`agent.max_verify_nudges`, 3 by default).
  * **Never blocks.** Every failure path — no ledger, missing vendored rielctl,
    unparseable `status` JSON, subprocess timeout — returns `None` and lets
    the turn finish. A gate that jams is worse than no gate.

Stdlib only and importable without Hermes: the only Hermes touch is the lazy
session-cwd lookup, and it is optional (the edited paths are the primary hint).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
RIELCTL = PLUGIN_DIR / "vendor" / "riel-cli" / "scripts" / "rielctl"
LEDGER_PARTS = (".riel", "ledger.md")
EVIDENCE_MARKER = "verified by:"
MAX_ANCESTOR_DEPTH = 12
TIMEOUT_SECS = 15

# Filled by register(); the defaults keep the module usable standalone (tests).
SETTINGS = {"enabled": True, "attempts": 1}


def _has_ledger(directory: Path) -> bool:
    try:
        return directory.joinpath(*LEDGER_PARTS).is_file()
    except (OSError, ValueError):
        # ValueError: a NUL byte or an unrepresentable path — never our problem.
        return False


def _normalize(raw, *, require_absolute: bool = False) -> Path | None:
    """Absolute, symlink-resolved path for *raw*, or None when it is junk.

    ``require_absolute`` is for *edited file* paths: Hermes records absolute
    paths, and a relative one can only be resolved against this process's cwd —
    the exact guess this gate must not make.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        candidate = Path(os.path.expanduser(text))
    except (OSError, ValueError):
        return None
    if require_absolute and not candidate.is_absolute():
        return None
    if not candidate.is_absolute():
        candidate = Path(os.path.abspath(text))
    try:
        return Path(os.path.realpath(candidate))
    except (OSError, ValueError):
        return None


def find_worktree(changed_paths, session_cwd=None, max_depth: int = MAX_ANCESTOR_DEPTH) -> str | None:
    """The Riel-tracked worktree this turn's edits belong to, or None.

    The **edited files win** over the session cwd: the gate asks "did you verify
    the code you just touched", and a turn can edit a worktree other than the
    one the session sits in (absolute paths, several repos). The session cwd is
    the fallback for the case where no edited path resolves to a tracked
    worktree.

    Both are guesses that only count when a ledger is actually there — "no
    ledger" means "not a Riel task", never "use the gateway's cwd". Blanks and
    relative paths are skipped for the same reason: `Path("")` is `.`, which
    would silently answer about whatever directory the process runs in.
    """
    candidates = []
    for raw in changed_paths or []:
        start = _normalize(raw, require_absolute=True)
        if start is None:
            continue
        if not start.is_dir():
            start = start.parent
        candidates.append(start)
        # `Path.parents` takes no slice on Python 3.9 — count instead.
        for depth, parent in enumerate(start.parents):
            if depth >= max_depth:
                break
            candidates.append(parent)
    candidates.append(_normalize(session_cwd))
    for candidate in candidates:
        if candidate is not None and _has_ledger(candidate):
            return str(candidate)
    return None


def assess(worktree, rielctl: Path = RIELCTL, timeout: int = TIMEOUT_SECS) -> dict:
    """Ledger facts the gate decides on. Never raises."""
    facts = {"present": False, "claims": [], "verified": [], "verified_with_evidence": [], "error": None}
    root = _normalize(worktree)
    if root is None or not root.is_dir() or not _has_ledger(root):
        return facts
    facts["present"] = True
    if not rielctl.exists():
        facts["error"] = "vendored rielctl is missing (run: make plugin-vendor)"
        return facts
    try:
        proc = subprocess.run(
            [sys.executable, str(rielctl), "status"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        facts["error"] = f"rielctl could not run: {exc}"
        return facts
    if proc.returncode != 0:
        facts["error"] = (proc.stderr or "").strip() or "rielctl status failed"
        return facts
    try:
        items = json.loads(proc.stdout)
    except ValueError:
        facts["error"] = "rielctl status did not return JSON"
        return facts
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        content = str(item.get("content") or "")
        if item_id.startswith("claim-"):
            facts["claims"].append(item_id)
        elif item_id.startswith("done-"):
            facts["verified"].append(item_id)
            if EVIDENCE_MARKER in content.lower():
                facts["verified_with_evidence"].append(item_id)
    return facts


def nudge_message(worktree: str, facts: dict) -> str | None:
    """The continuation message, or None when the ledger already holds the line."""
    if not facts.get("present"):
        return None
    if facts.get("error"):
        return None
    if facts["verified_with_evidence"]:
        return None
    pending = len(facts["claims"])
    if not pending and not facts["verified"]:
        # Nothing claimed, nothing verified: an empty ledger is not the gate's
        # business (it may be a brand-new task, or a worktree that just started).
        return None
    if facts["verified"] and not facts["verified_with_evidence"]:
        problem = (
            f"el ledger tiene {len(facts['verified'])} checkpoint(s) ✓ pero ninguno trae "
            f"la evidencia (`— {EVIDENCE_MARKER} …`)"
        )
    else:
        problem = f"el ledger tiene {pending} claim(s) y ningún checkpoint ✓"
    return (
        f"Riel: este turno editó código dentro de `{worktree}` y {problem}.\n"
        "Antes de cerrar: corre el gate real y regístralo con "
        "`riel_note({check: \"<qué verificaste>\", by: \"<comando y su salida>\", "
        "covering: \"<alcance>\"})`; si el trabajo no requería verificación, "
        "dilo en el ledger o cierra la pregunta abierta, y vuelve a cerrar el turno."
    )


def _session_cwd(session_id) -> str | None:
    """The session's recorded cwd (the terminal tool's record), if Hermes is around."""
    try:
        from tools.terminal_tool import get_session_cwd

        recorded = get_session_cwd(session_id)
        return str(recorded) if recorded else None
    except Exception:
        return None


def pre_verify(session_id: str = "", coding: bool = False, attempt: int = 0,
               changed_paths=None, **kwargs) -> dict | None:
    """Hook callback: continue the turn while the ledger has no verified checkpoint.

    Signature note: Hermes inspects hook signatures and passes every keyword it
    declares, so this stays `**kwargs`-tolerant (a new payload field must never
    break registration). `coding` is accepted but not required — the ledger
    check is the real scope.
    """
    if not SETTINGS.get("enabled", True):
        return None
    try:
        if attempt >= int(SETTINGS.get("attempts", 1)):
            return None
    except (TypeError, ValueError):
        return None
    try:
        worktree = find_worktree(changed_paths, session_cwd=_session_cwd(session_id))
        if not worktree:
            return None
        message = nudge_message(worktree, assess(worktree))
        return {"action": "continue", "message": message} if message else None
    except Exception:
        # A gate that jams is worse than no gate.
        return None
