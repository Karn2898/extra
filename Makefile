# Makefile — developer tasks for the Declarative Agent Platform.
#
# Run `make install` once to set up the environment (editable install + dev
# tools), then use `make check` as the quality gate. AGENTS.md, CLAUDE.md, and
# the .ai/ skills and tasks refer to these targets.

PYTHON ?= python3
SRC := src
TESTS := tests
# Which example the local stack runs. The starter example is the default
# because it needs one API key and no internet:
#   make up EXAMPLE=examples/enterprise-knowledge-assistant
EXAMPLE ?= examples/starter
CONFIG ?= agents.yaml
FLAGSHIP := $(EXAMPLE)/$(CONFIG)

# What the `dev-*` targets serve, and where its env comes from. Both accept a
# path anywhere: make dev AGENTS=~/work/their/agents.yaml ENV_FILE=~/dev.env
# (`override` is needed: a shell leaves `~` alone in `VAR=~/...`, and a
# command-line variable otherwise wins over any assignment here).
AGENTS ?= $(FLAGSHIP)
ENV_FILE ?=
override AGENTS := $(patsubst ~/%,$(HOME)/%,$(AGENTS))
override ENV_FILE := $(patsubst ~/%,$(HOME)/%,$(ENV_FILE))
# The MCP server each example bundles (see its docker-compose.yml entrypoint).
MCP_MODULE ?= $(if $(findstring starter,$(EXAMPLE)),mcps.bank.server,mcps.local_knowledge_mcp.server)

# Every example must stay offline-valid — `make validate` checks them all.
EXAMPLES := examples/starter examples/enterprise-knowledge-assistant

IMAGE := ghcr.io/extra-org/extra:local

# A container can't reach the host's loopback, so `make up` rewrites a localhost
# base URL to host.docker.internal. Any other value passes through untouched.
DOCKER_BASE_URL := $(shell sed -n 's/^OPENAI_BASE_URL=//p' $(EXAMPLE)/.env 2>/dev/null \
	| sed -e 's|//127\.0\.0\.1|//host.docker.internal|' -e 's|//localhost|//host.docker.internal|')
COMPOSE := CONFIG=$(CONFIG) $(if $(DOCKER_BASE_URL),OPENAI_BASE_URL=$(DOCKER_BASE_URL)) \
	docker compose -f $(EXAMPLE)/docker-compose.yml

.DEFAULT_GOAL := help
# Bootstrap the `.env` beside the spec, but only when that's the file in use and
# there's an example to copy from.
ENV_DIR := $(patsubst %/,%,$(dir $(AGENTS)))
DEV_ENV := $(if $(ENV_FILE),,$(if $(wildcard $(ENV_DIR)/.env.example),$(ENV_DIR)/.env))

.PHONY: help install generate-ai sync-ai sync-skills format-check format lint typecheck test \
        generate-check check clean validate inspect build validate-image up up-ui down logs \
        dev dev-engine dev-mcp dev-widget

help: ## Show available targets.
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: generate-ai ## Install the package (editable) with dev dependencies.
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

generate-ai: ## Generate adapters from .ai/. Use TARGET=claude|codex to limit scope.
	$(PYTHON) -m tools.skills $(if $(TARGET),--target $(TARGET),)

sync-ai: generate-ai ## Alias for generate-ai (older name, kept for docs compatibility).

sync-skills: generate-ai ## Alias for generate-ai (older name, kept for docs compatibility).

format-check: ## Check code formatting without modifying files.
	ruff format --check $(SRC) $(TESTS)

format: ## Auto-format the codebase.
	ruff format $(SRC) $(TESTS)

lint: ## Lint the codebase (ruff check).
	ruff check $(SRC) $(TESTS)

typecheck: ## Type-check the codebase (mypy).
	mypy $(SRC) $(TESTS)

test: ## Run the test suite (pytest).
	pytest

# Compares the example tree before and after `generate` rather than against
# HEAD, so an unrelated work-in-progress diff cannot make this fail.
generate-check: ## Fail if `agentctl generate` would write anything (stale stubs).
	@for ex in $(EXAMPLES); do \
		before=$$(find $$ex -type f -not -path '*/__pycache__/*' | sort | xargs shasum | shasum); \
		agentctl generate --config $$ex/agents.yaml >/dev/null; \
		after=$$(find $$ex -type f -not -path '*/__pycache__/*' | sort | xargs shasum | shasum); \
		if [ "$$before" != "$$after" ]; then \
			echo "Stale stubs in $$ex — run 'agentctl generate --config $$ex/agents.yaml' and commit."; \
			exit 1; \
		fi; \
	done

check: format-check lint typecheck test generate-check ## Quality gate.

validate: ## Validate every example offline (no LLM calls, no network, no API keys).
	@for ex in $(EXAMPLES); do agentctl validate $$ex/agents.yaml || exit 1; done

inspect: ## Inspect the flagship example offline (agents, MCPs, hooks, plugins, tags).
	agentctl inspect $(FLAGSHIP)

build: ## Build the container image, tagged ghcr.io/extra-org/extra:local.
	docker build -t $(IMAGE) .

# Validate inside the image so only Docker is required, not a local install.
validate-image: build
	docker run --rm -v "$(PWD)/$(EXAMPLE):/workspace" $(IMAGE) validate /workspace/$(CONFIG)

up: validate-image $(EXAMPLE)/.env ## Run the example in engine mode: API on http://localhost:8090
	$(COMPOSE) --profile engine up -d
	@echo "engine: http://localhost:8090/health"

up-ui: validate-image $(EXAMPLE)/.env ## Run the example in manager mode: playground on http://localhost:8100/playground
	$(COMPOSE) --profile ui up -d
	@echo "playground: http://localhost:8100/playground"

# Development: the servers run natively, one per terminal, so an IDE debugger
# attaches to an ordinary process. watchfiles restarts them on save, which is
# why they need no reload flag of their own. Port: `PORT=8200 make dev`.
dev-mcp: ## Run the example's bundled MCP server on 127.0.0.1:8765.
	cd $(EXAMPLE) && $(PYTHON) -m $(MCP_MODULE)

dev: $(DEV_ENV) ## Run the manager natively: playground on http://localhost:8100/playground
	watchfiles --filter python "agent-manager --config $(AGENTS) --host 127.0.0.1 $(if $(ENV_FILE),--env $(ENV_FILE))" $(SRC) $(ENV_DIR)

dev-engine: $(DEV_ENV) ## Run the engine natively: API on http://localhost:8090
	watchfiles --filter python "agentctl serve --config $(AGENTS) --host 127.0.0.1 $(if $(ENV_FILE),--env $(ENV_FILE))" $(SRC) $(ENV_DIR)

dev-widget: ## Rebuild the chat widget on every save.
	npm run watch:widget

down: ## Stop the example stack.
	$(COMPOSE) --profile engine --profile ui down

logs: ## Follow logs from the example stack.
	$(COMPOSE) --profile engine --profile ui logs -f

# No prerequisite on purpose: bootstraps a missing .env, never overwrites one.
%/.env:
	@cp $(@D)/.env.example $@
	@echo "Created $@ — fill in the required keys, then run make again."
	@exit 1

clean: ## Remove caches and build artifacts.
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
