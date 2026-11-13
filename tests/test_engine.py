"""Regression tests for engine/run.py — riel-run/v1 (riel 2.0, clean break).

Stdlib-only (unittest). Each test runs the real CLI in a fresh tempdir via
subprocess, so exit codes are the ACTUAL process exit codes.

Run:
    python3 -m unittest tests.test_engine -v
"""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENGINE = os.path.join(REPO, "hermes_plugin", "riel", "engine", "run.py")

LIST_RUN = """# Run: engine v2
<!-- riel-run/v1 -->

## Objective
The engine records evidence against riel-run/v1 plans.

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

    def activate(self, text=LIST_RUN, shaping=None):
        os.makedirs(os.path.join(self.tmp, ".riel"), exist_ok=True)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
        if shaping:
            with open(self.shaping_path(), "w", encoding="utf-8") as fh:
                fh.write(shaping)
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        return rc, out, err

    def run_path(self):
        return os.path.join(self.tmp, ".riel", "run.md")

    def shaping_path(self):
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
        self.assertIn("plan_sha256", body)
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
        self.assertIn("<!-- riel-shaping/v1 -->", draft)
        with open(shape_path, "w", encoding="utf-8") as handle:
            handle.write(draft.replace("<!-- riel-shaping/v1 -->", ""))
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

<!-- riel-shaping/v1 -->

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
        self.assertIn("shaping.md does not exist", out + err)


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

class FetchTests(TempDirTest):
    BODY = b"hello run"

    @classmethod
    def setUpClass(cls):
        cls.hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.hits.append(
                    (self.path, self.headers.get("Authorization")))
                if self.path == "/redir":
                    self.send_response(302)
                    self.send_header("Location",
                                     "http://localhost:%d/file"
                                     % cls.server.server_port)
                    self.end_headers()
                elif self.path == "/trunc":
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.write(b"x" * 50)
                elif self.path == "/binary":
                    body = b"\xff"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/file":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(cls.BODY)))
                    self.end_headers()
                    self.wfile.write(cls.BODY)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_fetch_happy_path_is_atomic_and_not_activated(self):
        out = os.path.join(self.tmp, "fetched.md")
        sha = hashlib.sha256(self.BODY).hexdigest()
        rc, out_text, err = run("run", "fetch",
                                "http://127.0.0.1:%d/file" % self.port,
                                "-o", out, "--sha256", sha, cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(), self.BODY)

    def test_fetch_requires_sha256(self):
        rc, _out, err = run("run", "fetch",
                            "http://127.0.0.1:%d/file" % self.port,
                            "-o", "f.md", cwd=self.tmp)
        self.assertEqual(rc, 2)  # argparse: --sha256 mandatory

    def test_fetch_sha_mismatch_rejected(self):
        rc, _out, err = run("run", "fetch",
                            "http://127.0.0.1:%d/file" % self.port,
                            "-o", "f.md",
                            "--sha256", "0" * 64, cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("sha256 mismatch", err)

    def test_fetch_rejects_incomplete_body(self):
        rc, _out, err = run("run", "fetch",
                            "http://127.0.0.1:%d/trunc" % self.port,
                            "-o", "f.md", "--sha256",
                            hashlib.sha256(b"x" * 50).hexdigest(),
                            cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("incomplete body", err)

    def test_fetch_redirect_strips_authorization_on_origin_change(self):
        sha = hashlib.sha256(self.BODY).hexdigest()
        rc, _out, err = run(
            "run", "fetch", "http://127.0.0.1:%d/redir" % self.port,
            "-o", "f.md", "--sha256", sha,
            "--header", "Authorization: Bearer secret", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        paths = {path: auth for path, auth in type(self).hits}
        self.assertEqual(paths["/redir"], "Bearer secret")
        self.assertIsNone(paths["/file"])  # stripped across the origin change


    def test_fetch_never_replaces_active_state(self):
        self.activate()
        before = self.read_run()
        sha = hashlib.sha256(self.BODY).hexdigest()
        rc, _out, err = run(
            "run", "fetch", "http://127.0.0.1:%d/file" % self.port,
            "-o", self.run_path(), "--sha256", sha, cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("refuses to replace", err)
        self.assertEqual(self.read_run(), before)


if __name__ == "__main__":
    unittest.main()
