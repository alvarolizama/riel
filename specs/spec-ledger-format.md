# Spec 1 — Local ledger format (`.riel/ledger.md`)

Status: draft v1 · Riel phase 2
Applies to every task in `loop` mode (multi-file, multi-tool, multi-phase, or spanning sessions).

## File location and lifecycle

- `.riel/ledger.md` in the task worktree; goes into `.gitignore`.
- **One workstream = one worktree = one ledger** (isolates parallel sessions; same lesson as git index races).
- It is ephemeral: after the final push it may be deleted — the durable state already lives in the remote.

### Git hygiene (the ledger is local state, never a deliverable)

- Each worktree has its own `.gitignore`; ensure `.riel/` is listed there
  **before** committing anything — never assume another repo's ignore file
  covers it.
- Prefer explicit adds (`git add <file>`) or `git add -p`; never `git add -A`
  unchecked when a `.riel/` directory exists.
- Before every commit, `git status` must show no `.riel/` entries. Fix the
  ignore file first, never after the commit.

## Exact format

```markdown
# Riel ledger

## Goal
<one sentence: what "done" means — from the remote todo's title/objective>

## Source
<remote system + identifier — e.g. dran:todo-slug>

## Phase
<active phase derived from the DAG — e.g. "F2: CREATE router_test.exs">

## Core
- <name> — <defining fact>
- <name> — <defining fact>

## Verified
- ✓01 <what holds> — verified by: <what established it>, covering <scope>

## Open
- ?01 <question> — settled by: <the cheapest test that would refute it>

## Next
<the single next action — never empty>
```

## Per-field rules

| Field | Rule |
|---|---|
| Goal | One sentence; updated only if the goal changes |
| Source | Optional; present only when the task came from a remote todo |
| Phase | Derived from the DAG (spec-phase-advance); pointer to the active mini-ledger |
| Core | Max 2 live items; change only via explicit swap; each with its defining fact |
| Verified | Numbered ✓NN, append-only; never deleted or renumbered |
| Open | Numbered ?NN; closed against a checkpoint; the number is never reused |
| Next | Never empty; if blocked, the block IS the Next ("waiting on X from Álvaro") |

## Valid ✓NN

`✓NN <what holds> — verified by: <verifier>, covering <scope>`

- **Verifier:** what established it (command, test, review).
- **Coverage:** what it covered (files, cases, platforms, ranges).
- Without coverage it is not a checkpoint — it is a mood.

## Valid ?NN

`?NN <question> — settled by: <the cheapest test that would refute it>`

- Without a settled-by it is not opened (it could never be closed).

## Stall detection

- Same `Next` for 3 seams → document why, or change course.
- Goal misaligned with what is being executed → return to the Goal before acting.

## The mechanism is the re-read

The file is not the mechanism; the mechanism is **re-reading it at every seam** (phase change, tool call, file change, long gap). With no script that is 4 steps and 15 seconds.
