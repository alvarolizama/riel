# Riel — repo tooling
#
# The product is the Hermes plugin package at hermes_plugin/riel/: it carries
# the prose (guide/), the engine that writes the formats, the tool that serves
# the prose, the eleven other tools, the gate and the desktop chip, and it
# installs as a COPY of a commit (`hermes plugins install … --enable`), never
# as a symlink and with nothing on PATH.
#
# `guide/`, `engine/` and `templates/` inside the package are BUILD ARTIFACTS:
# `make plugin-build` regenerates them from this repo's copies and
# tests/test_plugin_vendor.py pins every file by hash. Edit the repo's, never
# the package's.

PLUGINS_DIR ?= $(HOME)/.hermes/plugins

PLUGIN_DIR = hermes_plugin/riel
PARTS = guide engine templates

.DEFAULT_GOAL := help

.PHONY: help plugin-build plugin-link test validate digest lint

## help: list the available targets
help:
	@echo "Riel — make targets:"
	@grep -hE '^## ' $(MAKEFILE_LIST) | sed -E 's/^## /  /'

## plugin-build: rebuild the package's guide/, engine/ and templates/ (build artifacts)
plugin-build:
	@rm -rf $(PLUGIN_DIR)/skills $(PLUGIN_DIR)/vendor
	@for part in $(PARTS); do rm -rf $(PLUGIN_DIR)/$$part; cp -R $$part $(PLUGIN_DIR)/$$part; done
	@chmod +x $(PLUGIN_DIR)/engine/run.py
	@echo "bundled: $(words $(wildcard guide/*.md)) topics + engine/run.py + $(words $(wildcard templates/*.md)) templates -> $(PLUGIN_DIR)/"

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
	@for f in README.md specs/*.md guide/*.md; do \
		R="$$(python3 engine/run.py digest "$$f" 2>/dev/null)"; \
		if [ -n "$$R" ]; then printf '\n===== %s =====\n%s\n' "$$f" "$$R"; fi; \
	done

## lint: byte-compile the Python tooling; shellcheck the shell scripts if present
lint:
	python3 -m compileall -q scripts engine/run.py tests $(PLUGIN_DIR)
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh; \
	else \
		echo "shellcheck not found — skipped"; \
	fi
