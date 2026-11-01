"""Tool handlers — machinery for the Riel plugin.

Every task handler runs the **bundled engine** in a fresh subprocess whose cwd
is the session's worktree. That script is the engine, never an interface: the
agent sees tools, and no tool accepts argv — every parameter is typed. The
engine stays the sole writer of `.riel/ledger.md`: this module adds no ledger
semantics, no format, no state of its own.

Why a subprocess instead of importing the engine in-process: the engine resolves
`.riel/` relative to the process cwd, and a gateway serves several sessions from
one process — an `os.chdir` would be global state shared by every session. The
subprocess gives each call its own cwd AND its own `--worktree`, so concurrent
sessions cannot write into each other's ledger. The cost is ~40 ms per call; the
isolation is worth more than 40 ms.

Three rules this module follows by construction (see `_load.py`):

  * one loader — no by-path dance here;
  * one worktree resolver — no per-handler cwd guesses;
  * one envelope — `{tool, worktree, exit_code, passed, stdout, stderr}` from
    every tool, composite ones included.

Stdlib only, and importable outside Hermes: nothing here imports Hermes at
module level, so the repo's test suite can exercise these handlers directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

try:  # a package import when the host loaded us as one …
    from . import _load
except ImportError:  # … and a by-path load when it did not (repo suite, dashboard)
    import importlib.util as _ilu
    import pathlib as _pl

    _spec = _ilu.spec_from_file_location(
        "riel_plugin_load", _pl.Path(__file__).resolve().with_name("_load.py"))
    _load = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_load)

ENGINE = _load.ENGINE
TIMEOUT_SECS = 60
ENGINE_MISSING_HINT = "reinstall the plugin: hermes plugins update riel"

SEAM_MODES = ("read", "resume", "json")
CONTRACT_VERBS = ("new", "validate", "digest", "slice")
SHAPING_VERBS = ("new", "validate")
CLEAN_SCOPES = ("ledger", "all", "purge")
MAX_PARAMS = 24
MAX_KEYWORDS = 12


def _params():
    """`engine/params.py` — the one declaration of `riel_note`'s parameters."""
    return _load.sibling("riel_engine_params", "engine/params.py")


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(message: str, **extra) -> str:
    return _dump(_load.error(message, **extra))


