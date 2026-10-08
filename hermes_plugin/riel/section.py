"""The `riel` prompt section — what the agent knows about Riel before it asks.

One block, rendered once per session and frozen into the prompt by Hermes
(`ctx.register_system_prompt_section`, position `after_memory`). It answers the
one question no tool can: **that the prose exists at all**. The tools live in
the model's catalog; the guide's topics do not, so this block names the door
(`riel_guide`) and the worktree's ledger state.

The rules that keep it honest:

  * **No network.** The only subprocess is the engine's `status`, capped at
    {@link STATE_TIMEOUT_SECS}s; its failure is SILENCE — never an error in the
    prompt.
  * **The files are the truth.** The topic list comes from `guide/*.md` at
    render time, so the block cannot drift from the prose.
  * **Never over budget.** The note is dropped before the door, the state line
    only when it fits whole, and nothing is ever cut mid-sentence into a lie.
  * **Adaptation is the operator's slot.** The model-specific half is
    `harness_note`, read per render; there is no per-model table here.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, List, Optional

from . import guide, settings

SECTION_ID = "riel"
SECTION_MAX_CHARS = 3_000
STATE_FIELD_CHARS = 90
STATE_TIMEOUT_SECS = 3

PLUGIN_DIR = Path(__file__).resolve().parent
ENGINE = PLUGIN_DIR / "engine" / "run.py"

HEAD = (
    "Riel — steering for long tasks: externalized state (the ledger) and a "
    "machine-checkable plan (the contract). The prose ships with this plugin "
    "and is read through the riel_guide tool."
)


def _cap(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def index_line() -> str:
    """One line: the door to the prose plus the topics that exist right now."""
    topics = guide.topics()
    if not topics:
        return "Prose: riel_guide() — the package ships no guide/ prose yet."
    return (
        "Prose: riel_guide() lists the topics ("
        + ", ".join(topics)
        + '); riel_guide(topic="contract") reads one, and a section= argument '
        "gives just that slice of it."
    )


def _door_line() -> str:
    return (
        "Door: everything Riel does is a tool — riel_guide, riel_note, riel_seam, riel_resume, "
        "riel_todo, riel_state, riel_context, riel_brief, riel_shaping, riel_clean, riel_fetch, "
        'riel_check (deferred: reach them with tool_search "riel"). No command line, no PATH.'
    )


def _read_status(worktree: str) -> Optional[dict]:
    """`ledger_status.read_status` loaded by path; `None` when unavailable."""
    path = PLUGIN_DIR / "dashboard" / "ledger_status.py"
    try:
        spec = importlib.util.spec_from_file_location("riel_section_ledger_status", path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.read_status(worktree, timeout=STATE_TIMEOUT_SECS)
    except Exception:
        return None


def state_line(worktree: str) -> str:
    """One line about the worktree's ledger, or `""` (no ledger, no engine, slow)."""
    worktree = str(worktree or "").strip()
    if not worktree:
        return ""
    status = _read_status(worktree)
    if not isinstance(status, dict) or not status.get("present") or status.get("error"):
        return ""
    parts: List[str] = []
    goal = _cap(status.get("goal"), STATE_FIELD_CHARS)
    if goal:
        parts.append(f"Goal: {goal}")
    if status.get("phase"):
        parts.append(f"Phase {_cap(status['phase'], 24)}")
    nxt = _cap(status.get("next"), STATE_FIELD_CHARS)
    if nxt:
        parts.append(f"Next: {nxt}")
    parts.append(
        f"{status.get('claims', 0)} claims · {status.get('verified', 0)} verified · {status.get('open', 0)} open"
    )
    return (
        "Worktree state — "
        + " · ".join(parts)
        + "  →  re-read with riel_seam, write with riel_note."
    )


def render(session_info: Any = None) -> str:
    """The block, or `""` when the `context` group is off or nothing can be said."""
    if not settings.read_bool("context", default=True):
        return ""

    info = session_info if isinstance(session_info, dict) else {}
    core = [HEAD, index_line(), "", _door_line()]
    used = sum(len(line) + 1 for line in core)
    if used > SECTION_MAX_CHARS:
        return ""  # not even the door fits: empty beats a lie

    lines = list(core)
    # The state is the volatile half: it only joins when it fits WHOLE.
    state = state_line(info.get("cwd") or os.environ.get("TERMINAL_CWD") or "")
    if state and used + len(state) + 2 <= SECTION_MAX_CHARS:
        lines = [HEAD, index_line(), "", state, "", _door_line()]
        used += len(state) + 2

    # The operator's line is appended last, and yields first.
    note = settings.read_note()
    if note and used + len(note) + 1 <= SECTION_MAX_CHARS:
        lines.append(note)
        used += len(note) + 1

    block = "\n".join(lines)
    return block if len(block) <= SECTION_MAX_CHARS else ""
