# Spec 2 — Shaping format (`riel-shaping/v2`)

A shaping is optional research preceding one run, and it answers ONE question.
It lives at `.riel/shapings/<slug>.md`; several coexist, one per question or
project track. It is editable while researching and frozen by revision when
execution activates. It never records Definition nodes, cursor position, gate results
or Evidence. Local task state stays in the worktree's gitignored `.riel/`.

## Serialization

A shaping is UTF-8 Markdown, identical wherever it was produced. The file opens
with `# Shaping: <name>`, then the standalone marker carrying its uid before any
`##` heading:

    <!-- riel-shaping/v2 id:shp_xxxxxxxx -->

The uid is `shp_` plus 8 lowercase hex digits. It is the shaping's stable
identity: a rename does not change it, and two files sharing one uid are
refused. `shape new` mints a fresh uid while rendering; `--param id=shp_…`
overrides it for a system that mints its own.

The sections are, in order:

1. `## Question` — ONE line, ONE question mark. Two questions are two shapings.
2. `## Findings` — every citable `F#`, with `— source: …, confidence …`.
3. `## Facts` — established constraints grounded in findings, no new `F#` IDs.
4. `## Diagrams` — optional current/proposed diagrams, never execution graphs.
5. `## Alternatives bounced` — numbered alternatives and kept/discarded/deferred verdicts.
6. `## Open` — questions with `— settled by: <the cheapest test>`.
7. `## Verdict (→ run)` — We need, Decision+because, Claim seeds and Scope.

HTML comments never create Findings, Facts, alternatives or questions. Duplicate
finding IDs, findings without sources, an empty Question, a multi-line Question
and a Question without exactly one `?` are errors. The template demonstrates
citation syntax in comments without making those examples real evidence.

## Identity, location and revision

Three separate facts, never conflated:

- **uid** — who the shaping is. Stable across renames and copies.
- **slug/path** — where it lives: `.riel/shapings/<slug>.md`. The slug is the
  author's choice; migration derives it from the title.
- **sha256** — which bytes. A revision pin, not an identity: research is mutable,
  so every edit changes it.

A run binds all three. Resolution prefers the uid recorded at activation, so a
renamed file keeps its binding; the Definition's declaration is the authoring path.

## Code references

Repository evidence should record `repository@observed-commit:path:lines#symbol`.
URLs include a retrieval date. Benchmarks identify exact command and output.

The observed commit pins what was investigated; it does not imply current code
is unchanged. At activation relevant sources are re-read against the current
working tree when available. A reference being syntactically valid establishes
location, not truth.

## Handoff and freezing

Verdict supplies the run's Objective, Why, claim seeds and scope. Authoring the
actual graph, gate commands and paths remains deliberate, never automatically
inferred from prose. Findings supporting Claims use `— anchor: shaping:F#`, and
resolve against the ONE shaping the run declares under `### Shaping`.

Activation validates that shaping, resolves all anchors as hard requirements and
copies the selected Findings into a frozen `### Basis` inside run Context. That
carries source, confidence, uid and shaping hash into subsequently generated
slices without a dependency on the parent's shaping file.

Open questions must be resolved, explicitly transferred into run Open, or named
out of scope. A question cannot disappear at the handoff.

`definition_sha256` covers the Definition including Basis; `shaping_sha256` pins the bound
research. An edit to either makes the active run stale until explicit `rebase`,
which advances the run revision. Editing a SIBLING shaping never makes this run
stale. Evidence from older revisions remains present for audit but no longer
satisfies current claims or gates.

## Authoring outside Riel

Riel explains this format and validates it; it does not author shapings and it
does not fetch them. `shape new` renders the skeleton to stdout and writes
nothing. Any producer — an editor, a project system, an MCP server, an API, a
copy-paste — writes the bytes into `.riel/shapings/`, and `shape validate`
decides whether they are well formed. Transport is the producer's concern; the
Markdown is the contract.

## Migration of the loose legacy file

A pre-v2 `.riel/shaping.md` (marker `riel-shaping/v1`, no uid) is still resolved
so an already-active run keeps working after an upgrade. `run activate` and
`run rebase` migrate it:

1. Validate it. Issues (including a two-question Question) refuse the migration
   and leave the file untouched.
2. Derive the slug from the title; mint a uid and upgrade the marker to v2.
3. Write `.riel/shapings/<slug>.md` atomically. A different shaping already
   holding that slug refuses the migration; identical bytes reuse it.
4. Rotate the original to `.riel/shaping-<timestamp>.bak.md` — never delete it.
5. Declare the shaping in the Definition and record path, uid and sha256 in Metadata,
   in the same transaction.