def _worktree(args: dict, kwargs: dict) -> str:
    return _load.worktree(kwargs, args.get("worktree"))


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
            hint=ENGINE_MISSING_HINT,
        )
    try:
        proc = subprocess.run(
            [sys.executable, str(ENGINE), "--worktree", worktree, *argv],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        return _error(f"the engine timed out after {TIMEOUT_SECS}s", tool=tool, worktree=worktree)
    except OSError as exc:
        return _error(f"the engine could not be executed: {exc}", tool=tool, worktree=worktree)
    payload = _load.envelope(
        tool, worktree,
        exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
    )
    if verb:
        payload["verb"] = verb
    return _dump(payload)


def _flag_args(args: dict) -> list:
    """Map tool arguments onto the engine's flags — derived from params.py."""
    argv: list = []
    for param in _params().NOTE_PARAMS:
        value = args.get(param["name"])
        if value is None or str(value).strip() == "":
            continue
        if param["kind"] == "int":
            try:
                argv += [param["flag"], str(int(value))]
            except (TypeError, ValueError):
                raise ValueError(f"{param['name']} must be an integer, got {value!r}")
        else:
            argv += [param["flag"], str(value)]
    return argv


def _from_contract_args(args: dict) -> list:
    raw = args.get("from_contract")
    if raw is None:
        return []
    flag = _params().FROM_CONTRACT["flag"]
    value = str(raw).strip()
    if value == "" or value.lower() in {"false", "no", "0"}:
        return []
    if value.lower() in {"true", "yes", "1"}:
        return [flag]
    return [flag, os.path.expanduser(value)]


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
        accepted = ", ".join(sorted(_params().PARAM_NAMES))
        return _error(
            "riel_note needs at least one content flag (or from_contract)",
            accepted=accepted,
            note="with no flags the engine just re-prints the ledger; use riel_seam for that",
        )
    return _run(["note", *argv], args, kwargs, tool="riel_note")


def _passthrough(verb: list, tool: str, extra_note: "str | None" = None):
    """A handler that runs one engine verb and, optionally, adds a note.

    `tool` is the name this passthrough answers as — the envelope's provenance
    says which tool spoke, never which engine verb ran.
    """
    def handler(args: dict, **kwargs) -> str:
        payload = json.loads(_run(verb, args, kwargs, tool=tool))
        if extra_note and isinstance(payload, dict) and payload.get("exit_code") == 0:
            payload["next"] = extra_note
        return _dump(payload)

    return handler


def riel_seam(args: dict, **kwargs) -> str:
    """The seam re-read — one tool for state (read), post-gap (resume) and JSON.

    Three tools used to read the same ledger: `riel_seam` (prose), `riel_resume`
    (prose + a static invariant dump) and `riel_state` (JSON). The mode is the
    only difference, so it is a parameter, not three catalog entries.
    """
    mode = str(args.get("mode") or "read").strip().lower()
    if mode not in SEAM_MODES:
        return _error("unsupported mode for riel_seam", mode=mode, allowed=list(SEAM_MODES))
    payload = json.loads(_run(["seam", "--mode", mode], args, kwargs,
                              tool="riel_seam", verb=mode))
    if args.get("anchors") and payload.get("exit_code") == 0:
        anchors = json.loads(_run(["anchor"], args, kwargs, tool="riel_seam", verb="anchors"))
        payload["anchors"] = {
            "exit_code": anchors.get("exit_code"),
            "passed": anchors.get("passed"),
            "stdout": anchors.get("stdout"),
            "stderr": anchors.get("stderr"),
        }
    return _dump(payload)


riel_todo = _passthrough(["todo"], tool="riel_todo", extra_note=(
    "Inject this into the session todo: pass the items array (stdout) to the "
    "todo_list tool (todos=<array>) so the UI shows the plan — the contract's "
    "goal, its phases and their steps."
))


# ------------------------------------------------------------------ context ---
# The tool is an INDEX provider, not a searcher: a plugin cannot reach the
# memory backends. Those tools live in `agent/memory_manager.py`
# (`get_all_tool_schemas` / `handle_tool_call`), not in `tools.registry`, so
# `ctx.dispatch_tool("dran_memory_search", …)` returns "Unknown tool" — the
# agent reaches them because its executor routes to the memory manager. So the
# plugin supplies the contract's keywords and WHO searches decides: the agent,
# with whatever memory backend it has configured.
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
    return _dump(payload)


# --------------------------------------------------------------- the plan ---
# Typed doors to the verbs the prose uses, so nothing the agent calls looks like
# a command line: no tool takes argv, no flag travels as data. Each one maps its
# named parameters onto the engine's argv — the mapping is the tool's job, not
# the model's.
def _params_arg(raw) -> "list | str":
    """`["key=value", …]` from the caller as the engine's `--param` pairs."""
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, str) or "=" not in item for item in raw):
        return _error('params must be an array of "key=value" strings')
    return [part for item in raw[:MAX_PARAMS] for part in ("--param", item)]


def riel_contract(args: dict, **kwargs) -> str:
    """Contract and packet artifacts: instantiate, validate, digest, slice."""
    verb = str(args.get("verb") or "").strip().lower()
    if verb not in CONTRACT_VERBS:
        return _error("unsupported verb for riel_contract", verb=verb, allowed=list(CONTRACT_VERBS))

    argv = ["contract", verb]
    if verb == "new":
        kind = str(args.get("template") or args.get("type") or "").strip()
        if not kind:
            return _error("riel_contract verb='new' needs 'template' (feature, bugfix, packet, …)",
                          hint="pass template='<name>'; the engine lists the shipped ones with --list")
        argv += ["--type", kind]
        params = _params_arg(args.get("params"))
        if isinstance(params, str):
            return params
        argv += params
    else:
        target = str(args.get("file") or "").strip()
        if not target:
            return _error(f"riel_contract verb='{verb}' needs 'file' (the contract or packet path)")
        argv.append(os.path.expanduser(target))
        if verb == "slice":
            phase = str(args.get("phase") or "").strip()
            if phase:
                argv += ["--phase", phase]
    return _run(argv, args, kwargs, tool="riel_contract", verb=verb)


