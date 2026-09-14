# Spec 6 — Hermes session todo (the plan) + the ledger mirror (`status`)

Status: draft v3 · Riel phase 2
The Hermes `todo` tool keeps a session-scoped task list: items
`{id, content, status: pending|in_progress|completed|cancelled}`, optional
`parent` (nested subtasks), at most one `in_progress` at a time, gone when
the session ends. It is NOT durable state — the ledger is. This spec defines
the derivation from the Riel contract + ledger into that list.

The todo shows the PLAN: the contract's goal (its `## Objective`) is the
root, its phases are rows and each phase's steps are nested subtasks. The
ledger only decides the statuses. The ledger's own facts — Next, claims, open
questions, verified checkpoints — are NOT rows in the todo; `rielctl status`
serves them to the desktop chip and the `pre_verify` gate. Division of labor:
**todo = the plan (what must be done) · ledger = the state (what is being
done) · chip/gate = the ledger's facts.**

## Layering

| Layer | Artifact | Lifetime | Source of truth for |
|---|---|---|---|
| Contract (Spec 2) | `.riel/contract.md` (phases + steps + claims + gates) | the task | the plan |
| Ledger (`.riel/ledger.md`) | Goal/Phase/Claims/✓/?/Next | the task | the state |
| Session todo (Hermes tool) | items mirror of the PLAN | the session | nothing — a projection |
| Ledger mirror (`rielctl status`) | items of the LEDGER | the session | nothing — a projection |

The session todo is a **projection**: regenerate it from the contract + ledger
at every seam, never hand-edit it into a divergent plan. The todo may SHOW
future work (from the contract) but may never INVENT it — every phase and
step item must trace to a contract node.

## Derivation (`rielctl todo`)

`rielctl todo` reads `.riel/ledger.md` AND `.riel/contract.md` (when present)
and prints the JSON array for the todo tool. The todo is the plan alone:

| Source | Item | Status |
|---|---|---|
| Contract `## Objective` | root `goal`, content = the Objective | pending — `in_progress` only when every phase is already gated (the done-check); completed at done-check, by the agent |
| Contract DAG | one item per phase node (`F#`/`W#`), in authored order | derived (below) |
| Contract DAG | one nested item per step node of each phase (`parent` = the phase) | derived (below) |

No ledger fact becomes a row here. Without a contract the todo degrades to
`goal` (the ledger's Goal) + the ledger's single `PHASE:` row.

### Phase and step statuses (from the ledger's position)

- **Phase whose gate has a ✓** → `completed`.
- **The active phase** (the ledger `Phase`, or the phase owning the Next) →
  `pending` — its steps carry the progress. The phase item itself is never
  `in_progress` (unless it has no steps at all; see below).
- **Future phases** (no ✓, not active) → `pending`.
- **Steps of a completed phase** → `completed` (the gate covers the phase).
- **Steps of the active phase**: the step the Next points at is
  `in_progress`; the steps authored before it are `completed`; the rest
  `pending`. If the Next matches no step label, the active phase's first step
  is `in_progress` (best-effort, so the single-in_progress rule holds).
- **A phase with no steps** that is active carries `in_progress` on its own
  row — there is no step to hold it.

## The ledger mirror (`rielctl status`)

`rielctl status` prints the ledger's own facts as items — the same shape the
todo uses, so the chip and the gate keep one fold:

| Source | Item | Status |
|---|---|---|
| Ledger Goal | `goal` | pending |
| Ledger Phase | `phase` | pending |
| Ledger Next | `next` | `in_progress` |
| ?NN open | `open-N`, with its settled-by | pending |
| P# claims | `claim-N`, with its verify-with | pending |
| ✓NN verified | `done-N`, verifier + coverage kept | completed |

Consumers: the desktop chip (`hermes_plugin/riel/dashboard/ledger_status.py`)
folds it into its counters and popover; the `pre_verify` gate
(`hermes_plugin/riel/hooks.py`) reads the `claim-`/`done-` items to enforce
the checkpoint rule. Both shell out to `rielctl status`, never to `rielctl
todo` — the ledger format keeps exactly one owner (`rielctl`).

## Rules

1. `goal` is the root; phases are its children; steps are children of their
   phase (two levels total).
2. One `in_progress` total: the step the Next points at (the active phase's
   current step); the ledger's `phase` row when there is no contract; the
   `goal` row when every phase is already gated (the plan is done, only the
   done-check remains). If none of these applies, the mirror is malformed —
   fix the ledger, not the todo.
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
project into the todo tool) and the ledger mirror the chip and the gate fold
(`rielctl status`). Same hierarchy, different layer: contract = plan,
ledger = state, session todo = display.

## Cross-references

- Local contract (the plan): `spec-contract-format.md` (Spec 2)
- Ledger format: `spec-ledger-format.md` (Spec 1)
- Per-phase ledger: `spec-phase-advance.md` (Spec 4)