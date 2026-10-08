# Spec 8 — The Hermes plugin package (`.riel/` is not in it)

Status: draft v2 · Riel — plugin-first
Applies to `hermes_plugin/riel/`, the one artifact a Hermes user installs.

The **package is the product**. Everything the agent needs to run Riel — the
prose, the engine that writes the formats, the tools that reach it, the gate
that holds the line and the desktop chip — ships inside one directory that
installs as a copy of a commit and updates the same way. Nothing about it is
configured on disk outside the package: no skills directory, no `external_dirs`,
no symlink, nothing on `PATH`.

## What the package contains

| Path | What it is | Source of truth |
|---|---|---|
| `plugin.yaml` | the manifest: tools, hooks, the switch schema | itself |
| `__init__.py` | `register()`: tools, the prompt section, `/riel`, the gate | itself |
| `schemas.py` | the tool schemas — what the model reads to choose | itself |
| `tools.py` | the handlers: named parameters → the engine's argv | itself |
| `guide.py` | the prose's only door: index, one guide, one section | the `guide/` files |
| `section.py` | the `riel` prompt section (the door + worktree state) | itself |
| `settings.py` | per-call reads/writes of `plugins.entries.riel.settings.*` | itself |
| `commands.py` | the `/riel` slash command | itself |
| `hooks.py` | `pre_verify`, the checkpoint gate | itself |
| `dashboard/` | the chip's backend routes (`/api/plugins/riel/*`) | itself |
| `desktop/plugin.js` | the statusbar chip, the switches and the ⌘K commands | itself |
| `guide/` | the prose, one file per topic — **the source**, edited here | itself |
| `engine/` | `run.py` — the machine behind the tools, sole writer of the formats — **the source** | itself |
| `templates/` | the packet and shaping templates — **the source** | itself |

**One tree, no copies.** `guide/`, `engine/` and `templates/` are the package's
own sources, edited in place: there is no build step and nothing to keep in sync.
`tests/test_plugin_vendor.py` asserts each part exists inside the package and that
no same-named directory reappears at the repo root — the duplication cannot come
back by accident.

## The prose: topics, one door

The prose is six guides, each a markdown file with frontmatter:

```yaml
---
topic: contract
trigger: "Use when authoring mermaid verb-graph contracts …"
version: 3.7.1
---
```

| File | Topic | Holds |
|---|---|---|
| `guide/protocol.md` | `protocol` | the conversation protocol: grammar, persona, minimal surface |
| `guide/ledger.md` | `ledger` | the state: Goal/Claims/Core/Verified/Open/Next (Spec 1) |
| `guide/contract.md` | `contract` | mermaid as contract: closed verbs, funnel, anchors (Spec 2) |
| `guide/briefs.md` | `briefs` | the packets a delegate receives |
| `guide/delegate.md` | `delegate` | the delegation router |
| `guide/tools.md` | `tools` | the tool surface and the engine's rules |

**One door**: `riel_guide` reads them.

| Call | Answers |
|---|---|
| `riel_guide()` | the index — each topic with its trigger, read from the files |
| `riel_guide(topic="contract")` | that guide's body, frontmatter stripped |
| `riel_guide(topic="ledger", section="Pitfalls")` | just that `## section` |

The section match is a case-insensitive substring, so `section="Claim anchors"`
also finds `## Claim anchors (Spec 2 + Spec 7)`. An unknown topic or section is
a **structured error** carrying what does exist (`topics`, `sections`) and a
hint — never an exception and never a silence.

**Nothing registers a Hermes skill.** `ctx.register_skill` is not called: a
plugin skill never enters `<available_skills>`, so it would need the prompt
section to be found anyway — and then there would be two doors and two ways for
the prose to drift. `tests/test_plugin_vendor.py` asserts the package contains no
`register_skill` call, and `tests/test_plugin_guide.py` pins the door.

