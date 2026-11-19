"""Tool schemas — what the LLM reads to decide when to call these tools.

Machinery only: every task tool delegates to the bundled engine, which is the
sole writer of `.riel/runs/<slug>.md`. Descriptions state when
to use the tool, not how the run is formatted — the format, the rules and the
recipes live in the package's prose, which `riel_guide` serves.
"""

from __future__ import annotations

try:  # a package import when the host loaded us as one …
    from . import _load
except ImportError:  # … and a by-path load when it did not (repo suite, dashboard)
    import importlib.util as _ilu
    import pathlib as _pl

    _spec = _ilu.spec_from_file_location(
        "riel_plugin_load", _pl.Path(__file__).resolve().with_name("_load.py"))
    _load = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_load)

_PARAMS = _load.sibling("riel_engine_params", "engine/params.py")

_WORKTREE = {
    "type": "string",
    "description": (
        "Absolute path to the worktree whose .riel/ state to use. "
        "Omit to use the current session's working directory (the normal case); "
        "pass it only to address another checkout explicitly."
    ),
}


def _note_properties():
    """`riel_note`'s properties — derived from `engine/params.py`, never re-typed.

    The schema, the handler's flag map and the engine's argparse all derive
    from the one declaration (`_load` owns the two structural rules): an
    engine-owned parameter (`exit_code`) never reaches the model, and a
    repeat parameter reaches it as ONE array (`claims`).
    """
    props = {}
    for param in _PARAMS.NOTE_PARAMS:
        if param["name"] in _load.NOTE_FORBIDDEN:
            continue
        caller_name = _load.note_caller_name(param)
        if caller_name != param["name"] or param.get("kind") == "list":
            props[caller_name] = {
                "type": "array",
                "items": {"type": "string"},
                "description": param["help"],
            }
        else:
            props[caller_name] = {
                "type": "integer" if param.get("kind") == "int" else "string",
                "description": param["help"],
            }
    props["worktree"] = _WORKTREE
    return props


RIEL_NOTE = {
    "name": "riel_note",
    "description": (
        "Write to the Riel run state (.riel/runs/<slug>.md) and run its gates. For a gate, "
        "pass gates=['G1'], command='<the real command>' and claims=['P1']; the "
        "engine RUNS the command and records E# evidence. Never pass an exit code. "
        "Core facts, open questions and closures ride the same tool with their own flags."
    ),
    "parameters": {
        "type": "object",
        "properties": _note_properties(),
        "additionalProperties": False,
    },
}

RIEL_PROJECT = {
    "name": "riel_project",
    "description": (
        "Riel project — the ORDER in which a set of shapings gets executed "
        "(.riel/project.md). verb=new RENDERS the template to stdout (the editor "
        "is the writing path), validate checks the graph (every node is one "
        "shaping in .riel/shapings/, no cycles, no shaping bound twice), status "
        "derives each shaping's progress from the runs' own evidence and names "
        "the next one to run. One shaping = one question = one run = one PR. "
        "Riel explains the format and validates it; it never authors the files."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verb": {"type": "string",
                     "description": "One of: new, validate, status."},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=new: placeholder values as ["key=value", …].',
            },
            "file": {"type": "string",
                     "description": "For validate/status: the project path (default .riel/project.md)."},
            "worktree": _WORKTREE,
        },
        "required": ["verb"],
    },
}

RIEL_SHAPE = {
    "name": "riel_shape",
    "description": (
        "Riel shaping — ONE question's evidence, in .riel/shapings/<slug>.md. "
        "verb=new RENDERS the template to stdout with a fresh uid (the editor is "
        "the writing path — params as [\"key=value\", …] fill the placeholders); "
        "validate checks the structural rules over file (one question, sourced "
        "F# findings). Riel explains the format and validates it; it never "
        "authors a shaping."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verb": {"type": "string",
                     "description": "One of: new, validate."},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=new: placeholder values as ["key=value", …].',
            },
            "file": {"type": "string",
                     "description": "For validate: the shaping path (default: the only file in .riel/shapings/; with several, pass one)."},
            "worktree": _WORKTREE,
        },
        "required": ["verb"],
    },
}

