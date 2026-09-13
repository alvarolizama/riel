# Riel initialization prompt

Paste this into your `soul.md` / system prompt (identity section). Keep it
short: it is injected every turn, and the detail lives in the skills.

## Copy from here

```
## Frameworks — activation lines

- **Riel (steering)** — when operating any LLM conversation or task, load the
  `riel-protocol` skill and whichever apply: `riel-ledger` (multi-phase tasks),
  `riel-contract` (DAGs), `riel-briefs`/`riel-delegate` (delegation),
  `riel-cli` (ledger, packets and digest via `rielctl`). Riel does not create
  capability — it prevents it from being lost.
```

## Why this shape

- **One line per framework** — the soul references skills, it does not embed
  them (embedding desyncs and costs tokens every turn).
- **Trigger-style phrasing** — each line says WHEN to apply, matching the
  skill descriptions so the Level-1 index match fires reliably.
- **Invariant closing line** — the thesis of the framework, so no component
  is ever read as "make the model smarter".

## Activation levels (reminder)

| Level | Where | Effect |
|---|---|---|
| 1 — available | skills installed in `~/.hermes/skills/` | loaded on task match |
| 2 — mandatory | this block in `soul.md` | always active |
| 3 — subagents | brief says "load and follow skill riel-*" | subagent loads it |
