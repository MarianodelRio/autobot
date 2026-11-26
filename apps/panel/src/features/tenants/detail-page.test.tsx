import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { confirmApplied } from "@/lib/config-applied";
import { qk } from "@/lib/queries";
import { TenantDetailPage } from "./detail-page";

vi.mock("@/lib/config-applied", () => ({ confirmApplied: vi.fn() }));
let errorsEmpty = false;
let failTenant = false;

const tenant = {
  slug: "demo",
  name: "Negocio",
  pack: "bus",
  status: "active",
  timezone: "Europe/Madrid",
  document: { id: "id", channel: { type: "telegram" }, testers: {}, owner: {} },
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
function setup(status = "active", initialTab?: string) {
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    let value: unknown;
    if (failTenant && url.pathname.endsWith("/tenants/demo"))
      return new Response("{}", { status: 500 });
    if (url.pathname.endsWith("/health-check")) value = [];
    else if (url.pathname.endsWith("/setup")) value = [];
    else if (url.pathname.includes("/packs/"))
      value = {
        document: {
          type: "object",
          properties: { name: { type: "string", title: "Nombre" } },
        },
        ui_schema: {
          groups: [{ key: "business", label: "Negocio", fields: ["name"] }],
        },
      };
    else if (url.pathname.endsWith("/secrets"))
      value = {
        channel_type: "telegram",
        readable: true,
        updated_at: null,
        updated_by: null,
        fields: [],
      };
    else if (url.pathname.endsWith("/summary"))
      value = {
        start: "2026-11-01T00:00:00Z",
        end: "2026-11-04T00:00:00Z",
        pack_lines: [],
        pack_failed: false,
        users: 4,
        messages: 10,
        cost_eur: "1.20",
      };
    else if (url.pathname.endsWith("/activity"))
      value =
        url.searchParams.get("status") === "errors" && !errorsEmpty
          ? {
              items: [
                {
                  id: "o9",
                  at: "2026-11-04T10:00:00Z",
                  kind: "outbound",
                  tenant: "demo",
                  channel: "telegram",
                  label: "Respuesta",
                  status: "failed",
                },
                {
                  id: "o8",
                  at: "2026-11-04T09:00:00Z",
                  kind: "outbound",
                  tenant: "demo",
                  channel: "telegram",
                  label: "Respuesta",
                  status: "discarded",
                },
              ],
              next_cursor: null,
            }
          : { items: [], next_cursor: null };
    else if (url.pathname.endsWith("/contacts/id1"))
      value = {
        contact: { display_name: "Ana", external_id: "123" },
        exchanges: [
          {
            outbound_id: "o",
            inbound: "Hola",
            outbound: "Buenos días",
            status: "sent",
            outbound_at: "2026-11-04T10:00:00Z",
          },
        ],
        state: { step: "booking" },
      };
    else if (url.pathname.endsWith("/contacts"))
      value = {
        items: [
          {
            id: "id1",
            display_name: "Ana",
            external_id: "123",
            phone_e164: null,
          },
        ],
        next_cursor: null,
      };
    else if (url.pathname.endsWith("/notifications"))
      value = {
        items: [
          {
            kind: "booking",
            text: "Aviso enviado",
            status: "sent",
            created_at: "2026-11-04T10:00:00Z",
            sent_at: null,
          },
        ],
        next_cursor: null,
      };
    else if (url.pathname.endsWith("/contacts/id1/export"))
      value = { tenant: "demo", data: { contact: [{ id: "id1" }] } };
    else if (url.pathname.endsWith("/contacts/id1/forget"))
      value = { forgotten: true };
    else if (url.pathname.endsWith("/tenants/demo/export"))
      value = { tenant: "demo", data: {} };
    else value = { ...tenant, status };
    return new Response(JSON.stringify(value), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TenantDetailPage slug="demo" initialTab={initialTab} />
    </QueryClientProvider>,
  );
  return Object.assign(fetcher, { client });
}
afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(confirmApplied).mockClear();
  failTenant = false;
});
test.each([
  ["active", "Pausar"],
  ["paused", "Reactivar"],
])("shows the action for %s", async (status, action) => {
  setup(status);
  expect(await screen.findByRole("button", { name: action })).toBeEnabled();
});
test("an onboarding tenant has no header action, only Activar in Configuración", async () => {
  setup("onboarding");
  await screen.findByRole("heading", { name: "Negocio" });
  expect(
    screen.queryByRole("button", { name: "Activar" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Alta" })).toBeNull();
  await userEvent
    .setup()
    .click(screen.getByRole("tab", { name: "Configuración" }));
  expect(await screen.findByRole("button", { name: "Activar" })).toBeEnabled();
});
test("loads tabs and pairs conversation messages", async () => {
  const fetcher = setup();
  const user = userEvent.setup();
  await screen.findByRole("heading", { name: "Negocio" });
  expect(
    fetcher.mock.calls.some((call) =>
      String((call[0] as Request).url).endsWith("/summary"),
    ),
  ).toBe(false);
  await user.click(screen.getByRole("button", { name: "Cargar" }));
  await screen.findByText(/Usuarios: 4/);
  await user.click(screen.getByRole("tab", { name: "Actividad" }));
  await screen.findByText("No hay actividad.");
  await user.click(screen.getByRole("tab", { name: "Contactos" }));
  await user.click(await screen.findByRole("button", { name: "Ana" }));
  const sheet = await screen.findByRole("dialog");
  expect(await within(sheet).findByText("Entrada: Hola")).toBeInTheDocument();
  expect(within(sheet).getByText(/Salida: Buenos días/)).toBeInTheDocument();
  expect(within(sheet).getByText(/booking/)).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await user.click(screen.getByRole("tab", { name: "Avisos" }));
  await screen.findByText("Aviso enviado");
});
test("health check is sent from the summary tab and displays its result", async () => {
  const fetcher = setup();
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: "Comprobar ahora" }),
  );
  expect(
    fetcher.mock.calls.some((call) => (call[0] as Request).method === "POST"),
  ).toBe(true);
  expect(confirmApplied).not.toHaveBeenCalled(); // a check is not a config change
});
test("a contact's data can be exported and the contact forgotten", async () => {
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  const fetcher = setup();
  const user = userEvent.setup();
  await screen.findByRole("heading", { name: "Negocio" });
  await user.click(screen.getByRole("tab", { name: "Contactos" }));
  await user.click(await screen.findByRole("button", { name: "Ana" }));
  await user.click(
    await screen.findByRole("button", { name: "Exportar datos" }),
  );
  await vi.waitFor(() => expect(clickSpy).toHaveBeenCalled());

  await user.click(screen.getByRole("button", { name: "Olvidar contacto" }));
  await user.type(await screen.findByLabelText(/olvidar/), "olvidar");
  await user.click(screen.getByRole("button", { name: "Olvidar" }));
  await vi.waitFor(() =>
    expect(
      fetcher.mock.calls.some((call) =>
        String((call[0] as Request).url).endsWith("/contacts/id1/forget"),
      ),
    ).toBe(true),
  );
  clickSpy.mockRestore();
  expect(confirmApplied).not.toHaveBeenCalled(); // forgetting a contact is not config
});

