"""The group switches — read per call, fail-open, and serious on the write path.

Stdlib-only and Hermes-free: `hermes_cli.config` (the reader) and
`hermes_cli.plugins_state` (the writer) are faked, so these tests drive the
real `settings.py`, the real handler guard, the real `/riel` command and the
gate's live read.
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLUGIN = os.path.join(REPO, "hermes_plugin", "riel")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hermes_plugin.riel import commands, hooks, settings, tools  # noqa: E402

WRITES = []


def fake_hermes(values=None, writer=True):
    """Install fake `hermes_cli.config` / `hermes_cli.plugins_state` over *values*."""
    live = dict(values or {})
    module = types.ModuleType("hermes_cli.config")
    setattr(module, "load_config_readonly",
            lambda: {"plugins": {"entries": {"riel": {"settings": dict(live)}}}})
    package = types.ModuleType("hermes_cli")
    setattr(package, "config", module)
    sys.modules["hermes_cli"] = package
    sys.modules["hermes_cli.config"] = module
    if writer:
        state = types.ModuleType("hermes_cli.plugins_state")

        def save_plugin_setting(plugin_id, segments, value):
            if value == "boom":
                raise PermissionError("settings are administrator-managed")
            WRITES.append((plugin_id, segments, value))
            live[segments[0]] = value

        setattr(state, "save_plugin_setting", save_plugin_setting)
        setattr(package, "plugins_state", state)
        sys.modules["hermes_cli.plugins_state"] = state
    else:
        # No writer at all: the failure mode of a bare process / managed install.
        sys.modules.pop("hermes_cli.plugins_state", None)
        if hasattr(package, "plugins_state"):
            delattr(package, "plugins_state")
    return live


class SettingsTest(unittest.TestCase):
    def setUp(self):
        WRITES.clear()
        self.live = fake_hermes({})

    def tearDown(self):
        for name in list(sys.modules):
            if name.startswith("hermes_cli"):
                sys.modules.pop(name, None)

    def test_reads_the_group_and_fails_open(self):
        self.assertTrue(settings.read_bool("tools"))
        self.live["tools"] = False
        self.assertFalse(settings.read_bool("tools"))
        self.live["gate"] = "false"  # a string is not a switch
        self.assertTrue(settings.read_bool("gate"))
        sys.modules.pop("hermes_cli", None)
        self.assertTrue(settings.read_bool("gate", True))

    def test_note_is_capped_and_typed(self):
        self.live["harness_note"] = "x" * 5000
        self.assertEqual(len(settings.read_note()), settings.NOTE_MAX_CHARS)
        self.live["harness_note"] = ["nope"]
        self.assertEqual(settings.read_note(), "")

    def test_validate_refuses_junk(self):
        for bad in ({}, {"nope": True}, {"tools": "off"}, {"harness_note": 7},
                    {"harness_note": "x" * (settings.NOTE_MAX_CHARS + 1)}):
            with self.assertRaises(settings.Rejected, msg=bad):
                settings.validate(bad)

    def test_apply_writes_through_hermes_and_returns_the_state(self):
        state = settings.apply({"tools": False, "harness_note": "deferred tools"})
        self.assertFalse(state["tools"])
        self.assertEqual(state["harness_note"], "deferred tools")
        self.assertEqual(WRITES[0][0], "riel")
        self.assertEqual([segment for _p, segments, _v in WRITES for segment in segments],
                         ["tools", "harness_note"])

    def test_a_refused_write_propagates(self):
        with self.assertRaises(PermissionError):
            settings.write("gate", "boom")


class GuardTest(unittest.TestCase):
    """The check_fn hides; the handler must refuse — and never touch the engine."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-guard-test-")
        self.live = fake_hermes({})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for name in list(sys.modules):
            if name.startswith("hermes_cli"):
                sys.modules.pop(name, None)

    def ledger_path(self):
        return os.path.join(self.tmp, ".riel", "ledger.md")

    def test_tools_off_refuses_without_running_the_engine(self):
        self.live["tools"] = False
        payload = json.loads(tools.HANDLERS["riel_note"]({"goal": "must not run", "worktree": self.tmp}))
        self.assertIn("the 'tools' group is off", payload["error"])
        self.assertEqual(payload["group"], "tools")
        self.assertFalse(os.path.exists(self.ledger_path()), "the engine ran while the group was off")

    def test_every_registered_tool_is_guarded(self):
        self.live["tools"] = False
        for name, handler in tools.HANDLERS.items():
            payload = json.loads(handler({"worktree": self.tmp}))
            self.assertIn("group is off", payload.get("error", ""), name)

    def test_tools_on_runs_the_real_engine(self):
        payload = json.loads(tools.HANDLERS["riel_note"]({"goal": "ship it", "worktree": self.tmp}))
        self.assertTrue(payload["passed"], payload)
        self.assertTrue(os.path.exists(self.ledger_path()))

    def test_the_gate_reads_its_switch_per_call(self):
        self.assertTrue(hooks.gate_enabled())
        self.live["gate"] = False
        self.assertFalse(hooks.gate_enabled())
        self.live["gate_attempts"] = "3"
        self.assertEqual(hooks.gate_attempts(), 3, "a digit string is honoured")
        self.live["gate_attempts"] = "many"
        self.assertEqual(hooks.gate_attempts(), 1, "junk falls back to 1")

    def test_the_gate_stands_down_when_off(self):
        hooks.SETTINGS["enabled"] = True
        self.live["gate"] = False
        self.assertIsNone(hooks.pre_verify(session_id="s1", attempt=0))


class CommandTest(unittest.TestCase):
    def setUp(self):
        WRITES.clear()
        self.live = fake_hermes({})

    def tearDown(self):
        for name in list(sys.modules):
            if name.startswith("hermes_cli"):
                sys.modules.pop(name, None)

    def test_status_prints_the_three_groups(self):
        out = commands.handle("")
        for group in settings.GROUP_KEYS:
            self.assertIn(group, out)

    def test_off_writes_and_says_when_it_lands(self):
        out = commands.handle("off tools")
        self.assertIn("tools: off", out)
        self.assertIn("NEXT session", out)
        self.assertFalse(self.live["tools"])

    def test_unknown_group_is_reported(self):
        self.assertIn("Unknown group", commands.handle("off nope"))

    def test_note_and_clear(self):
        self.assertIn("deferred tools", commands.handle("note deferred tools"))
        self.assertEqual(self.live["harness_note"], "deferred tools")
        commands.handle("note -")
        self.assertEqual(self.live["harness_note"], "")

    def test_a_refused_write_is_reported_not_hidden(self):
        """No writer (a bare process, a managed install): say it, do not pretend."""
        fake_hermes({}, writer=False)
        self.assertIn("Could not write", commands.handle("on gate"))


if __name__ == "__main__":
    unittest.main()
