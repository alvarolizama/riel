"""Backend routes for the Riel desktop half, mounted at `/api/plugins/riel/`.

Read-only plus the settings writer, answering the statusbar chip:

  GET /health            → is the backend up and does it have its bundled engine
  GET /run?worktree=     → the worktree's CONTRACTS: the listing the chip's
                           counter and dialog list use (slug, status, pending)
  GET /run?worktree=&slug= → ONE contract: verbatim markdown (the dialog) +
                           the engine's `run status` object
  GET/POST /settings     → the switch surface (read), validated writes
  GET /session_cwd       → the FOCUSED session's stored worktree

The mount is the dashboard plugin API, which runs inside the gateway process.
Bound by construction: the only task paths this ever reads are
`<worktree>/.riel/runs/<slug>.md` — resolved against symlinks, capped, and the
engine reached the safe in-process way. Every route is a SYNC def: FastAPI runs sync
handlers on its threadpool, so a bounded engine call never blocks the event
loop (the gateway serves every session from it).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi import APIRouter, Query

_PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _load_plumbing():
    """`_load.py` — this file runs outside the package's import context.

    The dashboard plugin API is loaded by path by the gateway, so the relative
    imports every other module uses are not available here. Loading the one
    plumbing module by path keeps a single loader for the whole package: the
    spec dances this file used to carry are now `sibling()` calls.
    """
    path = _PLUGIN_DIR / "_load.py"
    spec = importlib.util.spec_from_file_location("riel_dashboard_load", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_load = _load_plumbing()
_ledger_status = _load.sibling("riel_dashboard_ledger_status", "dashboard/ledger_status.py")
_session_cwd = _load.sibling("riel_dashboard_session_cwd", "dashboard/session_cwd.py")
_settings = _load.sibling("riel_dashboard_settings", "settings.py")

router = APIRouter()
MAX_WORKTREE_CHARS = 4096


@router.get("/health")
def health() -> dict:
    """Up + engine present. No cwd, no paths beyond the bundled engine's."""
    engine = _ledger_status.ENGINE
    return {"ok": engine.exists(), "engine": str(engine)}


@router.get("/run")
def run_state(worktree: str = Query("", max_length=MAX_WORKTREE_CHARS),
              slug: str = Query("", max_length=256)) -> dict:
    """The worktree's contracts — the listing, or ONE contract with `slug`.

    Without `slug`: `{present, worktree, contracts, active, pending, total}` —
    what the chip's counter (`pending/active`) and the dialog's list render.
    With `slug`: `{present, worktree, slug, markdown, status}` — the contract
    the dialog opens. Absent, empty and error states included; a worktree
    without contracts is a normal `present: false`, not a failure.
    """
    if not worktree.strip():
        return {"present": False, "worktree": "", "contracts": [],
                "error": "worktree query parameter is required"}
    if slug.strip():
        return _ledger_status.read_run(worktree, slug)
    return _ledger_status.read_runs(worktree)


@router.get("/settings")
def read_settings() -> dict:
    """The switch surface: the groups, the operator's note and the attempts."""
    return {"ok": True, **_settings.state()}


@router.post("/settings")
def write_settings(payload: dict) -> dict:
    """Flip one or more switches. Validated here; written through Hermes' own writer."""
    try:
        return {"ok": True, **_settings.apply(payload)}
    except _settings.Rejected as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # PermissionError in a managed install, unreadable config, ...
        return {"ok": False, "error": f"could not write: {exc}"}


@router.get("/session_cwd")
def session_cwd(session_id: str = Query("", max_length=256)) -> dict:
    """The FOCUSED session's stored worktree — the chip's authoritative cwd.

    The app's workspace atoms can still hold the previous conversation's
    folder right after a switch; the session DB has the real one.
    """
    if not session_id.strip():
        return {"found": False, "cwd": "", "error": "session_id query parameter is required"}
    return _session_cwd.read_session_cwd(session_id)
