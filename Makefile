# Riel — repo tooling
#
# The product IS the Hermes plugin package at hermes_plugin/riel/: the prose
# (guide/), the engine that writes the formats, the twelve tools, the gate and
# the desktop chip. It installs as a COPY of a commit
# (`hermes plugins install … --enable`), never as a symlink and with nothing on
# PATH — so there is no install target here.
#
# There is no build step either: the package's tree IS the source. Edit it in
# place; `tests/` covers it, the engine's own `mermaid` subcommand parses its
# diagrams (`make validate`) and `specs/` is the long form of its formats.

PKG = hermes_plugin/riel

.DEFAULT_GOAL := help

.PHONY: help test validate digest lint

## help: list the available targets
help:
	@echo "Riel — make targets:"
	@grep -hE '^## ' $(MAKEFILE_LIST) | sed -E 's/^## /  /'

## test: run the stdlib regression suite (discovery — picks up new test files)
test:
	python3 -m unittest discover -s tests

## validate: parse every mermaid block with mmdc (needs mermaid-cli on PATH)
validate:
	python3 $(PKG)/engine/run.py mermaid README.md specs/*.md $(PKG)/guide/*.md $(PKG)/templates/*.md

## digest: print the explicit graph digest for the README, the specs and the guides
digest:
	@for f in README.md specs/*.md $(PKG)/guide/*.md; do \
		R="$$(python3 $(PKG)/engine/run.py digest "$$f" 2>/dev/null)"; \
		if [ -n "$$R" ]; then printf '\n===== %s =====\n%s\n' "$$f" "$$R"; fi; \
	done

## lint: byte-compile the Python tooling; shellcheck the shell scripts if present
lint:
	python3 -m compileall -q scripts $(PKG)/engine/run.py tests $(PKG)
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh; \
	else \
		echo "shellcheck not found — skipped"; \
	fi
