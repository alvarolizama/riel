"""Tool schemas — what the LLM reads to decide when to call these tools.

Machinery only: every task tool delegates to the bundled engine, which is the
sole writer of `.riel/run.md` and `.riel/shaping.md`. Descriptions state when
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
        "Write to the Riel run state (.riel/run.md) and run its gates. For a gate, "
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

RIEL_SHAPE = {
    "name": "riel_shape",
    "description": (
        "Riel shaping — the evidence before the plan (Spec 7). verb=new RENDERS "
        ".riel/shaping.md's template to stdout (the editor is the writing path — "
        "params as [\"key=value\", …] fill the placeholders), validate checks the "
        "structural rules over file, and fetch materializes a remote shaping into "
        "the worktree (HTTPS, atomic, sha256-pinned: the hash is mandatory)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verb": {"type": "string",
                     "description": "One of: new, validate, fetch."},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=new: placeholder values as ["key=value", …].',
            },
            "file": {"type": "string",
                     "description": "For validate: the shaping path (default the canonical .riel/shaping.md)."},
            "url": {"type": "string",
                    "description": "For verb=fetch: the source URL (single-use, short-lived token)."},
            "out": {"type": "string",
                    "description": "For verb=fetch: destination path (default .riel/shaping.md)."},
            "sha256": {"type": "string",
                       "description": "For verb=fetch: the expected sha256 of the body — mandatory, never optional."},
            "headers": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=fetch: extra headers as ["Name: value", …].',
            },
            "allow_http": {"type": "boolean",
                           "description": "For verb=fetch: allow plain http (localhost or a trusted VPN)."},
            "timeout": {"type": "integer", "description": "For verb=fetch: seconds before the fetch gives up."},
            "max_bytes": {"type": "integer", "description": "For verb=fetch: maximum body size accepted."},
            "worktree": _WORKTREE,
        },
        "required": ["verb"],
    },
}

RIEL_RUN = {
    "name": "riel_run",
    "description": (
        "Riel run — ONE door for the machine-checkable plan (.riel/run.md). verb=new "
        "PRINTS the draft template (you write .riel/run.md yourself — this tool never "
        "writes it), validate enforces the strict riel-run/v1 format (hashing plan + "
        "shaping), activate arms the run so the gate enforces it, rebase re-points the "
        "execution state, status returns the state as ONE JSON object, slice extracts "
        "one phase (pass phase) as a child packet, fetch materializes a remote run "
        "(HTTPS, atomic, sha256-pinned, never activates)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verb": {"type": "string",
                     "description": "One of: new, validate, activate, rebase, status, slice, fetch."},
            "template": {"type": "string",
                         "description": "For verb=new: the template name (default run)."},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=new: placeholder values as ["key=value", …].',
            },
            "file": {"type": "string",
                     "description": "For validate: the run path (default .riel/run.md)."},
            "phase": {"type": "string", "description": "For verb=slice: the phase id to extract."},
            "out": {"type": "string",
                    "description": "For verb=slice: packet destination; for verb=fetch: destination path (default .riel/run.md)."},
            "url": {"type": "string",
                    "description": "For verb=fetch: the source URL (single-use, short-lived token)."},
            "sha256": {"type": "string",
                       "description": "For verb=fetch: the expected sha256 of the body — mandatory, never optional."},
            "headers": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=fetch: extra headers as ["Name: value", …].',
            },
            "allow_http": {"type": "boolean",
                           "description": "For verb=fetch: allow plain http (localhost or a trusted VPN)."},
            "timeout": {"type": "integer", "description": "For verb=fetch: seconds before the fetch gives up."},
            "max_bytes": {"type": "integer", "description": "For verb=fetch: maximum body size accepted."},
            "worktree": _WORKTREE,
        },
        "required": ["verb"],
    },
}

RIEL_CLEAN = {
    "name": "riel_clean",
    "description": (
        "Riel housekeeping — archive the worktree's .riel/ state so a new task starts "
        "clean. scope='run' (default) backs up and removes the run; 'all' also the "
        "shaping; 'purge' deletes without a backup. The backups are flat, timestamped "
        "files INSIDE .riel/. Ask the user before cleaning a worktree whose state is "
        "not yours."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "description": "One of: run, all, purge (default run)."},
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
        "in front of you: 'run' before authoring or executing a plan, 'shaping' before "
        "researching the evidence, 'delegate' before delegating, 'tools' for the tool "
        "surface."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "run | shaping | delegate | tools. "
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

SCHEMAS = (RIEL_GUIDE, RIEL_SHAPE, RIEL_RUN, RIEL_NOTE, RIEL_CLEAN, RIEL_CHECK)
