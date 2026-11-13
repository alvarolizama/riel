# Spec 3 — The Hermes plugin package

Riel 2 ships as one installed copy of `hermes_plugin/riel/`. The package contains
its prose, engine, two artifact templates, typed handlers, pre_verify hook,
settings and desktop integration. There are no external guides, package
symlinks, root skills, PATH entries or generated build copies.

## Product and operational state

Only the package is installed. Task-local `.riel/` remains in its worktree and
outside the package. The engine exclusively writes `.riel/run.md` and new
`.riel/shaping.md`. The previous contract and ledger files are unsupported as
inputs or state, without migration; state resolution cannot silently fall back
to them or to another session's cwd.

Six tools are registered: `riel_guide`, `riel_shape`, `riel_run`, `riel_note`,
`riel_clean` and `riel_check`. Every tool returns the common
`{tool, worktree, exit_code, passed, stdout, stderr}` envelope, including invalid
input and disabled-group refusals. Internal engine argv never reaches callers.

## Hot paths and concurrency

All in-process calls receive their own output and error sinks. They never
redirect process-global stdout, chdir, inherit mutable task state or cache a
transient loader failure permanently. Storage paths are explicit and resolved
per session; environment cwd is not worktree identity in multiplexed sessions.
A failed engine load yields a checkpoint retry, not an invisible permanent
quality reduction.

Engine writes use an atomic replacement and serialize their full transaction
under a file lock. State does not follow symlinks outside the worktree. Readers
and writers observe either complete revisions or explicit errors, not a blank
truncate-then-write state.

## Prose and prompt

`guide.py` is the one prose reader. Each of run, shaping, delegate and tools
has frontmatter `topic`, `trigger` and `version`; `riel_guide` serves topic
outlines by default and sections/full content on demand. No Hermes skill is
registered beside these sources.

The `riel` prompt publishes that prose, tools and when available a status summary
of the explicitly selected run. It accepts mappings supplied by Hermes and never
substitutes another worktree. `harness_note` occupies its bounded operator slot.

Shared `gate`, `tools`, `context`, `gate_attempts` and `harness_note` settings
are typed, validated at their single writer, and reread by their consumers. The
pre_verify gate reads structured run status instead of counting arbitrary
verified lines. It is bounded, switchable and scoped away from inactive runs.

## Desktop API and UI

The desktop client reads a single `/api/plugins/riel/run` resource with the
confined Markdown and structured state it needs. The worktree URL parameter is
The worktree parameter is not arbitrary filesystem authority: the target remains
exactly `.riel/run.md` without symlink escapes. Responses are bounded and carry
explicit missing/error states. Synchronous routes let FastAPI use its threadpool
instead of blocking the event loop. The chip does not reimplement validation.

## Installation

Install a commit using the Hermes plugin manager. The package tree is the source,
not a copyable intermediate tree. Uncommitted changes do not travel through the
commit installer. Desktop and gateway loading follow their next-session/reload
rules after updating Riel.

Verify with the real suite and Mermaid checks (`make test`, `make lint`, `make
validate`) before publishing the installable commit.
