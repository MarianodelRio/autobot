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
