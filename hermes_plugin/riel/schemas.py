"""Tool schemas — what the LLM reads to decide when to call these tools.

Machinery only: every task tool delegates to the bundled engine, which is the
sole writer of `.riel/ledger.md`. Descriptions state when to use the tool, not
how the ledger is formatted — the format, the rules and the recipes live in the
package's prose, which `riel_guide` serves.
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

_NOTE_PARAMS = _load.sibling("riel_engine_params", "engine/params.py")

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

    This schema, the handler's flag map and the engine's argparse used to be
    three hand-maintained copies of the same fifteen parameters. One declaration
    now feeds all three, so a parameter cannot exist in the catalog and be
    ignored by the engine.
    """
    props = {}
    for param in _NOTE_PARAMS.NOTE_PARAMS:
        props[param["name"]] = {
            "type": "integer" if param["kind"] == "int" else "string",
            "description": param["help"],
        }
    props[_NOTE_PARAMS.FROM_CONTRACT["name"]] = {
        "type": "string",
        "description": _NOTE_PARAMS.FROM_CONTRACT["help"],
    }
    props["worktree"] = _WORKTREE
    return props


RIEL_NOTE = {
    "name": "riel_note",
    "description": (
        "Write or update the Riel ledger (.riel/ledger.md) in a worktree: goal, next "
        "action, core facts, claims with their verifying command, verified checkpoints "
        "with real gate output, open questions and closures. Use it on loop-mode tasks and "
        "on every delegated task, instead of hand-editing the ledger — the engine owns the "
        "format. Pass at least one content flag; with no flags it just re-prints the ledger."
    ),
    "parameters": {
        "type": "object",
        "properties": _note_properties(),
    },
}

RIEL_SEAM = {
    "name": "riel_seam",
    "description": (
        "Re-read the Riel ledger at a seam: prints the goal, claims, verified checkpoints, "
        "open questions, next action and the invariants due now. Use it before continuing "
        "work after a gap, before a decision, or when unsure of the current state — it is the "
        "cheap way to reload verified state instead of guessing from memory. `mode='resume'` "
        "adds the post-gap restore order, for a session that continues earlier work and has "
        "no memory of it; `mode='json'` answers the ledger's own items, for deciding "
        "mechanically by counts and ids. Pass anchors=true to also re-read every claim beside "
        "the region that supports it (the contract section, the graph node or the shaping "
        "finding its anchor names) — that pair is the seam: state plus the support under it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": (
                    "read (default) | resume | json. resume adds the post-gap restore "
                    "order; json returns the ledger items the chip and the gate fold."
                ),
            },
            "anchors": {
                "type": "boolean",
                "description": "Also re-read each claim beside the region its anchor names.",
            },
            "worktree": _WORKTREE,
        },
    },
}

RIEL_TODO = {
    "name": "riel_todo",
    "description": (
        "Derive the Riel session-todo mirror from the PLAN: the contract's Objective is the "
        "root item, its phases are rows and each phase's steps are nested subtasks. The ledger "
        "only sets the statuses (the step the Next points at is the only in_progress). The "
        "ledger's own facts — next, claims, open questions, verified checkpoints — are NOT "
        "rows here. THEN INJECT IT: pass the returned items array to the todo_list tool "
        "(todo_list with todos=<the array>) so the session's todo UI shows the plan — "
        "generating the mirror without injecting it shows nothing. The todo is a projection: "
        "when the ledger or the contract moves, call this again and re-inject; never "
        "hand-edit the list into a divergent plan."
    ),
    "parameters": {"type": "object", "properties": {"worktree": _WORKTREE}},
}

RIEL_CONTEXT = {
    "name": "riel_context",
    "description": (
        "Riel contract's context index, for the memory search YOU run — `### Context keywords` "
        "as a list of terms with an optional source hint. Call it when opening a Riel task and "
        "when advancing to a new phase, then do the searching YOURSELF with the memory tools you "
        "have configured (DRAN, your own memory, search_files) and keep the answers in the "
        "ledger's `## Core` (max 2 live items). This tool does not search: a plugin cannot reach "
        "the memory backends, so it gives you the terms and nothing else."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Terms to return instead of reading them from the contract. Omit in the "
                    "normal case: the contract carries the index, and both parent and child "
                    "read the same one."
                ),
            },
            "worktree": _WORKTREE,
        },
    },
}

