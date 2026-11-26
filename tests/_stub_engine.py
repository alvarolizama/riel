"""A stand-in `engine/run.py` for the plugin suite — the 2.0 run/shaping contract.

The bundled engine is the sole writer of the formats, and its own suite
(`tests/test_engine.py`, another worker's) pins it. The PLUGIN suite's job is
the layer around it — the handlers, the schemas, the gate, the dashboard and
the chip — and pinning that layer to a real engine would couple two suites
that two workers move at the same time. So the tests here run against THIS
stub: a faithful, tiny implementation of the contract the plugin codes to.

The contract (v2 — run/shaping model, clean break):

    run_verb(argv, worktree=None, out=None, err=None) -> int

  * one runner, explicit per-call sinks (never a global redirect), the
    worktree by parameter (no chdir);
  * verbs: `project new|validate|status`, `shape new|validate`,
    `run new|validate|activate|rebase|`
    `status|list|slice`, `note`, `todo`, `clean`, `check`;
  * `clean` wipes ALL of .riel/ (archiving opt-in, outside .riel/);
  * `run new` PRINTS the draft (never writes); `run status` answers ONE JSON
    OBJECT;
  * `note --gate G --command CMD --claim P …`: the ENGINE executes the command
    and records the evidence E# — a caller never passes an exit code. The
    note surface is `engine/params.py` (the real, packaged declaration — the
    stub does not re-declare it).

The stub keeps each contract in `.riel/runs/<slug>.md` behind a ` ```riel-state `
fence — a real file the gate, the dashboard and the chip can all see.

`install(tools)` points a freshly-loaded `tools` module at this file (as the
engine), so the note derivation is exercised against the packaged
`engine/params.py` — the same source the real handlers will read.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "2.0.0"

ENGINE_PATH = Path(__file__).resolve()


def install(tools):
    """Point a `tools` module at the stub engine (its params stay the real ones)."""
    tools.ENGINE = ENGINE_PATH
    tools._ENGINE["module"] = None  # force the next call to (re)load — the stub
    return tools


# ----------------------------------------------------------------- state ----

_FENCE_OPEN = "```riel-state"
_FENCE_CLOSE = "```"


def _runs_dir(worktree):
    return os.path.join(worktree, ".riel", "runs")


def _contract_slugs(worktree):
    folder = _runs_dir(worktree)
    if not os.path.isdir(folder):
        return []
    return sorted(f[:-3] for f in os.listdir(folder)
                  if f.endswith(".md") and not f.endswith(".bak.md"))


def _state_path(worktree, slug=None):
    """One contract in .riel/runs/ — executed in place, no live file."""
    if slug:
        return os.path.join(_runs_dir(worktree), str(slug) + ".md")
    slugs = _contract_slugs(worktree)
    if len(slugs) == 1:
        return os.path.join(_runs_dir(worktree), slugs[0] + ".md")
    return ""


def _selector(argv):
    return argv[argv.index("--run") + 1] if "--run" in argv else None


def _shaping_path(worktree):
    """The single shaping in .riel/shapings/, or "" — there is no loose file."""
    folder = os.path.join(worktree, ".riel", "shapings")
    if not os.path.isdir(folder):
        return ""
    files = sorted(f for f in os.listdir(folder) if f.endswith(".md"))
    return os.path.join(folder, files[0]) if len(files) == 1 else ""


def _empty_state():
    return {"active": False, "goal": "", "next": "", "phase": "",
            "claims": [], "gates": [], "evidence": [], "open": []}


def _load_state(worktree, slug=None):
    path = _state_path(worktree, slug)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if _FENCE_OPEN not in text:
        return None
    body = text.split(_FENCE_OPEN, 1)[1].split(_FENCE_CLOSE, 1)[0]
    try:
        state = json.loads(body)
    except ValueError:
        return None
    return state if isinstance(state, dict) else None


def _save_state(worktree, state, slug=None):
    os.makedirs(_runs_dir(worktree), exist_ok=True)
    body = (
        "# Run: {}\n\n```riel-state\n{}\n```\n".format(
            state.get("goal") or "draft", json.dumps(state, ensure_ascii=False, indent=1))
    )
    with open(_state_path(worktree, slug or state.get("slug") or "run"),
              "w", encoding="utf-8") as fh:
        fh.write(body)


def seed(worktree, claims=(), gates=(), **extra):
    """Write a run state directly — what `run new` + a hand-edited definition produces.

    Claims and gates are created HERE (in the definition), never by `note`: the note
    only ever executes gates and records evidence against existing ids.
    """
    state = {**_empty_state(), "active": True, **extra,
             "claims": [{"id": c, "text": "", "done": False} for c in claims],
             "gates": [{"id": g, "command": "", "covering": "", "exit_code": None,
                        "done": False} for g in gates]}
    _save_state(worktree, state)
    return state


# ----------------------------------------------------------------- verbs ----

def _note(argv, worktree, out, err):
    flags = {}
    gate_ids, claim_ids = [], []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--gate", "--claim"):
            i += 1
            (gate_ids if arg == "--gate" else claim_ids).append(argv[i])
        elif arg == "--partial":
            flags["partial"] = True
        elif arg.startswith("--"):
            i += 1
            flags[arg[2:].replace("-", "_")] = argv[i]
        else:
            err.write("note: unexpected positional {}\n".format(arg))
            return 2
        i += 1
    if not flags and not gate_ids and not claim_ids:
        err.write("note needs at least one content flag\n")
        return 2

    state = _load_state(worktree)
    if state is None:
        # A first note IS the task going live: the run it creates is active
        # (the gate's opt-in), not a draft.
        state = {**_empty_state(), "active": True}

    if flags.get("core"):
        state.setdefault("core", []).append(flags["core"])
    if flags.get("open"):
        state["open"].append({"q": flags["open"], "settled_by": flags.get("settled_by", "")})
    if flags.get("next"):
        state["next"] = flags["next"]

    gate_result = None
    if flags.get("command"):
        # The gate command IS a shell command by contract (the real engine
        # runs it the same way): it arrives from the test itself, not from a
        # network peer, and commands like `make test` need a shell.
        with open(os.devnull, "wb") as devnull:
            code = subprocess.call(flags["command"], shell=True, cwd=worktree,
                                   stdout=devnull, stderr=devnull)
        partial = bool(flags.get("partial"))
        passed = (code == 0) and not partial
        gate_result = (code, passed)
        evidence = {
            "id": "E{}".format(len(state["evidence"]) + 1),
            "gates": gate_ids, "command": flags["command"],
            "covering": flags.get("covering", ""), "exit_code": code,
            "partial": partial,
            "passed": passed,
        }
        state["evidence"].append(evidence)
        for gate in state["gates"]:
            if gate["id"] in gate_ids:
                gate["exit_code"] = code
                gate["done"] = passed
        for claim in state["claims"]:
            if claim["id"] in claim_ids:
                claim["done"] = passed

    if "close" in flags:
        if not flags.get("evidence"):
            err.write("close requires --evidence\n")
            return 2
        index = int(flags["close"]) - 1
        if 0 <= index < len(state["open"]):
            state["open"][index]["settled_by_evidence"] = flags["evidence"]
            state["open"][index]["settled"] = True

    _save_state(worktree, state)
    out.write(json.dumps({"ok": True, "claims": len(state["claims"]),
                          "gates": len(state["gates"]),
                          "evidence": len(state["evidence"])}) + "\n")
    if gate_result is not None:
        out.write("gate_exit_code: {} | gate_passed: {}\n".format(
            gate_result[0], str(gate_result[1]).lower()))
    return 0


def _check(argv, worktree, out, err):
    if not argv:
        err.write("check needs FILE\n")
        return 2
    target = argv[0] if os.path.isabs(argv[0]) else os.path.join(worktree, argv[0])
    mermaid = "--mermaid" in argv[1:]
    halves = {
        "ship": {"passed": True, "stdout": "ship ok"},
        "digest": {"passed": True, "stdout": "digest A -> B"},
    }
    if not os.path.isfile(target):
        halves["ship"] = {"passed": False, "stdout": ""}
        body = {"passed": False, "file": target, "halves": halves}
    else:
        body = {"passed": True, "file": target, "halves": halves}
    if mermaid:
        body["halves"]["mermaid"] = {"passed": True, "stdout": "PASS: 1 block(s)"}
    out.write(json.dumps(body) + "\n")
    return 0 if body["passed"] else 1


def run_verb(argv, worktree=None, out=None, err=None):
    """The runner the plugin layer codes to: explicit sinks, worktree by parameter."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    worktree = os.path.abspath(worktree or os.getcwd())
    if argv[:1] == ["--worktree"]:
        worktree = os.path.abspath(argv[1])
        argv = argv[2:]
    verb = argv[0] if argv else ""

    if verb == "project":
        sub = argv[1] if len(argv) > 1 else ""
        if sub == "new":
            out.write("# Project: draft\n\n<!-- riel-project/v1 -->\n\n"
                      "## Objective\n{{objective}}\n\n## Graph\n"
                      "- S1: .riel/shapings/demo.md\n")
            return 0  # RENDERS — never writes
        if sub in ("validate", "status"):
            target = argv[2] if len(argv) > 2 else os.path.join(
                worktree, ".riel", "project.md")
            target = target if os.path.isabs(target) else os.path.join(worktree, target)
            if not os.path.isfile(target):
                err.write("no project file at {}\n".format(target))
                return 2
            with open(target, encoding="utf-8") as fh:
                text = fh.read()
            nodes = re.findall(r"^- (S\d+):\s*(.+)$", text, re.M)
            ok = "<!-- riel-project/v1 -->" in text and bool(nodes)
            if sub == "validate":
                if ok:
                    out.write("project ok\n")
                    return 0
                err.write("project is not valid: {}\n".format(target))
                return 1
            rows = {}
            for nid, ref in nodes:
                slug = os.path.basename(ref.strip())[:-3]
                archived = os.path.join(worktree, ".riel", "runs", slug + ".md")
                rows[nid] = {"shaping": ref.strip(), "slug": slug,
                             "status": "done" if os.path.isfile(archived) else "pending"}
            out.write(json.dumps({
                "format": "riel-project/v1", "nodes": rows,
                "done": bool(rows) and all(r["status"] == "done" for r in rows.values()),
            }) + "\n")
            return 0
        err.write("unknown project verb: {}\n".format(sub))
        return 2

    if verb == "shape":
        sub = argv[1] if len(argv) > 1 else ""
        if sub == "new":
            params = [argv[i + 1] for i, a in enumerate(argv) if a == "--param"]
            name = params[0].split("=", 1)[1] if params else "draft"
            uid = "shp_{:08x}".format(
                sum(ord(c) * (i + 1) for i, c in enumerate(name)) % 0xffffffff)
            out.write(
                "# Shaping: {}\n\n<!-- riel-shaping/v3 id:{} -->\n\n"
                "## Question\n{{{{question}}}}\n\n"
                "## Answer\n{{{{answer}}}} — supported by F1\n\n"
                "## Findings\n\n### F1: {{{{finding}}}}\n"
                "— source: {{{{source}}}}, confidence high\n\n"
                "## Facts\n- {{{{fact}}}}\n\n"
                "## Not wanted\n- A1: {{{{option}}}} — verdict: discarded: {{{{reason}}}}\n\n"
                "## What we want\n- We need {{{{need}}}}\n"
                "- Claim seeds: {{{{claim}}}} — supported by F1\n"
                "- Scope: in {{{{in}}}} · out {{{{out}}}}\n\n"
                "## Open\n- Q1: {{{{open_question}}}} — settled by: {{{{test}}}}\n".format(name, uid))
            return 0  # RENDERS the template — never writes
        if sub == "validate":
            target = argv[2] if len(argv) > 2 else _shaping_path(worktree)
            if not target:
                err.write("no shaping to validate — name one under .riel/shapings/\n")
                return 1
            target = target if os.path.isabs(target) else os.path.join(worktree, target)
            if os.path.isfile(target):
                with open(target, encoding="utf-8") as fh:
                    body = fh.read()
                ok = ("<!-- riel-shaping/v3 id:shp_" in body
                      and "## Question" in body and "## Answer" in body)
            else:
                ok = False
            if ok:
                out.write("shaping ok\n")
                return 0
            err.write("shaping is not valid: {}\n".format(target))
            return 1
        err.write("unknown shape verb: {}\n".format(sub))
        return 2

    if verb == "run":
        sub = argv[1] if len(argv) > 1 else ""
        if sub == "new":
            template = argv[argv.index("--template") + 1] if "--template" in argv else "run"
            params = [argv[i + 1] for i, a in enumerate(argv) if a == "--param"]
            out.write(
                "# Run: {{{{title}}}} (template {})\n\n<!-- riel-run/v1 -->\n\n"
                "## Objective\n{{{{objective}}}}\n\n## Context\n\n### Why\n{{{{why}}}}\n\n"
                "## Constraints\n- {{{{constraint}}}}\n\n## Phases\n\n"
                "### F1: {{{{phase}}}}\n- RUN {{{{gate_command}}}}\n\n"
                "#### Claims\n- P1: {{{{claim}}}} — anchor: §F1#1\n\n"
                "#### Gates\n- G1: {{{{gate}}}}\n\n"
                "#### Deliverable\n- {{{{phase_deliverable}}}}\n\n"
                "## Deliverable\n{{{{deliverable}}}}\n\n## DO NOT\n- {{{{do_not}}}}\n".format(template))
            return 0  # PRINTS the draft — never writes
        sel = _selector(argv)
        if sub == "validate":
            state = _load_state(worktree, sel)
            if state is None:
                err.write("run is not valid: no readable contract in .riel/runs/\n")
                return 1
            out.write("run ok\n")
            return 0
        if sub == "activate":
            state = _load_state(worktree, sel)
            if state is None:
                err.write("nothing to activate: no contract in .riel/runs/\n")
                return 1
            state["active"] = True
            _save_state(worktree, state, sel)
            out.write("run activated\n")
            return 0
        if sub == "rebase":
            state = _load_state(worktree, sel)
            if state is None:
                err.write("nothing to rebase: no contract in .riel/runs/\n")
                return 1
            state["rebased"] = True
            _save_state(worktree, state, sel)
            out.write("run rebased\n")
            return 0
        if sub == "status":
            path = _state_path(worktree, sel)
            if path and os.path.isfile(path) and _load_state(worktree, sel) is None:
                err.write("the run state is unreadable\n")
                return 1
            out.write(json.dumps(_load_state(worktree, sel) or _empty_state()) + "\n")
            return 0
        if sub == "list":
            rows = []
            for slug in _contract_slugs(worktree):
                state = _load_state(worktree, slug)
                if state is None:
                    rows.append({"slug": slug,
                                 "run": ".riel/runs/{}.md".format(slug),
                                 "error": "the run state is unreadable"})
                    continue
                if state.get("error"):
                    rows.append({"slug": slug,
                                 "run": ".riel/runs/{}.md".format(slug),
                                 "error": state["error"]})
                    continue
                rows.append(dict(state, slug=slug,
                                 run=".riel/runs/{}.md".format(slug)))
            out.write(json.dumps({"contracts": rows}) + "\n")
            return 0
        if sub == "slice":
            if len(argv) < 3:
                err.write("slice needs a phase id\n")
                return 2
            out.write("# Run slice: {}\n".format(argv[2]))
            return 0
        err.write("unknown run verb: {}\n".format(sub))
        return 2

    if verb == "note":
        return _note(argv[1:], worktree, out, err)

    if verb == "todo":
        # EXACTLY one JSON array of {id, content, status, parent} — the goal is
        # the root (no parent), phases nest under it, steps under their phase.
        state = _load_state(worktree) or _empty_state()
        items = []
        if state.get("goal"):
            items.append({"id": "goal", "content": "GOAL: " + state["goal"],
                          "status": "completed" if state.get("done") else "pending"})
            pending = [c for c in state.get("claims", []) if not c.get("done")]
            if pending:
                items.append({"id": "phase-P", "content": "PHASE P: evidence",
                              "status": "in_progress", "parent": "goal"})
                for claim in pending:
                    items.append({"id": "step-P-" + claim["id"],
                                  "content": claim["id"],
                                  "status": "in_progress" if claim is pending[0] else "pending",
                                  "parent": "phase-P"})
        out.write(json.dumps(items, ensure_ascii=False) + "\n")
        return 0

    if verb == "clean":
        # The contract: EVERYTHING inside .riel/ goes; archiving is opt-in and
        # lands outside .riel/ (the stub keeps it beside the worktree).
        riel = os.path.join(worktree, ".riel")
        if not os.path.isdir(riel):
            out.write("nothing to clean\n")
            return 0
        entries = [e for e in sorted(os.listdir(riel)) if e != ".run.lock"]
        if "--archive" in argv[1:]:
            dest = os.path.join(worktree, ".riel-archive", "stub")
            n = 1
            while os.path.exists(dest):
                dest = os.path.join(worktree, ".riel-archive", "stub-%d" % n)
                n += 1
            for root, _dirs, files in os.walk(riel):
                for name in files:
                    src = os.path.join(root, name)
                    dst = os.path.join(dest, os.path.relpath(src, riel))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
            out.write("cleaned {} entry(ies) — archived to {}\n".format(len(entries), dest))
        else:
            out.write("cleaned {} entry(ies) — no archive\n".format(len(entries)))
        for name in entries:
            path = os.path.join(riel, name)
            if os.path.islink(path) or os.path.isfile(path):
                os.unlink(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        return 0

    if verb == "check":
        return _check(argv[1:], worktree, out, err)

    err.write("unknown verb: {}\n".format(verb))
    return 2


if __name__ == "__main__":  # pragma: no cover - the subprocess fallback shape
    worktree = os.getcwd()
    args = sys.argv[1:]
    if args[:1] == ["--worktree"]:
        worktree = args[1]
        args = args[2:]
    sys.exit(run_verb(args, worktree=worktree))
