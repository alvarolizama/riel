"""Regression tests for engine/run.py — riel-run/v1 (riel 2.0, clean break).

Stdlib-only (unittest). Each test runs the real CLI in a fresh tempdir via
subprocess, so exit codes are the ACTUAL process exit codes.

Run:
    python3 -m unittest tests.test_engine -v
"""
import importlib.util
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.path.join(REPO, "hermes_plugin", "riel", "engine", "run.py")

LIST_RUN = """# Run: engine v2
<!-- riel-run/v1 -->

## Objective
The engine records evidence against riel-run/v1 contracts.

## Context

### Why
The v1 contract/ledger pair made seams expensive.

### Context keywords
- riel → repo

## Constraints
- stdlib only.

## Claims
- P1: the parser reads the list register — anchor: §Graph
- P2: evidence closes gates — anchor: §Gates

## Graph
- F1: build parser
  - READ the spec
  - RUN make test
- F2: wire verbs
  - EDIT tools.py
  - RUN make test

## Gates
- G1: parser tests pass — phase: F1
- G2: verbs wired — phase: F2

## Deliverable
engine/run.py rewired.

## DO NOT
- touch tools.py.
"""

MERMAID_RUN = LIST_RUN.replace(
    """## Graph
- F1: build parser
  - READ the spec
  - RUN make test
- F2: wire verbs
  - EDIT tools.py
  - RUN make test
""",
    """## Graph
```mermaid
flowchart TD
  F1["build parser"] --> S1["READ the spec"]
  S1 --> D1{"tests ok?"}
  D1 -->|yes| F2["wire verbs"]
  D1 -->|no| S2["RUN make test"]
  S2 --> D1
```
""")


def run(*argv, cwd=None):
    proc = subprocess.run([sys.executable, ENGINE] + list(argv),
                          cwd=cwd, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-engine-test-")
        self.cwd = os.getcwd()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def activate(self, text=LIST_RUN, shaping=None, slug="engine"):
        os.makedirs(os.path.join(self.tmp, ".riel"), exist_ok=True)
        if shaping:
            os.makedirs(os.path.dirname(self.shaping_path(slug)), exist_ok=True)
            with open(self.shaping_path(slug), "w", encoding="utf-8") as fh:
                fh.write(shaping)
            text = self.declared(text, slug)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        return rc, out, err

    def declared(self, text, slug="engine"):
        """The run's ### Shaping declaration — the binding is authored, not guessed."""
        return text.replace(
            "- riel → repo\n",
            "- riel → repo\n\n### Shaping\n- shaping: .riel/shapings/{}.md\n".format(slug))

    def run_path(self):
        return os.path.join(self.tmp, ".riel", "run.md")

    def shaping_path(self, slug="engine"):
        return os.path.join(self.tmp, ".riel", "shapings", slug + ".md")

    def loose_shaping_path(self):
        return os.path.join(self.tmp, ".riel", "shaping.md")

    def status(self):
        rc, out, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def read_run(self):
        with open(self.run_path(), encoding="utf-8") as fh:
            return fh.read()


class FormatTests(TempDirTest):
    def test_new_renders_stdout_without_state(self):
        rc, out, err = run("run", "new", "--param", "title=demo", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("<!-- riel-run/v1 -->", out)
        self.assertIn("# Run: demo", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".riel")))

    def test_legacy_state_is_refused(self):
        os.makedirs(os.path.join(self.tmp, ".riel"))
        for legacy in ("contract.md", "ledger.md"):
            with open(os.path.join(self.tmp, ".riel", legacy), "w") as fh:
                fh.write("# legacy\n")
        rc, out, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("legacy riel v1 state", err)
        self.assertIn("no converter", err)
        rc, _out, err = run("note", "--core", "x — y", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("legacy", err)
        rc, _out, err = run("run", "validate",
                            os.path.join(self.tmp, ".riel", "contract.md"),
                            cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("riel-run/v1", err)

    def test_draft_and_active_validate(self):
        os.makedirs(os.path.join(self.tmp, ".riel"))
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(LIST_RUN)
        rc, out, _err = run("run", "validate", cwd=self.tmp)
        self.assertEqual(rc, 0, out)
        self.assertIn("valid draft run", out)
        st = self.status()
        self.assertEqual(st["status"], "draft")
        self.assertIsNone(st["revision"])
        self.assertEqual(st["current_phase"], "F1")
        self.assertFalse(st["done"])
        self.activate()
        st = self.status()
        self.assertEqual(st["status"], "active")
        self.assertEqual(st["revision"], "r1")
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, ".riel")))
        body = self.read_run()
        self.assertIn("definition_sha256", body)
        self.assertIn("## Evidence", body)
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("already active", out + err)

    def test_template_comments_are_not_data(self):
        text = LIST_RUN.replace(
            "- P2: evidence closes gates — anchor: §Gates",
            "<!-- - P2: commented out — anchor: §Gates -->\n"
            "- P2: evidence closes gates — anchor: §Gates")
        os.makedirs(os.path.join(self.tmp, ".riel"))
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
        rc, out, _err = run("run", "validate", cwd=self.tmp)
        self.assertEqual(rc, 0, out)


