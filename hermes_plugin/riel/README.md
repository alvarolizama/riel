# Riel — Hermes plugin (v4.1.0)

The package **is** the product: the prose, the engine, the tools, the gate and the
desktop chip. State lives in `.riel/runs/<slug>.md` (`riel-run/v1`), one question's evidence in
`.riel/shapings/<slug>.md` (`riel-shaping/v3`), and the order of several questions in
`.riel/project.md` (`riel-project/v1`). There is no converter and no compatibility with
the v1 tools (`riel_plan`, `riel_seam`).

The user-facing introduction — what Riel is for, the formats and the reason behind each
part — is the repository's root `README.md`. This document is about the package itself.

## The surface is tools, never a command line

Seven typed tools over one engine (stdlib, no dependencies, shipped inside the package):

| Tool | Verbs |
|---|---|
| `riel_guide` | the prose, by topic and section |
| `riel_project` | `new` · `validate` · `status` |
| `riel_shape` | `new` · `validate` |
| `riel_run` | `new` · `validate` · `activate` · `rebase` · `status` · `list` · `slice` |
| `riel_note` | the only writer of State; runs gates |
| `riel_clean` | wipe `.riel/`, optionally archiving first |
| `riel_check` | dense-register and graph checks on any Markdown |

No tool takes argv. The `tool` field in a response is provenance — which tool answered —
and `verb` when the tool carries one; neither is an interface. Every response, positive
or negative, speaks the same six-key envelope:

```
tool, worktree, exit_code, passed, stdout, stderr
```

The format has one owner. `schemas.py` derives its properties from `engine/params.py`,
the handler's flag map derives from the same declaration, and so does the engine's
argparse. Two structural rules follow from that: an engine-owned parameter (`exit_code`)
never reaches the model, and a repeatable parameter reaches it as ONE array (`claims`).

## The model

- **Riel explains and validates; it never authors.** `project new`, `shape new` and
  `run new` PRINT their skeletons — the editor is the writing path. A project system, an
  MCP server, an API or a copy-paste writes the bytes; `validate` decides whether they
  are well formed. There is no fetch: transport is the producer's business, and the
  Markdown is the contract.
- **An unfilled skeleton is refused.** `run validate`/`activate` and `shape validate`
  reject any `{{placeholder}}` left in the artifact and name every field still to author.
  Placeholders inside HTML comments are documentation and do not count.
- **One shaping = one question and one answer.** Marker
  `<!-- riel-shaping/v3 id:shp_xxxxxxxx -->`. The uid is the identity (it survives a
  rename), the slug the location, the sha256 the revision. Seven sections in order:
  `Question` (ONE line, ONE `?`) · `Answer` (ONE line, no `?`, with `— supported by F#`
  or `— decided by: owner`) · `Findings` (`### F#` dossiers with body, source and an
  optional `#### Diagram`) · `Facts` · `Not wanted` (what we do NOT want, with the
  reason) · `What we want` (We need · Claim seeds · Scope) · `Open` LAST (the residue,
  each item with its cheapest settling test). The Basis freezes heading + source +
  confidence, never the body.
- **The frame precedes the execution.** The Definition runs Objective · Context ·
  Deliverable · Constraints · DO NOT · Phases: the target and the boundary are
  declared before the how. `Objective` is the result in one sentence; `Deliverable`
  is the concrete artifacts (paths, files) a reviewer can point at.
- **Phases are sections.** `## Phases` carries the general DAG in its preamble (mermaid
  between phases, an arrow list `- F1 → F2`, or the authored heading order), then one
  `### F#: <title>` per phase with its steps and its OWN `#### Claims`, `#### Gates` and
  `#### Deliverable`. Membership is STRUCTURAL: no `— phase:` suffix, no run-global gate.
  Steps number PER PHASE (`F1S1`, `F1S2`…), so inserting a step never renumbers another
  phase's anchors and `§F1#2` is stable. `Constraints` and `DO NOT` are global — one run
  is one shaping is one PR.
- **A run executes one shaping.** The Definition declares it under `### Shaping` (path or
  uid). `activate` validates that shaping, resolves every `shaping:F#` anchor against it,
  freezes the cited findings into `### Basis`, and records path + uid + sha256 in
  Metadata. Editing the bound shaping marks the run stale (exit 3) and asks for `rebase`;
  editing a sibling shaping does not.
- **A project orders shapings.** `.riel/project.md` with `## Objective` and `## Graph`
  (`S#` nodes that are shapings; a linear list or a branching mermaid flowchart).
  `project status` DERIVES progress: a node is done when a contract bound to that
  shaping is done. It writes no state and has no gates of its own.
- **Executed in place.** A contract is authored at `.riel/runs/<slug>.md` and stays
  there — no live file, no archive move, never pruned. SEVERAL may be active at once
  (parallel tracks in one worktree); `run=<slug>` selects one and is required when
  several match. `run list` enumerates them all with their state.
- **`riel_note` runs gates.** `gates: ["G1"], command: "<real command>", covering:
  "<scope>", claims: ["P1"]` — the ENGINE executes the command, captures the real exit
  code and records `E#` evidence. Nobody passes an exit code.
- **`run status`** answers ONE JSON object with the run's state, including the bound
  shaping (`path`, `id`, `sha256`).
