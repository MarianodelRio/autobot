import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
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

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

type Options = {
  items?: unknown[];
  history?: unknown[][];
  casePages?: { items: unknown[]; next_cursor: string | null }[];
};

function stubFetch({
  items = incidents,
  history = [[]],
  casePages = [],
}: Options = {}) {
  let open = [...items];
  let historyPage = 0;
  return vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    const path = url.pathname;
    if (path.endsWith("/me")) return json({ username: "operator" });
    if (path.endsWith("/overview"))
      return json({
        status: { level: "ok" },
        tenant_rows: [],
        incidents_open: open.length,
      });
    if (path.endsWith("/incidents/history")) {
      const page = history[historyPage] ?? [];
      historyPage += 1;
      return json({
        items: page,
        next_cursor: historyPage < history.length ? `c${historyPage}` : null,
      });
    }
    if (path.endsWith("/cases")) {
      const index = url.searchParams.get("cursor") ? 1 : 0;
      return json(casePages[index] ?? { items: [], next_cursor: null });
    }
    if (path.endsWith("/incidents"))
      return json({
        items: open,
        total: open.length,
        by_severity: { critical: 0, warning: open.length, notice: 0 },
      });
    if (path.endsWith("/review")) {
      const id = path.split("/").at(-2);
      open = open.filter((item) => (item as { id: string }).id !== id);
      return json({ message: "Hecho." });
    }
    if (path.endsWith("/discard")) return json({ message: "Hecho." });
    if (path.endsWith("/mark-sent"))
      return json({ message: "Envío marcado como enviado." });
    if (path.endsWith("/resend")) {
      const body = req.body ? await req.json() : null;
      if (body?.confirm_duplicate_risk !== true)
        return json({ code: "bad_request", message: "Confirme." }, 400);
      return json({ message: "Mensaje reenviado." });
    }
    if (path.endsWith("/retry"))
      return json({ message: "Trabajo reencolado." });
    return json({});
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

function fetched(fetcher: ReturnType<typeof stubFetch>, suffix: string) {
  return fetcher.mock.calls.filter(
    (call) =>
      (call[0] as Request).method === "GET" &&
      String((call[0] as Request).url).includes(suffix),
  ).length;
}

const WAIT = { timeout: 8000 };

async function openCases(
  user: ReturnType<typeof userEvent.setup>,
  name: RegExp,
) {
  const toggles = await screen.findAllByRole("button", { name }, WAIT);
  await user.click(toggles[0] as HTMLElement);
}

test("one card per incident with severity counts, scope, advice and runbook", async () => {
  vi.stubGlobal("fetch", stubFetch());
  renderPage();

  expect(
    await screen.findByText("Envíos sin confirmar", {}, WAIT),
  ).toBeInTheDocument();
  expect(screen.getByText("Plataforma")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "demo" })).toBeInTheDocument();
  expect(screen.getByText("Decide cada uno.")).toBeInTheDocument();
  // A condition closes by itself; an event offers the review.
  expect(
    screen.getByText("Se cierra sola cuando se arregle."),
  ).toBeInTheDocument();
  expect(
    screen.getAllByRole("button", { name: "Lo he revisado" }),
  ).toHaveLength(1);
  expect(
    screen
      .getAllByRole("link", { name: "Ver runbook" })[0]
      ?.getAttribute("href"),
  ).toBe("/docs/incidencias/envios-unknown/");
  expect(screen.getAllByRole("link", { name: "Ver logs" })).toHaveLength(2);
  // Cases are collapsed until asked for.
  expect(
    screen.queryByRole("button", { name: "Marcar enviado" }),
  ).not.toBeInTheDocument();
}, 10_000);

test("says what is new since the review", async () => {
  vi.stubGlobal("fetch", stubFetch());
  renderPage();
  expect(
    await screen.findByText(/1 nuevos desde tu revisión/, {}, WAIT),
  ).toBeInTheDocument();
}, 10_000);

test("an empty inbox says «Todo en orden»", async () => {
  vi.stubGlobal("fetch", stubFetch({ items: [] }));
  renderPage();
  expect(
    await screen.findByText("Todo en orden", {}, WAIT),
  ).toBeInTheDocument();
}, 10_000);

test("«Lo he revisado» confirms, calls the endpoint and the card disappears", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Lo he revisado" }, WAIT),
  );
  expect(posted(fetcher, "/incidents/a2/review")).toBe(false);
  const dialog = await screen.findByRole("alertdialog");
  const overviewBefore = fetched(fetcher, "/overview");
  await user.click(
    within(dialog).getByRole("button", { name: "Lo he revisado" }),
  );

  await waitFor(() =>
    expect(posted(fetcher, "/incidents/a2/review")).toBe(true),
  );
  await waitFor(() =>
    expect(screen.queryByText(/Trabajo fallido/)).not.toBeInTheDocument(),
  );
  // The sidebar counter comes from the overview: it is refreshed too.
  expect(fetched(fetcher, "/overview")).toBeGreaterThan(overviewBefore);
}, 10_000);

test("marking a send as sent posts without confirmation", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await openCases(user, /Ver 1 caso/);
  expect(screen.getByText("Sin confirmar")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Marcar enviado" }));
  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/mark-sent")).toBe(true),
  );
}, 10_000);

