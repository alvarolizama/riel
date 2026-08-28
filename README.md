<div align="center">

# 🛤️ Riel

### Steering Layer for Harness/LLM

A homegrown agent-steering framework. **Riel does not create capability in the model: it prevents capability from being lost.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![LLM](https://img.shields.io/badge/LLM-Agnostic-8B5CF6?logo=openai&logoColor=white)](https://elixir-lang.org)
[![Steering](https://img.shields.io/badge/Steering-DAG-F59E0B?logo=mermaid&logoColor=white)](https://mermaid.js.org)

![Riel](assets/riel-header.png)

</div>

A homegrown agent-steering framework. **Riel does not create capability in the
model: it prevents capability from being lost.** The thesis comes from
*capability-realization loss* research: the gap between a model having a
capability and delivering it reliably (unstable trajectory, drifting state,
missing verification).

*LLM-as-a-Verifier* extends the thesis: the loss is not just in **generating**
the capability, but in **discriminating which output is correct** — agents
already solve the task; they can't tell the correct solution from the wrong
one.

**Corollary: Riel is the opposite of brute-force prompting.** The default way
most people work with an LLM is trial and error: throw a vague prompt, see
what comes back, re-prompt until something looks right, accept it because it
compiled. No plan, no state between turns, no definition of done — the model
is being sampled, not steered. Riel inverts each of those: a task is
**planned** as an explicit DAG before any work happens (`riel-contract`),
**held** in a ledger re-read at every seam (`riel-ledger`), **delegated**
through self-contained briefs instead of hope (`riel-briefs`,
`riel-delegate`), and only **accepted** when each Goal line maps to a `✓NN`
with a named verifier and stated coverage. The agent stops when the work is
verified, not when the human runs out of patience re-prompting.

Spec-driven development is the same enemy's opposite — it too plans before
coding. The difference is the lifetime of the plan: a spec is written, then
trusted to be read. Riel's contract is re-read at every seam and closed
against evidence, and dies when the task does.

The name: the train already moves on its own; the rail just keeps it from
derailing.

Applies to any harness/LLM (DeepSeek or other) by operating on the surfaces
the harness exposes — system prompt / first turn, between-turn context, task
structure — without touching weights or internals.

## How it works

```mermaid
flowchart LR
  TASK["Task\n(todo / ticket / chat)"] --> P["riel-protocol\nanchored first turn\ngrammar · persona ·\nminimal surface"]
  B["riel-briefs\ndelegation briefs"] -.->|"when delegating"| P
  P --> LLM["LLM / harness\n(DeepSeek or other)"]
  C["riel-contract\nmermaid DAG as contract\nverb-graph · verification funnel"] -.->|"task structure"| LLM
  D["riel-delegate\nplan · dispatch waves\nparent verifies with confidence"] -.->|"when delegating\nto subagents"| LLM
  LLM <-->|"re-read at every seam"| LEDGER["riel-ledger\n.riel/ledger.md\nGoal · Core · Verified\nOpen · Next"]
  LEDGER --> DC["done-check\n✓NN ↔ Goal, line by line"]
  DC -->|"adapter writeback"| REMOTE["remote\ncheckboxes + status\n(adapter's job)"]
```

Every component operates on a different control surface:

```mermaid
flowchart TD
  subgraph S1["Surface 1 — first turn"]
    A["riel-protocol: grammar, persona,\nminimal surface, zero injections"]
  end
  subgraph S2["Surface 2 — task structure"]
    B["riel-contract: mermaid DAG,\n6 verbs, verification funnel"]
    C["riel-briefs: curated context,\ngates, anchored opening"]
    E["riel-delegate: plan phases,\ndispatch waves, parent verifies"]
  end
  subgraph S3["Surface 3 — between-turn state"]
    D["riel-ledger: Goal/Core/Verified/\nOpen/Next + recovery checkpoints"]
  end
  S1 --> M["Model delivers\nwithout losing capability"]
  S2 --> M
  S3 --> M
```

## Components

| Component | What it steers | Metaphor | Status |
|---|---|---|---|
| `riel-protocol` | **Trajectory** — functional grammar, persona, minimal surface | the switch: the first turn picks the track | ✅ skill v1.3 |
| `riel-ledger` | **State** — Goal/Core/Verified/Open/Next, re-read at every seam; recovery via checkpoints; local-first, no remote dependency | the track level | ✅ skill v1.2 + specs |
| `riel-contract` | **Structure** — mermaid as contract, verification funnel, BRAID/FlowBench evidence | the rails themselves | ✅ skill v3.0 |
| `riel-briefs` | **Delegation briefs** — curated context, verb-graph, gates, anchored opening | the signage | ✅ skill v3.0 |
| `riel-delegate` | **Delegation end-to-end** — plan phases as deliverables, dispatch waves, parent verifies returns with confidence | the guard | ✅ skill v1.0 |

Each component is **independent and optional**: a short task uses zero;
a long loop may use all five. Inherited philosophy: "use only the machinery
the task earns".

## The ledger cycle (heart of the framework)

```mermaid
flowchart TD
  OPEN["Open .riel/ledger.md\nGoal + Core + Next"] --> W[Work]
  W --> S{"seam: phase change,\ntool call, file change,\nlong gap"}
  S --> R["Re-read the ledger\n(the whole mechanism)"]
  R --> ST{"stalled? same Next\n3 seams?"}
  ST -->|yes| FIX["Diagnose or\nchange course"]
  FIX --> W
  ST -->|no| DEG{"degraded?\ncascading errors"}
  DEG -->|yes| REC["Recovery: last ✓NN =\ncheckpoint → fresh plan,\nre-enter at step 1"]
  REC --> W
  DEG -->|no| V{"verified?"}
  V -->|yes| APP["Append ✓NN\nverifier + coverage"]
  APP --> W
  V -->|no| W
  W --> END{"all phases done"}
  END --> DC["done-check: every Goal\nline maps to a ✓NN"]
  DC --> DONE([Done])
```

## System prompt initialization

To make the framework mandatory, paste this block into `soul.md` or an
injected system prompt (full version with rationale: `system-prompt.md`):

```
## Riel — steering framework

When operating on any LLM conversation or task, follow the Riel framework
(load the matching skill when it applies):

1. riel-protocol — open every conversation and subagent brief with a shared
   objective ("We need…"), a short stable persona, and minimal surface.
   Never rewrite the user's request.
2. riel-ledger — for multi-phase or long tasks, keep
   Goal/Core/Verified/Open/Next in .riel/ledger.md and re-read it at every
   seam. No done until every Goal line maps to a ✓NN with verifier and
   coverage; recover from the last ✓NN with a fresh plan.
3. riel-contract — express instructions and phases as mermaid DAGs with the
   closed verb vocabulary (READ/EDIT/CREATE/RUN/VERIFY/ASK); every flow ends
   in VERIFY nodes before End.
4. riel-briefs — when delegating, briefs are self-contained: curated
   context, executable gates, explicit DO NOT.

Riel never rewrites capability in — it only prevents it from being lost.
```

Keep it this short: the soul references the skills, it never embeds them
(embedding desyncs and costs tokens every turn).

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

## Validate mermaid blocks

```bash
scripts/validate-mermaid.sh            # README + specs + skills + system-prompt
scripts/validate-mermaid.sh README.md  # a single file
```

Requires mermaid-cli (`npm install -g @mermaid-js/mermaid-cli`). Extracts the
` ```mermaid ` blocks with `scripts/extract-mermaid.py` (regex + `re.DOTALL`,
not awk — awk works line-by-line, not whole blocks) and pipes each through
`mmdc`. Practicing what riel-contract preaches: the repo's own diagrams must
parse.

## Structure

```
riel/
├── README.md          ← this file
├── assets/            ← framework infographic
├── skills/            ← installable skills (cp to ~/.hermes/skills/)
│   ├── riel-protocol/   ← trajectory: grammar, persona, minimal surface
│   ├── riel-ledger/     ← state: local Goal/Core/Verified/Open/Next + recovery
│   ├── riel-contract/   ← structure: mermaid contract + verification funnel
│   ├── riel-briefs/     ← delegation briefs with anchored opening
│   └── riel-delegate/   ← delegation end-to-end: plan + dispatch + parent verification
├── specs/             ← design contracts (source of the patches)
│   ├── spec-ledger-format.md    ← .riel/ledger.md format + rules + git hygiene
│   ├── spec-todo-contract.md    ← what the todo body must carry → todo-flow patch
│   ├── spec-pull-push.md        ← local↔remote protocol → coder-flow patch
│   ├── spec-phase-advance.md    ← per-phase ledger: ledger+contract fusion
│   └── spec-adapters.md         ← system-agnostic contract for remote task systems
├── scripts/           ← repo tooling
│   ├── validate-mermaid.sh   ← validates every mermaid block with mmdc
│   ├── extract-mermaid.py    ← extracts mermaid blocks (regex, re.DOTALL)
│   └── dag-format-benchmark.py  ← prose vs mermaid vs plan benchmark (see "Own evidence")
└── references/        ← local-only notes (gitignored; public contract in specs/)
```

## Papers & sources actually used

| Source | What it contributed | Component(s) |
|---|---|---|
| Gurnee et al., *Verbalizable Representations Form a Global Workspace in Language Models* (Anthropic, 2026) | Workspace concept: capacity of 1-2 active ideas, broadcast hub, written externalization survives workspace ablation | `riel-protocol`, `riel-ledger` |
| DeepSeek community research: [dsh-anchored-standard](https://github.com/xiaobright/dsh-anchored-standard) + [DeepseekCotexplorations](https://github.com/0liveiraaa/DeepseekCotexplorations) | The 3 anchoring levers: Minimal tool schema 5/5, output budget 26/32, skill-catalog injections 0/9; "We need…" trajectory | `riel-protocol` |
| DeepSeek-V4 official paper ([arXiv:2606.19348](https://arxiv.org/abs/2606.19348)) | Model facts (1.6T/49B, 1M context); confirmation that anchoring is NOT officially documented — it is black-box evidence | `riel-protocol` |
| DeepSeek Harness source ([deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)) | First-hand confirmation of the Minimal preset (complete persona, zero runtime context, two-tool pair); `ctx.invariants` registry; capability seams | `riel-protocol`, `riel-ledger` |
| BRAID ([arXiv:2512.15959](https://arxiv.org/abs/2512.15959)) | Mermaid graphs as executable plans: +4 to +33.8 accuracy points, up to 74x performance-per-dollar; atomic nodes; verification funnel; generator/solver split | `riel-contract`, `riel-briefs` |
| FlowBench (EMNLP 2024 Findings) | Flowcharts > prose for agent planning; text + code + flowchart together > any single format | `riel-contract` |
| Lost in the Middle ([arXiv:2307.03172](https://arxiv.org/abs/2307.03172)) | Branch logic in paragraphs gets lost in long context; graphs are position-proof | `riel-contract` |
| Metacognitive control harness ([arXiv:2605.14186](https://arxiv.org/abs/2605.14186)) + Nelson & Narens 1990 | Every monitoring signal must select an action (48.3 → 56.9 without weight changes) | `riel-ledger` |
| Long-horizon agent failures ([arXiv:2607.05775](https://arxiv.org/abs/2607.05775), [arXiv:2607.00692](https://arxiv.org/abs/2607.00692), [arXiv:2607.08964](https://arxiv.org/abs/2607.08964)) | Context-handling gap, no-recovery bottleneck, completion overestimation → ledger fields, recovery protocol, done-check | `riel-ledger` |
| Re-reading the input ([arXiv:2309.06275](https://arxiv.org/abs/2309.06275)) | Re-reading improves reasoning across 14 datasets → the seam re-read | `riel-ledger` |
| METR GPT-5 evaluation report | The recovery template: "Stop. Focus. Return to step by step" — fresh plan, re-enter at step 1 | `riel-ledger` |
| Kwok et al., *LLM-as-a-Verifier* ([arXiv:2607.05391](https://arxiv.org/abs/2607.05391)) | Verification is the bottleneck, not generation (agents already solve; they can't tell which output is correct) — best-of-N headroom needs a reliable selector to be realized. 26.7% tie-rate from coarse discrete scoring (verifier: zero ties); fine granularity (1–20) + criteria decomposition + repeated evaluation each scale verification; score tracks task progress; two-stage workaround for closed models | `riel-ledger`, `riel-contract`, `riel-delegate` |

Full distillation of the 24 verified sources lives in the local
`references/` directory.

## Own evidence: prompt-format benchmark (prose vs mermaid DAG vs numbered plan)

`riel-contract` bets that a mermaid DAG carries instructions better than
prose. Papers (BRAID, FlowBench) support the bet — so we tested it directly,
with the same graphs, the same question, three notations:

| Notation | How the same edge (`outline` → `draft`) looks |
|---|---|
| prose | *"draft can only start once all of these are finished: outline, research."* |
| dag-mermaid | `outline --> draft` |
| dag-compiler | `2: plan(name='draft', deps=[outline=0, research=1])` |

**Task.** Given the graph, return the minimum number of sequential rounds
(topological layering). Judged by exact match against ground truth computed
locally with Kahn's algorithm. Six graphs (four small, 7–8 nodes; two large,
18–20 nodes), four open-weight chat models, temperature 0, `max_tokens=1000`
— 72 calls total (4 models × 6 graphs × 3 notations) against one
OpenAI-compatible endpoint. No endpoints or keys are hardcoded; the script
takes everything from flags.

**Accuracy** — all six graphs · large graphs only:

| Model | prose | dag-mermaid | dag-compiler |
|---|---|---|---|
| qwen3.8-flash | 6/6 · 2/2 | 6/6 · 2/2 | 5/6 · 2/2 |
| glm-5.3-flash | 5/6 · 1/2 | 6/6 · 2/2 | 6/6 · 2/2 |
| glm-5.3 | 5/6 · 1/2 | 6/6 · 2/2 | 5/6 · 1/2 |
| deepseek-v4-flash | 4/6 · 0/2 | 5/6 · 1/2 | 4/6 · 0/2 |

**Tokens** (large graphs, per call):

| Metric | prose | dag-mermaid | dag-compiler |
|---|---|---|---|
| prompt tokens (mean) | 450 | **327** (−27%) | 474 |
| completion tokens (median) | 1,000 | **862** | 1,000 |
| hit the 1,000-token output cap | 5/8 | **2/8** | 5/8 |
| total per call (mean) | 1,392 | **1,184** | 1,456 |

**Findings.**

- **Small graphs (≤8 nodes): format doesn't matter** — 15/16 exact across
  all conditions. Structure buys nothing at toy scale.
- **Large graphs (18–20 nodes): the gap opens** — prose 4/8, mermaid 7/8,
  plan 6/8. The prose/plan failures are not misreadings: reconstructing the
  graph from sentences makes models reason longer and blow the output cap
  (`unparseable` at exactly `max_tokens`). Mermaid's edge list removes that
  reconstruction step.
- **Mermaid dominates both dimensions**: ~25% fewer input tokens (it encodes
  each dependency as 2–5 tokens, no per-node boilerplate), less wasted
  reasoning, and the best accuracy at scale. Empirical basis for
  `riel-contract`'s *mermaid as contract*.

**Reproduce:**

```bash
export OPENAI_API_KEY=...   # any OpenAI-compatible endpoint works
python3 scripts/dag-format-benchmark.py \
  --base-url https://your-endpoint/v1 \
  --models your-model-a,your-model-b \
  [--cases monorepo,dataplatform] [--dry-run]
```

**Limits.** Six graphs, one seed, one task family (dependency planning),
four models from one provider family. Cap effects mean prose/plan token
costs are lower bounds. Nothing here claims mermaid helps *reasoning
quality* on small graphs — only that, as graphs grow, the explicit edge list
is cheaper and more reliable than prose. Which is exactly the regime
contracts live in.
