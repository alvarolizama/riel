# Spec 5 — Adapters (system-agnostic contract)

Status: draft v1 · Riel phase 2

## Principle

The local format (spec-ledger-format) and the pull/push cycle (spec-pull-push) are **system-agnostic**. Only 3 operations vary by remote.

## The contract (3 operations)

| Operation | Input | Output | Guarantee |
|---|---|---|---|
| `pull` | task identifier | title, body with phases, existing checkboxes | full read of the task before working |
| `push-phase` | phase identifier | ack | checkbox marked without corrupting other sections |
| `push-close` | status | ack | status changed via safe route |

## Cross-cutting rules (any system)

1. Read-before-write on every push.
2. Rebuild the full content before writing.
3. Never split a write across multiple calls.
4. Status only via the system's meta-merge route.
5. One workstream = one worktree = one ledger.
6. The ledger file is local state: git hygiene from spec-ledger-format applies in every worktree.

## Reference implementation

A concrete adapter's operational detail — tool calls, safety notes,
token-limit fallback, hash verification — lives in a **local, gitignored**
note (`references/<adapter>-adapter-notes.md`), never in the public spec.
The day a new remote gets connected, one adapter-notes file is added locally
— contract and cycle untouched.

## Honest limit

Total agnosticism does not exist — each remote has different semantics (body replacement vs fields vs blocks). That is encapsulated in the adapter's safety notes; the rest of the system never notices.
