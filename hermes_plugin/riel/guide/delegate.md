---
topic: delegate
trigger: "Use when splitting a Riel run into subagents: immutable run slices, isolated worktrees, candidate JSON results and parent-side re-verification before Evidence."
version: 2.3.0
---
# delegate — One run, several workers

The parent owns `.riel/runs/<slug>.md` and is its only writer. Children receive `run
slices`: immutable packets carrying the global sections (Objective, Context with
Why, Deliverable, Constraints, DO NOT) plus ONE `### F#: <title>` block copied
verbatim — its steps, its `#### Claims`, its `#### Gates`, its
`#### Deliverable` — and the frozen Basis those claims reference. No other
phase travels. They do not receive mutable State or the whole shaping.

## Dispatch

Only graph-independent work with disjoint files may execute in parallel. Give
each child its own git worktree, an exact file allowlist and one structured
return schema. The parent re-checks the current contract revision before dispatch;
work outside those constraints is escalated instead of reinterpreted.

Every path a brief hands a child is absolute, and inside a worktree NOTHING may
live outside `.riel/`: a relative `backup-runs/<slug>.bak.md` resolves against the
child's cwd — the worktree root — and drops an untracked directory there. Session
artifacts go under `.riel/` (`.riel/backups/<slug>.bak.md`) or to an absolute
scratch path outside any worktree, never beside `.riel/` and never at its root.
After every child require `git status --porcelain` to show only the allowlisted
files: an unexpected `?? <dir>/` is a failed wave, not noise.

A slice is generated with `riel_run(verb="slice", phase="F2", run="<slug>")` after
its DAG predecessors pass (`ready_phases` lists all phases whose predecessors are
complete, so parallel branches become ready together); `run` is required when
several contracts are active. The child must know the `run_revision`, gate and
claim IDs, command runner (including any frozen gate command and `allow`/`deny`
glob rules in `Constraints`/`DO NOT`) and expected output. Inherited slices do
not activate new runs.

## Return

A child returns candidate observations such as files changed, command, exit code, `covering`, and which declared claims and gate it addressed. Those claims
are not durable evidence yet. A self-reported `passed: true` is never enough.

The parent integrates the diff and calls `riel_note` with the specific gate,
claims, `covering`, and `command` (omitted when the gate declares a frozen
command). Riel executes the command in the parent worktree and writes its actual
exit code, `diff_stat` (warning if test files were modified), and any
`SCOPE VIOLATION`. The Definition hash and referenced IDs must match; `partial=true`
never satisfies a gate or claim, and any edit after passing evidence sets
`dirty_since_evidence` until re-verified. Only then is Evidence appended and the
next DAG work enabled.

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
