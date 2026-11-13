"""The `riel` prompt section and the name mapping — the discovery surface.

Stdlib-only and Hermes-free on purpose: the section is loaded from the repo
package and the only Hermes touch (`hermes_cli.config.load_config_readonly`)
is faked, so these tests exercise the render the way a session build does —
including the budget, the fail-open switches and the operator's note. The
state line runs against the stub engine (the same file the handler suite
uses), so the whole block is testable without the bundled engine's file.
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "hermes_plugin" / "riel"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import _stub_engine as stub  # noqa: E402
from hermes_plugin.riel import section  # noqa: E402


def fake_hermes_config(settings=None):
    """Install a fake `hermes_cli.config` returning *settings* for this plugin."""
    module = types.ModuleType("hermes_cli.config")
    payload = {"plugins": {"entries": {"riel": {"settings": settings or {}}}}}
    setattr(module, "load_config_readonly", lambda: payload)
    package = types.ModuleType("hermes_cli")
    setattr(package, "config", module)
    sys.modules["hermes_cli"] = package
    sys.modules["hermes_cli.config"] = module


class SectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-section-test-")
        fake_hermes_config({})
        # The section reads the worktree through the dashboard's `read_run`,
        # which reaches the engine via its own tools reference — point that at
        # the stub so the state line is exercised end-to-end, offline.
        stub.install(section._ledger_status().tools)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for name in ("hermes_cli", "hermes_cli.config"):
            sys.modules.pop(name, None)

    def block(self, session_info=None):
        return section.render(session_info or {"cwd": self.tmp})

    # -- the index ---------------------------------------------------------

    def test_names_the_one_door_and_the_six_tools(self):
        block = self.block()
        self.assertIn("riel_guide()", block)
        self.assertIn("everything Riel does is a tool", block)
        for tool in ("riel_guide", "riel_shape", "riel_run", "riel_note",
                     "riel_clean", "riel_check"):
            self.assertIn(tool, block, block)
        self.assertNotIn("riel_todo", block, "the run owns the checks now")
        self.assertNotIn("skill_view", block)
        self.assertNotIn("riel_plan", block, "the old plan tool is gone")
        self.assertNotIn("riel_seam", block, "the old seam tool is gone")
        self.assertNotIn("riel:", block)

    def test_the_run_verbs_travel_in_the_door_line(self):
        block = self.block()
        self.assertIn("new|validate|activate|rebase|status|slice|fetch", block)
        self.assertIn("new|validate|fetch", block)

    def test_stays_within_the_section_budget(self):
        block = self.block()
        self.assertTrue(block)
        self.assertLessEqual(len(block), section.SECTION_MAX_CHARS)

    def test_the_state_and_the_note_yield_to_the_budget(self):
        """Nothing is cut mid-sentence: the volatile parts are dropped whole."""
        original = section.SECTION_MAX_CHARS
        try:
            # Room for the core block and the state, not for the operator's note.
            core = len(section.HEAD) + len(section.index_line()) + len(section._door_line()) + 4
            section.SECTION_MAX_CHARS = core + 160
            block = section.render({"cwd": self.tmp})
            self.assertTrue(block)
            self.assertLessEqual(len(block), section.SECTION_MAX_CHARS)
            self.assertNotIn("\u2026", block.splitlines()[-1])  # no truncated tail
            # Now: not even the state fits.
            section.SECTION_MAX_CHARS = core + 1
            tight = section.render({"cwd": self.tmp})
            self.assertEqual(tight.splitlines()[0], section.HEAD)
            self.assertLessEqual(len(tight), section.SECTION_MAX_CHARS)
        finally:
            section.SECTION_MAX_CHARS = original

    def test_the_note_still_renders_under_a_generous_budget(self):
        fake_hermes_config({"harness_note": "your harness defers tools: use tool_search"})
        block = self.render()
        self.assertIn("your harness defers tools: use tool_search", block)
        self.assertLessEqual(len(block), section.SECTION_MAX_CHARS)

    def test_returns_empty_when_not_even_one_line_fits(self):
        original = section.SECTION_MAX_CHARS
        try:
            section.SECTION_MAX_CHARS = 60
            self.assertEqual(section.render({"cwd": self.tmp}), "")
        finally:
            section.SECTION_MAX_CHARS = original

    # -- the switches (fail-open) ------------------------------------------

    def test_context_switch_off_renders_nothing(self):
        fake_hermes_config({"context": False})
        self.assertEqual(section.render({"cwd": self.tmp}), "")

    def test_a_mis_typed_switch_fails_open(self):
        fake_hermes_config({"context": "false"})
        self.assertTrue(section.render({"cwd": self.tmp}))

    def test_an_unreadable_config_fails_open(self):
        sys.modules.pop("hermes_cli", None)
        sys.modules.pop("hermes_cli.config", None)
        self.assertTrue(section.render({"cwd": self.tmp}))

    # -- the operator's line -----------------------------------------------

    def test_harness_note_renders_last_when_set(self):
        fake_hermes_config({"harness_note": "your harness defers tools: use tool_search"})
        block = self.render()
        self.assertTrue(block.rstrip().endswith("your harness defers tools: use tool_search"))

    def test_harness_note_is_capped(self):
        fake_hermes_config({"harness_note": "x" * 5000})
        block = self.render()
        self.assertLessEqual(len(block), section.SECTION_MAX_CHARS)
        self.assertIn("x" * section.settings.NOTE_MAX_CHARS, block)

    def test_harness_note_of_the_wrong_type_is_ignored(self):
        fake_hermes_config({"harness_note": ["not", "a", "string"]})
        self.assertNotIn("not a string", self.render())

    def render(self):
        return section.render({"cwd": self.tmp})

    # -- the worktree state ------------------------------------------------

    def test_state_line_reads_the_active_run(self):
        tools = section._ledger_status().tools
        stub.seed(self.tmp, goal="ship the package", next="run the suite")
        payload = json.loads(tools.riel_note({"core": "fact — x", "worktree": self.tmp}))
        self.assertEqual(payload["exit_code"], 0, payload)
        state = section.state_line(self.tmp)
        self.assertIn("Goal: ship the package", state)
        self.assertIn("Next: run the suite", state)
        self.assertIn("0 claims · 0 gates · 0 evidence", state)

    def test_no_run_means_no_state_line(self):
        self.assertEqual(section.state_line(self.tmp), "")

    def test_a_junk_worktree_is_silence_not_an_error(self):
        self.assertEqual(section.state_line(""), "")
        self.assertEqual(section.state_line(os.path.join(self.tmp, "nope")), "")

    def test_the_block_carries_the_state_when_there_is_a_run(self):
        stub.seed(self.tmp, goal="ship the package")
        self.assertIn("Worktree state — Goal: ship the package", self.render())


class GuideWiringTest(unittest.TestCase):
    """The section reads the guide's own files — the index cannot drift from them."""

    def test_the_index_line_names_every_shipped_topic(self):
        line = section.index_line()
        topics = section.guide.topics()
        self.assertTrue(topics, "the package ships no guide topics")
        for topic in topics:
            self.assertIn(topic, line)
        self.assertIn('riel_guide(topic="', line)

    def test_the_engine_the_section_reads_through_is_in_the_package(self):
        module = section._ledger_status()
        self.assertTrue(Path(module.ENGINE).is_file(), module.ENGINE)
        self.assertEqual(os.path.basename(os.path.dirname(str(module.ENGINE))), "engine")

    def test_no_hermes_import_at_module_level(self):
        for name in ("section.py", "settings.py"):
            with open(PLUGIN / name, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith(("import ", "from ")):
                        self.assertNotIn("hermes", line.lower(), f"{name}: {line}")
                        self.assertNotIn("from tools.", line, f"{name}: {line}")


if __name__ == "__main__":
    unittest.main()
