# Changelog

Notable changes to Riel. Version numbers refer to the plugin (`hermes_plugin/riel/plugin.yaml`);
the five guides carry their own versions in frontmatter.

## 1.0.0

The simplification release: Riel keeps the core steering (plan + ledger + gate) with less surface,
a simpler plan format and a faster engine.

### Changed
- **7 tools, one plan door.** `riel_contract`, `riel_shaping`, `riel_fetch` and `riel_context`
  collapsed into **`riel_plan`** (`verb=new/validate/digest/slice/fetch`, `kind=contract|shaping`).
  Surface: `riel_guide`, `riel_note`, `riel_seam`, `riel_todo`, `riel_plan`, `riel_clean`, `riel_check`.
- **The contract accepts two registers**: a rich mermaid execution graph, or a plain `F#`/`W#`
  phase list (canonical simple). `graph_any` dispatches; validate, todo, digest and slice share
  one code path. A phase's last step is its gate (`RUN`/`VERIFY`).
- **The engine runs in-process** by default: `run_verb` binds every path to the worktree by
  parameter, no global chdir. Measured ~36× faster than the old subprocess path
  (`scripts/bench-engine.py`, 200 calls). Subprocess remains as fallback.
- **The context index travels in `riel_plan`'s answer** on a successful contract `new`/`validate`.
- **README declares the core**: plan + ledger + gate; everything else is accessory.
- `make validate` covers 15 mermaid blocks; suite count 312.

### Removed
- **`protocol` guide.** Six topics down to five: `contract`, `delegate`, `ledger`, `shaping`, `tools`.
  Its opening conditions are owned by the harness/profile, not the framework.
- Standalone `riel_context`, `riel_contract`, `riel_shaping`, `riel_fetch` tool names.

### Fixed
- The engine resolves `__file__` absolutely, so by-path loads survive the plugin being installed
  as a copy (no more broken `engine/` resolution in some environments).

### Upgrade
Update from a previous version:

```bash
hermes plugins update riel    # or --force when already enabled
hermes plugins doctor riel
```

Call sites change: use `riel_plan(verb=...)` where you used `riel_contract`, `riel_shaping`
(`kind="shaping"`) or `riel_fetch` (`verb="fetch"`). The context keywords that came from
`riel_context` now ride in the plan's answer.
