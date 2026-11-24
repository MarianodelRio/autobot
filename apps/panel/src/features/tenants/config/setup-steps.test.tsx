import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Toaster } from "sonner";
import { afterEach, expect, test, vi } from "vitest";
import type { components } from "@/api/schema";
import { ConfigEditor } from "./editor";

// The editor is rendered on its own, not through the app's route tree: loading every
// route (rjsf, CodeMirror...) made these tests time out under the full suite.

afterEach(() => vi.unstubAllGlobals());

const TENANT: components["schemas"]["TenantDetail"] = {
  slug: "demo",
  name: "Negocio",
  pack: "bus",
  status: "onboarding",
  timezone: "Europe/Madrid",
  document: {
    id: "id",
    channel: { type: "telegram", bot_username: "demo_bot" },
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
  owner_invite_pending: false,
  month: { inbound: 12, outbound: 10, users: 4, cost_eur: "1.20" },
};

const STEPS = [
  {
    key: "document",
    section: "business",
    label: "Documento",
    why: "Un documento inválido no se puede activar.",
    state: "ok",
    blocking: true,
    detail: "El documento es válido.",
    values: [],
    tester_candidates: [],
    checkable: false,
  },
  {
    key: "health",
    section: "channel",
    label: "Salud del canal",
    why: "Un problema crítico de salud bloquea la activación.",
    state: "pending",
    blocking: true,
    detail: "Sin comprobar todavía.",
    values: [],
    tester_candidates: [],
    checkable: true,
  },
  {
    key: "tester",
    section: "people",
    label: "Mensaje de un tester",
    why: "Confirma que el canal principal responde de verdad antes de activar.",
    state: "pending",
    blocking: true,
    detail: "Pendiente.",
    values: [],
    tester_candidates: [
      { id: "999", display: "id 999", received_at: "2026-11-17T10:00:00Z" },
    ],
    checkable: false,
  },
];

const SCHEMA = {
  document: {
    type: "object",
    properties: { name: { type: "string", title: "Nombre" } },
  },
  ui_schema: {
    read_only: [],
    widgets: {},
    groups: [
      { key: "business", label: "Negocio", fields: ["name"] },
      { key: "channel", label: "Canal", fields: ["channel"] },
      { key: "people", label: "Dueño y testers", fields: ["owner", "testers"] },
    ],
  },
};

type Answer = { status?: number; value: unknown };

/** Renders the Configuración editor answering the steps, the schema, the channel's
 * own requests and whatever `handle` returns for the rest (actions, checks). */
function renderEditor({
  detail = TENANT,
  steps = STEPS as unknown[],
  handle = () => undefined,
}: {
  detail?: components["schemas"]["TenantDetail"];
  steps?: unknown[];
  handle?: (
    path: string,
    req: Request,
  ) => Promise<Answer | undefined> | Answer | undefined;
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const path = new URL(req.url).pathname;
    const answer: Answer =
      (await handle(path, req)) ??
      (path.endsWith("/setup")
        ? { value: steps }
        : path.includes("/packs/")
          ? { value: SCHEMA }
          : path.endsWith("/secrets")
            ? { value: { readable: true, fields: [] } }
            : path.endsWith("/telegram-webhook")
              ? { value: { registered: true } }
              : { value: detail });
    return new Response(JSON.stringify(answer.value), {
      status: answer.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <QueryClientProvider client={queryClient}>
      <Toaster />
      <ConfigEditor detail={detail} onDirtyChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

async function openSection(
  user: ReturnType<typeof userEvent.setup>,
  label: string,
) {
  const trigger = await screen.findByRole("button", {
    name: new RegExp(`^${label}`),
  });
  if (trigger.getAttribute("aria-expanded") !== "true")
    await user.click(trigger);
}

test("each step shows in its section, which opens by itself when it blocks the alta", async () => {
  const user = userEvent.setup();
  renderEditor({
    handle: (path) =>
      path.endsWith("/setup/check/health")
        ? {
            value: {
              ...STEPS[1],
              state: "ok",
              detail: "Sin problemas críticos.",
            },
          }
        : undefined,
  });
  // health (Canal) and tester (Dueño y testers) block the alta: their sections open.
  expect(await screen.findByText("Sin comprobar todavía.")).toBeInTheDocument();
  expect(screen.getByText("id 999")).toBeInTheDocument();
  // The Telegram webhook shows once, in the channel's own block, not as a step too.
  expect(
    screen.getAllByRole("button", { name: "Registrar webhook" }),
  ).toHaveLength(1);
  expect(screen.queryByText("Webhook de Telegram")).toBeNull();
  // «Documento» is ok: its section (Negocio) stays closed.
  expect(screen.queryByText("El documento es válido.")).toBeNull();
  await openSection(user, "Negocio");
  expect(screen.getByText("El documento es válido.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Comprobar" }));
  await screen.findByText("Sin problemas críticos.");
});

test("the alta banner counts the mandatory steps and links each missing one", async () => {
  const user = userEvent.setup();
  renderEditor({
    steps: [STEPS[0], { ...STEPS[1], blocking: false }, STEPS[2]],
  });
  const banner = await screen.findByRole("region", {
    name: "Progreso del alta",
  });
  expect(banner).toHaveTextContent("Alta: 1 de 2 pasos obligatorios listos");
  await user.click(screen.getByRole("button", { name: "Dueño y testers" }));
  await user.click(
    screen.getByRole("button", {
      name: "Mensaje de un tester (Dueño y testers)",
    }),
  );
  expect(
    screen.getByRole("button", { name: /^Dueño y testers/ }),
  ).toHaveAttribute("aria-expanded", "true");
});

test("an active tenant has no alta banner", async () => {
  renderEditor({ detail: { ...TENANT, status: "active" } });
  await screen.findByRole("button", { name: /^Negocio/ });
  expect(
    screen.queryByRole("region", { name: "Progreso del alta" }),
  ).toBeNull();
});

test("checks are locked while their section has unsaved changes", async () => {
  const user = userEvent.setup();
  renderEditor({
    steps: [
      { ...STEPS[0], key: "health", label: "Salud del canal", checkable: true },
    ],
  });
  await openSection(user, "Negocio");
  const check = screen.getByRole("button", { name: "Comprobar" });
  expect(check).toBeEnabled();
  await user.type(screen.getByLabelText("Nombre"), " nuevo");
  expect(check).toBeDisabled();
  expect(screen.getByText(/Guarda antes de comprobar/)).toBeInTheDocument();
});

test("lists recent non-tester senders and adds one as a tester", async () => {
  const user = userEvent.setup();
  renderEditor({
    handle: (path) =>
      path.endsWith("/setup/testers")
        ? { value: { ...STEPS[2], tester_candidates: [] } }
        : undefined,
  });
  await screen.findByText("id 999");
  await user.click(screen.getByRole("button", { name: "Añadir" }));
  await screen.findByText("Tester añadido.");
  expect(screen.queryByText("id 999")).not.toBeInTheDocument();
});

test("shows a downloadable QR for the public link in the channel section", async () => {
  renderEditor();
  await screen.findByText("QR del canal");
  expect(
    screen.getByRole("button", { name: "Descargar SVG" }),
  ).toBeInTheDocument();
});

test("Activar stays disabled while a blocking step isn't ok", async () => {
  const user = userEvent.setup();
  renderEditor();
  await user.click(await screen.findByRole("button", { name: "Activar" }));
  await user.type(screen.getByLabelText("Escribe demo"), "demo");
  const confirm = screen.getAllByRole("button", { name: "Activar" }).at(-1);
  expect(confirm).toBeDisabled(); // STEPS has blocking health/tester steps still pending
});

const WA_STEPS = [
  {
    key: "whatsapp_number",
    section: "channel",
    label: "Número registrado",
    why: "Un número sin registrar en la Cloud API no puede enviar ni recibir mensajes.",
    state: "pending",
    blocking: false,
    detail: "Pulsa «Comprobar» para consultarlo en Meta.",
    values: [],
    tester_candidates: [],
    checkable: true,
    action: { label: "Registrar número", needs_pin: true, confirm: false },
  },
  {
    key: "whatsapp_subscription",
    section: "channel",
    label: "App suscrita a la cuenta",
    why: "Sin la app suscrita a la cuenta de WhatsApp, Meta no le entrega los mensajes.",
    state: "pending",
    blocking: false,
    detail: "Pulsa «Comprobar» para consultarlo en Meta.",
    values: [],
    tester_candidates: [],
    checkable: true,
    action: { label: "Suscribir app", needs_pin: false, confirm: true },
  },
];

function renderWhatsApp(actionStatus: number, actionBody: unknown) {
  const actions: { path: string; body: unknown }[] = [];
  renderEditor({
    detail: { ...TENANT, channel_type: "whatsapp", public_link: null },
    steps: WA_STEPS,
    handle: async (path, req) => {
      if (!path.includes("/setup/action/")) return undefined;
      actions.push({ path, body: await req.json() });
      return { status: actionStatus, value: actionBody };
    },
  });
  return actions;
}

async function openChannel() {
  const user = userEvent.setup();
  await openSection(user, "Canal");
  await screen.findByText("Número registrado");
  return user;
}

test("registering a number asks for a 6-digit PIN and sends it", async () => {
  const actions = renderWhatsApp(200, {
    ...WA_STEPS[0],
    state: "ok",
    detail: "Número registrado en la Cloud API.",
  });
  const user = await openChannel();
  await user.click(screen.getByRole("button", { name: "Registrar número" }));
  expect(screen.getByText(/No se guarda en ningún sitio/)).toBeInTheDocument();
  const confirm = screen
    .getAllByRole("button", { name: "Registrar número" })
    .at(-1);
  await user.type(screen.getByLabelText("PIN de 6 dígitos"), "12345");
  expect(confirm).toBeDisabled();
  await user.type(screen.getByLabelText("PIN de 6 dígitos"), "6");
  expect(confirm).toBeEnabled();
  if (confirm) await user.click(confirm);
  await screen.findAllByText("Número registrado en la Cloud API.");
  expect(actions).toEqual([
    {
      path: "/api/panel/tenants/demo/setup/action/whatsapp_number",
      body: { pin: "123456" },
    },
  ]);
});

test("subscribing the app needs an explicit confirmation", async () => {
  const actions = renderWhatsApp(200, {
    ...WA_STEPS[1],
    state: "ok",
    detail: "App suscrita: el número ya puede recibir mensajes.",
  });
  const user = await openChannel();
  await user.click(screen.getByRole("button", { name: "Suscribir app" }));
  expect(actions).toEqual([]); // opening the dialog calls nothing
  expect(
    screen.getByText(/activa de verdad la recepción de mensajes/),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Sí, continuar" }));
  await screen.findAllByText(
    "App suscrita: el número ya puede recibir mensajes.",
  );
  expect(actions).toHaveLength(1);
  expect(actions[0]?.body).toEqual({});
});

test("a failed action shows the server's message", async () => {
  renderWhatsApp(502, {
    code: "unavailable",
    message: "Resultado desconocido: pulsa «Comprobar» antes de repetirlo.",
    details: [],
  });
  const user = await openChannel();
  await user.click(screen.getByRole("button", { name: "Suscribir app" }));
  await user.click(screen.getByRole("button", { name: "Sí, continuar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Resultado desconocido",
  );
});
