"""Tool handlers — machinery for the Riel plugin.

Every handler runs the **bundled engine** in a fresh subprocess whose cwd is
the session's worktree. That script is the engine, never an interface: the agent
sees tools, and no tool accepts argv — every parameter is typed. The engine stays
the sole writer of `.riel/ledger.md`: this module adds no ledger semantics, no
format, no state of its own.

Why a subprocess instead of importing the engine in-process: it resolves
`.riel/` relative to the process cwd, and its `DEFAULT_TEMPLATE_DIRS` freezes
`os.getcwd()` at import time. Inside a long-lived Hermes process (a gateway
serving several sessions) an `os.chdir` would be global state shared by every
session; a subprocess gives each call its own cwd, so concurrent sessions cannot
write into each other's ledger.

Stdlib only, and importable outside Hermes: nothing here imports Hermes at
module level, so the repo's test suite can exercise these handlers directly.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent
ENGINE = _PLUGIN_DIR / "engine" / "run.py"
TIMEOUT_SECS = 60

_SETTINGS_MODULE = None
_GUIDE_MODULE = None


def plugin_settings():
    """`settings.py` beside this file, loaded by path.

    By path, not by import: this module is loaded under whatever loader the
    host picked (package, `hermes_plugins.<name>`, the repo suite) and must stay
    importable without Hermes.
    """
    global _SETTINGS_MODULE
    if _SETTINGS_MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "riel_plugin_settings", _PLUGIN_DIR / "settings.py"
        )
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise RuntimeError("settings.py is missing from the package")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SETTINGS_MODULE = module
    return _SETTINGS_MODULE


def plugin_guide():
    """`guide.py` beside this file, loaded by path (same reason as settings.py)."""
    global _GUIDE_MODULE
    if _GUIDE_MODULE is None:
        spec = importlib.util.spec_from_file_location(
            "riel_plugin_guide", _PLUGIN_DIR / "guide.py"
        )
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise RuntimeError("guide.py is missing from the package")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _GUIDE_MODULE = module
    return _GUIDE_MODULE


_STR_FLAGS = {
    "goal": "--goal",
    "next": "--next",
    "source": "--source",
    "phase": "--phase",
    "core": "--core",
    "claim": "--claim",
    "verify_with": "--verify-with",
    "check": "--check",
    "by": "--by",
    "covering": "--covering",
    "open": "--open",
    "settled_by": "--settled-by",
}
_INT_FLAGS = {
    "core_slot": "--core-slot",
    "confidence": "--confidence",
    "close": "--close",
}


def _error(message: str, **extra) -> str:
    payload = {"error": message}
    payload.update(extra)
    return json.dumps(payload)


def _session_worktree(kwargs: dict) -> str:
    """The worktree this call belongs to.

    Order: the session's recorded cwd (the same record the terminal tool uses,
    so both routes agree on where `.riel/` lives) → ``TERMINAL_CWD`` → the
    process cwd. The Hermes import is lazy and defensive: internal module paths
    move between releases and a plugin must never fail to load because of it.
    """
    key = kwargs.get("task_id") or kwargs.get("session_key")
    try:
        from tools.terminal_tool import get_session_cwd  # internal, may move

        recorded = get_session_cwd(key)
        if recorded:
            return str(recorded)
    except Exception:
        pass
    env = (os.environ.get("TERMINAL_CWD") or "").strip()
    if env:
        # Hermes sets this absolute; abspath keeps a hand-set relative value safe
        # (the subprocess would otherwise resolve it against the process cwd).
        return os.path.abspath(os.path.expanduser(env))
    return os.getcwd()


def _worktree(args: dict, kwargs: dict) -> str:
    explicit = str(args.get("worktree") or "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    return _session_worktree(kwargs)


def _run(argv: list, args: dict, kwargs: dict, tool: str, verb: str = "") -> str:
    """Run the engine in the worktree; always return a JSON string, never raise.

    `tool`/`verb` are the envelope's provenance: WHICH tool answered and, when
    the tool takes one, with which verb. There is no command-shaped field — the
    engine's argv is implementation, not something a caller passes or reads.
    """
    worktree = _worktree(args, kwargs)
    if not os.path.isdir(worktree):
        return _error(f"worktree is not a directory: {worktree}", tool=tool, worktree=worktree)
    if not ENGINE.exists():
        return _error(
            "bundled engine is missing — the package has no engine/ tree",
            path=str(ENGINE),
            hint="from the repo checkout: make plugin-build",
        )
    try:
        proc = subprocess.run(
            [sys.executable, str(ENGINE), *argv],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        return _error(f"the engine timed out after {TIMEOUT_SECS}s", tool=tool, worktree=worktree)
    except OSError as exc:
        return _error(f"the engine could not be executed: {exc}", tool=tool, worktree=worktree)
    payload = {"tool": tool}
    if verb:
        payload["verb"] = verb
    payload.update(
        {
            "worktree": worktree,
            "exit_code": proc.returncode,
            "passed": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    )
    return json.dumps(payload)


def _flag_args(args: dict) -> list:
    """Map tool arguments onto the engine's flags (values only, no interpretation)."""
    argv: list = []
    for key, flag in _STR_FLAGS.items():
        value = args.get(key)
        if value is None or str(value).strip() == "":
            continue
        argv += [flag, str(value)]
    for key, flag in _INT_FLAGS.items():
        value = args.get(key)
        if value is None or value == "":
            continue
        try:
            argv += [flag, str(int(value))]
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer, got {value!r}")
    return argv


