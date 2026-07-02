# PrestoDeck -- friendly entry points. Run `make` (or `make help`) to see them.
#
# Typical first run on a fresh machine:
#   make install      # install the host software on this computer
#   make setup        # put WiFi creds + firmware on a USB-connected Presto
#   make run          # start the host; power-cycle the Presto and it appears

.DEFAULT_GOAL := help
.PHONY: help install setup run deploy test lint typecheck check clean

help: ## Show this help.
	@echo "PrestoDeck make targets:"
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install the host software (run once, or after pulling updates).
	cd host && pip install -e ".[dev]"

setup: ## Guided WiFi + firmware setup for a USB-connected Presto.
	prestodeck-setup

run: ## Start the host daemon (loads your deck; serves the web editor on :8080).
	prestodeck-host

deploy: ## Re-copy the firmware to the Presto and reset it.
	prestodeck-deploy --reset

test: ## Run the host and device test suites.
	cd host && pytest -q
	pytest device/tests -q

lint: ## Lint the host code.
	cd host && ruff check src

typecheck: ## Type-check the host code (mypy --strict).
	cd host && mypy src

check: lint typecheck test ## Run lint, type-check, and tests.

clean: ## Remove build artifacts and caches.
	rm -rf host/dist host/build host/src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
