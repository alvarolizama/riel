# Spec 8 — The run format (`riel-run/v1`), version 1

This document specifies **version 1** of the run format. The format tag is
`riel-run/v1`; the engine version that implements it is riel 2.0.0. Any
future incompatible change bumps the tag (and this spec gets a new version
section). There is **no converter**: riel v1's `.riel/contract.md` and
`.riel/ledger.md` are never read as state — the engine refuses when they are
present in `.riel/` and tells you to archive or delete them.

## Role and location

A run is ONE state file, `.riel/run.md`, plus an optional separate,
frozen-side research file, `.riel/shaping.md`, both inside the worktree's
`.riel/` directory. The run replaces riel v1's contract + ledger pair: the
plan and the execution state live in the same file, separated by activation.

## File anatomy

A run file has two halves. The PLAN half is authored by hand; the STATE half
is written only by the engine (`run activate`, `run rebase`, `note`).

    # Run: <title>
    <!-- riel-run/v1 -->

    ## Objective
    ## Context          (### Why, ### Context keywords, ### Basis — frozen)
    ## Constraints
    ## Claims
    ## Graph
    ## Gates
    ## Deliverable
    ## DO NOT
    ---------- activation line ----------
    ## Metadata
    ## Execution state
    ## Core
    ## Open
    ## Evidence

### Format marker

The second element of the file is the standalone line `<!-- riel-run/v1 -->`
(allowing surrounding blank lines), placed before the first `## ` heading.
`run validate` and every state read refuse a file without it — this is what
makes the format strict and keeps legacy files out.

### The plan (nine headings, frozen at activation)

1. `# Run: <title>` — the level-1 title.
2. `## Objective` — one sentence: what "done" produces.
3. `## Context` — carries `### Why` (surviving rationale), `### Context
   keywords` (`- term → source`, the context-fetch index), and, after
   activation, the frozen `### Basis`.
4. `## Constraints` — hard rules, at least one bullet.
5. `## Claims` — `- P1: <what must be true> — anchor: …`; anchors are
   `§<Section>[#<n>]`, a graph node id, or `shaping:F#`. At least one P#.
6. `## Graph` — the execution DAG, in either register (below).
7. `## Gates` — `- G1: <label> — phase: F1`; the `— phase:` clause is
   optional (a gate without one applies to the whole run).
8. `## Deliverable` — what exists when done.
9. `## DO NOT` — scope enforcement, at least one bullet.

### Graph registers

`## Graph` holds either a ` ```mermaid ` flowchart (phases `F#`/`W#`, steps
starting with the closed verbs READ/EDIT/CREATE/RUN/VERIFY/ASK, decision
nodes `{...}` whose outgoing edges all carry labels, loops with a bounded
counter guard) or the plain list register:

    - F1: build the parser
      - READ the spec
      - RUN make test
    - F2: wire the verbs
      - EDIT tools.py
      - RUN make test

In the list register a phase has exactly ONE outgoing edge — to its first
step; steps chain linearly; the last step of a phase edges to the next
phase. `-`, `*` and `1.` are all accepted as bullets; HTML comments are
stripped before parsing, so a commented-out example never becomes data.

### Activation

`run activate` refuses a run that is already active, validates the plan
(strictly) and the shaping (when present), then:

- If claims anchor `shaping:F#` findings, it copies each referenced finding
  — text, `— source:` and `— confidence:` — into a frozen `### Basis`
  subsection inside `## Context`. After this, slicing needs no external
  shaping file. A missing `.riel/shaping.md` is allowed ONLY when no claim
  anchors into it.
- It computes `plan_sha256` over the plan bytes BEFORE `## Metadata` — that
  is, including the frozen Basis — and `shaping_sha256` over the current
  shaping bytes (`none` when there is no shaping file).
- It appends Metadata (`format`, `revision: r1`, `activated`,
  `plan_sha256`, `shaping_sha256`), then Execution state, Core, Open,
  Evidence. A run activates exactly once.

### The state half

- `## Metadata` — the activated hashes and revision (see above).
- `## Execution state` — `current_phase: F1` (derived; see Derivation).
- `## Core` — `- 1. name — fact`; slots are 1-BASED.
- `## Open` — `- Q1: <question> — settled-by: <test>`; closing appends
  `— closed by: E#` to the line. Open ids are never reused, including for
  closed questions. An empty Open section is fine: open questions do not
  block done.
- `## Evidence` — one record per line:

      - E1 gate:G1 claims:P1,P2 revision:r1 command_b64:<base64-of-exact-UTF-8-command> exit_code:0 covering:parser confidence:14
        out: make test … bounded captured output snippet

  `gate:` is the G# (or comma list) this evidence completes; `claims:` the
  P# list it covers (`none` allowed); `revision:` the run revision the
  evidence was produced under. `command_b64:` is the base64 encoding of the
  exact UTF-8 command passed to the shell; Unicode and newlines survive byte
  for byte. State is an engine-written serialization, not an editable command
  list. Decode the field to display the executed command.
  `exit_code:` the REAL captured exit code — there is no flag to self-supply
  one; `covering:` the scope; `confidence:` optional, 1..20. The indented
  `out:` line carries a bounded output snippet.

