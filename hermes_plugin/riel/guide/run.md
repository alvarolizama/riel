---
topic: run
trigger: "Use when authoring and executing a contract with Riel: one .riel/runs/<slug>.md holds the Contract — its immutable Definition plus the engine-managed State and Evidence."
version: 1.4.0
---
# run — A contract and its evidence

A run is the execution of a **Contract**, and `.riel/runs/<slug>.md` is the file
that holds it — authored there and EXECUTED there, with no live copy and no
archive move. Several contracts may be active at once in one worktree (parallel
tracks); `run=<slug>` selects one, and with a single match it is optional.
The Contract has three parts:

- **Definition** — exactly what will be done. Authored by hand, frozen at
  activation, hashed.
- **State** — what is being done: revision, cursor, Core facts, Open questions.
  Written only by the engine.
- **Evidence** — what was done: one `E#` per gate execution, with the real
  command and its exit code. Append-only, written only by the engine.

They are not peer copies: Objective, Phases and their claims are authored once
in the Definition, and status, phase, Next and done are derived from Evidence.

`.riel/runs/` holds every contract. Any other file in `.riel/` is invisible to
the engine — there is no migration and no automatic merge of old state.

## Lifecycle

1. Assemble evidence first when needed (the shaping guide). When the work is
   several questions, `riel_project(verb="status")` names the next shaping.
2. `riel_run(verb="new", template="run")` returns a draft Definition; write it to
   `.riel/runs/<slug>.md`, fill every field, and declare its ONE shaping under
   `### Shaping` in Context.
3. Validate it, then `riel_run(verb="activate")`. Activation freezes the
   Contract's revision and the bound shaping, then creates empty State.
4. Work the graph. Each `riel_note` gate call executes its command in the
   worktree and appends typed Evidence only after the process returns.
5. Read `riel_run(verb="status")` (pass `run=<slug>` when several contracts are
   active); it returns the same nested checks it keeps synchronized in the
   session checklist after activation and every mutation. Repeat until `done`
   is computed true by the engine.

The contract stays where it was authored. A project derives each shaping's
progress from these files — a done contract is its node's proof, and deleting
one reopens the node. `riel_run(verb="list")` enumerates every contract with its
state, which is what the gate and the desktop chip read.

Activation is explicit. Writing or validating a draft does not activate it.

## Authoring guard

`run validate` and `run activate` REFUSE a Definition that still carries
`{{placeholder}}` text, and name every field left to author. A skeleton is not a
Contract: fill it, or the run does not start. Placeholders inside HTML comments
are documentation and do not count.

## Definition

The Definition carries Run, Objective, Context (`### Why`, `### Context keywords`
and `### Shaping`), Deliverable, Constraints, DO NOT and Phases — the frame first,
the execution last, so the target and the boundary are known before the how.
`Objective` is the result in one sentence; `Deliverable` is the concrete artifacts
(paths, files) a reviewer can point at.
Findings prove design choices in a shaping; Claims prove the implemented
behavior. Neither replaces the other.

`## Phases` holds the general DAG in its preamble (mermaid between phases, an
arrow list `- F1 → F2`, or nothing — then the heading order is the order), then
one `### F#: <title>` per phase. The phase graph models dependencies and
parallelism (parallel phases become ready together when predecessors pass); if
execution changes direction, update the Definition and run `run rebase` — do not
leave dead conditional branches whose unreachable gates prevent `done`. Each phase
carries its own steps and its own `#### Claims`, `#### Gates` and
`#### Deliverable`. Constraints and DO NOT are GLOBAL: one run is one shaping is
one PR, so no phase may relax the boundary. Both `## Constraints` and `## DO NOT`
also support optional enforceable path glob rules (`- allow: path/**` /
`- deny: path/**`, supporting `*`, `?`, `**`) checked against git worktree
changes; violations populate `scope_violations`, block `done`, and trigger
`pre_verify`.

`### Shaping` names the one shaping this run executes — a path under
`.riel/shapings/` or its uid. One run, one shaping, one question, one PR.

