# Spec 8 — The Contract and its run format (`riel-run/v1`)

This document specifies the Contract: the artifact a run executes. The format
tag is `riel-run/v1`; the engine version that implements it is riel 3.0.0. Any
future incompatible change bumps the tag (and this spec gets a new version
section). There is **no converter**: riel v1's `.riel/contract.md` and
`.riel/ledger.md` are never read as state — the engine refuses when they are
present in `.riel/` and tells you to archive or delete them.

## Role and location

A **Contract** is the operational artifact: the exact Definition of what will
be done, the State of what is being done, and the Evidence of what was done.
A **run** is the execution of that Contract, and `.riel/run.md` is the ONE file
that holds both, inside the worktree's `.riel/` directory. "Plan" is not a term
of this model. It executes ONE shaping from `.riel/shapings/` (Spec 2), optionally
ordered by `.riel/project.md` (Spec 9), and when finished it is archived to
`.riel/runs/<slug>.md`. The run replaces riel v1's contract + ledger pair: the
Definition, State and Evidence live in the same file, separated by activation.

## File anatomy

A run file holds ONE Contract in three parts. The DEFINITION is authored by
hand; the STATE and the EVIDENCE are written only by the engine (`run activate`,
`run rebase`, `note`). The cut is `## Metadata`: everything before it is the
Definition, everything from it down is engine-written.

    # Run: <title>
    <!-- riel-run/v1 -->

    DEFINITION — authored by hand, frozen and hashed at activation
    ## Objective
    ## Context          (### Why, ### Context keywords, ### Shaping, ### Basis — frozen)
    ## Constraints
    ## Claims
    ## Graph
    ## Gates
    ## Deliverable
    ## DO NOT
    ---------- activation line (## Metadata) ----------
    STATE — written only by the engine
    ## Metadata
    ## Execution state
    ## Core
    ## Open
    EVIDENCE — append-only, written only by the engine
    ## Evidence

### Format marker

The second element of the file is the standalone line `<!-- riel-run/v1 -->`
(allowing surrounding blank lines), placed before the first `## ` heading.
`run validate` and every state read refuse a file without it — this is what
makes the format strict and keeps legacy files out.

### The Definition (nine headings, frozen at activation)

1. `# Run: <title>` — the level-1 title.
2. `## Objective` — one sentence: what "done" produces.
3. `## Context` — carries `### Why` (surviving rationale), `### Context
   keywords` (`- term → source`, the context-fetch index), `### Shaping`
   (`- shaping: <path or uid>`, the one shaping this run executes), and, after
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

`run activate` refuses a run that is already active, resolves the shaping the
Definition declares under `### Shaping`, validates the Definition (strictly) and that
shaping, then:

- A loose legacy `.riel/shaping.md` is migrated into `.riel/shapings/` first
  (Spec 2), and the declaration is written into the Definition.
- If claims anchor `shaping:F#` findings, it copies each referenced finding
  — text, `— source:` and `— confidence:` — into a frozen `### Basis`
  subsection inside `## Context`, naming the shaping and its uid. After this,
  slicing needs no external shaping file. No bound shaping is allowed ONLY
  when no claim anchors into one.
- It computes `definition_sha256` over the Definition bytes BEFORE `## Metadata` — that
  is, including the frozen Basis — and `shaping_sha256` over the bound
  shaping's bytes (`none` when the run binds no shaping).
- It appends Metadata (`format`, `revision: r1`, `activated`, `definition_sha256`,
  `shaping`, `shaping_id`, `shaping_sha256`), then Execution state, Core, Open,
  Evidence. A run activates exactly once.

### State and Evidence

- `## Metadata` — the activated hashes, the revision, and the shaping binding
  (`shaping` path, `shaping_id` uid, `shaping_sha256`). The Definition hash is
  `definition_sha256`; a run activated before the Contract vocabulary carries
  the old `plan_sha256` key, which is still READ so a live run does not break.
  Its next rebase writes `definition_sha256` and drops the old key.
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
- note NEVER writes goals, nexts, phases or claims: those live in the Definition,
  or are derived.
- note refuses stale state (exit 3): if the Definition or the BOUND shaping's bytes
  no longer match the activated hashes, run `run rebase`. A sibling shaping's
  bytes are irrelevant to this run.

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

`run rebase` is for after activation: it re-validates the current Definition,
re-freezes the Basis from the bound shaping (migrating a loose legacy file if
that is what the run still binds), recomputes both hashes, and bumps the
revision (`r2`, `r3`, …). Evidence recorded under an older
revision is RETAINED verbatim but no longer counted. If nothing changed,
rebase says so and changes nothing.

## Slice

`run slice F1` emits a self-validating packet: a DRAFT run file (format
marker, nine Definition headings, no State or Evidence) carrying the parent's Objective,
Context (with the frozen Basis), Constraints, Claims, Deliverable and
DO NOT, the phase's subgraph as a mermaid block, and the gates mapped to
that phase. Claims anchored to nodes inside the subgraph are kept; if none
map, all claims are kept. `run validate` on the packet passes — the slice
validates itself and needs no external shaping (the Basis is frozen inside
it). The packet works from either graph register and iteratively, so deep
or cyclic graphs never hit a recursion limit.

## Other public verbs

- `shape [PATH]` — validate a shaping (Spec 2): title, marker with uid, ONE
  question on ONE line, Findings with UNIQUE F# ids and a `— source:` on each
  (a finding without a source is a hypothesis, a hard error), non-empty
  Verdict (warning only). With no PATH it answers for the only file in
  `.riel/shapings/`; with several, the caller must choose.
- `shape new` / `run new` / `project new` — render the template to STDOUT with
  `--param k=v`; they never write state. An editor, a project system or a
  copy-paste is the writing path. `shape new` mints the shaping's uid.
- `project [FILE]` / `project status` — the ordering of shapings and its
  derived progress (Spec 9).
- `run archive` — move the active run to `.riel/runs/<slug>.md`, byte-verified,
  refusing to overwrite an existing archive. Never pruned.
- `todo` — JSON mirror: goal, phases with nested steps and statuses, next,
  claims, open questions.
- `clean [--archive]` — remove EVERY entry inside `.riel/` (run, project,
  shapings, archived runs, legacy state, backups); only the lock file stays.
  `--archive` first copies the tree to `~/.hermes/riel/archive/<worktree>/<ts>/`
  and verifies every sha256. Without it there is no backup and no way back.
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
- Churn backups are flat (`run-<stamp>.bak.md` inside `.riel/`) and pruned to
  the last 3 — no unbounded accumulation. Archived runs (`.riel/runs/`) and a
  clean archive are NEVER pruned: they are evidence, not churn.
- Every error is clean text on the error sink, never a traceback; every
  output goes to explicit sinks (`run_verb(argv, worktree, out, err)`),
  never to process-global stdout/stderr.
