"""The `riel` prompt section — what the agent knows about Riel before it asks.

One block, rendered once per session and frozen into the prompt by Hermes
(`ctx.register_system_prompt_section`, position `after_memory`). It answers the
one question no tool can: **that the prose exists at all**. The tools live in
the model's catalog; the guide's topics do not, so this block names the door
(`riel_guide`) and the worktree's active run.

The rules that keep it honest:

  * **No network.** The only engine call is `run status`, reached the safe
    in-process way (`dashboard/ledger_status.read_run`), capped at
    {@link STATE_TIMEOUT_SECS}s of patience; its failure is SILENCE — never an
    error in the prompt.
  * **The files are the truth.** The topic list comes from `guide/*.md` at
    render time, so the block cannot drift from the prose.
  * **Never over budget.** The note is dropped before the door, the state line
    only when it fits whole, and nothing is ever cut mid-sentence into a lie.
  * **Adaptation is the operator's slot.** The model-specific half is
    `harness_note`, read per render; there is no per-model table here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, List, Optional
from collections.abc import Mapping

try:  # a package import when the host loaded us as one …
    from . import _load
except ImportError:  # … and a by-path load when it did not (repo suite, dashboard)
    import importlib.util as _ilu
    import pathlib as _pl

    _spec = _ilu.spec_from_file_location(
        "riel_plugin_load", _pl.Path(__file__).resolve().with_name("_load.py"))
    _load = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_load)

SECTION_ID = "riel"
SECTION_MAX_CHARS = 3_000
STATE_FIELD_CHARS = 90
STATE_TIMEOUT_SECS = 3

# Module-level handles, resolved through the one loader: the tests (and any
# caller that wants the prose's topic list without a worktree) read them here.
guide = _load.guide()
settings = _load.settings()

PLUGIN_DIR = Path(__file__).resolve().parent

HEAD = (
    "Riel — steering for long tasks: externalized state (.riel/runs/<slug>.md: the contract's definition, "
    "execution state, typed gate evidence) fed by the shaping. The prose ships "
    "with this plugin and is read through the riel_guide tool."
)


def _cap(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def index_line() -> str:
    """One line: the door to the prose plus the topics that exist right now."""
    topics = _load.guide().topics()
    if not topics:
        return "Prose: riel_guide() — the package ships no guide/ prose yet."
    return (
        "Prose: riel_guide() lists the topics ("
        + ", ".join(topics)
        + '); riel_guide(topic="run") lists that guide\'s sections by size, '
        "section= reads just one, full=true reads the whole body."
    )


def _door_line() -> str:
    return (
        "Door: everything Riel does is a tool — riel_guide, riel_project "
        "(new|validate|status), riel_shape "
        "(new|validate), riel_run (new|validate|activate|rebase|status|"
        "list|slice), riel_note, riel_clean, riel_check (deferred: "
        "reach them with tool_search \"riel\"). No command line, no PATH."
    )


_LEDGER_STATUS = None


def _ledger_status():
    """`dashboard/ledger_status.py` loaded by path, once per process."""
    global _LEDGER_STATUS
    if _LEDGER_STATUS is None:
        path = PLUGIN_DIR / "dashboard" / "ledger_status.py"
        spec = importlib.util.spec_from_file_location("riel_section_ledger_status", path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LEDGER_STATUS = module
    return _LEDGER_STATUS


def _read_runs(worktree: str) -> Optional[dict]:
    """`ledger_status.read_runs`; `None` when unavailable."""
    module = _ledger_status()
    if module is None:
        return None
    try:
        return module.read_runs(worktree)
    except Exception:
        return None


def state_line(worktree: str) -> str:
    """One line per ACTIVE contract, or `""` (no contracts, slow).

    Several tracks may be active at once: the model needs each one's cursor
    and what it still owes, with the slug that selects it.
    """
    worktree = str(worktree or "").strip()
    if not worktree:
        return ""
    report = _read_runs(worktree)
    if not isinstance(report, dict) or not report.get("present") or report.get("error"):
        return ""
    contracts = [c for c in (report.get("contracts") or []) if isinstance(c, dict)]
    lines: List[str] = []
    for contract in contracts:
        status = contract.get("status")
        if not isinstance(status, dict):
            continue
        err = status.get("error")
        if err:
            if "stale state" in str(err).lower():
                slug = contract.get("slug") or status.get("slug") or "?"
                lines.append(f"Worktree state — `{slug}` · STALE (run riel_run rebase)")
            continue
        if not contract.get("active"):
            continue
        parts: List[str] = ["`{}`".format(contract.get("slug") or "?")]
        goal = _cap(status.get("title") or status.get("goal"), STATE_FIELD_CHARS)
        if goal:
            parts.append(f"Goal: {goal}")
        nxt = _cap(status.get("next"), STATE_FIELD_CHARS)
        if nxt:
            parts.append(f"Next: {nxt}")
        evidence = status.get("evidence")
        total = evidence.get("total", 0) if isinstance(evidence, dict) else 0
        parts.append("{} claims ({} open) · {} gates ({} pending) · {} evidence".format(
            len(status.get("claims") or {}), contract.get("pending_claims", 0),
            len(status.get("gates") or {}), contract.get("pending_gates", 0),
            total))
        if contract.get("done"):
            parts.append("done")
        dirty = contract.get("dirty_since_evidence") or status.get("dirty_since_evidence")
        if dirty:
            parts.append("dirty since evidence")
        scope_violations = contract.get("scope_violations") or status.get("scope_violations") or []
        if scope_violations:
            parts.append(f"scope violations: {len(scope_violations)}")
        stuck_gates = contract.get("stuck_gates") or status.get("stuck_gates") or {}
        if isinstance(stuck_gates, dict) and stuck_gates:
            stuck_str = ", ".join(f"{gid}({cnt})" for gid, cnt in stuck_gates.items())
            parts.append(f"stuck: {stuck_str}")
        lines.append("Worktree state — " + " · ".join(parts))

        focus = contract.get("focus") if isinstance(contract.get("focus"), dict) else status.get("focus")
        if isinstance(focus, dict):
            do_not = focus.get("do_not") or []
            if do_not:
                lines.append("  DO NOT: " + _cap("; ".join(str(x) for x in do_not), STATE_FIELD_CHARS * 2))
            core_items = focus.get("core") or []
            if core_items:
                lines.append("  Core: " + _cap("; ".join(str(x) for x in core_items), STATE_FIELD_CHARS * 2))
    if not lines:
        return ""
    return "\n".join(lines) + (
        "\n  →  re-read with riel_run status, write with riel_note "
        "(pass run=<slug> when several contracts are active).")


def render(session_info: Any = None) -> str:
    """The block, or `""` when the `context` group is off or nothing can be said."""
    if not _load.settings().read_bool("context", default=True):
        return ""

    info = session_info if isinstance(session_info, Mapping) else {}
    core = [HEAD, index_line(), "", _door_line()]
    used = sum(len(line) + 1 for line in core)
    if used > SECTION_MAX_CHARS:
        return ""  # not even the door fits: empty beats a lie

    lines = list(core)
    # The state is the volatile half: it only joins when it fits WHOLE.
    state_worktree = _load.session_cwd(preferred=info.get("cwd"), recorded=False)
    if "cwd" in info:
        state_worktree = str(info.get("cwd") or "").strip()
    state = state_line(state_worktree or "")
    if state and used + len(state) + 2 <= SECTION_MAX_CHARS:
        lines = [HEAD, index_line(), "", state, "", _door_line()]
        used += len(state) + 2

    # The operator's line is appended last, and yields first.
    note = _load.settings().read_note()
    if note and used + len(note) + 1 <= SECTION_MAX_CHARS:
        lines.append(note)
        used += len(note) + 1

    block = "\n".join(lines)
    return block if len(block) <= SECTION_MAX_CHARS else ""
