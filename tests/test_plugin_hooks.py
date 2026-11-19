"""Regression tests for the `pre_verify` gate (the Riel run rule, v2).

Stdlib-only and Hermes-free: the gate's decision is a pure function over a
worktree, so the whole contract is testable without an agent loop. The Hermes-
side dispatch (signature inspection, `invoke_hook`, the continue directive) is
exercised separately by `hermes_plugin/probe-session-cwd.py`, which needs a
real Hermes install.

The gate reads the ACTIVE run (`.riel/run.md`) through the engine's safe
in-process path — the suite points `hooks.tools` at the stub engine and drives
real gate commands (`true` / `false`) through `riel_note`. Claims and gates
are created by the DEFINITION (`stub.seed`); the note only ever executes gates and
records evidence. A worktree with no `.riel/run.md` is NEVER
gated.

Run:
    python3 -m unittest discover -s tests -v
"""

import importlib.machinery
import importlib.util
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

import _stub_engine as stub  # noqa: E402


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    if spec is None:  # pragma: no cover
        raise RuntimeError(f"could not build a module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class GateTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hooks = load_module("riel_hooks", PLUGIN / "hooks.py")
        # The gate reaches the engine through ITS tools reference — the same
        # object `assess` resolves — so installing the stub there covers the
        # whole gate without touching the packaged engine's file.
        stub.install(cls.hooks.tools)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-gate-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seed(self, claims=("P1",), gates=("G1",), **extra):
        """A prepared run: claims and gates exist, none executed yet."""
        return stub.seed(self.tmp, claims=list(claims), gates=list(gates), **extra)

    def run_gate(self, command, worktree=None, gates=("G1",), claims=("P1",)):
        """Execute a gate through the real handler path (the note wrapper)."""
        payload = json.loads(self.hooks.tools.riel_note({
            "gates": list(gates), "command": command, "covering": "all",
            "claims": list(claims), "worktree": worktree or self.tmp,
        }))
        self.assertEqual(payload["exit_code"], 0, payload)
        return payload


class FindWorktreeTest(GateTestCase):
    def test_walks_up_from_an_edited_file(self):
        self.seed()
        self.run_gate("false")
        nested = Path(self.tmp) / "lib" / "nested" / "file.ex"
        worktree = self.hooks.find_worktree([str(nested)])
        self.assertEqual(worktree, os.path.realpath(self.tmp))

    def test_no_run_anywhere_returns_none(self):
        other = tempfile.mkdtemp(prefix="riel-untracked-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertIsNone(self.hooks.find_worktree([str(Path(other) / "a.py")]))

    def test_a_worktree_without_a_run_is_never_gated(self):
        """An old .riel/ledger.md with no run.md is invisible to the gate."""
        ledger = Path(self.tmp) / ".riel" / "ledger.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("# Riel ledger\n\n## Goal\nold world\n", encoding="utf-8")
        self.assertIsNone(self.hooks.find_worktree([str(Path(self.tmp) / "a.py")]))

    def test_session_cwd_is_used_when_it_carries_a_run(self):
        self.seed()
        worktree = self.hooks.find_worktree([], session_cwd=self.tmp)
        self.assertEqual(worktree, os.path.realpath(self.tmp))

    def test_edited_files_win_over_the_session_cwd(self):
        """A turn can edit a worktree other than the one the session sits in."""
        other = tempfile.mkdtemp(prefix="riel-other-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.seed()
        stub.seed(other, claims=["P9"], gates=["G9"])
        self.run_gate("false", worktree=other, gates=("G9",), claims=("P9",))
        worktree = self.hooks.find_worktree([str(Path(other) / "lib" / "a.ex")],
                                            session_cwd=self.tmp)
        self.assertEqual(worktree, os.path.realpath(other))

    def test_junk_inputs_never_raise(self):
        for changed, cwd in ((None, None), ([], ""), ([None, 1], None), ([""], "   ")):
            with self.subTest(changed=changed, cwd=cwd):
                self.assertIsNone(self.hooks.find_worktree(changed, session_cwd=cwd))


class AssessTest(GateTestCase):
    def test_counts_claims_gates_and_the_pending_ones(self):
        self.seed(claims=("P1", "P2"))
        self.run_gate("false")
        facts = self.hooks.assess(self.tmp)
        self.assertTrue(facts["present"])
        self.assertEqual(facts["claims"], 2)
        self.assertEqual(facts["gates"], 1)
        self.assertEqual(facts["pending_claims"], 2)
        self.assertEqual(facts["pending_gates"], 1, "a failed gate is still pending")

    def test_a_passing_gate_closes_its_claims(self):
        self.seed()
        self.run_gate("true")
        facts = self.hooks.assess(self.tmp)
        self.assertEqual(facts["pending_claims"], 0)
        self.assertEqual(facts["pending_gates"], 0)

    def test_reports_whether_the_run_is_active(self):
        run = Path(self.tmp) / ".riel" / "run.md"
        run.parent.mkdir(parents=True)
        draft = {"active": False, "goal": "g", "next": "", "phase": "",
                 "claims": [], "gates": [], "evidence": [], "open": []}
        run.write_text("# Run\n\n```riel-state\n{}\n```\n".format(json.dumps(draft)),
                       encoding="utf-8")
        facts = self.hooks.assess(self.tmp)
        self.assertTrue(facts["present"])
        self.assertFalse(facts["active"])
        payload = json.loads(self.hooks.tools.riel_run({"verb": "activate",
                                                        "worktree": self.tmp}))
        self.assertEqual(payload["exit_code"], 0, payload)
        facts = self.hooks.assess(self.tmp)
        self.assertTrue(facts["active"])

    def test_absent_run_is_reported(self):
        facts = self.hooks.assess(self.tmp)
        self.assertFalse(facts["present"])
        self.assertIsNone(facts["error"])

    def test_junk_worktree_never_raises(self):
        for value in ("", "/dev/null", "\x00", None):
            with self.subTest(value=value):
                self.assertFalse(self.hooks.assess(value)["present"])

    def test_the_engine_status_shape_is_consumed(self):
        """The REAL `run status` shape: a status word + dict registers."""
        run = Path(self.tmp) / ".riel" / "run.md"
        run.parent.mkdir(parents=True)

        def fence(status, claims, gates):
            state = {"format": "riel-run/v1", "status": status, "claims": claims,
                     "gates": gates, "evidence": {"total": 0, "counted": 0},
                     "done": False, "next": "S2", "open": {}}
            run.write_text("# Run\n\n```riel-state\n{}\n```\n".format(json.dumps(state)),
                           encoding="utf-8")

        fence("active", {"P1": "open"}, {"G1": "pending"})
        facts = self.hooks.assess(self.tmp)
        self.assertTrue(facts["active"])
        self.assertEqual((facts["pending_claims"], facts["pending_gates"]), (1, 1))
        fence("active", {"P1": "covered"}, {"G1": "passed"})
        facts = self.hooks.assess(self.tmp)
        self.assertEqual((facts["pending_claims"], facts["pending_gates"]), (0, 0))
        fence("draft", {"P1": "open"}, {"G1": "pending"})
        self.assertFalse(self.hooks.assess(self.tmp)["active"])

    def test_a_corrupt_run_never_raises(self):
        run = Path(self.tmp) / ".riel" / "run.md"
        run.parent.mkdir(parents=True)
        run.write_text("# Run\n\n```riel-state\n{not json\n```\n", encoding="utf-8")
        facts = self.hooks.assess(self.tmp)
        self.assertTrue(facts["present"])
        self.assertTrue(facts["error"], "a corrupt state surfaces as an error, never a crash")
        self.assertIsNone(self.hooks.nudge_message(self.tmp, facts))


class NudgeMessageTest(GateTestCase):
    def test_pending_claims_and_gates_nudge(self):
        self.seed(claims=("P1",))
        self.run_gate("false")
        message = self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp))
        self.assertIsNotNone(message)
        self.assertIn("1 gate(s)", message)
        self.assertIn("1 claim(s)", message)
        self.assertIn("riel_note", message)
        self.assertIn("command", message, "the nudge names the gate execution shape")

    def test_a_verified_gate_closes_the_nudge(self):
        self.seed()
        self.run_gate("true")
        self.assertIsNone(self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp)))

    def test_an_inactive_run_is_not_the_gates_business(self):
        """The gate is opt-in per ACTIVATED run: a draft is never nudged."""
        run = Path(self.tmp) / ".riel" / "run.md"
        run.parent.mkdir(parents=True)
        draft = {"active": False, "goal": "g", "next": "", "phase": "",
                 "claims": [{"id": "P1", "text": "", "done": False}],
                 "gates": [{"id": "G1", "command": "", "covering": "",
                            "exit_code": None, "done": False}],
                 "evidence": [], "open": []}
        run.write_text("# Run\n\n```riel-state\n{}\n```\n".format(json.dumps(draft)),
                       encoding="utf-8")
        facts = self.hooks.assess(self.tmp)
        self.assertTrue(facts["pending_claims"])
        self.assertIsNone(self.hooks.nudge_message(self.tmp, facts))

    def test_message_names_the_worktree(self):
        self.seed()
        self.run_gate("false")
        message = self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp))
        self.assertIn(self.tmp, message)


