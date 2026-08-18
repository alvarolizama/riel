# Spec 5 — Adapters (system-agnostic contract)

Status: draft v1 · Riel phase 2

## Principle

The local format (spec-ledger-format) and the pull/push cycle (spec-pull-push) are **system-agnostic**. Only 4 operations vary by remote. The day Hub or Notion gets connected, one column is added to the table plus a safety note — format and cycle are untouched.

## The contract (4 operations)

| Operation | Input | Output | Guarantee |
|---|---|---|---|
| `pull` | task identifier | title, body with phases, existing Verification | full read of the task before working |
| `push-verify` | ✓NN | ack | append without losing prior content |
| `push-phase` | phase identifier | ack | checkbox marked without corrupting other sections |
| `push-close` | ?NN + status | ack | Pending written; status changed via safe route |

## Cross-cutting rules (any system)

1. Read-before-write on every push.
2. Rebuild the full content before writing.
3. Never split a write across multiple calls.
4. Status only via the system's meta-merge route.
5. One workstream = one worktree = one ledger.

## Dran — first implementation

| Operation | Implementation | Safety notes |
|---|---|---|
| `pull` | `dran_get_page(slug, context)` | Read the full body; never from search excerpts |
| `push-verify` | `dran_update_page(slug, body=full)` | **Replaces the whole body**: rebuild first; pass body ONLY (no meta, or TipTap strips the mermaid) |
| `push-phase` | `dran_update_page(slug, body=full)` | Same — the checkbox is part of the body |
| `push-close` | `dran_update_todo(slug, kanban_status)` | **Status ONLY via update_todo (meta merge)**; the body was already written before |

Dran-specific rules:

- Context: `personal` (default profile).
- `created_by`: whoever executes (`chaos manager` / `alvaro` / `aluxe`).
- Body over the tool-call token limit → local file + REST `PUT /api/pages/:slug?context=personal`; verify integrity by comparing `body_hash` against the sha256 of the sent body.
- REST GET returns metadata without body — integrity verification is by hash, not re-reading.

## Hub and Notion — future mapping (interface only)

| Operation | Hub (hub-tracker) | Notion |
|---|---|---|
| `pull` | get ticket | read page blocks |
| `push-verify` | comment on the ticket | append block |
| `push-phase` | subtask status change | checkbox toggle |
| `push-close` | close ticket | page status |

When implemented: full column + each system's own safety notes.

## Honest limit

Total agnosticism does not exist — each remote has different semantics (body replacement vs fields vs blocks). That is encapsulated in the adapter's safety notes; the rest of the system never notices.
