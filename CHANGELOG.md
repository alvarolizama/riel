# Changelog

Notable changes to Riel. Version numbers refer to `hermes_plugin/riel/plugin.yaml`;
packaged guides carry their own versions.

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
