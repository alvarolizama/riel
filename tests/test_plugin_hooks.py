"""Regression tests for the `pre_verify` gate (the Riel checkpoint rule).

Stdlib-only and Hermes-free: the gate's decision is a pure function over a
worktree, so the whole contract is testable without an agent loop. The
Hermes-side dispatch (signature inspection, `invoke_hook`, the continue
directive) is exercised separately by `hermes_plugin/probe-session-cwd.py`,
which needs a real Hermes install.

Run:
    python3 -m unittest discover -s tests -v
"""

import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLUGIN = REPO / "hermes_plugin" / "riel"
VENDOR_RIELCTL = PLUGIN / "vendor" / "riel-cli" / "scripts" / "rielctl"

HAND_WRITTEN_NO_EVIDENCE = """# Riel ledger

## Goal
hand written ledger

## Verified
- ✓01 algo comprobado pero sin comando

## Next
seguir
"""


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

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-gate-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def seed(self, *argv):
        return self.seed_in(self.tmp, *argv)

    def seed_in(self, directory, *argv):
        proc = subprocess.run(
            [sys.executable, str(VENDOR_RIELCTL), *argv],
            cwd=directory,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def write_ledger(self, text):
        ledger = Path(self.tmp) / ".riel" / "ledger.md"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(text, encoding="utf-8")


class FindWorktreeTest(GateTestCase):
    def test_walks_up_from_an_edited_file(self):
        self.seed("note", "--goal", "g", "--next", "n")
        nested = Path(self.tmp) / "lib" / "nested" / "file.ex"
        worktree = self.hooks.find_worktree([str(nested)])
        self.assertEqual(worktree, os.path.realpath(self.tmp))

    def test_no_ledger_anywhere_returns_none(self):
        other = tempfile.mkdtemp(prefix="riel-untracked-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertIsNone(self.hooks.find_worktree([str(Path(other) / "a.py")]))

    def test_session_cwd_is_used_when_it_carries_a_ledger(self):
        self.seed("note", "--goal", "g", "--next", "n")
        worktree = self.hooks.find_worktree([], session_cwd=self.tmp)
        self.assertEqual(worktree, os.path.realpath(self.tmp))

    def test_edited_files_win_over_the_session_cwd(self):
        """A turn can edit a worktree other than the one the session sits in."""
        other = tempfile.mkdtemp(prefix="riel-other-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.seed("note", "--goal", "sesión", "--claim", "P1: aquí", "--verify-with", "x")
        self.seed_in(other, "note", "--goal", "editado", "--claim", "P1: allá", "--verify-with", "x")
        worktree = self.hooks.find_worktree([str(Path(other) / "lib" / "a.ex")], session_cwd=self.tmp)
        self.assertEqual(worktree, os.path.realpath(other))

    def test_junk_inputs_never_raise(self):
        for changed, cwd in ((None, None), ([], ""), ([None, 1], None), ([""], "   ")):
            with self.subTest(changed=changed, cwd=cwd):
                self.assertIsNone(self.hooks.find_worktree(changed, session_cwd=cwd))


class AssessTest(GateTestCase):
    def test_counts_claims_and_verified(self):
        self.seed("note", "--goal", "g", "--claim", "P1: la cosa", "--verify-with", "make test")
        self.seed("note", "--check", "lo verifiqué", "--by", "make test")
        facts = self.hooks.assess(self.tmp)
        self.assertTrue(facts["present"])
        self.assertEqual(len(facts["claims"]), 1)
        self.assertEqual(len(facts["verified"]), 1)
        self.assertEqual(len(facts["verified_with_evidence"]), 1, facts)

    def test_checkpoint_without_evidence_is_not_evidence(self):
        self.write_ledger(HAND_WRITTEN_NO_EVIDENCE)
        facts = self.hooks.assess(self.tmp)
        self.assertEqual(len(facts["verified"]), 1)
        self.assertEqual(facts["verified_with_evidence"], [])

    def test_absent_ledger_is_reported(self):
        facts = self.hooks.assess(self.tmp)
        self.assertFalse(facts["present"])
        self.assertIsNone(facts["error"])

    def test_missing_vendored_rielctl_degrades_to_an_error(self):
        self.seed("note", "--goal", "g", "--next", "n")
        facts = self.hooks.assess(self.tmp, rielctl=Path("/nope/rielctl"))
        self.assertTrue(facts["present"])
        self.assertIn("rielctl", facts["error"])
        self.assertIsNone(self.hooks.nudge_message(self.tmp, facts))

    def test_junk_worktree_never_raises(self):
        for value in ("", "/dev/null", "\x00", None):
            with self.subTest(value=value):
                self.assertFalse(self.hooks.assess(value)["present"])


class NudgeMessageTest(GateTestCase):
    def test_claims_without_any_checkpoint_nudges(self):
        self.seed("note", "--goal", "g", "--claim", "P1: la cosa", "--verify-with", "make test")
        message = self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp))
        self.assertIsNotNone(message)
        self.assertIn("1 claim", message)
        self.assertIn("riel_note", message)

    def test_checkpoint_without_evidence_nudges_about_evidence(self):
        self.write_ledger(HAND_WRITTEN_NO_EVIDENCE)
        message = self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp))
        self.assertIsNotNone(message)
        self.assertIn("evidencia", message)

    def test_a_verified_checkpoint_with_evidence_closes_the_gate(self):
        self.seed("note", "--goal", "g", "--claim", "P1: la cosa", "--verify-with", "make test")
        self.seed("note", "--check", "lo verifiqué", "--by", "make test, 3 passed")
        self.assertIsNone(self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp)))

    def test_an_empty_ledger_is_not_the_gates_business(self):
        self.seed("note", "--goal", "recién empezado")
        self.assertIsNone(self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp)))

    def test_message_names_the_worktree(self):
        self.seed("note", "--goal", "g", "--claim", "P1: x", "--verify-with", "make test")
        message = self.hooks.nudge_message(self.tmp, self.hooks.assess(self.tmp))
        # nudge_message echoes the worktree it is handed; the callback normalizes
        # first (see PreVerifyCallbackTest).
        self.assertIn(self.tmp, message)


