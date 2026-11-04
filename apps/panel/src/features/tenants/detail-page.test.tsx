import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { TenantDetailPage } from "./detail-page";

vi.mock("qrcode.react", () => ({
  QRCodeSVG: ({ value, title }: { value: string; title: string }) => (
    <svg data-value={value}>
      <title>{title}</title>
    </svg>
  ),
}));

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
function setup(status = "active") {
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    let value: unknown;
    if (url.pathname.endsWith("/health-check")) value = [];
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
      value = { items: [], next_cursor: null };
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
      value = [
        {
          kind: "booking",
          text: "Aviso enviado",
          status: "sent",
          created_at: "2026-11-04T10:00:00Z",
          sent_at: null,
        },
      ];
    else if (url.pathname.endsWith("/datasets"))
      value = [
        {
          name: "timetable",
          version: 1,
          author: "op",
          created_at: "2026-11-04T10:00:00Z",
          comment: "actualizado",
          sha256: "abc",
        },
      ];
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
      <TenantDetailPage slug="demo" />
    </QueryClientProvider>,
  );
  return fetcher;
}
afterEach(() => vi.unstubAllGlobals());
test.each([
  ["active", "Pausar"],
  ["paused", "Reactivar"],
  ["onboarding", "Activar"],
])("shows the action for %s", async (status, action) => {
  setup(status);
  expect(await screen.findByRole("button", { name: action })).toBeEnabled();
});
test("loads tabs, displays the public QR and pairs conversation messages", async () => {
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
  await user.click(screen.getByRole("tab", { name: "Canal" }));
  expect(
    await screen.findByRole("link", { name: "https://t.me/example_bot" }),
  ).toHaveAttribute("href", "https://t.me/example_bot");
  expect(
    screen.getByTitle("QR del canal público").closest("svg"),
  ).toHaveAttribute("data-value", "https://t.me/example_bot");
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
  await user.click(screen.getByRole("tab", { name: "Datos" }));
  await screen.findByText(/timetable/);
});
test("health check is sent and displays its result", async () => {
  const fetcher = setup();
  const user = userEvent.setup();
  await user.click(
    await screen.findByRole("button", { name: "Comprobar salud" }),
  );
  expect(
    await screen.findByText("Comprobación completada sin problemas."),
  ).toBeInTheDocument();
  expect(
    fetcher.mock.calls.some((call) => (call[0] as Request).method === "POST"),
  ).toBe(true);
});
