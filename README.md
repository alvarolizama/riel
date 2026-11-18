<div align="center">

<img src="assets/riel-header.png" width="96" alt="Riel" />

# Riel

### *Riel* — the rail a runaway train needs. Steering, not horsepower.

### Steering layer for harness/LLM

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-3.0.0-8B5CF6.svg)](./hermes_plugin/riel/plugin.yaml)
[![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Hermes](https://img.shields.io/badge/Hermes-plugin-5B8DEF)](https://www.nousresearch.com)

</div>

## What is Riel

Riel gives a coding agent a **contract, persistent execution state and real verification**. A task lives in `.riel/run.md`: what to build, its steps, its claims and the evidence produced by its gates. Progress is calculated from evidence, not from a confident "done".

Work is organized in three layers. A **shaping** (`.riel/shapings/<slug>.md`) answers **one question** with sourced findings, alternatives and a decision. A **run** executes exactly one shaping and delivers one PR. A **project** (`.riel/project.md`) orders several shapings and derives its progress from the runs that finished them.

Riel explains these formats and validates them. It never writes them for you: an editor, your project system, an MCP server or a plain copy-paste produces the bytes, and Riel decides whether they are well formed.

## What it is for

- **Multi-step work across sessions** — resume from derived state instead of memory.
- **Verified completion** — every claim and gate needs a real command result.
- **Projects with several tracks** — one question per shaping, one run per shaping, one PR per run, in the order the project declares.
- **Delegation** — children receive scoped, immutable run slices carrying their frozen findings; the parent re-runs their gates before accepting evidence.
- **Formats you can author anywhere** — the Markdown is the contract, so any system that can write a file can feed a run.

A quick one-step edit needs none of this.

## How to use it

### 1. Shape the question

```text
riel_shape(verb="new")
# Save the returned draft at .riel/shapings/<slug>.md and fill it.
riel_shape(verb="validate", file=".riel/shapings/<slug>.md")
```

One question per shaping, findings with sources, alternatives and the final decision. Code references name the repository, observed commit, file lines and symbol so they can be checked again.

### 2. Order the questions (when there are several)

```text
riel_project(verb="new")
# Save the returned draft at .riel/project.md and list the shapings.
riel_project(verb="validate")
riel_project(verb="status")
```

Status names the next shaping to run. A node is done when its archived run is done — never because someone said so.

### 3. Write and activate the run

```text
riel_run(verb="new", template="run")
# Write and fill the returned draft at .riel/run.md, declaring its shaping.
riel_run(verb="validate")
riel_run(verb="activate")
```

Activation freezes the Definition and the shaping it binds, records the shaping's uid and hash, and copies the cited findings into the run. Claims, phases and gates are defined before execution; changing them takes an explicit rebase.

### 4. Execute and verify

At a gate, Riel runs its real command:

```text
riel_note(
  gates=["G1"],
  claims=["P1"],
  command="make test",
  covering="P1 behavior and neighboring regressions"
)
```

It records the actual exit code as evidence. A checkpoint for another claim or gate cannot advance this work.

### 5. Read the result, then archive

```text
riel_run(verb="status")
riel_run(verb="archive")
```

Status calculates the cursor, claim and gate results, next and `done`, and keeps the session checklist synchronized: phases and gates are checks, steps are their subchecks, and only passing evidence completes them. Archive moves the finished run to `.riel/runs/<slug>.md`, where the project reads its proof, and frees the worktree for the next shaping.

To delegate, use `riel_run(verb="slice", phase="W1")`. The child receives its immutable scope; the parent integrates the code and re-runs its gate before accepting evidence.

## Install

```bash
hermes plugins install "git@github.com:alvarolizama/riel.git#hermes_plugin/riel" --enable
hermes plugins update riel         # after a new version
hermes plugins doctor riel         # verify the installation
```

Enable the desktop integration in **Capabilities → Plugins → riel**, then start a new session. The installer copies a commit: uncommitted local changes do not travel through it.

Python 3 is the only runtime requirement—no extra packages. Riel exposes seven tools, not a CLI on `PATH`:

`riel_guide` · `riel_project` · `riel_shape` · `riel_run` · `riel_note` · `riel_clean` · `riel_check`

Call `riel_guide()` for the packaged guides. The repository's `specs/` documents the formats, projections and package.

For development:

```bash
make test
make lint
make validate    # Mermaid parser checks; needs mmdc
```

## License

[MIT](LICENSE) — Copyright (c) 2026 Álvaro Lizama.
