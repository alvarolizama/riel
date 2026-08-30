# Papers & sources — reference & inspiration

These are the sources that shaped Riel's design. They live here as reference,
not as a public API. The framework works without reading them; they explain
*why* each defense exists.

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

## Honesty about evidence

Riel's own benchmark (`dag-format-benchmark.py`, 72 calls) showed mermaid
DAGs outperform prose plans on a narrow parsing task (+9.3 points, 95% CI
[−2.6, +9.3]). That is a weak signal, not a guarantee. The framework's value
is in the *verification gates*, not in any claimed accuracy gain.

The full design logic — including the 24-source distillation — lives in
personal notes, not here.
