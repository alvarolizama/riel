# Spec 1 — Local ledger format (`.riel/ledger.md`)

Status: draft v1 · Riel phase 2
Applies to every task in `loop` mode (multi-file, multi-tool, multi-phase, or spanning sessions).

## File location and lifecycle

- `.riel/ledger.md` in the task worktree; goes into `.gitignore`.
- **One workstream = one worktree = one ledger** (isolates parallel sessions; same lesson as git index races).
- It is ephemeral: after the done-check it may be deleted — the plan lives in `.riel/contract.md`; the ledger is disposable state.

### Git hygiene (the ledger is local state, never a deliverable)

- Each worktree has its own `.gitignore`; ensure `.riel/` is listed there
  **before** committing anything — never assume another repo's ignore file
  covers it.
- Prefer explicit adds (`git add <file>`) or `git add -p`; never `git add -A`
  unchecked when a `.riel/` directory exists.
- Before every commit, `git status` must show no `.riel/` entries. Fix the
  ignore file first, never after the commit.

## Exact format

The order below matches `rielctl` exactly — `note` writes Goal, then the
optional Source/Phase, then Claims, Core, Verified, Open, Next. Use
`rielctl note` as the writer; do not hand-format the file into a different
order.

```markdown
# Riel ledger

## Goal
<one sentence: what "done" means — from the contract's objective>

## Source
<where the task came from — e.g. todo:<slug>>

## Phase
<active phase derived from the DAG — e.g. "F2: CREATE router_test.exs">

## Claims
- P1: <what will be true when done> — verify with: <how>

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
| Source | Optional; present when the task came from a tracked item |
| Phase | Derived from the DAG (spec-phase-advance); pointer to the active mini-ledger |
| Claims | Pre-registered before the first action; P-ids; never edited after execution begins — a failed claim is refuted, not reinterpreted |
| Core | Max 2 live items; change only via explicit swap; each with its defining fact |
| Verified | Numbered ✓NN, append-only; never deleted or renumbered |
| Open | Numbered ?NN; closed against a checkpoint; the number is never reused |
| Next | Never empty; if blocked, the block IS the Next ("waiting on X from the user") |

## Valid ✓NN

`✓NN <what holds> — verified by: <verifier>, covering <scope>[, confidence X/20]`

- **Verifier:** what established it (command, test, review).
- **Coverage:** what it covered (files, cases, platforms, ranges).
- **Confidence (optional, critical checkpoints only):** a 1–20 score of how
  strongly the verification holds. Fine granularity (vs. a binary pass/fail)
  separates solid from borderline results — coarse discrete scoring produces a
  26.7% tie rate on Terminal-Bench V2 (a continuous verifier: zero ties),
  which hides uncertainty (LLM-as-a-Verifier).
- Without coverage it is not a checkpoint — it is a mood. With
  `confidence < 12/20` it is a **borderline** — not a checkpoint: `Next`
  becomes "strengthen the verification of ✓NN", not "advance".

## Valid ?NN

`?NN <question> — settled by: <the cheapest test that would refute it>`

- Without a settled-by it is not opened (it could never be closed).

## Stall detection

- Same `Next` for 3 seams → document why, or change course.
- Goal misaligned with what is being executed → return to the Goal before acting.

## The mechanism is the re-read

The file is not the mechanism; the mechanism is **re-reading it at every seam** (phase change, tool call, file change, long gap). With no script that is 4 steps and 15 seconds.
