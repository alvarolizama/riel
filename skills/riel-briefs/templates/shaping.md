# Shaping: {{name}}

## Question
{{question}}
<!-- ONE sentence: the decision this shaping closes. If it takes two, you have
     two shapings. Everything below exists to close this line. -->

## Findings
<!-- What was actually learned, and how we know it. One F# per line, each with
     its source and a confidence. A finding without a source is a hypothesis:
     `rielctl shaping validate` WARNs on it, and nothing downstream should
     rest on it.
       - F1: <finding> — source: path/to/file.py:120, confidence high
       - F2: <finding> — source: https://… (2026-01-15), confidence med
       - F3: <finding> — source: `make test` output, confidence low -->
- F1: {{finding}} — source: {{path:line | URL + date | command}}, confidence {{high|med|low}}

## Facts
<!-- What the design must RESPECT: established constraints, invariants,
     conventions of the repo, things that cannot be changed. Not opinions. -->
- {{fact}}

## Diagrams
<!-- OPTIONAL — delete it when the prose already carries the context. The shape
     of the system as it IS and as it WOULD BE, so whoever writes the contract
     sees where the change lands. Mermaid, as many blocks as needed:
       flowchart LR
         A["today: the gate at the end"] --> B["pain: the claim is read too late"]
     NOT the execution DAG — that one is the contract's ## Execution graph. -->

## Alternatives bounced
<!-- The ideas that were considered and why they lost. This is the part a
     contract cannot carry: its `### Why` keeps only the surviving rationale.
     One A# per line, with the verdict spelled out. -->
- A1: {{option}} — pro: {{…}} / contra: {{…}} — verdict: {{kept|discarded}}

## Open
<!-- Questions still unsettled. Each names the CHEAPEST test that would settle
     it — these migrate to the ledger's ?NN when the task opens. -->
- Q1: {{question}} — settled by: {{cheapest refuting test}}

## Verdict (→ contract)
<!-- The seed of the contract. Objective line, the decision with its because,
     the claims that will be pre-registered (with the finding that supports
     each), and the scope. Never a summary of the sections above: the
     decision, in the closed form the contract needs. -->
- We need {{what done produces}}
- Decision: {{the path chosen}} — because {{why this and not another}}
- Claim seeds: {{what will be true}} — supported by {{F#}}
- Scope: in {{…}} · out {{…}}