RIEL_CONTRACT = {
    "name": "riel_contract",
    "description": (
        "Riel plan artifacts — instantiate, validate, digest or slice a contract or a "
        "delegated packet. `verb='new'` renders the shipped template for `template` (feature, "
        "bugfix, refactor, research, writing, packet, shaping) with `params` as [\"key=value\"] "
        "placeholders and RETURNS the text — write it to .riel/contract.md yourself. "
        "`verb='validate'` runs the structural rules (closed verb vocabulary, funnel, ids, "
        "claim anchors) over `file` and exits 1 on an ISSUE. `verb='digest'` expands the "
        "graph of `file` into explicit text (the agent reads the digest, not the diagram). "
        "`verb='slice'` extracts one phase of `file` as a child packet — pass `phase`."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verb": {"type": "string", "description": "One of: new, validate, digest, slice."},
            "template": {"type": "string", "description": "For verb='new': the template name."},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=new: placeholder values as ["key=value", …].',
            },
            "file": {"type": "string", "description": "For validate/digest/slice: the contract or packet path."},
            "phase": {"type": "string", "description": "For verb='slice': the phase id (e.g. F2)."},
            "worktree": _WORKTREE,
        },
        "required": ["verb"],
    },
}

RIEL_SHAPING = {
    "name": "riel_shaping",
    "description": (
        "Riel shaping — the research that precedes the contract: instantiate the skeleton "
        "(`verb='new'`, with `params`) and check it against Spec 7 (`verb='validate'`, with "
        "`file`, default .riel/shaping.md). A shaped task writes findings with their sources "
        "and a confidence, the alternatives that lost, and a verdict that opens the contract; "
        "validate exits 1 on an ISSUE and warns on a finding without a source."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "verb": {"type": "string", "description": "One of: new, validate."},
            "params": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'For verb=new: placeholder values as ["key=value", …].',
            },
            "file": {"type": "string", "description": "For verb=validate: the shaping path."},
            "force": {
                "type": "boolean",
                "description": "For verb=new: overwrite an existing .riel/shaping.md (a shaping is research).",
            },
            "worktree": _WORKTREE,
        },
        "required": ["verb"],
    },
}

RIEL_CLEAN = {
    "name": "riel_clean",
    "description": (
        "Riel housekeeping — archive the worktree's .riel/ state so a new task starts clean. "
        "`scope='ledger'` backs up and removes the ledger; `'all'` also the contract and the "
        "shaping; `'purge'` deletes without a backup. The backups are flat, timestamped files "
        "inside .riel/ — never a subdirectory. Ask the user before cleaning a worktree whose "
        "state is not yours."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "description": "One of: ledger, all, purge (default ledger)."},
            "worktree": _WORKTREE,
        },
    },
}

RIEL_FETCH = {
    "name": "riel_fetch",
    "description": (
        "Riel remote contract — materialize a contract that lives on a server into the "
        "worktree (default .riel/contract.md), without routing the body through the model's "
        "context. HTTPS only (plain http needs allow_http on a trusted transport), the body is "
        "bounded, the write is atomic, and the URL is never printed — a short-lived token in "
        "the query string must not leak. Pass sha256 to pin integrity end to end."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The export URL (single-use, short-lived token)."},
            "out": {"type": "string", "description": "Destination path (default .riel/contract.md)."},
            "sha256": {"type": "string", "description": "Expected sha256 of the body, if the server gave one."},
            "headers": {
                "type": "array",
                "items": {"type": "string"},
                "description": 'Extra headers as ["Name: value", …], when the export needs them.',
            },
            "allow_http": {"type": "boolean", "description": "Allow plain http (localhost or a trusted VPN)."},
            "worktree": _WORKTREE,
        },
        "required": ["url"],
    },
}

RIEL_CHECK = {
    "name": "riel_check",
    "description": (
        "Riel delivery check on ONE file — the dense-register markers an outer deliverable "
        "must not leak, plus the explicit text digest of its mermaid graph. Run it before "
        "handing a packet, a brief or a contract to someone else: a doc that fails `ship` has "
        "internal shorthand in it, and the digest is what the receiving agent should read "
        "instead of re-deriving the graph from the diagram. With mermaid=true it ALSO parses "
        "every mermaid block with mermaid-cli (when installed), so a diagram that no renderer "
        "accepts never reaches a reader."
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
        "in front of you: 'contract' before authoring a plan, 'ledger' before running a "
        "loop task, 'shaping' before researching the evidence, 'delegate' before delegating, "
        "'protocol' when opening a conversation, 'tools' for the tool surface."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "protocol | ledger | contract | shaping | delegate | tools. "
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
                    "Only when the task needs all of it — 5–23 KB."
                ),
            },
        },
        "required": [],
    },
}

SCHEMAS = (RIEL_NOTE, RIEL_SEAM, RIEL_TODO, RIEL_CONTEXT, RIEL_CONTRACT,
           RIEL_SHAPING, RIEL_CLEAN, RIEL_FETCH, RIEL_CHECK, RIEL_GUIDE)
