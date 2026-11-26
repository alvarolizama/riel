# Spec 1 — Hermes projections

A session todo and the Riel status document are projections. Neither stores
accepted execution state: `.riel/runs/<slug>.md` does. They may be regenerated freely
from the run and never re-imported as evidence.

## Session checklist

Activating a contract materializes its Definition in the calling session's Hermes
checklist. `riel_run` refreshes it after every successful `activate`, `rebase`,
`status`, `list` and `riel_note`; `riel_clean` removes only `riel-*` rows.

Several contracts may be active at once, and the checklist holds ALL of them: the
refresh reads `run list` (one call, every contract's status) and concatenates the
rows of every activated contract. Every id is namespaced by the contract's slug —
`riel-<slug>-goal`, `riel-<slug>-phase-F1`, `riel-<slug>-gate-G1`,
`riel-<slug>-step-F1S1` — and the goal row reads `GOAL [<slug>]: …`, so two tracks
never collide and the reader can tell them apart. A contract that cannot be read is
reported in `todo_sync.unreadable`, never dropped in silence.

Rows use `{id, content, status, parent}` and nest as:
`GOAL → PHASE → CHECK (gate) → step subcheck`. Every phase declares its own
`#### Gates`, so a phase always has at least one check row. Only passing
current-revision Evidence completes a gate and its steps; a failed command never
completes either. Rows belonging to the user or another tool are preserved.

The write goes to the live TodoStore of the session id on the tool call, never
a process-global store. If that session exposes no store, the envelope reports
`todo_sync: {status: "unavailable", reason: …}`; `.riel/runs/<slug>.md` remains the
source of truth. A checklist checkbox never writes back to the run.

`riel_run(verb="status")` includes that contract's own `todos` array (slug-namespaced),
so a resumed session can reconcile without a second tool.

## Run status

`riel_run(verb="status")` is the machine state for the gate and desktop chip. It
answers the format and status, contract revision, derived `current_phase`,
`ready_phases` and `next`, claim and gate results, Open questions, Evidence,
`dirty_since_evidence`, `scope_violations`, `stuck_gates`, the active-phase
`focus` card (`phase`, `deliverable`, `pending_gates` with commands,
`open_claims`, `do_not`, `core`), and computed `done`. Riel does not derive
activity from timestamp ordering or from checkpoint prose.

Status failures are explicit: a stale shaping or Definition revision is not silently
interpreted as a new Definition. Mutating code under an active run without closing all
its claims and mandatory gates — or leaving `dirty_since_evidence` or
`scope_violations` unresolved — keeps `done` false.

## Gate hook and prompt section

`pre_verify` reads the active contracts in the worktree via `run list` and holds
the turn whenever any contract is `stale`, has `dirty_since_evidence`, has
`scope_violations`, or still owes pending gates or open claims. Its nudge prints
the actionable pending gates (with frozen commands when declared), open claims,
and `## DO NOT` boundaries, and emits a `STUCK WARNING` when `stuck_gates` is
populated.

The `riel` prompt section (`section.py`) summarizes each active contract with its
cursor and pending counts and surfaces `## DO NOT`, `## Core`, and stale,
dirty, or scope alerts when present.

`riel_clean` wipes `.riel/logs/` alongside the rest of `.riel/` (keeping only
the lock and `archive/`).

## Packets

`run slice` produces an immutable Definition subgraph plus its relevant claims, gates,
frozen Findings and revision. It has no independently writable State. Children
return candidate command results; the parent reruns commands through
`riel_note` before they enter Evidence.

Display progress therefore travels in one direction: Definition+Evidence to status
and todo, never UI checkbox to Definition, shaping or Evidence.
