---
topic: shaping
trigger: "Use when research must precede execution: .riel/shapings/<slug>.md answers ONE question with sourced findings, and a run binds exactly one shaping."
version: 2.0.0
---
# shaping — One question's evidence

A shaping is a separate editable research artifact: `.riel/shapings/<slug>.md`.
It answers ONE question — what we know and how we know it. It is not a Definition,
contains no execution cursor and never records task progress. A task whose
decision is settled skips it.

Several shapings coexist: one per question, one per track of a project. A run
binds exactly one of them, and a PR delivers that one answer.

## Format

`riel-shaping/v2`: the title `# Shaping: <name>`, then the marker carrying its
uid `<!-- riel-shaping/v2 id:shp_xxxxxxxx -->`, then Question, Findings, Facts,
optional Diagrams, Alternatives bounced, Open and Verdict.

The uid is the shaping's identity: it survives a rename, and a run binds by
uid + path + sha256. `shape new` mints a fresh one when it renders the skeleton;
a project system may supply its own with `params=["id=shp_…"]`. Two files
sharing one uid are refused: an id identifies one question.

## One question, enforced

`## Question` is ONE line with ONE question mark. Two questions are two
shapings, and the validator refuses them: a run that answers two questions
cannot be delivered as one PR. Everything below exists to close that line.

## Findings and code references

Every citable finding is one `F#` line under Findings with source and
confidence, on ONE physical line. Facts derive constraints from findings and do
not create competing `F#` identifiers. HTML comments are documentation, never
findings; labels in Mermaid comments are never execution nodes.

Pin repository evidence to its observed commit and symbol:

`repo@057dc31:hermes_plugin/riel/engine/run.py:694-718#contract_to_todo_items`

The commit fixes what was investigated; path and symbol make later drift
findable. Before activation, re-read the reference against current HEAD. A
passed benchmark with command and output belongs here. An execution assertion
about the future implementation belongs in the run's Claims instead.

## Decisions and open questions

Alternatives record kept, discarded and deferred options with reasons. Only the
winning decision survives into the run's Why; the rejected ones remain here.

Each Open item has the cheapest test that settles it. Activation must resolve
it, explicitly transfer it to the run's Open, or put it out of scope. A research
question cannot disappear during the handoff.

## Authoring outside Riel

Riel explains the format and validates it; it never authors a shaping.
`riel_shape(verb="new")` RENDERS the skeleton to stdout. The writing path is an
editor, a project system, an MCP server, an API or a copy-paste:

1. Render or copy the skeleton; keep the marker and its uid.
2. Write the bytes to `.riel/shapings/<slug>.md` in the target worktree.
3. `riel_shape(verb="validate", file=".riel/shapings/<slug>.md")`.
4. Declare it in the run under `### Shaping`, then activate.

The bytes are the contract: a shaping produced anywhere is the same Markdown,
so any transport that preserves them works. Riel does not fetch, and nothing
downloaded activates itself.

## Handoff into run

The Verdict supplies one Objective, the kept decision and rationale, claim
seeds and scope. Authoring the exact Definition remains deliberate: no generator
invents nodes, paths or gates from prose.

The run declares its shaping under `## Context`:

    ### Shaping
    - shaping: .riel/shapings/storage.md

A uid works too (`- shaping: shp_xxxxxxxx`). At activation Riel validates that
shaping, resolves all `shaping:F#` anchors against it, copies the referenced
findings into the run's frozen Basis, and records path, uid and sha256 in
Metadata. Delegated slices receive those frozen findings rather than a
reference to the parent's mutable workspace.

Editing the bound shaping marks the run stale and requires rebase. Editing a
sibling shaping does not: it is another track's evidence.

## The loose legacy file

A pre-v2 `.riel/shaping.md` is still read, so an active run keeps working after
an upgrade. `activate` and `rebase` migrate it into `.riel/shapings/<slug>.md`,
mint its uid, rotate the original to a timestamped `.bak.md` and rebind the run
in the same transaction. A shaping that answers two questions refuses
migration: split it first. A different shaping already holding the target slug
also refuses: rename one of them.