test("pausing a tenant asks for the «Aplicado en N procesos» confirmation", async () => {
  const user = userEvent.setup();
  setup("active");
  await user.click(await screen.findByRole("button", { name: "Pausar" }));
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Pausar" }));
  await vi.waitFor(() =>
    expect(confirmApplied).toHaveBeenCalledWith(expect.anything(), "demo"),
  );
});

test("a failed background refresh keeps the editor and its unsaved input", async () => {
  const user = userEvent.setup();
  const { client } = setup("active", "configuracion");
  await user.click(await screen.findByRole("button", { name: /^Negocio/ }));
  const name = await screen.findByLabelText("Nombre");
  await user.type(name, " nuevo");
  failTenant = true;
  await client.invalidateQueries({ queryKey: qk.tenant("demo") });
  expect(
    await screen.findByText(
      /No se pudo actualizar; se muestran los últimos datos/,
    ),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Nombre")).toHaveValue(" nuevo");
  expect(screen.getByRole("heading", { name: "Negocio" })).toBeInTheDocument();
  // Retrying once the backend is back clears the warning, the draft stays.
  failTenant = false;
  await user.click(screen.getByRole("button", { name: "Reintentar" }));
  await vi.waitFor(() =>
    expect(screen.queryByText(/No se pudo actualizar/)).toBeNull(),
  );
  expect(screen.getByLabelText("Nombre")).toHaveValue(" nuevo");
});

test("the Actividad tab filters the sends with an error and names their status", async () => {
  const user = userEvent.setup();
  const fetcher = setup("active", "actividad");
  const toggle = await screen.findByRole("button", {
    name: "Envíos con error",
  });
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  await user.click(toggle);

  expect(await screen.findByText("Rechazado")).toBeInTheDocument();
  expect(screen.getByText("Descartado")).toBeInTheDocument();
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  const asked = fetcher.mock.calls.some((call) =>
    String((call[0] as Request).url).includes("status=errors"),
  );
  expect(asked).toBe(true);
});

test("the errors filter with nothing to show says so", async () => {
  const user = userEvent.setup();
  errorsEmpty = true;
  try {
    setup("active", "actividad");
    expect(await screen.findByText("No hay actividad.")).toBeInTheDocument();
    await user.click(
      await screen.findByRole("button", { name: "Envíos con error" }),
    );
    expect(
      await screen.findByText("No hay envíos con error."),
    ).toBeInTheDocument();
  } finally {
    errorsEmpty = false;
  }
});
