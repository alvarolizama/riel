"""Tool schemas — what the LLM reads to decide when to call these tools.

Machinery only: every tool delegates to the vendored `rielctl`, which is the
sole writer of `.riel/ledger.md`. Descriptions state when to use the tool, not
how the ledger is formatted (that belongs to the `riel-ledger` skill).
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
        "Write or update the Riel ledger (.riel/ledger.md) in a worktree: the goal, "
        "the next action, core facts, claims (each with the command that would verify it), "
        "verified checkpoints with their real gate output, open questions, and closures. "
        "Use this on loop-mode tasks and on every delegated task, instead of hand-editing "
        "the ledger — rielctl owns the format. Pass at least one of the content flags; "
        "running it with no flags just re-prints the ledger."
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
        "cheap way to reload verified state instead of guessing from memory."
    ),
    "parameters": {"type": "object", "properties": {"worktree": _WORKTREE}},
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
        "Derive the session-todo mirror from the Riel ledger: Goal is the root item, Next is the "
        "only in_progress, open questions and pending claims are pending, verified checkpoints are "
        "completed. THEN INJECT IT: pass the returned items array to the todo_list tool "
        "(todo_list with todos=<the array>) so the session's todo UI mirrors the ledger — "
        "generating the mirror without injecting it shows nothing. The todo is a projection: "
        "when the ledger moves, call this again and re-inject; never hand-edit the list into a "
        "divergent plan."
    ),
    "parameters": {"type": "object", "properties": {"worktree": _WORKTREE}},
}

RIEL_CONTEXT = {
    "name": "riel_context",
    "description": (
        "Hand you the contract's context index — `### Context keywords` (or explicit keywords) "
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

SCHEMAS = (RIEL_NOTE, RIEL_SEAM, RIEL_RESUME, RIEL_TODO, RIEL_CONTEXT)
