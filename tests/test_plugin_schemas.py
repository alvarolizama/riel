"""The tool contract as the MODEL sees it: first line, budget, and the verbs.

A tool description is not documentation — it is the routing signal. With
progressive disclosure the model reads a one-line entry per tool in the
`tool_search` catalog, and the line it reads is the description's first
sentence. So the first sentence has to name the family (`Riel`) inside the
window that actually survives, and the rest of the description carries the
detail only a reader that already chose the tool will pay for.

The verb surfaces are pinned here against the HANDLERS too: a verb the schema
promises must be one the handler accepts, and a verb it refuses must be
refused with the allowed list — the model reads that list to recover.

Stdlib only, no Hermes: the schemas and handlers are loaded from the package
(the handlers against the stub engine, so verb surfaces are exercised, not
assumed).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "hermes_plugin" / "riel"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import _stub_engine as stub  # noqa: E402
from hermes_plugin.riel import schemas, tools  # noqa: E402

stub.install(tools)

# The window the deferred `tool_search` catalog shows for a tool (measured on a
# live prompt: `- riel_run: Riel run — ONE door for the contract`).
CATALOG_WINDOW = 60
DESC_MAX_CHARS = 1_200

SEVEN_TOOLS = frozenset({
    "riel_guide", "riel_project", "riel_shape", "riel_run", "riel_note",
    "riel_clean", "riel_check",
})


class SchemaContractTest(unittest.TestCase):
    def test_every_description_names_riel_inside_the_catalog_window(self):
        for schema in schemas.SCHEMAS:
            head = schema["description"][:CATALOG_WINDOW].lower()
            self.assertIn("riel", head, f"{schema['name']} hides its family from the catalog line")

    def test_every_description_opens_with_one_actionable_sentence(self):
        for schema in schemas.SCHEMAS:
            first = schema["description"].split(". ")[0]
            self.assertLessEqual(len(first), 220, f"{schema['name']}: first sentence runs long")

    def test_descriptions_stay_within_their_token_budget(self):
        for schema in schemas.SCHEMAS:
            self.assertLessEqual(len(schema["description"]), DESC_MAX_CHARS, schema["name"])

    def test_every_tool_declares_an_object_schema(self):
        for schema in schemas.SCHEMAS:
            self.assertEqual(schema["parameters"]["type"], "object", schema["name"])

    def test_every_task_tool_declares_a_worktree_and_the_guide_does_not(self):
        """`riel_guide` reads the package's prose: it needs no worktree state."""
        for schema in schemas.SCHEMAS:
            if schema["name"] == "riel_guide":
                self.assertNotIn("worktree", schema["parameters"]["properties"])
                continue
            self.assertIn("worktree", schema["parameters"]["properties"], schema["name"])


