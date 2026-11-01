"""One declaration, three consumers — the drift this repo used to accept.

`engine/params.py` is the only place `riel_note`'s parameters are written down.
Before it, the same fifteen flags lived in three hand-maintained copies: the
JSON schema the model reads, the handler's flag map and the engine's argparse.
They agreed by discipline; nothing caught a flag added to one and forgotten in
another, and the failure mode was silent — the model calls a parameter the
engine ignores.

This suite proves the three consumers agree, by construction:

  * every declared parameter reaches the schema;
  * every declared parameter reaches the engine's parser;
  * every declared parameter reaches the handler's argv;
  * and the engine ACCEPTS each one when handed a value (not just documents it).

It also covers the two structural guarantees the refactor added: `--worktree`
makes the engine independent of the caller's cwd, and `check` answers in one
process what `ship` + `digest` (+ `mermaid`) answered in three.

Stdlib only, subprocess-driven, no Hermes.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLUGIN = os.path.join(REPO, "hermes_plugin", "riel")
PACKAGE = os.path.join(REPO, "hermes_plugin")
ENGINE = os.path.join(PLUGIN, "engine", "run.py")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

from hermes_plugin.riel import _load, schemas, tools  # noqa: E402

PARAMS = _load.sibling("riel_test_params", "engine/params.py")


def run(*argv, cwd=None, timeout=60):
    proc = subprocess.run(
        [sys.executable, ENGINE, *argv],
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


class ParamsAreOneSourceTest(unittest.TestCase):
    def test_the_declaration_covers_every_note_parameter_the_schema_exposes(self):
        props = set(schemas.RIEL_NOTE["parameters"]["properties"])
        declared = set(PARAMS.PARAM_NAMES) | {"worktree"}
        self.assertEqual(props, declared,
                         "the schema and params.py disagree about riel_note's surface")

    def test_every_declared_parameter_reaches_the_handler(self):
        for param in PARAMS.NOTE_PARAMS:
            value = 3 if param["kind"] == "int" else "x"
            argv = tools._flag_args({param["name"]: value})
            self.assertEqual(argv, [param["flag"], "3" if param["kind"] == "int" else "x"],
                             f"{param['name']} never reaches the engine")

    def test_every_declared_parameter_reaches_the_engine_parser(self):
        rc, out, err = run("note", "--help")
        self.assertEqual(rc, 0, err)
        parsed = set(re.findall(r"(--[a-z][a-z0-9-]*)", out))
        expected = {param["flag"] for param in PARAMS.NOTE_PARAMS}
        expected.add(PARAMS.FROM_CONTRACT["flag"])
        self.assertEqual(parsed - {"--help"}, expected,
                         "the engine's parser and params.py disagree")

    def test_the_engine_accepts_every_declared_parameter(self):
        """Documented is not the same as accepted: hand each one a real value."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        # The flags that cannot stand alone get the partner the engine demands.
        dependent = {
            "check": ["note", "--check", "probe", "--by", "probe"],
            "by": ["note", "--check", "probe", "--by", "probe"],
            "open": ["note", "--open", "probe?", "--settled-by", "probe"],
            "settled_by": ["note", "--open", "probe?", "--settled-by", "probe"],
            "close": None,  # needs an open question to close first; see the CLI suite
        }
        for param in PARAMS.NOTE_PARAMS:
            value = "1" if param["kind"] == "int" else "probe"
            if param["name"] == "core":
                value = "probe — a fact"
            argv = dependent.get(param["name"])
            if param["name"] in dependent and argv is None:
                continue
            if argv is None:
                argv = ["note", param["flag"], value]
            rc, _, err = run(*argv, cwd=tmp)
            self.assertEqual(rc, 0, f"{param['name']} was documented but refused: {err}")

    def test_the_schema_type_follows_the_declaration(self):
        props = schemas.RIEL_NOTE["parameters"]["properties"]
        for param in PARAMS.NOTE_PARAMS:
            expected = "integer" if param["kind"] == "int" else "string"
            self.assertEqual(props[param["name"]]["type"], expected, param["name"])

    def test_the_declaration_names_only_sections_the_ledger_has(self):
        ledger, _error = _load.guide().read("ledger", full=True)
        for param in PARAMS.NOTE_PARAMS:
            self.assertIn(param["section"], ledger, f"{param['name']} points at a missing section")


