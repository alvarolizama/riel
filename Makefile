# Riel — repo tooling
# The installed product lives under hermes_plugin/riel/. There is no build
# step and no PATH command: edit the package in place and verify it here.

PKG = hermes_plugin/riel

.DEFAULT_GOAL := help
.PHONY: help test validate digest lint

help: ## list targets
	@echo "Riel — make targets:"
	@grep -hE '^## ' $(MAKEFILE_LIST) | sed -E 's/^## /  /'

test: ## run the stdlib regression suite
	python3 -m unittest discover -s tests

define CHECK_DOCS
	@for f in README.md specs/*.md $(PKG)/guide/*.md $(PKG)/templates/*.md; do \
		printf '\n===== %s =====\n' "$$f"; \
		python3 $(PKG)/engine/run.py check "$$f" $(1) || exit $$?; \
	done
endef

## validate: dense-register, graph and mmdc checks on every docs file
validate:
	$(call CHECK_DOCS,--mermaid)

## digest: print the explicit graph digest without mmdc
digest:
	$(call CHECK_DOCS,)

## lint: byte-compile Python and shellcheck scripts when available
lint:
	python3 -m compileall -q scripts $(PKG)/engine/run.py tests $(PKG)
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck scripts/*.sh; \
	else \
		echo "shellcheck not found — skipped"; \
	fi
