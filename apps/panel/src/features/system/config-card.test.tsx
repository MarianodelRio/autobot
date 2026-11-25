import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ConfigCard } from "./config-card";

afterEach(() => vi.unstubAllGlobals());

const PROCESS = {
  service: "web",
  host: "box",
  pid: 1,
  revision: 12,
  started_at: "2026-11-25T10:00:00Z",
  seen_at: "2026-11-25T11:59:50Z",
  behind: false,
  last_error_at: null,
};

function renderWith(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ConfigCard />
    </QueryClientProvider>,
  );
}

test("marks a process whose configuration checks fail as an error", async () => {
  renderWith({
    revision: 12,
    updated_at: null,
    processes: [
      PROCESS,
      {
        ...PROCESS,
        service: "worker-inbound",
        pid: 2,
        revision: 11,
        behind: true,
        last_error_at: "2026-11-25T11:50:00Z",
      },
      { ...PROCESS, service: "web-panel", pid: 3, revision: 10, behind: true },
    ],
  });
  expect(await screen.findByText("11 (error al recargar)")).toBeInTheDocument();
  expect(screen.getByText("10 (atrasado)")).toBeInTheDocument();
  expect(screen.getByText("12")).toBeInTheDocument();
});

test("says it could not read the state of the configuration", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new TypeError("network down");
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ConfigCard />
    </QueryClientProvider>,
  );
  expect(
    await screen.findByText("No se pudo leer el estado de la configuración."),
  ).toBeInTheDocument();
});
