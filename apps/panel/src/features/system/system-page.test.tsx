import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { SystemPage } from "./system-page";

afterEach(() => vi.unstubAllGlobals());

const BASE: Record<string, unknown> = {
  machine: {
    cpu_pct: null,
    mem_used_pct: null,
    disk_used_pct: null,
    load1: null,
    uptime_s: null,
  },
  samples: [],
  services: { web: true, worker: true, db: true, victorialogs: true },
  database: { ok: true, bytes: 1024, tables: [] },
  queues: [],
  backup: {
    ok: true,
    finished_at: "2026-11-04T09:00:00Z",
    dump_bytes: 100,
    stale: false,
  },
  deploys: [],
  release: "abc123",
  tls: { days_left: 30 },
  flow: {
    state: "ok",
    reason: null,
    last_inbound_at: "2026-11-04T09:56:00Z",
    last_outbound_at: "2026-11-04T09:57:00Z",
    received_1h: 12,
    answered_1h: 12,
    failed_1h: 0,
  },
  integrations: [
    {
      key: "bot:notify",
      label: "Bot de avisos",
      state: "ok",
      detail: null,
      checked_at: null,
    },
    {
      key: "bot:demo_tg",
      label: "Demo Telegram",
      state: "ok",
      detail: null,
      checked_at: null,
    },
    {
      key: "bot:demo_wa",
      label: "Demo WhatsApp",
      state: "off",
      detail: null,
      checked_at: null,
    },
    {
      key: "calendar",
      label: "Calendar",
      state: "ok",
      detail: "3 de 3 accesibles",
      checked_at: null,
    },
  ],
};

function renderWith(overrides: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ ...BASE, ...overrides }), {
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SystemPage />
    </QueryClientProvider>,
  );
}

test("colors TLS red under 7 days", async () => {
  renderWith({ tls: { days_left: 5 } });
  const text = await screen.findByText("5 días hasta caducar");
  expect(text.className).toContain("text-status-critical");
});

test("colors TLS amber under 20 days", async () => {
  renderWith({ tls: { days_left: 15 } });
  const text = await screen.findByText("15 días hasta caducar");
  expect(text.className).toContain("text-status-warning");
});

test("colors TLS green at 20 days or more", async () => {
  renderWith({ tls: { days_left: 25 } });
  const text = await screen.findByText("25 días hasta caducar");
  expect(text.className).toContain("text-status-ok");
});

test("shows a neutral TLS state when it has not been checked", async () => {
  renderWith({ tls: { days_left: null } });
  const text = await screen.findByText("Sin comprobar");
  expect(text.className).toContain("text-muted-foreground");
});

async function backupCard() {
  const title = await screen.findByText("Backup");
  const card = title.closest('[data-slot="card"]');
  if (!card) throw new Error("backup card not found");
  return within(card as HTMLElement);
}

test("colors the backup red when ok is false, even if not stale", async () => {
  renderWith({
    backup: {
      ok: false,
      finished_at: "2026-11-04T09:00:00Z",
      dump_bytes: 1,
      stale: false,
    },
  });
  const icon = (await backupCard()).getByText(/🔴/);
  expect(icon.className).toContain("text-status-critical");
});

test("colors the backup red when stale (older than 8h), even if ok", async () => {
  renderWith({
    backup: {
      ok: true,
      finished_at: "2026-11-04T01:00:00Z",
      dump_bytes: 1,
      stale: true,
    },
  });
  const icon = (await backupCard()).getByText(/🔴/);
  expect(icon.className).toContain("text-status-critical");
});

test("colors the backup green when ok and fresh", async () => {
  renderWith({});
  const icon = (await backupCard()).getByText(/🟢/);
  expect(icon.className).toContain("text-status-ok");
});

test("shows an explicit message when there is no backup at all", async () => {
  renderWith({ backup: { stale: true } });
  expect(
    (await backupCard()).getByText(/Sin backup registrado/),
  ).toBeInTheDocument();
});

test("shows the flow counts and a critical reason when there is one", async () => {
  renderWith({
    flow: {
      state: "critical",
      reason: "2 fallos en la última hora.",
      last_inbound_at: "2026-11-04T09:56:00Z",
      last_outbound_at: null,
      received_1h: 5,
      answered_1h: 3,
      failed_1h: 2,
    },
  });
  expect(
    await screen.findByText("2 fallos en la última hora."),
  ).toBeInTheDocument();
  expect(screen.getByText("5")).toBeInTheDocument();
  expect(screen.getByText("recibidos")).toBeInTheDocument();
});

test("shows an off integration as apagada and a calendar detail", async () => {
  renderWith({});
  expect(await screen.findByText("Demo WhatsApp")).toBeInTheDocument();
  expect(screen.getByText("apagada")).toBeInTheDocument();
  expect(screen.getByText("3 de 3 accesibles")).toBeInTheDocument();
});
