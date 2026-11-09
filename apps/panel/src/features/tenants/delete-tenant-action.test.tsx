import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { routeTree } from "@/routeTree.gen";

afterEach(() => vi.unstubAllGlobals());

const base = {
  slug: "demo",
  name: "Negocio",
  pack: "bus",
  status: "paused",
  timezone: "Europe/Madrid",
  document: {
    id: "id",
    channel: { type: "telegram" },
    testers: {},
    owner: {},
  } as Record<string, unknown>,
  version: 1,
  degraded: [],
  ambiguous: false,
  main_disabled: [],
  health: "ok",
  health_reasons: [],
  health_checked_at: null,
  open_alerts: [],
  channel_type: "telegram",
  webhook_url: "https://example.test/webhook",
  public_link: "https://t.me/example_bot",
  owner_linked: false,
  month: { inbound: 12, outbound: 10, users: 4, cost_eur: "1.20" },
};

function renderAt(path: string, tenant: typeof base) {
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    let value: unknown;
    if (url.pathname.endsWith("/me")) value = { username: "operator" };
    else if (url.pathname.endsWith("/overview"))
      value = { status: { level: "ok" }, tenant_rows: [] };
    else if (url.pathname.endsWith("/delete")) {
      const body = request instanceof Request ? await request.json() : {};
      value =
        body.confirm_slug === tenant.slug
          ? { telegram_webhook_removed: true }
          : { code: "bad_request", message: "no" };
    } else if (url.pathname.endsWith("/health-check")) value = [];
    else if (url.pathname.endsWith("/secrets"))
      value = {
        channel_type: "telegram",
        readable: true,
        updated_at: null,
        updated_by: null,
        fields: [],
      };
    else if (url.pathname.endsWith("/activity"))
      value = { items: [], next_cursor: null };
    else if (url.pathname.endsWith("/contacts"))
      value = { items: [], next_cursor: null };
    else if (url.pathname.endsWith("/notifications")) value = [];
    else if (url.pathname.endsWith(`/tenants/${tenant.slug}/summary`))
      value = {
        start: "2026-11-01T00:00:00Z",
        end: "2026-11-04T00:00:00Z",
        pack_lines: [],
        pack_failed: false,
        users: 0,
        messages: 0,
        cost_eur: "0",
      };
    else value = tenant;
    return new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

test("hidden for a demo tenant", async () => {
  renderAt("/clientes/demo", {
    ...base,
    document: { ...base.document, demo: { description: "x" } },
  });
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  expect(
    screen.queryByRole("button", { name: "Más acciones" }),
  ).not.toBeInTheDocument();
}, 10_000);

test("disabled while the tenant is active, with an explanation", async () => {
  const user = userEvent.setup();
  renderAt("/clientes/demo", { ...base, status: "active" });
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  await user.click(screen.getByRole("button", { name: "Más acciones" }));
  expect(
    screen.getByRole("menuitem", { name: "Eliminar cliente" }),
  ).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByText("Páusalo antes de eliminarlo.")).toBeInTheDocument();
}, 10_000);

test("requires typing the exact slug, then deletes and returns to the list", async () => {
  const user = userEvent.setup();
  const router = renderAt("/clientes/demo", base);
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  await user.click(screen.getByRole("button", { name: "Más acciones" }));
  await user.click(screen.getByRole("menuitem", { name: "Eliminar cliente" }));
  const confirmButton = await screen.findByRole("button", {
    name: "Eliminar",
  });
  expect(confirmButton).toBeDisabled();

  const input = screen.getByLabelText(/demo/);
  await user.type(input, "wrong");
  expect(confirmButton).toBeDisabled();
  await user.clear(input);
  await user.type(input, "demo");
  expect(confirmButton).toBeEnabled();

  await user.click(confirmButton);
  await vi.waitFor(() =>
    expect(router.state.location.pathname).toBe("/clientes"),
  );
}, 10_000);
