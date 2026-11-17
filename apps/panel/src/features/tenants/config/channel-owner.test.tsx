import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, expect, test, vi } from "vitest";
import type { components } from "@/api/schema";
import { CalendarSection } from "./calendar-section";
import { ChannelSection } from "./channel-section";
import { DatasetSection } from "./dataset-section";
import { OwnerSection } from "./owner-section";

afterEach(() => vi.unstubAllGlobals());

const detail = {
  slug: "demo",
  channel_type: "telegram",
  webhook_url: "https://example.test/webhook",
  public_link: null,
  owner_linked: false,
} as unknown as components["schemas"]["TenantDetail"];

function setup(
  ui: React.ReactNode,
  answer: (url: URL, method: string) => unknown,
) {
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    return new Response(JSON.stringify(answer(new URL(req.url), req.method)), {
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
      <form>{ui}</form>
    </QueryClientProvider>,
  );
  return { fetcher, client };
}

const secrets = {
  channel_type: "telegram",
  readable: true,
  updated_at: null,
  updated_by: null,
  fields: [],
};

test.each([
  [true, "Registrado"],
  [false, "Sin registrar"],
  [null, "Sin comprobar"],
])("webhook status %s shows %s", async (registered, label) => {
  setup(<ChannelSection detail={detail} />, (url) =>
    url.pathname.endsWith("/telegram-webhook") ? { registered } : secrets,
  );
  expect(await screen.findByText(label)).toBeInTheDocument();
});

test("C13: a missing public link warns instead of just hiding the QR", async () => {
  setup(<ChannelSection detail={detail} />, () => secrets);
  expect(
    await screen.findByText(/Falta el usuario del bot/),
  ).toBeInTheDocument();
});

test("C13: a QR with a public link offers SVG/PNG download and a print view", async () => {
  setup(
    <ChannelSection
      detail={{ ...detail, public_link: "https://t.me/mi_bot" }}
    />,
    (url) =>
      url.pathname.endsWith("/telegram-webhook")
        ? { registered: null }
        : secrets,
  );
  await screen.findByText("https://t.me/mi_bot");
  expect(
    screen.getByRole("button", { name: "Descargar SVG" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Descargar PNG" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Ver para imprimir" }),
  ).toBeInTheDocument();
});

test("registering the webhook refreshes its status", async () => {
  const user = userEvent.setup();
  let registered = false;
  const { fetcher } = setup(
    <ChannelSection detail={detail} />,
    (url, method) => {
      if (url.pathname.endsWith("/telegram-webhook")) {
        if (method === "POST") {
          registered = true;
          return { url: "https://example.test/webhook" };
        }
        return { registered };
      }
      return secrets;
    },
  );
  await screen.findByText("Sin registrar");
  const button = screen.getByRole("button", { name: "Registrar webhook" });
  expect(button).toHaveAttribute("type", "button");
  await user.click(button);
  await screen.findByText("Registrado");
  expect(
    fetcher.mock.calls.filter(
      ([r]) =>
        (r as Request).method === "GET" &&
        String((r as Request).url).endsWith("/telegram-webhook"),
    ).length,
  ).toBe(2);
});

test("the webhook status is not requested for other channels", async () => {
  const { fetcher } = setup(
    <ChannelSection detail={{ ...detail, channel_type: "whatsapp" }} />,
    () => ({ ...secrets, channel_type: "whatsapp" }),
  );
  await screen.findByText("Credenciales");
  expect(
    fetcher.mock.calls.some(([r]) =>
      String((r as Request).url).endsWith("/telegram-webhook"),
    ),
  ).toBe(false);
});

test.each([
  [true, true],
  [false, false],
])(
  "owner invite shows expiry and replaces_chat=%s",
  async (replaces, warns) => {
    const user = userEvent.setup();
    const { client } = setup(<OwnerSection detail={detail} />, () => ({
      url: "https://t.me/AvisosBot?start=abc",
      expires_at: "2026-11-10T10:30:00Z",
      replaces_chat: replaces,
    }));
    const invite = screen.getByRole("button", { name: "Invitar al dueño" });
    expect(invite).toHaveAttribute("type", "button");
    await user.click(invite);
    await screen.findByText("https://t.me/AvisosBot?start=abc");
    expect(screen.getByText(/Caduca el/)).toBeInTheDocument();
    const warning = screen.queryByText(
      "Ya hay un chat conectado; este enlace lo sustituirá cuando se use.",
    );
    expect(warning !== null).toBe(warns);
    // The link is never kept in the query cache.
    expect(
      JSON.stringify(
        client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ),
    ).not.toContain("start=abc");
  },
);

const salonDetail = {
  ...detail,
  pack: "salon",
  document: { config: { calendar_id: "demo@group.calendar.google.com" } },
} as unknown as components["schemas"]["TenantDetail"];

test("D1: shows the service account email with a copy affordance", async () => {
  setup(<CalendarSection detail={salonDetail} />, () => ({
    configured: true,
    email: "autobot@proyecto.iam.gserviceaccount.com",
  }));
  expect(
    await screen.findByText("autobot@proyecto.iam.gserviceaccount.com"),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Gmail personal/)).not.toBeInTheDocument();
});

