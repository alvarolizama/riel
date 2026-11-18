"""Tool handlers — machinery for the Riel plugin.

Every task handler runs the **bundled engine** in-process. The engine's runner
binds every path to the worktree by parameter and takes EXPLICIT per-call
sinks — ``run_verb(argv, worktree=…, out=…, err=…)`` — so this module never
touches ``redirect_stdout``: a global redirect is shared state, and a gateway
process serves several sessions at once. The engine stays the sole writer of
`.riel/`: this module adds no run semantics, no format, no state of its own.

Isolation without a subprocess: the engine resolves `.riel/` from the explicit
worktree argument, never from the process cwd — an `os.chdir` would be global
state shared by every session in a gateway, while a worktree parameter is
per-call. The fast path costs ~1 ms per call instead of ~40 ms; the fallback
keeps the same `--worktree` subprocess shape for the rare interpreter that
cannot load the engine.

The surface is SEVEN typed tools (the project/shaping/run model — the
old riel_plan/riel_seam pair is gone, no compatibility shims):

  * `riel_guide` — the prose (no engine call);
  * `riel_project` — new | validate | status, the ordering of shapings;
  * `riel_shape` — new | validate, one question's evidence;
  * `riel_run`   — new | validate | activate | rebase | status | slice | archive;
    activation and every later mutation also refresh the session's checks;
  * `riel_note`  — run-state writes, gates included (the engine executes the
    gate's command and records the evidence E#; a caller never passes an
    exit code);
  * `riel_clean` — wipe the worktree's `.riel/` (archiving is opt-in);
  * `riel_check` — the delivery check on one file.

Rules this module follows by construction (see `_load.py`):

  * one loader — no by-path dance here;
  * one worktree resolver — no per-handler cwd guesses;
  * one envelope — `{tool, worktree, exit_code, passed, stdout, stderr}` from
    every tool, NEGATIVES INCLUDED (an error is an envelope at exit_code 1,
    never a bare `{error: …}`).

Stdlib only, and importable outside Hermes: nothing here imports Hermes at
module level, so the repo's test suite can exercise these handlers directly.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys

def _sibling_load(filename: str):
    spec = importlib.util.spec_from_file_location("riel_plugin_" + filename,
                                                  os.path.join(os.path.dirname(__file__), filename))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load Riel sibling module: " + filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:  # a package import when the host loaded us as one …
    from . import _load, todos as _todos
except ImportError:  # … and a by-path load when it did not (repo suite, dashboard)
    _load = _sibling_load("_load.py")
    _todos = _sibling_load("todos.py")

ENGINE = _load.ENGINE
TIMEOUT_SECS = 60
ENGINE_MISSING_HINT = "reinstall the plugin: hermes plugins update riel"

PROJECT_VERBS = ("new", "validate", "status")
SHAPE_VERBS = ("new", "validate")
RUN_VERBS = ("new", "validate", "activate", "rebase", "status", "slice", "archive")
MAX_PARAMS = 24


def _params():
    """`engine/params.py` — the one declaration of `riel_note`'s parameters."""
    return _load.sibling("riel_engine_params", "engine/params.py")


def _dump(payload) -> str:
    """JSON for the caller — already-JSON strings pass through untouched."""
    return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)


def _error(message: str, **extra) -> str:
    return _dump(_load.error(message, **extra))


def _worktree(args: dict, kwargs: dict) -> str:
    return _load.worktree(kwargs, args.get("worktree"))


def _todo_sync(payload: dict, engine, args: dict, kwargs: dict, tool: str, verb: str) -> dict:
    """Refresh the calling session's checks after a successful run mutation."""
    if payload.get("exit_code") != 0:
        return payload
    worktree = payload.get("worktree") or _worktree(args, kwargs)
    session_id = str(kwargs.get("session_id") or "")
    if tool == "riel_clean":
        return _todos.attach(payload, items=[], clear=True, session_id=session_id)
    mutating = tool == "riel_note" or (
        tool == "riel_run" and verb in ("activate", "rebase", "status"))
    if not mutating:
        return payload
    if engine is None:
        try:
            proc = subprocess.run(
                [sys.executable, str(ENGINE), "--worktree", worktree,
                 "run", "status"],
                cwd=worktree, capture_output=True, text=True, timeout=TIMEOUT_SECS)
            state = json.loads(proc.stdout or "{}") if proc.returncode == 0 else {}
        except Exception:
            state = {}
        rows = state.get("todos")
    else:
        out, err = io.StringIO(), io.StringIO()
        try:
            code = engine.run_verb(["run", "status"], worktree=worktree,
                                   out=out, err=err)
            state = json.loads(out.getvalue() or "{}") if code == 0 else {}
        except Exception:
            state = {}
        rows = state.get("todos")
    if not isinstance(rows, list) or state.get("status") != "active":
        return payload
    payload["todos"] = rows
    return _todos.attach(payload, items=rows, session_id=session_id)


