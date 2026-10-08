---
topic: tools
trigger: "Use when you need Riel's tool surface — which of the twelve tools writes what, what each returns, and the template, fetch and exit-code rules. There is no command line: the tools are the interface."
version: 1.15.1
---

# tools — Riel's tool surface (Riel)

Every part of Riel the agent would otherwise have to remember by hand is a
**tool**, and each tool owns exactly one part — there is nothing to install and
no command line to call:

- Writing `.riel/ledger.md` with the exact expected format (`riel_note`)
- Reading the prose itself — the index, one guide, or one section of it
  (`riel_guide`)
- Instantiating packet templates (`riel_brief(verb="new")`)
- Verifying that a packet satisfies the structural constraints
  (`riel_brief(verb="validate")`) — including the closed verb vocabulary
- Expanding the execution graph into explicit text (`riel_brief(verb="digest")`)
- Deriving the Hermes session-todo mirror from the plan (`riel_todo`)
  and the ledger mirror the chip and the gate fold (`riel_state`)
- Emitting a contract's context keywords as JSON (`riel_context`) so the
  memory search has one authoritative index to read instead of re-parsing
  the contract
- Downloading a remote contract to disk without routing it through the
  agent's context (`riel_fetch`) — HTTPS-only, atomic, sha256-verified
- Instantiating the shaping skeleton and checking it against Spec 7
  (`riel_shaping(verb="new")` / `verb="validate"`)
- Re-reading each claim beside the region that supports it
  (`riel_seam(anchors=true)`) — the anchor surface of a seam
- Dense-register and graph-digest check on one file before delivering it
  (`riel_check`)

**When to use:** on any `loop`-mode task and on every delegated task, the
agent calls these tools in `RUN` nodes instead of handwriting ledger files.
`fast` and most `full` tasks don't need it — use only the machinery the
task earns.

## The surface: tools, never a command line

There is nothing to install and no command to remember: **the surface is the
tools**. Each one acts on the worktree of the session you are in — the session's
cwd, never the process's — and nothing is typed into a shell.

| Tool | Takes | Answers |
|---|---|---|
| `riel_guide` | `topic`, `section` | the prose: index, one guide, or one slice |
| `riel_note` | `goal`, `next`, `source`, `phase`, `core`+`core_slot`, `claim`+`verify_with`, `check`+`by`+`covering`+`confidence`, `open`+`settled_by`, `close`, `from_contract` | writes the ledger |
| `riel_seam` | `anchors=true` to also re-read each claim beside its support | the ledger at a seam |
| `riel_resume` | — | full post-gap bootstrap |
| `riel_todo` | — | the PLAN mirror (JSON) |
| `riel_state` | — | the LEDGER's facts (JSON) |
| `riel_context` | `keywords=[…]` (rarely) | the contract's context index |
| `riel_brief` | `verb` (new/validate/digest/slice) + `template`/`params`/`file`/`phase` | contracts and packets |
| `riel_shaping` | `verb` (new/validate) + `params`/`file`/`force` | the pre-contract research |
| `riel_clean` | `scope` (ledger/all/purge) | archives `.riel/` state |
| `riel_fetch` | `url`, `out`, `sha256`, `headers`, `allow_http` | a remote contract, on disk |
| `riel_check` | `file` | dense-register check + graph digest |

Every tool returns the same envelope: `{tool, worktree, exit_code, passed,
stdout, stderr}` plus its own keys (`verb` when the tool takes one, and the
prose's `topic`/`section` for `riel_guide`). **`tool` is provenance** — which
tool answered — never an interface: no tool takes argv, no flag travels as data,
and nothing here is meant to be typed into a shell.

All state-mutating tools write to `.riel/` in the worktree of the session; the
ones that only read take `worktree` to address another checkout explicitly.

### Ledger

```
riel_note(goal="what done means", next="first action")
riel_note(next="next action")
riel_note(core="Mailer — sends via Swoosh", core_slot=1)
riel_note(claim="token expires at 1h", verify_with="mix test token_test.exs")
riel_note(check="token signs", by="mix test token_test.exs",
          covering="sign+verify+expiry", confidence=14)
riel_note(open="does the link survive quote chars?",
          settled_by="property test on URI.encode_www_form")
riel_note(close=1, check="it survives", by="test", covering="encoding")
```

`close` requires `check`/`by`: a question is closed against the checkpoint that
settled it, never dropped silently.

Numbering (✓NN, ?NN) is assigned by `riel_note` — never hand-edited.

### Inspections

```
riel_seam(anchors=true)   # the ledger + each claim beside its support
riel_resume               # post-gap bootstrap (ledger → invariants → mode → next)
riel_state                # the ledger's facts as JSON (chip and gate fold this)
riel_check(file="packet-f2.md")   # dense markers + the graph digest, before delivery
```

### Clean (start a task over existing `.riel/` state)

```
riel_clean(scope="ledger")   # back up .riel/ledger.md, then remove it
riel_clean(scope="all")      # also the contract.md and the shaping.md
riel_clean(scope="purge")    # remove without backing up
```

The backup is a **flat timestamped file INSIDE `.riel/`**
(`ledger-<ts>.bak.md`) — never a subdirectory. A second clean within the
same second appends `-N` instead of clobbering. Idempotent: with nothing to
clean it reports success and says so.

**The agent asks the user before cleaning** — a `.riel/` found at the
opening holds another task's state, and the choice (back up / purge /
continue the existing ledger via `riel_resume`) is the user's, not a silent
default (rule in `riel_guide(topic="ledger")`, "Opening over an existing `.riel/`").

