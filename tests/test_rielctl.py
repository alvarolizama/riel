"""Regression tests for skills/riel-cli/scripts/rielctl.

Stdlib-only (unittest). Each test runs the CLI in a fresh tempdir via
subprocess so we exercise exactly what an agent would invoke.

Run:
    python3 -m unittest discover -s tests -v
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
RIELCTL = os.path.join(REPO, "skills", "riel-cli", "scripts", "rielctl")
BRIEFS_TEMPLATES = os.path.join(REPO, "skills", "riel-briefs", "templates")
EXTRACT_MERMAID = os.path.join(REPO, "scripts", "extract-mermaid.py")


def run(*argv, cwd=None):
    """Run rielctl and return (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, RIELCTL] + list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_script(script, *argv, cwd=None):
    """Run a repo script and return (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, script] + list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rielctl-test-")
        self.cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ledger_path(self):
        return os.path.join(self.tmp, ".riel", "ledger.md")

    def read_ledger(self):
        with open(self.ledger_path(), encoding="utf-8") as fh:
            return fh.read()


class NoteTests(TempDirTest):
    def test_open_writes_all_sections(self):
        rc, out, _ = run(
            "note", "--goal", "ship login", "--phase", "F1",
            "--source", "todo:login", "--next", "read spec",
        )
        self.assertEqual(rc, 0)
        body = self.read_ledger()
        for marker in (
            "## Goal\nship login",
            "## Source\ntodo:login",
            "## Phase\nF1",
            "## Claims",
            "## Core",
            "## Verified",
            "## Open",
            "## Next\nread spec",
        ):
            self.assertIn(marker, body, "missing: %r" % marker)

    def test_versions_of_sections_separated_by_blank_lines(self):
        run("note", "--goal", "g", "--source", "s", "--phase", "F1",
            "--next", "n")
        body = self.read_ledger()
        # every section header is followed or preceded by a blank line
        # (i.e., no two headings are adjacent with no breathing room)
        self.assertNotIn("\n## Source\ntodo:login\n## Phase\n", body)
        self.assertNotIn("\n## Phase\nF1\n## Claims\n", body)

    def test_claims_number_sequentially(self):
        run("note", "--goal", "g", "--next", "n")
        run("note", "--claim", "first", "--verify-with", "cmd")
        run("note", "--claim", "second", "--verify-with", "cmd")
        body = self.read_ledger()
        self.assertIn("- P1: first", body)
        self.assertIn("- P2: second", body)

    def test_checks_number_sequentially_with_confidence(self):
        run("note", "--goal", "g", "--next", "n")
        run("note", "--check", "compile", "--by", "mix compile",
            "--covering", "lib")
        run("note", "--check", "test", "--by", "mix test",
            "--covering", "unit", "--confidence", "15")
        verified = self.read_ledger()
        self.assertIn("✓01 compile", verified)
        self.assertIn("✓02 test", verified)
        self.assertIn("confidence 15/20", verified)

    def test_core_max_two_without_slot(self):
        run("note", "--goal", "g", "--next", "n")
        run("note", "--core", "A — one")
        run("note", "--core", "B — two")
        rc, _, err = run("note", "--core", "C — three")
        self.assertEqual(rc, 2)
        self.assertIn("Core is full", err)

    def test_core_slot_replaces(self):
        run("note", "--goal", "g", "--next", "n")
        run("note", "--core", "A — one")
        run("note", "--core", "B — two")
        rc, _, _ = run("note", "--core", "B — replaced", "--core-slot", "1")
        self.assertEqual(rc, 0)
        body = self.read_ledger()
        self.assertIn("B — replaced", body)
        self.assertNotIn("B — two", body)

    def test_core_requires_dash_separator(self):
        run("note", "--goal", "g", "--next", "n")
        rc, _, err = run("note", "--core", "noseparator")
        self.assertEqual(rc, 2)
        self.assertIn("name", err)

    def test_check_requires_by(self):
        run("note", "--goal", "g", "--next", "n")
        rc, _, err = run("note", "--check", "orphan")
        self.assertEqual(rc, 2)
        self.assertIn("--by", err)

    def test_open_requires_settled_by(self):
        run("note", "--goal", "g", "--next", "n")
        rc, _, err = run("note", "--open", "orphan question")
        self.assertEqual(rc, 2)
        self.assertIn("--settled-by", err)

    def test_close_removes_question(self):
        run("note", "--goal", "g", "--next", "n")
        run("note", "--open", "q1", "--settled-by", "t")
        run("note", "--open", "q2", "--settled-by", "t")
        rc, _, _ = run("note", "--close", "1", "--check", "settled",
                       "--by", "t")
        self.assertEqual(rc, 0)
        body = self.read_ledger()
        self.assertNotIn("q1", body)
        self.assertIn("q2", body)

    def test_close_missing_errors(self):
        run("note", "--goal", "g", "--next", "n")
        rc, _, err = run("note", "--close", "99")
        self.assertEqual(rc, 2)
        self.assertIn("no such open question", err)

    def test_close_requires_check(self):
        # a question is closed against a checkpoint, never dropped silently
        run("note", "--goal", "g", "--next", "n")
        run("note", "--open", "q1", "--settled-by", "t")
        rc, _, err = run("note", "--close", "1")
        self.assertEqual(rc, 2)
        self.assertIn("requires --check", err)
        # nothing was written — the open question is untouched
        self.assertIn("q1", self.read_ledger())

    def test_close_with_check_records_checkpoint(self):
        run("note", "--goal", "g", "--next", "n")
        run("note", "--open", "q1", "--settled-by", "t")
        rc, out, _ = run("note", "--close", "1", "--check", "settled",
                         "--by", "t")
        self.assertEqual(rc, 0, out)
        body = self.read_ledger()
        self.assertNotIn("q1", body)
        self.assertIn("✓01 settled", body)


class TodoTests(TempDirTest):
    def test_todo_without_ledger_errors(self):
        rc, _, err = run("todo")
        self.assertEqual(rc, 1)
        self.assertIn("no ledger", err)

    def test_todo_full_mirror(self):
        run("note", "--goal", "ship login", "--phase", "F1",
            "--next", "wire controller")
        run("note", "--claim", "login works", "--verify-with", "mix test")
        run("note", "--open", "link encodes?", "--settled-by", "property test")
        run("note", "--check", "compiles", "--by", "mix compile",
            "--covering", "lib")
        rc, out, _ = run("todo")
        self.assertEqual(rc, 0, out)
        items = json.loads(out)
        by_id = {i["id"]: i for i in items}
        self.assertEqual(by_id["goal"]["status"], "pending")
        self.assertIn("ship login", by_id["goal"]["content"])
        self.assertEqual(by_id["phase"]["parent"], "goal")
        self.assertEqual(by_id["next"]["status"], "in_progress")
        self.assertEqual(by_id["open-1"]["status"], "pending")
        self.assertTrue(by_id["open-1"]["content"].startswith("OPEN 01"))
        self.assertEqual(by_id["claim-1"]["status"], "pending")
        self.assertTrue(by_id["claim-1"]["content"].startswith("CLAIM:"))
        self.assertEqual(by_id["done-1"]["status"], "completed")
        self.assertTrue(by_id["done-1"]["content"].startswith("DONE 01"))
        self.assertEqual(
            sum(1 for i in items if i["status"] == "in_progress"), 1)

    def test_todo_next_empty_warns(self):
        run("note", "--goal", "g")
        rc, out, err = run("todo")
        self.assertEqual(rc, 0)
        self.assertIn("no in_progress", err)
        items = json.loads(out)
        self.assertEqual([i["id"] for i in items], ["goal"])


class SeamResumeShipTests(TempDirTest):
    def test_seam_without_ledger_errors(self):
        rc, _, err = run("seam")
        self.assertEqual(rc, 1)
        self.assertIn("no ledger", err)

    def test_seam_warns_no_checkpoints(self):
        run("note", "--goal", "g", "--next", "n")
        rc, out, _ = run("seam")
        self.assertEqual(rc, 0)
        self.assertIn("No ✓NN yet", out)

    def test_resume_reports_four_steps(self):
        run("note", "--goal", "g", "--next", "n")
        rc, out, _ = run("resume")
        self.assertEqual(rc, 0)
        for tag in ("[1/4]", "[2/4]", "[3/4]", "[4/4]"):
            self.assertIn(tag, out)

    def test_ship_clean(self):
        path = os.path.join(self.tmp, "ok.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("hello\n")
        rc, out, _ = run("ship", path)
        self.assertEqual(rc, 0)
        self.assertIn("clean", out)

    def test_ship_detects_dense_marker(self):
        path = os.path.join(self.tmp, "bad.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("verified ✓01 the fix\n")
        rc, out, _ = run("ship", path)
        self.assertEqual(rc, 1)
        self.assertIn("dense markers", out)

    def test_ship_missing_file(self):
        rc, _, err = run("ship", os.path.join(self.tmp, "nope.md"))
        self.assertEqual(rc, 1)
        self.assertIn("cannot read", err)


class CLITests(TempDirTest):
    def test_version(self):
        rc, out, _ = run("--version")
        self.assertEqual(rc, 0)
        with open(RIELCTL, encoding="utf-8") as fh:
            declared = re.search(r'VERSION = "([^"]+)"', fh.read()).group(1)
        self.assertIn(declared, out)


class GraphAndValidateTests(TempDirTest):
    VALID = """# Task: x