## `note` — the only state writer

    riel note --gate G1 --claim P1 --command CMD --covering WHAT [--confidence 1..20]
    riel note --core "name — fact" [--core-slot N]
    riel note --open "question" --settled-by TEST
    riel note --close 1 --evidence 1

Rules:

- `--gate` (repeatable) records evidence; it requires `--command` (executed
  via subprocess in the worktree, exit code captured, bounded output
  snippet, bounded timeout — 124 on timeout) and `--covering`.
- `--claim` (repeatable) must reference EXISTING P# ids; `--gate` must
  reference existing G# ids. Unknown ids are rejected.
- `--confidence` is optional (absent by default), 1..20; anything outside
  is rejected. `confidence > 20` and a `--source` flag do not exist.
- One note, one kind: gate evidence, or core, or open/close — never a mix.
- `--core` writes `## Core`; `--core-slot N` is 1-based and replaces or
  appends slot N.
- An open question closes only against existing evidence (`--evidence E#`).
- note NEVER writes goals, nexts, phases or claims: those live in the plan,
  or are derived.
- note refuses stale state (exit 3): if the plan or the shaping bytes no
  longer match the activated hashes, run `run rebase`.

## Derivation (status, todo, done)

- Evidence counts only when its `revision:` equals the current revision.
  Evidence with exit 0 AND (no confidence or confidence >= 12) is passed.
- A phase is complete when every gate mapped to it has passing, counted
  evidence AND all earlier phases are complete. A phase with no mapped gate
  completes automatically once its predecessors do. `current_phase` is the
  first incomplete phase; `next` is the first work step of that phase (its
  label), or the phase label if it has no steps.
- Gate completion drives the phase — never counts of evidence lines.
- done is true when ALL claims are covered by PASSING, counted evidence AND all
  gates have passing evidence. With no gates at all, done is all claims
  covered (the graph was already validated at activation). Open questions
  do NOT block done — an Open section that empties is fine by design.
- A run with no claims cannot be done.

## Rebase

`run rebase` is for after activation: it re-validates the current plan,
re-freezes the Basis from the current shaping, recomputes both hashes, and
bumps the revision (`r2`, `r3`, …). Evidence recorded under an older
revision is RETAINED verbatim but no longer counted. If nothing changed,
rebase says so and changes nothing.

## Slice

`run slice F1` emits a self-validating packet: a DRAFT run file (format
marker, nine plan headings, no state half) carrying the parent's Objective,
Context (with the frozen Basis), Constraints, Claims, Deliverable and
DO NOT, the phase's subgraph as a mermaid block, and the gates mapped to
that phase. Claims anchored to nodes inside the subgraph are kept; if none
map, all claims are kept. `run validate` on the packet passes — the slice
validates itself and needs no external shaping (the Basis is frozen inside
it). The packet works from either graph register and iteratively, so deep
or cyclic graphs never hit a recursion limit.

## Other public verbs

- `shape [PATH]` — validate `.riel/shaping.md` (or PATH): title, non-empty
  Question, Findings with UNIQUE F# ids and a `— source:` on each (a
  finding without a source is a hypothesis, a hard error), non-empty
  Verdict (warning only).
- `shape new` / `run new` — render the template to STDOUT with `--param
  k=v`; they never write state. An editor or write_file is the editing path.
- `todo` — JSON mirror: goal, phases with nested steps and statuses, next,
  claims, open questions.
- `clean [--all] [--purge]` — remove run.md (and shaping.md with `--all`),
  flat timestamped backups inside `.riel/`, at most the last 3 kept.
- `check FILE [--mermaid]` — dense-register markers + graph digest (+mmdc)
  as one JSON envelope (the riel_check behavior, unchanged).

## Persistence guarantees

- Writes go through a temp file + fsync + atomic rename inside the worktree.
- Strict symlink confinement: any symlink on the state path (from the
  worktree down to the file) is refused, and the real parent must resolve
  back inside the worktree.
- A cross-process exclusive flock is held around the ENTIRE note / activate
  / rebase transaction; readers take no lock and rely on the atomic rename,
  so a reader never sees an empty or partial state file.
- Backups are flat (`run-<stamp>.bak.md` inside `.riel/`) and pruned to the
  last 3 — no unbounded accumulation.
- Every error is clean text on the error sink, never a traceback; every
  output goes to explicit sinks (`run_verb(argv, worktree, out, err)`),
  never to process-global stdout/stderr.

## `run fetch` / `shape fetch` — one secure fetch

Both verbs share ONE implementation:

- `--sha256` is MANDATORY (64-hex; integrity is not optional).
- `-o FILE` is the only destination kind (out), written atomically inside
  the worktree; a fetched run.md lands as a DRAFT — activation is never
  automatic.
- `--timeout` and `--max-bytes` are optional bounds (defaults 30s / 5MB).
- Redirects are followed manually with the scheme policy applied to EACH
  hop (https required unless localhost or `--allow-http`), and
  Authorization/Cookie headers are stripped when the origin changes.
- A body shorter than its Content-Length is rejected as incomplete.
- URLs are never exposed with their path or query — errors redact to
  `scheme://host`.