### Shaping (Spec 7)

```
riel_shaping(verb="new", params=["name=reset flow"])    # writes .riel/shaping.md
riel_shaping(verb="validate", file=".riel/shaping.md")  # the rules
```

`verb="new"` drops the shipped skeleton into `.riel/shaping.md`; it refuses to
overwrite an existing shaping (exit 3) — a shaping is research, not a template
drop — unless `force=true`. The shipped skeleton carries one placeholder `F#`
line with its `source:`/`confidence` slots, so it validates like every other
fixture: the structure is there, the research is not.

`verb="validate"` errors on a missing section, an empty `## Question` and a
`## Findings` with no `F#` line; it WARNs on a finding without `source:` or
`confidence`, an alternative without a `verdict:`, an open question without
`settled by:`, a Verdict with no `We need …` line, and a contract claim
anchored to a finding this shaping does not have.

### Claim anchors (Spec 2 + Spec 7)

`riel_seam(anchors=true)` prints every claim beside the region that supports
it. A claim may end its line with `— anchor: <ref>`: `§<Section>[#<n>]` (the
n-th bullet of that section), a graph node id, or `shaping:F<n>` (a finding of
`.riel/shaping.md`). The tool resolves it and prints the excerpt — the seam's
own re-read surface, so a claim's support is re-read without re-reading the
whole contract. A claim with no anchor or an unresolvable one is reported; a
`shaping:` anchor falls back to the shaping beside the contract.

### Context keywords (Spec 2)

`riel_context` prints `{"keywords": [{"term": …, "source": …}]}` — the index the
memory search reads (one term per line under `### Context keywords`; `→ dran`
is an optional source hint). Empty list when the contract has none; it reports
a failure only when the contract is missing.

### Session todo (Hermes mirror, Spec 6)

`riel_todo` returns the **plan**: the contract's `## Objective` → root `goal`;
**each contract phase → a row (`PHASE F1: …`) and each phase's steps → nested
subtasks** (`parent` = the phase — the todo tool's own nesting). The ledger
only sets the statuses: a phase whose gate has a ✓ is completed; in the active
phase (the one owning the Next) the step the Next points at is the only
`in_progress`, the earlier steps completed, the rest pending (the `goal` row
carries it once every phase is gated). **No ledger fact is a row here.**
Without a contract the todo degrades to `goal` + the ledger's single `PHASE:`
row.

`riel_state` returns the **ledger's own facts** as items (goal, phase, next,
`OPEN NN`, `CLAIM:`, `DONE NN`) — the mirror the desktop chip and the
`pre_verify` gate fold. Keep the two apart: `riel_todo` = plan, `riel_state` =
state.

The todo is a projection — fix the ledger (or the contract) and regenerate
the mirror; never hand-edit the todo into a divergent plan. Spec:
`riel/specs/spec-todo-hermes.md`.

**Injecting it (Hermes):** the mirror is complete only when the array reaches
the session todo UI — pass it to the `todo_list` tool as
`todo_list(todos=<array>)` right after `riel_todo` returns it. Regenerate +
re-inject at every seam where the ledger moved; the store is session-scoped,
so a new session re-injects from the current ledger.

What each tool reports, in the envelope's `exit_code`:

- `riel_note` / `riel_seam` / `riel_resume` / `riel_todo` / `riel_state`: 0
  unless the arguments are invalid or the ledger is missing (1).
- `riel_clean`: always 0 — "nothing to clean" is a message, not an error.
- `riel_shaping(verb="validate")`: 0 with WARNs only; 1 with an `ISSUE` or a
  missing file. `verb="new"`: 0; 3 when the destination already exists (pass
  `force=true`).
- `riel_seam(anchors=true)`: the seam's own code, and the anchor half reports
  its own (1 with no contract; 2 with no claims or an unknown claim id) under
  `anchors.exit_code`.
