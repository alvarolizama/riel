---
topic: tools
trigger: "Use for Riel's seven-tool surface: guide, project, shape, run, note, clean and check, all operating explicitly on the session worktree."
version: 3.2.0
---
# tools — Seven doors, one worktree

The public interface is typed tools, not command construction. Every operation
runs against explicit session worktree storage; outputs use sinks local to the
call rather than diverting process-wide stdout or stderr.

## Surface

| Tool | Operations |
|---|---|
| `riel_guide` | prose index, topic outline, one section or full body |
| `riel_project` | project `new`, `validate`, `status` (derived from the contracts) |
| `riel_shape` | shaping `new`, `validate` |
| `riel_run` | Contract lifecycle AND synchronized session checks (gates + step subchecks) |
| `riel_note` | execute gate evidence and manage Core/Open State |
| `riel_clean` | remove everything inside `.riel/`; `archive=true` keeps a verified copy |
| `riel_check` | dense-register and graph checks; optional Mermaid parsing |

`run new`, `shape new` and `project new` print their templates; writing and
activation stay distinct. Riel explains the formats and validates them — it
never authors a shaping or a project, and it fetches nothing.

`run list` enumerates every contract in `.riel/runs/`, which is where
`project status` reads a shaping's proof. Those files are never pruned.

## Evidence call

Gate recording names references, not status prose: `gates`, `claims`,
`covering`, optional `command`, and optional `partial`. When a gate declares a
frozen command (`— cmd: ...` or backticks in `#### Gates`), `riel_note`
executes it automatically if `command` is omitted, and REFUSES a different
`command` (edit the Definition and run `run rebase` to change it). Unfrozen
gates still require `command`. The referenced IDs and run revision must match
current metadata. Unknown or stale references fail; exit codes cannot be
supplied by the model as a substitute for execution.

Verification is purely objective: evidence passes iff `exit_code == 0` and not
`partial`. Passing `partial=true` records intermediate evidence (`partial:true`)
without passing the gate or covering claims. `riel_note` prints
`gate_exit_code`, `gate_passed`, `diff_stat` (with a warning if test files were
modified), any `SCOPE VIOLATION`, `STUCK WARNING` after 3+ consecutive failures
on the same gate, the active phase's Focus Card, and on failure up to 3,000
chars of newline-preserved output tail; full large or failing outputs are saved
to `.riel/logs/<E#>.log`.

`core` accepts at most two facts (`—`, `--`, and `–` normalize to ` — `),
replaced by a one-based `core_slot`. `close` and `evidence` take the numbers N
of Q<N> and E<N> respectively.
Removed: `confidence`, `goal`, `next`, `phase`, ad hoc claim creation, `check/by`,
`from_contract` and `verify_with` are not parameters.

## Envelope and scope

Tool calls answer `{tool, worktree, exit_code, passed, stdout, stderr}`, with
`verb` when applicable and operation-specific fields such as keywords. Errors
use the same base envelope. `tool` is provenance, not an argument to type.

`clean` removes EVERY entry inside `.riel/` — contracts, project, shapings,
logs, backups and any other file — and keeps only the lock file and `archive/`.
Archiving is opt-in: `archive=true` copies the tree into
`.riel/archive/<timestamp>/`, verifies every sha256 before removing anything,
and that copy survives the wipe. Without it the removal is not recoverable,
because `.riel/` is gitignored. There is no `scope` parameter.

## Verification

`riel_check(file=…)` must run on the file that will ship, not an earlier copy.
A draft validates structurally; only an activated, revision-bound run can record
Evidence. Edits outside `.riel/` after the last passing evidence set
`dirty_since_evidence: true` and block `done` until re-verified; `allow:` /
`deny:` glob violations populate `scope_violations` and block `done`; `pre_verify`
catches `stale`, `dirty_since_evidence`, `scope_violations`, and pending work.
Read status (including `ready_phases` and `focus`) from `run`, not the todo UI:
the latter is a projection.
