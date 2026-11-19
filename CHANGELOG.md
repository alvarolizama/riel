# Changelog

Notable changes to Riel. Version numbers refer to `hermes_plugin/riel/plugin.yaml`;
packaged guides carry their own versions.

## 4.0.0

### Changed
- **Contracts are executed in place.** `.riel/run.md` is gone: a contract is
  authored at `.riel/runs/<slug>.md` and stays there, live and finished alike.
  `done` is derived from evidence, so encoding it as a location carried no
  information and forced a move when the work finished.
- **Several contracts may be active at once in one worktree** — parallel tracks
  no longer need separate worktrees. Every run verb and `note` accept
  `run=<slug>`; with one match it is optional, with several the verb REFUSES and
  names them rather than guessing which contract it is writing.
- `project status` matches a node to its contract by the contract's `### Shaping`
  declaration (path or uid), not by filename, and reads one code path instead of
  the old live-vs-archived split.
- The gate aggregates across active contracts: it holds the turn while ANY of
  them owes evidence, and names the pending slugs. The prompt section lists every
  active contract with its cursor and pending counts, one line each.
- The desktop chip shows `pending/active` and its dialog LISTS the contracts;
  picking one renders its markdown. `GET /run` returns the listing, and
  `GET /run?slug=` returns one contract.

### Added
- `run list` — every contract with its status object, slug and path. A contract
  that cannot be read is reported WITH its error, never skipped.
- `run` selector on `riel_run` (validate/activate/rebase/status/slice) and on
  `riel_note`; `title` in the status object.

### Fixed
- **The session checklist froze with several active contracts.** The refresh read
  one contract's status without forwarding the selector, so with two tracks it hit
  the ambiguity refusal and wrote NOTHING — no rows, no `todo_sync`, no warning,
  while the work advanced. It now reads `run list` and aggregates every activated
  contract. Ids are namespaced by slug (`riel-<slug>-goal`) because two contracts
  used to collide on `riel-goal`; the goal row reads `GOAL [<slug>]: …`. An
  unreadable contract is reported in `todo_sync.unreadable`.
- `scripts/bench-engine.py` could not run at all: its fixture used the refused flat
  format (`## Claims`/`## Graph`/`## Gates`) and wrote `.riel/run.md`. Rebuilt as a
  real contract with a bound shaping and one phase, executed in place.
- Prose that contradicted the engine: the project guide still said one active run
  per worktree (contradicting itself two lines later), the todo spec described a
  phase without a gate (every phase must declare `#### Gates`), a docstring and a
  schema example pointed at a guide section that does not exist, and comments
  still called the engine "v2".
- Step ids are ASSIGNED, not authored: a step bullet starts with its closed verb
  (`- READ the spec`). The template and the run guide said "numbered per phase",
  which read as an instruction to write `F1S1:` by hand — the engine refuses that.

### Removed
- `run archive` — there is nothing to move. Contracts are never pruned.
- The fixed `.riel/run.md` path and every `paths["run"]` resolution.

## 3.0.0

### Added
- `.riel/project.md` (`riel-project/v1`): a project orders shapings. `## Graph`
  nodes are shapings (list register or mermaid), and `project status` derives
  each node's progress from the runs' own evidence — the live run plus the
  archived ones. No gates, no commands and no state of its own.
- `riel_project` (`new|validate|status`), the seventh tool.
- `.riel/shapings/<slug>.md`: several shapings coexist, one per question. Each
  carries a uid (`shp_xxxxxxxx`) in its marker, so identity survives a rename.
- A run binds ONE shaping, declared under `### Shaping` in Context (path or
  uid). Activation records `shaping`, `shaping_id` and `shaping_sha256` in
  Metadata; `run status` reports the binding.
- `run archive`: moves the finished run to `.riel/runs/<slug>.md`, byte-verified
  and never pruned — that file is the project's proof.
- `clean archive=true`: copies `.riel/` outside the worktree
  (`~/.hermes/riel/archive/<worktree>/<timestamp>/`) and verifies every sha256
  before removing anything, then prints the restore command.
- Authoring guard on BOTH artifacts: `run validate`/`run activate` refuse a
  Definition, and `shape validate` refuses a shaping, that still carries
  `{{placeholder}}` text — listing every unfilled field by name. Before this,
  filling only the anchor let a Contract with 21 raw placeholders activate and
  freeze, and a shaping with 18 raw placeholders validate clean: non-empty
  sections were mistaken for authoring. Placeholders inside HTML comments do
  not count.
- The Definition's frame comes before its execution: Objective · Context ·
  Deliverable · Constraints · DO NOT · Phases. Deliverable and DO NOT used to sit
  AFTER the phases, so a reader learned the target and the boundary only after
  reading all the steps. `run slice` emits the packet in the same order.
- Objective and Deliverable are deliberately distinct: the Objective is the
  RESULT in one sentence, the Deliverable is the CONCRETE artifacts (paths,
  files, endpoints). Each phase also carries its own `#### Deliverable` — its
  step of the staircase, not the run's final artifact.
- The Definition is restructured around phases: `## Claims`, `## Graph` and
  `## Gates` are gone, replaced by `## Phases` — the general DAG in its
  preamble, then one `### F#: <title>` per phase carrying its own steps and its
  own `#### Claims`, `#### Gates` and `#### Deliverable`. Seven Definition
  headings instead of nine. The flat sections are REFUSED, not converted.
