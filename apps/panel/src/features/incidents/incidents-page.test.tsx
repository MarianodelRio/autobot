import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { qk } from "@/lib/queries";
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
  has_cases: true,
  can_discard_all: false,
  cases_next_cursor: null,
};

const sendCase = {
  type: "send",
  id: "o1",
  channel: "telegram",
  status: "unknown",
  created_at: "2026-11-04T09:00:00Z",
  case_at: "2026-11-04T09:00:00Z",
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
  /** Responses that fail: the end of the path -> HTTP status. */
  failing?: Record<string, number>;
  /** The open list fails to refresh from the Nth GET on (0 = never). */
  failListAfter?: number;
  /** A POST to this path suffix never answers (an action in flight). */
  hold?: string;
};

type Open = {
  id: string;
  cases: { id: string | number; type: string }[];
  case_count: number;
};

/** Request bodies by path suffix, for the last stub. */
let bodies: Record<string, unknown> = {};

/** A stateful backend: an action removes its case (and the incident with its last
 * one), so what the screen shows after a refresh is what the server would say. */
function stubFetch({
  items = incidents,
  history = [[]],
  casePages = [],
  failing = {},
  failListAfter = 0,
  hold,
}: Options = {}) {
  let open = structuredClone(items) as Open[];
  let historyPage = 0;
  let listCalls = 0;
  bodies = {};
  const dropCase = (id: string | number) => {
    for (const item of open) {
      const before = item.cases.length;
      item.cases = item.cases.filter((c) => c.id !== id);
      if (item.cases.length < before) item.case_count -= 1;
    }
    open = open.filter((item) => item.case_count > 0);
  };
  return vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    const path = url.pathname;
    if (req.method === "POST") {
      const text = await req.clone().text();
      bodies[path] = text ? JSON.parse(text) : null;
    }
    if (hold && req.method === "POST" && path.endsWith(hold))
      return new Promise<Response>(() => {});
    for (const [suffix, status] of Object.entries(failing))
      if (req.method === "POST" && path.endsWith(suffix))
        return json({ code: "conflict", message: "Ya no se puede." }, status);
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
      const index = url.searchParams.get("cursor") === "p2" ? 1 : 0;
      return json(casePages[index] ?? { items: [], next_cursor: null });
    }
    if (path.endsWith("/incidents")) {
      listCalls += 1;
      if (failListAfter && listCalls >= failListAfter)
        return json({ code: "boom", message: "Caído." }, 500);
      return json({
        items: open,
        total: open.length,
        by_severity: { critical: 0, warning: open.length, notice: 0 },
      });
    }
    if (path.endsWith("/review") || path.endsWith("/discard-all")) {
      const id = path.split("/").at(-2);
      open = open.filter((item) => item.id !== id);
      return json({ message: "Hecho." });
    }
    for (const action of ["/discard", "/mark-sent", "/resend"])
      if (path.endsWith(action)) {
        dropCase(path.split("/").at(-2) as string);
        return json({ message: "Hecho." });
      }
    if (path.endsWith("/retry")) {
      dropCase(Number(path.split("/").at(-2)));
      return json({ message: "Trabajo reencolado." });
    }
    return json({});
  });
}

let lastClient: QueryClient | undefined;

