# Shaping: {{name}}

<!-- riel-shaping/v3 id:{{id}} -->

## Question
{{question}}
<!-- ONE line with ONE question mark: the single question this shaping closes.
     Two questions are two shapings — split them, because a run binds one
     shaping and a PR delivers one answer. The uid in the marker identifies the
     shaping across renames: a run binds it by id, path and sha256. -->

## Answer
{{answer}} — because {{why}} — supported by {{F#}}
<!-- ONE line, no '?': the resolution of the Question. Cite a finding
     (`— supported by F1`) or the owner (`— decided by: owner`); an answer
     without either is an opinion. This line feeds the Contract's ### Why.
     It is NOT the deliverable: what must be built goes in What we want. -->

## Findings
<!-- What was actually learned, and how we know it. One dossier per finding:
     the heading is the citable claim (ONE line), the body is its support, and
     a finding may carry its own #### Diagram. Ids unique; a finding without a
     source is a hypothesis and `shape validate` fails on it.
     The Basis freezes heading + source + confidence — never the body. -->

### F1: {{finding}}
{{evidence}}
— source: {{repo@commit:path:lines#symbol | path:line | URL + date | command}}, confidence {{high|med|low}}

#### Diagram
<!-- OPTIONAL — delete it when the prose already carries the point. This
     finding's own diagram, NOT the execution DAG (that one is the Contract's
     ## Graph). -->

## Facts
<!-- What the design must RESPECT: established constraints, invariants,
     conventions of the repo, things that cannot be changed. Derived from the
     findings, never new F# ids. These become the Contract's ## Constraints. -->
- {{fact}}

## Not wanted
<!-- What we do NOT want, and why it lost. One A# per line with the verdict
     spelled out: kept | discarded: <reason> | deferred: <reason>. The Contract
     keeps only the surviving rationale in ### Why; the rejected options stay
     here so the next session does not re-litigate them. -->
- A1: {{option}} — pro: {{pro}} / contra: {{contra}} — verdict: discarded: {{reason}}

## What we want
<!-- The commission to the executor: the three things the Contract needs.
     Not the answer again — the answer is above. We need seeds the Objective,
     Claim seeds become the pre-registered P# (each supported by a finding),
     and Scope becomes Constraints and DO NOT. -->
- We need {{what done produces}}
- Claim seeds: {{what will be true}} — supported by {{F#}}
- Scope: in {{in}} · out {{out}}

## Open
<!-- LAST: the residue. What this shaping could NOT close, each with the
     CHEAPEST test that would settle it, on the SAME line. These transfer to
     the Contract's ## Open at the handoff. If nothing is open, say so here
     instead of deleting the section. -->
- Q1: {{open_question}} — settled by: {{cheapest refuting test}}
