"""Backend routes for the Riel desktop half, mounted at `/api/plugins/riel/`.

Two read-only endpoints, both answering the statusbar chip:

  GET /health            → is the backend up and does it have its vendored rielctl
  GET /ledger?worktree=  → the ledger summary for one worktree

The mount is the dashboard plugin API, which runs inside the gateway process.
Bound by construction: the only path this ever reads is `<worktree>/.riel/ledger.md`,
and only a normalized summary (counters + the goal/next headlines) leaves here —
never raw file contents of anything else.

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

_spec = importlib.util.spec_from_file_location("riel_dashboard_ledger_status", _STATUS_PATH)
if _spec is None or _spec.loader is None:  # pragma: no cover - defensive
    raise RuntimeError(f"cannot load {_STATUS_PATH}")
_ledger_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ledger_status)

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
