"""Normalize a worktree's Riel ledger into the small summary the statusbar chip shows.

Stdlib only, and importable without FastAPI so the repo suite can test it
directly. It shells out to the **vendored** `rielctl todo` — the same JSON
mirror the `riel_todo` tool returns — instead of re-parsing `.riel/ledger.md`
here, so the ledger format keeps exactly one owner (`rielctl`).

Never raises: the caller is an HTTP route and the panel must degrade to
"no ledger" instead of a 500.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
RIELCTL = PLUGIN_DIR / "vendor" / "riel-cli" / "scripts" / "rielctl"
TIMEOUT_SECS = 15

_LEDGER_SUFFIX = (".riel", "ledger.md")
_CONTRACT_SUFFIX = (".riel", "contract.md")
# A contract is working memory for the task in flight, not a book — if it ever
# grows past this, the dialog still opens, it just stops at the cap.
MAX_CONTRACT_CHARS = 262_144


def _blank(worktree: str) -> dict:
    return {
        "present": False,
        "worktree": worktree,
        "goal": "",
        "next": "",
        "phase": "",
        "claims": 0,
        "open": 0,
        "verified": 0,
        "updated": None,
        "stale_secs": None,
    }


def _strip(content: str, prefix: str) -> str:
    text = str(content or "")
    return text[len(prefix):].strip() if text.startswith(prefix) else text.strip()


def summarize(items: list) -> dict:
    """Fold `rielctl todo` items into the chip's counters, headlines AND detail.

    The detail lists carry each item's content (claims with their verify-with,
    verified checkpoints with their evidence, open questions) so the popover can
    show everything the ledger has — the counters alone are the bar's business.
    """
    summary = {
        "goal": "", "next": "", "phase": "",
        "claims": 0, "open": 0, "verified": 0,
        "claims_detail": [], "verified_detail": [], "open_detail": [],
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        content = str(item.get("content") or "")
        if item_id == "goal":
            summary["goal"] = _strip(content, "GOAL: ")
        elif item_id == "next":
            summary["next"] = _strip(content, "NEXT: ")
        elif item_id == "phase":
            summary["phase"] = _strip(content, "PHASE: ")
        elif item_id.startswith("open-"):
            summary["open"] += 1
            summary["open_detail"].append(_strip(content, "OPEN "))
        elif item_id.startswith("claim-"):
            summary["claims"] += 1
            summary["claims_detail"].append(_strip(content, "CLAIM: "))
        elif item_id.startswith("done-"):
            summary["verified"] += 1
            summary["verified_detail"].append(_strip(content, "DONE "))
    return summary


def read_status(worktree: str, rielctl: Path = RIELCTL, timeout: int = TIMEOUT_SECS) -> dict:
    """Ledger summary for *worktree*, or a `present: False` report. Never raises."""
    raw = str(worktree or "").strip()
    if not raw:
        # An empty value must NOT fall back to the gateway's cwd: that would
        # silently report some unrelated directory's ledger.
        status = _blank("")
        status["error"] = "worktree is required"
        return status
    root = os.path.abspath(os.path.expanduser(raw))
    status = _blank(root)
    if not os.path.isdir(root):
        status["error"] = "worktree is not a directory"
        return status

    ledger = Path(root).joinpath(*_LEDGER_SUFFIX)
    if not ledger.is_file():
        return status

    try:
        status["updated"] = int(ledger.stat().st_mtime)
    except OSError:
        pass
    if status["updated"] is not None:
        status["stale_secs"] = max(0, int(time.time()) - status["updated"])
    status["present"] = True

    if not rielctl.exists():
        status["error"] = "vendored rielctl is missing (run: make plugin-vendor)"
        return status
    try:
        proc = subprocess.run(
            [sys.executable, str(rielctl), "todo"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        status["error"] = f"rielctl timed out after {timeout}s"
        return status
    except OSError as exc:
        status["error"] = f"rielctl could not be executed: {exc}"
        return status
    if proc.returncode != 0:
        # A ledger with no goal/next/verified yet: present, just empty.
        status["error"] = (proc.stderr or "").strip() or "rielctl todo failed"
        return status
    try:
        items = json.loads(proc.stdout)
    except ValueError:
        status["error"] = "rielctl todo did not return JSON"
        return status
    if isinstance(items, list):
        status.update(summarize(items))
    return status


def read_contract(worktree: str) -> dict:
    """The worktree's contract.md, verbatim, for the statusbar dialog. Never raises.

    Same boundary discipline as `read_status`: the only path this ever reads is
    `<worktree>/.riel/contract.md`, and `present` is only true when that file
    exists — a missing contract is reported, never invented.
    """
    raw = str(worktree or "").strip()
    if not raw:
        status = {"present": False, "worktree": "", "markdown": "", "chars": 0}
        status["error"] = "worktree is required"
        return status
    root = os.path.abspath(os.path.expanduser(raw))
    status = {"present": False, "worktree": root, "markdown": "", "chars": 0}
    if not os.path.isdir(root):
        status["error"] = "worktree is not a directory"
        return status
    path = Path(root).joinpath(*_CONTRACT_SUFFIX)
    if not path.is_file():
        status["error"] = "no .riel/contract.md in this worktree (write the contract first)"
        return status
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        status["error"] = f"contract unreadable: {exc}"
        return status
    if len(text) > MAX_CONTRACT_CHARS:
        text = text[:MAX_CONTRACT_CHARS] + "\n\n<!-- truncated at 256 KiB -->"
    status["present"] = True
    status["markdown"] = text
    status["chars"] = len(text)
    return status
