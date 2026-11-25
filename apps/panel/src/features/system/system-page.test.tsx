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
  services: { worker: true, db: true, victorialogs: true },
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
  containers: {
    available: true,
    generated_at: "2026-11-04T09:59:00Z",
    stale: false,
    maintenance: null,
    items: [
      {
        service: "web",
        name: "autobot-web-1",
        status: "running",
        health: "healthy",
        restart_count: 0,
        oom_killed: false,
        started_at: "2026-11-04T09:00:00Z",
        image_tag: "abc123def456",
        image_matches: true,
        level: "ok",
        reason: null,
      },
    ],
  },
};

const CONFIG: Record<string, unknown> = {
  revision: 12,
  updated_at: "2026-11-04T09:50:00Z",
  processes: [
    {
      service: "web",
      host: "box1",
      pid: 7,
      revision: 12,
      started_at: "2026-11-04T08:00:00Z",
      seen_at: "2026-11-04T09:59:50Z",
      behind: false,
    },
    {
      service: "worker-outbound",
      host: "box2",
      pid: 9,
      revision: 11,
      started_at: "2026-11-04T08:00:00Z",
      seen_at: "2026-11-04T09:59:55Z",
      behind: true,
    },
  ],
};

function renderWith(
  overrides: Record<string, unknown>,
  config: Record<string, unknown> = CONFIG,
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const body = request.url.endsWith("/system/config")
        ? config
        : { ...BASE, ...overrides };
      return new Response(JSON.stringify(body), {
        headers: { "Content-Type": "application/json" },
      });
    }),
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

async function containersCard() {
  const title = await screen.findByText("Contenedores");
  const card = title.closest('[data-slot="card"]');
  if (!card) throw new Error("containers card not found");
  return within(card as HTMLElement);
}

test("shows the containers table with a row per service", async () => {
  renderWith({});
  const card = await containersCard();
  expect(card.getByText("web")).toBeInTheDocument();
  expect(card.getByText("En marcha")).toBeInTheDocument();
  expect(card.getByText("Bien")).toBeInTheDocument();
  expect(card.getByText("abc123def456")).toBeInTheDocument();
});

test("shows an empty state when there is no container snapshot", async () => {
  renderWith({
    containers: {
      available: false,
      generated_at: null,
      stale: false,
      maintenance: null,
      items: [],
    },
  });
  const card = await containersCard();
  expect(
    card.getByText(/Sin datos de contenedores\. En producción, revisa/),
  ).toBeInTheDocument();
});

test("warns when the container snapshot is stale", async () => {
  renderWith({
    containers: {
      available: true,
      generated_at: "2026-11-04T09:00:00Z",
      stale: true,
      maintenance: null,
      items: [],
    },
  });
  const card = await containersCard();
  const warning = card.getByText(/Datos desactualizados/);
  expect(warning.className).toContain("text-status-warning");
});

test("shows a deploy-in-progress notice and suppresses no alert styling", async () => {
  renderWith({
    containers: {
      available: true,
      generated_at: "2026-11-04T09:59:00Z",
      stale: false,
      maintenance: "deploy",
      items: [],
    },
  });
  const card = await containersCard();
  expect(card.getByText("Despliegue en curso.")).toBeInTheDocument();
});

test("colors a mismatched image tag as a warning", async () => {
  renderWith({
    containers: {
      available: true,
      generated_at: "2026-11-04T09:59:00Z",
      stale: false,
      maintenance: null,
      items: [
        {
          service: "web",
          name: "autobot-web-1",
          status: "running",
          health: "healthy",
          restart_count: 1,
          oom_killed: false,
          started_at: "2026-11-04T09:00:00Z",
          image_tag: "old1234567",
          image_matches: false,
          level: "warning",
          reason: "Imagen old1234567 distinta de la desplegada abc123def456",
        },
      ],
    },
  });
  const card = await containersCard();
  const tag = card.getByText("old1234567");
  expect(tag.className).toContain("text-status-warning");
  expect(
    card.getByText("Imagen old1234567 distinta de la desplegada abc123def456"),
  ).toBeInTheDocument();
});

test("shows how long the oldest ready and running jobs of each queue have waited", async () => {
  renderWith({
    queues: [
      {
        queue_name: "outbound",
        pending: 4,
        oldest: "2026-11-04T09:50:00Z",
        age_s: 420,
        running: 1,
        running_age_s: 45,
      },
      {
        queue_name: "ops",
        pending: 0,
        oldest: null,
        age_s: null,
        running: 0,
        running_age_s: null,
      },
    ],
  });
  expect(
    await screen.findByText(/el más antiguo espera 7 min/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/1 en curso \(el más antiguo, 45 s\)/),
  ).toBeInTheDocument();
});

async function configCard() {
  const title = await screen.findByText("Configuración cargada");
  const card = title.closest('[data-slot="card"]');
  if (!card) throw new Error("config card not found");
  return within(card as HTMLElement);
}

test("lists the alive processes with their revision and marks the one behind", async () => {
  renderWith({});
  const card = await configCard();
  expect(await card.findByText("Revisión 12", { exact: false })).toBeVisible();
  expect(card.getByText("web")).toBeInTheDocument();
  expect(card.getByText("worker-outbound")).toBeInTheDocument();
  expect(card.getByText("11 (atrasado)")).toBeInTheDocument();
  expect(card.getAllByText("12").length).toBeGreaterThan(0);
});

test("says so when no process has reported its configuration", async () => {
  renderWith({}, { ...CONFIG, processes: [] });
  const card = await configCard();
  expect(
    await card.findByText(/Ningún proceso ha informado/),
  ).toBeInTheDocument();
});
