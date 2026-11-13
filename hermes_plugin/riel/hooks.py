"""`pre_verify` — the Riel gate on the ACTIVE run, enforced by the runtime.

Riel's rule (v2): while a run is ACTIVE in the worktree, the turn does not
close with pending claims or gates. The run state (`.riel/run.md`) carries the
claims and the gates; the engine's `run status` knows which ones are done.
This hook asks the engine — IN-PROCESS, through the same safe path the tools
use (explicit worktree, explicit sinks; never a subprocess fallback) — and if
the run is active with work pending, answers `{"action": "continue", …}` so
the agent keeps going instead of closing the turn.

Bounds that keep it honest:

  * **Opt-in per worktree.** No active `.riel/run.md` anywhere above the
    edited files → never nudge. A worktree with only a legacy `.riel/ledger.md`
    is NOT gated: the v2 gate reads the run state, nothing else.
  * **Only an ACTIVE run.** A run that exists but is not activated (draft,
    written by hand, awaiting validate) is the agent's business, not the gate's.
  * **Self-throttled.** At most `gate_attempts` nudges per turn (default 1),
    on top of Hermes' own cap (`agent.max_verify_nudges`, 3 by default).
  * **Never blocks.** Every failure path — no run, missing bundled engine,
    unparseable status JSON — returns `None` and lets the turn finish. A gate
    that jams is worse than no gate.

Stdlib only and importable without Hermes: the only Hermes touch is the lazy
session-cwd lookup, and it is optional (the edited paths are the primary hint).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:  # a package import when the host loaded us as one …
    from . import _load, tools
except ImportError:  # … and a by-path load when it did not (repo suite, dashboard)
    import importlib.util as _ilu
    import pathlib as _pl

    _spec = _ilu.spec_from_file_location(
        "riel_plugin_load", _pl.Path(__file__).resolve().with_name("_load.py"))
    _load = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_load)
    tools = _load.sibling("riel_plugin_tools", "tools.py")

RUN_PARTS = (".riel", "run.md")
MAX_ANCESTOR_DEPTH = 12

# Install defaults, filled by register(); the live value is read per call so a
# chip toggle lands on the next turn's gate without a restart.
SETTINGS = {"enabled": True, "attempts": 1}


def gate_enabled() -> bool:
    """The `gate` group right now; an unreadable config falls back to ON."""
    try:
        return _load.settings().read_bool("gate", SETTINGS.get("enabled", True))
    except Exception:
        return bool(SETTINGS.get("enabled", True))


def gate_attempts() -> int:
    """How many nudges this turn may get.

    The manifest types this as `int`, so an int or a digit string is honoured and
    anything else falls back to 1 — a hand-edited `"many"` must not become an
    unbounded gate.
    """
    try:
        value = _load.settings().read("gate_attempts", SETTINGS.get("attempts", 1))
    except Exception:
        value = SETTINGS.get("attempts", 1)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 1


def _has_run(directory: Path) -> bool:
    try:
        return directory.joinpath(*RUN_PARTS).is_file()
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

    The **edited files win** over the session cwd: the gate asks "did you
    finish the run you just touched", and a turn can edit a worktree other
    than the one the session sits in (absolute paths, several repos). The
    session cwd is the fallback for the case where no edited path resolves to
    a tracked worktree.

    Both are guesses that only count when an ACTIVE RUN is actually there —
    "no run.md" means "not a Riel v2 task", never "use the gateway's cwd",
    and a legacy ledger-only worktree is left alone. Blanks and relative
    paths are skipped for the same reason: `Path("")` is `.`, which would
    silently answer about whatever directory the process runs in.
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
        if candidate is not None and _has_run(candidate):
            return str(candidate)
    return None


def _pending_items(items) -> int:
    """How many of *items* (a claims/gates list) are not done yet.

    Defensive fold for list-shaped state (each item a dict with `done`/`exit_code`
    or a string opening with the checkpoint mark) — never raises on a shape it
    does not recognize.
    """
    pending = 0
    for item in items or []:
        if isinstance(item, dict):
            if item.get("done") is not True and item.get("exit_code") != 0:
                pending += 1
        elif isinstance(item, str):
            if not item.lstrip().startswith("✓"):
                pending += 1
    return pending


def _pending(state, key: str, done_value: str) -> int:
    """Pending count for one register, in EITHER status shape.

    The engine's `run status` answers DICTS of id → word (`{"P1": "open"}`,
    `{"G1": "pending"}`); a list shape is tolerated for robustness.
    """
    items = state.get(key) or {}
    if isinstance(items, dict):
        return sum(1 for value in items.values() if value != done_value)
    return _pending_items(items)


def _is_active(state: dict) -> bool:
    """The run is active: the engine says so (`status: "active"`) — or the
    boolean `active` some shapes carry. A draft is never active."""
    if state.get("status") == "active":
        return True
    return state.get("active") is True


def assess(worktree) -> dict:
    """Run-state facts the gate decides on. Never raises; no subprocess.

    The engine is reached the same safe way the tools reach it — in-process,
    explicit worktree, explicit sinks — so a gate turn never shells out.
    """
    facts = {"present": False, "active": False, "claims": 0, "gates": 0,
             "pending_claims": 0, "pending_gates": 0, "error": None}
    root = _normalize(worktree)
    if root is None or not root.is_dir() or not _has_run(root):
        return facts
    facts["present"] = True
    try:
        payload = json.loads(tools.riel_run({"verb": "status", "worktree": str(root)}))
    except Exception as exc:
        facts["error"] = f"the gate could not read the run state: {exc}"
        return facts
    if payload.get("error"):
        facts["error"] = payload["error"]
        return facts
    if payload.get("exit_code") != 0:
        facts["error"] = (payload.get("stderr") or "").strip() or "the engine's status call failed"
        return facts
    try:
        state = json.loads(payload.get("stdout") or "{}")
    except ValueError:
        facts["error"] = "the engine's status call did not return JSON"
        return facts
    if not isinstance(state, dict):
        facts["error"] = "the engine's status call did not return an object"
        return facts
    facts["active"] = _is_active(state)
    facts["claims"] = len(state.get("claims") or {})
    facts["gates"] = len(state.get("gates") or {})
    facts["pending_claims"] = _pending(state, "claims", "covered")
    facts["pending_gates"] = _pending(state, "gates", "passed")
    return facts


def nudge_message(worktree: str, facts: dict) -> str | None:
    """The continuation message, or None when the run holds the line."""
    if not facts.get("present") or facts.get("error"):
        return None
    if not facts.get("active"):
        return None  # a draft run is not the gate's business
    pending_claims, pending_gates = facts.get("pending_claims", 0), facts.get("pending_gates", 0)
    if not pending_claims and not pending_gates:
        return None
    parts = []
    if pending_gates:
        parts.append(f"{pending_gates} gate(s) sin evidencia")
    if pending_claims:
        parts.append(f"{pending_claims} claim(s) pendiente(s)")
    return (
        f"Riel: este turno editó código dentro de `{worktree}` y el run activo tiene "
        f"{', '.join(parts)}.\n"
        "Antes de cerrar: ejecuta los gates reales con "
        "`riel_note(gates: [\"G#\"], command: \"<el comando real>\", covering: "
        "\"<alcance>\", claims: [\"P#\"])` — el motor corre el comando y registra la "
        "evidencia E# — o actualiza el estado del run si ya no aplica, y vuelve a "
        "cerrar el turno."
    )


def _session_cwd(session_id) -> str | None:
    """The session's recorded cwd — one resolver for the whole package (`_load`)."""
    return _load.session_cwd(session_id)


def pre_verify(session_id: str = "", coding: bool = False, attempt: int = 0,
               changed_paths=None, **kwargs) -> dict | None:
    """Hook callback: continue the turn while the active run has work pending.

    Signature note: Hermes inspects hook signatures and passes every keyword it
    declares, so this stays `**kwargs`-tolerant (a new payload field must never
    break registration). `coding` is accepted but not required — the run check
    is the real scope.
    """
    if not gate_enabled():
        return None
    try:
        if not _load.settings().read_bool("tools", True):
            return None
    except Exception:
        pass  # retain the fail-open gate when the settings store is broken
    if attempt >= gate_attempts():
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
