"""Session-owned TodoStore synchronization for the Riel run projection.

The run engine stays host-independent: it projects the goal, phases, gates and
steps into the flat ``{id, content, status, parent}`` list Hermes accepts. This
module writes that projection into the CALLING session's TodoStore and leaves
every non-Riel item untouched.

No process-global store is created. The store belongs to the live AIAgent of
the session id Hermes puts on the tool call; the classic CLI fallback is the
agent attached to the plugin context. When neither is reachable the result is
an honest ``unavailable`` and the run state remains the source of truth.
"""
from __future__ import annotations

import sys

TODO_PREFIX = "riel-"
_CONTEXT = {"context": None}


def configure(context) -> None:
    """Record the plugin context used as the classic-CLI fallback."""
    _CONTEXT["context"] = context


def _store_for(context, session_id):
    """The live TodoStore for this session, or None.

    Gateway/TUI sessions are held in ``tui_gateway.server._sessions`` keyed by
    the same id Hermes passes to tool handlers. The classic CLI keeps its agent
    on ``PluginContext._manager._cli_ref``. Both are looked up lazily so this
    module imports on any surface (repo suite, dashboard, headless).
    """
    server = sys.modules.get("tui_gateway.server")
    sessions = getattr(server, "_sessions", None) if server is not None else None
    if isinstance(sessions, dict) and session_id:
        record = sessions.get(session_id)
        agent = record.get("agent") if isinstance(record, dict) else None
        store = getattr(agent, "_todo_store", None)
        if store is not None:
            return store
    manager = getattr(context, "_manager", None)
    agent = getattr(getattr(manager, "_cli_ref", None), "agent", None)
    return getattr(agent, "_todo_store", None)


def _publish(session_id, state) -> None:
    """Best-effort `todo.updated` to the live client; the store write is the truth."""
    server = sys.modules.get("tui_gateway.server")
    emit = getattr(server, "_emit", None) if server is not None else None
    if callable(emit) and session_id:
        try:
            emit("todo.updated", session_id, state)
        except Exception:
            pass


def synchronize(context=None, store=None, items=None, clear=False, session_id=""):
    """Replace only Riel rows in the caller's store; report the actual outcome."""
    store = store or _store_for(context or _CONTEXT.get("context"), session_id)
    if store is None:
        return {"status": "unavailable", "namespace": TODO_PREFIX,
                "reason": "this session exposes no TodoStore to the plugin"}
    try:
        snapshot = store.snapshot()
        preserved = [row for row in snapshot.get("todos", [])
                     if not str(row.get("id", "")).startswith(TODO_PREFIX)]
        rows = [] if clear else items
        if rows is None:
            raise ValueError("the run returned no todo projection")
        if not isinstance(rows, list):
            raise ValueError("the run returned an invalid todo projection")
        written = store.write(preserved + rows)
        if len(written) != len(preserved) + len(rows):
            raise ValueError("the host dropped a todo row")
        state = store.snapshot()
        _publish(session_id, state)
        return {"status": "cleared" if clear else "synced",
                "items": 0 if clear else len(rows),
                "revision": state.get("revision"), "namespace": TODO_PREFIX}
    except Exception as exc:
        return {"status": "unavailable", "namespace": TODO_PREFIX,
                "reason": str(exc)[:400]}


def attach(payload, context=None, store=None, items=None, clear=False, session_id=""):
    """Add an honest sync result to a successful envelope, without a traceback."""
    if payload.get("exit_code") != 0:
        return payload
    payload["todo_sync"] = synchronize(
        context, store, items=items, clear=clear, session_id=session_id)
    if payload["todo_sync"]["status"] == "unavailable":
        payload["stderr"] = (payload.get("stderr", "").rstrip()
                            + "\nWARNING: session todo unavailable: "
                            + payload["todo_sync"]["reason"]).lstrip()
    return payload
