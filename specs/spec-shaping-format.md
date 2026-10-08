# Spec 7 — Shaping format (`.riel/shaping.md`)

Status: draft v1 · Riel — local-first
Applies to every task that explores before it plans: the on-ramp that
`spec-contract-format.md` (Spec 2) consumes. A task whose decision is already
settled needs no shaping; a task whose decision was researched does.

The **contract** is the plan, the **ledger** is the state, and the **shaping**
is the EVIDENCE the plan rests on. It is written before the contract, and the
contract's claims point back into it (Spec 2, "Claim anchors").

## Role and location

- `.riel/shaping.md` in the task worktree; `.riel/` is in `.gitignore` — local
  state, never a deliverable, never committed (same hygiene as the ledger and
  the contract).
- Written **before** the contract: the shaping closes the question, then the
  contract restates the decision in its closed form. Same worktree, same task.
- `riel_clean(scope="all")` backs it up (flat, timestamped, inside `.riel/`) and
  removes it, exactly like the contract; without `--all` it is left in place.
- Overwritten per task: it is the working evidence of the task in flight, not a
  durable record.

## Why it is not the contract

A doc that restates another is a drift source. The contract's `## Context` is
CLOSED (reference snippets verified against the repo, paths decided) and its
`### Why` is one or two sentences of surviving rationale. The shaping is OPEN:
findings with their sources and a confidence, alternatives with their verdicts,
questions still unsettled. It is the on-ramp, never a copy.

| Artifact | Answers | Register |
|---|---|---|
| `shaping.md` | what do we know, and how do we know it | open, sourced |
| `contract.md` | what will be true, and how it is verified | closed, decided |
| `ledger.md` | where we are | state |

## Sections, in order

1. `# Shaping: <name>`
2. `## Question` — one sentence: the decision this shaping closes
3. `## Findings` — `- F<n>: <finding> — source: <path:line | URL + date | command>, confidence <high|med|low>`
4. `## Facts` — what the design must respect (established facts, with where they were verified)
5. `## Diagrams` — OPTIONAL: the shape of the system as it is and as it would be
6. `## Alternatives bounced` — `- A<n>: <option> — pro: … / contra: … — verdict: kept|discarded`
7. `## Open` — questions not settled yet, each with the cheapest test that would settle it: `— settled by: <test>`
8. `## Verdict (→ contract)` — the seed: `We need …` (the Objective), `Decision: … — because …` (the `### Why`), the claim seeds, and the scope in/out

`## Diagrams` is free — the validator pins the required set and does not
require it. It holds mermaid of the system's CURRENT shape and the proposed
one (the flow being changed, where the pain is, what moves), so the contract
is authored with the picture in view. It is never the execution DAG: the
contract's `## Execution graph` is the only plan graph, and a shaping diagram
that drifts into it just duplicates what the contract must state.

## Validation

`riel_shaping(verb="validate", file=PATH)` — default `.riel/shaping.md`.

Errors (exit 1): a missing section, an empty `## Question`, a `## Findings`
section with no `F#` line.

WARNs (non-fatal): a finding without `source:`, a finding without a
`confidence`, an `## Alternatives bounced` item without a `verdict:`, an
`## Open` item without `settled by:`, a `## Verdict` that does not open its
Objective line with `We need`, and a `shaping:F<n>` anchor in the contract that
names a finding the shaping does not have.

The shipped template carries one placeholder `F#` line with its `source:` and
`confidence` slots, so a freshly instantiated shaping validates like every
other shipped fixture: the structure is there, the research is not.

## Claim anchors

The contract's claims point back into the shaping: `— anchor: shaping:F<n>`
(Spec 2, "Claim anchors"). That is what keeps provenance: at any seam,
`riel_seam(anchors=true)` prints the claim beside the finding that supports it, so a
finding that changed can be noticed while the claim is still refutable —
instead of after it has been "verified".

## The handoff

`riel_shaping(verb="new")` instantiates `templates/shaping.md`. The
handoff into the contract is authored, never generated: the Verdict seeds
`## Objective`, the `### Why` and `## Pre-registered claims`, and each claim
keeps its provenance anchor.

## Cross-references

- `spec-contract-format.md` (Spec 2) — the plan the shaping seeds; Claim anchors
- `spec-ledger-format.md` (Spec 1) — the state the plan advances
- `spec-todo-hermes.md` (Spec 6) — the plan mirror
- `riel_guide(topic="briefs")` — the template, and the shaping step before the contract
- `riel_guide(topic="tools")` — `shaping validate`, `shaping new`, the seam's anchors