function renderPage() {
  const queryClient = new QueryClient();
  lastClient = queryClient;
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

function reviewPath() {
  return (
    Object.keys(bodies).find((p) => p.endsWith("/incidents/a2/review")) ?? ""
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
  // The ambiguous sends are open by default; the other cases wait to be asked for.
  expect(
    screen.getByRole("button", { name: "Marcar enviado" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Reintentar" }),
  ).not.toBeInTheDocument();
}, 10_000);

test("says what is new since the review", async () => {
  vi.stubGlobal("fetch", stubFetch());
  renderPage();
  expect(
    await screen.findByText(/1 nuevo desde tu revisión/, {}, WAIT),
  ).toBeInTheDocument();
}, 10_000);

test("an empty inbox says «Todo en orden»", async () => {
  vi.stubGlobal("fetch", stubFetch({ items: [] }));
  renderPage();
  expect(
    await screen.findByText("Todo en orden", {}, WAIT),
  ).toBeInTheDocument();
}, 10_000);

test("«Lo he revisado» is one click, sends what is displayed and the card disappears", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  const overviewBefore = fetched(fetcher, "/overview");
  await user.click(
    await screen.findByRole("button", { name: "Lo he revisado" }, WAIT),
  );
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  await waitFor(() =>
    expect(posted(fetcher, "/incidents/a2/review")).toBe(true),
  );
  expect(bodies[reviewPath()]).toEqual({
    last_case_at: "2026-11-04T10:00:00Z",
  });
  await waitFor(() =>
    expect(screen.queryByText(/Trabajo fallido/)).not.toBeInTheDocument(),
  );
  // The sidebar counter comes from the overview: it is refreshed too.
  expect(fetched(fetcher, "/overview")).toBeGreaterThan(overviewBefore);
}, 10_000);

test("a review that conflicts shows its error and keeps the card", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch({ failing: { "/review": 409 } }));
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Lo he revisado" }, WAIT),
  );
  expect(await screen.findByText("Ya no se puede.")).toBeInTheDocument();
  expect(screen.getByText(/Trabajo fallido/)).toBeInTheDocument();
}, 10_000);

test("marking a send as sent posts without confirmation", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();
  lastClient?.setQueryData(qk.tenant("demo"), {});
  lastClient?.setQueryData(qk.activity("demo", "", ""), { pages: [] });

  // The ambiguous sends are open by default.
  expect(
    await screen.findByText("Sin confirmar", {}, WAIT),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Marcar enviado" }));
  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/mark-sent")).toBe(true),
  );
  // After the refresh the case (and its incident) is gone, and the tenant's
  // detail and activity were refreshed too.
  await waitFor(() =>
    expect(screen.queryByText("Envíos sin confirmar")).not.toBeInTheDocument(),
  );
  // The tenant's detail and activity (cached from its own screens) go stale.
  for (const key of [qk.tenant("demo"), qk.activity("demo", "", "")])
    expect(lastClient?.getQueryState(key)?.isInvalidated).toBe(true);
}, 10_000);

test("resending requires confirming the duplicate risk", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Reenviar" }, WAIT),
  );
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

  await user.click(
    await screen.findByRole("button", { name: "Descartar" }, WAIT),
  );
  expect(posted(fetcher, "/outbound/o1/discard")).toBe(false);
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Descartar" }));
  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/discard")).toBe(true),
  );
  await waitFor(() =>
    expect(screen.queryByText("Envíos sin confirmar")).not.toBeInTheDocument(),
  );
}, 10_000);

test("a rejected send shows its translated error and no dead buttons", async () => {
  const rejected = {
    ...sendCase,
    status: "failed",
    error_title: "Fuera de la ventana de 24 h",
    error_advice: "Solo se puede con plantilla.",
    can_mark_sent: false,
    can_resend: false,
    can_discard: false,
    resend_reason: "Reintentar no sirve: el canal lo rechaza.",
  };
  vi.stubGlobal(
    "fetch",
    stubFetch({ items: [{ ...incidents[0], cases: [rejected] }] }),
  );
  renderPage();

  expect(await screen.findByText("Rechazado", {}, WAIT)).toBeInTheDocument();
  expect(screen.getByText("Fuera de la ventana de 24 h")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Reenviar" }),
  ).not.toBeInTheDocument();
}, 10_000);

