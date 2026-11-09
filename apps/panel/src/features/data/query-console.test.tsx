import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { QueryConsole } from "./query-console";

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

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => vi.unstubAllGlobals());

function stubFetch(
  queryResponse: unknown = {
    columns: [],
    rows: [],
    truncated: false,
    duration_ms: 1,
  },
) {
  return vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    if (url.pathname.endsWith("/tenants"))
      return new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/data/tables"))
      return new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/data/query"))
      return new Response(JSON.stringify(queryResponse), {
        headers: { "Content-Type": "application/json" },
      });
    return new Response(JSON.stringify({}), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

function renderConsole(sql = "SELECT 1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <QueryConsole sql={sql} onSqlChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

test("warns when the result was truncated", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch({
      columns: [{ name: "id", type: "int4" }],
      rows: [[1]],
      truncated: true,
      duration_ms: 5,
    }),
  );
  renderConsole();

  await user.click(await screen.findByRole("button", { name: /Ejecutar/ }));

  expect(
    await screen.findByText("Resultado truncado: afina la consulta."),
  ).toBeInTheDocument();
});

test("shows the PostgreSQL error in red when the query fails", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: RequestInfo | URL) => {
      const url = new URL(
        request instanceof Request ? request.url : String(request),
      );
      if (url.pathname.endsWith("/data/query"))
        return new Response(
          JSON.stringify({
            code: "bad_request",
            message: 'column "x" does not exist',
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        );
      return stubFetch()(request);
    }),
  );
  renderConsole();

  await user.click(await screen.findByRole("button", { name: /Ejecutar/ }));

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent('column "x" does not exist');
  expect(alert.className).toContain("text-destructive");
});

test("remembers the last query for next time", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch());
  renderConsole("SELECT * FROM tenant");

  await user.click(screen.getByRole("button", { name: /Ejecutar/ }));

  await screen.findByText("0 filas");
  expect(
    JSON.parse(localStorage.getItem("autobot.panel.data.lastQuery") ?? "{}")
      .sql,
  ).toBe("SELECT * FROM tenant");
});
