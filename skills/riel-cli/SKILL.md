---
name: riel-cli
description: "Use when Riel needs its mechanical helper — writes the ledger with the exact format, instantiates and validates packets, expands a graph digest, derives the session-todo mirror. The agent invokes it in RUN nodes instead of handwriting state files."
version: 1.6.0
author: Álvaro Lizama
license: MIT
metadata:
  hermes:
    tags: [riel, cli, ledger, briefs, tooling]
    related_skills: [riel-ledger, riel-briefs, riel-contract, riel-delegate]
---

# riel-cli — Mechanical helper for Riel (Riel)

`rielctl` is a stdlib-only Python script that performs the mechanical parts
of the framework so the agent doesn't have to remember them:

- Writing `.riel/ledger.md` with the exact expected format
- Instantiating packet templates (`rielctl brief new`)
- Verifying that a packet satisfies the structural constraints
  (`rielctl brief validate`) — including the closed verb vocabulary
- Expanding the execution graph into explicit text (`rielctl brief digest`)
- Deriving the Hermes session-todo mirror from the ledger (`rielctl todo`)
- Emitting a contract's context keywords as JSON (`rielctl context`) so the
  memory search has one authoritative index to read instead of re-parsing
  the contract

**When to use:** on any `loop`-mode task and on every delegated task, the
agent invokes `rielctl` in `RUN` nodes instead of handwriting ledger files.
`fast` and most `full` tasks don't need it — use only the machinery the
task earns.

## Location

`rielctl` is normally on PATH — the repo's `make install` symlinks it
into `~/.local/bin`:

```bash
rielctl note --goal "..." --next "..."
```

If `command -v rielctl` comes up empty, invoke the skill copy directly
(it has a shebang):

```bash
python3 <skill-root>/scripts/rielctl note --goal "..." --next "..."
```

and restore the symlink with `make install` from the riel repo
checkout.

## Commands

All state-mutating commands write to `.riel/` in the *current working
directory*. Invoke from the task's worktree root.

### Ledger

```bash
rielctl note --goal "what done means" --next "first action"
rielctl note --next "next action"
rielctl note --core "Mailer — sends via Swoosh" [--core-slot 1]
rielctl note --claim "token expires at 1h" --verify-with "mix test token_test.exs"
rielctl note --check "token signs" --by "mix test token_test.exs" \
             --covering "sign+verify+expiry" [--confidence 14]
rielctl note --open "does the link survive quote chars?" \
             --settled-by "property test on URI.encode_www_form"
rielctl note --close 1 --check "it survives" --by "test" --covering "encoding"
```

`--close` requires `--check`/`--by`: a question is closed against the
checkpoint that settled it, never dropped silently.

Numbering (✓NN, ?NN) is assigned by `rielctl` — never hand-edited.

### Inspections

```bash
rielctl seam     # re-print the ledger + which invariants are due
rielctl resume   # full post-gap bootstrap (ledger → invariants → mode → next)
rielctl ship FILE.md   # check FILE for dense-register leakage before delivery
rielctl digest FILE.md # explicit text digest of any file's mermaid graph
```

### Context keywords (Spec 2)

```bash
rielctl context [--contract PATH] [-o OUT]
```

Prints `{"contract": …, "keywords": [{"term": …, "source": …}]}` — the index the
memory search reads (one term per line under `### Context keywords`; `→ dran`
is an optional source hint). Empty list when the contract has none; exit 1 only
when the contract is missing.

### Session todo (Hermes mirror, Spec 6)

```bash
rielctl todo    # JSON array for the todo tool, derived from the ledger
```

Reads the ledger AND the contract (when present) and prints the
session-todo items. Spec 6 v2 — the todo shows the whole plan:
Goal → root item; **each contract phase → a row (`PHASE F1: …`) and each
phase's steps → nested subtasks** (`parent` = the phase — the todo tool's
own nesting); Next → the only `in_progress`; ?NN → `OPEN NN` pending;
P# → `CLAIM:` pending; ✓NN → `DONE NN` completed. A phase is completed when
its gate's ✓ exists; the phase owning the Next stays pending (the Next owns
in_progress). Without a contract it degrades to the v1 mirror (single PHASE
row). The todo is a projection — fix the ledger (or the contract) and
regenerate the mirror; never hand-edit the todo into a divergent plan. Spec:
`riel/specs/spec-todo-hermes.md`.

**Injecting it (Hermes):** the mirror is complete only when the array reaches
the session todo UI — pass it to the `todo_list` tool as
`todo_list(todos=<array>)` right after generating it (with the plugin:
`riel_todo` → `todo_list`). Regenerate + re-inject at every seam where the
ledger moved; the store is session-scoped, so a new session re-injects from
the current ledger.

Exit codes:

- `note` / `seam` / `resume` / `todo`: 0 unless arguments invalid or the
  ledger is missing (1).
- `ship`: exit 0 if the file is clean; exit 1 if it finds dense markers
  (the agent should fix before delivery).

### Contracts & packets

```bash
# the contract (the plan) — from a typed skeleton
rielctl brief new --type feature --param name="reset flow" \
                  --param one_sentence="add password reset via email" \
                  > .riel/contract.md
rielctl brief validate .riel/contract.md
rielctl brief digest   .riel/contract.md   # explicit text expansion of the graph

# a child's packet — one phase sliced from the contract
rielctl brief slice .riel/contract.md --phase F2
```

`brief new` searches templates in order:

1. `~/.hermes/skills/riel-briefs/templates/<type>.md`
2. `<task-worktree>/.riel/templates/<type>.md`
3. `skills/riel-briefs/templates/<type>.md` (built into this repo)

Double-curly placeholders `{{param}}` are replaced with `--param` values;
unknown params abort non-zero so typos never silently produce broken
packets. Fill in the remaining content by hand with `patch` afterwards —
the template is the skeleton, not the final packet.

`brief validate` checks the structure, the Objective/claims/DO-NOT, and the
execution graph against `riel-contract` — predictable ids, a RUN + VERIFY
funnel, labeled decision edges, **every execution node starting with a
closed verb** (READ/EDIT/CREATE/RUN/VERIFY/ASK), **an `ASK` node naming its
trigger** (`ASK[irreversible|outside-claims|goal-changing]`), no `<br/>`, no
`style` in the DAG, no tool names in labels — plus an mmdc parse when
mermaid-cli is present. Loops without a counter guard (`< 3` / `>= 3`) and
over-long labels are reported as non-fatal `WARN`s.

`brief digest FILE [-o OUT]` prints the explicit **graph digest** — elements,
authored edges, branches, entry/terminals and loops, with a "meaning &
limits" footer. Use it to give an agent the text beside the diagram (the
diagram stays for humans).

## The one rule

`rielctl` decides nothing and verifies nothing semantically.
It is a clerk: it keeps the format perfect so the agent can spend its
reasoning on the actual work. Every semantic decision — what the Goal is,
whether the gate actually passed, whether the claim is satisfied — remains
the agent's.