def _run(argv: list, args: dict, kwargs: dict, tool: str, verb: str = "") -> str:
    """Run the engine against the worktree; always return a JSON string, never raise.

    Fast path: the engine loaded IN-PROCESS; `run_verb` binds every path to
    the worktree by parameter (no chdir — safe in a multiplexed gateway) and
    takes explicit `out`/`err` sinks, so nothing here redirects a global
    stream. ~1 ms per call instead of the ~40 ms a fresh subprocess paid.
    Fallback: the same subprocess call, when the engine cannot load in this
    interpreter. `tool`/`verb` are the envelope's provenance: WHICH tool
    answered and, when the tool takes one, with which verb.
    """
    worktree = _worktree(args, kwargs)
    if not os.path.isdir(worktree):
        return _error(f"worktree is not a directory: {worktree}", tool=tool, worktree=worktree)
    if not ENGINE.exists():
        return _error(
            "bundled engine is missing — the package has no engine/ tree",
            tool=tool, worktree=worktree, path=str(ENGINE), hint=ENGINE_MISSING_HINT,
        )
    engine = _engine()
    if engine is not None:
        out, err = io.StringIO(), io.StringIO()
        code = 1
        try:
            code = engine.run_verb(argv, worktree=worktree, out=out, err=err)
        except SystemExit as exc:  # argparse refusals
            code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:  # a jammed verb must not jam the turn
            err.write("{}: {}\n".format(type(exc).__name__, exc))
            code = 1
        payload = _load.envelope(
            tool, worktree,
            exit_code=1 if code is None else int(code),
            stdout=out.getvalue(), stderr=err.getvalue(),
        )
        if verb:
            payload["verb"] = verb
        payload = _todo_sync(payload, engine, args, kwargs, tool, verb)
        return _dump(payload)

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


_ENGINE: dict = {"module": None}


def _engine():
    """The bundled engine loaded in-process; None when it cannot load — YET.

    Only a SUCCESSFUL load is cached. A failed one is retried on the next
    call: the engine ships inside an installable copy and a half-written
    update (`hermes plugins update`) must not poison the loader for the life
    of the process — the call after the update lands works, with no restart.
    """
    if _ENGINE["module"] is not None:
        return _ENGINE["module"]
    try:
        spec = importlib.util.spec_from_file_location("riel_engine", str(ENGINE))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return None  # not cached: the next call tries again
    _ENGINE["module"] = module
    return module


def _params_arg(raw, tool: str) -> "list | str":
    """`[\"key=value\", …]` from the caller as the engine's `--param` pairs."""
    if raw is None:
        return []
    if not isinstance(raw, list) or any(
            not isinstance(item, str) or "=" not in item for item in raw):
        return _error('params must be an array of "key=value" strings', tool=tool)
    argv: list = []
    for item in raw[:MAX_PARAMS]:
        argv += ["--param", item]
    return argv


def _verb_args(args: dict, verbs: tuple, tool: str) -> str:
    verb = str(args.get("verb") or "").strip().lower()
    if verb not in verbs:
        return verb  # caller checks membership; "" and strays come back
    return verb


# --------------------------------------------------------------- project ---
def riel_project(args: dict, **kwargs) -> str:
    """The project — the ORDER in which a set of shapings gets executed.

    `new` RENDERS the project template to stdout (the editor is the writing
    path — the tool never writes `.riel/project.md`), `validate` checks the
    graph of shapings, `status` derives each shaping's progress from the runs'
    own evidence (the live run plus `.riel/runs/`). Nothing here authors a
    shaping or writes state.
    """
    verb = _verb_args(args, PROJECT_VERBS, "riel_project")
    if verb not in PROJECT_VERBS:
        return _error("unsupported verb for riel_project", tool="riel_project",
                      verb=verb, allowed=list(PROJECT_VERBS))
    argv = ["project", verb]
    if verb == "new":
        params = _params_arg(args.get("params"), "riel_project")
        if isinstance(params, str):
            return params
        argv += params
    else:
        target = str(args.get("file") or "").strip()
        if target:
            argv.append(os.path.expanduser(target))
    return _dump(_run(argv, args, kwargs, tool="riel_project", verb=verb))


