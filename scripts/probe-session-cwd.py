#!/usr/bin/env python3
"""Exercise Riel's live Hermes discovery, registry and pre_verify dispatch.

Use the interpreter Hermes itself uses. HERMES_AGENT_ROOT can point at a managed
agent tree when the ordinary import is unavailable. Temporary plugin/session
homes and run fixtures are created and removed by this process.
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
ENGINE = PLUGIN / "engine" / "run.py"


def import_hermes():
    try:
        import hermes_cli.plugins  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    root = Path(os.environ.get("HERMES_AGENT_ROOT") or
                Path.home() / ".hermes" / "hermes-agent")
    sys.path.insert(0, str(root))
    try:
        import hermes_bootstrap  # noqa: F401
        import hermes_cli.plugins  # noqa: F401
    except Exception as exc:
        raise SystemExit(f"Hermes is not importable: {exc!r}")


import_hermes()
from hermes_cli.plugins import get_plugin_manager, get_pre_verify_continue_message  # noqa: E402
from tools.registry import registry  # noqa: E402
from tools.terminal_tool import record_session_cwd  # noqa: E402


def dispatch(tool, args, task_id):
    raw = registry.dispatch(tool, args, task_id=task_id)
    return json.loads(raw if isinstance(raw, str) else json.dumps(raw))


def draft(objective):
    proc = subprocess.run(
        [sys.executable, str(ENGINE), "run", "new"],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout.replace("{{title}}", "live probe").replace(
        "{{objective}}", objective).replace("{{claim}}", "a real command ran").replace(
        "{{anchor}}", "§Graph")


def main():
    temp = Path(tempfile.mkdtemp(prefix="riel-live-probe-"))
    home = temp / "home"
    sessions = [temp / "a", temp / "b"]
    for worktree in sessions:
        (worktree / ".riel").mkdir(parents=True)
        (worktree / ".riel" / "run.md").write_text(
            draft(f"The run for {worktree.name} stays isolated."), encoding="utf-8")
    try:
        os.environ["HERMES_HOME"] = str(home)
        plugin_root = home / "plugins"
        plugin_root.mkdir(parents=True)
        os.symlink(PLUGIN, plugin_root / "riel")
        manager = get_plugin_manager()
        manifests = manager._scan_directory(plugin_root, source="user")
        assert len(manifests) == 1
        manager._load_plugin(manifests[0])
        loaded = manager._plugins.get(manifests[0].key or manifests[0].name)
        assert loaded is not None and not loaded.error, getattr(loaded, "error", "missing")
        assert loaded.tools_registered == [
            "riel_guide", "riel_project", "riel_shape", "riel_run", "riel_note",
            "riel_clean", "riel_check"]
        print(f"registered: {loaded.tools_registered}")

        for task, worktree in zip(("probe-a", "probe-b"), sessions):
            record_session_cwd(task, str(worktree))
            activated = dispatch("riel_run", {"verb": "activate"}, task)
            assert activated["passed"], activated
            assert activated["worktree"] == str(worktree)
            noted = dispatch("riel_note", {"core": f"session {worktree.name} — only here"}, task)
            assert noted["passed"], noted
            status = dispatch("riel_run", {"verb": "status"}, task)
            assert status["passed"], status
            assert json.loads(status["stdout"])["status"] == "active"
        bodies = [(root / ".riel" / "run.md").read_text() for root in sessions]
        assert "session a — only here" in bodies[0]
        assert "session b — only here" not in bodies[0]
        assert "session b — only here" in bodies[1]
        print("session cwd: isolated registry dispatch passed")

        gate_probe = sessions[0]
        payload = {"session_id": "probe-a", "coding": True,
                   "changed_paths": [str(gate_probe / "sample.py")]}
        assert get_pre_verify_continue_message(attempt=0, **payload)
        result = dispatch("riel_note", {
            "gates": ["G1"], "claims": ["P1"], "command": "true",
            "covering": "a real registry-invoked gate", "worktree": str(gate_probe),
        }, "probe-a")
        assert result["passed"], result
        assert get_pre_verify_continue_message(attempt=0, **payload) is None
        rejected = dispatch("riel_run", {"verb": "fictional",
                                        "worktree": str(gate_probe)}, "probe-a")
        assert rejected["exit_code"] == 1
        print("pre_verify: pending nudge, executed gate and completion passed")
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
