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
- **Written (or fetched) first, always** — before opening the ledger, before
  any execution, **whether the task delegates or not**. A remote contract
  (authored elsewhere) is materialized here, at the opening, with
  `riel_fetch` — never deferred to delegation ("Remote contracts", below).
- Overwritten per session: it is working memory for the task in flight, not
  a durable record.

## The format is the packet format

`contract.md` reuses the packet's section set — canonical skeleton in
`riel-briefs/templates/packet.md`; graph conventions in `riel:contract`.
**Do not duplicate the structure here.**

The nine sections, in order:

1. `# Task:` — the name
2. `## Objective` — one sentence, opens with "We need…"; `brief validate`
   WARNs (non-fatal) when it runs past one sentence — rationale belongs in
   `### Why`, not here
3. `## Context` — project, code to read/modify, reference snippets, plus the
   `### Why` rationale and the `### Context keywords` index (see "Context
   fetch")
4. `## Constraints` — hard rules
5. `## Pre-registered claims` — P-ids with a verify-with and their anchor
   (see "Claim anchors")
6. `## Execution graph` — the mermaid DAG (riel:contract)
7. `## Verification gates` — command / expected / on failure, per phase
8. `## Deliverable`
9. `## DO NOT`

Validate it mechanically: `riel_brief(verb="validate", file=".riel/contract.md")` (the
validator keys on this exact section set and order).

## Claim anchors

A `P#` claim may close its line with the anchor to the region of this contract
that supports it, after the verify-with:

```
- P1: the token verifies for ≤1h — verify with: `mix test token_test.exs` — anchor: §Constraints#2
- P2: no query escapes the scope — verify with: `mix test scope_test.exs` — anchor: G2
- P3: the finding still holds — verify with: `mix test` — anchor: shaping:F1
```

Three forms and only three: `§<Section>[#<n>]` (the whole section, or its n-th
bullet), a node id of this contract's execution graph, and `shaping:<F#>`
(a finding of `.riel/shaping.md`, Spec 7). Canonical syntax and its
enforcement: `riel:contract`, "Claim anchors".

Two mechanical facts bind the form: **the claim stays on ONE line** — the
ledger seed reads line by line — and `brief slice` copies the section
verbatim, so an anchor written here reaches the child for free.
`riel_seam(anchors=true)` resolves a claim's anchor into its excerpt, which is what a seam
re-reads; a missing anchor is a `WARN` (the shipped templates carry none),
never a hard failure.

## Intent (the `### Why` subsection)

`## Context` opens with `### Why`: one or two sentences of rationale — what
triggers this objective, which alternative was discarded. The Objective says
*what done looks like*; the claims make it falsifiable; `### Why` is the only
home for *why this and not something else*.

It is a `###` subsection on purpose: `brief validate` pins the nine `##`
sections and ignores `###`, so the format stays stable. It is **inherited
mechanically by `riel_brief(verb="slice")`** (like `### Context keywords` and the
Objective itself), so a delegated child receives the rationale instead of a
FILL — and the inherited copy carries the rule: on a conflict with the
execution, the child escalates (`ASK[goal-changing]`), it never
reinterprets the intent.

Missing `### Why` is not an error and not a WARN: a hand-driven task whose
author holds the rationale needs no section for it. It earns its place when
the contract travels — a remote `fetch`, a slice, a resumed session.

## Context fetch (the keywords)

`## Context` carries a machine-readable index: `### Context keywords`, one term
per line with an optional `→ dran|memory|code` hint (`riel_context` emits it
as JSON). It is consulted at exactly the two moments where `Core` is (re)set —
nowhere else, so no tool call pays for a search the task does not need:

| Moment | What happens |
|---|---|
| Opening the task (`resume`, `seam`, `note --from-contract`) | the keywords are searched and the answers seed `Core` (max 2) |
| Advancing a phase (spec-ledger-format, Phase advance) | the incoming phase's `Core` comes from the same search |
| Slicing a packet for a child | `brief slice` carries the keywords into the packet, so the child searches the same index with its own budget |

Missing keywords are a `WARN`, never an error: a contract without them still
validates — the fetch simply has nothing to search.

**Who searches:** the agent, with whatever memory backend it has configured
(DRAN, its own memory, `search_files`). A plugin cannot reach those backends —
they live in the agent's memory manager, not in the tool registry — so the
plugin's job (`riel_context`) is to hand over the index, never to answer with
hits it did not obtain.

## Contract vs ledger

| Layer | Artifact | Source of truth for | Lifetime |
|---|---|---|---|
| Contract | `.riel/contract.md` | the plan (phases, claims, gates) | the task |
| Ledger | `.riel/ledger.md` | the state (✓NN evidence, Next) | the task |

- Each phase of the contract's graph = one mini-ledger
  (spec-ledger-format, Phase advance). Only the active phase's ledger is live.
- The ✓NN evidence lives in the ledger, **never in the contract**.
- The contract is written once and re-read as the plan; the ledger is
  re-read at every seam.

## Delegation: the packet is a slice of the contract

When the task delegates, the child receives a **packet**: the contract
narrowed to the child's phase — its subgraph, its gates, its Deliverable,
its DO NOT — plus the inherited intent (the Objective and the `### Why`
rationale travel in every slice). Same format, fewer phases. The child
**never opens a ledger**: it returns JSON and the **parent** — the sole
writer of `.riel/ledger.md` — turns that into ✓NN. The parent keeps the full
contract and the ledger.

## Remote contracts (fetch)

The contract is not always hand-written in the worktree: an authoring tool
(e.g. Gorim) can render it server-side and hand the agent a reference. The
body never travels through the agent's context — MCP responses cap at ~10KB
and a contract exceeds it — so the export returns `{url, sha256, bytes}` and
`riel_fetch(url=…, out=".riel/contract.md", sha256=…)` materializes it
into the worktree. `fetch` is server-agnostic: HTTPS by default (plain `http`
only for localhost, or anywhere with `--allow-http` on a trusted transport
such as a VPN), TLS verified, body bounded, **atomic** write, and the URL is
never printed — a short-lived, single-use token embedded in the query string
must not leak into logs. The `sha256` from the reference pins end-to-end
integrity. Full flags and exit codes: skill `riel:cli`, "Fetch" section.

**When:** at the *opening* of the task — the moment Riel starts working on the
contract (`resume` / `seam` / `note --from-contract`), right before the
context fetch. **Independent of delegation:** a solo task fetches its contract
the same way, and slicing a packet for a child (`brief slice`) is a later,
separate moment — never the trigger. Tying the download to delegation would
leave a non-delegating task without its contract.

## Cross-references

- Ledger format: `spec-ledger-format.md` (Spec 1)
- Session-todo mirror: `spec-todo-hermes.md` (Spec 6)
- Packet skeleton + templates: skill `riel:briefs`
- Graph conventions: skill `riel:contract`
