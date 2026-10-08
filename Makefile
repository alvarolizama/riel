# Riel — repo tooling
#
# The product is the Hermes plugin package at hermes_plugin/riel/: it carries
# the six skills, the engine that writes the formats, the tools, the gate and
# the desktop chip, and it installs as a COPY of a commit
# (`hermes plugins install … --enable`), never as a symlink and with nothing
# on PATH.
#
# Its `skills/` directory is a BUILD ARTIFACT: `make plugin-skills` regenerates
# it from this repo's `skills/` and tests/test_plugin_vendor.py pins every file
# by hash. Edit `skills/` here, never the copy.

PLUGINS_DIR ?= $(HOME)/.hermes/plugins

SKILLS = riel-cli riel-ledger riel-contract riel-protocol riel-briefs riel-delegate
PLUGIN_DIR = hermes_plugin/riel

.DEFAULT_GOAL := help

.PHONY: help plugin-skills plugin-link test validate digest lint

## help: list the available targets
help:
	@echo "Riel — make targets:"
	@grep -hE '^## ' $(MAKEFILE_LIST) | sed -E 's/^## /  /'

## plugin-skills: rebuild the plugin's bundled skills/ from skills/ (build artifact)
plugin-skills:
	@rm -rf $(PLUGIN_DIR)/skills
	@cp -R skills $(PLUGIN_DIR)/skills
	@rm -rf $(PLUGIN_DIR)/vendor
	@echo "bundled: $(words $(SKILLS)) skills + scripts/rielctl + $(words $(wildcard skills/riel-briefs/templates/*.md)) templates -> $(PLUGIN_DIR)/skills/"

## plugin-link: symlink the package into a plugins dir — DEV ONLY, never a real install
plugin-link:
	@mkdir -p $(PLUGINS_DIR)
	@ln -sfn $(CURDIR)/$(PLUGIN_DIR) $(PLUGINS_DIR)/riel
	@echo "linked: $(PLUGINS_DIR)/riel -> $(CURDIR)/$(PLUGIN_DIR)"
	@echo "a real install is a copy: hermes plugins install \"file://$(CURDIR)#hermes_plugin/riel\" --enable"

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
	python3 -m compileall -q scripts skills/riel-cli/scripts/rielctl tests $(PLUGIN_DIR)
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh; \
	else \
		echo "shellcheck not found — skipped"; \
	fi
