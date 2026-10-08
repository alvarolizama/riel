"""The tool contract as the MODEL sees it: first line, budget, and the CLI door.

A tool description is not documentation — it is the routing signal. With
progressive disclosure the model reads a one-line entry per tool in the
`tool_search` catalog, and the line it reads is the description's first
sentence. So the first sentence has to name the family (`Riel`) inside the
window that actually survives, and the rest of the description carries the
detail only a reader that already chose the tool will pay for.

Stdlib only, no Hermes: the schemas and handlers are loaded from the package.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLUGIN = os.path.join(REPO, "hermes_plugin", "riel")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hermes_plugin.riel import schemas, tools  # noqa: E402

# The window the deferred `tool_search` catalog shows for a tool (measured on a
# live prompt: `- riel_note: Write or update the Riel ledger (.riel/ledger.md) in a`).
CATALOG_WINDOW = 60
DESC_MAX_CHARS = 1_200


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

    def test_every_tool_declares_a_worktree_and_an_object_schema(self):
        for schema in schemas.SCHEMAS:
            params = schema["parameters"]
            self.assertEqual(params["type"], "object", schema["name"])
            self.assertIn("worktree", params["properties"], schema["name"])


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

    def test_the_surface_covers_every_verb_the_prose_calls(self):
        self.assertEqual(
            sorted(h for h in tools.HANDLERS),
            sorted(["riel_note", "riel_seam", "riel_resume", "riel_todo", "riel_context",
                    "riel_state", "riel_brief", "riel_shaping", "riel_clean", "riel_fetch",
                    "riel_check"]),
        )

    def test_verb_enums_are_declared_and_refused(self):
        for name, allowed in (("riel_brief", tools.BRIEF_VERBS), ("riel_shaping", tools.SHAPING_VERBS)):
            spelled = self.schema(name)["parameters"]["properties"]["verb"]["description"]
            for verb in allowed:
                self.assertIn(verb, spelled, name)
            payload = self.call(name, {"verb": "run"})
            self.assertIn("unsupported verb", payload["error"], name)
            self.assertEqual(payload["allowed"], list(allowed), name)

    def test_brief_validate_maps_named_parameters_onto_the_engine(self):
        payload = self.call("riel_brief", {"verb": "validate", "file": ".riel/contract.md"})
        self.assertEqual(payload["command"], ["rielctl", "brief", "validate", ".riel/contract.md"],
                         "a relative path stays relative: the engine resolves it in the worktree")

    def test_brief_new_renders_and_does_not_write(self):
        payload = self.call("riel_brief", {"verb": "new", "template": "feature",
                                           "params": ["name=demo", "one_sentence=do the thing"]})
        self.assertTrue(payload["passed"], payload)
        self.assertIn("# Task: demo", payload["stdout"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".riel", "contract.md")),
                         "the tool returns the text; the agent decides what to write")

    def test_brief_new_rejects_a_parameter_that_is_not_key_equals_value(self):
        payload = self.call("riel_brief", {"verb": "new", "template": "feature", "params": ["name"]})
        self.assertIn("key=value", payload["error"])

    def test_brief_without_a_target_file_is_refused(self):
        payload = self.call("riel_brief", {"verb": "digest"})
        self.assertIn("needs 'file'", payload["error"])

    def test_clean_scopes_map_to_the_engine_flags(self):
        for scope, flag in (("ledger", None), ("all", "--all"), ("purge", "--purge")):
            payload = self.call("riel_clean", {"scope": scope})
            self.assertEqual(payload["command"][1], "clean", scope)
            if flag:
                self.assertIn(flag, payload["command"], scope)
            else:
                self.assertEqual(len(payload["command"]), 2, scope)
        self.assertIn("unsupported scope", self.call("riel_clean", {"scope": "everything"})["error"])

    def test_seam_can_carry_the_anchor_re_read(self):
        self.assertEqual(self.call("riel_note", {"goal": "ship it", "next": "run the suite"})["exit_code"], 0)
        payload = self.call("riel_seam", {"anchors": True})
        self.assertEqual(payload["exit_code"], 0, payload)
        self.assertIn("anchors", payload, "seam with anchors must report both surfaces")
        self.assertIn("anchors", self.schema("riel_seam")["parameters"]["properties"])
        self.assertEqual(payload["anchors"]["exit_code"], 1, "no contract here: the anchor half says so")

    def test_a_failed_seam_does_not_run_the_anchor_half(self):
        payload = self.call("riel_seam", {"anchors": True})
        self.assertEqual(payload["exit_code"], 1, "no ledger: the seam itself failed")
        self.assertNotIn("anchors", payload)

    def test_fetch_requires_a_url_and_never_echoes_it_back(self):
        self.assertIn("needs 'url'", self.call("riel_fetch", {})["error"])
        payload = self.call("riel_fetch", {"url": "https://example.test/c.md?token=secret"})
        self.assertEqual(payload["command"][:2], ["rielctl", "fetch"])
        self.assertNotIn("token", payload.get("error", ""))

    def test_check_runs_both_halves_on_one_file(self):
        target = os.path.join(self.tmp, "doc.md")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("# Doc\n\n```mermaid\nflowchart TD\n  A[\"x\"] --> B[\"y\"]\n```\n")
        payload = self.call("riel_check", {"file": target})
        self.assertIn("ship", payload)
        self.assertIn("digest", payload)
        self.assertEqual(payload["ship"]["exit_code"], 0, payload)
        self.assertIn("A", payload["digest"]["stdout"])

    def test_state_is_the_ledger_mirror(self):
        payload = self.call("riel_state", {})
        self.assertEqual(payload["command"][:2], ["rielctl", "status"])
        for key in ("exit_code", "passed", "stdout", "stderr"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