## Objective
We need x

## Context
c

## Constraints
- r

## Pre-registered claims
- P1: a — verify with: true

## Execution graph

```mermaid
flowchart TD
  S1["RUN ls"] --> G1{"ok?"}
  G1 -->|yes| END([Done])
  G1 -->|no| S1
```

## Verification gates
g

## Deliverable
d

## DO NOT
- x
"""

    def _write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_rejects_non_verb_execution_node(self):
        bad = self.VALID.replace('S1["RUN ls"]', 'S1["Fetch it"]')
        rc, out, _ = run("brief", "validate", self._write("b.md", bad))
        self.assertEqual(rc, 1)
        self.assertIn("closed verb", out)

    def test_rejects_br_tag(self):
        bad = self.VALID.replace('{"ok?"}', '{"ok?<br/>x"}')
        rc, out, _ = run("brief", "validate", self._write("b.md", bad))
        self.assertEqual(rc, 1)
        self.assertIn("<br/>", out)

    def test_rejects_style_in_execution_graph(self):
        bad = self.VALID.replace('  G1 -->|no| S1\n',
                                 '  G1 -->|no| S1\n  style S1 fill:#f00\n')
        rc, out, _ = run("brief", "validate", self._write("b.md", bad))
        self.assertEqual(rc, 1)
        self.assertIn("style", out)

    def test_rejects_tool_name_in_label(self):
        bad = self.VALID.replace('S1["RUN ls"]', 'S1["RUN read_file x"]')
        rc, out, _ = run("brief", "validate", self._write("b.md", bad))
        self.assertEqual(rc, 1)
        self.assertIn("tool name", out)

    def test_warns_loop_without_counter(self):
        rc, out, err = run("brief", "validate",
                           self._write("ok.md", self.VALID))
        self.assertEqual(rc, 0, out)
        self.assertIn("WARN", err)

    def test_digest_lists_structure(self):
        path = self._write("ok.md", self.VALID)
        rc, out, _ = run("brief", "digest", path)
        self.assertEqual(rc, 0, out)
        for marker in ("Elements", "Edges", "Branches", "Entry", "Terminals",
                       "S1", "G1", "END"):
            self.assertIn(marker, out)

    def test_digest_writes_output_file(self):
        path = self._write("ok.md", self.VALID)
        outp = os.path.join(self.tmp, "digest.txt")
        rc, _, _ = run("brief", "digest", path, "-o", outp)
        self.assertEqual(rc, 0)
        with open(outp, encoding="utf-8") as fh:
            self.assertIn("Elements", fh.read())

    def test_digest_without_graph_errors(self):
        path = self._write("plain.md", "# Task: x\n\nno graph here\n")
        rc, _, err = run("brief", "digest", path)
        self.assertEqual(rc, 1)
        self.assertIn("no mermaid", err)

    def test_digest_top_level_any_file(self):
        path = self._write("ok.md", self.VALID)
        rc, out, _ = run("digest", path)
        self.assertEqual(rc, 0, out)
        self.assertIn("Elements", out)

    def test_rejects_ask_without_trigger(self):
        bad = self.VALID.replace('S1["RUN ls"]',
                                 'S1["ASK should we proceed?"]')
        rc, out, _ = run("brief", "validate", self._write("b.md", bad))
        self.assertEqual(rc, 1)
        self.assertIn("ASK", out)

    def test_accepts_ask_with_trigger(self):
        ok = self.VALID.replace('S1["RUN ls"]',
                                'S1["ASK[irreversible] proceed?"]')
        rc, out, err = run("brief", "validate", self._write("ok.md", ok))
        # the ASK node is valid; only the (unrelated) no-RUN-gate issue may fire
        self.assertNotIn("must start with its trigger", out + err)


class BriefTests(TempDirTest):
    MINIMAL_VALID = """# Task: x