Use `P#` for claims, `F#`/`W#` for phases and `G#` for gates. A step bullet
STARTS with its closed verb (`- READ the spec`) — you do not write its id: the
engine numbers steps PER PHASE (`F1S1`, `F1S2`, …) in authored order, so
inserting a step never renumbers another phase's anchors. A claim closes as:

`- P1: what must hold — anchor: shaping:F1`

inside its phase's `#### Claims`. Freeze each gate's command inside its phase's
`#### Gates` via `— cmd: <command>` (or `-- cmd:`) or leading backticks (for
example `- G1: parser tests pass — cmd: make test` or `- G1: \`make test\``);
unfrozen gates emit a validation warning and still require `command` on
`riel_note`. Membership is structural, so there is no `— phase:` suffix. Clause
separators accept ` — `, ` -- `, and ` – ` (normalized to ` — ` on write).
`§F1#2` anchors a claim to step 2 of phase F1.

Anchors can also be `§Section#n` or a graph node. Every `shaping:F#` anchor
must resolve to a real finding in the BOUND shaping before activation; its text
is copied into the run's frozen Basis so packets do not depend on a mutable
external file.

## State and Evidence

Only `riel_note` writes State. It accepts a gate ID, one or more existing claim
IDs, explicit covering scope, optional `command` (auto-running the gate's frozen
command when omitted, and refusing a different command), and optional
`partial=true`. It executes the command in the worktree and records the actual
exit code, current contract revision, git `tree:<12hex>` and `files:<N>` (when
in a git worktree), and the evidence ID. Accepting a `passed: true` sentence
without running evidence is not verification.

Verification is purely objective: evidence passes iff `exit_code == 0` and not
`partial` (there is no `confidence` parameter). Passing `partial=true` records
intermediate `partial:true` evidence without passing the gate or covering
claims. On every gate run, `riel_note` reports `gate_exit_code`, `gate_passed`,
`diff_stat` (warning when test files were modified), any `SCOPE VIOLATION`, the
active phase's Focus Card (`focus phase`, `deliverable`, `pending_gates`,
`open_claims`, `do_not`, `core`), and on failure prints up to 3,000 chars of
newline-preserved output directly. Large or failing outputs are saved to
`.riel/logs/<E#>.log`.

Consecutive failures on the same gate in the current revision are tracked: at 3
or more consecutive failures, `stuck_gates` is populated and `riel_note` /
`pre_verify` emit a `STUCK WARNING` urging reassessment or `ASK` instead of blind
patching. Inside a git worktree, editing tracked or untracked files outside
`.riel/` after the last passing evidence sets `dirty_since_evidence: true`,
which blocks `done` and triggers `pre_verify` until the gate is re-run.

Core holds at most two working facts; its slots are one-based. Open questions
have stable `Q#` identifiers and close against one existing `E#` checkpoint.
Evidence is append-only. Comments and prose cannot create checkpoints.

Phase completion and `ready_phases` follow the DAG edges (a phase completes when
its predecessor phases and its own gates pass), never the number of Evidence rows.
A claim closes only by passing evidence that names it at the current revision.
An open question is not discarded into done by omission.

## Revision and recovery

Editing the Definition or its bound shaping requires explicit `rebase`. A sibling
shaping is another track's evidence and never makes this run stale. That binds a new
revision; older Evidence stays for audit but stops satisfying the new Definition.
Claims whose support changed must be re-run. Never rewrite a failed claim into
what the code happens to do: change the Definition in a new reviewed revision or
refute the claim.

After a gap, read status and the active Contract. Continue from the derived cursor
(`current_phase`, `ready_phases`, and `focus`), not conversation memory. A failed
gate is work remaining, not a finished phase.

## Read exactly enough

Status is the compact machine view — including `ready_phases`,
`dirty_since_evidence`, `scope_violations`, `stuck_gates`, and `focus` (`phase`,
`deliverable`, `pending_gates` with commands, `open_claims`, `do_not`, `core`).
Read the Definition section by section when the next decision needs it. Use
anchors to recover design support. Do not re-read unchanged guides or every
historical Evidence item at every tool boundary; what matters is that the input
to each judgment is real and current.
