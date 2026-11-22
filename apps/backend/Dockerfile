# syntax=docker/dockerfile:1
# Multi-stage image: dependencies with uv, then a minimal non-root runtime.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = true ]; then uv sync --locked; else uv sync --locked --no-dev; fi

FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY manage.py ./
COPY src ./src
# hadolint ignore=DL3066
USER app
EXPOSE 8000
# The production command, and the only place its flags live (compose.prod.yaml does
# not repeat it; compose.local.yaml replaces it with a --reload variant).
# --graceful-timeout (30 s) stays below the 60 s stop_grace_period of compose.prod.yaml:
# a worker that does not finish on SIGTERM is killed by gunicorn before Docker kills
# the container. --max-requests recycles workers (with jitter, so they do not all
# restart together). The access log has no query string (%(U)s, not %(r)s): WhatsApp's
# webhook verification carries its verify token there.
CMD ["gunicorn", "config.wsgi", "-b", "0.0.0.0:8000", "--workers=2", "--threads=4", "--no-control-socket", "--timeout=60", "--graceful-timeout=30", "--keep-alive=5", "--max-requests=1000", "--max-requests-jitter=100", "--access-logfile=-", "--access-logformat=%(h)s \"%(m)s %(U)s\" %(s)s %(b)s %(M)sms"]