## Objective
We need x

## Context
c

## Constraints
- r

## Pre-registered claims
- P1: a — verify with: true

## Execution graph

```mermaid
flowchart TD
  S1["RUN ls"] --> G1{"ok?"}
  G1 -->|yes| END([Done])
  G1 -->|no| S1
```

## Verification gates
g

## Deliverable
d

## DO NOT
- x
"""

    def _write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_brief_new_lists_all_builtin(self):
        rc, out, _ = run("brief", "new", "--list")
        self.assertEqual(rc, 0)
        for name in ("feature", "bugfix", "refactor", "research",
                     "writing", "packet"):
            self.assertIn(name, out)

    def test_brief_new_substitutes_params_leaves_rest(self):
        rc, out, err = run(
            "brief", "new", "--type", "feature",
            "--param", "name=login fix",
            "--param", "one_sentence=fix login",
        )
        self.assertEqual(rc, 0, err)
        self.assertIn("# Task: login fix", out)
        self.assertIn("We need fix login.", out)
        self.assertIn("{{repo_path}}", out)  # left for manual fill

    def test_brief_new_strict_fails_on_missing_param(self):
        rc, _, err = run(
            "brief", "new", "--type", "feature",
            "--strict", "--param", "name=x",
        )
        self.assertEqual(rc, 2)
        self.assertIn("missing --param", err)

    def test_brief_new_strict_message_not_quoted(self):
        # the message is a plain sentence, not repr()'d
        rc, _, err = run(
            "brief", "new", "--type", "feature",
            "--strict", "--param", "name=x",
        )
        self.assertEqual(rc, 2)
        self.assertNotIn("'missing --param", err)

    def test_brief_new_output_writes_file(self):
        out_path = os.path.join(self.tmp, "packet.md")
        rc, _, err = run(
            "brief", "new", "--type", "feature",
            "--param", "name=reset flow",
            "--param", "one_sentence=add reset",
            "-o", out_path,
        )
        self.assertEqual(rc, 0, err)
        with open(out_path, encoding="utf-8") as fh:
            self.assertIn("# Task: reset flow", fh.read())

    def test_brief_new_finds_project_template(self):
        tdir = os.path.join(self.tmp, ".riel", "templates")
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, "custom.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# Task: {{name}}\n")
        rc, out, err = run("brief", "new", "--type", "custom",
                           "--param", "name=proj")
        self.assertEqual(rc, 0, err)
        self.assertIn("# Task: proj", out)

    def test_brief_new_unknown_type_errors(self):
        rc, _, err = run("brief", "new", "--type", "no-such")
        self.assertEqual(rc, 2)
        self.assertIn("no template", err)

    def test_brief_validate_accepts_minimal_valid(self):
        path = self._write("ok.md", self.MINIMAL_VALID)
        rc, out, _ = run("brief", "validate", path)
        self.assertEqual(rc, 0, out)

    def test_brief_validate_missing_claims(self):
        bad = self.MINIMAL_VALID.replace(
            "\n## Pre-registered claims\n- P1: a — verify with: true\n", "\n"
        )
        path = self._write("bad.md", bad)
        rc, out, _ = run("brief", "validate", path)
        self.assertEqual(rc, 1)
        self.assertIn("Pre-registered claims", out)

    def test_brief_validate_rejects_non_we_need_objective(self):
        bad = self.MINIMAL_VALID.replace("We need x", "Make x better")
        path = self._write("bad.md", bad)
        rc, out, _ = run("brief", "validate", path)
        self.assertEqual(rc, 1)
        self.assertIn("We need", out)

    def test_brief_validate_rejects_out_of_order_sections(self):
        bad = self.MINIMAL_VALID.replace(
            "\n## Context\nc\n\n## Constraints\n- r\n",
            "\n## Constraints\n- r\n\n## Context\nc\n",
        )
        path = self._write("bad.md", bad)
        rc, out, _ = run("brief", "validate", path)
        self.assertEqual(rc, 1)
        self.assertIn("out of order", out)

    def test_brief_validate_builtin_example(self):
        path = os.path.join(BRIEFS_TEMPLATES, "example-password-reset.md")
        rc, out, _ = run("brief", "validate", path)
        self.assertEqual(rc, 0, out)

    def test_brief_validate_builtin_skeletons(self):
        # packet.md is the empty template (Objective = placeholder),
        # so it is intentionally NOT required to validate.
        for name in ("feature", "bugfix", "refactor",
                     "research", "writing"):
            path = os.path.join(BRIEFS_TEMPLATES, name + ".md")
            rc, out, _ = run("brief", "validate", path)
            self.assertEqual(rc, 0, "%s: %s" % (name, out))


class ExtractMermaidTests(TempDirTest):
    def _write(self, name, content):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def test_extracts_blocks_in_order(self):
        md = self._write(
            "doc.md",
            "# t\n\n```mermaid\nflowchart TD\n  A --> B\n```\n\n"
            "prose\n\n```mermaid\nflowchart LR\n  C --> D\n```\n",
        )
        out_dir = os.path.join(self.tmp, "out")
        rc, _, err = run_script(EXTRACT_MERMAID, md, out_dir)
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(os.listdir(out_dir)), ["001.mmd", "002.mmd"])
        with open(os.path.join(out_dir, "001.mmd"), encoding="utf-8") as fh:
            self.assertIn("A --> B", fh.read())

    def test_no_blocks_exits_zero(self):
        md = self._write("plain.md", "just prose, no diagrams\n")
        out_dir = os.path.join(self.tmp, "empty")
        rc, _, _ = run_script(EXTRACT_MERMAID, md, out_dir)
        self.assertEqual(rc, 0)


class ContractSeedTests(TempDirTest):
    CONTRACT = """# Task: x

