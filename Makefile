# Riel — rielctl installer
#
# The 6 skills are plain markdown read by the agent from wherever they
# are deployed (default: ~/Workspace/Skills). `rielctl` additionally
# gets a symlink in ~/.local/bin so any shell (human or agent, in any
# worktree) can call it without resolving the skill path first.
#
# The symlink points at THIS checkout, so `git pull` is enough to keep
# rielctl current — no re-install needed.

BIN_DIR ?= $(HOME)/.local/bin
SKILLS_DIR ?= $(HOME)/Workspace/Skills

SKILLS = riel-cli riel-ledger riel-contract riel-protocol riel-briefs riel-delegate

.PHONY: install skills uninstall test

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

uninstall:
	@rm -f $(BIN_DIR)/rielctl
	@echo "removed $(BIN_DIR)/rielctl (deployed skills left in place)"

test:
	python3 tests/test_rielctl.py
