"""Regression tests for the Hermes plugin package (hermes_plugin/riel).

Stdlib-only and Hermes-free on purpose: the plugin's handler module imports
nothing from Hermes at module level, so these tests exercise the real handlers
against the **bundled** engine — the same copy a user gets when installing
the plugin.

Two things are pinned here:
  * `guide/`, `engine/` and `templates/` exist in the package and NOWHERE else,
    so the duplication cannot come back;
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

MANIFEST = os.path.join(PLUGIN, "plugin.yaml")

# The package's own tree: the prose (`guide/`), the engine the tools run
# (`engine/`) and the packet templates (`templates/`). They live here and are
# edited here — a same-named directory at the repo root is a regression.
PARTS = ("guide", "engine", "templates")

# The topics the prose ships today: ONE door (`riel_guide`) reads them.
TOPICS = ("briefs", "contract", "delegate", "ledger", "protocol", "tools")


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


def _tree(root):
    """`{relative path: sha256}` for every file under *root*, skipping bytecode."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            files[os.path.relpath(full, root)] = sha256(full)
    return files


def _frontmatter(path):
    """The YAML frontmatter of a guide as a flat `{key: value}` map (stdlib only)."""
    meta, lines, inside = {}, [], False
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.strip() == "---":
                if inside:
                    break
                inside = True
                continue
            if inside:
                lines.append(line)
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


class PackageTest(unittest.TestCase):
    """One tree: the package owns its sources — nothing to rebuild, nothing to drift."""

    def test_every_part_is_there_and_edit_in_place(self):
        """Each part exists in the package — and NOWHERE else in the repo.

        The old layout kept a copy at the repo root and pinned it by hash; the
        single tree removed both the copy and the pin. A stray root dir means
        someone re-created the duplication.
        """
        for part in PARTS:
            bundled = os.path.join(PLUGIN, part)
            self.assertTrue(os.path.isdir(bundled), f"{part}/ is missing from the package")
            self.assertTrue(_tree(bundled), f"{part}/ is empty")
            self.assertFalse(os.path.exists(os.path.join(REPO, part)),
                             f"{part}/ reappeared at the repo root: the package owns it")

    def test_the_prose_ships_with_its_frontmatter(self):
        guide_dir = os.path.join(PLUGIN, "guide")
        self.assertEqual(sorted(f for f in os.listdir(guide_dir) if f.endswith(".md")),
                         sorted(f"{topic}.md" for topic in TOPICS))
        for topic in TOPICS:
            path = os.path.join(guide_dir, f"{topic}.md")
            meta = _frontmatter(path)
            self.assertEqual(meta.get("topic"), topic, path)
            self.assertTrue(meta.get("trigger"), f"{topic} has no trigger")
            self.assertTrue(meta.get("version"), f"{topic} has no version")

    def test_the_bundle_carries_the_machinery_the_prose_calls(self):
        engine = os.path.join(PLUGIN, "engine", "run.py")
        templates = os.path.join(PLUGIN, "templates")
        self.assertTrue(os.path.isfile(engine))
        self.assertTrue(os.path.isfile(engine), engine)
        self.assertEqual(len([f for f in os.listdir(templates) if f.endswith(".md")]), 8,
                         "the package ships the eight packet/shaping templates")
        self.assertTrue(os.access(engine, os.X_OK), "the bundled engine must stay executable")

    def test_no_vendor_or_skills_directory(self):
        self.assertFalse(os.path.exists(os.path.join(PLUGIN, "vendor")), "vendor/ was retired")
        self.assertFalse(os.path.exists(os.path.join(PLUGIN, "skills")),
                         "skills/ was retired: the prose is served by riel_guide")

    def test_the_package_registers_no_skill(self):
        """One door: nothing in the package calls `register_skill`."""
        with open(os.path.join(PLUGIN, "__init__.py"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("register_skill", source)


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
    """The handlers drive the bundled engine end-to-end."""

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
        self.assertEqual(seam["tool"], "riel_seam")
        self.assertNotIn("command", seam)

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


class ContextToolTest(unittest.TestCase):
    """`riel_context`: hands over the contract's index — it does NOT search.

    Memory backends live in the agent's memory manager, not in the tool
    registry, so a plugin cannot reach them. These tests pin that boundary:
    the tool returns terms (and says who searches), never hits.
    """

    @classmethod
    def setUpClass(cls):
        cls.tools = load_module("riel_plugin_tools_ctx", os.path.join(PLUGIN, "tools.py"))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-ctx-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _contract(self, keywords="- login flow → dran\n- phoenix streams\n"):
        path = os.path.join(self.tmp, ".riel", "contract.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "# Task: t\n\n## Objective\nWe need x\n\n## Context\n\n"
                "### Context keywords\n" + keywords + "\n## DO NOT\n- x\n"
            )

    def payload(self, args):
        raw = self.tools.riel_context(args)
        self.assertIsInstance(raw, str, "handlers must return a JSON string")
        return json.loads(raw)

    def test_returns_the_contract_index(self):
        self._contract()
        result = self.payload({"worktree": self.tmp})
        self.assertEqual(result["origin"], "contract")
        self.assertEqual(result["keywords"], [
            {"term": "login flow", "source": "dran"},
            {"term": "phoenix streams", "source": ""},
        ])

    def test_it_does_not_search_and_says_who_does(self):
        """The whole point of the boundary: no hits, and the agent is told."""
        self._contract()
        result = self.payload({"worktree": self.tmp})
        self.assertNotIn("hits", result)
        self.assertNotIn("results", result)
        self.assertIn("Core", result["next"])
        self.assertIn("does not search", result["next"])

    def test_explicit_keywords_override_the_contract(self):
        self._contract()
        result = self.payload({"worktree": self.tmp, "keywords": ["solo esta"]})
        self.assertEqual(result["origin"], "argument")
        self.assertEqual(result["keywords"], [{"term": "solo esta", "source": ""}])

    def test_keyword_count_is_capped(self):
        self._contract("".join("- kw {}\n".format(i) for i in range(20)))
        result = self.payload({"worktree": self.tmp})
        self.assertEqual(len(result["keywords"]), self.tools.MAX_KEYWORDS)
        self.assertTrue(result["truncated"])

    def test_contract_without_keywords_is_a_note_not_an_error(self):
        self._contract("")
        result = self.payload({"worktree": self.tmp})
        self.assertEqual(result["keywords"], [])
        self.assertIn("note", result)
        self.assertNotIn("next", result)

    def test_missing_contract_errors_with_a_hint(self):
        result = self.payload({"worktree": self.tmp})
        self.assertIn("error", result)
        self.assertIn("hint", result)

    def test_bad_worktree_errors(self):
        result = self.payload({"worktree": os.path.join(self.tmp, "nope")})
        self.assertIn("not a directory", result["error"])


if __name__ == "__main__":
    unittest.main()
