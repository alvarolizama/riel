# Riel initialization prompt

Paste this into your `soul.md` / system prompt (identity section) when the
Hermes plugin is *not* installed — with the plugin, the `riel` prompt section
and `riel_guide` do this job and this block is redundant. Keep it short: it is
injected every turn, and the detail lives in the guides.

## Copy from here

```
## Frameworks — activation lines

- **Riel (steering)** — when operating any LLM conversation or task, read
  `riel_guide(topic="protocol")` and whichever apply: `riel_guide(topic="ledger")`
  (multi-phase tasks), `riel_guide(topic="contract")` (DAGs),
  `riel_guide(topic="briefs")` / `riel_guide(topic="delegate")` (delegation),
  `riel_guide(topic="tools")` (the tool surface: ledger, packets and digests).
  Riel does not create capability — it prevents it from being lost.
```

## Why this shape

- **One line per framework** — the soul points at the prose, it does not embed
  it (embedding desyncs and costs tokens every turn).
- **Trigger-style phrasing** — each line says WHEN to apply, matching the
  guides' own `trigger:` lines so the match fires reliably.
- **Invariant closing line** — the thesis of the framework, so no component
  is ever read as "make the model smarter".

## Activation levels (reminder)

| Level | Where | Effect |
|---|---|---|
| 1 — the plugin | the `riel` prompt section names the door; `riel_guide` serves the prose | read on need |
| 1' — no plugin | the six guides copied into a skills dir, loaded by the agent | loaded on task match |
| 2 — mandatory | the block above in `soul.md` | always active |
| 3 — subagents | brief says "read `riel_guide(topic=…)`" | subagent reads it |
