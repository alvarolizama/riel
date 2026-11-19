---
topic: shaping
trigger: "Use when research must precede execution: .riel/shapings/<slug>.md asks ONE question and answers it with sourced findings, and a run binds exactly one shaping."
version: 3.0.0
---
# shaping — One question, one answer

A shaping is a separate editable research artifact: `.riel/shapings/<slug>.md`.
It asks ONE question and answers it. It is not a Definition, contains no
execution cursor and never records task progress. A task whose decision is
already settled skips it.

Several shapings coexist: one per question, one per track of a project. A run
binds exactly one of them, and a PR delivers that one answer.

## Format

`riel-shaping/v3`: the title `# Shaping: <name>`, the marker carrying its uid
`<!-- riel-shaping/v3 id:shp_xxxxxxxx -->`, then seven sections in this order:

| section | role |
|---|---|
| `## Question` | the one question, ONE line, ONE `?` |
| `## Answer` | the resolution, ONE line, no `?`, backed by a finding or the owner |
| `## Findings` | what was learned: `### F#` dossiers, each with its source |
| `## Facts` | what the design must respect (the Contract's Constraints) |
| `## Not wanted` | what we do NOT want, and why it lost (`A#` with verdict) |
| `## What we want` | the commission: We need · Claim seeds · Scope |
| `## Open` | LAST — the residue: what could not be closed, with its cheapest test |

Open goes last because it is what remains after the answer, the evidence and
the commission. The order is enforced.

The uid is the shaping's identity: it survives a rename, and a run binds by
uid + path + sha256. `shape new` mints a fresh one when it renders the skeleton;
a project system may supply its own with `params=["id=shp_…"]`. Two files
sharing one uid are refused: an id identifies one question.

## Authoring guard

`shape validate` REFUSES a shaping that still carries `{{placeholder}}` text and
names every field left to author. A skeleton is not research: fill it, or no run
can bind to it. Placeholders inside HTML comments are documentation and do not
count.

## Question and Answer

`## Question` is ONE line with ONE question mark. Two questions are two
shapings: a run that answers two questions cannot be delivered as one PR.

`## Answer` is ONE line, with no `?` — a question is not an answer — and it must
cite its backing: `— supported by F1` (a finding that exists) or
`— decided by: owner`. An answer with neither is an opinion, and validation
refuses it. Whether the answer truly addresses the question is a review
judgment, not something a validator can decide.

The Answer is the resolution, not the deliverable. What must be built goes in
`## What we want`.

## Findings as dossiers

Each finding is a `### F#` subsection: the heading is the citable claim on ONE
line, the body is its support, and `— source: …, confidence …` names the
evidence. A finding may carry its own `#### Diagram`.

    ### F1: one file holds the Definition and the State
    The cut is `## Metadata`; everything above it is authored, everything below
    is engine-written.
    — source: repo@2b1979a:hermes_plugin/riel/engine/run.py:442-452#_split_definition, confidence high

    #### Diagram
    ```mermaid
    flowchart TD
      A["run.md"] --> B["Definition"]
      A --> C["State + Evidence"]
    ```

The frozen Basis copies the heading, the source and the confidence — never the
body or the diagram, so a delegated slice stays small.

Facts derive constraints from findings and do not create competing `F#` ids.
HTML comments are documentation, never findings. Only dossiers are read.

Pin repository evidence to its observed commit and symbol:
`repo@057dc31:path/to/file.py:694-718#symbol`. The commit fixes what was
investigated; path and symbol make later drift findable. Before activation,
re-read the reference against current HEAD. A passed benchmark with command and
output belongs here. An execution assertion about the future implementation
belongs in the Contract's Claims instead.

## Not wanted, and what stays open

`## Not wanted` records kept, discarded and deferred options with reasons. Only
the surviving rationale reaches the Contract's `### Why`; the rejected ones stay
here so the next session does not re-litigate them.

`## Open` is the residue. Each item names the cheapest test that settles it, on
the SAME line (`— settled by:`). The handoff must resolve it, transfer it to the
Contract's Open with `riel_note`, or put it out of scope — the engine does not
transfer it automatically, so a question can disappear if the author skips it.

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

## Handoff into the Contract

`## Answer` feeds the Objective's rationale (`### Why`). `## What we want`
supplies the three things the Definition needs: `We need` seeds the Objective,
`Claim seeds` become the pre-registered `P#`, and `Scope` becomes Constraints
and DO NOT. Authoring the exact Definition remains deliberate: no generator
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

## No legacy support

Only `riel-shaping/v3` is read. A v1 or v2 shaping is refused, not converted:
there is no converter and no migration path. A loose `.riel/shaping.md` is not
read at all — shapings live in `.riel/shapings/`. Re-author the source in v3: the
Answer, `Not wanted`, `What we want` and the dossier findings are authored
decisions, not something a tool can invent from old prose.
