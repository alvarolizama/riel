"""Regression tests for the Hermes plugin package (hermes_plugin/riel).

Stdlib-only and Hermes-free on purpose: the plugin's handler module imports
nothing from Hermes at module level, so these tests exercise the real handlers
against the **vendored** rielctl — the same copy a user gets when installing
the plugin.

Two things are pinned here:
  * `vendor/` matches the repo sources (hash), so the build artifact cannot drift;
  * manifest, schemas and handlers agree, and the handlers actually run.

Run:
    python3 -m unittest discover -s tests -v
"""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLUGIN = os.path.join(REPO, "hermes_plugin", "riel")

SOURCE_RIELCTL = os.path.join(REPO, "skills", "riel-cli", "scripts", "rielctl")
SOURCE_TEMPLATES = os.path.join(REPO, "skills", "riel-briefs", "templates")
VENDOR_RIELCTL = os.path.join(PLUGIN, "vendor", "riel-cli", "scripts", "rielctl")
VENDOR_TEMPLATES = os.path.join(PLUGIN, "vendor", "riel-briefs", "templates")
MANIFEST = os.path.join(PLUGIN, "plugin.yaml")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name, path):
    """Load a stdlib-only module from an arbitrary path (no package import)."""
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:  # pragma: no cover - SourceFileLoader always yields a spec
        raise RuntimeError(f"could not build a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _manifest_tools():
    """The `provides_tools` list from plugin.yaml (no YAML dependency)."""
    tools, in_list = [], False
    with open(MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("provides_tools:"):
                in_list = True
                continue
            if in_list:
                if line.startswith("  - "):
                    tools.append(line.strip()[2:].strip())
                elif line.strip() and not line.startswith(" "):
                    break
    return tools


class VendoringTest(unittest.TestCase):
    """`make plugin-vendor` output must equal the repo sources, byte for byte."""

    def test_vendored_rielctl_matches_source(self):
        self.assertTrue(os.path.isfile(VENDOR_RIELCTL), "run: make plugin-vendor")
        self.assertEqual(sha256(VENDOR_RIELCTL), sha256(SOURCE_RIELCTL))

    def test_vendored_templates_match_source(self):
        self.assertTrue(os.path.isdir(VENDOR_TEMPLATES), "run: make plugin-vendor")
        source = sorted(f for f in os.listdir(SOURCE_TEMPLATES) if f.endswith(".md"))
        vendored = sorted(f for f in os.listdir(VENDOR_TEMPLATES) if f.endswith(".md"))
        self.assertEqual(vendored, source)
        for name in source:
            self.assertEqual(
                sha256(os.path.join(VENDOR_TEMPLATES, name)),
                sha256(os.path.join(SOURCE_TEMPLATES, name)),
                f"{name} drifted from skills/riel-briefs/templates/",
            )


class WiringTest(unittest.TestCase):
    """Manifest, schemas and handlers describe the same tools."""

    @classmethod
    def setUpClass(cls):
        cls.tools = load_module("riel_plugin_tools", os.path.join(PLUGIN, "tools.py"))
        cls.schemas = load_module("riel_plugin_schemas", os.path.join(PLUGIN, "schemas.py"))

    def test_manifest_declares_registered_tools(self):
        self.assertEqual(sorted(_manifest_tools()), sorted(self.tools.HANDLERS))

    def test_schemas_match_handlers(self):
        self.assertEqual(
            sorted(s["name"] for s in self.schemas.SCHEMAS),
            sorted(self.tools.HANDLERS),
        )

    def test_every_schema_has_a_description(self):
        for schema in self.schemas.SCHEMAS:
            self.assertTrue(schema.get("description"), schema["name"])

    def test_no_hermes_import_at_module_level(self):
        """The handler module must stay importable outside Hermes."""
        with open(os.path.join(PLUGIN, "tools.py"), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(("import ", "from ")):
                    self.assertNotIn("hermes", line.lower())
                    self.assertNotIn("from tools.", line)


class HandlerTest(unittest.TestCase):
    """The handlers drive the vendored rielctl end-to-end."""

    @classmethod
    def setUpClass(cls):
        cls.tools = load_module("riel_plugin_tools_run", os.path.join(PLUGIN, "tools.py"))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-plugin-test-")
        self.real_tmp = os.path.realpath(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, handler, args):
        raw = handler(args)
        self.assertIsInstance(raw, str, "handlers must return a JSON string")
        return json.loads(raw)

    def test_note_writes_the_ledger_and_seam_reads_it(self):
        note = self.payload(self.tools.riel_note, {"goal": "ship the plugin", "worktree": self.tmp})
        self.assertEqual(note["exit_code"], 0, note)
        self.assertTrue(note["passed"])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, ".riel", "ledger.md")))

        seam = self.payload(self.tools.riel_seam, {"worktree": self.tmp})
        self.assertEqual(seam["exit_code"], 0, seam)
        self.assertIn("ship the plugin", seam["stdout"])
        self.assertEqual(seam["command"], ["rielctl", "seam"])

    def test_todo_returns_the_session_mirror(self):
        self.payload(self.tools.riel_note, {"goal": "goal text", "next": "next action", "worktree": self.tmp})
        todo = self.payload(self.tools.riel_todo, {"worktree": self.tmp})
        self.assertEqual(todo["exit_code"], 0, todo)
        items = json.loads(todo["stdout"])
        self.assertIsInstance(items, list)
        self.assertTrue(any("goal text" in json.dumps(item) for item in items), items)

    def test_resume_runs_in_the_worktree(self):
        self.payload(self.tools.riel_note, {"goal": "resume goal", "worktree": self.tmp})
        resume = self.payload(self.tools.riel_resume, {"worktree": self.tmp})
        self.assertEqual(resume["exit_code"], 0, resume)
        self.assertIn("resume goal", resume["stdout"])

    def test_note_without_content_flags_errors_and_writes_nothing(self):
        payload = self.payload(self.tools.riel_note, {"worktree": self.tmp})
        self.assertIn("error", payload)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".riel")))

    def test_note_rejects_a_non_integer_slot(self):
        payload = self.payload(self.tools.riel_note, {"core_slot": "one", "worktree": self.tmp})
        self.assertIn("error", payload)
        self.assertIn("integer", payload["error"])

    def test_from_contract_false_is_treated_as_absent(self):
        payload = self.payload(self.tools.riel_note, {"from_contract": "false", "worktree": self.tmp})
        self.assertIn("error", payload)

    def test_missing_worktree_returns_an_error_not_an_exception(self):
        payload = self.payload(self.tools.riel_seam, {"worktree": os.path.join(self.tmp, "nope")})
        self.assertIn("error", payload)
        self.assertIn("not a directory", payload["error"])

    def test_worktree_defaults_to_the_process_cwd(self):
        """Without an explicit worktree and outside Hermes: TERMINAL_CWD → cwd."""
        previous = os.getcwd()
        try:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TERMINAL_CWD", None)
                os.chdir(self.tmp)
                payload = self.payload(self.tools.riel_todo, {})
                self.assertEqual(payload["worktree"], os.path.realpath(os.getcwd()))
        finally:
            os.chdir(previous)

    def test_terminal_cwd_is_used_when_no_session_record_exists(self):
        """Outside Hermes the env var is the last resort before the process cwd."""
        with mock.patch.dict(os.environ, {"TERMINAL_CWD": self.tmp}, clear=False):
            payload = self.payload(self.tools.riel_todo, {})
        self.assertEqual(payload["worktree"], self.tmp)


if __name__ == "__main__":
    unittest.main()