# ---------------------------------------------------------------- shaping ---
def riel_shape(args: dict, **kwargs) -> str:
    """The shaping — the evidence (Spec 7) before any run is authored.

    `new` RENDERS the shaping template to stdout (the editor is the writing
    path — the tool never writes a shaping file), `params` as
    `[\"key=value\", …]` fill the placeholders; `validate` checks the
    structural rules over `file`.
    """
    verb = _verb_args(args, SHAPE_VERBS, "riel_shape")
    if verb not in SHAPE_VERBS:
        return _error("unsupported verb for riel_shape", tool="riel_shape",
                      verb=verb, allowed=list(SHAPE_VERBS))
    argv = ["shape", verb]
    if verb == "new":
        params = _params_arg(args.get("params"), "riel_shape")
        if isinstance(params, str):
            return params
        argv += params
    else:
        target = str(args.get("file") or "").strip()
        if target:
            argv.append(os.path.expanduser(target))
    return _dump(_run(argv, args, kwargs, tool="riel_shape", verb=verb))


# ------------------------------------------------------------------- run ----
def riel_run(args: dict, **kwargs) -> str:
    """The run — ONE door for the contract (`.riel/run.md`).

    `new` PRINTS the draft template — the agent writes `.riel/run.md` itself,
    then `validate` (the strict riel-run/v1 rules, hashing definition+shaping; the
    file is optional, the worktree's run is the default) and `activate`
    (freezes the definition, computes the hashes, opens r1 — no file argument: it
    always answers for the worktree's run). `rebase` re-freezes the hashes
    after a definition/shaping edit, `status` answers the state as ONE JSON object,
    `slice` extracts one phase (`phase` required) as a child packet, `archive`
    moves the finished run to `.riel/runs/<slug>.md` so the next shaping can
    activate (the project derives its progress from those files).
    """
    verb = _verb_args(args, RUN_VERBS, "riel_run")
    if verb not in RUN_VERBS:
        return _error("unsupported verb for riel_run", tool="riel_run",
                      verb=verb, allowed=list(RUN_VERBS))

    argv = ["run", verb]
    if verb == "new":
        template = str(args.get("template") or "").strip()
        if template:
            argv += ["--template", template]
        params = _params_arg(args.get("params"), "riel_run")
        if isinstance(params, str):
            return params
        argv += params
    elif verb == "slice":
        phase = str(args.get("phase") or "").strip()
        if not phase:
            return _error("riel_run verb='slice' needs 'phase' (the phase id)", tool="riel_run")
        argv.append(phase)
        out = str(args.get("out") or "").strip()
        if out:
            argv += ["-o", os.path.expanduser(out)]
    elif verb == "validate":
        # the one verb that takes a file: the draft may live anywhere
        target = str(args.get("file") or "").strip()
        if target:
            argv.append(os.path.expanduser(target))
    # activate / rebase / status take no file: they answer for the
    # worktree's own .riel/run.md, always.
    return _dump(_run(argv, args, kwargs, tool="riel_run", verb=verb))


