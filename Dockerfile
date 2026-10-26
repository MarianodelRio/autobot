# syntax=docker/dockerfile:1
# Multi-stage image (design.md §14.6): dependencies with uv, then a minimal non-root runtime.
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.14-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

FROM python:3.14-slim AS runtime
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY manage.py ./
COPY src ./src
COPY tenants ./tenants
# Build the manifest for the production staticfiles backend. These values exist only
# for collectstatic and never become image environment variables.
RUN ENVIRONMENT=prod DJANGO_SECRET_KEY=build-only-staticfiles \
    DJANGO_ALLOWED_HOSTS=localhost DB_APP_URL=postgres://build:build@localhost/build \
    SECRETS_FILE=/run/secrets/secrets.yaml WHATSAPP_GRAPH_VERSION=v23.0 \
    python manage.py collectstatic --noinput
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi", "-b", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--no-control-socket"]
