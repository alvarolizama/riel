# Spec 1 — Hermes projections

A session todo and the Riel status document are projections. Neither stores
accepted execution state: `.riel/runs/<slug>.md` does. They may be regenerated freely
from the run and never re-imported as evidence.

## Session checklist

Activating a run materializes the Definition in the calling session's Hermes
checklist. `riel_run` refreshes it after every successful `activate`, `rebase`,
`status` and `riel_note`; `riel_clean` removes only `riel-*` rows.

Rows use `{id, content, status, parent}` and nest as:
`GOAL → PHASE → CHECK (gate) → step subcheck`. A phase without an explicit
gate holds its steps directly. Only passing current-revision Evidence
completes a gate and its steps; a failed command never completes either. Rows
belonging to the user or another tool are preserved.

The write goes to the live TodoStore of the session id on the tool call, never
a process-global store. If that session exposes no store, the envelope reports
`todo_sync: {status: "unavailable", reason: …}`; `.riel/runs/<slug>.md` remains the
source of truth. A checklist checkbox never writes back to the run.

`riel_run(verb="status")` includes the same `todos` array, so a resumed session
can reconcile without a second tool.

## Run status

`riel_run(verb="status")` is the machine state for the gate and desktop chip. It
answers the format and status, contract revision, derived phase and Next, claim and
gate results, Open questions, Evidence and computed `done`. Riel does not derive
activity from timestamp ordering or from checkpoint prose.

Status failures are explicit: a stale shaping or Definition revision is not silently
interpreted as a new Definition. Mutating code under an active run without closing all
its claims and mandatory gates keeps `done` false.

## Packets

`run slice` produces an immutable Definition subgraph plus its relevant claims, gates,
frozen Findings and revision. It has no independently writable State. Children
return candidate command results; the parent reruns commands through
`riel_note` before they enter Evidence.

Display progress therefore travels in one direction: Definition+Evidence to status
and todo, never UI checkbox to Definition, shaping or Evidence.
