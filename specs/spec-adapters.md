# Spec 5 — Adapters (system-agnostic contract)

Status: draft v1 · Riel phase 2

## Principle

The local format (spec-ledger-format) and the pull/push cycle (spec-pull-push) are **system-agnostic**. Only 3 operations vary by remote. The day Hub or Notion gets connected, one column is added to the table plus a safety note — format and cycle are untouched.

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

The first adapter targets a private second-brain server. Its operational
detail — concrete tool calls, safety notes, token-limit fallback, hash
verification — lives in a **local, gitignored** note
(`references/<adapter>-notes.md`), not in this public spec. The public
contract stays system-agnostic on purpose.

## Hub and Notion — future mapping (interface only)

| Operation | Hub (hub-tracker) | Notion |
|---|---|---|
| `pull` | get ticket | read page blocks |
| `push-phase` | subtask status change | checkbox toggle |
| `push-close` | close ticket | page status |

When implemented: full column + each system's own safety notes (in the local
notes file, same as the reference implementation).

## Honest limit

Total agnosticism does not exist — each remote has different semantics (body replacement vs fields vs blocks). That is encapsulated in the adapter's safety notes; the rest of the system never notices.
