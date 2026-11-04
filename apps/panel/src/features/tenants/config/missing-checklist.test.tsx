import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { MissingChecklist } from "./missing-checklist";

function provider(child: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(<QueryClientProvider client={client}>{child}</QueryClientProvider>);
}
function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

test("lists only the pending checks and marks the blocking ones", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json([
        {
          key: "document",
          label: "Documento",
          ok: true,
          blocking: true,
          detail: "",
        },
        {
          key: "channel",
          label: "Secretos",
          ok: false,
          blocking: true,
          detail: "Faltan secretos",
        },
        {
          key: "owner",
          label: "Dueño",
          ok: false,
          blocking: false,
          detail: "Sin enlazar",
        },
      ]),
    ),
  );
  provider(<MissingChecklist slug="test" />);
  await screen.findByText(/Secretos: Faltan secretos/);
  expect(screen.getByText(/\(bloqueante\)/)).toBeInTheDocument();
  expect(screen.getByText(/Dueño: Sin enlazar/)).toBeInTheDocument();
  expect(screen.queryByText(/Documento:/)).not.toBeInTheDocument();
});

test("reports when nothing is left pending", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json([])),
  );
  provider(<MissingChecklist slug="test" />);
  await screen.findByText("No quedan comprobaciones pendientes.");
});

test("shows an error state with retry on failure", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({}, 500)),
  );
  provider(<MissingChecklist slug="test" />);
  await screen.findByText("No se pudieron cargar las comprobaciones.");
});
