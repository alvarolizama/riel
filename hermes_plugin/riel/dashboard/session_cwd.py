"""Session-cwd lookup for the desktop half: the FOCUSED session's worktree.

The chips need "which folder does this conversation live in", and the app's
own atoms are no answer right after a switch (they still hold the previous
conversation's folder). The session DB does have it — `cwd` is part of the
session row (`hermes_state_sessions`) — and this module runs inside the
gateway process, so it can ask the store directly.

Never raises; a missing/unreadable session is reported, never invented.
"""

from __future__ import annotations

from pathlib import Path


def read_session_cwd(session_id: str) -> dict:
    """The stored cwd of *session_id*, or a `found: False` report."""
    sid = str(session_id or "").strip()
    out = {"session_id": sid, "cwd": "", "found": False}
    if not sid:
        out["error"] = "session_id is required"
        return out
    try:
        # Same store the dashboard's session list reads. Lazy import: module
        # names move between Hermes releases and a plugin must never fail to
        # load because of one.
        from hermes_cli.web_server_sessions import _open_session_db_for_profile

        db = _open_session_db_for_profile(None, read_only=True)
        try:
            row = db.get_session(sid)
        finally:
            db.close()
    except Exception as exc:  # store busy / module moved: report, don't crash
        out["error"] = f"session store unavailable: {exc}"
        return out
    if not row:
        out["error"] = "session not found"
        return out
    cwd = str(row.get("cwd") or "").strip()
    if cwd:
        out["cwd"] = cwd
        out["found"] = True
    else:
        out["error"] = "session has no stored cwd"
    return out
