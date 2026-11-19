---
topic: run
trigger: "Use when authoring and executing a contract with Riel: one .riel/run.md holds the Contract — its immutable Definition plus the engine-managed State and Evidence."
version: 1.2.0
---
# run — A contract and its evidence

A run is the execution of a **Contract**, and `.riel/run.md` is the file that
holds it. The Contract has three parts:

- **Definition** — exactly what will be done. Authored by hand, frozen at
  activation, hashed.
- **State** — what is being done: revision, cursor, Core facts, Open questions.
  Written only by the engine.
- **Evidence** — what was done: one `E#` per gate execution, with the real
  command and its exit code. Append-only, written only by the engine.

They are not peer copies: Objective, Phases and their claims are authored once
in the Definition, and status, phase, Next and done are derived from Evidence.

`.riel/run.md` is the only state file. Any other file in `.riel/` is invisible
to the engine — there is no migration and no automatic merge of old state.

## Lifecycle

1. Assemble evidence first when needed (the shaping guide). When the work is
   several questions, `riel_project(verb="status")` names the next shaping.
2. `riel_run(verb="new", template="run")` returns a draft Definition; write it to
   `.riel/run.md`, fill every field, and declare its ONE shaping under
   `### Shaping` in Context.
3. Validate it, then `riel_run(verb="activate")`. Activation freezes the
   Contract's revision and the bound shaping, then creates empty State.
4. Work the graph. Each `riel_note` gate call executes its command in the
   worktree and appends typed Evidence only after the process returns.
5. Read `riel_run(verb="status")`; it returns the same nested checks it keeps
   synchronized in the session checklist after activation and every mutation.
   meaningful changes. Repeat until `done` is computed true by the engine.

When the run is done, `riel_run(verb="archive")` moves it to
`.riel/runs/<slug>.md` so the next shaping can activate. A project derives its
progress from those archived runs.

Activation is explicit. Writing or validating a draft does not activate it.

## Authoring guard

`run validate` and `run activate` REFUSE a Definition that still carries
`{{placeholder}}` text, and name every field left to author. A skeleton is not a
Contract: fill it, or the run does not start. Placeholders inside HTML comments
are documentation and do not count.

## Definition

The Definition carries Run, Objective, Context (`### Why`, `### Context keywords`
and `### Shaping`), Constraints, Phases, Deliverable and DO NOT.
Findings prove design choices in a shaping; Claims prove the implemented
behavior. Neither replaces the other.

`## Phases` holds the general DAG in its preamble (mermaid between phases, an
arrow list `- F1 → F2`, or nothing — then the heading order is the order), then
one `### F#: <title>` per phase. Each phase carries its own steps and its own
`#### Claims`, `#### Gates` and `#### Deliverable`. Constraints and DO NOT are
GLOBAL: one run is one shaping is one PR, so no phase may relax the boundary.

`### Shaping` names the one shaping this run executes — a path under
`.riel/shapings/` or its uid. One run, one shaping, one question, one PR.

Use `P#` for claims, `F#`/`W#` for phases and `G#` for gates. Steps are numbered
PER PHASE (`F1S1`, `F1S2`, …) so inserting a step never renumbers another
phase's anchors. A claim closes as:

`- P1: what must hold — anchor: shaping:F1`

inside its phase's `#### Claims`. The gate command lives in the same phase's
`#### Gates` (`G1`); membership is structural, so there is no `— phase:` suffix.
`§F1#2` anchors a claim to step 2 of phase F1.

Anchors can also be `§Section#n` or a graph node. Every `shaping:F#` anchor
must resolve to a real finding in the BOUND shaping before activation; its text
is copied into the run's frozen Basis so packets do not depend on a mutable
external file.

## State and Evidence

Only `riel_note` writes State. It accepts a gate ID, one or more existing claim
IDs, a command and explicit covering scope. It executes that command and records the
actual exit code, current contract revision and the evidence ID. Accepting a
`passed: true` sentence without running evidence is not verification.

Core holds at most two working facts; its slots are one-based. Open questions
have stable `Q#` identifiers and close against one existing `E#` checkpoint.
Evidence is append-only. Comments and prose cannot create checkpoints.

Phase completion comes from its own gate, not the number of Evidence rows.
A claim closes only by evidence that names it and its current contract revision.
An open question is not discarded into done by omission.

## Revision and recovery

Editing the Definition or its bound shaping requires explicit `rebase`. A sibling
shaping is another track's evidence and never makes this run stale. That binds a new
revision; older Evidence stays for audit but stops satisfying the new Definition.
Claims whose support changed must be re-run. Never rewrite a failed claim into
what the code happens to do: change the Definition in a new reviewed revision or
refute the claim.

After a gap, read status and the active Contract. Continue from the derived cursor,
not conversation memory. A failed gate is work remaining, not a finished phase.

## Read exactly enough

Status is the compact machine view. Read the Definition section by section when the
next decision needs it. Use anchors to recover design support. Do not re-read
unchanged guides or every historical Evidence item at every tool boundary;
what matters is that the input to each judgment is real and current.
