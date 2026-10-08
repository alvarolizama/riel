"""`/riel` — the switch surface from any surface, not just the desktop chip.

The chip and this command are two doors to the same three switches
(`gate`, `tools`, `context`) and the operator's `harness_note`; the command
exists because the chip does not: a CLI session, a Telegram chat or a bot has
a slash command and no status bar.

The wording is part of the design. A switch written now is a switch the NEXT
session obeys — the prompt and the tool list are frozen when a session starts —
so every reply says what happened and when it lands, and never implies the
running turn changed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import List

_PLUGIN_DIR = Path(__file__).resolve().parent
_SETTINGS_MODULE = None

USAGE = (
    "/riel — Riel's switches. Usage: /riel status | /riel on <group> | /riel off <group> "
    "| /riel note <text to append to the prompt section> | /riel note - (clear it). "
    "Groups: gate, tools, context."
)
NEXT_SESSION = "Applies to the NEXT session (this one keeps the prompt and tools it started with)."


def plugin_settings():
    """`settings.py` beside this file, loaded by path (the package's own pattern)."""
    global _SETTINGS_MODULE
    if _SETTINGS_MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "riel_plugin_settings_commands", _PLUGIN_DIR / "settings.py"
        )
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise RuntimeError("settings.py is missing from the package")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SETTINGS_MODULE = module
    return _SETTINGS_MODULE


def _render(snapshot: dict) -> str:
    lines: List[str] = []
    for key in ("gate", "tools", "context"):
        mark = "on " if snapshot.get(key, True) else "off"
        lines.append(f"  {key:8s} {mark}")
    note = str(snapshot.get("harness_note") or "")
    lines.append(f"  note     {'—' if not note else note}")
    return "\n".join(lines)


def handle(raw_args: str = "", **kwargs) -> str:
    """`/riel …` → a short report. Never raises; a bad write is reported, not hidden."""
    settings = plugin_settings()
    parts = str(raw_args or "").split()
    action = parts[0].lower() if parts else "status"
    rest = parts[1:]

    if action in ("status", "state", ""):
        return "Riel settings\n" + _render(settings.state())

    if action in ("on", "off", "toggle"):
        if not rest:
            return USAGE
        group = rest[0].lower()
        if group not in settings.GROUP_KEYS:
            return f"Unknown group '{group}'. Groups: {', '.join(settings.GROUP_KEYS)}."
        current = settings.read_bool(group)
        wanted = {"on": True, "off": False, "toggle": not current}[action]
        try:
            landed = settings.write(group, wanted)
        except Exception as exc:  # PermissionError in a managed install, etc.
            return f"Could not write '{group}': {exc}"
        return f"{group}: {'on' if landed else 'off'}\n{NEXT_SESSION}"

    if action == "note":
        text = " ".join(rest).strip()
        try:
            landed = settings.write(settings.NOTE_KEY, "" if text in ("-", "clear", "none") else text)
        except Exception as exc:
            return f"Could not write the note: {exc}"
        return (
            f"note: {'(cleared)' if not landed else landed}\n{NEXT_SESSION}"
        )

    return USAGE


COMMANDS = {"riel": handle}
