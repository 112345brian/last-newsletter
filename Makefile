.PHONY: check test lint format-check types import-boundaries arch

check: test lint format-check types import-boundaries arch

test:
	uv run --all-packages pytest

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

types:
	uv run ty check src/*/src libs/*/src

import-boundaries:
	uv run lint-imports

arch:
	uv run arborescent check