class PreVerifyCallbackTest(GateTestCase):
    """The registered callback: the contract Hermes' hook dispatcher relies on."""

    def setUp(self):
        super().setUp()
        self.hooks.SETTINGS.update({"enabled": True, "attempts": 1})

    def paths(self):
        return [str(Path(self.tmp) / "lib" / "a.ex")]

    def test_continues_the_turn_while_the_active_run_has_pending_work(self):
        self.seed()
        self.run_gate("false")
        result = self.hooks.pre_verify(
            session_id="s1",
            platform="desktop",
            model="m",
            coding=True,
            attempt=0,
            final_response="listo",
            changed_paths=self.paths(),
        )
        self.assertEqual(result["action"], "continue")
        self.assertIn(os.path.realpath(self.tmp), result["message"])

    def test_allows_the_turn_to_close_once_the_gates_pass(self):
        self.seed()
        self.run_gate("true")
        self.assertIsNone(self.hooks.pre_verify(attempt=0, changed_paths=self.paths()))

    def test_self_throttles_after_the_configured_attempts(self):
        self.seed()
        self.run_gate("false")
        self.assertIsNotNone(self.hooks.pre_verify(attempt=0, changed_paths=self.paths()))
        self.assertIsNone(self.hooks.pre_verify(attempt=1, changed_paths=self.paths()))

    def test_respects_the_gate_setting(self):
        self.seed()
        self.run_gate("false")
        self.hooks.SETTINGS["enabled"] = False
        self.addCleanup(self.hooks.SETTINGS.update, {"enabled": True})
        self.assertIsNone(self.hooks.pre_verify(attempt=0, changed_paths=self.paths()))

    def test_untracked_worktree_is_never_gated(self):
        other = tempfile.mkdtemp(prefix="riel-untracked-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertIsNone(self.hooks.pre_verify(attempt=0, changed_paths=[str(Path(other) / "a.py")]))

    def test_no_changed_paths_and_no_session_record_declines(self):
        self.seed()
        self.assertIsNone(self.hooks.pre_verify(attempt=0, changed_paths=[]))

    def test_unknown_payload_fields_are_tolerated(self):
        """Hermes adds hook payload fields over time; registration must not break."""
        self.seed()
        self.run_gate("false")
        result = self.hooks.pre_verify(
            attempt=0,
            changed_paths=self.paths(),
            something_new_in_a_later_release={"a": 1},
            coding=False,
        )
        self.assertEqual(result["action"], "continue")

    def test_an_old_ledger_never_gates_the_turn(self):
        ledger = Path(self.tmp) / ".riel" / "ledger.md"
        ledger.parent.mkdir(parents=True)
        ledger.write_text("# Riel ledger\n", encoding="utf-8")
        self.assertIsNone(self.hooks.pre_verify(attempt=0, changed_paths=self.paths()))


if __name__ == "__main__":
    unittest.main()
