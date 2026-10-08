# Spec 8 — The Hermes plugin package (`.riel/` is not in it)

Status: draft v1 · Riel — plugin-first
Applies to `hermes_plugin/riel/`, the one artifact a Hermes user installs.

The **package is the product**. Everything the agent needs to run Riel — the
six skills, the engine that writes the formats, the tools that reach it, the
gate that holds the line and the desktop chip — ships inside one directory that
installs as a copy of a commit and updates the same way. Nothing about it is
configured on disk outside the package: no skills directory, no `external_dirs`,
no symlink, nothing on `PATH`.

## What the package contains

| Path | What it is | Source of truth |
|---|---|---|
| `plugin.yaml` | the manifest: tools, hooks, the switch schema | itself |
| `__init__.py` | `register()`: tools, skills, the prompt section, `/riel`, the gate | itself |
| `schemas.py` | the tool schemas — what the model reads to choose | itself |
| `tools.py` | the handlers: named parameters → the engine's argv | itself |
| `section.py` | the `riel` prompt section (index + worktree state + door) | itself |
| `settings.py` | per-call reads/writes of `plugins.entries.riel.settings.*` | itself |
| `commands.py` | the `/riel` slash command | itself |
| `hooks.py` | `pre_verify`, the checkpoint gate | itself |
| `dashboard/` | the chip's backend routes (`/api/plugins/riel/*`) | itself |
| `desktop/plugin.js` | the statusbar chip, the switches and the ⌘K commands | itself |
| `skills/` | the six skills, the engine and the templates | **the repo's `skills/`** |

`skills/` is a **build artifact**: `make plugin-skills` regenerates it from the
repo's `skills/` and `tests/test_plugin_vendor.py` pins every file by hash. It
is never edited in place — an edit there is invisible to the repo and dies on
the next build.

## The six skills: file identity vs load name

The plugin registers every bundled `skills/<slug>/SKILL.md` under its **short
name**, because the plugin namespace already carries the product:

| File (identity, paths, frontmatter `name:`) | Load name (what the agent calls) |
|---|---|
| `skills/riel-protocol/SKILL.md` | `riel:protocol` |
| `skills/riel-ledger/SKILL.md` | `riel:ledger` |
| `skills/riel-contract/SKILL.md` | `riel:contract` |
| `skills/riel-briefs/SKILL.md` | `riel:briefs` |
| `skills/riel-delegate/SKILL.md` | `riel:delegate` |
| `skills/riel-cli/SKILL.md` | `riel:cli` |

The rule: a **path** and a frontmatter `name:` keep the file's identity; a
**citation in prose** and a load call use the short form. `riel:riel-ledger`
would repeat the namespace, and the prose has exactly one way to name a skill.

`tests/test_plugin_section.py` pins the mapping, and the prose is scanned for
the short form.

## The `riel` prompt section

`ctx.register_system_prompt_section("riel", section.render, position="after_memory",
max_chars=3000)` — registered always, rendered once per session and frozen by
Hermes. It answers the one question a plugin-registered skill cannot: *that the
prose exists at all*. (`register_skill` puts a body behind `skill_view()`, but a
plugin skill never enters `<available_skills>`, so nothing else would name it.)

Three parts are fixed and measured first, then two are filled by budget:

| Part | Content | Budget |
|---|---|---|
| head | what Riel is + how the prose loads (`skill_view("riel:<short>")`) | ≤ 220 |
| door | the tools are the door (`tool_search` reaches them); no command line, no `PATH` | ≤ 220 |
| note | the operator's `harness_note`, exactly as written | ≤ 400 |
| index | one line per bundled skill: `riel:<short>` + trigger, capped at 100 chars | until the budget ends |
| state | the worktree's ledger: goal · phase · next · claims/verified/open | only if it fits whole |

Cut rules, all silent-failure-proof: the room for the "… N more" declaration is
reserved *before* the lines are filled, so a truncated index says so; the state
line is dropped entire rather than halved; and a block with no room for even one
index line renders `""` — Hermes discards empty sections, and empty beats a lie.
With `context` off, or with nothing to say, the section is empty.

