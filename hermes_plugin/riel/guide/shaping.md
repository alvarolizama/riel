---
topic: shaping
trigger: "Use when research must precede execution: an optional .riel/shaping.md collects sourced findings, alternatives and open questions before it is frozen into a run."
version: 1.1.0
---
# shaping — Evidence before the Plan

Shaping is a separate editable research artifact: `.riel/shaping.md`. It answers
what we know and how we know it. It is not a Plan, contains no execution cursor
and never records task progress. A task whose decision is settled skips it.

The final format is `riel-shaping/v1`: Question, Findings, Facts, optional
Diagrams, Alternatives bounced, Open and Verdict.

## Findings and code references

Every citable finding is one `F#` line under Findings with source and
confidence. Facts derive constraints from findings and do not create competing
`F#` identifiers. HTML comments are documentation, never findings; labels in
Mermaid comments are never execution nodes.

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

## Remote shaping

Remote and local shaping use the same bytes and format. An exchange returns
`url`, `sha256` and `bytes`; the Markdown body stays outside agent context.
Materialize with `riel_shape(verb="fetch", url=…, out=".riel/shaping.md", sha256=…)`.

SHA-256 is mandatory, transport is bounded and TLS-verified, writes are atomic.
Downloading never executes or activates anything. Validate after download.
The frozen bytes remain local throughout the run; there is no network at seams.

## Handoff into run

The Verdict supplies one Objective, the kept decision and rationale, claim
seeds and scope. Authoring the exact Plan remains deliberate: no generator
invents nodes, paths or gates from prose.

At activation Riel hashes shaping, resolves all `shaping:F#` anchors and embeds
the referenced findings in the run's Basis. Delegated slices receive those
frozen findings rather than a reference to the parent's mutable workspace.
Changing shaping later marks the old connection stale and requires rebase.