- Gate membership is STRUCTURAL: a gate belongs to the phase whose block holds
  it. The `— phase:` suffix and the run-global gate fallback are gone; a
  leftover suffix that disagrees with its block is an error.
- Steps are numbered PER PHASE (`F1S1`, `F1S2`, …) instead of one global
  counter. Inserting a step in one phase no longer renumbers another phase's
  anchors, and `§F1#2` resolves to a phase's step — stable, addressable sections
  instead of fragile positional node ids. Checklist rows are `riel-step-F1S1`.
- `run slice F1` copies the phase block VERBATIM with the global sections and
  the frozen Basis, so the packet's anchors resolve exactly as in the parent
  and no other phase's claims or findings travel.
- No legacy support: only `riel-shaping/v3` is read. v1/v2 shapings are refused,
  not converted, and a loose `.riel/shaping.md` is not read at all. There is no
  migration verb and no converter.
- Guides and specs for the new model: `guide/project.md`, `specs/spec-project.md`,
  and an "Authoring outside Riel" section in the shaping guide.

### Changed
- The operational artifact is a **Contract** with three named parts: the
  **Definition** (exactly what will be done, authored and frozen), the **State**
  (what is being done) and the **Evidence** (what was done). A run is the
  execution of a Contract; `.riel/runs/<slug>.md` holds it. The word "plan" is gone from
  the model, the identifiers (`DEFINITION_TITLES`, `_split_definition`,
  `_check_definition`, `definition_sha256`) and every guide and spec.
- Metadata's Definition hash is `definition_sha256` and is REQUIRED on an active
  run: the pre-rename `plan_sha256` key is not read, and a run without a
  Definition hash is refused as stale.
- Shaping format is `riel-shaping/v3`. The marker carries the uid, and the
  shaping now ANSWERS its question: seven sections in a fixed order —
  `Question` (ONE line, ONE `?`), `Answer` (ONE line, no `?`, backed by
  `— supported by F#` or `— decided by: owner`), `Findings`, `Facts`,
  `Not wanted`, `What we want`, and `Open` LAST (the residue).
- Findings are `### F#` dossiers: the heading is the citable claim, the body is
  its support, and a finding may carry its own `#### Diagram`. The frozen Basis
  copies heading + source + confidence, never the body — slices stay small.
  This removes the one-physical-line trap of the bullet register.
- `Alternatives bounced` is now `Not wanted`; `Verdict (→ run)` splits into
  `Answer` (the resolution, which feeds the Contract's Why) and `What we want`
  (the commission: We need · Claim seeds · Scope). The top-level `Diagrams`
  section folds into per-finding `#### Diagram`.
- v2 and v1 sources are refused. Upgrading is deliberate authoring: the Answer,
  `Not wanted`, `What we want` and the dossier findings are decisions, not
  something a converter can invent from old prose.
- `shape validate` with no path answers for the only file in `.riel/shapings/`;
  with several, the caller must choose.
- The stale check watches the BOUND shaping. Editing a sibling shaping no longer
  makes a run stale.
- `clean` removes EVERY entry inside `.riel/` (run, project, shapings, archived
  runs, backups, any other file); only the lock file stays. Archiving is opt-in,
  never the default.
- Riel explains the formats and validates them; it never authors a shaping or a
  project. `new` renders to stdout for every artifact.

### Removed
- `run fetch` and `shape fetch`, and the whole secure-fetch transport (redirect
  policy, sha256 pin, headers, bounds). Producers write the bytes; Riel validates
  them.
- `clean`'s `scope` parameter (`run|all|purge`) and its default backup.
- The canonical single `.riel/shaping.md` as the binding target.

### Upgrade
There is no upgrade path for old state: a v1/v2 shaping must be re-authored in
v3, and a run whose Metadata predates `definition_sha256` must be re-activated.
Archived runs and project files are new — nothing to convert.
`clean` is now destructive by default: pass `archive=true` to keep a verified
copy.

## 2.0.0

### Changed
- Replaced separate contract and ledger state with `.riel/runs/<slug>.md`: one immutable
  Plan, revision-bound State and typed Evidence.
- Shaping stays separate as `.riel/shaping.md`, versioned `riel-shaping/v1`,
  and its referenced Findings are frozen into run slices.
- Six tools: `riel_guide`, `riel_shape`, `riel_run`, `riel_note`,
  `riel_clean`, `riel_check`.
- Activating a run keeps the session checklist synchronized automatically:
  phases and gates are checks, steps are their subchecks, and only passing
  evidence completes them. Non-Riel rows are preserved.
- Gate calls execute their commands and record their actual exit codes.
  Current gate and claim IDs—not checkpoint counts—drive progress.
- Added atomic writes, cross-process locks, bounded backups and per-call output
  sinks. Remote fetch requires SHA-256 and applies its safety policy to every
  redirect.
- README reduced to purpose, use cases, practical flow and installation.

### Removed
- `.riel/contract.md` and `.riel/ledger.md` support, conversion and fallback.
- `riel_plan` and `riel_seam`; separate graph/context verbs and legacy templates.
  Graph checks remain in `riel_check`.
- Free-form claim creation, Goal/Phase/Next state edits and self-supplied gate
  exit codes through `riel_note`.

### Upgrade
This is a deliberate breaking release. Archive any previous local task state and
start a new run; there is no automatic migration.

## 1.0.0

- Seven concrete tools under one plan door, in-process engine and a contract
  supporting mermaid or plain phase lists.
- Prose shipped inside the plugin, read by section, with an optional desktop chip.
