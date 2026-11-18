# Run: {{title}}

<!-- riel-run/v1 -->

## Objective
<!-- ONE sentence: what "done" produces. Rationale belongs in ### Why. -->

{{objective}}

## Context

### Why
<!-- Why this objective and not another. This is the surviving rationale,
     not a summary: the alternatives that lost live in the shaping. -->

{{why}}

### Context keywords
<!-- One term per line, optional source after the arrow. These are the
     context-fetch keywords: what to pull from memory before executing. -->
- {{term}} → {{source}}

### Shaping
<!-- The ONE shaping this run executes: a path under .riel/shapings/ or its
     uid (shp_xxxxxxxx). One run = one shaping = one question = one PR.
     Delete this subsection only when no claim anchors into a shaping. -->
- shaping: {{shaping}}

## Constraints
<!-- Hard rules the execution may not break. -->
- {{constraint}}

## Claims
<!-- What must be true for the run to be done. One P# per line; the anchor
     is optional but a claim that cannot be re-read at a seam is a WARN:
     `— anchor: §Section#n` | a graph node id | `shaping:F#`. -->
- P1: {{claim}} — anchor: {{anchor}}

## Graph
<!-- EITHER a ```mermaid flowchart (phases F#, steps with closed verbs
     READ/EDIT/CREATE/RUN/VERIFY/ASK, decisions `{...}` with labeled
     outgoing edges, loops with a `< 3` counter guard) OR the plain list
     register below. A phase's last step is its gate (RUN or VERIFY). -->
- F1: {{phase}}
  - READ {{step}}
  - RUN {{gate_command}}

## Gates
<!-- One G# per line; `— phase: F#` maps the gate onto a graph phase (a
     gate with no phase applies to the whole run). `note --gate G#` runs
     the command and stores the evidence. -->
- G1: {{gate}} — phase: F1

## Deliverable
<!-- What exists when the run is done. -->

{{deliverable}}

## DO NOT
<!-- Scope enforcement: what this run must not touch. -->
- {{do_not}}