RIEL_RUN = {
    "name": "riel_run",
    "description": (
        "Riel run — ONE door for a contract in .riel/runs/<slug>.md, executed "
        "IN PLACE (several may be active at once; pass run=<slug> to pick one). "
        "verb=new PRINTS the draft template (you save it yourself — this tool "
        "never writes it), validate enforces the strict riel-run/v1 format "
        "(hashing definition + shaping), activate arms the contract so the gate "
        "enforces it, rebase re-points the execution state, status returns one "
        "contract's state as ONE JSON object, list enumerates every contract "
        "with its state, slice extracts one phase (pass phase) as a child packet."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verb": {"type": "string",
                     "description": "One of: new, validate, activate, rebase, status, list, slice."},
            "template": {"type": "string",
                         "description": "For verb=new: the template name (default run)."},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=new: placeholder values as ["key=value", …].',
            },
            "file": {"type": "string",
                     "description": "For validate: an explicit contract path."},
            "run": {"type": "string",
                    "description": ("Contract slug in .riel/runs/ (or its path). "
                                    "Optional when only one contract matches; "
                                    "REQUIRED when several are active.")},
            "phase": {"type": "string", "description": "For verb=slice: the phase id to extract."},
            "out": {"type": "string",
                    "description": "For verb=slice: packet destination (optional; the packet always prints to stdout)."},
            "worktree": _WORKTREE,
        },
        "required": ["verb"],
    },
}

RIEL_CLEAN = {
    "name": "riel_clean",
    "description": (
        "Riel housekeeping — remove EVERYTHING inside the worktree's .riel/ "
        "(run.md, project.md, shapings/, runs/, backups and any other file) so a "
        "new task starts clean. Archiving is OPT-IN: archive=true copies the "
        "tree outside .riel/ and verifies every sha256 BEFORE removing anything. "
        "Without it the removal is NOT recoverable (.riel/ is gitignored). Ask "
        "the user before cleaning a worktree whose state is not yours."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "archive": {
                "type": "boolean",
                "description": (
                    "Keep a verified copy outside .riel/ before wiping it "
                    "(default false: clean removes without a backup)."
                ),
            },
            "worktree": _WORKTREE,
        },
    },
}

RIEL_CHECK = {
    "name": "riel_check",
    "description": (
        "Riel delivery check on ONE file — the dense-register markers an outer deliverable "
        "must not leak, plus the explicit text digest of its mermaid graph. Run it before "
        "handing a packet, a brief or a run to someone else. With mermaid=true it ALSO "
        "parses every mermaid block with mermaid-cli (when installed), so a diagram no "
        "renderer accepts never reaches a reader."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "The file to check, relative to the worktree."},
            "mermaid": {
                "type": "boolean",
                "description": (
                    "Also parse each mermaid block with mmdc (needs mermaid-cli on PATH; "
                    "silently skipped when absent). Use it when the file carries diagrams "
                    "someone else will render."
                ),
            },
            "worktree": _WORKTREE,
        },
        "required": ["file"],
    },
}

RIEL_GUIDE = {
    "name": "riel_guide",
    "description": (
        "Read Riel's prose on demand — the only door to it. Call it with NO topic for "
        "the index (each topic with when to use it), with a topic for one guide, or with "
        "a topic and a section for just that slice. Read the guide that matches the work "
        "in front of you: 'project' before ordering several shapings, 'run' before "
        "authoring or executing a contract, 'shaping' before researching one question's "
        "evidence, 'delegate' before delegating, 'tools' for the tool surface."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "run | shaping | project | delegate | tools. "
                    "Omit for the index."
                ),
            },
            "section": {
                "type": "string",
                "description": (
                    "A '## <heading>' of that guide, matched case-insensitively, "
                    "e.g. 'Claim anchors' — the slice you need, not the whole body."
                ),
            },
            "full": {
                "type": "boolean",
                "description": (
                    "Read the whole guide body instead of its section outline. "
                    "Only when the task needs all of it."
                ),
            },
        },
        "required": [],
    },
}

SCHEMAS = (RIEL_GUIDE, RIEL_PROJECT, RIEL_SHAPE, RIEL_RUN, RIEL_NOTE,
           RIEL_CLEAN, RIEL_CHECK)
