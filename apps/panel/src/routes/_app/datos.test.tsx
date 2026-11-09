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

vi.mock("@uiw/react-codemirror", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange?: (value: string) => void;
  }) => (
    <textarea
      aria-label="sql"
      value={value}
      onChange={(event) => onChange?.(event.target.value)}
    />
  ),
}));

afterEach(() => vi.unstubAllGlobals());

const tenant = {
  name: "tenant",
  group: "Negocios y config",
  description: "Identidad y estado de los negocios.",
  written_by: "Configuración del panel",
  retention: "Hasta la purga del negocio",
  rls: false,
  row_count: 1,
  approx: false,
  bytes: 8192,
  columns: [
    {
      name: "id",
      type: "uuid",
      nullable: false,
      primary_key: true,
      description: "",
      hidden: false,
    },
  ],
  rows_by_tenant: [],
  incoming: [],
  outgoing: [],
};

function renderAt(path: string) {
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function stubFetch({ onQuery }: { onQuery?: () => void } = {}) {
  return vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    if (url.pathname.endsWith("/me"))
      return new Response(JSON.stringify({ username: "operator" }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/overview"))
      return new Response(
        JSON.stringify({ status: { level: "ok" }, tenant_rows: [] }),
        { headers: { "Content-Type": "application/json" } },
      );
    if (url.pathname.endsWith("/data/tables/tenant"))
      return new Response(JSON.stringify({ ...tenant, rows: [["id-1"]] }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/data/tables"))
      return new Response(JSON.stringify([tenant]), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/data/query")) {
      onQuery?.();
      return new Response(
        JSON.stringify({
          columns: [],
          rows: [],
          truncated: false,
          duration_ms: 1,
        }),
        { headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.pathname.endsWith("/tenants"))
      return new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      });
    return new Response(JSON.stringify({}), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

test("inserting a SELECT fills the editor without running it", async () => {
  const onQuery = vi.fn();
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch({ onQuery }));
  renderAt("/datos");

  await user.click(await screen.findByText("tenant", {}, { timeout: 8000 }));
  await screen.findByRole("heading", { name: "tenant" });

  await user.click(screen.getByRole("button", { name: "Insertar SELECT" }));

  expect(await screen.findByLabelText("sql")).toHaveValue(
    'SELECT * FROM "tenant" LIMIT 100',
  );
  expect(onQuery).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("heading", { name: "tenant" }),
  ).not.toBeInTheDocument();
}, 10_000);

test("viewing details navigates to the table page", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch());
  const router = renderAt("/datos");

  await user.click(await screen.findByText("tenant", {}, { timeout: 8000 }));
  await user.click(screen.getByRole("button", { name: "Ver detalle" }));

  expect(router.state.location.pathname).toBe("/datos/tenant");
  await screen.findByRole("heading", { name: "tenant" });
}, 10_000);
