"""The run owns the session checklist: activation and evidence synchronize it."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hermes_plugin.riel import tools, todos

LIST_RUN = """# Run: checks
<!-- riel-run/v1 -->

## Objective
Keep the session checklist in sync with run evidence.

## Context

### Why
The checklist is a projection, never a second source of truth.

### Context keywords
- run → this repo

## Deliverable
A nested checklist with step subchecks.

## Constraints
- one TodoStore per session.

## DO NOT
- edit another session's todos.
## Phases

### F1: implement checks
- EDIT todos.py
- RUN python3 -m unittest

#### Claims
- P1: activation publishes the checks — anchor: §F1#1

#### Gates
- G1: phase one passes

#### Deliverable
- the checks are published

### F2: verify checks
- RUN python3 -m unittest

#### Claims
- P2: evidence closes them — anchor: §F2#1

#### Gates
- G2: phase two passes

#### Deliverable
- the nested checklist

"""


class FakeStore:
    """The subset of Hermes TodoStore Riel uses, with its real shape."""

    def __init__(self):
        self._items = [{"id": "mine", "content": "user item", "status": "pending"}]
        self.revision = 0

    def snapshot(self):
        return {"todos": [dict(row) for row in self._items], "revision": self.revision}

    def write(self, rows):
        self._items = [dict(row) for row in rows]
        self.revision += 1
        return [dict(row) for row in self._items]


class RunOwnsTodoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="riel-todo-test-")
        self._saved_engine = (tools.ENGINE, tools._ENGINE["module"])
        tools.ENGINE = Path(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "hermes_plugin", "riel", "engine", "run.py"))
        tools._ENGINE["module"] = None
        os.makedirs(os.path.join(self.tmp, ".riel"))
        with open(os.path.join(self.tmp, ".riel", "run.md"), "w", encoding="utf-8") as fh:
            fh.write(LIST_RUN)
        self.store = FakeStore()

    def tearDown(self):
        tools.ENGINE, tools._ENGINE["module"] = self._saved_engine
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, tool, **args):
        with mock.patch.object(todos, "_store_for", return_value=self.store), \
                mock.patch.object(todos, "_publish"):
            return json.loads(tool({**args, "worktree": self.tmp},
                                   session_id="session-1"))

    def rows(self):
        return {row["id"]: row for row in self.store.snapshot()["todos"]}

    def test_activation_publishes_checks_with_step_subchecks(self):
        payload = self.call(tools.riel_run, verb="activate")
        self.assertTrue(payload["passed"], payload)
        self.assertEqual(payload["todo_sync"]["status"], "synced")
        rows = self.rows()
        self.assertIn("mine", rows, "a non-Riel item survives the sync")
        self.assertEqual(rows["riel-phase-F1"]["status"], "in_progress")
        self.assertEqual(rows["riel-gate-G1"]["parent"], "riel-phase-F1")
        self.assertEqual(rows["riel-step-F1S1"]["parent"], "riel-gate-G1")
        self.assertEqual(rows["riel-step-F1S1"]["status"], "in_progress")

    def test_passing_evidence_closes_checks_and_failed_evidence_does_not(self):
        self.call(tools.riel_run, verb="activate")
        self.call(tools.riel_note, gates=["G1"], claims=["P1"],
                  command="true", covering="phase one")
        rows = self.rows()
        self.assertEqual(rows["riel-gate-G1"]["status"], "completed")
        self.assertEqual(rows["riel-step-F1S1"]["status"], "completed")
        self.call(tools.riel_note, gates=["G2"], claims=["P2"],
                  command="false", covering="phase two")
        rows = self.rows()
        self.assertEqual(rows["riel-gate-G2"]["status"], "in_progress")
        self.assertEqual(rows["riel-step-F2S1"]["status"], "in_progress")
        self.assertFalse(json.loads(
            self.call(tools.riel_run, verb="status")["stdout"])["done"])

    def test_clean_removes_only_riel_rows(self):
        self.call(tools.riel_run, verb="activate")
        payload = self.call(tools.riel_clean)
        self.assertEqual(payload["todo_sync"]["status"], "cleared")
        self.assertEqual(list(self.rows()), ["mine"])

    def test_resolves_the_live_session_store_and_emits_the_update(self):
        emit = mock.Mock()
        server = SimpleNamespace(
            _sessions={"session-9": {"agent": SimpleNamespace(_todo_store=self.store)}},
            _emit=emit)
        rows = [{"id": "riel-goal", "content": "GOAL: x", "status": "pending"}]
        with mock.patch.dict(sys.modules, {"tui_gateway.server": server}):
            result = todos.synchronize(session_id="session-9", items=rows)
        self.assertEqual(result["status"], "synced")
        self.assertEqual(list(self.rows()), ["mine", "riel-goal"])
        emit.assert_called_once_with("todo.updated", "session-9",
                                     self.store.snapshot())

    def test_an_unknown_session_is_reported_not_silently_dropped(self):
        with mock.patch.dict(sys.modules, {"tui_gateway.server": SimpleNamespace(
                _sessions={}, _emit=mock.Mock())}):
            result = todos.synchronize(session_id="absent", items=[])
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("no TodoStore", result["reason"])


if __name__ == "__main__":
    unittest.main()
