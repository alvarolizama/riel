"""The `riel` prompt section — what the agent knows about Riel before it asks.

One block, rendered once per session and frozen into the prompt by Hermes
(`ctx.register_system_prompt_section`, position `after_memory`). Three fixed
parts go first — what Riel is, the door to `rielctl`, and the operator's own
line — then one index line per bundled skill by budget, then the worktree's
ledger state only when it fits whole.

The rules that keep it honest:

  * **No network.** The only subprocess is `rielctl status`, capped at
    {@link STATE_TIMEOUT_SECS}s; its failure is SILENCE — never an error in the
    prompt.
  * **The file is the truth.** Skill names and triggers come from each bundled
    `SKILL.md`'s frontmatter at render time, so the index cannot drift from
    the prose; the load name is the short form (`riel-ledger` → `riel:ledger`).
  * **Never over budget.** A line that does not fit is declared, the state line
    is dropped entire, and a block with no index line returns `""` — Hermes
    discards an empty section, and empty beats a lie.
  * **Adaptation is the operator's slot.** The model-specific half is
    `harness_note`, read per render; there is no per-model table here.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

from . import settings

SECTION_ID = "riel"
SECTION_MAX_CHARS = 3_000
DESC_MAX_CHARS = 100
STATE_FIELD_CHARS = 90
STATE_TIMEOUT_SECS = 3

PLUGIN_DIR = Path(__file__).resolve().parent
SKILLS_DIR = PLUGIN_DIR / "skills"
RIELCTL = SKILLS_DIR / "riel-cli" / "scripts" / "rielctl"

# The product's own order: the router first, then state, structure, delegation, tooling.
SKILLS: Tuple[Tuple[str, str], ...] = (
    ("riel-protocol", "protocol"),
    ("riel-ledger", "ledger"),
    ("riel-contract", "contract"),
    ("riel-briefs", "briefs"),
    ("riel-delegate", "delegate"),
    ("riel-cli", "cli"),
)

HEAD = (
    "Riel — steering for long tasks: externalized state (the ledger) and a "
    "machine-checkable plan (the contract). The prose ships with this plugin "
    'and loads by tool: skill_view("riel:<name>").'
)


def _cap(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _frontmatter_description(path: Path) -> str:
    """The `description:` of a SKILL.md, or `""` — no YAML dependency."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            if inside:
                break
            inside = True
            continue
        if inside and stripped.startswith("description:"):
            value = stripped.split(":", 1)[1].strip()
            return value.strip('"').strip("'")
    return ""


def skill_entries() -> List[Tuple[str, Any, str]]:
    """`[(short name, SKILL.md, description)]` for every bundled skill that declares one.

    The one reader both consumers share: `register_skill` takes the full
    description, the index line caps it.
    """
    entries: List[Tuple[str, Any, str]] = []
    for slug, short in SKILLS:
        path = SKILLS_DIR / slug / "SKILL.md"
        description = _frontmatter_description(path)
        if description:
            entries.append((short, path, description))
    return entries


def index_rows() -> List[Tuple[str, str]]:
    """`[(short name, trigger)]` — the index lines, descriptions capped."""
    return [(short, _cap(description, DESC_MAX_CHARS)) for short, _path, description in skill_entries()]


def _door_line() -> str:
    return (
        "Door: everything Riel does is a tool — riel_note, riel_seam, riel_resume, riel_todo, "
        "riel_context, riel_state, riel_brief, riel_shaping, riel_clean, riel_fetch, riel_check "
        '(deferred: reach them with tool_search "riel"). No command line, no PATH.'
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
    """One line about the worktree's ledger, or `""` (no ledger, no rielctl, slow)."""
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
    """The block, or `""` when the group is off or nothing can be said."""
    if not settings.read_bool("context", default=True):
        return ""
    rows = index_rows()
    if not rows:
        return ""

    info = session_info if isinstance(session_info, dict) else {}
    door = _door_line()
    note = settings.read_note()
    fixed = [HEAD, door] + ([note] if note else [])
    used = sum(len(line) + 1 for line in fixed)

    # The declaration of what the budget dropped is part of the promise, so its
    # room is reserved BEFORE filling lines: a truncated index that says so is
    # honest, one that just stops is a silent lie.
    declaration = f"- … {len(rows)} more: run skills_list for this plugin's rows."
    reserve = len(declaration) + 1
    lines: List[str] = [HEAD]
    shown = 0
    for short, description in rows:
        line = f"- riel:{short} — {description}"
        if used + len(line) + 1 + reserve > SECTION_MAX_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1
    if shown == 0:
        return ""  # no room for a single skill line: empty is better than a lie

    remaining = len(rows) - shown
    if remaining > 0:
        declared = f"- … {remaining} more: run skills_list for this plugin's rows."
        lines.append(declared)
        used += len(declared) + 1

    state = state_line(info.get("cwd") or os.environ.get("TERMINAL_CWD") or "")
    if state and used + len(state) + 1 <= SECTION_MAX_CHARS:
        lines += ["", state]
        used += len(state) + 2

    lines += ["", door]
    if note:
        lines.append(note)
    block = "\n".join(lines)
    return block if len(block) <= SECTION_MAX_CHARS else ""