def _from_contract_args(args: dict) -> list:
    raw = args.get("from_contract")
    if raw is None:
        return []
    value = str(raw).strip()
    if value == "" or value.lower() in {"false", "no", "0"}:
        return []
    if value.lower() in {"true", "yes", "1"}:
        return ["--from-contract"]
    return ["--from-contract", os.path.expanduser(value)]


def _str_list(raw, field: str) -> "list | str":
    """A typed list of strings from the caller, or an error string."""
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        return _error(f"{field} must be an array of strings")
    return raw


def riel_note(args: dict, **kwargs) -> str:
    """Append/update ledger entries via the engine's `note` verb."""
    try:
        argv = _flag_args(args) + _from_contract_args(args)
    except ValueError as exc:
        return _error(str(exc))
    if not argv:
        keys = ", ".join(sorted([*_STR_FLAGS, *_INT_FLAGS, "from_contract"]))
        return _error(
            "riel_note needs at least one content flag (or from_contract)",
            accepted=keys,
            note="with no flags the engine just re-prints the ledger; use riel_seam for that",
        )
    return _run(["note", *argv], args, kwargs, tool="riel_note")


def _passthrough(verb: str, tool: str, extra_note: "str | None" = None):
    """A handler that runs one engine verb and, optionally, adds a note.

    `tool` is the name this passthrough answers as — the envelope's provenance
    says which tool spoke, never which engine verb ran.
    """
    def handler(args: dict, **kwargs) -> str:
        payload = json.loads(_run([verb], args, kwargs, tool=tool))
        if extra_note and isinstance(payload, dict) and payload.get("exit_code") == 0:
            payload["next"] = extra_note
        return json.dumps(payload, ensure_ascii=False)

    return handler


def riel_seam(args: dict, **kwargs) -> str:
    """The seam re-read: the ledger, and — when asked — each claim beside its support."""
    payload = json.loads(_run(["seam"], args, kwargs, tool="riel_seam"))
    if args.get("anchors") and payload.get("exit_code") == 0:
        anchors = json.loads(_run(["anchor"], args, kwargs, tool="riel_seam", verb="anchors"))
        payload["anchors"] = {"exit_code": anchors.get("exit_code"),
                              "passed": anchors.get("passed"),
                              "stdout": anchors.get("stdout"),
                              "stderr": anchors.get("stderr")}
    return json.dumps(payload, ensure_ascii=False)


