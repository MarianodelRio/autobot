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

const TENANT = {
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
  month: { inbound: 12, outbound: 10, users: 4, cost_eur: "1.20" },
};

const STEPS = [
  {
    key: "document",
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
    key: "webhook",
    label: "Webhook de Telegram",
    why: "Sin el webhook registrado, Telegram nunca entrega los mensajes.",
    state: "pending",
    blocking: true,
    detail: "Pulsa «Comprobar» para consultarlo en Telegram.",
    values: [
      {
        label: "URL esperada",
        value: "https://x/webhooks/telegram/abc",
        copiable: true,
      },
    ],
    tester_candidates: [],
    checkable: true,
  },
  {
    key: "tester",
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

function renderAt(
  checkResult: Record<string, unknown>,
  addTesterResult?: Record<string, unknown>,
) {
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: ["/clientes/demo"] }),
  });
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    let value: unknown;
    if (url.pathname.endsWith("/me")) value = { username: "operator" };
    else if (url.pathname.endsWith("/overview"))
      value = { status: { level: "ok" }, tenant_rows: [] };
    else if (url.pathname.endsWith("/setup/check/webhook")) value = checkResult;
    else if (url.pathname.endsWith("/setup/testers")) value = addTesterResult;
    else if (url.pathname.endsWith("/setup")) value = STEPS;
    else value = TENANT;
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
}

test("lists the steps and lets a checkable one be re-checked", async () => {
  const user = userEvent.setup();
  renderAt({
    key: "webhook",
    label: "Webhook de Telegram",
    why: "Sin el webhook registrado, Telegram nunca entrega los mensajes.",
    state: "ok",
    blocking: true,
    detail: "Registrado.",
    values: [
      {
        label: "URL esperada",
        value: "https://x/webhooks/telegram/abc",
        copiable: true,
      },
    ],
    checkable: true,
  });
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  await user.click(screen.getByRole("tab", { name: "Alta" }));
  await screen.findByText("Documento");
  expect(
    screen.getByText("Pulsa «Comprobar» para consultarlo en Telegram."),
  ).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Comprobar" }));
  await screen.findByText("Registrado.");
}, 10_000);

test("lists recent non-tester senders and adds one as a tester", async () => {
  const user = userEvent.setup();
  renderAt(
    {},
    {
      key: "tester",
      label: "Mensaje de un tester",
      why: "Confirma que el canal principal responde de verdad antes de activar.",
      state: "pending",
      blocking: true,
      detail: "Pendiente.",
      values: [],
      tester_candidates: [],
      checkable: false,
    },
  );
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  await user.click(screen.getByRole("tab", { name: "Alta" }));
  await screen.findByText("id 999");
  await user.click(screen.getByRole("button", { name: "Añadir" }));
  await screen.findByText("Tester añadido.");
  expect(screen.queryByText("id 999")).not.toBeInTheDocument();
}, 10_000);

test("C13: shows a downloadable QR for the public link", async () => {
  const user = userEvent.setup();
  renderAt({});
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  await user.click(screen.getByRole("tab", { name: "Alta" }));
  await screen.findByText("QR del canal");
  expect(
    screen.getByRole("button", { name: "Descargar SVG" }),
  ).toBeInTheDocument();
}, 10_000);

test("C12: Activar in the Alta tab stays disabled while a blocking step isn't ok", async () => {
  const user = userEvent.setup();
  renderAt({});
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  await user.click(screen.getByRole("tab", { name: "Alta" }));
  const openButtons = await screen.findAllByRole("button", { name: "Activar" });
  await user.click(openButtons[0]!);
  await user.type(screen.getByLabelText("Escribe demo"), "demo");
  const confirm = screen.getAllByRole("button", { name: "Activar" }).at(-1);
  expect(confirm).toBeDisabled(); // STEPS has blocking webhook/tester steps still pending
}, 10_000);

const WA_STEPS = [
  {
    key: "whatsapp_number",
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
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: ["/clientes/demo"] }),
  });
  const actions: { path: string; body: unknown }[] = [];
  const fetcher = vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    let status = 200;
    let value: unknown;
    if (url.pathname.endsWith("/me")) value = { username: "operator" };
    else if (url.pathname.endsWith("/overview"))
      value = { status: { level: "ok" }, tenant_rows: [] };
    else if (url.pathname.includes("/setup/action/")) {
      actions.push({ path: url.pathname, body: await req.json() });
      status = actionStatus;
      value = actionBody;
    } else if (url.pathname.endsWith("/setup")) value = WA_STEPS;
    else value = { ...TENANT, channel_type: "whatsapp", public_link: null };
    return new Response(JSON.stringify(value), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetcher);
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return actions;
}

async function openAlta() {
  const user = userEvent.setup();
  await screen.findByRole("heading", { name: "Negocio" }, { timeout: 8000 });
  await user.click(screen.getByRole("tab", { name: "Alta" }));
  await screen.findByText("Número registrado");
  return user;
}

test("C18: registering a number asks for a 6-digit PIN and sends it", async () => {
  const actions = renderWhatsApp(200, {
    ...WA_STEPS[0],
    state: "ok",
    detail: "Número registrado en la Cloud API.",
  });
  const user = await openAlta();
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
}, 10_000);

test("C18: subscribing the app needs an explicit confirmation", async () => {
  const actions = renderWhatsApp(200, {
    ...WA_STEPS[1],
    state: "ok",
    detail: "App suscrita: el número ya puede recibir mensajes.",
  });
  const user = await openAlta();
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
}, 10_000);

test("C18: a failed action shows the server's message", async () => {
  renderWhatsApp(502, {
    code: "unavailable",
    message: "Resultado desconocido: pulsa «Comprobar» antes de repetirlo.",
    details: [],
  });
  const user = await openAlta();
  await user.click(screen.getByRole("button", { name: "Suscribir app" }));
  await user.click(screen.getByRole("button", { name: "Sí, continuar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Resultado desconocido",
  );
}, 10_000);
