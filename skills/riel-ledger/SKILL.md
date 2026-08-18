---
name: riel-ledger
description: "Use when running a loop-mode task — write the local Goal/Core/Verified/Open/Next ledger in the worktree, re-read at every seam, verify before done. No remote dependency."
version: 1.1.0
author: Álvaro Lizama
license: MIT
metadata:
  hermes:
    tags: [riel, ledger, agent-state, verification, worktree]
    related_skills: [riel-protocol, riel-contract, riel-briefs]
---

# riel-ledger — Local verified state for long tasks (Riel)

The ledger is **externalized working memory** for tasks long enough to lose
state. It does not solve anything — it lets the agent **restore the same
task state** after every seam: a tool call, a file change, a context
compaction, an hours-long gap.

**Local-first:** this skill operates entirely inside the task worktree.
It does NOT depend on Dran, Hub, Notion, or any remote. Remote sync
(pulling the task in, pushing verification back) is an optional adapter
layer — see "Optional remote sync" at the end. The full contracts live in
`riel/specs/` (repo `Repos/alvarolizama/riel`).

## When to use

| Mode | Ledger? |
|---|---|
| **fast** — 1 step, checkable at a glance | ❌ nothing |
| **full** — bounded multi-step, clear deliverable | ⚠️ only the done-check |
| **loop** — multi-file, multi-tool, multi-phase, or spanning sessions | ✅ full protocol |

Symptoms that you need a ledger even if you did not plan one: several seams
without knowing the next step; about to re-verify something already
verified; hours passed and you cannot remember where you left off.

## The file: `.riel/ledger.md` in the worktree

- Lives at the worktree root; goes in `.gitignore`.
- **One workstream = one worktree = one ledger** — parallel sessions never
  share a ledger (same lesson as git index races).
- Ephemeral: after the final writeback it may be deleted.

```markdown
# Riel ledger

## Goal
<one sentence: what "done" means>

## Source
<optional: remote system + identifier — e.g. dran:todo-slug>

## Phase
<active phase if the task has phases — e.g. "F2: CREATE router_test.exs">

## Core
- <name> — <defining fact>
- <name> — <defining fact>

## Verified
- ✓01 <what holds> — verified by: <what established it>, covering <scope>

## Open
- ?01 <question> — settled by: <the cheapest test that would refute it>

## Next
<the single next action — never empty>
```

## Field rules

| Field | Rule |
|---|---|
| Goal | One sentence; updated only if the goal changes |
| Source | Optional; present when the task came from a remote todo |
| Phase | Derived from the phases graph (riel-contract); pointer to the active mini-ledger |
| Core | Max 2 live items; change only via explicit swap; each with its defining fact |
| Verified | Numbered ✓NN, append-only; never deleted or renumbered |
| Open | Numbered ?NN; closed against a checkpoint; the number is never reused |
| Next | Never empty; if blocked, the block IS the Next ("waiting on X from Álvaro") |

A ✓NN without coverage is not a checkpoint — **it is a mood**. Every entry
names the verifier AND what it covered.

## The protocol

```mermaid
flowchart TD
  START([loop-mode task]) --> OPEN["Open the ledger:\nGoal + Source + Core + Next\n(.riel/ledger.md)"]
  OPEN --> W[Work]
  W --> S{"seam: phase change,\ntool call, file,\nlong gap"}
  S --> R["Re-read the ledger\n(the whole mechanism)"]
  R --> ST{"stalled? same Next\nfor 3 seams?"}
  ST -->|yes| F["Diagnose: document why,\nor change course"]
  F --> W
  ST -->|no| DEG{"degraded? cascading\nerrors, corrupted output"}
  DEG -->|yes| REC["Recovery: last ✓NN =\ncheckpoint → fresh plan,\nre-enter at step 1"]
  REC --> W
  DEG -->|no| CK{"verified something?"}
  CK -->|yes| APP["Append ✓NN with\nverifier + coverage"]
  APP --> W
  CK -->|no| W
  W --> PH{"phase gate passed?"}
  PH -->|yes| ADV["Advance Phase,\nswap Core, new Next"]
  ADV --> W
  PH -->|"no phases left"| DC["done-check: every Goal\nline maps to a ✓NN"]
  DC -->|"missing"| W
  DC -->|"all covered"| WB["Writeback (if Source):\nVerified + Pending to the remote,\nthen done"]
```

### Opening (loop mode only)

1. State the Goal — one sentence, what "done" means. If the task came from
   a remote todo, set Source and pull Goal from its title.
2. Set Core — max 2 live items with their defining facts.
3. Set Phase if the task has a phases graph — the first phase without a
   checkbox.
4. Set Next — the first concrete action.
5. Write `.riel/ledger.md`.

