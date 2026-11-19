---
topic: tools
trigger: "Use for Riel's seven-tool surface: guide, project, shape, run, note, clean and check, all operating explicitly on the session worktree."
version: 3.0.0
---
# tools — Seven doors, one worktree

The public interface is typed tools, not command construction. Every operation
runs against explicit session worktree storage; outputs use sinks local to the
call rather than diverting process-wide stdout or stderr.

## Surface

| Tool | Operations |
|---|---|
| `riel_guide` | prose index, topic outline, one section or full body |
| `riel_project` | project `new`, `validate`, `status` (derived from the runs) |
| `riel_shape` | shaping `new`, `validate` |
| `riel_run` | Contract lifecycle AND synchronized session checks (gates + step subchecks) |
| `riel_note` | execute gate evidence and manage Core/Open State |
| `riel_clean` | remove everything inside `.riel/`; `archive=true` keeps a verified copy |
| `riel_check` | dense-register and graph checks; optional Mermaid parsing |

`run new`, `shape new` and `project new` print their templates; writing and
activation stay distinct. Riel explains the formats and validates them — it
never authors a shaping or a project, and it fetches nothing.

`run archive` moves the finished run to `.riel/runs/<slug>.md`, which is where
`project status` reads a shaping's proof. Those files are never pruned.

## Evidence call

Gate recording names references, not status prose: `gates`, `claims`, `command`,
`covering` and optional `confidence`. The referenced IDs and run revision must
match current metadata. Unknown or stale references fail; exit codes cannot be
supplied by the model as a substitute for execution.

`core` accepts at most two facts, replaced by a one-based `core_slot`. `close` and
`evidence` take the numbers N of Q<N> and E<N> respectively.
Removed: `goal`, `next`, `phase`, ad hoc claim creation, `check/by`,
`from_contract` and `verify_with` are not parameters.

## Envelope and scope

Tool calls answer `{tool, worktree, exit_code, passed, stdout, stderr}`, with
`verb` when applicable and operation-specific fields such as keywords. Errors
use the same base envelope. `tool` is provenance, not an argument to type.

`clean` removes EVERY entry inside `.riel/` — run, project, shapings, archived
runs, backups and any other file — and keeps only the lock file. Archiving is
opt-in: `archive=true` copies the tree outside `.riel/`
(`~/.hermes/riel/archive/<worktree>/<timestamp>/`) and verifies every sha256
before removing anything. Without it the removal is not recoverable, because
`.riel/` is gitignored. There is no `scope` parameter.

## Verification

`riel_check(file=…)` must run on the file that will ship, not an earlier copy.
A draft validates structurally; only an activated, revision-bound run can record
Evidence. Read status from `run`, not the todo UI: the latter is a projection.