riel_resume = _passthrough("resume", tool="riel_resume")
riel_todo = _passthrough(
    "todo",
    tool="riel_todo",
    extra_note=(
        "Inject this into the session todo: pass the items array (stdout) to the "
        "todo_list tool (todos=<array>) so the UI shows the plan — the contract's "
        "goal, its phases and their steps."
    ),
)
riel_state = _passthrough("status", tool="riel_state")


# ------------------------------------------------------------------ context ---
# The tool is an INDEX provider, not a searcher: a plugin cannot reach the
# memory backends. Those tools live in `agent/memory_manager.py`
# (`get_all_tool_schemas` / `handle_tool_call`), not in `tools.registry`, so
# `ctx.dispatch_tool("dran_memory_search", …)` returns "Unknown tool" — the
# agent reaches them because its executor routes to the memory manager. So the
# plugin supplies the contract's keywords and WHO searches decides: the agent,
# with whatever memory backend it has configured.
MAX_KEYWORDS = 12


def _contract_keywords(worktree: str):
    """(keywords, error) from the worktree's contract, via the engine's `context`."""
    payload = json.loads(_run(["context"], {"worktree": worktree}, {}, tool="riel_context"))
    if payload.get("error"):
        return None, payload["error"]
    if payload.get("exit_code") != 0:
        stderr = (payload.get("stderr") or "").strip()
        return None, stderr or "the engine's context call failed"
    try:
        keywords = json.loads(payload.get("stdout") or "{}").get("keywords") or []
    except ValueError:
        return None, "the engine's context call did not return JSON"
    return keywords, None


def riel_context(args: dict, **kwargs) -> str:
    """The contract's context keywords, for the agent to search memory with."""
    worktree = _worktree(args, kwargs)
    if not os.path.isdir(worktree):
        return _error(f"worktree is not a directory: {worktree}", worktree=worktree)

    raw_keywords = args.get("keywords")
    if raw_keywords:
        if isinstance(raw_keywords, str):
            raw_keywords = [raw_keywords]
        keywords = [{"term": str(k).strip(), "source": ""}
                    for k in raw_keywords if str(k).strip()]
        origin = "argument"
    else:
        keywords, error = _contract_keywords(worktree)
        if error:
            return _error(error, worktree=worktree, origin="contract",
                          hint="write the contract first, or pass keywords explicitly")
        keywords = keywords or []
        origin = "contract"

    total = len(keywords)
    keywords = keywords[:MAX_KEYWORDS]
    payload = {
        "worktree": worktree,
        "origin": origin,
        "keywords": keywords,
        "truncated": total > len(keywords),
    }
    if keywords:
        payload["next"] = (
            "Search these terms with the memory tools you have configured (DRAN, "
            "your own memory) and keep the answers in the ledger's ## Core — max 2 "
            "live items. This tool does not search: it only hands you the index."
        )
    else:
        payload["note"] = "the contract declares no '### Context keywords' to search"
    return json.dumps(payload, ensure_ascii=False)


# --------------------------------------------------------------- the plan ---
# Typed doors to the verbs the prose uses, so nothing the agent calls looks like
# a command line: no tool takes argv, no flag travels as data. Each one maps its
# named parameters onto the engine's argv — the mapping is the tool's job, not
# the model's.
BRIEF_VERBS = ("new", "validate", "digest", "slice")
SHAPING_VERBS = ("new", "validate")
CLEAN_SCOPES = ("ledger", "all", "purge")
MAX_PARAMS = 24


def _params(raw) -> "list | str":
    """`["key=value", …]` from the caller as the engine's `--param` pairs."""
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, str) or "=" not in item for item in raw):
        return _error('params must be an array of "key=value" strings')
    return [part for item in raw[:MAX_PARAMS] for part in ("--param", item)]


