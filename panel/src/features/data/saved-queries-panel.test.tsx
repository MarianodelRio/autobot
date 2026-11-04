import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { SavedQueriesPanel } from "./saved-queries-panel";

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  let queries = [
    {
      id: 1,
      name: "Negocios activos",
      sql: "SELECT 1",
      created_at: "2026-11-04T00:00:00Z",
      updated_at: "2026-11-04T00:00:00Z",
    },
  ];
  return vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    if (url.pathname.endsWith("/data/saved-queries") && req.method === "GET")
      return new Response(JSON.stringify(queries), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/data/saved-queries") && req.method === "POST") {
      const body = await req.json();
      const created = {
        id: 2,
        name: body.name,
        sql: body.sql,
        created_at: "2026-11-04T00:00:00Z",
        updated_at: "2026-11-04T00:00:00Z",
      };
      queries = [...queries, created];
      return new Response(JSON.stringify(created), {
        headers: { "Content-Type": "application/json" },
      });
    }
    if (
      url.pathname.match(/\/data\/saved-queries\/\d+$/) &&
      req.method === "PUT"
    ) {
      const body = await req.json();
      queries = queries.map((q) =>
        String(q.id) === url.pathname.split("/").at(-1) ? { ...q, ...body } : q,
      );
      return new Response(JSON.stringify(queries[0]), {
        headers: { "Content-Type": "application/json" },
      });
    }
    if (
      url.pathname.match(/\/data\/saved-queries\/\d+$/) &&
      req.method === "DELETE"
    ) {
      const id = url.pathname.split("/").at(-1);
      queries = queries.filter((q) => String(q.id) !== id);
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify({}), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

function renderPanel(currentSql = "SELECT 2", onLoad = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SavedQueriesPanel currentSql={currentSql} onLoad={onLoad} />
    </QueryClientProvider>,
  );
  return { client, onLoad };
}

test("loads a saved query into the editor", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch());
  const { onLoad } = renderPanel();

  await user.click(await screen.findByText("Negocios activos"));
  expect(onLoad).toHaveBeenCalledWith("SELECT 1");
});

test("creates a new saved query from the current SQL", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch());
  renderPanel("SELECT 2");

  await screen.findByText("Negocios activos");
  await user.click(screen.getByRole("button", { name: "Guardar" }));
  await user.type(screen.getByLabelText("Nombre"), "Mi consulta");
  await user.click(screen.getByRole("button", { name: "Guardar" }));

  expect(await screen.findByText("Mi consulta")).toBeInTheDocument();
});

test("updates a saved query with the current SQL", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPanel("SELECT 3");

  await user.click(await screen.findByRole("button", { name: "Actualizar" }));

  expect(
    fetcher.mock.calls.some(
      (call) =>
        (call[0] as Request).method === "PUT" &&
        String((call[0] as Request).url).endsWith("/data/saved-queries/1"),
    ),
  ).toBe(true);
});

test("deletes a saved query after confirming", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch());
  renderPanel();

  await user.click(await screen.findByRole("button", { name: "Eliminar" }));
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: "Eliminar" }));

  await screen.findByText("No hay consultas guardadas.");
});
