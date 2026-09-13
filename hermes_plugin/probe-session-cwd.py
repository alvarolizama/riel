#!/usr/bin/env python3
"""Probe the plugin the way a LIVE Hermes session would.

Not part of `make test`: it needs Hermes itself on `sys.path` (module names
like `hermes_cli.plugins` and `tools.registry` only resolve inside a Hermes
install), so it lives outside the stdlib-only regression suite.

What it proves, against a real Hermes install:
  1. Hermes' own discovery + registration finds the plugin and its tools;
  2. dispatching a tool through the real registry resolves the worktree from
     the **session cwd record**, not from this process's cwd;
  3. two sessions in different worktrees never touch each other's ledger;
  4. bad input returns error JSON instead of raising;
  5. the `pre_verify` gate fires through Hermes' own hook dispatch
     (`get_pre_verify_continue_message`) and closes once a ✓ with evidence is
     in the ledger.

Usage (run from a directory that is NOT either worktree):

    HERMES_PY=/path/to/hermes/venv/bin/python   # `head -1 $(command -v hermes)` chain
    "$HERMES_PY" hermes_plugin/probe-session-cwd.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "hermes_plugin" / "riel"
RIELCTL = PLUGIN / "vendor" / "riel-cli" / "scripts" / "rielctl"


def _dispatch(registry, tool: str, args: dict, task: str) -> dict:
    """Dispatch through the real registry; the handler always returns JSON text."""
    raw = registry.dispatch(tool, args, task_id=task)
    return json.loads(raw if isinstance(raw, str) else json.dumps(raw))


def _seed(worktree: str, *argv) -> None:
    """Write ledger entries with the vendored rielctl."""
    subprocess.run(
        [sys.executable, str(RIELCTL), *argv],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=True,
    )


def main() -> int:
    home = tempfile.mkdtemp(prefix="hermes-probe-home-")
    work_a = tempfile.mkdtemp(prefix="riel-session-a-")
    gate_tree = tempfile.mkdtemp(prefix="riel-gate-")
    work_b = tempfile.mkdtemp(prefix="riel-session-b-")
    cwd_before = os.getcwd()
    # The probe may be run from a directory that legitimately has its own ledger
    # (e.g. this repo). What must not happen is the ledger *changing* there.
    cwd_ledger = Path(cwd_before) / ".riel" / "ledger.md"
    ledger_before = cwd_ledger.read_text() if cwd_ledger.exists() else None
    try:
        os.environ["HERMES_HOME"] = home
        plugins_root = Path(home) / "plugins"
        plugins_root.mkdir(parents=True)
        os.symlink(PLUGIN, plugins_root / "riel")

        from hermes_cli.plugins import get_plugin_manager
        from tools.registry import registry
        from tools.terminal_tool import get_session_cwd, record_session_cwd

        # THE manager the runtime uses (module-level lookups like has_hook go
        # through it) — a private PluginManager() would register into an object
        # nothing else consults.
        manager = get_plugin_manager()
        manifests = manager._scan_directory(plugins_root, source="user")
        if len(manifests) != 1:
            print(f"FAIL: expected 1 manifest, found {len(manifests)}", file=sys.stderr)
            return 1
        manifest = manifests[0]
        manager._load_plugin(manifest)
        loaded = manager._plugins.get(manifest.key or manifest.name)
        if loaded is None or loaded.error:
            print(f"FAIL: registration error: {getattr(loaded, 'error', 'no record')}", file=sys.stderr)
            return 1
        print(f"discovery : {manifest.name} {manifest.version} ({manifest.source})")
        print(f"registered: {sorted(loaded.tools_registered)} + hooks {sorted(loaded.hooks_registered)}")

        record_session_cwd("probe-a", work_a)
        record_session_cwd("probe-b", work_b)
        print(f"process cwd: {cwd_before}")
        print(f"session A  : {get_session_cwd('probe-a')}")
        print(f"session B  : {get_session_cwd('probe-b')}")

        out_a = _dispatch(registry, "riel_note", {"goal": "goal of session A"}, "probe-a")
        out_b = _dispatch(registry, "riel_note", {"goal": "goal of session B"}, "probe-b")
        for label, out, expected in (("A", out_a, work_a), ("B", out_b, work_b)):
            print(f"{label} -> worktree={out.get('worktree')} exit_code={out.get('exit_code')}")
            assert out.get("worktree") == expected, (out.get("worktree"), expected)
            assert out.get("exit_code") == 0, out

        for tool, task in (("riel_todo", "probe-a"), ("riel_seam", "probe-b"), ("riel_resume", "probe-a")):
            payload = _dispatch(registry, tool, {}, task)
            print(f"{tool:12s} -> exit_code={payload['exit_code']} {payload['stdout'].splitlines()[0][:48]}")
            assert payload["exit_code"] == 0, payload

        ledger_a = (Path(work_a) / ".riel" / "ledger.md").read_text()
        ledger_b = (Path(work_b) / ".riel" / "ledger.md").read_text()
        assert "goal of session A" in ledger_a and "goal of session B" not in ledger_a
        assert "goal of session B" in ledger_b and "goal of session A" not in ledger_b
        ledger_after = cwd_ledger.read_text() if cwd_ledger.exists() else None
        assert ledger_after == ledger_before, "the ledger leaked into the process cwd"

        bad = _dispatch(registry, "riel_seam", {"worktree": "/nope/nope"}, "probe-a")
        assert "error" in bad, bad
        print(f"bad input  -> error JSON: {bad['error']}")

        # --- the pre_verify gate, through Hermes' own hook dispatch ---------
        from hermes_cli.plugins import get_pre_verify_continue_message

        _seed(gate_tree, "note", "--goal", "gate probe",
              "--claim", "P1: la cosa", "--verify-with", "make test")
        payload = {
            "session_id": "probe-a",
            "platform": "desktop",
            "model": "m",
            "coding": True,
            "changed_paths": [str(Path(gate_tree) / "lib" / "a.ex")],
        }
        nudge = get_pre_verify_continue_message(attempt=0, **payload)
        print(f"gate       -> {nudge.splitlines()[0][:88] if nudge else 'NO NUDGE'}")
        assert nudge and os.path.realpath(gate_tree) in nudge, nudge

        throttled = get_pre_verify_continue_message(attempt=1, **payload)
        assert throttled is None, throttled
        print("gate       -> no insiste dos veces (gate_attempts=1 por defecto)")

        untracked = tempfile.mkdtemp(prefix="riel-untracked-")
        try:
            assert get_pre_verify_continue_message(
                attempt=0, **{**payload, "changed_paths": [str(Path(untracked) / "a.py")]}
            ) is None
        finally:
            shutil.rmtree(untracked, ignore_errors=True)
        print("gate       -> no toca worktrees sin .riel/ledger.md")

        _seed(gate_tree, "note", "--check", "el gate corrió", "--by", "probe-session-cwd.py")
        assert get_pre_verify_continue_message(attempt=0, **payload) is None
        print("gate       -> cierra el turno cuando hay un ✓ con evidencia")

        print("\nOK: discovery, registry dispatch, session cwd resolution, per-session")
        print("    isolation and the pre_verify gate verified")
        return 0
    finally:
        os.chdir(cwd_before)
        for path in (home, work_a, work_b, gate_tree):
            shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