def riel_shaping(args: dict, **kwargs) -> str:
    """The pre-contract research: instantiate the skeleton or check it (Spec 7)."""
    verb = str(args.get("verb") or "").strip().lower()
    if verb not in SHAPING_VERBS:
        return _error("unsupported verb for riel_shaping", verb=verb, allowed=list(SHAPING_VERBS))

    argv = ["shaping", verb]
    if verb == "new":
        params = _params_arg(args.get("params"))
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

    ONE engine call: the engine's `check` verb runs the three report functions
    in one process instead of the three subprocesses this handler used to chain.
    """
    target = str(args.get("file") or "").strip()
    if not target:
        return _error("riel_check needs 'file'")
    argv = ["check", os.path.expanduser(target)]
    if args.get("mermaid"):
        argv.append("--mermaid")
    raw = json.loads(_run(argv, args, kwargs, tool="riel_check"))
    if raw.get("error") or raw.get("exit_code") is None:
        return _dump(raw)
    try:
        body = json.loads(raw.get("stdout") or "{}")
    except ValueError:
        return _dump(raw)
    halves = {}
    for name, half in (body.get("halves") or {}).items():
        passed = bool(half.get("passed"))
        halves[name] = {
            "exit_code": 0 if passed else 1,
            "passed": passed,
            "stdout": half.get("stdout") or "",
            "stderr": "",
        }
    ok = bool(body.get("passed"))
    payload = _load.envelope(
        "riel_check", raw.get("worktree", ""), exit_code=0 if ok else 1,
        stdout="\n".join((half["stdout"] or "") for half in halves.values()).strip(),
        stderr=raw.get("stderr") or "",
        file=body.get("file") or target,
    )
    payload.update(halves)
    return _dump(payload)


def riel_guide(args: dict, **kwargs) -> str:
    """Riel's prose — the index (no `topic`), one guide's outline, or a section.

    Reads the package's own `guide/`, so it needs no worktree state and runs no
    engine: the prose ships with the plugin. A topic answers with that guide's
    SECTION OUTLINE by default; `full=true` pays for the whole body, and
    `section=` reads one `## heading`. The envelope is the shared one, with the
    text in `stdout` (and `content`).
    """
    module = _load.guide()
    worktree = _worktree(args, kwargs)
    topic = str(args.get("topic") or "").strip()
    section = str(args.get("section") or "").strip() or None

    if not topic:
        rows = module.entries()
        if not rows:
            return _error(
                "the package ships no guide/ prose",
                path=str(module.GUIDE_DIR),
                hint=ENGINE_MISSING_HINT,
            )
        text = module.index_text()
        payload = _load.envelope("riel_guide", worktree, stdout=text,
                                 topic=None, topics=module.topics(), bytes=len(text))
        payload["content"] = text
        return _dump(payload)

    text, error = module.read(topic, section, bool(args.get("full")))
    if error:
        payload = dict(error)
        payload["tool"] = "riel_guide"
        payload["worktree"] = worktree
        payload["exit_code"] = 1
        payload["passed"] = False
        return _dump(payload)
    payload = _load.envelope("riel_guide", worktree, stdout=text, topic=topic,
                             section=section, full=bool(args.get("full")),
                             bytes=len(text))
    payload["content"] = text
    return _dump(payload)


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
            enabled = _load.settings().read_bool("tools", True)
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
    "riel_todo": _guard(riel_todo),
    "riel_context": _guard(riel_context),
    "riel_contract": _guard(riel_contract),
    "riel_shaping": _guard(riel_shaping),
    "riel_clean": _guard(riel_clean),
    "riel_fetch": _guard(riel_fetch),
    "riel_check": _guard(riel_check),
    "riel_guide": _guard(riel_guide),
}