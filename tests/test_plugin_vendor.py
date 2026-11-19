"""Regression tests for the Hermes plugin package (hermes_plugin/riel).

Stdlib-only and Hermes-free on purpose. Two kinds of tests live here:

  * package/wiring — the tree layout, the manifest, the version contract and
    the schema/handler agreement, all against the REAL package files;
  * handlers — driven end-to-end against the STUB engine (`_stub_engine.py`),
    a faithful stand-in for the 2.0 run/shaping contract. The bundled engine
    is the sole writer of the formats and has its own suite; pinning the
    plugin layer to it would couple two suites two workers move at once.

Version contract (v4.0.0, contracts executed in place): the manifest, the
package README and the engine's VERSION all say 4.0.0 — asserted here so the three cannot
drift apart.

Run:
    python3 -m unittest discover -s tests -v
"""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "hermes_plugin" / "riel"

sys.path.insert(0, str(HERE))

import _stub_engine as stub  # noqa: E402

MANIFEST = PLUGIN / "plugin.yaml"
VERSION = "4.0.0"

# The package's own tree: the prose (`guide/`), the engine the tools run
# (`engine/`) and the run/shaping templates (`templates/`). They live here and
# are edited here — a same-named directory at the repo root is a regression.
PARTS = ("guide", "engine", "templates")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_module(name, path):
    """Load a stdlib-only module from an arbitrary path (no package import)."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:  # pragma: no cover - SourceFileLoader always yields a spec
        raise RuntimeError(f"could not build a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _manifest_field(field):
    """A top-level scalar from plugin.yaml (no YAML dependency)."""
    with open(MANIFEST, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith(f"{field}:"):
                return line.split(":", 1)[1].strip().strip('"')
    return None


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
        """Each part exists in the package — and NOWHERE else in the repo."""
        for part in PARTS:
            bundled = PLUGIN / part
            self.assertTrue(bundled.is_dir(), f"{part}/ is missing from the package")
            self.assertTrue(_tree(bundled), f"{part}/ is empty")
            self.assertFalse((REPO / part).exists(),
                             f"{part}/ reappeared at the repo root: the package owns it")

    def test_the_prose_ships_with_its_frontmatter(self):
        """Every guide file carries its identity (topic/trigger/version)."""
        guide_dir = PLUGIN / "guide"
        guides = sorted(guide_dir.glob("*.md"))
        self.assertTrue(guides, "the package ships no guide/ prose")
        for path in guides:
            meta = _frontmatter(path)
            self.assertEqual(meta.get("topic"), path.stem, path)
            self.assertTrue(meta.get("trigger"), f"{path.stem} has no trigger")
            self.assertTrue(meta.get("version"), f"{path.stem} has no version")

    def test_the_bundle_carries_the_machinery_the_prose_calls(self):
        engine = PLUGIN / "engine" / "run.py"
        templates = PLUGIN / "templates"
        self.assertTrue(engine.is_file())
        self.assertTrue(engine.is_file(), engine)
        names = {p.name for p in templates.glob("*.md")}
        self.assertIn("run.md", names, "the run template ships with the package")
        self.assertIn("shaping.md", names, "the shaping template ships with the package")
        self.assertTrue(os.access(engine, os.X_OK), "the bundled engine must stay executable")

    def test_no_vendor_or_skills_directory(self):
        self.assertFalse((PLUGIN / "vendor").exists(), "vendor/ was retired")
        self.assertFalse((PLUGIN / "skills").exists(),
                         "skills/ was retired: the prose is served by riel_guide")

    def test_the_package_registers_no_skill(self):
        """One door: nothing in the package calls `register_skill`."""
        with open(PLUGIN / "__init__.py", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("register_skill", source)


class VersionContractTest(unittest.TestCase):
    """4.0.0 — said identically by manifest, README and engine."""

    def test_the_manifest_is_3_0_0(self):
        self.assertEqual(_manifest_field("version"), VERSION, MANIFEST)

    def test_the_package_readme_says_the_same_version(self):
        """The package's own README (the installed user's doc) names v4.0.0."""
        readme = (PLUGIN / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"v{VERSION}", readme,
                      f"hermes_plugin/riel/README.md does not say v{VERSION}")

    def test_the_engine_says_the_same_version(self):
        module = load_module("riel_engine_version", PLUGIN / "engine" / "run.py")
        self.assertEqual(module.VERSION, VERSION,
                         "the engine's VERSION and the manifest disagree")

    def test_the_major_bump_is_declared_in_the_manifest_description(self):
        """A clean break is not a silent one: the description names the model."""
        description = _manifest_field("description") or ""
        self.assertIn("runs/<slug>.md", description)


class WiringTest(unittest.TestCase):
    """Manifest, schemas and handlers describe the same tools."""

    @classmethod
    def setUpClass(cls):
        cls.tools = load_module("riel_plugin_tools", PLUGIN / "tools.py")
        cls.schemas = load_module("riel_plugin_schemas", PLUGIN / "schemas.py")

    def test_the_surface_is_the_seven_tools_of_the_project_model(self):
        self.assertEqual(
            sorted(self.tools.HANDLERS),
            sorted(["riel_guide", "riel_project", "riel_shape", "riel_run",
                    "riel_note", "riel_clean", "riel_check"]),
        )
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
        with open(PLUGIN / "tools.py", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(("import ", "from ")):
                    self.assertNotIn("hermes", line.lower())
                    self.assertNotIn("from tools.", line)


class HandlerTest(unittest.TestCase):
    """The handlers drive the (stub) engine end-to-end, over real files."""

    @classmethod
    def setUpClass(cls):
        cls.tools = stub.install(load_module("riel_plugin_handlers", PLUGIN / "tools.py"))

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-plugin-test-")
        self.real_tmp = os.path.realpath(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, handler, args):
        raw = handler(args)
        self.assertIsInstance(raw, str, "handlers must return a JSON string")
        return json.loads(raw)

    def test_every_negative_still_speaks_the_shared_envelope(self):
        """A refusal is an envelope at exit_code 1 — six base keys, every time."""
        for handler, args in (
            (self.tools.riel_run, {"verb": "status", "worktree": os.path.join(self.tmp, "nope")}),
            (self.tools.riel_note, {"worktree": self.tmp}),
            (self.tools.riel_run, {"verb": "nope", "worktree": self.tmp}),
            (self.tools.riel_shape, {"verb": "nope", "worktree": self.tmp}),
            (self.tools.riel_run, {"verb": "slice", "worktree": self.tmp}),
            (self.tools.riel_check, {"worktree": self.tmp}),
        ):
            with self.subTest(args=args):
                payload = self.payload(handler, args)
                for key in ("tool", "worktree", "exit_code", "passed", "stdout", "stderr"):
                    self.assertIn(key, payload, f"the negative lacks {key}")
                self.assertFalse(payload["passed"])
                self.assertIn("error", payload)

    def test_run_new_prints_the_draft_and_never_writes(self):
        payload = self.payload(self.tools.riel_run, {"verb": "new", "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("# Run:", payload["stdout"])
        self.assertFalse((Path(self.tmp) / ".riel" / "runs").exists(),
                         "the tool returns the draft; the agent writes .riel/runs/<slug>.md itself")

    def test_note_executes_a_gate_and_records_the_evidence(self):
        """gates + command → the ENGINE runs it, records E# and closes the claims."""
        stub.seed(self.tmp, claims=["P1"], gates=["G1"])
        payload = self.payload(self.tools.riel_note, {
            "gates": ["G1"], "command": "true", "covering": "all",
            "claims": ["P1"], "worktree": self.tmp,
        })
        self.assertEqual(payload["exit_code"], 0, payload)
        state = json.loads(self.payload(self.tools.riel_run,
                                        {"verb": "status", "worktree": self.tmp})["stdout"])
        self.assertIsInstance(state, dict, "run status answers ONE JSON object")
        self.assertTrue(state["gates"][0]["done"])
        self.assertEqual(state["gates"][0]["exit_code"], 0)
        self.assertTrue(state["claims"][0]["done"])
        self.assertEqual(state["evidence"][0]["id"], "E1")

    def test_a_failing_gate_is_recorded_not_hidden(self):
        stub.seed(self.tmp, claims=["P1"], gates=["G1"])
        self.payload(self.tools.riel_note, {
            "gates": ["G1"], "command": "false", "claims": ["P1"], "worktree": self.tmp,
        })
        state = json.loads(self.payload(self.tools.riel_run,
                                        {"verb": "status", "worktree": self.tmp})["stdout"])
        self.assertEqual(state["gates"][0]["exit_code"], 1)
        self.assertFalse(state["claims"][0]["done"])

    def test_the_caller_never_passes_an_exit_code(self):
        """The exit code in the state comes from the RUN, never from the call."""
        stub.seed(self.tmp, claims=["P1"], gates=["G1"])
        payload = self.payload(self.tools.riel_note, {
            "gates": ["G1"], "command": "false", "exit_code": 0, "worktree": self.tmp,
        })
        self.assertEqual(payload["exit_code"], 1)
        self.assertIn("unknown parameter", payload["error"])
        state = json.loads(self.payload(self.tools.riel_run,
                                        {"verb": "status", "worktree": self.tmp})["stdout"])
        self.assertIsNone(state["gates"][0]["exit_code"],
                          "a rejected caller field never becomes evidence")

    def test_shape_new_renders_and_does_not_write(self):
        payload = self.payload(self.tools.riel_shape,
                               {"verb": "new", "params": ["name=demo"], "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("# Shaping:", payload["stdout"])
        self.assertFalse((Path(self.tmp) / ".riel" / "shapings").exists(),
                         "the tool returns the text; the agent decides what to write")

    def test_shape_validate_accepts_the_written_shaping(self):
        shaping = Path(self.tmp) / ".riel" / "shapings" / "demo.md"
        shaping.parent.mkdir(parents=True)
        shaping.write_text(
            "# Shaping: demo\n\n<!-- riel-shaping/v3 id:shp_0a1b2c3d -->\n\n"
            "## Question\nDoes it read one file?\n\n"
            "## Answer\nIn one file — supported by F1\n", encoding="utf-8")
        payload = self.payload(self.tools.riel_shape, {"verb": "validate", "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)

    def test_run_slice_needs_a_phase(self):
        payload = self.payload(self.tools.riel_run, {"verb": "slice", "worktree": self.tmp})
        self.assertIn("needs 'phase'", payload["error"])
        payload = self.payload(self.tools.riel_run, {"verb": "slice", "phase": "F1",
                                                     "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("# Run slice: F1", payload["stdout"])

    def test_run_activate_arms_the_gate(self):
        stub.seed(self.tmp)
        payload = self.payload(self.tools.riel_run, {"verb": "activate", "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)
        state = json.loads(self.payload(self.tools.riel_run,
                                        {"verb": "status", "worktree": self.tmp})["stdout"])
        self.assertTrue(state["active"])

    def test_clean_wipes_the_state_and_does_not_archive_by_default(self):
        stub.seed(self.tmp, goal="old task")
        payload = self.payload(self.tools.riel_clean, {"worktree": self.tmp})
        self.assertEqual(payload["tool"], "riel_clean")
        self.assertNotIn("verb", payload, "clean takes no verb — the envelope says the tool")
        self.assertFalse((Path(self.tmp) / ".riel" / "runs").exists())
        self.assertEqual(list((Path(self.tmp) / ".riel").glob("*.bak.md")), [],
                         "archiving is opt-in: the default leaves no backup")

    def test_check_folds_the_halves_into_the_shared_envelope(self):
        target = Path(self.tmp, "doc.md")
        target.write_text("# Doc\n\n```mermaid\nflowchart TD\n  A[\"x\"] --> B[\"y\"]\n```\n",
                          encoding="utf-8")
        payload = self.payload(self.tools.riel_check, {"file": str(target)})
        for key in ("tool", "worktree", "exit_code", "passed", "stdout", "stderr"):
            self.assertIn(key, payload, f"riel_check misses {key}")
        self.assertIn("ship", payload)
        self.assertIn("digest", payload)
        self.assertNotIn("mermaid", payload, "the parser-level half is opt-in")
        self.assertIn("digest A -> B", payload["stdout"], "the halves' text rides in stdout too")

    def test_check_parses_the_diagrams_when_asked(self):
        target = Path(self.tmp, "doc.md")
        target.write_text("# Doc\n", encoding="utf-8")
        payload = self.payload(self.tools.riel_check, {"file": str(target), "mermaid": True})
        self.assertIn("mermaid", payload)
        self.assertTrue(payload["passed"], payload)

    def test_a_missing_worktree_is_a_negative_envelope(self):
        payload = self.payload(self.tools.riel_run, {"verb": "status",
                                                     "worktree": os.path.join(self.tmp, "nope")})
        self.assertIn("not a directory", payload["error"])

    def test_worktree_defaults_to_the_process_cwd(self):
        """Without an explicit worktree and outside Hermes: TERMINAL_CWD → cwd."""
        previous = os.getcwd()
        try:
            os.environ.pop("TERMINAL_CWD", None)
            os.chdir(self.tmp)
            payload = self.payload(self.tools.riel_run, {"verb": "status"})
            self.assertEqual(payload["worktree"], os.path.realpath(os.getcwd()))
        finally:
            os.chdir(previous)

    def test_terminal_cwd_is_used_when_no_session_record_exists(self):
        """Outside Hermes the env var is the last resort before the process cwd."""
        with mock.patch.dict(os.environ, {"TERMINAL_CWD": self.tmp}, clear=False):
            payload = self.payload(self.tools.riel_run, {"verb": "status"})
        self.assertEqual(payload["worktree"], self.tmp)


class LoaderRetryTest(unittest.TestCase):
    """A failed engine load is never poisoned forever."""

    @classmethod
    def setUpClass(cls):
        cls.tools = load_module("riel_plugin_loader", PLUGIN / "tools.py")

    def test_a_failed_load_is_retried_on_the_next_call(self):
        tmp = tempfile.mkdtemp(prefix="riel-loader-")
        self.addCleanup(shutil.rmtree, tmp, True)
        broken = Path(tmp) / "broken.py"
        broken.write_text("raise RuntimeError('half-written update')\n", encoding="utf-8")

        real = self.tools.ENGINE
        try:
            self.tools.ENGINE = broken
            payload = json.loads(self.tools.riel_run({"verb": "status", "worktree": tmp}))
            for key in ("tool", "worktree", "exit_code", "passed", "stdout", "stderr"):
                self.assertIn(key, payload, f"the jammed engine lacks {key}")
            self.assertFalse(payload["passed"])
            self.assertTrue(payload["stderr"], "the jammed engine explains itself")
            # `hermes plugins update` lands mid-process: the next call retries.
            self.tools.ENGINE = stub.ENGINE_PATH
            self.tools._ENGINE["module"] = None
            payload = json.loads(self.tools.riel_run({"verb": "status", "worktree": tmp}))
            self.assertEqual(payload["exit_code"], 0, payload)
        finally:
            self.tools.ENGINE = real
            self.tools._ENGINE["module"] = None


class EngineIntegrationTest(unittest.TestCase):
    """The handlers against the REAL bundled engine — the contract, not a stub.

    The stub suite above pins the plugin layer independently of the engine's
    own suite; this one lights up the actual pair, so a flag the engine renames
    fails HERE instead of silently in a session. Skips only when the bundled
    engine file is absent (a half-written install).
    """

    @classmethod
    def setUpClass(cls):
        if not (PLUGIN / "engine" / "run.py").is_file():
            raise unittest.SkipTest("the bundled engine is not present")
        cls.tools = load_module("riel_plugin_tools_real", PLUGIN / "tools.py")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-integration-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, handler, args):
        return json.loads(handler(args))

    def test_run_new_renders_the_v1_draft(self):
        payload = self.payload(self.tools.riel_run, {"verb": "new", "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("riel-run/v1", payload["stdout"])
        self.assertFalse((Path(self.tmp) / ".riel" / "runs").exists())

    def test_shape_new_renders_the_shaping_template(self):
        payload = self.payload(self.tools.riel_shape,
                               {"verb": "new", "params": ["name=demo"], "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("# Shaping:", payload["stdout"])
        self.assertIn("riel-shaping/v3", payload["stdout"])
        self.assertFalse((Path(self.tmp) / ".riel" / "shapings").exists())

    def test_a_missing_run_state_is_a_negative_envelope(self):
        payload = self.payload(self.tools.riel_run, {"verb": "status", "worktree": self.tmp})
        self.assertFalse(payload["passed"])
        for key in ("tool", "worktree", "exit_code", "passed", "stdout", "stderr"):
            self.assertIn(key, payload)
        self.assertIn("contract in .riel/runs/", payload["stderr"])

    def test_note_without_a_run_state_refuses(self):
        payload = self.payload(self.tools.riel_note,
                               {"core": "probe — fact", "worktree": self.tmp})
        self.assertFalse(payload["passed"])
        self.assertIn("contract in .riel/runs/", payload["stderr"])

    def test_clean_archive_flag_reaches_the_engine(self):
        stub.seed(self.tmp, goal="old task")
        # The real engine archives under ~/.hermes/riel/archive — point HOME at
        # the temp dir so a test never writes into the operator's home.
        home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp
        self.addCleanup(lambda: os.environ.__setitem__("HOME", home)
                        if home else os.environ.pop("HOME", None))
        payload = self.payload(self.tools.riel_clean,
                               {"archive": True, "worktree": self.tmp})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("archived", payload["stdout"])
        self.assertFalse((Path(self.tmp) / ".riel" / "runs").exists())
        self.assertTrue(list(Path(self.tmp).glob(".hermes/riel/archive/**/*.md")),
                        "the archive lands OUTSIDE .riel/, which clean wipes")

    def test_check_answers_the_engine_json_through_the_envelope(self):
        doc = Path(self.tmp) / "doc.md"
        doc.write_text("# Doc\n", encoding="utf-8")
        payload = self.payload(self.tools.riel_check, {"file": str(doc)})
        for key in ("tool", "worktree", "exit_code", "passed", "stdout", "stderr"):
            self.assertIn(key, payload)
        self.assertIn("ship", payload)
        self.assertIn("digest", payload)


if __name__ == "__main__":
    unittest.main()