def riel_brief(args: dict, **kwargs) -> str:
    """Contract and packet artifacts: instantiate, validate, digest, slice."""
    verb = str(args.get("verb") or "").strip().lower()
    if verb not in BRIEF_VERBS:
        return _error("unsupported verb for riel_brief", verb=verb, allowed=list(BRIEF_VERBS))

    argv = ["brief", verb]
    if verb == "new":
        kind = str(args.get("template") or args.get("type") or "").strip()
        if not kind:
            return _error("riel_brief verb='new' needs 'template' (feature, bugfix, packet, …)",
                          hint="pass template='<name>'; the engine lists the shipped ones with --list")
        argv += ["--type", kind]
        params = _params(args.get("params"))
        if isinstance(params, str):
            return params
        argv += params
    else:
        target = str(args.get("file") or "").strip()
        if not target:
            return _error(f"riel_brief verb='{verb}' needs 'file' (the contract or packet path)")
        argv.append(os.path.expanduser(target))
        if verb == "slice":
            phase = str(args.get("phase") or "").strip()
            if phase:
                argv += ["--phase", phase]
    return _run(argv, args, kwargs, tool="riel_brief", verb=verb)


def riel_shaping(args: dict, **kwargs) -> str:
    """The pre-contract research: instantiate the skeleton or check it (Spec 7)."""
    verb = str(args.get("verb") or "").strip().lower()
    if verb not in SHAPING_VERBS:
        return _error("unsupported verb for riel_shaping", verb=verb, allowed=list(SHAPING_VERBS))

    argv = ["shaping", verb]
    if verb == "new":
        params = _params(args.get("params"))
        if isinstance(params, str):
            return params
        argv += params
        if args.get("force"):
            argv.append("--force")
    else:
        target = str(args.get("file") or "").strip()
        if target:
            argv.append(os.path.expanduser(target))
    return _run(argv, args, kwargs, tool="riel_shaping", verb=verb)


def riel_clean(args: dict, **kwargs) -> str:
    """Archive the worktree's Riel state. `ledger` backs up the ledger only;
    `all` adds the contract and the shaping; `purge` deletes without a backup."""
    scope = str(args.get("scope") or "ledger").strip().lower()
    if scope not in CLEAN_SCOPES:
        return _error("unsupported scope for riel_clean", scope=scope, allowed=list(CLEAN_SCOPES))
    argv = ["clean"] + (["--all"] if scope == "all" else ["--purge"] if scope == "purge" else [])
    return _run(argv, args, kwargs, tool="riel_clean")


def riel_fetch(args: dict, **kwargs) -> str:
    """Materialize a remote contract into the worktree (HTTPS, atomic, sha256)."""
    url = str(args.get("url") or "").strip()
    out = str(args.get("out") or ".riel/contract.md").strip()
    if not url:
        return _error("riel_fetch needs 'url' and writes to 'out' (default .riel/contract.md)")
    argv = ["fetch", url, "-o", os.path.expanduser(out)]
    sha = str(args.get("sha256") or "").strip()
    if sha:
        argv += ["--sha256", sha]
    headers = _str_list(args.get("headers"), "headers")
    if isinstance(headers, str):
        return headers
    for header in headers:
        argv += ["--header", header]
    if args.get("allow_http"):
        argv.append("--allow-http")
    return _run(argv, args, kwargs, tool="riel_fetch")


def riel_check(args: dict, **kwargs) -> str:
    """A file's delivery check: dense markers, the graph digest and — when asked
    with `mermaid=true` — the parser-level check of every mermaid block (mmdc).
    """
    target = str(args.get("file") or "").strip()
    if not target:
        return _error("riel_check needs 'file'")
    path = os.path.expanduser(target)
    ship = json.loads(_run(["ship", path], args, kwargs, tool="riel_check", verb="ship"))
    digest = json.loads(_run(["digest", path], args, kwargs, tool="riel_check", verb="digest"))
    payload = {
        "file": path,
        "worktree": ship.get("worktree"),
        "ship": {"exit_code": ship.get("exit_code"), "passed": ship.get("passed"),
                 "stdout": ship.get("stdout"), "stderr": ship.get("stderr")},
        "digest": {"exit_code": digest.get("exit_code"), "passed": digest.get("passed"),
                   "stdout": digest.get("stdout"), "stderr": digest.get("stderr")},
        "passed": bool(ship.get("passed")) and bool(digest.get("passed")),
    }
    if args.get("mermaid"):
        parse = json.loads(_run(["mermaid", path], args, kwargs, tool="riel_check", verb="mermaid"))
        payload["mermaid"] = {
            "exit_code": parse.get("exit_code"), "passed": parse.get("passed"),
            "stdout": parse.get("stdout"), "stderr": parse.get("stderr"),
        }
        # No blocks or no mmdc is exit 0 with a SKIP line: silence is not a failure.
        payload["passed"] = payload["passed"] and bool(parse.get("passed"))
    return json.dumps(payload, ensure_ascii=False)