The files keep their identity: the repo's `guide/<topic>.md` and the package's
copy are the same bytes, and the H1 opens with the topic (`# ledger — …`) — the
file name, the frontmatter `topic:` and the title agree.
A citation in prose uses the call (`riel_guide(topic="ledger")`); a mermaid
label uses the bare topic (`ledger`), because a graph label is not a place for a
tool signature.

## The `riel` prompt section

`ctx.register_system_prompt_section("riel", section.render, position="after_memory",
max_chars=3000)` — registered always, rendered once per session and frozen by
Hermes. It answers the one question no tool can: *that the prose exists at all*.
The tools live in the model's catalog; the topics do not.

| Part | Content | Budget |
|---|---|---|
| head | what Riel is + that the prose is read through `riel_guide` | ≤ 220 |
| index | ONE line: the topics that exist right now + the two call shapes | ~240 |
| state | the worktree's ledger: goal · phase · next · claims/verified/open | only if it fits whole |
| door | the twelve tools by name; no command line, no `PATH` | ~250 |
| note | the operator's `harness_note`, appended last, exactly as written | ≤ 400 |

Cut rules, all silent-failure-proof: the topic list comes from `guide/*.md` at
render time, so the index cannot drift from the prose and there is no "… N more"
declaration to get wrong; the state line joins only when it fits WHOLE; the note
yields before the door does; and if not even head + index + door fit, the
section renders `""` — Hermes discards empty sections, and empty beats a lie.
With `context` off, the section is empty.

The state line runs the engine's `status` with a 3s cap. A slow or missing
engine is silence, never an error inside the prompt.

`harness_note` is where adaptation lives (one line per profile), never a
per-model table: the structure carries the rest (one action per line, capped
descriptions, tools named in English).

## The switches

Three groups, all in `plugins.entries.riel.settings.*`, all read **per call**
(the gate on every turn, the section once per session, the chip whenever it
asks) and all fail-open — an unreadable config means ON:

| Group | Off means | Enforced by |
|---|---|---|
| `gate` | `pre_verify` stands down | the hook reads it per turn |
| `tools` | the twelve tools leave the model's surface **and** refuse to run | a non-cached `check_fn` hides them; the handler guard refuses before the engine |
| `context` | the prompt section renders `""` | the render reads it per session |

**Semantics the UI must state:** a switch written now is obeyed by the NEXT
session — a running session keeps the prompt and the tool list it started with.
The handler guard is the only immediate half, and it is a refusal. The chip, the
⌘K commands and `/riel status` say exactly that; nothing claims the running turn
changed.

Writes go through Hermes' own writer (`hermes_cli.plugins_state.save_plugin_setting`),
never a hand-edited `config.yaml`, so the cross-process lock and the
managed-install refusals apply.

## The interface: tools, never a command line

The engine (`engine/run.py`, one stdlib file) does the mechanical work and is the
sole writer of the formats. It is **implementation**: no tool takes argv, no flag
travels as data, and nothing in the package is meant to be typed into a shell.
The twelve tools are the surface:

| Tool | Verb behind it |
|---|---|
| `riel_guide` | reads the package's prose (no engine call) |
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
| `riel_check` | dense markers + graph digest on one file (+ `mermaid=true`: the parser check) |

Every tool returns one envelope — `{tool, worktree, exit_code, passed, stdout,
stderr}` plus its own keys (`verb` when the tool takes one) — so a caller, a test
or the chip can read the result the same way. `riel_guide` puts the prose in
`stdout` (and `content`) and needs no worktree state: it reads the package, not
the task. `tool` is **provenance** (which tool answered), not an interface — there
is no command-shaped field anywhere in the envelope.

## What the package is not

- It is not `.riel/`. The ledger, the contract and the shaping are the task's
  local state, in the worktree, gitignored — the package never carries them.
- It is not a service. Nothing listens; the chip's backend runs inside the
  gateway and reads only `<worktree>/.riel/*`.
- It registers **no skills**: the prose reaches the model through `riel_guide`
  and the prompt section, and through nothing else.
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
- The prose itself: `guide/*.md`, read through `riel_guide`