test("resending requires confirming the duplicate risk", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await openCases(user, /Ver 1 caso/);
  await user.click(screen.getByRole("button", { name: "Reenviar" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(
    within(dialog).getByText(/reenviar puede crear un duplicado/),
  ).toBeInTheDocument();
  expect(posted(fetcher, "/outbound/o1/resend")).toBe(false);
  await user.click(within(dialog).getByRole("button", { name: "Reenviar" }));
  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/resend")).toBe(true),
  );
}, 10_000);

test("discarding a send asks first and then posts", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await openCases(user, /Ver 1 caso/);
  await user.click(screen.getByRole("button", { name: "Descartar" }));
  expect(posted(fetcher, "/outbound/o1/discard")).toBe(false);
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Descartar" }));
  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/discard")).toBe(true),
  );
}, 10_000);

test("a rejected send shows its translated error and a disabled action keeps its reason", async () => {
  const user = userEvent.setup();
  const rejected = {
    ...sendCase,
    status: "failed",
    error_title: "Fuera de la ventana de 24 h",
    error_advice: "Solo se puede con plantilla.",
    can_resend: false,
    resend_reason: "Reintentar no sirve: el canal lo rechaza.",
  };
  vi.stubGlobal(
    "fetch",
    stubFetch({ items: [{ ...incidents[0], cases: [rejected] }] }),
  );
  renderPage();

  await openCases(user, /Ver 1 caso/);
  expect(screen.getByText("Rechazado")).toBeInTheDocument();
  expect(screen.getByText("Fuera de la ventana de 24 h")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reenviar" })).toBeDisabled();
  expect(
    screen.getByTitle("Reintentar no sirve: el canal lo rechaza."),
  ).toBeInTheDocument();
}, 10_000);

test("retries a failed job", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  const toggles = await screen.findAllByRole(
    "button",
    { name: /Ver 1 caso/ },
    WAIT,
  );
  await user.click(toggles[1] as HTMLElement);
  expect(screen.getByText("Comprobación de operación")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reintentar" }));
  await waitFor(() => expect(posted(fetcher, "/jobs/1/retry")).toBe(true));
}, 10_000);

test("a held notice links to the owner section of the tenant", async () => {
  const user = userEvent.setup();
  const notice = {
    type: "notice",
    id: "n1",
    status: "held",
    created_at: "2026-11-04T09:00:00Z",
  };
  vi.stubGlobal(
    "fetch",
    stubFetch({
      items: [{ ...incidents[0], kind: "owner_unlinked", cases: [notice] }],
    }),
  );
  renderPage();

  await openCases(user, /Ver 1 caso/);
  const link = screen.getByRole("link", { name: "Invitar al dueño" });
  expect(link.getAttribute("href")).toContain("/clientes/demo");
  expect(link.getAttribute("href")).toContain("section=personas");
}, 10_000);

test("«Ver más» loads further cases page by page", async () => {
  const user = userEvent.setup();
  const mk = (id: string) => ({ ...sendCase, id });
  const fetcher = stubFetch({
    items: [{ ...incidents[0], case_count: 3, cases: [mk("o1")] }],
    casePages: [
      { items: [mk("o1"), mk("o2")], next_cursor: "next" },
      { items: [mk("o3")], next_cursor: null },
    ],
  });
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await openCases(user, /Ver 3 casos/);
  expect(
    screen.getAllByRole("button", { name: "Marcar enviado" }),
  ).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Ver más" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Marcar enviado" }),
    ).toHaveLength(2),
  );
  await user.click(screen.getByRole("button", { name: "Ver más" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Marcar enviado" }),
    ).toHaveLength(3),
  );
  expect(
    screen.queryByRole("button", { name: "Ver más" }),
  ).not.toBeInTheDocument();
}, 10_000);

const closed = (
  id: string,
  closedHow: string,
  severity: string,
  by: string | null = null,
) => ({
  id,
  kind: "x",
  nature: "event",
  tenant: null,
  severity,
  title: `Cerrada ${id}`,
  text: "",
  runbook: null,
  case_count: 2,
  first_seen_at: "2026-11-01T09:00:00Z",
  last_seen_at: "2026-11-01T10:00:00Z",
  resolved_at: "2026-11-02T10:00:00Z",
  closed: closedHow,
  closed_by: by,
});

test("the history shows how each one closed, handles info and unknown severities and paginates", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch({
      items: [],
      history: [
        [
          closed("h1", "auto", "warning"),
          closed("h2", "review", "critical", "ana"),
          closed("h3", "info", "info"),
        ],
        [closed("h4", "auto", "mystery")],
      ],
    }),
  );
  renderPage();

  await user.click(await screen.findByText("Historial", {}, WAIT));
  expect(await screen.findByText("Cerrada h1", {}, WAIT)).toBeInTheDocument();
  expect(screen.getByText(/Se cerró sola/)).toBeInTheDocument();
  expect(screen.getByText(/Revisada por ana/)).toBeInTheDocument();
  expect(screen.getByText(/Informativa/)).toBeInTheDocument();
  expect(screen.getByText("Info")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cargar más" }));
  expect(await screen.findByText("Cerrada h4", {}, WAIT)).toBeInTheDocument();
  expect(screen.getByText("Desconocido")).toBeInTheDocument();
}, 10_000);
