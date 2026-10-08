"""`riel_guide` — the prose's only door.

What is pinned here is the shape of the door, not the prose itself:

  * with no `topic` it lists the topics (the index the prompt section also uses);
  * with a `topic` it returns that guide's BODY, frontmatter stripped;
  * with `topic` + `section` it returns just that `## heading` — the slice;
  * a bad topic or section is a STRUCTURED error that says what does exist
    (`topic`/`topics`/`sections`/`hint`), never an exception and never a silence;
  * the schema's topic list cannot drift from the files shipped;
  * the tool obeys the same envelope as every other Riel tool.

Stdlib-only and Hermes-free: the handler module imports nothing from Hermes.
"""

import importlib.machinery
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLUGIN = os.path.join(REPO, "hermes_plugin", "riel")
GUIDE_DIR = os.path.join(PLUGIN, "guide")


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:  # pragma: no cover - SourceFileLoader always yields a spec
        raise RuntimeError(f"could not build a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class GuideModuleTest(unittest.TestCase):
    """`guide.py` reads the shipped files — it invents nothing."""

    @classmethod
    def setUpClass(cls):
        cls.guide = load_module("riel_plugin_guide_mod", os.path.join(PLUGIN, "guide.py"))
        cls.schemas = load_module("riel_plugin_schemas_guide", os.path.join(PLUGIN, "schemas.py"))

    def test_entries_come_from_the_files(self):
        topics = self.guide.topics()
        files = sorted(f[:-3] for f in os.listdir(GUIDE_DIR) if f.endswith(".md"))
        self.assertEqual(sorted(topics), files)
        self.assertTrue(topics, "the package ships no prose")
        for topic, path, trigger in self.guide.entries():
            self.assertTrue(trigger, f"{topic} ships no trigger")
            self.assertTrue(os.path.isfile(path), path)

    def test_every_topic_has_a_version_and_no_skill_costume(self):
        for topic, path, _trigger in self.guide.entries():
            fields = self.guide._frontmatter(path)
            self.assertRegex(fields.get("version", ""), r"^\d+\.\d+\.\d+$", topic)
            self.assertNotIn("name", fields, f"{topic} still poses as a skill")
            self.assertNotIn("description", fields, topic)

    def test_read_returns_the_body_without_frontmatter(self):
        body, error = self.guide.read("ledger")
        self.assertIsNone(error)
        self.assertNotIn("topic: ledger", body)
        self.assertIn("# riel-ledger", body)

    def test_read_slices_one_section(self):
        body, _ = self.guide.read("ledger")
        chunk, error = self.guide.read("ledger", "The three registers")
        self.assertIsNone(error)
        self.assertLess(len(chunk), len(body))
        self.assertTrue(chunk.startswith("## "))
        self.assertEqual([line for line in chunk.splitlines() if line.startswith("## ")], ["## The three registers"])

    def test_unknown_topic_errors_with_the_list(self):
        body, error = self.guide.read("nope")
        self.assertIsNone(body)
        self.assertIn("unknown topic", error["error"])
        self.assertEqual(sorted(error["topics"]), sorted(self.guide.topics()))

    def test_unknown_section_errors_with_the_headings(self):
        body, error = self.guide.read("ledger", "no such heading")
        self.assertIsNone(body)
        self.assertIn("no section matching", error["error"])
        self.assertTrue(error["sections"])
        self.assertTrue(all(s for s in error["sections"]))

    def test_schema_assigns_a_topic_per_shipped_guide(self):
        schema = next(s for s in self.schemas.SCHEMAS if s["name"] == "riel_guide")
        described = schema["parameters"]["properties"]["topic"]["description"]
        for topic in self.guide.topics():
            self.assertIn(topic, described, f"the schema does not name the topic {topic}")


class GuideHandlerTest(unittest.TestCase):
    """The handler: the same envelope as every other tool, and no exception."""

    @classmethod
    def setUpClass(cls):
        cls.tools = load_module("riel_plugin_tools_guide", os.path.join(PLUGIN, "tools.py"))

    def payload(self, args):
        raw = self.tools.riel_guide(args)
        self.assertIsInstance(raw, str, "handlers must return a JSON string")
        return json.loads(raw)

    def test_no_topic_is_the_index(self):
        result = self.payload({})
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(os.path.isdir(result["worktree"]), result["worktree"])
        for topic in result["topics"]:
            self.assertIn(f"- {topic} —", result["stdout"])
        self.assertTrue(result["bytes"])

    def test_a_topic_returns_the_guide(self):
        result = self.payload({"topic": "contract"})
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["topic"], "contract")
        self.assertIn("mermaid", result["content"])
        self.assertEqual(result["content"], result["stdout"])
        self.assertEqual(result["bytes"], len(result["content"]))

    def test_a_section_returns_just_that_slice(self):
        whole = self.payload({"topic": "ledger"})
        slice_ = self.payload({"topic": "ledger", "section": "Pitfalls"})
        self.assertTrue(slice_["passed"], slice_)
        self.assertLess(slice_["bytes"], whole["bytes"])
        self.assertEqual(slice_["section"], "Pitfalls")
        self.assertIn("## Pitfalls", slice_["content"])

    def test_unknown_topic_is_a_structured_error(self):
        result = self.payload({"topic": "no-such-topic"})
        self.assertFalse(result["passed"])
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("unknown topic", result["error"])
        self.assertTrue(result["topics"])
        self.assertIn("hint", result)

    def test_unknown_section_is_a_structured_error(self):
        result = self.payload({"topic": "ledger", "section": "no such heading"})
        self.assertFalse(result["passed"])
        self.assertIn("no section matching", result["error"])
        self.assertTrue(result["sections"])

    def test_the_guide_needs_no_worktree_state(self):
        """The prose ships with the package: a call outside any worktree works."""
        result = self.payload({"topic": "protocol", "worktree": "/tmp"})
        self.assertTrue(result["passed"], result)

    def test_an_empty_worktree_with_no_repo_still_answers(self):
        """A bare `/tmp` has no `.riel/`: the guide does not care."""
        result = self.payload({"topic": "delegate", "worktree": "/tmp"})
        self.assertEqual(result["bytes"], len(result["content"]))
        self.assertIn("delegat", result["content"].lower())


if __name__ == "__main__":
    unittest.main()
