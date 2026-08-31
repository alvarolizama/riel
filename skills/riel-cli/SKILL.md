---
name: riel-cli
description: "Mechanical helper for Riel: writes the ledger with the exact format, instantiates packet templates, validates packets, derives the Hermes session-todo mirror. The agent invokes it in RUN nodes instead of handwriting state files."
version: 1.1.0
author: Álvaro Lizama
license: MIT
metadata:
  hermes:
    tags: [riel, cli, ledger, briefs, tooling]
    related_skills: [riel-ledger, riel-briefs, riel-contract, riel-delegate]
---

# riel-cli — Mechanical helper for Riel (Riel)

`rielctl` is a stdlib-only Python script that performs the mechanical parts
of the framework so the agent doesn't have to remember them:

- Writing `.riel/ledger.md` with the exact expected format
- Instantiating packet templates (`rielctl brief new`)
- Verifying that a packet satisfies the structural constraints
  (`rielctl brief validate`)
- Deriving the Hermes session-todo mirror from the ledger (`rielctl todo`)

**When to use:** on any `loop`-mode task and on every delegated task, the
agent invokes `rielctl` in `RUN` nodes instead of handwriting ledger files.
`fast` and most `full` tasks don't need it — use only the machinery the
task earns.

## Location

`rielctl` is normally on PATH — the repo's `make install` symlinks it
into `~/.local/bin`:

```bash
rielctl note --goal "..." --next "..."
```

If `command -v rielctl` comes up empty, invoke the skill copy directly
(it has a shebang):

```bash
python3 <skill-root>/scripts/rielctl note --goal "..." --next "..."
```

and restore the symlink with `make install` from the riel repo
checkout.

## Commands

All state-mutating commands write to `.riel/` in the *current working
directory*. Invoke from the task's worktree root.

### Ledger

```bash
rielctl note --goal "what done means" --next "first action"
rielctl note --next "next action"
rielctl note --core "Mailer — sends via Swoosh" [--core-slot 1]
rielctl note --claim "token expires at 1h" --verify-with "mix test token_test.exs"
rielctl note --check "token signs" --by "mix test token_test.exs" \
             --covering "sign+verify+expiry" [--confidence 14]
rielctl note --open "does the link survive quote chars?" \
             --settled-by "property test on URI.encode_www_form"
rielctl note --close 1 --check "it survives" --by "test" --covering "encoding"
```

Numbering (✓NN, ?NN) is assigned by `rielctl` — never hand-edited.

### Inspections

```bash
rielctl seam     # re-print the ledger + which invariants are due
rielctl resume   # full post-gap bootstrap (ledger → invariants → mode → next)
rielctl ship FILE.md   # check FILE for dense-register leakage before delivery
```

### Session todo (Hermes mirror, Spec 6)

```bash
rielctl todo    # JSON array for the todo tool, derived from the ledger
```

Reads the ledger and prints the session-todo items: Goal → root item,
Phase → pending child, Next → the only `in_progress`, ?NN → `OPEN NN`
pending, P# → `CLAIM:` pending, ✓NN → `DONE NN` completed. The todo is a
projection — fix the ledger and regenerate the mirror; never hand-edit the
todo into a divergent plan. Spec: `riel/specs/spec-todo-hermes.md`.

Exit codes:

- `note` / `seam` / `resume` / `todo`: 0 unless arguments invalid or the
  ledger is missing (1).
- `ship`: exit 0 if the file is clean; exit 1 if it finds dense markers
  (the agent should fix before delivery).

### Packets

```bash
rielctl brief new --type feature --param name="reset flow" \
                  --param one_sentence="add password reset via email" \
                  > .riel/packet.md
rielctl brief validate .riel/packet.md
```

`brief new` searches templates in order:

1. `~/.hermes/skills/riel-briefs/templates/<type>.md`
2. `<task-worktree>/.riel/templates/<type>.md`
3. `skills/riel-briefs/templates/<type>.md` (built into this repo)

Double-curly placeholders `{{param}}` are replaced with `--param` values;
unknown params abort non-zero so typos never silently produce broken
packets. Fill in the remaining content by hand with `patch` afterwards —
the template is the skeleton, not the final packet.

## The one rule

`rielctl` decides nothing and verifies nothing semantically.
It is a clerk: it keeps the format perfect so the agent can spend its
reasoning on the actual work. Every semantic decision — what the Goal is,
whether the gate actually passed, whether the claim is satisfied — remains
the agent's.
