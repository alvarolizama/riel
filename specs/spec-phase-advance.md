# Spec 4 — Per-phase ledger and advancement (riel-ledger + riel-contract fusion)

Status: draft v1 · Riel phase 2

## The graph defines the ledgers

The `## Phases` mermaid (riel-contract) defines:

- **How many mini-ledgers exist** — one per phase.
- **Their order and dependencies** — the DAG edges.
- **Each phase's gate** — the VERIFY node before advancing.

**N phases = N sequential mini-ledgers.** Only one is live at a time: the active phase's (the `Phase` pointer). Previous ones are already in the remote (✓NN); future ones do not exist yet.

## The Phase pointer

- Derived from the DAG checkboxes: first phase without a checkbox = active.
- Never set by hand; re-derived at every pull and after every gate.

## The gate — fusion point

The gate is TWO things at once:

| Face | Component | Meaning |
|---|---|---|
| Contract | riel-contract | "The phase's VERIFY node passed" |
| Ledger | riel-ledger | "Append this phase's ✓NN to the LOCAL ledger" |

Gate content (verifiers + coverage):

- compile without warnings
- scope tests green
- format with no extra diffs
- diff ⊆ phase scope
- **coverage statement:** what was verified and what it covered (without this there is no ✓NN)

## Phase advancement

1. Gate passes → PUSH (spec-pull-push).
2. `Phase` ← next phase enabled by the DAG.
3. `Core` ← swap to the new phase's items (max 2 live).
4. `Next` ← first action of the new phase.
5. `Open` items belonging to future phases migrate with their numbers.

## Parallelism

- **Disjoint** phases (different files, no DAG edge) may run in parallel: each with its own worktree + its own local ledger.
- Phases touching the same file → serialize.
- The parent coordinates pushes to the remote (same lesson as git index races).
- **Git hygiene:** each parallel ledger lives in its own worktree and is never committed — see spec-ledger-format.
