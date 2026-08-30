# Riel initialization prompt

Paste this into your `soul.md` / system prompt (identity section). Keep it
short: it is injected every turn, and the detail lives in the skills.

## Copy from here

```
## Frameworks — líneas activadoras

- **Riel (steering)** — al operar cualquier conversación o tarea LLM, carga el
  skill `riel-protocol` y los que apliquen: `riel-ledger` (tareas multi-fase),
  `riel-contract` (DAGs), `riel-briefs`/`riel-delegate` (delegación),
  `riel-cli` (cuando necesites manipular el ledger o instanciar packets
  desde templates: `rielctl`). Riel no crea capacidad — evita que se pierda.
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