test("an ambiguous send with a disabled action shows the reason as text", async () => {
  const ambiguous = {
    ...sendCase,
    can_resend: false,
    resend_reason: "Aún no ha pasado el plazo de conciliación.",
  };
  vi.stubGlobal(
    "fetch",
    stubFetch({ items: [{ ...incidents[0], cases: [ambiguous] }] }),
  );
  renderPage();

  expect(
    await screen.findByText(
      "Aún no ha pasado el plazo de conciliación.",
      {},
      WAIT,
    ),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reenviar" })).toBeDisabled();
}, 10_000);

test("a send's buttons stay off while one of its actions is running", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch({ hold: "/mark-sent" }));
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Marcar enviado" }, WAIT),
  );
  expect(screen.getByRole("button", { name: "Descartar" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Reenviar" })).toBeDisabled();
}, 10_000);

test("a failed send action shows its error inline", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch({ failing: { "/mark-sent": 409 } }));
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Marcar enviado" }, WAIT),
  );
  expect(await screen.findByText("Ya no se puede.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Descartar" })).toBeEnabled();
}, 10_000);

test("retries a failed job and the card goes after the refresh", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: /Ver 1 caso/ }, WAIT),
  );
  expect(screen.getByText("Comprobación de operación")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reintentar" }));
  await waitFor(() => expect(posted(fetcher, "/jobs/1/retry")).toBe(true));
  await waitFor(() =>
    expect(screen.queryByText(/Trabajo fallido/)).not.toBeInTheDocument(),
  );
}, 10_000);

test("a job that cannot be retried shows the backend error inline", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch({ failing: { "/retry": 409 } }));
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: /Ver 1 caso/ }, WAIT),
  );
  await user.click(screen.getByRole("button", { name: "Reintentar" }));
  expect(await screen.findByText("Ya no se puede.")).toBeInTheDocument();
}, 10_000);

test("«Invitar al dueño» is one link on the card, only for owner_unlinked", async () => {
  const user = userEvent.setup();
  const notice = {
    type: "notice",
    id: "n1",
    status: "held",
    created_at: "2026-11-04T09:00:00Z",
    case_at: "2026-11-04T09:00:00Z",
  };
  vi.stubGlobal(
    "fetch",
    stubFetch({
      items: [
        { ...incidents[0], kind: "owner_unlinked", cases: [notice] },
        { ...incidents[1], kind: "notification_failed", cases: [notice] },
      ],
    }),
  );
  renderPage();

  const link = await screen.findByRole(
    "link",
    { name: "Invitar al dueño" },
    WAIT,
  );
  expect(link.getAttribute("href")).toContain("/clientes/demo");
  expect(link.getAttribute("href")).toContain("section=personas");
  const toggles = screen.getAllByRole("button", { name: /Ver 1 caso/ });
  for (const toggle of toggles) await user.click(toggle);
  expect(
    screen.getAllByRole("link", { name: "Invitar al dueño" }),
  ).toHaveLength(1);
  expect(screen.getAllByText("Aviso al dueño").length).toBeGreaterThan(0);
}, 10_000);

test("an incident without cases shows its figures and no case toggle", async () => {
  vi.stubGlobal(
    "fetch",
    stubFetch({
      items: [
        {
          ...incidents[1],
          kind: "disk",
          nature: "condition",
          title: "Disco casi lleno",
          text: "Disco al 91 %",
          has_cases: false,
          case_count: 0,
          cases: [],
        },
      ],
    }),
  );
  renderPage();

  expect(
    await screen.findByText("Disco al 91 %", {}, WAIT),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Ver \d+ caso/ })).toBeNull();
  expect(screen.queryByText(/ caso/)).toBeNull();
}, 10_000);

test("unknown case type, delivery and a platform incident do not crash", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch({
      items: [
        {
          ...incidents[1],
          delivery: "mystery",
          cases: [
            { type: "mystery", id: "x", case_at: "2026-11-04T09:00:00Z" },
          ],
        },
      ],
    }),
  );
  renderPage();

  expect(await screen.findByText("Plataforma", {}, WAIT)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Ver 1 caso/ }));
  expect(screen.getByText(/tipo que este panel no conoce/)).toBeInTheDocument();
  expect(screen.queryByText("Aviso al dueño")).toBeNull();
}, 10_000);

