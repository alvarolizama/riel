"""The `riel` prompt section and the name mapping — the discovery surface.

Stdlib-only and Hermes-free on purpose: the section is loaded from the repo
package and the only Hermes touch (`hermes_cli.config.load_config_readonly`)
is faked, so these tests exercise the render the way a session build does —
including the budget, the fail-open switches and the operator's note.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLUGIN = os.path.join(REPO, "hermes_plugin", "riel")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hermes_plugin.riel import section  # noqa: E402  (path set above)

TOPICS = ("protocol", "ledger", "contract", "shaping", "delegate", "tools")


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

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for name in ("hermes_cli", "hermes_cli.config"):
            sys.modules.pop(name, None)

    def block(self, session_info=None):
        return section.render(session_info or {"cwd": self.tmp})

    # -- the index ---------------------------------------------------------

    def test_names_the_one_door_and_the_topics_that_exist(self):
        block = self.block()
        self.assertIn("riel_guide()", block)
        self.assertIn("everything Riel does is a tool", block)
        for topic in TOPICS:
            self.assertIn(topic, block, block)
        self.assertIn("riel_guide", block)
        self.assertNotIn("skill_view", block)
        self.assertNotIn("riel:", block)

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
            section.SECTION_MAX_CHARS = core + 120
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

    def test_state_line_reads_the_worktree_the_session_sits_in(self):
        subprocess.run(
            [sys.executable, str(section.ENGINE), "note", "--goal", "ship the package",
             "--next", "run the suite"],
            cwd=self.tmp, capture_output=True, text=True, check=True,
        )
        state = section.state_line(self.tmp)
        self.assertIn("Goal: ship the package", state)
        self.assertIn("Next: run the suite", state)
        self.assertIn("0 claims · 0 verified · 0 open", state)

    def test_no_ledger_means_no_state_line(self):
        self.assertEqual(section.state_line(self.tmp), "")

    def test_a_missing_engine_is_silence_not_an_error(self):
        self.assertEqual(section.state_line(""), "")
        self.assertEqual(section.state_line(os.path.join(self.tmp, "nope")), "")

    def test_the_block_carries_the_state_when_there_is_a_ledger(self):
        subprocess.run(
            [sys.executable, str(section.ENGINE), "note", "--goal", "ship the package"],
            cwd=self.tmp, capture_output=True, text=True, check=True,
        )
        self.assertIn("Worktree state — Goal: ship the package", self.render())


class GuideWiringTest(unittest.TestCase):
    """The section reads the guide's own files — the index cannot drift from them."""

    def test_the_index_line_names_every_shipped_topic(self):
        line = section.index_line()
        topics = section.guide.topics()
        self.assertEqual(sorted(topics), sorted(TOPICS))
        for topic in topics:
            self.assertIn(topic, line)
        self.assertIn("riel_guide(topic=\"contract\")", line)

    def test_the_engine_the_section_runs_is_in_the_package(self):
        self.assertTrue(os.path.isfile(section.ENGINE), section.ENGINE)
        self.assertEqual(os.path.basename(os.path.dirname(section.ENGINE)), "engine")

    def test_no_hermes_import_at_module_level(self):
        for name in ("section.py", "settings.py"):
            with open(os.path.join(PLUGIN, name), encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith(("import ", "from ")):
                        self.assertNotIn("hermes", line.lower(), f"{name}: {line}")
                        self.assertNotIn("from tools.", line, f"{name}: {line}")


if __name__ == "__main__":
    unittest.main()
