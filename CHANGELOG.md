# Changelog

Notable changes to Riel. Version numbers refer to `hermes_plugin/riel/plugin.yaml`;
packaged guides carry their own versions.

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
- Migration of a loose `.riel/shaping.md`: `activate`/`rebase` move it into
  `shapings/`, mint its uid, rotate the original to a timestamped `.bak.md` and
  rebind the run in one transaction. An already-active pre-v2 run keeps working
  until its next rebase.
- Guides and specs for the new model: `guide/project.md`, `specs/spec-project.md`,
  and an "Authoring outside Riel" section in the shaping guide.

### Changed
- The operational artifact is a **Contract** with three named parts: the
  **Definition** (exactly what will be done, authored and frozen), the **State**
  (what is being done) and the **Evidence** (what was done). A run is the
  execution of a Contract; `.riel/run.md` holds it. The word "plan" is gone from
  the model, the identifiers (`DEFINITION_TITLES`, `_split_definition`,
  `_check_definition`, `definition_sha256`) and every guide and spec.
- Metadata's Definition hash is `definition_sha256`. The pre-rename `plan_sha256`
  key is still read, so an already-active run keeps working; its next rebase
  writes the new key and drops the old one.
- Shaping format is `riel-shaping/v2`: the marker carries the uid, and
  `## Question` must be ONE line with ONE question mark. Two questions are two
  shapings, and validation refuses them.
- `shape validate` with no path answers for the only file in `.riel/shapings/`;
  with several, the caller must choose.
- The stale check watches the BOUND shaping. Editing a sibling shaping no longer
  makes a run stale.
- `clean` removes EVERY entry inside `.riel/` (run, project, shapings, archived
  runs, legacy state, backups); only the lock file stays. Archiving is opt-in,
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
A loose `.riel/shaping.md` is migrated automatically on the next `activate` or
`rebase`; a shaping that answers two questions refuses migration and must be
split first. Archived runs and project files are new — nothing to convert.
`clean` is now destructive by default: pass `archive=true` to keep a verified
copy.

## 2.0.0

### Changed
- Replaced separate contract and ledger state with `.riel/run.md`: one immutable
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
