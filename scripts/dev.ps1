$ErrorActionPreference = "Stop"

docker compose up -d postgres
uv run python src/manage.py migrate
uv run python src/manage.py runserver
