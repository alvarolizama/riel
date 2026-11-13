---
topic: tools
trigger: "Use for Riel's six-tool surface: guide, shape, run, note, clean and check, all operating explicitly on the session worktree."
version: 2.0.0
---
# tools — Six doors, one worktree

The public interface is typed tools, not command construction. Every operation
runs against explicit session worktree storage; outputs use sinks local to the
call rather than diverting process-wide stdout or stderr.

## Surface

| Tool | Operations |
|---|---|
| `riel_guide` | prose index, topic outline, one section or full body |
| `riel_shape` | shaping `new`, `validate`, `fetch` |
| `riel_run` | Plan lifecycle AND synchronized session checks (gates + step subchecks) |
| `riel_note` | execute gate evidence and manage Core/Open State |
| `riel_clean` | archived removal of `run`, `all`, or explicit `purge` |
| `riel_check` | dense-register and graph checks; optional Mermaid parsing |

`run new` prints the draft; writing and activation stay distinct. `shape new`
also prints the research template. Both `fetch` operations require sha256
and materialize a file only; no fetch mutates an active run.

## Evidence call

Gate recording names references, not status prose: `gates`, `claims`, `command`,
`covering` and optional `confidence`. The referenced IDs and run revision must
match current metadata. Unknown or stale references fail; exit codes cannot be
supplied by the model as a substitute for execution.

`core` accepts at most two facts, replaced by a one-based `core_slot`. `close` and
`evidence` take the numbers N of Q<N> and E<N> respectively.
Legacy `goal`, `next`, `phase`, ad hoc claim creation, `check/by`,
`from_contract` and `verify_with` are not parameters.

## Envelope and scope

Tool calls answer `{tool, worktree, exit_code, passed, stdout, stderr}`, with
`verb` when applicable and operation-specific fields such as keywords. Errors
use the same base envelope. `tool` is provenance, not an argument to type.

`clean` removes only the named new artifacts. `purge` is explicitly destructive;
archived scopes back up the state first. Old `contract.md` and `ledger.md` are
never implicitly selected or deleted as run state.

## Verification

`riel_check(file=…)` must run on the file that will ship, not an earlier copy.
A draft validates structurally; only an activated, revision-bound run can record
Evidence. Read status from `run`, not the todo UI: the latter is a projection.