test("D4: warns when calendar_id is a personal Gmail account", async () => {
  setup(
    <CalendarSection
      detail={{
        ...salonDetail,
        document: { config: { calendar_id: "peluquero@gmail.com" } },
      }}
    />,
    () => ({
      configured: true,
      email: "autobot@proyecto.iam.gserviceaccount.com",
    }),
  );
  expect(await screen.findByText(/Gmail personal/)).toBeInTheDocument();
});

test("warns when the server has no service account configured", async () => {
  setup(<CalendarSection detail={salonDetail} />, () => ({
    configured: false,
    email: null,
  }));
  expect(
    await screen.findByText(
      "El servidor no tiene configurada la cuenta de servicio de Google.",
    ),
  ).toBeInTheDocument();
});

test("C14: shows a pending invitation and lets you disconnect it", async () => {
  const toastSpy = vi.spyOn(toast, "success");
  const user = userEvent.setup();
  setup(
    <OwnerSection detail={{ ...detail, owner_invite_pending: true }} />,
    () => ({ had_chat: false }),
  );
  await screen.findByText("Invitación pendiente");
  await user.click(screen.getByRole("button", { name: "Desconectar" }));
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Desconectar" }));
  await waitFor(() =>
    expect(toastSpy).toHaveBeenCalledWith("Invitación cancelada."),
  );
});

test("C14: disconnecting a linked owner says so", async () => {
  const toastSpy = vi.spyOn(toast, "success");
  const user = userEvent.setup();
  setup(<OwnerSection detail={{ ...detail, owner_linked: true }} />, () => ({
    had_chat: true,
  }));
  await screen.findByText("Dueño enlazado");
  await user.click(screen.getByRole("button", { name: "Desconectar" }));
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Desconectar" }));
  await waitFor(() =>
    expect(toastSpy).toHaveBeenCalledWith("Dueño desconectado."),
  );
});

const busDetail = {
  ...detail,
  slug: "bus",
  pack: "bus",
  document: { config: {} },
} as unknown as components["schemas"]["TenantDetail"];

test("C23: warns without any dataset chosen yet", async () => {
  setup(<DatasetSection detail={busDetail} dataset="timetable" />, () => ({
    version: null,
    author: null,
    comment: "",
    created_at: null,
    source_name: null,
    source_version: null,
    newer_version_available: null,
  }));
  expect(
    await screen.findByText(/Sin horarios elegidos todavía/),
  ).toBeInTheDocument();
});

test("C23: offers Aplicar when a newer library version exists", async () => {
  const toastSpy = vi.spyOn(toast, "success");
  const user = userEvent.setup();
  setup(<DatasetSection detail={busDetail} dataset="timetable" />, (url) =>
    url.pathname.endsWith("/apply")
      ? { version: 2 }
      : {
          version: 1,
          author: "op",
          comment: "",
          created_at: "2026-11-01T00:00:00Z",
          source_name: "linea-cordoba",
          source_version: 1,
          newer_version_available: 2,
        },
  );
  await screen.findByText("Horarios en uso");
  expect(screen.getAllByText(/linea-cordoba/).length).toBeGreaterThan(0);
  expect(screen.getByText(/versión más nueva/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Aplicar" }));
  await user.click(screen.getByRole("button", { name: "Confirmar" }));
  await waitFor(() =>
    expect(toastSpy).toHaveBeenCalledWith("Horarios actualizados."),
  );
});
