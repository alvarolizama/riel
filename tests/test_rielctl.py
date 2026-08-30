"""Regression tests for skills/riel-cli/scripts/rielctl.

Stdlib-only (unittest). Each test runs the CLI in a fresh tempdir via
subprocess so we exercise exactly what an agent would invoke.

Run:
    python3 -m unittest discover -s tests -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
RIELCTL = os.path.join(REPO, "skills", "riel-cli", "scripts", "rielctl")
BRIEFS_TEMPLATES = os.path.join(REPO, "skills", "riel-briefs", "templates")


def run(*argv, cwd=None):
    """Run rielctl and return (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, RIELCTL] + list(argv),
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


if __name__ == "__main__":
    unittest.main()
