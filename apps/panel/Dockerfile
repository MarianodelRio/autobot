# syntax=docker/dockerfile:1
# Multi-stage image, built from the REPO ROOT (`docker build -f apps/panel/Dockerfile .`):
# the SPA with Node, the documentation site with Zensical, and both served by a minimal
# non-root Caddy. The context is filtered by apps/panel/Dockerfile.dockerignore.
FROM node:24-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS build
WORKDIR /app
# The repo this build came from, for the commit links on the system page. Empty for a
# local dev build.
ARG VITE_GITHUB_REPO=
ENV VITE_GITHUB_REPO=$VITE_GITHUB_REPO
COPY apps/panel/package.json apps/panel/pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY apps/panel/ ./
RUN pnpm build

# Documentation site (ADR-018). Zensical comes from the `docs` dependency group of
# apps/backend/pyproject.toml, pinned by uv.lock (zensical==0.1.3), the same as
# `make docs-check`.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS docs
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /repo
COPY apps/backend/pyproject.toml apps/backend/uv.lock apps/backend/
COPY mkdocs.yml ./
COPY docs/ docs/
# Code that the docs embed with `--8<--` snippets.
COPY apps/backend/src/ apps/backend/src/
RUN uv run --project apps/backend --only-group docs --frozen zensical build --strict -f mkdocs.yml \
    && test -f var/docs-site/index.html

FROM caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0 AS runtime
RUN adduser -S -D -H -u 10001 -s /sbin/nologin app
COPY --from=build /app/dist /srv
COPY --from=docs /repo/var/docs-site /srv/docs
COPY apps/panel/Caddyfile /etc/caddy/Caddyfile
# The filesystem is read-only; Caddy needs somewhere writable for its config/data dirs.
ENV XDG_CONFIG_HOME=/tmp/config XDG_DATA_HOME=/tmp/data
# hadolint ignore=DL3066
USER app
EXPOSE 8080
