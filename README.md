<div align="center">

<img src="assets/riel-header.png" width="96" alt="Riel" />

# Riel

### *Riel* — the rail a runaway train needs. Steering, not horsepower.

### Steering layer for harness/LLM

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.0-8B5CF6.svg)](./hermes_plugin/riel/plugin.yaml)
[![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Hermes](https://img.shields.io/badge/Hermes-plugin-5B8DEF)](https://www.nousresearch.com)

</div>

## What is Riel

Riel gives a coding agent a **plan, persistent execution state and real verification**. The whole task lives in `.riel/run.md`: what to build, its steps, its claims and the evidence produced by its gates. Progress is calculated from evidence, not from a confident "done".

When the design still needs research, `.riel/shaping.md` records the question, code references, alternatives and decision that feed the Plan. Research is separate and editable; an active Plan changes only through an explicit rebase.

## What it is for

- **Multi-step work across sessions** — resume from derived state instead of memory.
- **Verified completion** — every claim and gate needs a real command result.
- **Delegation** — children receive scoped, immutable run slices; the parent re-runs their gates before accepting evidence.
- **Remote tasks** — materialize bounded, SHA-256-checked runs and shapings without putting their bodies into model context.

A quick one-step edit needs none of this.

## How to use it

### 1. Shape the decision when needed

```text
riel_shape(verb="new")
# Save the returned draft at .riel/shaping.md and fill it.
riel_shape(verb="validate")
```

A shaping records findings with sources, alternatives and the final decision. Code references should name the repository, observed commit, file lines and symbol so they can be checked again.

### 2. Write and activate the Plan

```text
riel_run(verb="new", template="run")
# Write and fill the returned draft at .riel/run.md.
riel_run(verb="validate")
riel_run(verb="activate")
```

Activation freezes the Plan and the shaping cited by its claims. Claims, phases, gates and their IDs are defined before execution; changing them takes an explicit rebase.

### 3. Execute and verify

At a gate, Riel runs its real command:

```text
riel_note(
  gates=["G1"],
  claims=["P1"],
  command="make test",
  covering="P1 behavior and neighboring regressions"
)
```

It records the actual exit code as Evidence. A checkpoint for another claim or gate cannot advance this work.

### 4. Read the result

```text
riel_run(verb="status")
```

Status calculates the cursor, claim/gate results, Next and `done`. `riel_run` also keeps the session checklist synchronized automatically: phases and gates are checks, steps are their subchecks, and only passing evidence completes them.

To delegate, use `riel_run(verb="slice", phase="W1")`. The child receives its immutable scope; the parent integrates the code and reruns its gate before accepting Evidence.

## Install

```bash
hermes plugins install "git@github.com:alvarolizama/riel.git#hermes_plugin/riel" --enable
hermes plugins update riel         # after a new version
hermes plugins doctor riel         # verify the installation
```

Enable the desktop integration in **Capabilities → Plugins → riel**, then start a new session. The installer copies a commit: uncommitted local changes do not travel through it.

Python 3 is the only runtime requirement—no extra packages. Riel exposes six tools, not a CLI on `PATH`:

`riel_guide` · `riel_shape` · `riel_run` · `riel_note` · `riel_clean` · `riel_check`

Remote runs and shapings use the same Markdown format as local files. `fetch` requires their SHA-256 and writes an inactive draft; validation and activation remain separate.

Call `riel_guide()` for the packaged guides. The repository's `specs/` documents the formats, projections and package.

For development:

```bash
make test
make lint
make validate    # Mermaid parser checks; needs mmdc
```

## License

[MIT](LICENSE) — Copyright (c) 2026 Álvaro Lizama.
