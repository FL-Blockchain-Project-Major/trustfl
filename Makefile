.PHONY: help install check lint format test clean venv audit

PYTHON ?= python3
VENV ?= .venv

help: ## Display available commands
	@echo "TrustFL Monorepo Build Automation"
	@echo "================================="
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

venv: ## Create virtual environment using uv or standard python venv
	@if command -v uv >/dev/null 2>&1; then \
		echo "Creating virtualenv with uv..."; \
		uv venv $(VENV) --python 3.11 || uv venv $(VENV); \
	else \
		echo "Creating virtualenv with $(PYTHON)..."; \
		$(PYTHON) -m venv $(VENV); \
	fi

install: venv ## Install project and development dependencies
	@if command -v uv >/dev/null 2>&1; then \
		echo "Installing dependencies with uv..."; \
		uv pip install -e ".[dev]"; \
	else \
		echo "Installing dependencies with pip..."; \
		$(VENV)/bin/pip install --upgrade pip; \
		$(VENV)/bin/pip install -e ".[dev]"; \
	fi

lint: ## Run code linter and static analysis
	@echo "==> Running Ruff linter..."
	@if [ -x "$(VENV)/bin/ruff" ]; then \
		$(VENV)/bin/ruff check .; \
	elif command -v ruff >/dev/null 2>&1; then \
		ruff check .; \
	else \
		echo "Ruff not found in environment; performing syntax validation..."; \
		$(PYTHON) -m compileall -q apps packages datasets tests scripts; \
	fi

format: ## Run code formatters
	@echo "==> Formatting code..."
	@if [ -x "$(VENV)/bin/ruff" ]; then \
		$(VENV)/bin/ruff format .; \
	elif command -v ruff >/dev/null 2>&1; then \
		ruff format .; \
	else \
		echo "Ruff not installed. Skipping formatting."; \
	fi

test: ## Run test suites
	@echo "==> Running test suites..."
	@if [ -x "$(VENV)/bin/pytest" ]; then \
		$(VENV)/bin/pytest tests; \
	elif command -v pytest >/dev/null 2>&1; then \
		pytest tests; \
	else \
		echo "Pytest not found in environment; falling back to python unittest..."; \
		$(PYTHON) -m unittest discover -s tests -p "test_*.py"; \
	fi

audit: ## Check git repository against forbidden patterns (Zero-Git principle)
	@echo "==> Auditing repository for unauthorized artifacts, data, or secrets..."
	@! git ls-files | grep -E '\.(pt|pth|bin|safetensors|onnx|npy|h5|csv|key|pem|secret)$$' || (echo "ERROR: Forbidden files found in git index!" && exit 1)
	@echo "Audit passed: No sensitive data, weights or keys detected."

check: lint test audit ## Run all code quality checks, tests, and security audits
	@echo "==> All checks completed successfully."

clean: ## Clean build, test, and temporary cache artifacts
	@echo "==> Cleaning cache and build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type d -name "*.egg-info" -exec rm -rf {} +
	@find . -type d -name ".pytest_cache" -exec rm -rf {} +
	@find . -type d -name ".ruff_cache" -exec rm -rf {} +
	@find . -type d -name ".mypy_cache" -exec rm -rf {} +
	@rm -rf build dist htmlcov .coverage