class PreVerifyCallbackTest(GateTestCase):
    """The registered callback: the contract Hermes' hook dispatcher relies on."""

    def setUp(self):
        super().setUp()
        self.hooks.SETTINGS.update({"enabled": True, "attempts": 1})

    def test_continues_the_turn_while_the_ledger_lacks_a_verified_checkpoint(self):
        self.seed("note", "--goal", "g", "--claim", "P1: x", "--verify-with", "make test")
        result = self.hooks.pre_verify(
            session_id="s1",
            platform="desktop",
            model="m",
            coding=True,
            attempt=0,
            final_response="listo",
            changed_paths=[str(Path(self.tmp) / "lib" / "a.ex")],
        )
        self.assertEqual(result["action"], "continue")
        self.assertIn(os.path.realpath(self.tmp), result["message"])

    def test_allows_the_turn_to_close_once_verified(self):
        self.seed("note", "--goal", "g", "--claim", "P1: x", "--verify-with", "make test")
        self.seed("note", "--check", "ok", "--by", "make test")
        self.assertIsNone(
            self.hooks.pre_verify(attempt=0, changed_paths=[str(Path(self.tmp) / "lib" / "a.ex")])
        )

    def test_self_throttles_after_the_configured_attempts(self):
        self.seed("note", "--goal", "g", "--claim", "P1: x", "--verify-with", "make test")
        paths = [str(Path(self.tmp) / "lib" / "a.ex")]
        self.assertIsNotNone(self.hooks.pre_verify(attempt=0, changed_paths=paths))
        self.assertIsNone(self.hooks.pre_verify(attempt=1, changed_paths=paths))

    def test_respects_the_gate_setting(self):
        self.seed("note", "--goal", "g", "--claim", "P1: x", "--verify-with", "make test")
        self.hooks.SETTINGS["enabled"] = False
        self.addCleanup(self.hooks.SETTINGS.update, {"enabled": True})
        self.assertIsNone(
            self.hooks.pre_verify(attempt=0, changed_paths=[str(Path(self.tmp) / "lib" / "a.ex")])
        )

    def test_untracked_worktree_is_never_gated(self):
        other = tempfile.mkdtemp(prefix="riel-untracked-")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertIsNone(self.hooks.pre_verify(attempt=0, changed_paths=[str(Path(other) / "a.py")]))

    def test_no_changed_paths_and_no_session_record_declines(self):
        self.seed("note", "--goal", "g", "--claim", "P1: x", "--verify-with", "make test")
        self.assertIsNone(self.hooks.pre_verify(attempt=0, changed_paths=[]))

    def test_unknown_payload_fields_are_tolerated(self):
        """Hermes adds hook payload fields over time; registration must not break."""
        self.seed("note", "--goal", "g", "--claim", "P1: x", "--verify-with", "make test")
        result = self.hooks.pre_verify(
            attempt=0,
            changed_paths=[str(Path(self.tmp) / "lib" / "a.ex")],
            something_new_in_a_later_release={"a": 1},
            coding=False,
        )
        self.assertEqual(result["action"], "continue")

    def test_broken_ledger_never_blocks_the_turn(self):
        self.write_ledger("# Riel ledger\n")
        self.assertIsNone(
            self.hooks.pre_verify(attempt=0, changed_paths=[str(Path(self.tmp) / "lib" / "a.ex")])
        )


if __name__ == "__main__":
    unittest.main()
