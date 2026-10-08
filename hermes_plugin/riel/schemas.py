"""Tool schemas — what the LLM reads to decide when to call these tools.

Machinery only: every tool delegates to the bundled `rielctl`, which is the
sole writer of `.riel/ledger.md`. Descriptions state when to use the tool, not
how the ledger is formatted — the format, the rules and the recipes live in the
package's prose, which `riel_guide` serves.
"""

_WORKTREE = {
    "type": "string",
    "description": (
        "Absolute path to the worktree whose .riel/ state to use. "
        "Omit to use the current session's working directory (the normal case); "
        "pass it only to address another checkout explicitly."
    ),
}

RIEL_NOTE = {
    "name": "riel_note",
    "description": (
        "Write or update the Riel ledger (.riel/ledger.md) in a worktree: goal, next "
        "action, core facts, claims with their verifying command, verified checkpoints "
        "with real gate output, open questions and closures. Use it on loop-mode tasks and "
        "on every delegated task, instead of hand-editing the ledger — rielctl owns the "
        "format. Pass at least one content flag; with no flags it just re-prints the ledger."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What 'done' means for this task (## Goal)."},
            "next": {"type": "string", "description": "The single next concrete action (## Next)."},
            "source": {"type": "string", "description": "Where the task came from (## Source)."},
            "phase": {"type": "string", "description": "Current phase pointer, e.g. F2 (## Phase)."},
            "core": {
                "type": "string",
                "description": "A load-bearing fact the receiver of this work must know, as 'name — fact'.",
            },
            "core_slot": {
                "type": "integer",
                "description": "Which Core slot to write (1-based); omit to append.",
            },
            "claim": {
                "type": "string",
                "description": "A claim about the code ('what must be true'), used with verify_with.",
            },
            "verify_with": {
                "type": "string",
                "description": "The command that would verify the claim, e.g. 'mix test token_test.exs'.",
            },
            "check": {
                "type": "string",
                "description": "A verified checkpoint ('what I checked'), used with by.",
            },
            "by": {
                "type": "string",
                "description": "The real command/gate that produced the evidence for --check (never a guess).",
            },
            "covering": {
                "type": "string",
                "description": "What scope the checkpoint covers, e.g. 'sign+verify+expiry'.",
            },
            "confidence": {
                "type": "integer",
                "description": "Confidence in the checkpoint, if the project tracks it.",
            },
            "open": {
                "type": "string",
                "description": "An open question, used with settled_by.",
            },
            "settled_by": {
                "type": "string",
                "description": "The test/check that would settle the open question.",
            },
            "close": {
                "type": "integer",
                "description": "Number of an open question to close (requires check and by).",
            },
            "from_contract": {
                "type": "string",
                "description": (
                    "Seed Goal/Phase/Claims/Next from a contract: 'true' uses .riel/contract.md, "
                    "or pass an explicit path. Omit to write entries by hand."
                ),
            },
            "worktree": _WORKTREE,
        },
    },
}

RIEL_SEAM = {
    "name": "riel_seam",
    "description": (
        "Re-read the Riel ledger at a seam: prints the goal, claims, verified checkpoints, "
        "open questions, next action and which invariants are due. Use it before continuing "
        "work after a gap, before a decision, or when unsure of the current state — it is the "
        "cheap way to reload verified state instead of guessing from memory. Pass anchors=true "
        "to also re-read every claim beside the region that supports it (the contract section, "
        "the graph node or the shaping finding its anchor names) — that pair is the seam: state "
        "plus the support under it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "anchors": {
                "type": "boolean",
                "description": "Also re-read each claim beside the region its anchor names.",
            },
            "worktree": _WORKTREE,
        },
    },
}

RIEL_RESUME = {
    "name": "riel_resume",
    "description": (
        "Full post-gap bootstrap for a Riel task: ledger → invariants → mode → next action. "
        "Use at the start of a session that continues earlier work, when the ledger exists "
        "in the worktree but this conversation has no memory of it."
    ),
    "parameters": {"type": "object", "properties": {"worktree": _WORKTREE}},
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

RIEL_STATE = {
    "name": "riel_state",
    "description": (
        "Riel ledger state as JSON — the machine-readable mirror the desktop chip and the "
        "pre_verify gate fold. One item per claim, verified checkpoint and open question, with "
        "the evidence each carries. Use it to decide mechanically — counts and ids — where "
        "riel_seam is the prose re-read."
    ),
    "parameters": {"type": "object", "properties": {"worktree": _WORKTREE}},
}

RIEL_BRIEF = {
    "name": "riel_brief",
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
        "instead of re-deriving the graph from the diagram."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "The file to check, relative to the worktree."},
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
        "loop task, 'briefs' before dispatching a packet, 'delegate' before delegating, "
        "'protocol' when opening a conversation, 'tools' for the tool surface."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "protocol | ledger | contract | briefs | delegate | tools. "
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
        },
        "required": [],
    },
}

SCHEMAS = (RIEL_NOTE, RIEL_SEAM, RIEL_RESUME, RIEL_TODO, RIEL_CONTEXT,
           RIEL_STATE, RIEL_BRIEF, RIEL_SHAPING, RIEL_CLEAN, RIEL_FETCH, RIEL_CHECK,
           RIEL_GUIDE)
