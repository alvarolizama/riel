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
    ## Phases           (general DAG, then ### F#: <title> per phase,
                         each with #### Claims, #### Gates, #### Deliverable)
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

### Authoring guard

A Definition that still carries `{{placeholder}}` text is a SKELETON, not a
Contract: `run validate` and `run activate` refuse it and list every unfilled
field by name. Non-empty sections are not authoring — `{{objective}}` is
non-empty text, and without this guard `definition_sha256` would freeze the
template as if it were a decision. Placeholders inside HTML comments do not
count; they are documentation, never data.

### Format marker

The second element of the file is the standalone line `<!-- riel-run/v1 -->`
(allowing surrounding blank lines), placed before the first `## ` heading.
`run validate` and every state read refuse a file without it — this is what
makes the format strict and keeps legacy files out.

### The Definition (seven headings, frozen at activation)

1. `# Run: <title>` — the level-1 title.
2. `## Objective` — one sentence: what "done" produces.
3. `## Context` — carries `### Why` (surviving rationale), `### Context
   keywords` (`- term → source`, the context-fetch index), `### Shaping`
   (`- shaping: <path or uid>`, the one shaping this run executes), and, after
   activation, the frozen `### Basis`.
4. `## Constraints` — hard rules, at least one bullet. GLOBAL: they bind every
   phase.
5. `## Phases` — the execution structure, in two levels (below).
6. `## Deliverable` — what exists when the whole run is done.
7. `## DO NOT` — scope enforcement for the whole PR, at least one bullet.
   GLOBAL: no phase may relax it. One run is one shaping is one PR, so the
   boundary is reviewed as a whole, not per phase.

The flat `## Claims`, `## Graph` and `## Gates` sections are REFUSED, not read:
claims, gates and the DAG live inside `## Phases`. There is no converter.

### The Phases outline

`## Phases` holds the general DAG in its preamble, then one `### F#: <title>`
per phase. Each phase block carries its own steps and its own `#### Claims`,
`#### Gates` and `#### Deliverable` — all three required, all non-empty.

    ## Phases
    <!-- general DAG here: mermaid between phases, or `- F1 → F2 → F3` -->

    ### F1: build the parser
    - READ the spec
    - EDIT engine/run.py
    - RUN make test

    #### Claims
    - P1: the parser cuts at Metadata — anchor: §F1#2

    #### Gates
    - G1: make test

    #### Deliverable
    - engine/run.py reads one file

    ### F2: wire the verbs
    - VERIFY make lint

    #### Claims
    - P2: the verbs resolve — anchor: §F2#1

    #### Gates
    - G2: make lint

    #### Deliverable
    - tools.py rewired

**Level 1 — the general DAG.** A ` ```mermaid ` flowchart between phases
(decision nodes `{...}` whose outgoing edges all carry labels, loops with a
bounded counter guard `< 3` / `>= 3`), or an arrow list `- F1 → F2 → F3`, or
nothing: then the authored order of the `### F#` headings IS the order.
Decisions and loops belong to this level.

**Level 2 — a phase's steps.** Bullets starting with the closed verbs
READ/EDIT/CREATE/RUN/VERIFY/ASK, chained linearly. They are numbered PER PHASE
(`F1S1`, `F1S2`, …, `F2S1`, …), so inserting a step in one phase never
renumbers another phase's anchors. A phase has exactly ONE outgoing edge — to
its first step; the last step edges to the next phase per the general DAG.

**Membership is structural.** A gate belongs to the phase whose block holds
it; there is no `— phase:` suffix and no run-global gate. A leftover suffix
that disagrees with its block is an error. `P#` and `G#` ids stay globally
unique because Evidence rows reference them.

**Anchors.** `§F1#2` names step 2 of phase F1 and is stable against edits in
other phases. `§<Section>#n`, a node id, and `shaping:F#` work as before.

`-`, `*` and `1.` are all accepted as bullets; HTML comments are stripped
before parsing, so a commented-out example never becomes data.

### Activation

`run activate` refuses a run that is already active, resolves the shaping the
Definition declares under `### Shaping`, validates the Definition (strictly) and that
shaping, then:

- The shaping declaration is written into the Definition (Spec 2).
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
  `definition_sha256` and it is REQUIRED: a run carrying the pre-rename
  `plan_sha256` key, or no Definition hash at all, is refused as stale. There
  is no upgrade path — re-author the Definition and activate again.
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
- A phase is complete when every gate INSIDE its block has passing, counted
  evidence AND all earlier phases are complete. Membership is structural, so
  every valid phase has at least one gate. `current_phase` is the first
  incomplete phase; `next` is the first work step of that phase (its label),
  or the phase label if it has no steps.
- Gate completion drives the phase — never counts of evidence lines.
- done is true when ALL claims are covered by PASSING, counted evidence AND all
  gates have passing evidence. With no gates at all, done is all claims
  covered (the graph was already validated at activation). Open questions
  do NOT block done — an Open section that empties is fine by design.
- A run with no claims cannot be done.

## Rebase

`run rebase` is for after activation: it re-validates the current Definition,
re-freezes the Basis from the bound shaping, recomputes both hashes, and bumps the
revision (`r2`, `r3`, …). Evidence recorded under an older
revision is RETAINED verbatim but no longer counted. If nothing changed,
rebase says so and changes nothing.

## Slice

`run slice F1` emits a self-validating packet: a DRAFT Contract (format
marker, the seven Definition headings, no State or Evidence) carrying the
parent's Objective, Context (with the frozen Basis, Why and keywords),
Constraints, Deliverable and DO NOT — all global — plus ONE `### F1: <title>`
block copied VERBATIM: its steps, its `#### Claims`, its `#### Gates` and its
`#### Deliverable`. No other phase travels, so the child never sees another
track's claims or findings.

Because the block is verbatim, its anchors resolve exactly as in the parent:
`§F1#2` names the same step, and `shaping:F#` resolves against the frozen
Basis inside the packet — no external shaping file is needed. `run validate`
on the packet passes; the slice validates itself before it is emitted.
Graph walks are iterative, so deep or cyclic graphs never hit a recursion
limit.

## Other public verbs

- `shape [PATH]` — validate a shaping (Spec 2): title, marker with uid, ONE
  question on ONE line, ONE answer on ONE line with no `?` and cited backing
  (`— supported by F#` or `— decided by: owner`), Findings with UNIQUE F# ids
  and a `— source:` on each (a finding without a source is a hypothesis, a hard
  error), and the seven sections in order with Open last. Only v3 is read.
  With no PATH it answers for
  the only file in `.riel/shapings/`; with several, the caller must choose.
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
