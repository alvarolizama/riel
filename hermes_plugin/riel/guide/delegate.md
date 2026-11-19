---
topic: delegate
trigger: "Use when splitting a Riel run into subagents: immutable run slices, isolated worktrees, candidate JSON results and parent-side re-verification before Evidence."
version: 2.1.0
---
# delegate — One run, several workers

The parent owns `.riel/runs/<slug>.md` and is its only writer. Children receive `run
slices`: immutable packets carrying the global sections (Objective, Why,
Constraints, Deliverable, DO NOT) plus ONE `### F#: <title>` block copied
verbatim — its steps, its `#### Claims`, its `#### Gates`, its
`#### Deliverable` — and the frozen Basis those claims reference. No other
phase travels. They do not receive mutable State or the whole shaping.

## Dispatch

Only graph-independent work with disjoint files may execute in parallel. Give
each child its own git worktree, an exact file allowlist and one structured
return schema. The parent re-checks the current contract revision before dispatch;
work outside those constraints is escalated instead of reinterpreted.

A slice is generated with `riel_run(verb="slice", phase="W2")` after its
predecessors pass. The child must know the `run_revision`, gate and claim IDs,
command runner and expected output. Inherited slices do not activate new runs.

## Return

A child returns candidate observations such as files changed, command, exit code, `covering`, and which declared claims and gate it addressed. Those claims
are not durable evidence yet. A self-reported `passed: true` is never enough.

The parent integrates the diff and calls `riel_note` with the specific gate,
claims, `command` and `covering`. Riel executes the command in the parent worktree
and writes its actual exit code. The Definition hash and referenced IDs must match.
Only then is Evidence appended and the next DAG work enabled.

## Failure and revision

If the work exceeds scope, changes intent or requires unregistered files, the
child stops with the exact conflict. If a gate fails, return failure and the
relevant log; do not rewrite the claim or the Definition. An unresolved design question
returns to shaping without pretending the existing evidence covers it.

A rebase makes an older run slice stale. Do not merge stale proof into the new
revision. Re-slice and rerun the required gates; old Evidence remains audit
history, not a new result.

## State surfaces

Only the parent calls `riel_note`, `riel_clean`, `activate` or `rebase`. After a
successful mutation it reads run status and refreshes the session checks
through `riel_run`.
Intermediate notes, chat transcripts and child worktrees are not durable
finished state.