class TypedToolsTest(unittest.TestCase):
    """Every verb the prose needs is a TYPED tool — no argv, no bare subcommand."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-tools-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, name, args=None):
        return json.loads(tools.HANDLERS[name]({**(args or {}), "worktree": self.tmp}))

    def schema(self, name):
        return next(s for s in schemas.SCHEMAS if s["name"] == name)

    def test_no_tool_takes_argv(self):
        """The line the user drew: a tool never carries a command line as data."""
        for schema in schemas.SCHEMAS:
            props = schema["parameters"]["properties"]
            for banned in ("args", "argv", "flags"):
                self.assertNotIn(banned, props, f"{schema['name']} smuggles a command line ({banned})")

    def test_the_surface_is_the_seven_tools_the_prose_calls(self):
        self.assertEqual(set(tools.HANDLERS), set(SEVEN_TOOLS))
        self.assertEqual({s["name"] for s in schemas.SCHEMAS}, set(SEVEN_TOOLS))

    def test_project_declares_and_refuses_its_verbs(self):
        spelled = self.schema("riel_project")["parameters"]["properties"]["verb"]["description"]
        for verb in tools.PROJECT_VERBS:
            self.assertIn(verb, spelled)
        payload = self.call("riel_project", {"verb": "activate"})
        self.assertIn("unsupported verb", payload["error"])
        self.assertEqual(payload["allowed"], list(tools.PROJECT_VERBS))

    def test_run_declares_and_refuses_its_verbs(self):
        spelled = self.schema("riel_run")["parameters"]["properties"]["verb"]["description"]
        for verb in tools.RUN_VERBS:
            self.assertIn(verb, spelled)
        payload = self.call("riel_run", {"verb": "digest"})
        self.assertIn("unsupported verb", payload["error"])
        self.assertEqual(payload["allowed"], list(tools.RUN_VERBS))

    def test_shape_declares_and_refuses_its_verbs(self):
        spelled = self.schema("riel_shape")["parameters"]["properties"]["verb"]["description"]
        for verb in tools.SHAPE_VERBS:
            self.assertIn(verb, spelled)
        payload = self.call("riel_shape", {"verb": "activate"})
        self.assertIn("unsupported verb", payload["error"])
        self.assertEqual(payload["allowed"], list(tools.SHAPE_VERBS))

    def test_the_guide_is_the_door_the_prose_names(self):
        described = self.schema("riel_guide")["parameters"]["properties"]
        self.assertIn("topic", described)
        self.assertIn("section", described)

    def test_run_new_prints_the_draft_and_does_not_write(self):
        payload = self.call("riel_run", {"verb": "new", "params": ["name=demo"]})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("# Run:", payload["stdout"])
        self.assertEqual(payload["tool"], "riel_run")
        self.assertEqual(payload["verb"], "new")
        self.assertFalse((Path(self.tmp) / ".riel" / "runs").exists(),
                         "the tool returns the draft; the agent writes .riel/runs/<slug>.md itself")

    def test_run_new_rejects_a_parameter_that_is_not_key_equals_value(self):
        payload = self.call("riel_run", {"verb": "new", "params": ["name"]})
        self.assertIn("key=value", payload["error"])

    def test_run_status_answers_one_json_object(self):
        self.call("riel_note", {"core": "fact — x"})
        payload = self.call("riel_run", {"verb": "status"})
        self.assertTrue(payload["passed"], payload)
        self.assertEqual(payload["verb"], "status")
        state = json.loads(payload["stdout"])
        self.assertIsInstance(state, dict, "status is an object, never the old list")
        for key in ("exit_code", "passed", "stdout", "stderr"):
            self.assertIn(key, payload)

    def test_run_slice_needs_a_phase(self):
        self.assertIn("needs 'phase'", self.call("riel_run", {"verb": "slice"})["error"])

    def test_run_without_a_worktree_directory_is_a_negative_envelope(self):
        payload = json.loads(tools.HANDLERS["riel_run"](
            {"verb": "status", "worktree": os.path.join(self.tmp, "nope")}))
        for key in ("tool", "worktree", "exit_code", "passed", "stdout", "stderr"):
            self.assertIn(key, payload)
        self.assertIn("error", payload)

    def test_clean_takes_an_archive_flag_and_no_scope(self):
        """The envelope reports the TOOL; the engine's flags are implementation."""
        described = self.schema("riel_clean")["parameters"]["properties"]
        self.assertIn("archive", described)
        self.assertEqual(described["archive"]["type"], "boolean")
        self.assertNotIn("scope", described, "clean wipes all of .riel/ — there is no scope")
        payload = self.call("riel_clean", {})
        self.assertEqual(payload["tool"], "riel_clean")
        self.assertNotIn("verb", payload)
        self.assertNotIn("command", payload)
        self.assertIn("no longer takes 'scope'",
                      self.call("riel_clean", {"scope": "all"})["error"])

    def test_note_declares_the_gate_surface(self):
        described = self.schema("riel_note")["parameters"]["properties"]
        for name in ("gates", "command", "covering", "claims", "worktree"):
            self.assertIn(name, described, name)
        self.assertEqual(described["claims"]["type"], "array")
        self.assertEqual(described["gates"]["type"], "array")
        self.assertNotIn("exit_code", described,
                         "the engine records the exit code; the model never passes one")

    def test_note_without_content_flags_refuses_and_names_what_it_accepts(self):
        payload = self.call("riel_note", {})
        self.assertIn("error", payload)
        self.assertIn("accepted", payload)
        self.assertIn("gates", payload["accepted"])
        self.assertIn("claims", payload["accepted"])

    def test_note_rejects_a_claims_array_that_is_not_strings(self):
        payload = self.call("riel_note", {"claims": [1, 2]})
        self.assertIn("array of strings", payload["error"])

    def test_check_runs_both_halves_on_one_file(self):
        target = os.path.join(self.tmp, "doc.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("# Doc\n\n```mermaid\nflowchart TD\n  A[\"x\"] --> B[\"y\"]\n```\n")
        payload = self.call("riel_check", {"file": target})
        self.assertIn("ship", payload)
        self.assertIn("digest", payload)
        self.assertEqual(payload["ship"]["exit_code"], 0, payload)
        self.assertNotIn("mermaid", payload, "the parser-level half is opt-in")

    def test_check_answers_with_the_shared_envelope(self):
        """A composite tool still speaks the envelope every other tool speaks."""
        target = os.path.join(self.tmp, "doc.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("# Doc\n")
        payload = self.call("riel_check", {"file": target})
        for key in ("tool", "worktree", "exit_code", "passed", "stdout", "stderr"):
            self.assertIn(key, payload, f"riel_check misses {key}")
        self.assertEqual(payload["tool"], "riel_check")
        self.assertEqual(payload["exit_code"], 0 if payload["passed"] else 1)


if __name__ == "__main__":
    unittest.main()
