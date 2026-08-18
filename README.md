# Riel — steering layer for harness/LLM

A homegrown agent-steering framework. **Riel does not create capability in the
model: it prevents capability from being lost.** The thesis comes from
*capability-realization loss* research: the gap between a model having a
capability and delivering it reliably (unstable trajectory, drifting state,
missing verification).

The name: the train already moves on its own; the rail just keeps it from
derailing.

Applies to any harness/LLM (DeepSeek or other) by operating on the surfaces
the harness exposes — system prompt / first turn, between-turn context, task
structure, evaluation — without touching weights or internals.

## Components

| Component | What it steers | Metaphor | Status |
|---|---|---|---|
| `riel-protocol` | **Trajectory** — functional grammar, persona, minimal surface | the switch: the first turn picks the track | ✅ skill v1.2 |
| `riel-ledger` | **State** — Goal/Core/Verified/Open/Next, re-read at every seam; recovery via checkpoints; local-first, no remote dependency | the track level | ✅ skill v1.1 + specs (Dran patches pending) |
| `riel-contract` | **Structure** — mermaid as contract, verification funnel, BRAID/FlowBench evidence | the rails themselves | ✅ skill v3.0 (migrated from mermaid-skill-authoring) |
| `riel-briefs` | **Delegation briefs** — curated context, verb-graph, gates, anchored opening | the signage | ✅ skill v3.0 (migrated from agent-instruction-authoring) |

Each component is **independent and optional**: a short task uses zero;
a long loop may use all four. Inherited philosophy: "use only the machinery
the task earns".

## How skills get loaded (Hermes mechanics)

Skills are NOT injected whole into every conversation — only their
name+description lives in each turn's system-prompt index. There are three
activation levels:

**Level 1 — available (automatic).** Skill installed in `~/.hermes/skills/`
→ its description appears in each turn's index → the agent loads it
(`skill_view`) when the task matches the description trigger. That is why
the first ~57 characters of the description are the actual trigger.

**Level 2 — mandatory (soul).** One line in the soul (identity system
prompt): *"In every conversation or brief for an LLM, apply the protocol of
skill `riel-protocol`."* The soul references the skill, never embeds its
content (it would desync and cost tokens every turn).

**Level 3 — subagents (brief).** `delegate_task` subagents have access to
the same skills; the parent's brief includes *"load and follow skill
riel-protocol"* and the subagent loads it itself.

General rule: the skill body enters context **only when needed**; the index
is what lives always.

## Installation

```bash
# from the repo
cp -R ~/Workspace/Repos/alvarolizama/riel/skills/riel-protocol ~/.hermes/skills/

# update after repo changes
cp -R ~/Workspace/Repos/alvarolizama/riel/skills/* ~/.hermes/skills/
```

Verify: the skill must appear in the session's skill index (`skills_list` or
the system listing).

## Structure

```
riel/
├── README.md          ← this file
├── skills/            ← installable skills (cp to ~/.hermes/skills/)
│   ├── riel-protocol/   ← trajectory: grammar, persona, minimal surface
│   ├── riel-ledger/     ← state: local Goal/Core/Verified/Open/Next
│   ├── riel-contract/   ← structure: mermaid contract + verification funnel
│   └── riel-briefs/     ← delegation briefs with anchored opening
├── specs/             ← design contracts (source of the patches)
│   ├── spec-ledger-format.md    ← .riel/ledger.md format + rules
│   ├── spec-todo-contract.md    ← what the todo body must carry → todo-flow patch
│   ├── spec-pull-push.md        ← local↔remote protocol → coder-flow patch
│   ├── spec-phase-advance.md    ← per-phase ledger: ledger+contract fusion
│   └── spec-adapters.md         ← system-agnostic contract (Dran first)
└── references/        ← distilled evidence (local notes)
```

## Evidence base

Distilled in Dran (`personal` context):

- `j-space-global-workspace-papers` — 24 verified sources (Anthropic global
  workspace, illegible reasoning, metacognition)
- `deepseek-v4-interfaz-y-trayectoria-we-need` — the 3 anchoring levers for
  trajectory in DeepSeek
- `graph-engineering-instrucciones-agentes` — BRAID/FlowBench/mermaid
- `ledger-pattern-estado-de-agentes` — Goal/Core/Verified/Open/Next
- `capability-realization-loss` — the problem frame
- `harness-analysis-papers-en-extension-points` — paper → harness map

## Honesty about evidence

- **Measured:** first-turn conditions anchor the trajectory on DeepSeek
  (Minimal schema 5/5; with injections 0/9).
- **Hypothesis:** that the anchored trajectory improves scores — independent
  replication with 95% CI [−2.6, +9.3]; one A/B found no gain. Riel does not
  promise better results; task verification lives in the done-check of
  `riel-ledger`.

## Dran project

Page `riel` (project type, `personal` context) — vision, phases, status.