### Seam — the mechanism

A seam is any boundary: a phase ending, a tool call, opening a file, a
context compaction, coming back hours later. At each seam: **re-read the
ledger.** That is the whole mechanism — the file is not the mechanism, the
re-read is. Without any tooling it is 4 steps and 15 seconds.

Stall detection: same Next for 3 seams → document why or change course.
Goal misaligned with what is being executed → return to the Goal before
acting.

### Recovery (when work degrades)

Long-horizon failure mode (research): once an agent commits to a wrong
intermediate state deep into a trajectory, it cannot detect it and roll
back on its own. The ✓NN entries are numbered on purpose — they are
addressable checkpoints. When work degrades (cascading errors, doubt
loops, corrupted output):

1. **Do NOT resume where it broke.**
2. Re-read the ledger in full.
3. Identify the last ✓NN — that is the return checkpoint.
4. Write a fresh explicit plan from that checkpoint.
5. Re-enter at step 1 of the fresh plan — a new plan, not a continuation
   of the broken one.

The recovery does not pick up where it left off; it writes a fresh plan
and re-enters at step 1. That is the template.

### Failure invariants (not working if...)

Checked whenever the ledger is re-read:

1. A ✓NN was declared and never written to the ledger
2. Something was called verified without stated coverage
3. The Next changed without the real work changing (churn)
4. Something with an existing ✓NN got re-verified
5. The Goal does not match what is being executed
6. Open questions keep growing at every seam with nothing being settled

### Recording verification

When something is verified, append immediately — do not batch:

`✓NN <what holds> — verified by: <command/test/review>, covering <scope>`

### Phase advancement (when the task has a phases graph)

One phase = one mini-ledger. N phases = N sequential mini-ledgers; only the
active one is live. When a phase gate passes: append its ✓NN, advance
Phase, swap Core to the new phase's items, set the new Next. Open items
belonging to future phases migrate with their numbers.

### Done-check (before declaring done)

Read the Goal back **line by line**. Every line must map to a ✓NN with
coverage. If any line is missing → not done. Open ?NN that cannot be
closed go to a Pending list, explicitly — never silently dropped.

## Optional remote sync (compatibility layer, not a dependency)

When `Source` is set, the ledger bridges to the remote task at two moments
only — the remote is never the live ledger:

- **Pull at start:** read the remote task fully → Goal from the title,
  Phase from the first uncompleted phase, seed Verified from existing
  verification.
- **Push at each phase gate and at the end:** append the phase's ✓NN to the
  remote verification section, mark its checkbox, write open ?NN to a
  pending section, then set status done via the safe route.

Adapter contracts (4 operations: pull / push-verify / push-phase /
push-close) and system-specific safety rules (Dran today; Hub/Notion
future) live in `riel/specs/spec-adapters.md`. The Dran-specific patches to
`todo-flow` and `coder-flow` are derived separately from
`spec-todo-contract.md` and `spec-pull-push.md` — they add compatibility,
this skill does not require them.

## Pitfalls

- **Ledger for a fast task** — pure overhead; the gate decides.
- **Batching verification** — append each ✓NN as it happens; batched
  memory is exactly what the ledger prevents.
- **Verified without coverage** — a mood, not a result; the entry is
  incomplete without what it covered.
- **More than 2 live Core items** — workspace capacity is 1-2 ideas; park
  the rest.
- **Empty Next** — the ledger stops being state; if blocked, the block is
  the Next.
- **Sharing a ledger between parallel sessions** — one worktree per
  workstream.
- **Doing done from memory** — the done-check re-reads the Goal line by
  line against the ✓NN list, always.

## Checklist

- [ ] Mode classified: fast/full/loop — ledger only for loop
- [ ] `.riel/ledger.md` opened with Goal + Core + Next (Source if remote)
- [ ] One worktree per workstream
- [ ] Ledger re-read at every seam
- [ ] Failure invariants checked (no unwritten ✓NN, no coverage-less verifies, no churn)
- [ ] On degradation: recovery via last ✓NN + fresh plan, never resumed broken
- [ ] Every ✓NN has verifier + coverage, appended as it happens
- [ ] Every ?NN has a settled-by
- [ ] Next never empty
- [ ] Done-check passed: every Goal line maps to a ✓NN
- [ ] Remote writeback done if Source was set (optional)

## Cross-references

- Local format and rules: `riel/specs/spec-ledger-format.md` (repo)
- Pull/push protocol: `riel/specs/spec-pull-push.md`
- Phase advancement: `riel/specs/spec-phase-advance.md`
- System adapters (Dran first): `riel/specs/spec-adapters.md`
- The phases graph the ledger navigates: `riel-contract`
