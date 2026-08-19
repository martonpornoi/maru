$ErrorActionPreference = "Stop"

uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run python scripts/validate_docs.py
uv run pydoclint src scripts
uv run python scripts/validate_python_docstrings.py src scripts
uv run sphinx-build -W --keep-going --fresh-env -b html docs docs/_build/html
uv run python src/manage.py makemigrations --check --dry-run
uv run python src/manage.py check
uv run python scripts/verify_production_settings.py
uv run python src/manage.py spectacular --file openapi.yaml --validate
uv run pytest --cov=maru --cov-report=term-missing

Push-Location frontends/staff-console
try {
    pnpm install --frozen-lockfile
    pnpm run generate:api
    pnpm run typecheck
    pnpm run test
    pnpm run build
}
finally {
    Pop-Location
}
