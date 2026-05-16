UV ?= uv

.PHONY: sync sync-sender lint format format-check lock check

sync:
	$(UV) sync

sync-sender:
	$(UV) sync --extra sender

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

format-check:
	$(UV) run ruff format --check .

lock:
	$(UV) lock

check: lint format-check