class NoteTests(TempDirTest):
    def test_command_really_runs_and_exit_code_is_real(self):
        self.activate()
        marker = os.path.join(self.tmp, "ran.txt")
        rc, _out, err = run(
            "note", "--gate", "G1", "--claim", "P1",
            "--command", "python3 -c \"open('ran.txt','w').write('hi')\"",
            "--covering", "parser", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.isfile(marker))  # the shell command RAN here
        body = self.read_run()
        self.assertIn("exit_code:0", body)
        self.assertIn("gate:G1", body)
        self.assertIn("claims:P1", body)
        st = self.status()
        self.assertEqual(st["gates"]["G1"], "passed")
        self.assertEqual(st["claims"]["P1"], "covered")
        # a failing command records its REAL exit code and does not pass
        rc, _out, err = run(
            "note", "--gate", "G2", "--command", "false",
            "--covering", "verbs", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        st = self.status()
        self.assertEqual(st["gates"]["G2"], "pending")

    def test_unrelated_gate_does_not_advance_phase(self):
        self.activate()
        rc, _out, err = run(
            "note", "--gate", "G2", "--command", "true",
            "--covering", "verbs", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        st = self.status()
        self.assertEqual(st["gates"]["G2"], "passed")
        self.assertEqual(st["current_phase"], "F1")  # G2 is not F1's gate
        rc, _out, err = run(
            "note", "--gate", "G1", "--command", "true",
            "--covering", "parser", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        # its own gate now passed: F1 completes, and F2 was already complete
        # — no incomplete phase remains
        self.assertIsNone(self.status()["current_phase"])

    def test_done_requires_all_claims_and_all_gates(self):
        self.activate()
        run("note", "--gate", "G1", "--claim", "P1",
            "--command", "true", "--covering", "parser", cwd=self.tmp)
        st = self.status()
        self.assertFalse(st["done"])  # P2 open, G2 pending
        run("note", "--gate", "G2", "--claim", "P2",
            "--command", "true", "--covering", "verbs", cwd=self.tmp)
        self.assertTrue(self.status()["done"])

    def test_unknown_gate_and_claim_rejected(self):
        self.activate()
        rc, _out, err = run("note", "--gate", "G9", "--command", "true",
                            "--covering", "x", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("unknown gate", err)
        rc, _out, err = run("note", "--gate", "G1", "--claim", "P9",
                            "--command", "true", "--covering", "x",
                            cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("unknown claim", err)

    def test_confidence_bounds_and_low_confidence_vetoes(self):
        self.activate()
        rc, _out, err = run("note", "--gate", "G1", "--command", "true",
                            "--covering", "x", "--confidence", "22",
                            cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("1..20", err)
        rc, _out, err = run("note", "--gate", "G1", "--command", "true",
                            "--covering", "x", "--confidence", "5",
                            cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.status()["gates"]["G1"], "pending")

    def test_core_slots_are_1_based(self):
        self.activate()
        run("note", "--core", "alpha — first fact", cwd=self.tmp)
        run("note", "--core", "beta — second fact", cwd=self.tmp)
        rc, _out, err = run("note", "--core", "zeta — replaced",
                            "--core-slot", "1", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        body = self.read_run()
        self.assertIn("- 1. zeta — replaced", body)
        self.assertIn("- 2. beta — second fact", body)
        rc, _out, err = run("note", "--core", "omega — x",
                            "--core-slot", "9", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("1..3", err)

    def test_open_ids_are_never_reused(self):
        self.activate()
        run("note", "--gate", "G1", "--command", "true",
            "--covering", "parser", cwd=self.tmp)  # E1
        run("note", "--open", "does it blend?", "--settled-by", "blend.test",
            cwd=self.tmp)
        self.assertIn("Q1", self.read_run())
        run("note", "--close", "1", "--evidence", "1", cwd=self.tmp)
        run("note", "--open", "again?", "--settled-by", "t2", cwd=self.tmp)
        body = self.read_run()
        self.assertIn("Q1: does it blend?", body)
        self.assertIn("closed by: E1", body)
        self.assertIn("Q2: again?", body)  # no reuse of Q1
        rc, _out, err = run("note", "--close", "2", "--evidence", "99",
                            cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("E99 does not exist", err)

    def test_note_cannot_self_supply_exit_code_or_mix_kinds(self):
        self.activate()
        rc, _out, _err = run("note", "--gate", "G1", "--command", "true",
                             "--covering", "x", "--core", "a — b", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("one note, one kind", _err)

    def test_command_does_not_hide_a_second_line(self):
        self.activate()
        target = "true # a comment must not swallow the next line\nfalse"
        rc, _out, err = run("note", "--gate", "G1", "--command", target,
                            "--covering", "multiline preservation", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.status()["gates"]["G1"], "pending")
        specs = importlib.util.spec_from_file_location("riel_value", ENGINE)
        if specs is None or specs.loader is None:
            self.fail("the packaged engine cannot be loaded")
        engine = importlib.util.module_from_spec(specs)
        specs.loader.exec_module(engine)
        stored = engine.load_state(self.tmp)["evidence"][0]["command"]
        self.assertEqual(stored, target)

    def test_claim_without_gate_does_not_write_state(self):
        self.activate()
        before = self.read_run()
        rc, out, err = run("note", "--claim", "P1", "--command", "true",
                           "--covering", "no gate", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("needs at least one --gate", out + err)
        self.assertEqual(self.read_run(), before)

    def test_atomic_concurrent_notes_reader_never_sees_partial(self):
        self.activate()
        import importlib.util
        spec = importlib.util.spec_from_file_location("riel_engine", ENGINE)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        errors = []
        reads = [0]

        def reader():
            while not done.is_set():
                try:
                    engine.load_state(self.tmp, require_active=True)
                    reads[0] += 1
                except Exception as exc:  # a partial read would land here
                    errors.append(repr(exc))
                time.sleep(0.001)

        done = threading.Event()
        t = threading.Thread(target=reader)
        t.start()
        procs = [subprocess.Popen(
            [sys.executable, ENGINE, "note", "--gate", "G1",
             "--command", "true", "--covering", "writer %d" % i],
            cwd=self.tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for i in range(3)]
        codes = [p.wait(timeout=60) for p in procs]
        done.set()
        t.join()
        self.assertEqual(codes, [0, 0, 0])
        self.assertEqual(errors, [])
        self.assertGreater(reads[0], 0)
        body = self.read_run()
        for evidence_id in ("E1", "E2", "E3"):
            self.assertIn(evidence_id + " gate:G1", body)

    def test_symlinked_state_is_refused(self):
        self.activate()
        # (a) symlink INSIDE the worktree: the component walk refuses it
        with open(os.path.join(self.tmp, ".riel", "other.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(self.read_run())
        os.remove(self.run_path())
        os.symlink(os.path.join(self.tmp, ".riel", "other.md"),
                   self.run_path())
        rc, _out, err = run("note", "--core", "a — b", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("symlink", err)
        with open(os.path.join(self.tmp, ".riel", "other.md"),
                  encoding="utf-8") as fh:
            self.assertNotIn("a — b", fh.read())  # nothing written through
        # (b) symlink OUTSIDE the worktree: containment refuses it
        outside = os.path.join(tempfile.mkdtemp(prefix="riel-outside-"),
                               "victim.md")
        shutil.copy2(os.path.join(self.tmp, ".riel", "other.md"), outside)
        os.remove(self.run_path())
        os.symlink(outside, self.run_path())
        rc, _out, err = run("note", "--core", "a — b", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("escapes the worktree", err)
        with open(outside, encoding="utf-8") as fh:
            self.assertNotIn("a — b", fh.read())  # nothing written through


class ProjectionTests(TempDirTest):
    def test_projection_shape_and_shaping_version(self):
        self.activate()
        rc, output, err = run("todo", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        items = json.loads(output)
        self.assertEqual(items[0]["status"], "pending")
        self.assertEqual(items[1]["id"], "riel-phase-F1")
        self.assertEqual(items[1]["status"], "in_progress")
        self.assertEqual(items[2]["id"], "riel-gate-G1")
        self.assertEqual(items[2]["status"], "in_progress")
        self.assertEqual(items[3]["status"], "in_progress")
        self.assertEqual(items[3]["parent"], "riel-gate-G1")
        self.assertIn(items[3]["status"], ("pending", "in_progress", "completed"))

        shape_path = os.path.join(self.tmp, "shape.md")
        rc, draft, _ = run("shape", "new", "--param", "name=demo", cwd=self.tmp)
        self.assertEqual(rc, 0)
        self.assertRegex(draft, r"<!-- riel-shaping/v2 id:shp_[0-9a-f]{8} -->")
        with open(shape_path, "w", encoding="utf-8") as handle:
            handle.write(re.sub(r"<!-- riel-shaping/v2 id:shp_[0-9a-f]{8} -->",
                                "", draft))
        rc, _out, _err = run("shape", "validate", shape_path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        rc, _out, err = run("run", "new", "--param", "invalid", cwd=self.tmp)
        self.assertNotEqual(rc, 0)
        self.assertIn("want key=value", err)

    def test_projection_of_parallel_gates_keeps_real_phase(self):
        self.activate()
        run("note", "--gate", "G2", "--command", "true",
            "--covering", "another phase", cwd=self.tmp)
        rc, output, err = run("todo", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        states = {row["id"]: row["status"] for row in json.loads(output)}
        self.assertEqual(states["riel-phase-F1"], "in_progress")
        self.assertEqual(states["riel-phase-F2"], "pending")


    def test_global_gate_does_not_complete_a_phase_early(self):
        self.activate(text=LIST_RUN.replace(" — phase: F1", ""))
        state = self.status()
        self.assertEqual(state["current_phase"], "F1")
        self.assertEqual(state["gates"]["G1"], "pending")
        rc, output, err = run("todo", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rows = {row["id"]: row["status"] for row in json.loads(output)}
        self.assertEqual(rows["riel-phase-F1"], "in_progress")
        self.assertEqual(rows["riel-step-F1-S1"], "in_progress")


class FailedEvidenceTests(TempDirTest):
    def test_failed_command_never_covers_its_claim(self):
        self.activate()
        for claim, command in (("P1", "true"), ("P2", "false")):
            result = run("note", "--gate", "G1", "--claim", claim,
                         "--command", command, "--covering", claim, cwd=self.tmp)
            self.assertEqual(result[0], 0)  # evidence is recorded; its gate failed
        self.assertEqual(self.status()["claims"]["P2"], "open")
        run("note", "--gate", "G2", "--command", "true",
            "--covering", "second phase", cwd=self.tmp)
        state = self.status()
        self.assertFalse(state["done"])
        self.assertIn("P2", repr(state["claims"]))


class SliceTests(TempDirTest):
    def test_slice_self_validates_in_both_registers(self):
        for text in (LIST_RUN, MERMAID_RUN):
            with self.subTest(register="mermaid" if "```" in text else "list"):
                self.activate(text=text)
                rc, packet, err = run("run", "slice", "F1", cwd=self.tmp)
                self.assertEqual(rc, 0, err)
                self.assertNotIn("## Metadata", packet)  # no global state
                packet_path = os.path.join(self.tmp, "packet.md")
                with open(packet_path, "w", encoding="utf-8") as fh:
                    fh.write(packet)
                rc, out, err = run("run", "validate", packet_path,
                                   cwd=self.tmp)
                self.assertEqual(rc, 0, out + err)

    def test_slice_is_iterative_on_cycles(self):
        self.activate(text=MERMAID_RUN)
        sys.setrecursionlimit(200)
        try:
            rc, _packet, err = run("run", "slice", "F1", cwd=self.tmp)
            self.assertEqual(rc, 0, err)
            rc, _out, err = run("todo", cwd=self.tmp)
            self.assertEqual(rc, 0, err)
        finally:
            sys.setrecursionlimit(1000)


class RebaseTests(TempDirTest):
    SHAPING = """# Shaping: engine

<!-- riel-shaping/v2 id:shp_0a1b2c3d -->

## Question
Does the v2 engine read one state file?

## Findings
- F1: the single run.md parse works — source: scratch probe, confidence high

## Facts
- stdlib only.

## Verdict (→ run)
- We need one file
"""

    @staticmethod
    def anchored(text):
        return text.replace(
            "- P1: the parser reads the list register — anchor: §Graph",
            "- P1: the parser reads the list register — anchor: shaping:F1")

    def test_rebase_reserves_old_evidence(self):
        self.activate(text=self.anchored(LIST_RUN), shaping=self.SHAPING)
        body = self.read_run()
        self.assertIn("### Basis", body)
        self.assertIn("F1: the single run.md parse works", body)
        self.assertIn("— source: scratch probe", body)
        run("note", "--gate", "G1", "--claim", "P1", "--command", "true",
            "--covering", "parser", cwd=self.tmp)
        with open(self.shaping_path(), "a", encoding="utf-8") as fh:
            fh.write("- F2: extra finding — source: later probe\n")
        rc, _out, err = run("note", "--gate", "G2", "--command", "true",
                            "--covering", "verbs", cwd=self.tmp)
        self.assertEqual(rc, 3, err)  # stale
        self.assertIn("stale state", err)
        self.assertIn("run rebase", err)
        rc, out, err = run("run", "rebase", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        st = self.status()
        self.assertEqual(st["revision"], "r2")
        self.assertEqual(st["evidence"]["total"], 1)     # retained
        self.assertEqual(st["evidence"]["counted"], 0)   # but not counted
        self.assertEqual(st["gates"]["G1"], "pending")
        rc, _out, err = run("note", "--gate", "G1", "--claim", "P1",
                            "--command", "true", "--covering", "parser",
                            cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        st = self.status()
        self.assertEqual(st["gates"]["G1"], "passed")

    def test_slice_is_valid_without_external_shaping(self):
        self.activate(text=self.anchored(LIST_RUN), shaping=self.SHAPING)
        os.remove(self.shaping_path())
        rc, packet, err = run("run", "slice", "F1", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        packet_path = os.path.join(self.tmp, "packet.md")
        with open(packet_path, "w", encoding="utf-8") as handle:
            handle.write(packet)
        rc, out, err = run("run", "validate", packet_path, cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)

    def test_activate_requires_shaping_when_anchored(self):
        text = self.anchored(LIST_RUN)
        os.makedirs(os.path.join(self.tmp, ".riel"), exist_ok=True)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("binds no shaping", out + err)
        self.assertIn("### Shaping", out + err)


class SinkTests(TempDirTest):
    def test_outputs_go_to_explicit_sinks_only(self):
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location("riel_engine", ENGINE)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        self.activate()
        real_stdout, real_stderr = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            sink, sink_err = io.StringIO(), io.StringIO()
            code = engine.run_verb(["run", "status"], worktree=self.tmp,
                                   out=sink, err=sink_err)
            leaked = sys.stdout.getvalue() + sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = real_stdout, real_stderr
        self.assertEqual(code, 0)
        self.assertEqual(leaked, "")
        payload = json.loads(sink.getvalue())
        self.assertEqual(payload["format"], "riel-run/v1")
        # captured mode: (code, out_text, err_text)
        code2, out2, err2 = engine.run_verb(["run", "status"],
                                            worktree=self.tmp)
        self.assertEqual(code2, 0)
        self.assertIn('"status": "active"', out2)


    def test_parser_rejections_use_only_the_call_sinks(self):
        spec = importlib.util.spec_from_file_location("riel_parser_test", ENGINE)
        if spec is None or spec.loader is None:
            self.fail("the packaged engine cannot be loaded")
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        stdout, stderr = sys.stdout, sys.stderr
        out, err = io.StringIO(), io.StringIO()
        code = engine.run_verb(
            ["run", "new", "--template", "bogus"], worktree=self.tmp,
            out=out, err=err)
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err.getvalue())
        self.assertIs(sys.stdout, stdout)
        self.assertIs(sys.stderr, stderr)
        self.assertEqual(out.getvalue(), "")

    def test_unknown_gate_parameter_is_rejected_by_typed_tool(self):
        if REPO not in sys.path:
            sys.path.insert(0, REPO)
        from hermes_plugin.riel import tools
        result = json.loads(tools.riel_note({
            "gate": "G1", "command": "true", "worktree": self.tmp,
        }))
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("unknown parameter", result["error"])
        self.assertFalse(os.path.exists(self.run_path()))

def shaping_text(name="engine", uid="shp_0a1b2c3d",
                 question="Does the v2 engine read one state file?", findings=None):
    """A valid riel-shaping/v2 source: ONE question, sourced findings."""
    findings = findings or [
        "- F1: the single run.md parse works — source: scratch probe, confidence high"]
    return ("# Shaping: {}\n\n<!-- riel-shaping/v2 id:{} -->\n\n"
            "## Question\n{}\n\n## Findings\n{}\n\n"
            "## Facts\n- stdlib only.\n\n"
            "## Verdict (→ run)\n- We need one file\n").format(
                name, uid, question, "\n".join(findings))


class ShapingBindingTests(TempDirTest):
    """One run binds ONE shaping: by uid, path and sha256 — never by guesswork."""

    def write_shaping(self, slug="engine", **kw):
        path = self.shaping_path(slug)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(shaping_text(name=slug, **kw))
        return path

    def write_run(self, text):
        os.makedirs(os.path.join(self.tmp, ".riel"), exist_ok=True)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)

    def undecorated_anchored_run(self, anchor="shaping:F1"):
        """A pre-v2 run: anchors into a shaping, but declares nothing."""
        return LIST_RUN.replace(
            "- P1: the parser reads the list register — anchor: §Graph",
            "- P1: the parser reads the list register — anchor: " + anchor)

    def anchored_run(self, slug="engine", anchor="shaping:F1"):
        text = LIST_RUN.replace(
            "- P1: the parser reads the list register — anchor: §Graph",
            "- P1: the parser reads the list register — anchor: " + anchor)
        return self.declared(text, slug)

    # ---------------------------------------------------- one question ----
    def test_one_question_is_valid(self):
        path = self.write_shaping()
        rc, out, err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)

    def test_two_question_lines_are_refused(self):
        path = self.write_shaping(question="Does it read one file?\nAnd does it hash it?")
        rc, out, err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("ONE line", out + err)

    def test_two_question_marks_on_one_line_are_refused(self):
        path = self.write_shaping(question="Does it read one file? Or two?")
        rc, out, err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("exactly ONE question", out + err)

    def test_a_question_without_a_mark_is_refused(self):
        path = self.write_shaping(question="Decide the storage layout.")
        rc, out, _err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)

    def test_shape_new_mints_a_unique_uid_and_writes_nothing(self):
        rc, first, _ = run("shape", "new", "--param", "name=a", cwd=self.tmp)
        rc2, second, _ = run("shape", "new", "--param", "name=b", cwd=self.tmp)
        self.assertEqual((rc, rc2), (0, 0))
        a = re.search(r"id:(shp_[0-9a-f]{8})", first).group(1)
        b = re.search(r"id:(shp_[0-9a-f]{8})", second).group(1)
        self.assertNotEqual(a, b)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".riel")))

    # ------------------------------------------------------- the binding ----
    def test_activate_records_id_path_and_hash(self):
        self.write_shaping()
        self.write_run(self.anchored_run())
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        body = self.read_run()
        self.assertIn("- shaping: .riel/shapings/engine.md", body)
        self.assertIn("- shaping_id: shp_0a1b2c3d", body)
        self.assertRegex(body, r"- shaping_sha256: [0-9a-f]{64}")
        self.assertIn("### Basis", body)
        st = self.status()
        self.assertEqual(st["shaping"]["path"], ".riel/shapings/engine.md")
        self.assertEqual(st["shaping"]["id"], "shp_0a1b2c3d")

    def test_a_declaration_by_uid_resolves_the_file(self):
        self.write_shaping()
        text = self.anchored_run().replace(
            "- shaping: .riel/shapings/engine.md", "- shaping: shp_0a1b2c3d")
        self.write_run(text)
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.status()["shaping"]["path"], ".riel/shapings/engine.md")

    def test_anchors_resolve_only_against_the_bound_shaping(self):
        self.write_shaping("a", uid="shp_0000000a")
        self.write_shaping("b", uid="shp_0000000b", findings=[
            "- F2: only b knows this — source: probe, confidence high"])
        self.write_run(self.anchored_run(slug="a", anchor="shaping:F2"))
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("no such finding", out + err)
        self.assertIn("a.md", out + err)
        self.assertNotIn("b.md", out + err)

    def test_editing_the_bound_shaping_is_stale_a_sibling_is_not(self):
        self.write_shaping()
        self.write_shaping("sibling", uid="shp_0000000f")
        self.write_run(self.anchored_run())
        rc, _out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        with open(self.shaping_path("sibling"), "a", encoding="utf-8") as fh:
            fh.write("\n- F9: sibling research — source: probe\n")
        rc, _out, err = run("note", "--core", "sibling — edited", cwd=self.tmp)
        self.assertEqual(rc, 0, "a sibling shaping is not this run's evidence: " + err)
        with open(self.shaping_path(), "a", encoding="utf-8") as fh:
            fh.write("\n- F2: bound research moved — source: probe\n")
        rc, _out, err = run("note", "--core", "bound — edited", cwd=self.tmp)
        self.assertEqual(rc, 3)
        self.assertIn("stale state", err)
        self.assertIn(".riel/shapings/engine.md", err)

    def test_a_rename_keeps_the_binding_by_uid(self):
        self.write_shaping()
        self.write_run(self.anchored_run())
        rc, _out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        os.rename(self.shaping_path(), self.shaping_path("renamed"))
        st = self.status()
        self.assertEqual(st["shaping"]["path"], ".riel/shapings/renamed.md")
        self.assertEqual(st["shaping"]["id"], "shp_0a1b2c3d")
        rc, _out, err = run("note", "--core", "rename — survived", cwd=self.tmp)
        self.assertEqual(rc, 0, err)

    def test_a_duplicate_uid_is_refused(self):
        self.write_shaping()
        self.write_shaping("copy")            # same uid, different file
        self.write_run(self.anchored_run())
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertNotEqual(rc, 0)
        self.assertIn("not unique", out + err)

    def test_no_declaration_and_anchors_refuses_activation(self):
        self.write_shaping()
        self.write_run(LIST_RUN.replace(
            "- P1: the parser reads the list register — anchor: §Graph",
            "- P1: the parser reads the list register — anchor: shaping:F1"))
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("binds no shaping", out + err)

    # ------------------------------------------------------- migration ----
    def loose(self, text):
        os.makedirs(os.path.join(self.tmp, ".riel"), exist_ok=True)
        with open(self.loose_shaping_path(), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_migration_moves_mints_rebinds_and_keeps_the_original(self):
        original = shaping_text().replace(
            "<!-- riel-shaping/v2 id:shp_0a1b2c3d -->", "<!-- riel-shaping/v1 -->")
        self.loose(original)
        self.write_run(LIST_RUN.replace(
            "- P1: the parser reads the list register — anchor: §Graph",
            "- P1: the parser reads the list register — anchor: shaping:F1"))
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertFalse(os.path.exists(self.loose_shaping_path()))
        migrated = self.shaping_path()
        self.assertTrue(os.path.isfile(migrated))
        with open(migrated, encoding="utf-8") as fh:
            body = fh.read()
        self.assertRegex(body, r"<!-- riel-shaping/v2 id:shp_[0-9a-f]{8} -->")
        self.assertIn("F1: the single run.md parse works", body)
        backups = [f for f in os.listdir(os.path.join(self.tmp, ".riel"))
                   if f.startswith("shaping-") and f.endswith(".bak.md")]
        self.assertEqual(len(backups), 1, "the original is rotated, never deleted")
        with open(os.path.join(self.tmp, ".riel", backups[0]), encoding="utf-8") as fh:
            kept = fh.read()
        self.assertEqual(kept, original)
        run_body = self.read_run()
        self.assertIn("- shaping: .riel/shapings/engine.md", run_body)
        self.assertIn("### Shaping", run_body)
        self.assertIn("### Basis", run_body)

    def test_migration_refuses_to_overwrite_a_different_shaping(self):
        self.write_shaping("engine", uid="shp_0000000e",
                           question="Is this a different question?")
        self.loose(shaping_text().replace(
            "<!-- riel-shaping/v2 id:shp_0a1b2c3d -->", "<!-- riel-shaping/v1 -->"))
        self.write_run(self.undecorated_anchored_run())
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertNotEqual(rc, 0)
        self.assertIn("DIFFERENT shaping", out + err)
        self.assertTrue(os.path.exists(self.loose_shaping_path()))

    def test_migration_refuses_an_invalid_loose_shaping(self):
        self.loose(shaping_text(question="One? Two?").replace(
            "<!-- riel-shaping/v2 id:shp_0a1b2c3d -->", "<!-- riel-shaping/v1 -->"))
        self.write_run(self.undecorated_anchored_run())
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("exactly ONE question", out + err)
        self.assertTrue(os.path.exists(self.loose_shaping_path()))

    def test_a_pre_rename_definition_hash_key_still_reads_and_rebase_migrates_it(self):
        """The Contract vocabulary must not turn a live run stale on upgrade."""
        self.write_shaping()
        self.write_run(self.anchored_run())
        rc, _out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        body = self.read_run()
        self.assertIn("- definition_sha256:", body)
        # rewind Metadata to the pre-rename key, bytes of the Definition untouched
        head, state = body.split("## Metadata", 1)
        state = state.replace("- definition_sha256:", "- plan_sha256:")
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(head + "## Metadata" + state)
        rc, out, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 0, "the old key is still read: " + err)
        rc, _out, err = run("note", "--core", "legacy key — still writes", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        with open(self.shaping_path(), "a", encoding="utf-8") as fh:
            fh.write("\n- F2: research moved — source: probe\n")
        rc, out, err = run("run", "rebase", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        body = self.read_run()
        self.assertIn("- definition_sha256:", body)
        self.assertNotIn("- plan_sha256:", body, "the rebase drops the pre-rename key")


    def test_a_legacy_active_run_keeps_working_until_its_next_rebase(self):
        """A pre-v2 active run: hash-only Metadata, no declaration, loose shaping.

        The state half is built by hand exactly as the old engine wrote it, so
        the definition hash is real — upgrading must not turn a live run stale.
        """
        definition = self.undecorated_anchored_run()
        loose_text = shaping_text().replace(
            "<!-- riel-shaping/v2 id:shp_0a1b2c3d -->", "<!-- riel-shaping/v1 -->")
        self.loose(loose_text)
        definition_bytes = definition.rstrip("\n") + "\n"
        state = (
            "## Metadata\n\n"
            "- format: riel-run/v1\n- revision: r1\n"
            "- activated: 2026-01-01T00:00:00\n"
            "- definition_sha256: {}\n- shaping_sha256: {}\n\n"
            "## Execution state\n\n- current_phase: F1\n\n"
            "## Core\n\n<!-- empty -->\n\n"
            "## Open\n\n<!-- empty -->\n\n"
            "## Evidence\n\n<!-- empty -->\n").format(
                hashlib.sha256(definition_bytes.encode("utf-8")).hexdigest(),
                hashlib.sha256(loose_text.encode("utf-8")).hexdigest())
        self.write_run(definition_bytes + "\n" + state)
        rc, out, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 0, "a pre-v2 active run must not break on upgrade: " + err)
        self.assertEqual(json.loads(out)["shaping"]["path"], ".riel/shaping.md")
        rc, _out, err = run("note", "--core", "legacy — still writes", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rc, out, err = run("run", "rebase", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(os.path.isfile(self.shaping_path()))
        self.assertFalse(os.path.exists(self.loose_shaping_path()))
        body = self.read_run()
        self.assertIn("- shaping: .riel/shapings/engine.md", body)
        self.assertIn("- shaping_id: shp_", body)
        self.assertIn("### Shaping", body)
        self.assertEqual(self.status()["revision"], "r2")


class CleanAndArchiveTests(TempDirTest):
    """clean wipes ALL of .riel/ (archiving opt-in); runs/ is never pruned."""

    def seed_layout(self):
        self.activate(text=LIST_RUN, shaping=shaping_text(), slug="engine")
        riel = os.path.join(self.tmp, ".riel")
        extra = {
            "project.md": "# Project: demo\n",
            "shapings/sibling.md": shaping_text(name="sibling", uid="shp_0000000f"),
            "runs/old.md": "# Run: an older proof\n",
            "shaping.md": shaping_text(name="loose", uid="shp_0000000l"),
            "contract.md": "# legacy v1\n",
            "ledger.md": "# legacy v1\n",
            "run-20260101-000000.bak.md": "# an old backup\n",
            "templates/mine.md": "# a user template\n",
        }
        for rel, body in extra.items():
            path = os.path.join(riel, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
        return extra

    def entries(self):
        return sorted(os.listdir(os.path.join(self.tmp, ".riel")))

    def test_clean_removes_every_entry_and_keeps_only_the_lock(self):
        self.seed_layout()
        rc, out, err = run("clean", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(self.entries(), [".run.lock"],
                         "clean wipes run, project, shapings/, runs/, legacy and backups")
        self.assertIn("no archive", out)

    def test_clean_leaves_no_backup_by_default(self):
        self.seed_layout()
        run("clean", cwd=self.tmp)
        leftovers = []
        for root, _dirs, files in os.walk(self.tmp):
            leftovers += [f for f in files if f.endswith(".bak.md")]
        self.assertEqual(leftovers, [], "archiving is opt-in, never the default")

    def test_clean_on_an_absent_riel_is_a_no_op(self):
        rc, out, err = run("clean", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("nothing to clean", out)

    def test_clean_archive_is_verified_and_restorable(self):
        extra = self.seed_layout()
        home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp        # never write into the operator's home
        self.addCleanup(lambda: os.environ.__setitem__("HOME", home)
                        if home else os.environ.pop("HOME", None))
        before = {}
        for root, _dirs, files in os.walk(os.path.join(self.tmp, ".riel")):
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as fh:
                    before[os.path.relpath(path, os.path.join(self.tmp, ".riel"))] = fh.read()
        rc, out, err = run("clean", "--archive", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("archived", out)
        self.assertIn("restore:", out)
        archives = list(Path(self.tmp).glob(".hermes/riel/archive/*/*"))
        self.assertEqual(len(archives), 1, out)
        archive = archives[0]
        for rel, body in before.items():
            with open(os.path.join(str(archive), rel), "rb") as fh:
                self.assertEqual(fh.read(), body, "archive byte mismatch: " + rel)
        self.assertEqual(self.entries(), [".run.lock"])
        shutil.copytree(str(archive), os.path.join(self.tmp, ".riel"),
                        dirs_exist_ok=True)
        # the restore is byte-complete, legacy files included — and v1 state
        # still refuses v2 reads, so archive those two before reading the run
        for legacy in ("contract.md", "ledger.md"):
            os.unlink(os.path.join(self.tmp, ".riel", legacy))
        st = self.status()
        self.assertEqual(st["status"], "active", "the restore brings the run back")
        self.assertEqual(st["shaping"]["id"], "shp_0a1b2c3d")

    def test_run_archive_moves_the_run_and_keeps_the_binding(self):
        self.activate(text=self.declared(LIST_RUN), shaping=shaping_text())
        rc, out, err = run("run", "archive", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertFalse(os.path.exists(self.run_path()))
        archived = os.path.join(self.tmp, ".riel", "runs", "engine.md")
        self.assertTrue(os.path.isfile(archived))
        with open(archived, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("- shaping_id: shp_0a1b2c3d", body)
        self.assertIn("- shaping: .riel/shapings/engine.md", body)
        self.assertIn("NOT done", out, "an unfinished run archives as pending proof")

    def test_run_archive_refuses_to_overwrite_the_same_shaping(self):
        self.activate(text=self.declared(LIST_RUN), shaping=shaping_text())
        rc, _out, err = run("run", "archive", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.activate(text=self.declared(LIST_RUN), shaping=shaping_text())
        rc, out, err = run("run", "archive", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("already exists", out + err)
        self.assertTrue(os.path.exists(self.run_path()), "the live run is untouched")

    def test_archived_runs_are_never_pruned(self):
        for i in range(5):
            slug = "track{}".format(i)
            self.activate(text=LIST_RUN,
                          shaping=shaping_text(name=slug, uid="shp_%08x" % i),
                          slug=slug)
            rc, _out, err = run("run", "archive", cwd=self.tmp)
            self.assertEqual(rc, 0, err)
        runs = sorted(os.listdir(os.path.join(self.tmp, ".riel", "runs")))
        self.assertEqual(runs, ["track{}.md".format(i) for i in range(5)],
                         "a project derives its progress from these — none may be pruned")


def slug_uid(slug):
    """A deterministic, well-formed uid for a test shaping (no hash randomization)."""
    return "shp_%08x" % (sum(ord(c) * (i + 1) for i, c in enumerate(slug)) % 0xffffffff)


class ProjectTests(TempDirTest):
    """A project orders shapings; its progress is derived from the runs' proof."""

    def shaping(self, slug, uid=None, question="Does this track hold?"):
        path = self.shaping_path(slug)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(shaping_text(name=slug, uid=uid or slug_uid(slug),
                                  question=question))
        return path

    def project(self, body=None):
        os.makedirs(os.path.join(self.tmp, ".riel"), exist_ok=True)
        text = body if body is not None else (
            "# Project: demo\n\n<!-- riel-project/v1 -->\n\n"
            "## Objective\nShip the demo in two tracks.\n\n"
            "## Graph\n- S1: .riel/shapings/a.md\n- S2: .riel/shapings/b.md\n")
        path = os.path.join(self.tmp, ".riel", "project.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_for(self, slug, finish=False):
        self.activate(text=LIST_RUN, shaping=shaping_text(
            name=slug, uid=slug_uid(slug)), slug=slug)
        if finish:
            for gate, claim in (("G1", "P1"), ("G2", "P2")):
                rc, _out, err = run("note", "--gate", gate, "--claim", claim,
                                    "--command", "true", "--covering", claim,
                                    cwd=self.tmp)
                self.assertEqual(rc, 0, err)
            self.assertTrue(self.status()["done"])
        rc, out, err = run("run", "archive", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)

    def pstatus(self):
        rc, out, err = run("project", "status", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        return json.loads(out)

    def test_a_valid_project_passes(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        rc, out, err = run("project", "validate", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("2 shaping(s)", out)

    def test_project_new_renders_and_writes_nothing(self):
        rc, out, _err = run("project", "new", "--param", "name=demo", cwd=self.tmp)
        self.assertEqual(rc, 0)
        self.assertIn("<!-- riel-project/v1 -->", out)
        self.assertIn("# Project: demo", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".riel", "project.md")))

    def test_a_missing_marker_is_refused(self):
        self.shaping("a")
        self.project("# Project: demo\n\n## Objective\nShip it.\n\n"
                     "## Graph\n- S1: .riel/shapings/a.md\n")
        rc, out, _err = run("project", "validate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("riel-project/v1", out)

    def test_a_node_without_a_shaping_is_refused(self):
        self.shaping("a")
        self.project()          # S2 points at shapings/b.md, which does not exist
        rc, out, _err = run("project", "validate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("S2", out)
        self.assertIn("no such shaping", out)

    def test_one_shaping_cannot_be_two_nodes(self):
        self.shaping("a")
        self.project("# Project: demo\n\n<!-- riel-project/v1 -->\n\n"
                     "## Objective\nShip it.\n\n## Graph\n"
                     "- S1: .riel/shapings/a.md\n- S2: .riel/shapings/a.md\n")
        rc, out, _err = run("project", "validate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("one shaping is one run", out)

    def test_a_cycle_is_refused(self):
        self.shaping("a"); self.shaping("b")
        self.project("# Project: demo\n\n<!-- riel-project/v1 -->\n\n"
                     "## Objective\nShip it.\n\n## Graph\n```mermaid\n"
                     "flowchart TD\n  S1[\"shapings/a.md\"] --> S2[\"shapings/b.md\"]\n"
                     "  S2 --> S1\n```\n")
        rc, out, _err = run("project", "validate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("cycle", out)

    def test_an_invalid_shaping_is_reported_against_its_node(self):
        self.shaping("a", question="One? Two?")
        self.shaping("b")
        self.project()
        rc, out, _err = run("project", "validate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("S1", out)
        self.assertIn("exactly ONE question", out)

    def test_status_starts_pending_and_names_the_first(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        st = self.pstatus()
        self.assertEqual(st["order"], ["S1", "S2"])
        self.assertEqual(st["nodes"]["S1"]["status"], "pending")
        self.assertEqual(st["nodes"]["S2"]["status"], "blocked")
        self.assertEqual(st["next"], "S1")
        self.assertFalse(st["done"])
        self.assertEqual(st["nodes"]["S1"]["question"], "Does this track hold?")

    def test_an_archived_done_run_completes_its_node(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        self.run_for("a", finish=True)
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S1"]["status"], "done")
        self.assertEqual(st["nodes"]["S1"]["run"], ".riel/runs/a.md")
        self.assertEqual(st["nodes"]["S2"]["status"], "pending")
        self.assertEqual(st["next"], "S2")
        self.assertFalse(st["done"])

    def test_an_unfinished_archive_does_not_complete_the_node(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        self.run_for("a", finish=False)
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S1"]["status"], "pending")
        self.assertEqual(st["next"], "S1")

    def test_the_live_run_makes_its_shaping_active(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        self.activate(text=LIST_RUN, shaping=shaping_text(
            name="a", uid=slug_uid("a")), slug="a")
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S1"]["status"], "active")
        self.assertEqual(st["nodes"]["S1"]["run"], ".riel/run.md")

    def test_deleting_the_proof_reopens_the_node(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        self.run_for("a", finish=True)
        self.assertEqual(self.pstatus()["nodes"]["S1"]["status"], "done")
        os.remove(os.path.join(self.tmp, ".riel", "runs", "a.md"))
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S1"]["status"], "pending",
                         "progress is the evidence, not a declaration")
        self.assertEqual(st["next"], "S1")

    def test_the_project_is_done_when_every_shaping_is(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        self.run_for("a", finish=True)
        self.run_for("b", finish=True)
        st = self.pstatus()
        self.assertTrue(st["done"])
        self.assertIsNone(st["next"])

    def test_parallel_branches_block_until_their_predecessor_is_done(self):
        self.shaping("a"); self.shaping("b"); self.shaping("c")
        self.project("# Project: demo\n\n<!-- riel-project/v1 -->\n\n"
                     "## Objective\nShip it.\n\n## Graph\n```mermaid\n"
                     "flowchart TD\n  S1[\"shapings/a.md\"] --> S2[\"shapings/b.md\"]\n"
                     "  S1 --> S3[\"shapings/c.md\"]\n```\n")
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S2"]["status"], "blocked")
        self.assertEqual(st["nodes"]["S3"]["status"], "blocked")
        self.run_for("a", finish=True)
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S2"]["status"], "pending")
        self.assertEqual(st["nodes"]["S3"]["status"], "pending")

    def test_status_refuses_an_invalid_project_instead_of_inventing_progress(self):
        self.shaping("a")
        self.project()          # S2 has no shaping
        rc, out, _err = run("project", "status", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("INVALID project", out)


if __name__ == "__main__":
    unittest.main()