# ------------------------------------------------------------------ note ----
def _note_argv(args: dict) -> list:
    """Map the tool's arguments onto the engine's flags — derived from params.py.

    Every parameter comes from `engine/params.py`; the wrapper re-types
    nothing. Two structural rules ride here (`_load.py` owns them so the
    schema cannot drift): the engine-owned `exit_code` is dropped before it
    can lie about a gate, and a repeat parameter travels as ONE array from
    the caller (`claims`) and lands as repeated flags.
    """
    argv: list = []
    for param in _params().NOTE_PARAMS:
        name = param["name"]
        if name in _load.NOTE_FORBIDDEN:
            continue
        flag, kind = param["flag"], param.get("kind", "str")
        caller_name = _load.note_caller_name(param)
        value = args.get(caller_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if caller_name != name or kind == "list":
            if not isinstance(value, list) or any(not isinstance(i, str) for i in value):
                raise ValueError(f"{caller_name} must be an array of strings")
            for item in value:
                argv += [flag, item]
        elif kind == "int":
            try:
                argv += [flag, str(int(value))]
            except (TypeError, ValueError):
                raise ValueError(f"{caller_name} must be an integer, got {value!r}") from None
        else:
            argv += [flag, str(value)]
    return argv


def _note_param_names() -> list:
    """The caller-facing names the note tool accepts (the schema's contract)."""
    return [_load.note_caller_name(p) for p in _params().NOTE_PARAMS
            if p["name"] not in _load.NOTE_FORBIDDEN]


def riel_note(args: dict, **kwargs) -> str:
    """Write to the run state — and run its gates.

    A gate takes gates=['G1'], claims=['P1'], command='<the real command>'
    and covering='<scope>' — the ENGINE executes the command and records the
    evidence `E#`; a caller never passes an exit code. Core facts, open
    questions and closures ride the same tool with their own flags.
    """
    unknown = set(args) - set(_note_param_names()) - {"worktree"}
    if unknown:
        return _error(
            "riel_note received unknown parameter(s): {}".format(
                ", ".join(sorted(unknown))),
            tool="riel_note", accepted=_note_param_names(),
        )
    try:
        argv = _note_argv(args)
    except ValueError as exc:
        return _error(str(exc), tool="riel_note")
    if not argv:
        return _error(
            "riel_note needs at least one content flag",
            tool="riel_note",
            accepted=_note_param_names(),
            note=(
                "a gate takes gates=['G1'], command='<real cmd>', "
                "claims=['P1 …'] — the engine runs it and records the evidence"
            ),
        )
    return _run(["note", *argv], args, kwargs, tool="riel_note")


def riel_clean(args: dict, **kwargs) -> str:
    """Remove EVERYTHING inside the worktree's `.riel/`: the run, project.md,
    shapings/, the archived runs and any legacy state. Archiving is OPT-IN
    (`archive=true`) and lands OUTSIDE `.riel/`, verified by sha256 before
    anything is removed. Without it the removal is not recoverable — `.riel/`
    is gitignored local state. Ask the user before cleaning a worktree whose
    state is not yours.
    """
    if "scope" in args:
        return _error(
            "riel_clean no longer takes 'scope' — it cleans all of .riel/; "
            "pass archive=true to keep a verified copy first",
            tool="riel_clean")
    argv = ["clean"] + (["--archive"] if args.get("archive") else [])
    return _run(argv, args, kwargs, tool="riel_clean")


def riel_check(args: dict, **kwargs) -> str:
    """A file's delivery check: dense markers, the graph digest and — when asked
    with `mermaid=true` — the parser-level check of every mermaid block (mmdc).

    ONE engine call: the engine's `check` verb runs the report functions in
    one process, and this handler folds them into the shared envelope.
    """
    target = str(args.get("file") or "").strip()
    if not target:
        return _error("riel_check needs 'file'", tool="riel_check")
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
                tool="riel_guide", worktree=worktree,
                path=str(module.GUIDE_DIR), hint=ENGINE_MISSING_HINT,
            )
        text = module.index_text()
        payload = _load.envelope("riel_guide", worktree, stdout=text,
                                 topic=None, topics=module.topics(), bytes=len(text))
        payload["content"] = text
        return _dump(payload)

    text, error_info = module.read(topic, section, bool(args.get("full")))
    if error_info:
        payload = dict(error_info)
        payload["tool"] = "riel_guide"
        payload["worktree"] = worktree
        payload["exit_code"] = 1
        payload["passed"] = False
        payload.setdefault("stdout", "")
        payload.setdefault("stderr", payload.get("error", ""))
        return _dump(payload)
    payload = _load.envelope("riel_guide", worktree, stdout=text, topic=topic,
                             section=section, full=bool(args.get("full")),
                             bytes=len(text))
    payload["content"] = text
    return _dump(payload)


# ------------------------------------------------------------------- guard ---
# The `tools` group switch. The check_fn Hermes runs hides a tool from the
# model, but `dispatch` does not re-evaluate it — a prompt frozen before the
# switch still knows the tool — so the handler refuses too, BEFORE the engine.
# Fail-open on the read; explicit refusal on the call.
def _group_off_error(group: str, tool: str = "") -> str:
    return _error(
        f"the '{group}' group is off — this tool would not run",
        group=group, tool=tool,
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
            return _group_off_error("tools", getattr(fn, "__name__", ""))
        return fn(args, **kwargs)

    handler.__name__ = getattr(fn, "__name__", "handler")
    return handler


HANDLERS = {
    "riel_guide": _guard(riel_guide),
    "riel_project": _guard(riel_project),
    "riel_shape": _guard(riel_shape),
    "riel_run": _guard(riel_run),
    "riel_note": _guard(riel_note),
    "riel_clean": _guard(riel_clean),
    "riel_check": _guard(riel_check),
}
