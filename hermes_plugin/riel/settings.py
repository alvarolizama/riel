"""Per-call reads and writes of this plugin's own settings — the live half of the group switches.

`plugins.entries.riel.settings.<key>` is the single home of the three group
switches (`gate`, `tools`, `context`) and of the operator's `harness_note`.
Both halves of the plugin read it, and both must read it **per call**: the
gate runs on every turn's hot path, the prompt section renders once per
session, and the desktop chip can flip a value while the process is alive.

Rules that make a switch honest:

  * **Fail-open.** A missing key, an unreadable config or a non-boolean value
    all mean ON. This is operator comfort, never a security boundary.
  * **Read per call, resolve the home per call.** One process serves several
    profiles (gateway multiplex) and the plugin loads once: a home captured at
    registration would answer for the wrong profile.
  * **Write only through Hermes.** The writer is
    `hermes_cli.plugins_state.save_plugin_setting` — the same door the desktop
    settings action uses, with the cross-process lock and the managed-install
    refusals. This module never edits `config.yaml` itself.

Stdlib only, no Hermes import at module level: the repo suite runs without
Hermes and injects a fake `hermes_cli.config` / `hermes_cli.plugins_state`.
"""

from __future__ import annotations

from typing import Any, Dict

PLUGIN_ID = "riel"
GROUP_KEYS = ("gate", "tools", "context")
NOTE_KEY = "harness_note"
# The section caps the note; keep the write-side cap identical so a value the
# operator sets here is the value the prompt renders.
NOTE_MAX_CHARS = 400


def _settings_readonly() -> Dict[str, Any]:
    """`plugins.entries.riel.settings` from the ACTIVE profile, `{}` on any failure."""
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
    except Exception:
        return {}
    try:
        entries = (config.get("plugins") or {}).get("entries") or {}
        settings = (entries.get(PLUGIN_ID) or {}).get("settings") or {}
    except AttributeError:
        return {}
    return settings if isinstance(settings, dict) else {}


def read(key: str, default: Any = True) -> Any:
    """One setting. Absent, illegible or mis-typed ⇒ *default* (fail-open)."""
    return _settings_readonly().get(key, default)


def read_bool(key: str, default: bool = True) -> bool:
    """One group switch as a boolean — non-boolean values fall back to ON."""
    value = _settings_readonly().get(key, default)
    return value if isinstance(value, bool) else default


def read_groups() -> Dict[str, bool]:
    """Every group switch at once, the shape the chip and `/riel status` print."""
    return {key: read_bool(key) for key in GROUP_KEYS}


def read_note() -> str:
    """The operator's adaptation line, capped; absent or non-string ⇒ `""`."""
    value = _settings_readonly().get(NOTE_KEY, "")
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:NOTE_MAX_CHARS]


def write(key: str, value: Any) -> Any:
    """Write one setting through Hermes' writer; returns the value as it landed.

    Raises whatever the writer raises (`PermissionError` in a managed install)
    so the caller can report it instead of pretending the switch moved.
    """
    from hermes_cli.plugins_state import save_plugin_setting

    save_plugin_setting(PLUGIN_ID, (key,), value)
    return _settings_readonly().get(key, value)


def state() -> Dict[str, Any]:
    """The whole switch surface: `{group: bool, ...}` plus the operator's note."""
    snapshot: Dict[str, Any] = read_groups()
    snapshot[NOTE_KEY] = read_note()
    return snapshot


class Rejected(ValueError):
    """A value the settings surface refuses (unknown key, wrong type, too long)."""


def validate(values: Dict[str, Any]) -> Dict[str, Any]:
    """Check a `{key: value}` patch against the manifest's schema, or raise `Rejected`."""
    if not isinstance(values, dict) or not values:
        raise Rejected("expected a non-empty object of settings")
    checked: Dict[str, Any] = {}
    for key, value in values.items():
        if key in GROUP_KEYS:
            if not isinstance(value, bool):
                raise Rejected(f"{key} must be a boolean, got {type(value).__name__}")
        elif key == NOTE_KEY:
            if not isinstance(value, str):
                raise Rejected(f"{NOTE_KEY} must be a string, got {type(value).__name__}")
            if len(value) > NOTE_MAX_CHARS:
                raise Rejected(f"{NOTE_KEY} is capped at {NOTE_MAX_CHARS} chars, got {len(value)}")
        else:
            raise Rejected(f"unknown setting '{key}' — known: {', '.join((*GROUP_KEYS, NOTE_KEY))}")
        checked[key] = value
    return checked


def apply(values: Dict[str, Any]) -> Dict[str, Any]:
    """Validate then write a patch; returns the whole surface as it stands after."""
    for key, value in validate(values).items():
        write(key, value)
    return state()
