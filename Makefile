ROOT_DIR := $(shell git rev-parse --show-toplevel 2>/dev/null || pwd)
MCP_NAME := emacs-org
SERVER_SCRIPT := server.py
UV_PATH := $(shell which uv)
CLAUDE_CONFIG := $(HOME)/Library/Application Support/Claude/claude_desktop_config.json

.PHONY: setup sync lint black test mcp-install mcp-uninstall mcp-status mcp-install-desktop mcp-uninstall-desktop clean help install uninstall

setup: ## Initial project setup: install dependencies and pre-commit hooks
	echo "Installing dependencies (including dev)..."; \
	uv sync --all-extras
	@echo "Installing pre-commit hooks..."
	uv run pre-commit install
	@echo "Setup complete!"

sync: ## Sync dependencies
	uv sync --all-extras

lint: ## Run all pre-commit hooks (black, isort, ruff, mypy, etc)
	uv run pre-commit run --all-files

black: ## Run just black formatter
	uv run pre-commit run --all-files black

isort: ## Run just isort import sorter
	uv run pre-commit run --all-files isort

ruff: ## Run just ruff linter
	uv run pre-commit run --all-files ruff-check

mypy: ## Run just mypy type checker
	uv run mypy .

test: ## Run pytest tests
	uv run pytest -v

test-mcp: ## Test the MCP server with a simple tools/list request
	@(echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'; \
	  echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'; \
	  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}') | \
	  uv run $(SERVER_SCRIPT) 2>/dev/null | tail -1 | python3 -m json.tool

mcp-install: ## Install this MCP server globally in Claude Code
	@echo "Installing MCP server '$(MCP_NAME)' globally..."
	claude mcp add --scope user $(MCP_NAME) -- uv --directory $(ROOT_DIR) run $(SERVER_SCRIPT)
	@echo "MCP server installed. Restart Claude Code to use it."

mcp-uninstall: ## Uninstall this MCP server from Claude Code
	@echo "Uninstalling MCP server '$(MCP_NAME)'..."
	claude mcp remove --scope user $(MCP_NAME)
	@echo "MCP server uninstalled."

mcp-status: ## Show if the MCP server is configured in Claude Code
	@echo "Checking MCP server status..."
	@claude mcp list 2>/dev/null | grep -E "$(MCP_NAME)" || echo "MCP server '$(MCP_NAME)' is not installed"

mcp-install-desktop: ## Install this MCP server in Claude Desktop (macOS)
	@echo "Installing MCP server '$(MCP_NAME)' to Claude Desktop..."
	@mkdir -p "$(dir $(CLAUDE_CONFIG))"
	@uv run $(ROOT_DIR)/scripts/install_desktop.py \
		install \
		"$(CLAUDE_CONFIG)" \
		"$(MCP_NAME)" \
		"$(UV_PATH)" \
		"$(ROOT_DIR)" \
		"$(SERVER_SCRIPT)"
	@echo "Configuration updated. Restart Claude Desktop to use the MCP server."

mcp-uninstall-desktop: ## Uninstall this MCP server from Claude Desktop (macOS)
	@echo "Uninstalling MCP server '$(MCP_NAME)' from Claude Desktop..."
	@uv run $(ROOT_DIR)/scripts/install_desktop.py \
		uninstall \
		"$(CLAUDE_CONFIG)" \
		"$(MCP_NAME)"
	@echo "MCP server uninstalled. Restart Claude Desktop to apply changes."

install: mcp-install mcp-install-desktop
uninstall: mcp-uninstall mcp-uninstall-desktop

run: ## Run the MCP server directly (for debugging)
	uv run $(SERVER_SCRIPT)

clean: ## Clean up generated files and caches
	@echo "Cleaning up..."
	rm -rf .mypy_cache .pytest_cache .ruff_cache __pycache__ .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Clean complete."

help: ## Show this help
	@grep -hE '^[A-Za-z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
