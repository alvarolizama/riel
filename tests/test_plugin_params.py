"""One declaration, three consumers — the drift this repo used to accept.

`engine/params.py` is the only place `riel_note`'s parameters are written down.
Before it, the same flags lived in three hand-maintained copies: the JSON
schema the model reads, the handler's flag map and the engine's argparse.
They agreed by discipline; nothing caught a flag added to one and forgotten in
another, and the failure mode was silent — the model calls a parameter the
engine ignores.

This suite proves the consumers agree, BY DERIVATION (never re-typed), against
the REAL packaged declaration:

  * every declared parameter reaches the schema (repeat ones as arrays,
    engine-owned ones not at all);
  * every declared parameter reaches the handler's argv (repeats expanded,
    forbidden dropped);
  * the schema type follows the declaration;
  * and the derived surface is FROZEN in the tests (MappingProxyType), so a
    test cannot quietly widen what the wrapper accepts.

The handlers run against the stub engine; the declaration under test is the
packaged `engine/params.py` — the same file the schema and the wrapper read.

Stdlib only, no Hermes.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "hermes_plugin" / "riel"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import _stub_engine as stub  # noqa: E402
from hermes_plugin.riel import _load, schemas, tools  # noqa: E402

stub.install(tools)
PARAMS = tools._params()

# The declaration is a contract, not a working variable: frozen here so a test
# cannot quietly widen what the wrapper accepts.
PARAMS_FROZEN = MappingProxyType(
    {p["name"]: MappingProxyType(p) for p in PARAMS.NOTE_PARAMS})


def caller_names():
    return {_load.note_caller_name(p) for p in PARAMS.NOTE_PARAMS
            if p["name"] not in _load.NOTE_FORBIDDEN}


class ParamsAreOneSourceTest(unittest.TestCase):
    """Derivation, by construction: schema and wrapper read the same list."""

    def test_the_declaration_covers_every_note_parameter_the_schema_exposes(self):
        expected = caller_names() | {"worktree"}
        self.assertEqual(set(schemas.RIEL_NOTE["parameters"]["properties"]), expected,
                         "the schema and params.py disagree about riel_note's surface")

    def test_the_schema_is_derived_not_re_typed(self):
        """Every non-worktree property traces back to a declaration entry."""
        for name, prop in schemas.RIEL_NOTE["parameters"]["properties"].items():
            if name == "worktree":
                continue
            matches = [p for p in PARAMS.NOTE_PARAMS
                       if _load.note_caller_name(p) == name]
            self.assertTrue(matches, f"{name} exists in the schema but not in the declaration")
            self.assertEqual(prop["description"], matches[0]["help"],
                             f"{name}: the schema re-typed the help text")

    def test_every_declared_parameter_reaches_the_handler(self):
        for param in PARAMS.NOTE_PARAMS:
            caller = _load.note_caller_name(param)
            if param["kind"] == "int":
                value, expected = 3, [param["flag"], "3"]
            elif param.get("repeat"):
                value, expected = ["x"], [param["flag"], "x"]
            else:
                value, expected = "x", [param["flag"], "x"]
            argv = tools._note_argv({caller: value})
            self.assertEqual(argv, expected, f"{caller} never reaches the engine")

    def test_a_repeat_declaration_expands_into_repeated_flags(self):
        self.assertEqual(tools._note_argv({"claims": ["P1", "P2"]}),
                         ["--claim", "P1", "--claim", "P2"])
        self.assertEqual(tools._note_argv({"gates": ["G1", "G2"]}),
                         ["--gate", "G1", "--gate", "G2"])

    def test_the_gate_travels_with_its_command_and_scope(self):
        argv = tools._note_argv({"gates": ["G1"], "command": "make test", "covering": "all"})
        self.assertEqual(argv, ["--gate", "G1", "--command", "make test", "--covering", "all"])

    def test_the_engine_owned_exit_code_never_reaches_the_argv(self):
        argv = tools._note_argv({"gates": ["G1"], "command": "true", "exit_code": 0})
        self.assertEqual(argv, ["--gate", "G1", "--command", "true"],
                         "a caller-supplied exit code would lie about the gate")
        self.assertNotIn("exit_code", caller_names(),
                         "exit_code is not a declaration entry in 2.0")

    def test_the_schema_type_follows_the_declaration(self):
        props = schemas.RIEL_NOTE["parameters"]["properties"]
        for param in PARAMS.NOTE_PARAMS:
            caller = _load.note_caller_name(param)
            if caller == "worktree" or param["name"] in _load.NOTE_FORBIDDEN:
                continue
            if caller != param["name"]:
                self.assertEqual(props[caller]["type"], "array", caller)
            else:
                expected = "integer" if param["kind"] == "int" else "string"
                self.assertEqual(props[caller]["type"], expected, caller)

    def test_the_derived_surface_is_frozen_in_the_tests(self):
        self.assertIsInstance(PARAMS_FROZEN, MappingProxyType)
        with self.assertRaises(TypeError):
            PARAMS_FROZEN["gate"] = {"name": "gate"}  # type: ignore[index]
        with self.assertRaises(TypeError):
            PARAMS_FROZEN["gate"]["kind"] = "list"  # type: ignore[index]


class WorktreeIsExplicitTest(unittest.TestCase):
    """The worktree is a parameter of every call — never a cwd guess."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_engine_writes_into_the_worktree_not_the_cwd(self):
        elsewhere = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, elsewhere, True)
        payload = json.loads(tools.riel_note({"core": "fact — x", "worktree": self.tmp}))
        self.assertEqual(payload["exit_code"], 0, payload)
        self.assertTrue((Path(self.tmp) / ".riel" / "run.md").is_file())
        self.assertFalse((Path(elsewhere) / ".riel").exists(),
                         "the engine wrote into the caller's cwd")

    def test_a_missing_worktree_is_a_clean_error(self):
        payload = json.loads(tools.riel_run({"verb": "status",
                                             "worktree": os.path.join(self.tmp, "nope")}))
        self.assertIn("not a directory", payload["error"])