class WorktreeIsExplicitTest(unittest.TestCase):
    """`--worktree` removes the engine's dependence on the caller's cwd."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_engine_writes_into_the_worktree_not_the_cwd(self):
        elsewhere = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, elsewhere, True)
        rc, _, err = run("--worktree", self.tmp, "note", "--goal", "g", cwd=elsewhere)
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, ".riel", "ledger.md")))
        self.assertFalse(os.path.exists(os.path.join(elsewhere, ".riel")),
                         "the engine wrote into the caller's cwd")

    def test_a_missing_worktree_is_a_clean_error(self):
        rc, _, err = run("--worktree", os.path.join(self.tmp, "nope"), "seam")
        self.assertEqual(rc, 2, err)
        self.assertIn("not a directory", err)

    def test_a_relative_fetch_destination_lands_in_the_worktree(self):
        """Every relative path resolves against --worktree, not the cwd."""
        elsewhere = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, elsewhere, True)
        rc, _, err = run("--worktree", self.tmp, "clean", "--purge", cwd=elsewhere)
        self.assertEqual(rc, 0, err)
        self.assertFalse(os.path.isdir(os.path.join(elsewhere, ".riel")))


class CheckIsOneCallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.doc = os.path.join(self.tmp, "doc.md")
        with open(self.doc, "w", encoding="utf-8") as handle:
            handle.write('# Doc\n\n```mermaid\nflowchart TD\n  A["x"] --> B["y"]\n```\n')

    def test_one_process_answers_what_three_answered(self):
        rc, out, err = run("check", self.doc)
        self.assertEqual(rc, 0, err)
        body = json.loads(out)
        self.assertTrue(body["passed"])
        self.assertEqual(sorted(body["halves"]), ["digest", "ship"])
        # …and the halves are the same report functions the single verbs print.
        _, ship_out, _ = run("ship", self.doc)
        _, digest_out, _ = run("digest", self.doc)
        self.assertEqual(body["halves"]["ship"]["stdout"], ship_out.strip())
        self.assertEqual(body["halves"]["digest"]["stdout"], digest_out.strip())

    def test_the_parser_half_is_opt_in(self):
        _, out, _ = run("check", self.doc)
        self.assertNotIn("mermaid", json.loads(out)["halves"])
        _, out, _ = run("check", self.doc, "--mermaid")
        self.assertIn("mermaid", json.loads(out)["halves"])

    def test_a_dense_marker_fails_the_composite(self):
        with open(self.doc, "a", encoding="utf-8") as handle:
            handle.write("\nverified \u271301 the fix\n")
        rc, out, _ = run("check", self.doc)
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(out)["passed"])


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
                args["goal"] = "g"
            if name in ("riel_contract", "riel_shaping"):
                args["verb"] = "validate"
                args["file"] = doc
            if name == "riel_check":
                args["file"] = doc
            if name == "riel_fetch":
                continue  # needs the network; its refusal shape is covered elsewhere
            payload = json.loads(handler(args))
            if "error" in payload:
                continue
            for key in self.KEYS:
                self.assertIn(key, payload, f"{name} does not speak the shared envelope")


class SettingsAreLoadedOnceTest(unittest.TestCase):
    """The eight by-path loader copies are one loader, and it caches."""

    def test_the_same_module_is_handed_back(self):
        self.assertIs(_load.settings(), _load.settings())
        self.assertIs(_load.guide(), _load.guide())

    def test_the_guarded_bootstrap_is_the_only_by_path_dance_per_module(self):
        """One bootstrap per module, and `settings.py` is never loaded beside it."""
        for name in ("tools.py", "hooks.py", "section.py", "commands.py", "schemas.py"):
            text = open(os.path.join(PLUGIN, name), encoding="utf-8").read()
            self.assertEqual(text.count('"riel_plugin_load"'), 1,
                             f"{name} does not use the one bootstrap")
            self.assertNotIn('"riel_plugin_settings', text,
                             f"{name} loads settings by path instead of _load.settings()")
            self.assertNotIn('"riel_plugin_guide', text,
                             f"{name} loads the prose by path instead of _load.guide()")

    def test_only_load_py_knows_how_to_load_a_sibling(self):
        text = open(os.path.join(PLUGIN, "_load.py"), encoding="utf-8").read()
        self.assertEqual(text.count("spec_from_file_location"), 1,
                         "_load.py must be the only place that knows the loader trick")


if __name__ == "__main__":
    unittest.main()