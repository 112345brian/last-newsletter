.PHONY: check test lint format-check types import-boundaries arch

check: test lint format-check types import-boundaries arch

test:
	uv run --package last-newsletter-cli pytest

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

types:
	uv run ty check packages/*/src

import-boundaries:
	uv run lint-imports

arch:
	uv run arborescent check
