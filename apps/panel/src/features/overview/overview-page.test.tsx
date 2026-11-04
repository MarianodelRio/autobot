import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { components } from "@/api/schema";
import { OverviewContent, OverviewPage } from "./overview-page";

type Overview = components["schemas"]["Overview"];
const data: Overview = {
  generated_at: "2026-11-04T10:00:00Z",
  status: { level: "ok", problems: [] },
  tenants: { active: 1, onboarding: 0, paused: 0, demos: 2, total: 3 },
  month: {
    start: "2026-11-01T00:00:00Z",
    inbound: 1240,
    outbound: 1310,
    users: 87,
    billable: 310,
    cost_eur: "12.40",
    by_day: [],
    metrics: [],
  },
  tenant_rows: [],
  incidents_open: 0,
  recent_alerts: [],
  system: {
    cpu_pct: null,
    mem_used_pct: null,
    disk_used_pct: null,
    last_backup_at: null,
    backup_ok: null,
    tls_days_left: null,
    release: "",
    deployed_at: null,
  },
};

test.each([
  ["ok", "Todo bien"],
  ["warning", "Atención"],
  ["critical", "Estado crítico"],
] as const)("shows %s status and linked problems", (level, title) => {
  render(
    <OverviewContent
      data={{
        ...data,
        status: {
          level,
          problems: [
            {
              text: "Canal sin secretos",
              tenant: "demo",
              link: "/clientes/demo",
            },
          ],
        },
      }}
    />,
  );
  expect(screen.getByText(title)).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Canal sin secretos" }),
  ).toHaveAttribute("href", "/clientes/demo");
});

test("formats KPIs and shows empty states", () => {
  render(<OverviewContent data={data} />);
  expect(screen.getByText("1.240 entrada")).toBeInTheDocument();
  expect(screen.getByText("1.310 salida")).toBeInTheDocument();
  expect(screen.getByText("87")).toBeInTheDocument();
  expect(screen.getByText(/12,40/)).toBeInTheDocument();
  expect(screen.getByText("No hay clientes.")).toBeInTheDocument();
  expect(screen.getByText("Sin mensajes este mes.")).toBeInTheDocument();
  expect(screen.getByText("Sin métricas este mes.")).toBeInTheDocument();
  expect(screen.getByText("No hay alertas.")).toBeInTheDocument();
});

afterEach(() => vi.unstubAllGlobals());
test("shows an error and allows retry", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 503 })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <OverviewPage />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText("No se pudo cargar el resumen."),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Reintentar" }),
  ).toBeInTheDocument();
});