## Objective
We need the thing to work.

## Context
c

## Constraints
- r

## Pre-registered claims
- P1: a — verify with: true
- P2: b — verify with: cmd

## Execution graph

```mermaid
flowchart TD
  F1["EDIT a.ex — x"] --> F2["RUN test"]
  F2 --> G1{"green?"}
  G1 -->|no| F1
  G1 -->|yes| END([Done])
```

## Verification gates
g

## Deliverable
d

## DO NOT
- x
"""

    def _write_contract(self, content=None):
        d = os.path.join(self.tmp, ".riel")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "contract.md"), "w", encoding="utf-8") as fh:
            fh.write(content if content is not None else self.CONTRACT)

    def test_seeds_goal_phase_claims_next(self):
        self._write_contract()
        rc, _, err = run("note", "--from-contract")
        self.assertEqual(rc, 0, err)
        body = self.read_ledger()
        self.assertIn("## Goal\nWe need the thing to work.", body)
        self.assertIn("## Phase\nEDIT a.ex — x", body)
        self.assertIn("- P1: a — verify with: true", body)
        self.assertIn("- P2: b — verify with: cmd", body)
        # entry node ignores the back-edge F1 <- G1
        self.assertIn("## Next\nEDIT a.ex — x", body)

    def test_missing_contract_errors(self):
        rc, _, err = run("note", "--from-contract")
        self.assertEqual(rc, 2)
        self.assertIn("no contract found", err)

    def test_explicit_flag_overrides_seed(self):
        self._write_contract()
        run("note", "--from-contract", "--goal", "explicit")
        self.assertIn("## Goal\nexplicit", self.read_ledger())

    def test_seed_idempotent_on_claims(self):
        self._write_contract()
        run("note", "--from-contract")
        run("note", "--from-contract")
        self.assertEqual(
            self.read_ledger().count("- P1: a — verify with: true"), 1)

    def test_from_contract_custom_path(self):
        path = os.path.join(self.tmp, "c.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.CONTRACT)
        rc, _, _ = run("note", "--from-contract", path)
        self.assertEqual(rc, 0)
        self.assertIn("## Goal\nWe need the thing to work.", self.read_ledger())


class SliceTests(TempDirTest):
    CONTRACT = """# Task: login flow

