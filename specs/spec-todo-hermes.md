# Spec 6 — Hermes session todo (the mirror of the ledger)

Status: draft v1 · Riel phase 2
The Hermes `todo` tool keeps a session-scoped task list: items
`{id, content, status: pending|in_progress|completed|cancelled}`, optional
`parent`, at most one `in_progress` at a time, gone when the session ends.
It is NOT durable state — the ledger is. This spec defines the derivation
from the Riel contract + ledger into that list, so the UI shows what the
ledger knows instead of a second, divergent plan.

## Layering

| Layer | Artifact | Lifetime | Source of truth for |
|---|---|---|---|
| Contract (riel-contract) | phases graph `W/G/S` | repo / PR | the plan |
| Ledger (`.riel/ledger.md`) | Goal/Phase/Claims/✓/?/Next | the task | the state |
| Session todo (Hermes tool) | items mirror | the session | nothing — a projection |
| Remote todo (Spec 2) | durable body | the tracker | the record |

The session todo is a **projection**: regenerate it from the ledger at every
seam, never hand-edit it into a divergent plan. Two todos in one task — the
ledger's and the UI's — and the ledger wins.

## Derivation (`rielctl todo`)

`rielctl todo` reads `.riel/ledger.md` and prints the JSON array for the
todo tool. Mapping:

| Ledger | Item | Status |
|---|---|---|
| Goal | root `goal`, content = goal text | pending — completed only at done-check, by the agent |
| Phase | `phase`, content = phase text | pending |
| Next | `next`, content = next action | `in_progress` — the ONLY one |
| ?NN open | one per question, with its settled-by | pending |
| P# claims | one per claim, with its verify-with | pending |
| ✓NN verified | one per checkpoint, verifier + coverage kept | completed |

Rules:

1. All children carry `"parent": "goal"`.
2. One `in_progress` total: the Next. If the ledger has no Next, the mirror
   is malformed — fix the ledger, not the todo.
3. Outer register: no dense markers (`✓NN`/`?NN`) in contents — `DONE` /
   `OPEN` prefixes instead; verifier and coverage stay in plain words.
4. The todo never introduces work that is not in the ledger. Work missing
   from the ledger goes to the ledger first (`rielctl note`), then the todo
   is regenerated.
5. Hand edits in the UI (status flips) are noise — re-derive instead. The
   ledger is the one that moves; the mirror follows.

## Packet → child todo (delegation)

A dispatch packet's `## Execution graph` IS the child's plan. A child that
receives a packet and runs loop mode opens its own ledger (riel-cli), then
derives its session todo from the graph: `W#/F#` phase nodes → pending
items, `G#` gates → verification criteria, the funnel's VERIFY nodes → the
done criteria. Same rule as above: the child's ledger — not the parent's
chat, not the packet prose — is the source once execution begins.

## Relationship to spec-todo-contract

Spec 2 defines the durable body in the REMOTE tracker (what a todo must
carry to be a ledger). This spec defines the SESSION mirror in the agent UI
(what the local ledger projects into the todo tool). Same hierarchy,
different layer: remote = record, session = display.

## Cross-references

- Remote durable body: `spec-todo-contract.md` (Spec 2)
- Ledger format: `spec-ledger-format.md` (Spec 1)
- Command: `rielctl todo` (skill `riel-cli`)