test("the delivery hints read as the operator expects", async () => {
  vi.stubGlobal(
    "fetch",
    stubFetch({
      items: [
        { ...incidents[0], delivery: "unconfigured" },
        { ...incidents[1], delivery: "sent" },
      ],
    }),
  );
  renderPage();
  expect(
    await screen.findByText(/Avisos por Telegram sin configurar/, {}, WAIT),
  ).toBeInTheDocument();
  expect(screen.getByText(/Avisado por Telegram/)).toBeInTheDocument();
}, 10_000);

test("«N nuevos» is plural and hidden when there are none", async () => {
  vi.stubGlobal(
    "fetch",
    stubFetch({
      items: [
        { ...incidents[1], new_since_review: 3 },
        { ...incidents[0], reviewable: true, new_since_review: 0 },
      ],
    }),
  );
  renderPage();
  expect(
    await screen.findByText(/3 nuevos desde tu revisión/, {}, WAIT),
  ).toBeInTheDocument();
  expect(screen.queryByText(/0 nuevo/)).toBeNull();
}, 10_000);

test("«Descartar todos» asks once, calls discard-all and the card goes", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch({
    items: [{ ...incidents[0], can_discard_all: true, case_count: 4 }],
  });
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Descartar todos" }, WAIT),
  );
  const dialog = await screen.findByRole("alertdialog");
  expect(
    within(dialog).getByText(
      "Se descartarán 4 envíos ambiguos: no se reenviarán.",
    ),
  ).toBeInTheDocument();
  expect(posted(fetcher, "/incidents/a1/discard-all")).toBe(false);
  await user.click(
    within(dialog).getByRole("button", { name: "Descartar todos" }),
  );
  await waitFor(() =>
    expect(posted(fetcher, "/incidents/a1/discard-all")).toBe(true),
  );
  await waitFor(() =>
    expect(screen.queryByText("Envíos sin confirmar")).not.toBeInTheDocument(),
  );
}, 10_000);

test("without can_discard_all there is no «Descartar todos»", async () => {
  vi.stubGlobal("fetch", stubFetch());
  renderPage();
  await screen.findByText("Envíos sin confirmar", {}, WAIT);
  expect(screen.queryByRole("button", { name: "Descartar todos" })).toBeNull();
}, 10_000);

test("a failed refetch keeps the cards and warns", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch({ failListAfter: 2 }));
  renderPage();

  await screen.findByText("Envíos sin confirmar", {}, WAIT);
  // The first action refetches the open list, which now fails.
  await user.click(
    await screen.findByRole("button", { name: "Lo he revisado" }),
  );
  expect(
    await screen.findByText(
      /No se pudo actualizar; se muestran los últimos datos/,
      {},
      WAIT,
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Envíos sin confirmar")).toBeInTheDocument();
}, 10_000);

test("«Ver más» continues from the preview's cursor, page by page", async () => {
  const user = userEvent.setup();
  const mk = (id: string) => ({ ...sendCase, id });
  const fetcher = stubFetch({
    items: [
      {
        ...incidents[0],
        case_count: 3,
        cases: [mk("o1")],
        cases_next_cursor: "p1",
      },
    ],
    casePages: [
      { items: [mk("o2")], next_cursor: "p2" },
      { items: [mk("o3")], next_cursor: null },
    ],
  });
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await screen.findByText("Envíos sin confirmar", {}, WAIT);
  expect(
    screen.getAllByRole("button", { name: "Marcar enviado" }),
  ).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Ver más" }));
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Marcar enviado" }),
    ).toHaveLength(2),
  );
  const caseCalls = fetcher.mock.calls
    .map((call) => new URL((call[0] as Request).url))
    .filter((url) => url.pathname.endsWith("/cases"));
  expect(caseCalls[0]?.searchParams.get("cursor")).toBe("p1");
  expect(caseCalls[0]?.searchParams.get("limit")).toBe("20");
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
  expect(screen.getByText(/Informativa ·/)).toBeInTheDocument();
  expect(screen.getByText("Informativa")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cargar más" }));
  expect(await screen.findByText("Cerrada h4", {}, WAIT)).toBeInTheDocument();
  expect(screen.getByText("Desconocido")).toBeInTheDocument();
}, 10_000);
