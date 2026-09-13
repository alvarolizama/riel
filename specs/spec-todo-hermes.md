# Spec 6 — Hermes session todo (the mirror of the contract + ledger)

Status: draft v2 · Riel phase 2
The Hermes `todo` tool keeps a session-scoped task list: items
`{id, content, status: pending|in_progress|completed|cancelled}`, optional
`parent` (nested subtasks), at most one `in_progress` at a time, gone when
the session ends. It is NOT durable state — the ledger is. This spec defines
the derivation from the Riel contract + ledger into that list.

v2: the todo now shows the WHOLE plan, not just the state — phases come from
the contract's DAG (what will be done), steps of each phase come as nested
subtasks (how), and the ledger decides the statuses (what is being done now).
Division of labor: **todo = what must be done · ledger = what is being done ·
contract = everything that will be done, and how.**

## Layering

| Layer | Artifact | Lifetime | Source of truth for |
|---|---|---|---|
| Contract (Spec 2) | `.riel/contract.md` (phases + claims + gates) | the task | the plan |
| Ledger (`.riel/ledger.md`) | Goal/Phase/Claims/✓/?/Next | the task | the state |
| Session todo (Hermes tool) | items mirror | the session | nothing — a projection |

The session todo is a **projection**: regenerate it from the contract + ledger
at every seam, never hand-edit it into a divergent plan. The todo may SHOW
future work (from the contract) but may never INVENT it — every phase and
step item must trace to a contract node.

## Derivation (`rielctl todo`)

`rielctl todo` reads `.riel/ledger.md` AND `.riel/contract.md` (when present)
and prints the JSON array for the todo tool. Mapping:

| Source | Item | Status |
|---|---|---|
| Ledger Goal | root `goal`, content = goal text | pending — completed only at done-check, by the agent |
| Contract DAG | one item per phase node (`F#`/`W#`), in graph order | derived (below) |
| Contract DAG | one nested item per step node of each phase (`parent` = the phase) | derived (below) |
| Ledger Next | `next`, content = next action | `in_progress` — the ONLY one |
| ?NN open | one per question, with its settled-by | pending |
| P# claims | one per claim, with its verify-with | pending |
| ✓NN verified | one per checkpoint, verifier + coverage kept | completed |

### Phase and step statuses (from the ledger's position)

- **Phase whose gate has a ✓** → `completed`.
- **The active phase** (ledger `Phase`, or the phase owning the Next) →
  `pending` — its steps carry the progress. The phase item itself is never
  `in_progress`: the Next owns that, so the single-in_progress rule holds.
- **Future phases** (no ✓, not active) → `pending`.
- **Steps of a phase**: steps are contract nodes, not ledger state — a step
  is `completed` when its phase's gate ✓ exists (the gate covers the phase),
  otherwise `pending`. No step is ever `in_progress` (the Next item is).

Without a contract (or a graph-less task), the todo degrades to the v1
mirror: goal + phase + next + opens + claims + verified.

## Rules

1. `goal` is the root; phases and every ledger-derived item are its children;
   steps are children of their phase (two levels total).
2. One `in_progress` total: the Next. If the ledger has no Next, the mirror
   is malformed — fix the ledger, not the todo.
3. Outer register: no dense markers (`✓NN`/`?NN`) in contents — `DONE` /
   `OPEN` prefixes instead; verifier and coverage stay in plain words.
4. The todo shows only contract-declared work. A step or phase that is not
   in the contract does not enter the todo — it goes to the contract first
   (or the ledger, if it is state), then the todo is regenerated.
5. Hand edits in the UI (status flips) are noise — re-derive instead. The
   ledger is the one that moves; the mirror follows.
6. Gate/decision nodes (`G#`, funnel) are not steps — they are the phase's
   verification, already represented by the phase item and its ✓.

## Packet → child (delegation)

A dispatch packet's `## Execution graph` IS the child's plan. The child
**never opens a ledger** — the ledger has a single writer: the parent.
The child works the graph and returns **JSON** (`output_schema`) carrying
everything the parent needs to update the ledger: per gate `command`,
`exit_code`, `passed`, `coverage`; per claim `verified` + `evidence`. The
parent turns those into the ledger's ✓NN (verifier + coverage) and derives
the session todo. Nothing a child reports is durable until the parent
writes it into `.riel/ledger.md`.

## Relationship to spec-contract-format

Spec 2 defines the local contract (`.riel/contract.md`, the plan). This spec
defines the SESSION mirror in the agent UI (what the contract + local ledger
project into the todo tool). Same hierarchy, different layer: contract =
plan, ledger = state, session todo = display.

## Cross-references

- Local contract (the plan): `spec-contract-format.md` (Spec 2)
