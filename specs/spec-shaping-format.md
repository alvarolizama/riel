# Spec 2 — Shaping format (`riel-shaping/v3`)

A shaping is optional research preceding one run. It asks ONE question and
answers it. It lives at `.riel/shapings/<slug>.md`; several coexist, one per
question or project track. It is editable while researching and frozen by
revision when execution activates. It never records Definition nodes, cursor
position, gate results or Evidence. Local task state stays in the worktree's
gitignored `.riel/`.

## Serialization

A shaping is UTF-8 Markdown, identical wherever it was produced. The file opens
with `# Shaping: <name>`, then the standalone marker carrying its uid before any
`##` heading:

    <!-- riel-shaping/v3 id:shp_xxxxxxxx -->

The uid is `shp_` plus 8 lowercase hex digits. It is the shaping's stable
identity: a rename does not change it, and two files sharing one uid are
refused. `shape new` mints a fresh uid while rendering; `--param id=shp_…`
overrides it for a system that mints its own.

## Authoring guard

A shaping that still carries `{{placeholder}}` text is a SKELETON, not research:
`shape validate` refuses it and lists every unfilled field by name. The same
guard the Definition has — a shaping whose Facts, Not wanted or Open are still
`{{…}}` must not back a run. Placeholders inside HTML comments do not count;
they are documentation, never data.

## Sections, in order

1. `## Question` — ONE line, ONE question mark. Two questions are two shapings.
2. `## Answer` — ONE line, no `?`, citing `— supported by F#` or
   `— decided by: owner`.
3. `## Findings` — `### F#` dossiers: heading = the citable claim, body = its
   support, `— source: …, confidence …`, optional `#### Diagram`.
4. `## Facts` — established constraints grounded in findings, no new `F#` ids.
5. `## Not wanted` — `A#` options with `verdict: kept | discarded: <reason> |
   deferred: <reason>`.
6. `## What we want` — `We need`, `Claim seeds … — supported by F#`, `Scope: in … · out …`.
7. `## Open` — LAST. `Q#` with `— settled by: <the cheapest test>` on the same line.

The order is enforced, and Open is last because it is the residue: what the
shaping could not close after the answer, the evidence and the commission.

HTML comments never create Findings, Facts, options or questions. Errors:
duplicate finding ids, a finding without a source, an empty or multi-line
Question, a Question without exactly one `?`, an empty or multi-line Answer, an
Answer containing `?`, an Answer with no finding citation and no owner decision,
an Answer citing a finding that does not exist, a missing section, and sections
out of order.

## Question and Answer

The Question is the unit of decomposition: one shaping, one question, one run,
one PR. The Answer is its resolution — epistemic, present tense, one line. It
feeds the Contract's `### Why`.

`## What we want` is different in kind: a commission to the executor, future
tense, three transferable bullets. `We need` seeds the Objective, `Claim seeds`
become the pre-registered `P#`, `Scope` becomes Constraints and DO NOT. The
Answer never restates the deliverable, and What we want never restates the
resolution.

Whether an Answer semantically addresses its Question is a review judgment. The
validator enforces the structural proxies (one line, no `?`, cited backing), not
meaning.

## Findings

A finding is a dossier:

    ### F1: <the citable claim, ONE line>
    <the support: prose, measurements, what was read>
    — source: repo@<commit>:<path>:<lines>#<symbol>, confidence high

    #### Diagram
    ```mermaid
    flowchart TD
      A["as it is"] --> B["as it would be"]
    ```

The heading is the claim; a `#### Diagram` (four hashes) stays inside its
finding, while the next `###` ends it. The frozen Basis copies heading, source
and confidence — never the body or the diagram — so a slice stays small.

Only dossiers are parsed; the old one-line bullet register is not read. Clause
separators accept ` — `, ` -- `, and ` – `.

Repository evidence should record `repository@observed-commit:path:lines#symbol`
(or worktree-relative `path:lines#symbol`). URLs include a retrieval date.
Benchmarks identify exact command and output. The observed commit pins what was
investigated; it does not imply current code is unchanged. A reference being
syntactically valid establishes location, not truth.

`shape validate` and `run activate` verify repository source references
(`repo@<rev>:<path>[:start[-end]][#symbol]` and local
`<path>:start[-end][#symbol]`) against the actual worktree:

- missing files, paths escaping the worktree, out-of-range line numbers, or a
  missing `#symbol` in the target file FAIL validation;
- a `#symbol` found in the file outside the cited line range emits a warning;
- non-file sources (URLs, `cmd:`, `benchmark:`, etc.) are accepted without file
  checks.

## Identity, location and revision

Three separate facts, never conflated:

- **uid** — who the shaping is. Stable across renames and copies.
- **slug/path** — where it lives: `.riel/shapings/<slug>.md`. The slug is the
  the author's choice.
- **sha256** — which bytes. A revision pin, not an identity: research is mutable,
  so every edit changes it.

A run binds all three. Resolution prefers the uid recorded at activation, so a
renamed file keeps its binding; the Definition's declaration is the authoring path.

## Handoff and freezing

Findings supporting Claims use `— anchor: shaping:F#`, and resolve against the
ONE shaping the run declares under `### Shaping`. Activation validates that
shaping, resolves all anchors as hard requirements and copies the selected
Findings into a frozen `### Basis` inside the Contract's Context, carrying
source, confidence, uid and shaping hash into slices without a dependency on the
parent's shaping file.

Open questions must be resolved, explicitly transferred into the Contract's Open
(`riel_note`), or named out of scope. The engine does NOT transfer them
automatically: the handoff is the author's obligation.

`definition_sha256` covers the Definition including Basis; `shaping_sha256` pins
the bound research. An edit to either makes the active run stale until explicit
`rebase`, which advances the revision. Editing a SIBLING shaping never makes this
run stale. Evidence from older revisions remains for audit but no longer
satisfies current claims or gates.

## Authoring outside Riel

Riel explains this format and validates it; it does not author shapings and it
does not fetch them. `shape new` renders the skeleton to stdout and writes
nothing. Any producer — an editor, a project system, an MCP server, an API, a
copy-paste — writes the bytes into `.riel/shapings/`, and `shape validate`
decides whether they are well formed. Transport is the producer's concern; the
Markdown is the contract.

## No legacy support

Only `riel-shaping/v3` is read. v1/v2 markers are refused with the missing-marker
error; there is no converter, no dual register and no migration verb. A loose
`.riel/shaping.md` is not resolved: shapings live in `.riel/shapings/`. An active
run whose Metadata carries the pre-rename `plan_sha256` key — or no
`definition_sha256` at all — is refused as stale: re-author the Definition and
activate again. Upgrading is deliberate authoring, never a rewrite the engine
invents.
