# Run: {{title}}

<!-- riel-run/v1 -->

## Objective
<!-- ONE sentence: the RESULT "done" produces. Not the artifacts — those go in
     ## Deliverable. Rationale belongs in ### Why. -->

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

## Deliverable
<!-- The CONCRETE artifacts that exist when the whole run is done: paths,
     files, endpoints. The Objective says what result they add up to; this
     says what a reviewer can point at. -->

{{deliverable}}

## Constraints
<!-- Hard rules the execution may not break. Global: they bind every phase. -->
- {{constraint}}

## DO NOT
<!-- Scope enforcement for the whole PR. Global: no phase may relax it.
     Declared BEFORE the phases so the boundary is known before the how. -->
- {{do_not}}

## Phases
<!-- The general DAG goes HERE, before the first phase: a ```mermaid flowchart
     between phases (decisions `{...}` with labeled outgoing edges, loops with
     a `< 3` counter guard), or an arrow list `- F1 → F2 → F3`. With neither,
     the authored order of the ### headings is the execution order.
     Then ONE `### F#: <title>` per phase. Its steps are bullets STARTING with a
     closed verb (READ/EDIT/CREATE/RUN/VERIFY/ASK) — write the verb, NOT an id:
     the engine numbers them PER PHASE as F1S1, F1S2… in authored order, so
     inserting a step never renumbers another phase's anchors.
     Each phase carries its OWN #### Claims, #### Gates and #### Deliverable.
     Gate membership is structural: there is no `— phase:` suffix. -->

### F1: {{phase}}
- READ {{step}}
- EDIT {{target}}
- RUN {{gate_command}}

#### Claims
<!-- What must be true when this phase is done. Anchors: `§F1#2` (this phase's
     step 2), `shaping:F#` (a frozen finding), or another `## Section#n`. -->
- P1: {{claim}} — anchor: {{anchor}}

#### Gates
<!-- The commands that prove this phase. `note --gate G1` runs and records. -->
- G1: {{gate}}

#### Deliverable
<!-- What exists when THIS phase is done — its own step of the staircase. -->
- {{phase_deliverable}}

### F2: {{next_phase}}
- VERIFY {{verify_command}}

#### Claims
- P2: {{next_claim}} — anchor: §F2#1

#### Gates
- G2: {{next_gate}}

#### Deliverable
- {{next_phase_deliverable}}