## Objective
We need the login to validate both providers.

## Context
c

## Constraints
- no new deps

## Pre-registered claims
- P1: both providers validate — verify with: mix test auth_test.exs

## Execution graph

```mermaid
flowchart TD
  F1["EDIT a.ex — x"] --> F2["RUN mix test"]
  F2 --> G1{"green?"}
  G1 -->|no| F1
  G1 -->|yes| END([Done])
```

## Verification gates
g

## Deliverable
d

## DO NOT
- x
"""

    def _contract(self):
        d = os.path.join(self.tmp, ".riel")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "contract.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.CONTRACT)
        return path

    def test_slice_keeps_phase_subgraph_only(self):
        self._contract()
        rc, out, _ = run("brief", "slice", ".riel/contract.md", "--phase", "F2")
        self.assertEqual(rc, 0)
        self.assertIn('F2["RUN mix test"]', out)
        self.assertIn('G1{"green?"}', out)
        self.assertNotIn("F1", out)      # does not cross into the other phase
        self.assertNotIn("|no|", out)    # back-edge to F1 dropped

    def test_slice_default_first_phase(self):
        self._contract()
        rc, out, _ = run("brief", "slice", ".riel/contract.md")
        self.assertEqual(rc, 0)
        self.assertIn('F1["EDIT a.ex — x"]', out)

    def test_slice_output_validates(self):
        self._contract()
        rc, _, _ = run("brief", "slice", ".riel/contract.md",
                       "--phase", "F2", "-o", "mini.md")
        self.assertEqual(rc, 0)
        rc2, out2, _ = run("brief", "validate", "mini.md")
        self.assertEqual(rc2, 0, out2)

    def test_slice_unknown_phase_errors(self):
        self._contract()
        rc, _, err = run("brief", "slice", ".riel/contract.md", "--phase", "F9")
        self.assertEqual(rc, 2)
        self.assertIn("no phase node", err)


if __name__ == "__main__":
    unittest.main()
