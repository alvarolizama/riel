# Riel — rielctl installer + repo tooling
#
# The 6 skills are plain markdown read by the agent from wherever they
# are deployed (default: ~/Workspace/Skills). `rielctl` additionally
# gets a symlink in ~/.local/bin so any shell (human or agent, in any
# worktree) can call it without resolving the skill path first.
#
# The symlink points at THIS checkout, so `git pull` is enough to keep
# rielctl current — no re-install needed.

# Destinations are overridable — the skills dir is machine/user-specific:
#   make skills SKILLS_DIR=~/.hermes/skills
#   make install BIN_DIR=/other/bin
BIN_DIR ?= $(HOME)/.local/bin
SKILLS_DIR ?= $(HOME)/Workspace/Skills

SKILLS = riel-cli riel-ledger riel-contract riel-protocol riel-briefs riel-delegate

.DEFAULT_GOAL := help

.PHONY: help install skills uninstall test validate lint

## help: list the available targets
help:
	@echo "Riel — make targets:"
	@grep -hE '^## ' $(MAKEFILE_LIST) | sed -E 's/^## /  /'

## install: symlink rielctl into ~/.local/bin (PATH)
install:
	@mkdir -p $(BIN_DIR)
	@ln -sf $(CURDIR)/skills/riel-cli/scripts/rielctl $(BIN_DIR)/rielctl
	@echo "installed: $(BIN_DIR)/rielctl -> $(CURDIR)/skills/riel-cli/scripts/rielctl"

## skills: sync the 6 skills to SKILLS_DIR (deploy copies, not symlinks)
skills:
	@mkdir -p $(SKILLS_DIR)
	@for s in $(SKILLS); do \
		mkdir -p $(SKILLS_DIR)/$$s && cp -R skills/$$s/. $(SKILLS_DIR)/$$s/; \
	done
	@echo "synced 6 skills -> $(SKILLS_DIR)/"

## uninstall: remove the rielctl symlink (deployed skills stay in place)
uninstall:
	@rm -f $(BIN_DIR)/rielctl
	@echo "removed $(BIN_DIR)/rielctl (deployed skills left in place)"

## test: run the stdlib regression suite (discovery — picks up new test files)
test:
	python3 -m unittest discover -s tests

## validate: parse every mermaid block with mmdc (needs mermaid-cli on PATH)
validate:
	scripts/validate-mermaid.sh

## digest: print the explicit graph digest for every skill, README and spec
digest:
	@for f in README.md specs/*.md skills/*/SKILL.md; do \
		R="$$(python3 skills/riel-cli/scripts/rielctl digest "$$f" 2>/dev/null)"; \
		if [ -n "$$R" ]; then printf '\n===== %s =====\n%s\n' "$$f" "$$R"; fi; \
	done

## lint: byte-compile the Python tooling; shellcheck the shell scripts if present
lint:
	python3 -m compileall -q scripts skills/riel-cli/scripts/rielctl tests
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh; \
	else \
		echo "shellcheck not found — skipped"; \
	fi
