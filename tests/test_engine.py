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

## Deliverable
engine/run.py rewired.

## Constraints
- stdlib only.

## DO NOT
- touch tools.py.
## Phases

### F1: build parser
- READ the spec
- RUN make test

#### Claims
- P1: the parser reads the phase outline — anchor: §F1#1

#### Gates
- G1: parser tests pass

#### Deliverable
- the parser reads one file

### F2: wire verbs
- EDIT tools.py
- RUN make test

#### Claims
- P2: evidence closes gates — anchor: §F2#2

#### Gates
- G2: verbs wired

#### Deliverable
- tools.py rewired

"""

MERMAID_RUN = LIST_RUN.replace(
    """## Phases

### F1: build parser""",
    """## Phases
<!-- the general DAG between phases; retry < 3 attempts -->
```mermaid
flowchart TD
  F1["build parser"] --> D1{"tests ok?"}
  D1 -->|yes| F2["wire verbs"]
  D1 -->|no| F1
```

### F1: build parser""")


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
        os.makedirs(os.path.dirname(self.run_path()), exist_ok=True)
        if shaping:
            os.makedirs(os.path.dirname(self.shaping_path(slug)), exist_ok=True)
            with open(self.shaping_path(slug), "w", encoding="utf-8") as fh:
                fh.write(shaping)
            text = self.declared(text, slug)
        with open(self.run_path(slug), "w", encoding="utf-8") as fh:
            fh.write(text)
        rc, out, err = run("run", "activate", "--run", slug, cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        return rc, out, err

    def declared(self, text, slug="engine"):
        """The run's ### Shaping declaration — the binding is authored, not guessed."""
        return text.replace(
            "- riel → repo\n",
            "- riel → repo\n\n### Shaping\n- shaping: .riel/shapings/{}.md\n".format(slug))

    def run_path(self, slug="engine"):
        """Contracts are executed IN PLACE at .riel/runs/<slug>.md."""
        return os.path.join(self.tmp, ".riel", "runs", slug + ".md")

    def shaping_path(self, slug="engine"):
        return os.path.join(self.tmp, ".riel", "shapings", slug + ".md")

    def loose_shaping_path(self):
        return os.path.join(self.tmp, ".riel", "shaping.md")

    def status(self, slug=None):
        argv = ["run", "status"] + (["--run", slug] if slug else [])
        rc, out, err = run(*argv, cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def read_run(self, slug="engine"):
        with open(self.run_path(slug), encoding="utf-8") as fh:
            return fh.read()


class FormatTests(TempDirTest):
    def test_new_renders_stdout_without_state(self):
        rc, out, err = run("run", "new", "--param", "title=demo", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("<!-- riel-run/v1 -->", out)
        self.assertIn("# Run: demo", out)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".riel")))

    def test_old_state_files_are_invisible(self):
        """No legacy machinery: without run.md there is simply no run state."""
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"))
        for name in ("contract.md", "ledger.md"):
            with open(os.path.join(self.tmp, ".riel", name), "w") as fh:
                fh.write("# old state\n")
        rc, _out, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertNotIn("legacy", err)
        rc, _out, err = run("note", "--core", "x — y", cwd=self.tmp)
        self.assertEqual(rc, 2)
        rc, _out, err = run("run", "validate",
                            os.path.join(self.tmp, ".riel", "contract.md"),
                            cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("riel-run/v1", err)

    def test_draft_and_active_validate(self):
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"))
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
        rc, out, err = run("run", "activate", "--run", "engine", cwd=self.tmp)
        self.assertEqual(rc, 2, out + err)
        self.assertIn("already active", out + err)

    def test_template_comments_are_not_data(self):
        text = LIST_RUN.replace(
            "- P2: evidence closes gates — anchor: §F2#2",
            "<!-- - P2: commented out — anchor: §F2#2 -->\n"
            "- P2: evidence closes gates — anchor: §F2#2")
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"))
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

    def test_partial_evidence_records_without_passing_and_confidence_rejected(self):
        self.activate()
        rc, _out, err = run("note", "--gate", "G1", "--command", "true",
                            "--covering", "x", "--confidence", "15",
                            cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("unrecognized arguments", err)
        rc, out, err = run("note", "--gate", "G1", "--claim", "P1",
                           "--command", "true", "--covering", "wip check",
                           "--partial", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("gate_exit_code: 0 | gate_passed: false", out)
        body = self.read_run()
        self.assertIn("partial:true", body)
        st = self.status()
        self.assertEqual(st["gates"]["G1"], "pending")
        self.assertEqual(st["claims"]["P1"], "open")
        self.assertFalse(st["done"])

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
        self.assertEqual(items[1]["id"], "riel-engine-phase-F1")
        self.assertEqual(items[1]["status"], "in_progress")
        self.assertEqual(items[2]["id"], "riel-engine-gate-G1")
        self.assertEqual(items[2]["status"], "in_progress")
        self.assertEqual(items[3]["status"], "in_progress")
        self.assertEqual(items[3]["parent"], "riel-engine-gate-G1")
        self.assertIn(items[3]["status"], ("pending", "in_progress", "completed"))

        shape_path = os.path.join(self.tmp, "shape.md")
        rc, draft, _ = run("shape", "new", "--param", "name=demo", cwd=self.tmp)
        self.assertEqual(rc, 0)
        self.assertRegex(draft, r"<!-- riel-shaping/v3 id:shp_[0-9a-f]{8} -->")
        with open(shape_path, "w", encoding="utf-8") as handle:
            handle.write(re.sub(r"<!-- riel-shaping/v3 id:shp_[0-9a-f]{8} -->",
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
        self.assertEqual(states["riel-engine-phase-F1"], "in_progress")
        self.assertEqual(states["riel-engine-phase-F2"], "pending")


    def test_a_later_phases_gate_does_not_complete_an_earlier_phase(self):
        """Gate membership is structural: G2 lives in F2 and cannot close F1."""
        self.activate()
        state = self.status()
        self.assertEqual(state["current_phase"], "F1")
        self.assertEqual(state["gates"]["G1"], "pending")
        self.assertEqual(state["gates"]["G2"], "pending")
        rc, output, err = run("todo", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rows = {row["id"]: row["status"] for row in json.loads(output)}
        self.assertEqual(rows["riel-engine-phase-F1"], "in_progress")
        self.assertEqual(rows["riel-engine-step-F1S1"], "in_progress")
        self.assertEqual(rows["riel-engine-phase-F2"], "pending")


class PhasesTests(TempDirTest):
    """## Phases: the general DAG plus one ### F# block per phase.

    Phase membership is structural, step ids are per phase, and a phase's
    claims/gates/deliverable travel with it.
    """

    @staticmethod
    def engine():
        spec = importlib.util.spec_from_file_location("riel_engine_phases", ENGINE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def validate(self, text):
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"), exist_ok=True)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)
        return run("run", "validate", cwd=self.tmp)

    def test_step_ids_are_per_phase_and_stable(self):
        eng = self.engine()
        before = eng.contract_graph(LIST_RUN)[0]
        inserted = LIST_RUN.replace("- READ the spec\n",
                                    "- READ the spec\n- READ the changelog\n")
        after = eng.contract_graph(inserted)[0]
        self.assertEqual(before["F2S1"], after["F2S1"],
                         "inserting a step in F1 must not renumber F2")
        self.assertEqual(after["F1S2"][1], "READ the changelog")
        self.assertEqual(after["F1S3"][1], "RUN make test")

    def test_a_section_anchor_names_a_phase_step(self):
        eng = self.engine()
        nodes, edges, _r = eng.contract_graph(LIST_RUN)
        issues, _w = eng._check_definition(LIST_RUN, nodes, edges, "", False, [])
        self.assertEqual(issues, [])
        bad = LIST_RUN.replace("— anchor: §F1#1", "— anchor: §F1#9")
        nodes, edges, _r = eng.contract_graph(bad)
        issues, _w = eng._check_definition(bad, nodes, edges, "", False, [])
        self.assertTrue(any("§F1#9" in i and "item(s)" in i for i in issues), issues)

    def test_gate_membership_is_structural(self):
        gates = self.engine()._parse_gates(LIST_RUN)
        self.assertEqual([(g["id"], g["phase"]) for g in gates],
                         [("G1", "F1"), ("G2", "F2")])
        self.assertTrue(all(g["declared_phase"] == "" for g in gates))

    def test_a_disagreeing_phase_suffix_is_refused(self):
        bad = LIST_RUN.replace("- G1: parser tests pass",
                               "- G1: parser tests pass — phase: F2")
        rc, out, _err = self.validate(bad)
        self.assertEqual(rc, 1)
        self.assertIn("declares phase F2 but lives in F1", out)

    def test_the_flat_pre_phases_definition_is_refused(self):
        old = """# Run: old
<!-- riel-run/v1 -->

## Objective
o.

## Context

### Why
w.

## Deliverable
d.

## Constraints
- c.

## DO NOT
- n.
## Claims
- P1: x — anchor: §Graph

## Graph
- F1: build
  - RUN true

## Gates
- G1: g — phase: F1

"""
        rc, out, _err = self.validate(old)
        self.assertEqual(rc, 1)
        for name in ("Claims", "Graph", "Gates"):
            self.assertIn("## {} is no longer part of the Contract".format(name), out)

    def test_each_phase_needs_claims_gates_and_deliverable(self):
        missing = LIST_RUN.replace("""#### Deliverable
- the parser reads one file

""", "")
        rc, out, _err = self.validate(missing)
        self.assertEqual(rc, 1)
        self.assertIn("phase F1 has no #### Deliverable items", out)

    def test_a_phase_without_steps_is_refused(self):
        no_steps = LIST_RUN.replace("- READ the spec\n- RUN make test\n", "")
        rc, out, _err = self.validate(no_steps)
        self.assertEqual(rc, 1)
        self.assertIn("phase F1 has no steps", out)

    def test_duplicate_ids_across_phases_are_refused(self):
        dup = LIST_RUN.replace("- P2: evidence closes gates", "- P1: evidence closes gates")
        rc, out, _err = self.validate(dup)
        self.assertEqual(rc, 1)
        self.assertIn("duplicate claim id P1", out)
        dupg = LIST_RUN.replace("- G2: verbs wired", "- G1: verbs wired")
        rc, out, _err = self.validate(dupg)
        self.assertEqual(rc, 1)
        self.assertIn("duplicate gate id across phases", out)

    def test_the_general_dag_can_be_an_arrow_list(self):
        eng = self.engine()
        listed = LIST_RUN.replace("## Phases\n", "## Phases\n- F2 → F1\n")
        nodes, edges, register = eng.contract_graph(listed)
        self.assertEqual(register, "outline")
        self.assertIn(("F2S2", "", "F1"), edges,
                      "the preamble order overrides the heading order")
        self.assertNotIn(("F1S2", "", "F2"), edges)

    def test_the_general_dag_can_be_mermaid_with_a_decision(self):
        eng = self.engine()
        nodes, edges, register = eng.contract_graph(MERMAID_RUN)
        self.assertEqual(register, "mermaid")
        self.assertIn("D1", nodes)
        self.assertEqual(nodes["D1"][0], "{")
        issues, warnings = eng._check_definition(MERMAID_RUN, nodes, edges, "", False, [])
        self.assertEqual(issues, [])
        self.assertFalse(any("counter guard" in w for w in warnings), warnings)

    def test_the_authored_heading_order_is_the_default(self):
        nodes, _edges, register = self.engine().contract_graph(LIST_RUN)
        self.assertEqual(register, "outline")
        self.assertEqual([n for n in nodes if re.match(r"^F\d+$", n)], ["F1", "F2"])

    def test_a_slice_carries_its_phase_block_and_self_validates(self):
        self.activate()
        rc, out, err = run("run", "slice", "F1", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("### F1: build parser", out)
        self.assertIn("#### Claims", out)
        self.assertIn("#### Gates", out)
        self.assertIn("#### Deliverable", out)
        self.assertIn("- P1: the parser reads the phase outline", out)
        self.assertNotIn("### F2:", out, "a slice carries ONE phase")
        self.assertNotIn("- P2:", out)
        self.assertIn("## DO NOT", out, "the global scope travels with the slice")
        eng = self.engine()
        nodes, edges, _r = eng.contract_graph(out)
        issues, _w = eng._check_definition(out, nodes, edges, "", False,
                                           eng._parse_basis(out), basis_only=True)
        self.assertEqual(issues, [])

    def test_the_checklist_names_steps_by_their_phase_scoped_id(self):
        self.activate()
        rc, out, err = run("todo", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rows = {row["id"] for row in json.loads(out)}
        self.assertIn("riel-engine-step-F1S1", rows)
        self.assertIn("riel-engine-step-F2S1", rows)
        self.assertNotIn("riel-engine-step-F1-S1", rows)


class PlaceholderGuardTests(TempDirTest):
    """A Definition still carrying {{…}} is a skeleton, not a Contract."""

    def write(self, text):
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"), exist_ok=True)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_a_raw_template_is_refused_and_names_what_is_missing(self):
        rc, draft, err = run("run", "new", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.write(draft)
        rc, out, _err = run("run", "validate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("unfilled placeholder(s) in the Definition", out)
        for name in ("{{objective}}", "{{why}}", "{{constraint}}", "{{do_not}}"):
            self.assertIn(name, out)
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1, "a skeleton must not activate")
        self.assertIn("unfilled placeholder(s)", out + err)

    def test_one_leftover_placeholder_refuses_activation(self):
        self.write(LIST_RUN.replace("The engine records evidence against riel-run/v1 contracts.",
                                    "{{objective}}"))
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("{{objective}}", out + err)
        self.assertNotIn("revision r1", out)

    def test_a_placeholder_inside_a_comment_is_not_data(self):
        self.write(LIST_RUN + "\n<!-- example: {{not_a_field}} -->\n")
        rc, out, err = run("run", "validate", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)

    def test_an_authored_contract_passes(self):
        self.write(LIST_RUN)
        rc, out, err = run("run", "validate", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn("unfilled placeholder", out)


class ParallelTracksTests(TempDirTest):
    """Several active contracts in ONE worktree, executed in place."""

    def track(self, slug, finish=False):
        self.activate(text=LIST_RUN,
                      shaping=shaping_text(name=slug, uid=slug_uid(slug)), slug=slug)
        if finish:
            for gate, claim in (("G1", "P1"), ("G2", "P2")):
                rc, _o, err = run("note", "--run", slug, "--gate", gate,
                                  "--claim", claim, "--command", "true",
                                  "--covering", claim, cwd=self.tmp)
                self.assertEqual(rc, 0, err)

    def test_tracks_progress_independently(self):
        self.track("a", finish=True)
        self.track("b")
        self.assertTrue(self.status("a")["done"])
        self.assertFalse(self.status("b")["done"])
        self.assertEqual(self.status("b")["current_phase"], "F1")

    def test_list_enumerates_every_contract(self):
        self.track("a"); self.track("b")
        rc, out, err = run("run", "list", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rows = json.loads(out)["contracts"]
        self.assertEqual([r["slug"] for r in rows], ["a", "b"])
        self.assertTrue(all(r["status"] == "active" for r in rows))
        self.assertEqual(rows[0]["run"], ".riel/runs/a.md")

    def test_list_reports_an_unreadable_contract_instead_of_skipping_it(self):
        self.track("a")
        with open(self.run_path("broken"), "w", encoding="utf-8") as fh:
            fh.write("# Run: broken\n\nno marker here\n")
        rc, out, err = run("run", "list", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rows = {r["slug"]: r for r in json.loads(out)["contracts"]}
        self.assertIn("broken", rows, "a silent omission would look like finished work")
        self.assertIn("error", rows["broken"])

    def test_backups_are_not_contracts(self):
        self.track("a")
        backups = [f for f in os.listdir(os.path.join(self.tmp, ".riel", "runs"))
                   if f.endswith(".bak.md")]
        self.assertTrue(backups, "activation backs the draft up next to the contract")
        rc, out, err = run("run", "list", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual([r["slug"] for r in json.loads(out)["contracts"]], ["a"])
        rc, _o, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 0, "one contract plus its backup is still unambiguous: " + err)

    def test_a_selector_accepts_a_path(self):
        self.track("a"); self.track("b")
        rc, out, err = run("run", "status", "--run", ".riel/runs/b.md", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["shaping"]["path"], ".riel/shapings/b.md")

    def test_an_unknown_selector_names_what_exists(self):
        self.track("a")
        rc, _o, err = run("run", "status", "--run", "nope", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("no contract named 'nope'", err)
        self.assertIn("have: a", err)

    def test_note_needs_a_selector_when_several_are_active(self):
        self.track("a"); self.track("b")
        rc, _o, err = run("note", "--gate", "G1", "--claim", "P1",
                          "--command", "true", "--covering", "x", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("pass run=<slug>", err)
        rc, _o, err = run("note", "--run", "b", "--gate", "G1", "--claim", "P1",
                          "--command", "true", "--covering", "x", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.status("b")["gates"]["G1"], "passed")
        self.assertEqual(self.status("a")["gates"]["G1"], "pending",
                         "evidence for one track never advances another")

    def test_a_contract_is_never_moved(self):
        self.track("a", finish=True)
        self.assertTrue(os.path.isfile(self.run_path("a")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, ".riel", "run.md")))
        rc, _o, err = run("run", "archive", cwd=self.tmp)
        self.assertEqual(rc, 2, "archive is gone: there is nothing to move")


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

<!-- riel-shaping/v3 id:shp_0a1b2c3d -->

## Question
Does the engine read one state file?

## Answer
In one file, cut at Metadata — supported by F1

## Findings

### F1: the single run.md parse works
The cut is `## Metadata`.
— source: scratch probe, confidence high

## Facts
- stdlib only.

## Not wanted
- A1: two files — pro: separation / contra: drift — verdict: discarded: drift

## What we want
- We need one file
- Claim seeds: the parser reads it — supported by F1
- Scope: in engine · out ui

## Open
- Q1: does the reader survive a partial write? — settled by: kill -9 mid-rename
"""

    @staticmethod
    def anchored(text):
        return text.replace(
            "- P1: the parser reads the phase outline — anchor: §F1#1",
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
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"), exist_ok=True)
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
                 question="Does the engine read one state file?", findings=None):
    """A valid riel-shaping/v3 source — the fixture the binding tests share.

    `findings` accepts the old bullet spelling for convenience and is converted
    to dossiers; the Answer cites the first finding so the fixture stays valid.
    """
    bullets = findings or [
        "- F1: the single run.md parse works — source: scratch probe, confidence high"]
    dossiers, first = [], None
    for bullet in bullets:
        body = bullet.lstrip("- ")
        fid, _, rest = body.partition(":")
        claim, _, source = rest.partition(" — source: ")
        fid = fid.strip()
        first = first or fid
        dossiers.append("### {}: {}\n— source: {}".format(
            fid, claim.strip(), source.strip() or "scratch probe"))
    return shaping_v3(name=name, uid=uid, question=question,
                      answer="In one file, cut at Metadata — supported by " + (first or "F1"),
                      findings="\n\n".join(dossiers) + "\n")



class ShapingBindingTests(TempDirTest):
    """One run binds ONE shaping: by uid, path and sha256 — never by guesswork."""

    def write_shaping(self, slug="engine", **kw):
        path = self.shaping_path(slug)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(shaping_text(name=slug, **kw))
        return path

    def write_run(self, text):
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"), exist_ok=True)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(text)

    def undecorated_anchored_run(self, anchor="shaping:F1"):
        """A pre-v2 run: anchors into a shaping, but declares nothing."""
        return LIST_RUN.replace(
            "- P1: the parser reads the phase outline — anchor: §F1#1",
            "- P1: the parser reads the list register — anchor: " + anchor)

    def anchored_run(self, slug="engine", anchor="shaping:F1"):
        text = LIST_RUN.replace(
            "- P1: the parser reads the phase outline — anchor: §F1#1",
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
            "- P1: the parser reads the phase outline — anchor: §F1#1",
            "- P1: the parser reads the list register — anchor: shaping:F1"))
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("binds no shaping", out + err)

    # ------------------------------------------------------- migration ----
    def loose(self, text):
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"), exist_ok=True)
        with open(self.loose_shaping_path(), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_a_loose_shaping_file_is_not_read(self):
        """There is no canonical loose shaping any more: shapings/ or nothing."""
        self.loose(shaping_text())
        self.write_run(self.undecorated_anchored_run())
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("binds no shaping", out + err)
        self.assertTrue(os.path.exists(self.loose_shaping_path()),
                        "the loose file is not migrated, not touched, not read")
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, ".riel", "shapings")))
    def test_a_pre_v3_run_is_refused(self):
        """No legacy support: a run without definition_sha256 is stale, not read."""
        self.write_shaping()
        self.write_run(self.anchored_run())
        rc, _out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        body = self.read_run()
        head, state = body.split("## Metadata", 1)
        state = state.replace("- definition_sha256:", "- plan_sha256:")
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(head + "## Metadata" + state)
        rc, _out, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 3, "the pre-rename key is not read: " + err)
        self.assertIn("stale state", err)


def shaping_v3(name="engine", uid="shp_0a1b2c3d",
               question="Does the engine read one state file?",
               answer="In one file, cut at Metadata — supported by F1",
               findings=None, sections=None):
    """A valid riel-shaping/v3 source: dossiers, an Answer, and Open last."""
    findings = findings if findings is not None else (
        "### F1: the single run.md parse works\n"
        "The cut is `## Metadata`; above it is authored, below it is engine-written.\n"
        "— source: scratch probe, confidence high\n")
    parts = {
        "Question": question,
        "Answer": answer,
        "Findings": findings,
        "Facts": "- stdlib only.",
        "Not wanted": "- A1: two files — pro: separation / contra: drift — verdict: discarded: drift",
        "What we want": ("- We need one file\n"
                         "- Claim seeds: the parser reads it — supported by F1\n"
                         "- Scope: in engine · out ui"),
        "Open": "- Q1: does the reader survive a partial write? — settled by: kill -9 mid-rename",
    }
    order = sections if sections is not None else list(parts)
    body = "\n\n".join("## {}\n{}".format(k, parts[k]) for k in order if k in parts)
    return "# Shaping: {}\n\n<!-- riel-shaping/v3 id:{} -->\n\n{}\n".format(name, uid, body)


class ShapingV3Tests(TempDirTest):
    """v3: the answer is a first-class line, findings are dossiers, Open is last."""

    def write(self, text, slug="engine"):
        path = self.shaping_path(slug)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def validate(self, text):
        return run("shape", "validate", self.write(text), cwd=self.tmp)

    def test_a_valid_v3_shaping_passes(self):
        rc, out, err = self.validate(shaping_v3())
        self.assertEqual(rc, 0, out + err)
        self.assertIn("1 finding(s)", out)

    def test_a_dossier_may_carry_its_own_diagram(self):
        os.makedirs(os.path.join(self.tmp, "engine"), exist_ok=True)
        with open(os.path.join(self.tmp, "engine", "run.py"), "w", encoding="utf-8") as fh:
            fh.write("\n".join("# line {}".format(i) for i in range(1, 450)) + "\n")
        findings = ("### F1: one file holds both halves\n"
                    "The cut is Metadata.\n"
                    "— source: engine/run.py:442, confidence high\n\n"
                    "#### Diagram\n```mermaid\nflowchart TD\n  A[\"run.md\"] --> B[\"Definition\"]\n```\n")
        rc, out, err = self.validate(shaping_v3(findings=findings))
        self.assertEqual(rc, 0, out + err)

    def test_the_answer_is_mandatory(self):
        rc, out, _err = self.validate(shaping_v3(sections=[
            "Question", "Findings", "Facts", "Not wanted", "What we want", "Open"]))
        self.assertEqual(rc, 1)
        self.assertIn("missing shaping section: Answer", out)

    def test_an_empty_answer_is_refused(self):
        rc, out, _err = self.validate(shaping_v3(answer=""))
        self.assertEqual(rc, 1)
        self.assertIn("## Answer is empty", out)

    def test_a_multiline_answer_is_refused(self):
        rc, out, _err = self.validate(shaping_v3(answer="In one file.\nAnd it is cut at Metadata."))
        self.assertEqual(rc, 1)
        self.assertIn("## Answer must be ONE line", out)

    def test_an_answer_that_is_a_question_is_refused(self):
        rc, out, _err = self.validate(shaping_v3(answer="Maybe in one file? — supported by F1"))
        self.assertEqual(rc, 1)
        self.assertIn("must not be a question", out)

    def test_an_answer_without_backing_is_refused(self):
        rc, out, _err = self.validate(shaping_v3(answer="In one file, because it is simpler"))
        self.assertEqual(rc, 1)
        self.assertIn("needs evidence", out)

    def test_an_answer_citing_a_missing_finding_is_refused(self):
        rc, out, _err = self.validate(shaping_v3(answer="In one file — supported by F9"))
        self.assertEqual(rc, 1)
        self.assertIn("cites F9 which is not a finding", out)

    def test_an_owner_decision_backs_an_answer(self):
        rc, out, err = self.validate(shaping_v3(answer="In one file — decided by: owner"))
        self.assertEqual(rc, 0, out + err)

    def test_open_must_be_last(self):
        rc, out, _err = self.validate(shaping_v3(sections=[
            "Question", "Answer", "Findings", "Facts", "Not wanted", "Open", "What we want"]))
        self.assertEqual(rc, 1)
        self.assertIn("out of order", out)
        self.assertIn("Open goes last", out)

    def test_a_missing_section_is_refused(self):
        rc, out, _err = self.validate(shaping_v3(sections=[
            "Question", "Answer", "Findings", "Facts", "What we want", "Open"]))
        self.assertEqual(rc, 1)
        self.assertIn("missing shaping section: Not wanted", out)

    def test_duplicate_dossier_ids_are_refused(self):
        findings = ("### F1: first\n— source: a.py:1, confidence high\n\n"
                    "### F1: again\n— source: b.py:2, confidence high\n")
        rc, out, _err = self.validate(shaping_v3(findings=findings))
        self.assertEqual(rc, 1)
        self.assertIn("duplicate finding id(s): F1", out)

    def test_a_dossier_without_a_source_is_refused(self):
        rc, out, _err = self.validate(shaping_v3(findings="### F1: a claim with no evidence\nJust prose.\n"))
        self.assertEqual(rc, 1)
        self.assertIn("F1 has no `— source:`", out)

    def test_a_raw_shaping_template_is_refused_and_names_what_is_missing(self):
        rc, draft, err = run("shape", "new", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        path = self.write(draft)
        rc, out, _err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("unfilled placeholder(s) in the shaping", out)
        for name in ("{{question}}", "{{answer}}", "{{fact}}"):
            self.assertIn(name, out)

    def test_one_leftover_shaping_placeholder_is_refused(self):
        path = self.write(shaping_v3().replace("- stdlib only.", "- {{fact}}"))
        rc, out, _err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("{{fact}}", out)

    def test_a_shaping_placeholder_inside_a_comment_is_not_data(self):
        path = self.write(shaping_v3() + "\n<!-- example: {{not_a_field}} -->\n")
        rc, out, err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)

    def test_a_v2_shaping_is_refused(self):
        old = shaping_text().replace("<!-- riel-shaping/v3 id:", "<!-- riel-shaping/v2 id:")
        rc, out, _err = self.validate(old)
        self.assertEqual(rc, 1)
        self.assertIn("riel-shaping/v3", out)
    def test_the_basis_freezes_the_claim_not_the_dossier_body(self):
        os.makedirs(os.path.join(self.tmp, "engine"), exist_ok=True)
        with open(os.path.join(self.tmp, "engine", "run.py"), "w", encoding="utf-8") as fh:
            fh.write("\n".join("# line {}".format(i) for i in range(1, 450)) + "\n")
        findings = ("### F1: one file holds both halves\n"
                    "A long body paragraph that must NOT travel into a slice.\n"
                    "— source: engine/run.py:442, confidence high\n\n"
                    "#### Diagram\n```mermaid\nflowchart TD\n  A[\"x\"] --> B[\"y\"]\n```\n")
        self.write(shaping_v3(findings=findings))
        text = LIST_RUN.replace(
            "- P1: the parser reads the phase outline — anchor: §F1#1",
            "- P1: the parser reads the list register — anchor: shaping:F1")
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"), exist_ok=True)
        with open(self.run_path(), "w", encoding="utf-8") as fh:
            fh.write(self.declared(text))
        rc, out, err = run("run", "activate", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        body = self.read_run()
        basis = body.split("### Basis", 1)[1].split("## Constraints", 1)[0]
        self.assertIn("- F1: one file holds both halves", basis)
        self.assertIn("— source: engine/run.py:442", basis)
        self.assertIn("— confidence: high", basis)
        self.assertNotIn("long body paragraph", basis)
        self.assertNotIn("mermaid", basis)


class CleanAndArchiveTests(TempDirTest):
    """clean wipes ALL of .riel/ (archiving opt-in); runs/ is never pruned."""

    def seed_layout(self):
        self.activate(text=LIST_RUN, shaping=shaping_text(), slug="engine")
        riel = os.path.join(self.tmp, ".riel")
        extra = {
            "project.md": "# Project: demo\n",
            "shapings/sibling.md": shaping_text(name="sibling", uid="shp_0000000f"),
            "runs/old.txt": "# an older proof, not a contract\n",
            "shaping.md": shaping_text(name="loose", uid="shp_0000000e"),
            "contract.md": "# old state\n",
            "ledger.md": "# old state\n",
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
                         "clean wipes run, project, shapings/, runs/, old files and backups")
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
        archives = list(Path(self.tmp).glob(".riel/archive/*"))
        self.assertEqual(len(archives), 1, out)
        archive = archives[0]
        for rel, body in before.items():
            with open(os.path.join(str(archive), rel), "rb") as fh:
                self.assertEqual(fh.read(), body, "archive byte mismatch: " + rel)
        self.assertEqual(self.entries(), [".run.lock", "archive"])
        shutil.copytree(str(archive), os.path.join(self.tmp, ".riel"),
                        dirs_exist_ok=True)
        # the restore is byte-complete, old files included — and state
        # still refuses v2 reads, so archive those two before reading the run
        for legacy in ("contract.md", "ledger.md"):
            os.unlink(os.path.join(self.tmp, ".riel", legacy))
        st = self.status()
        self.assertEqual(st["status"], "active", "the restore brings the run back")
        self.assertEqual(st["shaping"]["id"], "shp_0a1b2c3d")

    def test_clean_writes_nothing_outside_riel(self):
        self.seed_layout()
        rc, out, err = run("clean", "--archive", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(sorted(os.listdir(self.tmp)), [".riel"],
                         "the archive lands inside .riel/, not beside the worktree")

    def test_a_later_clean_keeps_the_earlier_archive_and_never_nests_it(self):
        self.seed_layout()
        run("clean", "--archive", cwd=self.tmp)
        with open(os.path.join(self.tmp, ".riel", "project.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("# Project: second\n")
        rc, out, err = run("clean", "--archive", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        archives = sorted(Path(self.tmp, ".riel", "archive").iterdir())
        self.assertEqual(len(archives), 2, "an earlier snapshot is history, not state")
        self.assertTrue(all((a / "project.md").is_file() for a in archives))
        self.assertFalse((archives[-1] / "archive").exists(),
                         "an archive never copies itself into the next one")

    def test_a_contract_stays_in_place_and_keeps_the_binding(self):
        """Executed where it was authored: there is no live file and no move."""
        self.activate(text=self.declared(LIST_RUN), shaping=shaping_text())
        path = self.run_path()
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.basename(os.path.dirname(path)), "runs")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("- shaping_id: shp_0a1b2c3d", body)
        self.assertIn("- shaping: .riel/shapings/engine.md", body)
        self.assertFalse(self.status()["done"], "an unfinished contract is not proof yet")

    def test_two_tracks_coexist_in_one_worktree(self):
        """Parallel tracks: several active contracts, one selector to pick."""
        self.activate(text=LIST_RUN, shaping=shaping_text(name="a", uid=slug_uid("a")), slug="a")
        self.activate(text=LIST_RUN, shaping=shaping_text(name="b", uid=slug_uid("b")), slug="b")
        rc, out, err = run("run", "list", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        contracts = json.loads(out)["contracts"]
        self.assertEqual([c["slug"] for c in contracts], ["a", "b"])
        self.assertTrue(all(c["status"] == "active" for c in contracts))
        rc, _out, err = run("run", "status", cwd=self.tmp)
        self.assertEqual(rc, 2, "two active contracts need a selector")
        self.assertIn("pass run=<slug>", err)
        rc, out, err = run("run", "status", "--run", "b", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["shaping"]["path"], ".riel/shapings/b.md")

    def test_contracts_are_never_pruned(self):
        for i in range(5):
            slug = "track{}".format(i)
            self.activate(text=LIST_RUN,
                          shaping=shaping_text(name=slug, uid="shp_%08x" % i),
                          slug=slug)
        runs = sorted(f for f in os.listdir(os.path.join(self.tmp, ".riel", "runs"))
                      if not f.endswith(".bak.md"))
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
        os.makedirs(os.path.join(self.tmp, ".riel", "runs"), exist_ok=True)
        text = body if body is not None else (
            "# Project: demo\n\n<!-- riel-project/v1 -->\n\n"
            "## Objective\nShip the demo in two tracks.\n\n"
            "## Graph\n- S1: .riel/shapings/a.md\n- S2: .riel/shapings/b.md\n")
        path = os.path.join(self.tmp, ".riel", "project.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_for(self, slug, finish=False):
        """Author a contract for one shaping — it stays in runs/, no move."""
        self.activate(text=LIST_RUN, shaping=shaping_text(
            name=slug, uid=slug_uid(slug)), slug=slug)
        if finish:
            for gate, claim in (("G1", "P1"), ("G2", "P2")):
                rc, _out, err = run("note", "--run", slug, "--gate", gate,
                                    "--claim", claim, "--command", "true",
                                    "--covering", claim, cwd=self.tmp)
                self.assertEqual(rc, 0, err)
            self.assertTrue(self.status(slug)["done"])

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

    def test_an_unfinished_contract_is_active_not_done(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        self.run_for("a", finish=False)
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S1"]["status"], "active")
        self.assertEqual(st["nodes"]["S1"]["run"], ".riel/runs/a.md")
        self.assertFalse(st["done"])

    def test_the_live_run_makes_its_shaping_active(self):
        self.shaping("a"); self.shaping("b")
        self.project()
        self.activate(text=LIST_RUN, shaping=shaping_text(
            name="a", uid=slug_uid("a")), slug="a")
        st = self.pstatus()
        self.assertEqual(st["nodes"]["S1"]["status"], "active")
        self.assertEqual(st["nodes"]["S1"]["run"], ".riel/runs/a.md")

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


class FrozenGateTests(TempDirTest):
    """Frozen gate commands prevent substituting weaker commands at note time."""

    @staticmethod
    def engine():
        spec = importlib.util.spec_from_file_location("riel_engine_frozen", ENGINE)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_parse_frozen_gate_formats_and_warning(self):
        eng = self.engine()
        text = LIST_RUN.replace(
            "- G1: parser tests pass",
            "- G1: parser tests pass — cmd: python3 -c \"print('ok')\"",
        ).replace(
            "- G2: verbs wired",
            "- G2: `true` — verbs wired",
        )
        gates = eng._parse_gates(text)
        self.assertEqual(gates[0]["label"], "parser tests pass")
        self.assertEqual(gates[0]["command"], "python3 -c \"print('ok')\"")
        self.assertEqual(gates[1]["label"], "verbs wired")
        self.assertEqual(gates[1]["command"], "true")

        bt_only = LIST_RUN.replace("- G1: parser tests pass", "- G1: `make test`")
        self.assertEqual(eng._parse_gates(bt_only)[0]["label"], "make test")
        self.assertEqual(eng._parse_gates(bt_only)[0]["command"], "make test")

        # Unfrozen gate emits a warning, not an issue
        nodes, edges, _r = eng.contract_graph(LIST_RUN)
        issues, warnings = eng._check_definition(LIST_RUN, nodes, edges, "", False, [])
        self.assertEqual(issues, [])
        self.assertTrue(any("G1 has no frozen command" in w for w in warnings), warnings)

    def test_frozen_gate_auto_runs_and_refuses_substitution(self):
        text = LIST_RUN.replace(
            "- G1: parser tests pass",
            "- G1: parser tests pass — cmd: python3 -c \"open('ran_frozen.txt','w').write('ok')\"",
        ).replace(
            "- G2: verbs wired",
            "- G2: `true` -- verbs wired",
        )
        self.activate(text=text)
        # Omitting --command runs the frozen command automatically
        rc, out, err = run("note", "--gate", "G1", "--claim", "P1",
                           "--covering", "frozen auto", cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "ran_frozen.txt")))
        self.assertEqual(self.status()["gates"]["G1"], "passed")

        # Substituting a different command is refused
        rc, _out, err = run("note", "--gate", "G2", "--command", "echo fake",
                            "--covering", "sub", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("frozen to command", err)

        # Whitespace-normalized matching command is accepted
        rc, _out, err = run("note", "--gate", "G2", "--claim", "P2",
                            "--command", "  true  ", "--covering", "exact",
                            cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertTrue(self.status()["done"])

    def test_multi_gate_frozen_mismatch_refused_and_shared_runs(self):
        text = LIST_RUN.replace(
            "- G1: parser tests pass", "- G1: g1 — cmd: true"
        ).replace(
            "- G2: verbs wired", "- G2: g2 — cmd: echo two"
        )
        self.activate(text=text)
        rc, _out, err = run("note", "--gate", "G1", "--gate", "G2",
                            "--covering", "both", cwd=self.tmp)
        self.assertEqual(rc, 2)
        self.assertIn("different frozen commands", err)

        text_same = LIST_RUN.replace(
            "- G1: parser tests pass", "- G1: g1 — cmd: true"
        ).replace(
            "- G2: verbs wired", "- G2: g2 — cmd: true"
        )
        shutil.rmtree(os.path.join(self.tmp, ".riel"))
        self.activate(text=text_same)
        rc, _out, err = run("note", "--gate", "G1", "--gate", "G2",
                            "--covering", "shared", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.status()["gates"], {"G1": "passed", "G2": "passed"})


class GateFeedbackAndStuckTests(TempDirTest):
    """Failure output tail, .riel/logs/<E#>.log, focus card, and stuck breaker."""

    def test_failure_prints_multiline_tail_and_writes_log(self):
        self.activate()
        cmd = "python3 -c \"import sys; print('line one'); print('line two'); sys.exit(3)\""
        rc, out, err = run("note", "--gate", "G1", "--command", cmd,
                           "--covering", "fail check", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("gate_exit_code: 3 | gate_passed: false", out)
        self.assertIn("--- gate output (exit 3) ---", out)
        self.assertIn("line one\nline two", out)
        self.assertIn("log: .riel/logs/E1.log", out)
        self.assertIn("focus phase: F1", out)
        self.assertIn("pending_gates:", out)
        self.assertIn("open_claims:", out)
        self.assertIn("do_not:", out)
        log_file = os.path.join(self.tmp, ".riel", "logs", "E1.log")
        self.assertTrue(os.path.isfile(log_file))
        with open(log_file, encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "line one\nline two")

    def test_long_passing_output_writes_log_and_keeps_snippet_short(self):
        self.activate()
        cmd = "python3 -c \"print('x' * 500)\""
        rc, out, err = run("note", "--gate", "G1", "--command", cmd,
                           "--covering", "long output", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("log: .riel/logs/E1.log", out)
        log_file = os.path.join(self.tmp, ".riel", "logs", "E1.log")
        self.assertTrue(os.path.isfile(log_file))
        with open(log_file, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().strip()), 500)

    def test_stuck_breaker_warns_after_three_failures_and_resets_on_pass(self):
        self.activate()
        run("note", "--core", "parser — single pass", cwd=self.tmp)
        for i in range(2):
            rc, out, err = run("note", "--gate", "G1", "--command", "false",
                               "--covering", "try {}".format(i), cwd=self.tmp)
            self.assertEqual(rc, 0, err)
            self.assertNotIn("STUCK WARNING", out)
        self.assertEqual(self.status()["stuck_gates"], {})

        rc, out, err = run("note", "--gate", "G1", "--command", "false",
                           "--covering", "try 3", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("STUCK WARNING: G1 failed 3 consecutive times", out)
        self.assertIn("core: parser — single pass", out)
        self.assertEqual(self.status()["stuck_gates"], {"G1": 3})

        rc, out, err = run("note", "--gate", "G1", "--claim", "P1",
                           "--command", "true", "--covering", "fixed",
                           cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertNotIn("STUCK WARNING", out)
        self.assertEqual(self.status()["stuck_gates"], {})


class GitTreeAndScopeTests(TempDirTest):
    """Git tree_sha, dirty_since_evidence, diff_stat, and allow/deny scope rules."""

    def init_git(self):
        subprocess.run(["git", "init"], cwd=self.tmp, check=True,
                       capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"],
                       cwd=self.tmp, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"],
                       cwd=self.tmp, check=True, capture_output=True)
        os.makedirs(os.path.join(self.tmp, "src"), exist_ok=True)
        with open(os.path.join(self.tmp, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# repo\n")
        with open(os.path.join(self.tmp, "src", "app.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        subprocess.run(["git", "add", "README.md", "src/app.py"],
                       cwd=self.tmp, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"],
                       cwd=self.tmp, check=True, capture_output=True)

    def scoped_run(self):
        return LIST_RUN.replace(
            "- stdlib only.",
            "- stdlib only.\n- allow: src/**, tests/**"
        ).replace(
            "- touch tools.py.",
            "- touch tools.py.\n- deny: src/secret.txt"
        )

    def test_dirty_since_evidence_and_test_file_warning(self):
        self.init_git()
        self.activate(text=self.scoped_run())
        with open(os.path.join(self.tmp, "src", "app.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 2\n")
        rc, out, err = run("note", "--gate", "G1", "--claim", "P1",
                           "--command", "true", "--covering", "p1",
                           cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("diff: 1 file(s) (src/app.py)", out)
        body = self.read_run()
        self.assertRegex(body, r"tree:[0-9a-f]{12}\s+files:1")

        rc, out, err = run("note", "--gate", "G2", "--claim", "P2",
                           "--command", "true", "--covering", "p2",
                           cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        st = self.status()
        self.assertFalse(st["dirty_since_evidence"])
        self.assertTrue(st["done"])

        # Edit a tracked file AFTER passing evidence -> dirty_since_evidence vetoes done
        with open(os.path.join(self.tmp, "src", "app.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 3\n")
        st = self.status()
        self.assertTrue(st["dirty_since_evidence"])
        self.assertFalse(st["done"])

        # Modifying a test file emits a diff warning, and re-running gate clears dirty
        os.makedirs(os.path.join(self.tmp, "tests"), exist_ok=True)
        with open(os.path.join(self.tmp, "tests", "test_app.py"), "w", encoding="utf-8") as fh:
            fh.write("assert True\n")
        rc, out, err = run("note", "--gate", "G2", "--claim", "P2",
                           "--command", "true", "--covering", "rerun",
                           cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("WARNING: modified test files: tests/test_app.py", out)
        st = self.status()
        self.assertFalse(st["dirty_since_evidence"])
        self.assertTrue(st["done"])

    def test_scope_violations_block_done_and_warn(self):
        self.init_git()
        self.activate(text=self.scoped_run())
        with open(os.path.join(self.tmp, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("# outside allow\n")
        with open(os.path.join(self.tmp, "src", "secret.txt"), "w", encoding="utf-8") as fh:
            fh.write("nope\n")
        rc, out, err = run("note", "--gate", "G1", "--claim", "P1",
                           "--command", "true", "--covering", "p1",
                           cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        self.assertIn("SCOPE VIOLATION:", out)
        self.assertIn("README.md", out)
        self.assertIn("src/secret.txt", out)
        run("note", "--gate", "G2", "--claim", "P2",
            "--command", "true", "--covering", "p2", cwd=self.tmp)
        st = self.status()
        self.assertEqual(st["scope_violations"], ["README.md", "src/secret.txt"])
        self.assertFalse(st["done"])

    def test_glob_matcher_supports_double_star_and_single_star(self):
        spec = importlib.util.spec_from_file_location("riel_engine_glob", ENGINE)
        assert spec is not None and spec.loader is not None
        eng = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(eng)
        self.assertTrue(eng._glob_match("docs/a.md", "docs/**"))
        self.assertTrue(eng._glob_match("docs/sub/b.md", "docs/**"))
        self.assertFalse(eng._glob_match("src/a.md", "docs/**"))
        self.assertTrue(eng._glob_match("README.md", "*.md"))
        self.assertFalse(eng._glob_match("docs/a.md", "*.md"))
        self.assertTrue(eng._glob_match("docs/sub/a.md", "**/*.md"))


class SourceVerificationTests(TempDirTest):
    """Shaping `— source:` file/line/symbol verification against the worktree."""

    def write_shaping(self, source_line, slug="engine"):
        findings = ("### F1: claim text\n"
                    "Support.\n"
                    "— source: {}\n").format(source_line)
        path = self.shaping_path(slug)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(shaping_v3(name=slug, findings=findings))
        return path

    def test_valid_repo_source_with_lines_and_symbol_passes(self):
        os.makedirs(os.path.join(self.tmp, "src"), exist_ok=True)
        with open(os.path.join(self.tmp, "src", "mod.py"), "w", encoding="utf-8") as fh:
            fh.write("def alpha():\n    return 1\n\ndef beta():\n    return 2\n")
        path = self.write_shaping("repo@HEAD:src/mod.py:1-5#beta, confidence high")
        rc, out, err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(err, "")

    def test_missing_file_out_of_range_lines_and_missing_symbol_fail(self):
        path = self.write_shaping("repo@HEAD:src/missing.py:1-2#sym")
        rc, out, _err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("source file not found in worktree: src/missing.py", out)

        os.makedirs(os.path.join(self.tmp, "src"), exist_ok=True)
        with open(os.path.join(self.tmp, "src", "mod.py"), "w", encoding="utf-8") as fh:
            fh.write("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
        path = self.write_shaping("src/mod.py:1-99#alpha")
        rc, out, _err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("out of bounds", out)

        path = self.write_shaping("src/mod.py:1-3#no_such_symbol")
        rc, out, _err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("source symbol #no_such_symbol not found", out)

        # Symbol exists in file, outside the cited line range -> warning, not error
        path = self.write_shaping("src/mod.py:1-2#beta")
        rc, out, err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 0, out + err)
        self.assertIn("WARN:", err)
        self.assertIn("outside lines 1-2", err)

    def test_non_file_sources_and_traversal(self):
        for src in ("http://example.com:8080/a", "https://example.com/a:1",
                    "cmd: pytest:1", "benchmark: run 1:2", "scratch probe"):
            path = self.write_shaping(src)
            rc, out, err = run("shape", "validate", path, cwd=self.tmp)
            self.assertEqual(rc, 0, src + ": " + out + err)

        path = self.write_shaping("../outside.py:1")
        rc, out, _err = run("shape", "validate", path, cwd=self.tmp)
        self.assertEqual(rc, 1)
        self.assertIn("escapes worktree", out)


class DagAndFocusTests(TempDirTest):
    """Real DAG phase derivation, ready_phases, and focus card in status."""

    DIAMOND_RUN = """# Run: diamond
<!-- riel-run/v1 -->

## Objective
Diamond DAG execution.

## Context

### Why
Parallel phases converge cleanly.

### Context keywords
- dag → graph

## Deliverable
Four phases done.

## Constraints
- stdlib only.

## DO NOT
- skip F3.

## Phases
```mermaid
flowchart TD
  F1["root"] --> F2["left"]
  F1 --> F3["right"]
  F2 --> F4["join"]
  F3 --> F4
```

### F1: root
- RUN echo f1

#### Claims
- P1: root holds — anchor: §F1#1

#### Gates
- G1: root gate — cmd: true

#### Deliverable
- root built

### F2: left
- RUN echo f2

#### Claims
- P2: left holds — anchor: §F2#1

#### Gates
- G2: left gate — cmd: true

#### Deliverable
- left built

### F3: right
- RUN echo f3

#### Claims
- P3: right holds — anchor: §F3#1

#### Gates
- G3: right gate — cmd: true

#### Deliverable
- right built

### F4: join
- RUN echo f4

#### Claims
- P4: join holds — anchor: §F4#1

#### Gates
- G4: join gate — cmd: true

#### Deliverable
- join built
"""

    def test_diamond_dag_ready_phases_and_focus_card(self):
        self.activate(text=self.DIAMOND_RUN, slug="diamond")
        st = self.status("diamond")
        self.assertEqual(st["ready_phases"], ["F1"])
        self.assertEqual(st["current_phase"], "F1")
        self.assertEqual(st["focus"]["phase"], "F1")
        self.assertEqual(st["focus"]["deliverable"], ["root built"])
        self.assertEqual(st["focus"]["pending_gates"],
                         [{"id": "G1", "label": "root gate", "command": "true"}])
        self.assertEqual(st["focus"]["open_claims"],
                         [{"id": "P1", "text": "root holds"}])
        self.assertEqual(st["focus"]["do_not"], ["skip F3."])

        run("note", "--run", "diamond", "--gate", "G1", "--claim", "P1",
            "--covering", "f1", cwd=self.tmp)
        st = self.status("diamond")
        self.assertEqual(st["ready_phases"], ["F2", "F3"])
        self.assertEqual(st["current_phase"], "F2")

        run("note", "--run", "diamond", "--gate", "G2", "--claim", "P2",
            "--covering", "f2", cwd=self.tmp)
        st = self.status("diamond")
        self.assertEqual(st["ready_phases"], ["F3"])
        self.assertEqual(st["current_phase"], "F3")

        run("note", "--run", "diamond", "--gate", "G3", "--claim", "P3",
            "--covering", "f3", cwd=self.tmp)
        st = self.status("diamond")
        self.assertEqual(st["ready_phases"], ["F4"])
        self.assertEqual(st["current_phase"], "F4")

        run("note", "--run", "diamond", "--gate", "G4", "--claim", "P4",
            "--covering", "f4", cwd=self.tmp)
        st = self.status("diamond")
        self.assertEqual(st["ready_phases"], [])
        self.assertIsNone(st["current_phase"])
        self.assertTrue(st["done"])

    def test_mermaid_decision_loop_tracks_phase_dependency(self):
        self.activate(text=MERMAID_RUN, slug="mermaid")
        # Passing G2 before G1 must NOT complete F2 because F1 -> D1 -> F2
        run("note", "--run", "mermaid", "--gate", "G2", "--claim", "P2",
            "--command", "true", "--covering", "g2", cwd=self.tmp)
        st = self.status("mermaid")
        self.assertEqual(st["ready_phases"], ["F1"])
        self.assertEqual(st["current_phase"], "F1")


class PostelParserTests(TempDirTest):
    """Em-dash (—), double-hyphen (--), and en-dash (–) clause separators."""

    def test_postel_separators_and_version(self):
        spec = importlib.util.spec_from_file_location("riel_engine_postel", ENGINE)
        assert spec is not None and spec.loader is not None
        eng = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(eng)
        self.assertEqual(eng.VERSION, "5.0.0")

        self.assertEqual(eng._clauses("a -- b – c — d"), ["a", "b", "c", "d"])
        shaping = (
            "# Shaping: postel\n\n"
            "<!-- riel-shaping/v3 id:shp_12345678 -->\n\n"
            "## Question\nDoes Postel work?\n\n"
            "## Answer\nYes — supported by F1\n\n"
            "## Findings\n"
            "### F1: double hyphen works -- source: scratch probe, confidence high\n\n"
            "### F2: en dash works – source: memory probe, confidence med\n\n"
            "## Facts\n- ok\n\n## Not wanted\n- none\n\n"
            "## What we want\n- ok\n\n## Open\n- Q1: q? -- settled-by: test\n"
        )
        findings = eng.shaping_findings(shaping)
        self.assertEqual(findings[0]["text"], "double hyphen works")
        self.assertEqual(findings[0]["source"], "scratch probe")
        self.assertEqual(findings[1]["text"], "en dash works")
        self.assertEqual(findings[1]["source"], "memory probe")

        basis_md = "## Context\n\n### Basis\n- F1: fact -- source: probe -- confidence: high\n"
        basis = eng._parse_basis(basis_md)
        self.assertEqual(basis, [{"id": "F1", "text": "fact",
                                  "source": "probe", "confidence": "high"}])

        open_md = "## Open\n- Q1: question? – settled-by: pytest -- closed by: E1\n"
        opens = eng._parse_open(open_md)
        self.assertEqual(opens, [{"id": "Q1", "text": "question?",
                                  "settled_by": "pytest", "closed_by": "E1"}])

        # --core normalizes '--' or '–' to canonical ' — ' on write
        self.activate()
        rc, _out, err = run("note", "--core", "sep -- normalized", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        rc, _out, err = run("note", "--core", "endash – normalized", cwd=self.tmp)
        self.assertEqual(rc, 0, err)
        body = self.read_run()
        self.assertIn("- 1. sep — normalized", body)
        self.assertIn("- 2. endash — normalized", body)


if __name__ == "__main__":
    unittest.main()
