# Task: {{name}}

## Objective
We need the code in {{scope}} restructured so that {{goal}} — with zero observable behavior change.

## Context

### Project
- **Path:** {{repo_path}}
- **Stack:** {{language, framework, key deps}}
- **Conventions:** {{style, patterns}}

### Existing code to read
{{paths to be refactored}}

### Code to modify
{{exact files, and what changes structurally (not behaviorally) in each}}

### Reference snippets
{{3-5 snippets of the before-state}}

## Constraints (hard rules)
1. **Zero behavior change** — no new features, no bug fixes, no API changes.
2. All existing tests pass **unedited**.

## Pre-registered claims
- P1: The full existing suite passes **unedited** after the refactor — verify with: `{{suite command}}`
- P2: {{structural goal holds, e.g. "no module in X imports Y"}} — verify with: `{{grep command}}` returns nothing
- P3: Public API surface is unchanged — verify with: `{{diff command on exports/docs}}`

## Execution graph

```mermaid
flowchart TD
  S1["RUN {{suite command}}"] --> G0{"baseline green?"}
  G0 -->|no| ERR([Stop: dirty baseline — do not refactor])
  G0 -->|yes| S2["READ {{target files}}"]
  S2 --> S3["EDIT {{file 1}} — {{structural change}}"]
  S3 --> S4["RUN {{targeted tests}}"]
  S4 --> G1{"targeted tests green?"}
  G1 -->|no| S3
  G1 -->|yes| S5["EDIT {{file 2}} — {{structural change}}"]
  S5 --> S6["RUN {{full suite}}"]
  S6 --> G2{"full suite green, unedited?"}
  G2 -->|no| S3
  G2 -->|yes| END([Done])
```

## Verification gates

### Gate: Baseline is green
**Command:** `{{suite command}}`
**Expected:** all pass BEFORE any edit
**On failure:** stop — refactor on a dirty baseline mixes signal

### Gate: Full suite after refactor
**Command:** `{{suite command}}`
**Expected:** all pass, with **no test file edited**
**On failure:** the refactor changed behavior; revert the last structural change

## Deliverable
{{files restructured, structural goal achieved, behavior untouched}}

## DO NOT
- Fix any bug discovered mid-refactor (open a separate task)
- Add tests (unless the spec explicitly asks)
- Style-touch files outside the scope
