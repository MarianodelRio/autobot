import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { TenantListPage } from "./list-page";

afterEach(() => vi.unstubAllGlobals());
test("filters clients by search, pack and status", async () => {
  const row = {
    channel: "demo",
    health: "ok",
    inbound_month: 0,
    outbound_month: 0,
    cost_eur_month: "0",
    last_activity_at: null,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify([
            {
              ...row,
              slug: "ana",
              name: "Ana",
              pack: "salon",
              status: "active",
            },
            {
              ...row,
              slug: "bus",
              name: "Autobús",
              pack: "bus",
              status: "paused",
            },
          ]),
          { headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TenantListPage />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await screen.findByRole("link", { name: "Ana" });
  await user.selectOptions(screen.getByLabelText("Pack"), "bus");
  expect(screen.queryByRole("link", { name: "Ana" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Autobús" })).toHaveAttribute(
    "href",
    "/clientes/bus",
  );
  await user.selectOptions(screen.getByLabelText("Estado"), "active");
  expect(screen.getByText("No hay clientes que mostrar.")).toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText("Pack"), "");
  await user.type(screen.getByLabelText("Buscar clientes"), "ana");
  expect(screen.getByRole("link", { name: "Ana" })).toBeInTheDocument();
});
