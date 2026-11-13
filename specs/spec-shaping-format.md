# Spec 2 — Shaping format (`riel-shaping/v1`)

Shaping is optional research preceding one run. It is editable while researching
and frozen by revision when execution activates. It never records Plan nodes,
cursor position, gate results or Evidence. Local task state stays in the
worktree's gitignored `.riel/`.

## Serialization

Local and remote shaping are the same UTF-8 Markdown bytes. The file opens with
`# Shaping: <name>`, then the standalone marker `<!-- riel-shaping/v1 -->` before
any `##` heading. The remote catalog supplies URL, sha256 and bytes separately;
its download body is this document, not transport credentials or runtime state.

The sections are, in order:

1. `## Question` — one decision to close.
2. `## Findings` — every citable `F#`, with `— source: …, confidence …`.
3. `## Facts` — established constraints grounded in findings, no new `F#` IDs.
4. `## Diagrams` — optional current/proposed diagrams, never execution graphs.
5. `## Alternatives bounced` — numbered alternatives and kept/discarded/deferred verdicts.
6. `## Open` — questions with `— settled by: <the cheapest test>`.
7. `## Verdict (→ run)` — We need, Decision+because, Claim seeds and Scope.

HTML comments never create Findings, Facts, alternatives or questions. Duplicate
finding IDs and findings without sources are errors. The template demonstrates
citation syntax in comments without making those examples real evidence.

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
inferred from prose. Findings supporting Claims use `— anchor: shaping:F#`.

Activation resolves all shaping anchors as hard requirements and copies the
selected Findings into a frozen `### Basis` inside run Context. That carries
source, confidence and shaping hash into subsequently generated slices without
a dependency on the parent's shaping file.

Open questions must be resolved, explicitly transferred into run Open, or named
out of scope. A question cannot disappear at the handoff.

`plan_sha256` covers the Plan including Basis; `shaping_sha256` pins the original
research. An edit to either makes the active run stale until explicit `rebase`,
which advances the run revision. Evidence from older revisions remains present
for audit but no longer satisfies current claims or gates.

## Fetch

`riel_shape(verb="fetch")` requires expected SHA-256 and a confined output path.
Transport bounds the body and time, verifies TLS, applies the scheme policy at
every redirect, strips Authorization/Cookie on cross-origin redirects and rejects
incomplete Content-Length bodies. Errors redact URL path and query.

Fetching writes atomically but never activates a Plan. The validated local
shaping remains available offline throughout execution.