def riel_guide(args: dict, **kwargs) -> str:
    """Riel's prose — the index (no `topic`), one guide, or one section of it.

    Reads the package's own `guide/`, so it needs no worktree state and runs no
    engine: the prose ships with the plugin. The envelope is the same shape as
    every other tool's, with the text in `stdout` (and `content`).
    """
    module = plugin_guide()
    worktree = _worktree(args, kwargs)
    topic = str(args.get("topic") or "").strip()
    section = str(args.get("section") or "").strip() or None

    if not topic:
        rows = module.entries()
        if not rows:
            return _error(
                "the package ships no guide/ prose",
                path=str(module.GUIDE_DIR),
                hint="from the repo checkout: make plugin-build",
            )
        text = module.index_text()
        return json.dumps(
            {
                "tool": "riel_guide",
                "worktree": worktree,
                "exit_code": 0,
                "passed": True,
                "topic": None,
                "topics": module.topics(),
                "bytes": len(text),
                "stdout": text,
                "content": text,
                "stderr": "",
            },
            ensure_ascii=False,
        )

    text, error = module.read(topic, section)
    if error:
        payload = dict(error)
        payload["tool"] = "riel_guide"
        payload["worktree"] = worktree
        payload["exit_code"] = 1
        payload["passed"] = False
        return json.dumps(payload, ensure_ascii=False)
    return json.dumps(
        {
            "tool": "riel_guide",
            "worktree": worktree,
            "exit_code": 0,
            "passed": True,
            "topic": topic,
            "section": section,
            "bytes": len(text),
            "stdout": text,
            "content": text,
            "stderr": "",
        },
        ensure_ascii=False,
    )


# ------------------------------------------------------------------- guard ---
# The `tools` group switch. The check_fn Hermes runs hides a tool from the
# model, but `dispatch` does not re-evaluate it — a prompt frozen before the
# switch still knows the tool — so the handler refuses too, BEFORE the
# subprocess. Fail-open on the read; explicit refusal on the call.
def _group_off_error(group: str) -> str:
    return _error(
        f"the '{group}' group is off — this tool would not run",
        group=group,
        hint=(
            "re-enable it in the Riel chip (status bar) or run: /riel on "
            f"{group} — it applies to the NEXT session; the switch on the chip "
            "is immediate for nothing but the refusal you just got"
        ),
    )


def _guard(fn):
    def handler(args: dict, **kwargs) -> str:
        try:
            enabled = plugin_settings().read_bool("tools", True)
        except Exception:
            enabled = True  # fail-open: a broken settings read never disables work
        if not enabled:
            return _group_off_error("tools")
        return fn(args, **kwargs)

    handler.__name__ = getattr(fn, "__name__", "handler")
    return handler


HANDLERS = {
    "riel_note": _guard(riel_note),
    "riel_seam": _guard(riel_seam),
    "riel_resume": _guard(riel_resume),
    "riel_todo": _guard(riel_todo),
    "riel_context": _guard(riel_context),
    "riel_state": _guard(riel_state),
    "riel_brief": _guard(riel_brief),
    "riel_shaping": _guard(riel_shaping),
    "riel_clean": _guard(riel_clean),
    "riel_fetch": _guard(riel_fetch),
    "riel_check": _guard(riel_check),
    "riel_guide": _guard(riel_guide),
}
