# syntax=docker/dockerfile:1
# Multi-stage image: build the SPA with Node, serve it with a minimal non-root Caddy.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM caddy:2.11.7-alpine AS runtime
RUN adduser -S -D -H -u 10001 -s /sbin/nologin app
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
# The filesystem is read-only; Caddy needs somewhere writable for its config/data dirs.
ENV XDG_CONFIG_HOME=/tmp/config XDG_DATA_HOME=/tmp/data
USER app
EXPOSE 8080
