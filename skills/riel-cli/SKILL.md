---
name: riel-cli
description: "Mechanical helper for Riel: writes the ledger with the exact format, instantiates packet templates, validates packets. The agent invokes it in RUN nodes instead of handwriting state files."
version: 1.0.0
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

**When to use:** on any `loop`-mode task and on every delegated task, the
agent invokes `rielctl` in `RUN` nodes instead of handwriting ledger files.
`fast` and most `full` tasks don't need it — use only the machinery the
task earns.

## Location

The script lives inside this skill:

```
<skill-root>/scripts/rielctl
```

Resolve `<skill-root>` by finding this skill under ~/.hermes/skills/ or in
the repo at `skills/riel-cli/`. Invoke it directly (it has a shebang):

```bash
python3 <skill-root>/scripts/rielctl note --goal "..." --next "..."
```

### Discovering the path

If you're Riel-aware but don't know the absolute path of this skill, run
once:

```bash
python3 -c "import os; print(next(os.path.join(r, 'riel-cli') for r, ds, _ in os.walk(os.path.expanduser('~/.hermes')) if 'riel-cli' in ds), end='')"
```

Or search the current repo: `find . -type d -name riel-cli`.

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

Exit codes:

- `note` / `seam` / `resume`: always 0 unless arguments are invalid.
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
