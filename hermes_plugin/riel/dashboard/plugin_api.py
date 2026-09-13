"""Backend routes for the Riel desktop half, mounted at `/api/plugins/riel/`.

Three read-only endpoints, answering the statusbar chip:

  GET /health            → is the backend up and does it have its vendored rielctl
  GET /ledger?worktree=  → the ledger summary for one worktree (the chip's counters)
  GET /contract?worktree= → the contract.md verbatim (the chip's click dialog)

The mount is the dashboard plugin API, which runs inside the gateway process.
Bound by construction: the only paths this ever reads are
`<worktree>/.riel/ledger.md` and `<worktree>/.riel/contract.md` — and of the
contract, the verbatim markdown leaves (the renderer, Streamdown, draws the
sections and the mermaid graph; no digest or re-parsing here).

The ledger logic lives beside this file in `ledger_status.py`, loaded by path so
it works whatever loader the gateway uses for `plugin_api.py`.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from fastapi import APIRouter, Query

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_STATUS_PATH = Path(__file__).resolve().parent / "ledger_status.py"
_SESSION_CWD_PATH = Path(__file__).resolve().parent / "session_cwd.py"

_spec = importlib.util.spec_from_file_location("riel_dashboard_ledger_status", _STATUS_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise RuntimeError(f"cannot load {_STATUS_PATH}")
_ledger_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ledger_status)

_spec2 = importlib.util.spec_from_file_location("riel_dashboard_session_cwd", _SESSION_CWD_PATH)
if _spec2 is None or _spec2.loader is None:  # pragma: no cover - defensive
    raise RuntimeError(f"cannot load {_SESSION_CWD_PATH}")
_session_cwd = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(_session_cwd)

router = APIRouter()
MAX_WORKTREE_CHARS = 4096


@router.get("/health")
async def health() -> dict:
    rielctl = _ledger_status.RIELCTL
    return {"ok": rielctl.exists(), "rielctl": str(rielctl), "cwd": os.getcwd()}


@router.get("/ledger")
async def ledger(worktree: str = Query("", max_length=MAX_WORKTREE_CHARS)) -> dict:
    """Summary of `<worktree>/.riel/ledger.md` — absent, empty and error states included."""
    if not worktree.strip():
        return {"present": False, "worktree": "", "error": "worktree query parameter is required"}
    return _ledger_status.read_status(worktree)


@router.get("/contract")
async def contract(worktree: str = Query("", max_length=MAX_WORKTREE_CHARS)) -> dict:
    """The verbatim `<worktree>/.riel/contract.md` — the chip's click dialog renders it."""
    if not worktree.strip():
        return {"present": False, "worktree": "", "error": "worktree query parameter is required"}
    return _ledger_status.read_contract(worktree)


@router.get("/session_cwd")
async def session_cwd(session_id: str = Query("", max_length=256)) -> dict:
    """The FOCUSED session's stored worktree — the chips' authoritative cwd.

    The app's workspace atoms can still hold the previous conversation's
    folder right after a switch; the session DB has the real one.
    """
    if not session_id.strip():
        return {"found": False, "cwd": "", "error": "session_id query parameter is required"}
    return _session_cwd.read_session_cwd(session_id)