- **`riel_clean`** removes EVERYTHING inside `.riel/` (run, project, shapings, runs,
  backups, any other file); only the lock and `archive/` stay. Archiving is opt-in:
  `archive=true` copies the tree into `.riel/archive/<ts>/`, verifies every sha256
  BEFORE removing anything, and that copy survives the wipe. Without it there is no
  way back — `.riel/` is gitignored.
- **No old versions.** Only `riel-shaping/v3` is read; a v1/v2 shaping is refused, not
  converted, and a loose `.riel/shaping.md` is not read at all. A run without
  `definition_sha256` is stale. Upgrading means re-authoring, not migrating.

## The prose ships here, behind one door, by sections

`guide/` holds the topics the index lists: `project`, `run`, `shaping`, `delegate`,
`tools`. With no argument `riel_guide()` returns the index; with `topic` it returns that
guide's **section outline**; with `section` just that slice; with `full=true` the whole
body.

The `riel` prompt section publishes what the tool catalogue cannot — that the prose
exists — plus the worktree's state. **No skill is registered**: a plugin skill never
enters `<available_skills>`, so registering one would create two doors and two ways for
the prose to fall out of sync.

## Install (user)

```bash
hermes plugins install "git@github.com:alvarolizama/riel.git#hermes_plugin/riel" --enable
hermes plugins update riel
```

The installer clones the repo and **moves only this subdirectory** to
`~/.hermes/plugins/riel` — the checkout does not survive. That is why the package is
self-contained: `guide/`, `engine/` and `templates/` travel inside and **are the source**.
There is no copy and no build step. Edit them here; `tests/test_plugin_vendor.py`
verifies that no duplicate tree reappears and that manifest, README and engine all say
`4.0.0`.

## Install (development)

```bash
HERMES_HOME=~/.hermes/profiles/coder hermes plugins install \
  "file://$(pwd)#hermes_plugin/riel" --enable
```

Plugins are **per profile** (`$HERMES_HOME/plugins/`) and an install is always a copy of
a commit: there is no symlink, not even in development.

## How the worktree resolves

The engine resolves `.riel/` from the explicit parameter, never from the process cwd.
Each call resolves the root in this order:

1. the tool's `worktree` argument (an explicit path),
2. the session's registered cwd (the same one the `terminal` tool uses),
3. `TERMINAL_CWD`,
4. the process cwd (only outside a multiplexed gateway).

It then runs the engine **in the same process** via
`run_verb(argv, worktree=…, out=…, err=…)`: explicit text sinks per call (never a global
redirect), no shared chdir between concurrent sessions. Only when the engine cannot load
in that interpreter does it fall back to a subprocess with `--worktree <worktree>` — and
a failed load does not poison the loader: the next call retries it.

## Desktop half — a chip in the status bar

`desktop/plugin.js` registers one chip in `statusBar.right`, and it is the only one:

- **It exists only when there is a run**: an active or draft `.riel/runs/<slug>.md` in the
  focused worktree. With no run, the status bar shows nothing.
- **At rest**: `Riel` — the run exists; one click opens a modal with the run rendered
  (Streamdown draws the sections and the mermaid graph).
- **During a turn**: `Riel ● <tool>` — the dot pulses in the accent colour and names the
  live tool of the focused chat (e.g. `Riel ● riel_note`).

Detailed run state does not live in the bar: the model re-reads it with `riel_run status`
and the gate enforces it. The two facts arrive by different paths:

| Fact | Path |
|---|---|
| Run | `host.state.cwd` / `session.info` → `GET /api/plugins/riel/run?worktree=<cwd>` (on open, on focus change, and immediately when a tool completes) |
| Execution | `host.onEvent('tool.start' \| 'tool.complete')` — the gateway tap — plus `host.state.busy` for the turn in flight |

`GET /run` answers `{present, worktree, markdown, status}`: the verbatim markdown
(bounded, symlink-resolved) for the modal, and the `run status` JSON object for state.
The old routes (`/ledger`, `/contract`) no longer exist, and `/health` does not leak the
gateway's cwd. Every route is a sync `def`: FastAPI runs them in its threadpool, so a
bounded engine call never blocks the event loop.

The switches remain available as ⌘K commands: `Riel: turn the gate on/off` and
`… the prompt block`.

## The gate (`pre_verify`)

While an ACTIVE run exists in the edited worktree, the turn does not close with claims
or gates pending: the plugin queries `run status` (in-process, through the same safe path
as the tools) and returns `{"action": "continue", …}`.

| Limit | How |
|---|---|
| Opt-in per worktree | no `.riel/runs/<slug>.md` above the edited files → no nudge; an old state file alone does NOT enable the gate |
| Active runs only | a run written but not `activate`d is the agent's business, not the gate's |
| One nudge per turn | `plugins.entries.riel.settings.gate_attempts` (int, 0–10, default 1); above that Hermes caps at `agent.max_verify_nudges` (3) |
| Never blocks | any failure (no run, no engine, unreadable state) returns `None` and the turn closes |
| No subprocess | the gate uses the in-process engine (safe loader), never a subprocess fallback |
| Switchable | `plugins.entries.riel.settings.gate: false` |

Which worktree is judged: first the one containing the **edited files** (a turn may edit
another repo), and if none of them is a worktree with a run, the session's cwd.

## Verification

```bash
make test          # includes tests/test_plugin_*.py (package + handlers + chip)
make lint          # byte-compile engine, package, scripts and tests
make validate      # dense-register + graph + mmdc over README, specs, guides, templates
hermes plugins validate hermes_plugin/riel   # the same discovery/registration Hermes uses
```
