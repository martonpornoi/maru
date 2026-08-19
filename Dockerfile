# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
RUN python -m pip install --disable-pip-version-check --no-cache-dir uv==0.11.29
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && \
    DJANGO_SETTINGS_MODULE=maru.settings.local /opt/venv/bin/python src/manage.py collectstatic --noinput

FROM python:3.12-slim-bookworm@sha256:a116514e19457bcb7af7efe9c3dd0b9b71e85b317694e7882a1c52aa15a78134 AS runtime

ARG MARU_BUILD_VERSION=development
ARG MARU_BUILD_COMMIT=unknown
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=maru.settings.production \
    MARU_BUILD_VERSION=$MARU_BUILD_VERSION \
    MARU_BUILD_COMMIT=$MARU_BUILD_COMMIT

WORKDIR /app
RUN groupadd --system --gid 10001 maru && \
    useradd --system --uid 10001 --gid maru --home-dir /nonexistent --shell /usr/sbin/nologin maru
COPY --from=builder --chown=maru:maru /opt/venv /opt/venv
COPY --from=builder --chown=maru:maru /app/src /app/src
COPY --from=builder --chown=maru:maru /app/staticfiles /app/staticfiles
COPY --chown=maru:maru LICENSE README.md /app/

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)" || exit 1
CMD ["gunicorn", "--chdir", "/app/src", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "maru.wsgi:application"]
