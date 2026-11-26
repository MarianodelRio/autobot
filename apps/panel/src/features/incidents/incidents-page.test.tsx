import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { routeTree } from "@/routeTree.gen";

afterEach(() => vi.unstubAllGlobals());

const base = {
  tenant_id: "t1",
  tenant: "demo",
  severity: "warning",
  text: "🟠 demo: algo",
  first_seen_at: "2026-11-04T09:00:00Z",
  last_seen_at: "2026-11-04T10:00:00Z",
  last_case_at: "2026-11-04T10:00:00Z",
  delivery: "sent",
};

const sendCase = {
  type: "send",
  id: "o1",
  channel: "telegram",
  status: "unknown",
  created_at: "2026-11-04T09:00:00Z",
  error_class: null,
  error_title: null,
  error_advice: null,
  can_mark_sent: true,
  mark_sent_reason: null,
  can_resend: true,
  resend_reason: null,
  can_discard: true,
  discard_reason: null,
};

const jobCase = {
  type: "job",
  id: 1,
  task: "ops_check",
  task_label: "Comprobación de operación",
  failed_at: "2026-11-04T09:00:00Z",
  can_retry: true,
  retry_reason: null,
};

const incidents = [
  {
    ...base,
    id: "a1",
    kind: "outbound_ambiguous",
    nature: "condition",
    title: "Envíos sin confirmar",
    advice: "Decide cada uno.",
    runbook: "/docs/incidencias/envios-unknown/",
    case_count: 1,
    new_since_review: null,
    reviewable: false,
    cases: [sendCase],
  },
  {
    ...base,
    id: "a2",
    kind: "failed_job:ops_check",
    tenant_id: null,
    tenant: null,
    nature: "event",
    title: "Trabajo fallido: Comprobación de operación",
    advice: "Reinténtala.",
    runbook: null,
    case_count: 1,
    new_since_review: 1,
    reviewable: true,
    cases: [jobCase],
  },
];

function stubFetch() {
  return vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    if (url.pathname.endsWith("/me"))
      return new Response(JSON.stringify({ username: "operator" }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/overview"))
      return new Response(
        JSON.stringify({ status: { level: "ok" }, tenant_rows: [] }),
        { headers: { "Content-Type": "application/json" } },
      );
    if (url.pathname.endsWith("/incidents/history"))
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/incidents"))
      return new Response(
        JSON.stringify({
          items: incidents,
          total: 2,
          by_severity: { critical: 0, warning: 2, notice: 0 },
        }),
        { headers: { "Content-Type": "application/json" } },
      );
    if (url.pathname.endsWith("/incidents/history"))
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/review") || url.pathname.endsWith("/discard"))
      return new Response(JSON.stringify({ message: "Hecho." }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/mark-sent"))
      return new Response(
        JSON.stringify({ message: "Envío marcado como enviado." }),
        { headers: { "Content-Type": "application/json" } },
      );
    if (url.pathname.endsWith("/resend")) {
      const body = req.body ? await req.json() : null;
      if (body?.confirm_duplicate_risk !== true)
        return new Response(
          JSON.stringify({
            code: "bad_request",
            message: "Confirme el riesgo.",
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        );
      return new Response(JSON.stringify({ message: "Mensaje reenviado." }), {
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.pathname.endsWith("/retry"))
      return new Response(JSON.stringify({ message: "Trabajo reencolado." }), {
        headers: { "Content-Type": "application/json" },
      });
    return new Response(JSON.stringify({}), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

function renderPage() {
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: ["/incidencias"] }),
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function posted(fetcher: ReturnType<typeof stubFetch>, suffix: string) {
  return fetcher.mock.calls.some(
    (call) =>
      (call[0] as Request).method === "POST" &&
      String((call[0] as Request).url).endsWith(suffix),
  );
}

test("an incident with a runbook links to it in the docs", async () => {
  vi.stubGlobal("fetch", stubFetch());
  renderPage();

  const links = await screen.findAllByRole(
    "link",
    { name: "Ver runbook" },
    { timeout: 8000 },
  );
  expect(links[0]?.getAttribute("href")).toBe(
    "/docs/incidencias/envios-unknown/",
  );
}, 10_000);

test("an event is closed with «Lo he revisado» and says what is new", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  expect(
    await screen.findByText(
      /1 nuevos desde tu revisión/,
      {},
      { timeout: 8000 },
    ),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Lo he revisado" }));
  await waitFor(() =>
    expect(posted(fetcher, "/incidents/a2/review")).toBe(true),
  );
}, 10_000);

test("marking a send as sent posts without confirmation", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole(
      "button",
      { name: "Marcar enviado" },
      { timeout: 8000 },
    ),
  );

  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/mark-sent")).toBe(true),
  );
}, 10_000);

test("resending a message requires confirming the duplicate risk", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Reenviar" }, { timeout: 8000 }),
  );
  expect(
    screen.getByText(/reenviar puede crear un duplicado/),
  ).toBeInTheDocument();
  expect(posted(fetcher, "/outbound/o1/resend")).toBe(false);

  const buttons = screen.getAllByRole("button", { name: "Reenviar" });
  const confirmButton = buttons.at(-1);
  if (!confirmButton) throw new Error("confirm button not found");
  await user.click(confirmButton);

  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/resend")).toBe(true),
  );
}, 10_000);

test("retries a failed job", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole(
      "button",
      { name: "Reintentar" },
      { timeout: 8000 },
    ),
  );

  await waitFor(() => expect(posted(fetcher, "/jobs/1/retry")).toBe(true));
}, 10_000);

test("discards an ambiguous send", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Descartar" }, { timeout: 8000 }),
  );
  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/discard")).toBe(true),
  );
}, 10_000);