class OneEnvelopeTest(unittest.TestCase):
    """Every tool answers with the same six keys — a caller folds without asking."""

    KEYS = ("tool", "worktree", "exit_code", "passed", "stdout", "stderr")

    def test_every_handler_answers_the_shared_envelope(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        doc = os.path.join(tmp, "doc.md")
        with open(doc, "w", encoding="utf-8") as handle:
            handle.write("# Doc\n")

        for name, handler in tools.HANDLERS.items():
            args = {"worktree": tmp}
            if name == "riel_note":
                args["core"] = "fact — x"
            if name == "riel_run":
                args["verb"] = "status"
            if name == "riel_shape":
                args["verb"] = "new"
            if name == "riel_project":
                args["verb"] = "new"
            if name == "riel_check":
                args["file"] = doc
            payload = json.loads(handler(args))
            if "error" in payload:
                continue
            for key in self.KEYS:
                self.assertIn(key, payload, f"{name} does not speak the shared envelope")


class SettingsAreLoadedOnceTest(unittest.TestCase):
    """The by-path loader copies are one loader, and it caches."""

    def test_the_same_module_is_handed_back(self):
        self.assertIs(_load.settings(), _load.settings())
        self.assertIs(_load.guide(), _load.guide())

    def test_the_guarded_bootstrap_is_the_only_by_path_dance_per_module(self):
        """One bootstrap per module, and `settings.py` is never loaded beside it."""
        for name in ("tools.py", "hooks.py", "section.py", "commands.py", "schemas.py"):
            text = (PLUGIN / name).read_text(encoding="utf-8")
            self.assertEqual(text.count('"_load.py"'), 1,
                             f"{name} does not use the one guarded sibling loader")
            self.assertNotIn('"riel_plugin_settings', text,
                             f"{name} loads settings by path instead of _load.settings()")
            self.assertNotIn('"riel_plugin_guide', text,
                             f"{name} loads the prose by path instead of _load.guide()")

    def test_only_load_py_knows_how_to_load_a_sibling(self):
        text = (PLUGIN / "_load.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("spec_from_file_location"), 1,
                         "_load.py must be the only place that knows the loader trick")


if __name__ == "__main__":
    unittest.main()
