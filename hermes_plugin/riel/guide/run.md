---
topic: run
trigger: "Use when planning and executing a task with Riel: one .riel/run.md owns the immutable Plan and the engine-managed State, Evidence and completion."
version: 1.0.0
---
# run — A checked plan and its evidence

A run is the only operational artifact: `.riel/run.md`. Its **Plan** says what
must happen; its **State** says what the engine has established. They are not
peer copies: Objective, Claims and graph are authored once in the Plan and
status, phase, Next and done are derived from Evidence.

Old `contract.md` and `ledger.md` are unsupported. There is no migration and
no automatic merge of old state.

## Lifecycle

1. Assemble evidence first when needed (the shaping guide).
2. `riel_run(verb="new", template="run")` returns a draft Plan; write it to
   `.riel/run.md` and fill every field.
3. Validate it, then `riel_run(verb="activate")`. Activation freezes the
   Plan revision and the referenced shaping, then creates empty State.
4. Work the graph. Each `riel_note` gate call executes its command in the
   worktree and appends typed Evidence only after the process returns.
5. Read `riel_run(verb="status")`; it returns the same nested checks it keeps
   synchronized in the session checklist after activation and every mutation.
   meaningful changes. Repeat until `done` is computed true by the engine.

Activation is explicit. Fetching, writing or validating a draft does not
activate it.

## Plan

The Plan carries Run, Objective, Context (`### Why` and `### Context
keywords`), Constraints, Claims, Graph, Gates, Deliverable and DO NOT. Findings prove design choices in shaping;
Claims prove the implemented behavior. Neither replaces the other.

Use `P#` for claims, `F#`/`W#` for phases, `S#` for steps and `G#` for gate
decisions. A claim closes as:

`- P1: what must hold — anchor: shaping:F1`

The gate command lives in Gates (`G1`); the claim says what must hold.

Anchors can also be `§Section#n` or a graph node. Every `shaping:F#` anchor
must resolve to a real finding before activation; its text is copied into the
run's frozen Basis so packets do not depend on a mutable external file.

## State and Evidence

Only `riel_note` writes State. It accepts a gate ID, one or more existing claim
IDs, a command and explicit covering scope. It executes that command and records the
actual exit code, current plan revision and the evidence ID. Accepting a
`passed: true` sentence without running evidence is not verification.

Core holds at most two working facts; its slots are one-based. Open questions
have stable `Q#` identifiers and close against one existing `E#` checkpoint.
Evidence is append-only. Comments and prose cannot create checkpoints.

Phase completion comes from its own gate, not the number of Evidence rows.
A claim closes only by evidence that names it and its current plan revision.
An open question is not discarded into done by omission.

## Revision and recovery

Editing the Plan or its shaping requires explicit `rebase`. That binds a new
revision; older Evidence stays for audit but stops satisfying the new Plan.
Claims whose support changed must be re-run. Never rewrite a failed claim into
what the code happens to do: change the Plan in a new reviewed revision or
refute the claim.

After a gap, read status and the active Plan. Continue from the derived cursor,
not conversation memory. A failed gate is work remaining, not a finished phase.

## Read exactly enough

Status is the compact machine view. Read the Plan section by section when the
next decision needs it. Use anchors to recover design support. Do not re-read
unchanged guides or every historical Evidence item at every tool boundary;
what matters is that the input to each judgment is real and current.
