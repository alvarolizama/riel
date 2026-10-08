# Spec 1 — Local ledger format (`.riel/ledger.md`)

Status: draft v1 · Riel phase 2
Applies to every task in `loop` mode (multi-file, multi-tool, multi-phase, or spanning sessions).

## File location and lifecycle

- `.riel/ledger.md` in the task worktree; goes into `.gitignore`.
- **One workstream = one worktree = one ledger** (isolates parallel sessions; same lesson as git index races).
- It is ephemeral: after the done-check it is cleared with `rielctl clean` — the plan lives in `.riel/contract.md`; the ledger is disposable state. `clean` backs up as a flat timestamped file INSIDE `.riel/` (`ledger-<ts>.bak.md`, never a subdirectory); `--all` also clears the contract, `--purge` clears without backup.

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
| Phase | Derived from the DAG (Phase advance, below); pointer to the active mini-ledger |
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

## Phase advance (multi-phase tasks)

The contract's graph (`spec-contract-format`) defines how many mini-ledgers
exist: **one per phase**, in DAG order, each closing with its VERIFY gate.
**N phases = N sequential mini-ledgers**, only one live at a time — the
`Phase` pointer above. Previous phases are already ✓NN here; future ones do
not exist yet.

The pointer is never set by hand.

### The gate is the fusion point

| Face | Component | Meaning |
|---|---|---|
| Contract | riel:contract | "The phase's VERIFY node passed" |
| Ledger | riel:ledger | "Append this phase's ✓NN to the LOCAL ledger" |

Gate content (verifiers + coverage):

- compile without warnings
- scope tests green
- format with no extra diffs
- diff ⊆ phase scope
- **coverage statement:** what was verified and what it covered (without this there is no ✓NN)

### Advancing

1. Gate passes → append this phase's ✓NN.
2. `Phase` ← next phase enabled by the DAG.
3. `Core` ← swap to the new phase's items (searched from the contract's
   `### Context keywords` — spec-contract-format, "Context fetch").
4. `Next` ← first action of the new phase.
5. `Open` items belonging to future phases migrate with their numbers.

### Parallelism

- **Disjoint** phases (different files, no DAG edge) may run in parallel: each
  with its own worktree + its own local ledger (Git hygiene, above).
- Phases touching the same file → serialize.
- The parent coordinates the merges (same lesson as git index races).

## Stall detection

- Same `Next` for 3 seams → document why, or change course.
- Goal misaligned with what is being executed → return to the Goal before acting.

## The mechanism is the re-read

The file is not the mechanism; the mechanism is **re-reading it at every seam** (phase change, tool call, file change, long gap). With no script that is 4 steps and 15 seconds.