- `riel_check`: 0 when the file is clean; 1 when it finds dense markers or the
  graph cannot be expanded (fix before delivery).

### Contracts & packets

```
# the contract (the plan) — from a typed skeleton, then write it yourself
riel_brief(verb="new", template="feature",
           params=["name=reset flow", "one_sentence=add password reset via email"])
# → returns the rendered text; write it to .riel/contract.md with write_file

riel_brief(verb="validate", file=".riel/contract.md")
riel_brief(verb="digest",   file=".riel/contract.md")   # the graph as explicit text

# a child's packet — one phase sliced from the contract
riel_brief(verb="slice", file=".riel/contract.md", phase="F2")
```

`verb="new"` searches templates in order:

1. `~/.hermes/riel/templates/<type>.md` (a user-level override)
2. `<worktree>/.riel/templates/<type>.md` (versioned with the code)
3. `<package>/templates/<type>.md` (the shipped set)

Double-curly placeholders `{{param}}` are replaced with the `params` values;
unknown params abort non-zero so typos never silently produce broken
packets. Fill in the remaining content by hand with `patch` afterwards — the
template is the skeleton, not the final packet.

`verb="validate"` checks the structure, the Objective/claims/DO-NOT, and the
execution graph against `riel_guide(topic="contract")` — predictable ids, a RUN + VERIFY
funnel, labeled decision edges, **every execution node starting with a
closed verb** (READ/EDIT/CREATE/RUN/VERIFY/ASK), **an `ASK` node naming its
trigger** (`ASK[irreversible|outside-claims|goal-changing]`), no `<br/>`, no
`style` in the DAG, no tool names in labels — plus an mmdc parse when
mermaid-cli is present. Loops without a counter guard (`< 3` / `>= 3`),
over-long labels and an Objective that runs past one sentence (the spec
asks for one — rationale goes in `### Why`) are reported as non-fatal
`WARN`s. **Claim anchors** are checked too: a claim with no anchor is a
`WARN`; a `§Section#n` that does not resolve, or an anchor in no known form,
is an `ISSUE`; a node the local graph lacks (the inherited-on-a-slice case)
and a `shaping:F#` the shaping does not have are `WARN`s.

`verb="slice"` extracts one phase's subgraph as a mini packet. It inherits
mechanically — never as FILL — the Objective, the `### Why` rationale (with the
rule: the child escalates `ASK[goal-changing]` on a conflict instead of
reinterpreting) and the `### Context keywords`; the rest of the sections stay
FILL for the parent.

`verb="digest"` prints the explicit **graph digest** — elements, authored
edges, branches, entry/terminals and loops, with a "meaning & limits" footer.
Use it to give an agent the text beside the diagram (the diagram stays for
humans). `riel_check` runs the same expansion on any file.

### Fetch (download a contract, Spec 2 — local-first)

```
riel_fetch(url=URL, out=".riel/contract.md", sha256=H, headers=["Name: value"],
           allow_http=False)
```

Materializes a contract that lives on a server (e.g. Gorim's
`GET /api/steps/:id/contract.md`) into the worktree — the body never travels
through the agent's context (MCP responses cap at ~10KB; a contract exceeds
it). The server's export returns a reference `{url, sha256, bytes}`; the tool
downloads the URL and verifies the hash before writing. The URL typically
embeds a **short-lived signed token** (not the api_key): it expires (TTL) and
is single-use, so the tool needs no credentials.

**When to run it:** at the *opening* of a task that uses a remote contract —
`riel_resume` / `riel_seam` / `riel_note(from_contract=true)`, before the
context fetch — **not only when delegating**. A solo task fetches its contract
the same way; `riel_brief(verb="slice")` (for a child) is a later, separate
moment and is never the trigger.

Security defaults (not optional): **HTTPS required** — plain `http` is refused
except for `localhost`/`127.0.0.1`/`::1`, or anywhere with `allow_http=true` (a
trusted transport such as a VPN); TLS is verified; the body is bounded; the
write is **atomic** (temp file + rename, so a failed or mismatched download
never leaves a partial file); and the URL is **never printed** — a short-lived
token embedded in the query string must not leak into logs or tool output. Pass
`sha256` to enforce end-to-end integrity.

How a fetch can fail, in the envelope's `exit_code`: `0` ok · `1`
network/HTTP/write error · `2` bad scheme or refused plain-http · `3` body over
the bound · `4` sha256 mismatch (nothing written).

## The one rule

Riel decides nothing and verifies nothing semantically. The tools are clerks:
they keep the format perfect so the agent can spend its reasoning on the actual
work. Every semantic decision — what the Goal is,
whether the gate actually passed, whether the claim is satisfied — remains
the agent's.
