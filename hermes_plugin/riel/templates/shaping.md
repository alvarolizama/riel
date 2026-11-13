# Shaping: {{name}}

<!-- riel-shaping/v1 -->

## Question
{{question}}
<!-- ONE sentence: the decision this shaping closes. If it takes two, you
     have two shapings. Everything below exists to close this line. -->

## Findings
<!-- What was actually learned, and how we know it. One F# per line, ids
     unique, each with its source; confidence is optional but a finding
     that a run activates gets copied with it. A finding without a source
     is a hypothesis: `shape` fails on it and nothing downstream should
     rest on it.
       - F1: <finding> — source: path/to/file.py:120, confidence high
       - F2: <finding> — source: https://… (2026-01-15), confidence med -->
- F1: {{finding}} — source: {{path:line | URL + date | command}}, confidence {{high|med|low}}

## Facts
<!-- What the design must RESPECT: established constraints, invariants,
     conventions of the repo, things that cannot be changed. Not opinions. -->
- {{fact}}

## Diagrams
<!-- OPTIONAL — delete it when the prose already carries the context. The
     shape of the system as it IS and as it WOULD BE. Mermaid. NOT the
     execution DAG — that one is the run's ## Graph. -->

## Alternatives bounced
<!-- The ideas that were considered and why they lost. This is the part a
     run cannot carry: its ### Why keeps only the surviving rationale.
     One A# per line, with the verdict spelled out. -->
- A1: {{option}} — pro: {{pro}} / contra: {{contra}} — verdict: {{kept|discarded}}

## Open
<!-- Questions still unsettled. Each names the CHEAPEST test that would
     settle it — these migrate to the run's ## Open when it activates. -->
- Q1: {{question}} — settled by: {{cheapest refuting test}}

## Verdict (→ run)
<!-- The seed of the run. The Objective line, the decision with its
     because, the claims that will be pre-registered (with the finding
     that supports each), and the scope. Never a summary of the sections
     above: the decision, in the closed form the run needs. -->
- We need {{what done produces}}
- Decision: {{the path chosen}} — because {{why this and not another}}
- Claim seeds: {{what will be true}} — supported by {{F#}}
- Scope: in {{in}} · out {{out}}