Budgets and the model-specific half: the section is where adaptation lives (one
`harness_note` per profile), never a per-model table. The structure carries the
rest: one action per line, capped descriptions, tools named in English.

The state line runs the engine's `status` with a 3s cap. A slow or missing
engine is silence, never an error inside the prompt.

## The switches

Three groups, all in `plugins.entries.riel.settings.*`, all read **per call**
(the gate on every turn, the section once per session, the chip whenever it
asks) and all fail-open — an unreadable config means ON:

| Group | Off means | Enforced by |
|---|---|---|
| `gate` | `pre_verify` stands down | the hook reads it per turn |
| `tools` | the eleven tools leave the model's surface **and** refuse to run | a non-cached `check_fn` hides them; the handler guard refuses before the engine |
| `context` | the prompt section renders `""` | the render reads it per session |

`harness_note` is not a switch: it is the operator's line, appended last.

**Semantics the UI must state:** a switch written now is obeyed by the NEXT
session — a running session keeps the prompt and the tool list it started with.
The handler guard is the only immediate half, and it is a refusal. The chip, the
⌘K commands and `/riel status` say exactly that; nothing claims the running turn
changed.

Writes go through Hermes' own writer (`hermes_cli.plugins_state.save_plugin_setting`),
never a hand-edited `config.yaml`, so the cross-process lock and the
managed-install refusals apply.

## The interface: tools, never a command line

The engine (`skills/riel-cli/scripts/rielctl`, stdlib only) does the mechanical
work and is the sole writer of the formats. It is **implementation**: no tool
takes argv, no flag travels as data, and nothing in the package is meant to be
typed into a shell. The eleven tools are the surface:

| Tool | Verb behind it |
|---|---|
| `riel_note` | write/update the ledger |
| `riel_seam` (+ `anchors`) | re-read the ledger, and each claim beside its support |
| `riel_resume` | post-gap bootstrap |
| `riel_todo` | the plan mirror |
| `riel_state` | the ledger's facts |
| `riel_context` | the contract's context index |
| `riel_brief` (new/validate/digest/slice) | contracts and packets |
| `riel_shaping` (new/validate) | the shaping (Spec 7) |
| `riel_clean` (ledger/all/purge) | archive `.riel/` state |
| `riel_fetch` | a remote contract, on disk |
| `riel_check` | dense markers + graph digest on one file |

Every tool returns one envelope — `{command, worktree, exit_code, passed,
stdout, stderr}` plus its own keys — so a caller, a test or the chip can read
the result the same way. `command` is **provenance** (which engine call produced
this), not an interface.

## What the package is not

- It is not `.riel/`. The ledger, the contract and the shaping are the task's
  local state, in the worktree, gitignored — the package never carries them.
- It is not a service. Nothing listens; the chip's backend runs inside the
  gateway and reads only `<worktree>/.riel/*`.
- It is not the whole framework without Hermes: a checkout with no plugin has
  the prose and the engine but no tool surface, and the prose says so.

## Install and update

A copy of a commit with provenance, never a symlink:

```bash
hermes plugins install "file:///path/to/riel#hermes_plugin/riel" --enable   # local checkout
hermes plugins install "git@github.com:alvarolizama/riel.git#hermes_plugin/riel" --enable
hermes plugins update riel                                                  # after new commits
```

Commit first: the installer clones a commit, so anything uncommitted does not
travel. The desktop half is opt-in in the app (Capabilities → Plugins → riel).

## Cross-references

- The ledger and the contract the tools write: `spec-ledger-format.md` (Spec 1),
  `spec-contract-format.md` (Spec 2)
- The shaping: `spec-shaping-format.md` (Spec 7)
- The plan mirror and the prompt section's state line: `spec-todo-hermes.md` (Spec 6)
- The prose the package ships: skills `riel:protocol`, `riel:ledger`,
  `riel:contract`, `riel:briefs`, `riel:delegate`, `riel:cli`
