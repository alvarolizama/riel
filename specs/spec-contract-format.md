# Spec 2 — Local contract format (`.riel/contract.md`)

Status: draft v2 · Riel — local-first
Applies to every task that plans before executing (fast/full/loop and
delegate).
The **contract** is the plan; the **ledger** is the state. This spec defines
the plan artifact and its relationship to the ledger.

## Role and location

- `.riel/contract.md` in the task worktree; goes in `.gitignore` (local
  state, never a deliverable — same git hygiene as the ledger).
- **One workstream = one worktree = one contract.**
- **Written first, always** — before opening the ledger, before any
  execution, whether the task delegates or not.
- Overwritten per session: it is working memory for the task in flight, not
  a durable record.

## The format is the packet format

`contract.md` reuses the packet's section set — canonical skeleton in
`riel-briefs/templates/packet.md`; graph conventions in `riel-contract`.
**Do not duplicate the structure here.**

The nine sections, in order:

1. `# Task:` — the name
2. `## Objective` — one sentence, opens with "We need…"
3. `## Context` — project, code to read/modify, reference snippets
4. `## Constraints` — hard rules
5. `## Pre-registered claims` — P-ids with a verify-with
6. `## Execution graph` — the mermaid DAG (riel-contract)
7. `## Verification gates` — command / expected / on failure, per phase
8. `## Deliverable`
9. `## DO NOT`

Validate it mechanically: `rielctl brief validate .riel/contract.md` (the
validator keys on this exact section set and order).

## Contract vs ledger

| Layer | Artifact | Source of truth for | Lifetime |
|---|---|---|---|
| Contract | `.riel/contract.md` | the plan (phases, claims, gates) | the task |
| Ledger | `.riel/ledger.md` | the state (✓NN evidence, Next) | the task |

- Each phase of the contract's graph = one mini-ledger
  (spec-phase-advance). Only the active phase's ledger is live.
- The ✓NN evidence lives in the ledger, **never in the contract**.
- The contract is written once and re-read as the plan; the ledger is
  re-read at every seam.

## Delegation: the packet is a slice of the contract

When the task delegates, the child receives a **packet**: the contract
narrowed to the child's phase — its subgraph, its gates, its Deliverable,
its DO NOT. Same format, fewer phases. The child **never opens a ledger**:
it returns JSON and the **parent** — the sole writer of `.riel/ledger.md` —
turns that into ✓NN. The parent keeps the full contract and the ledger.

## Cross-references

- Ledger format: `spec-ledger-format.md` (Spec 1)
- Per-phase ledger: `spec-phase-advance.md` (Spec 4)
- Session-todo mirror: `spec-todo-hermes.md` (Spec 6)
- Packet skeleton + templates: skill `riel-briefs`
- Graph conventions: skill `riel-contract`
