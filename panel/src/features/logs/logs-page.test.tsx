import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { type LogsFilters, LogsPage } from "./logs-page";

// jsdom has no layout engine: clientWidth/clientHeight always read 0, so the
// virtualizer (which measures the scroll container through them) would
// otherwise think its viewport is empty and render no rows.
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(1000);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const baseFilters: LogsFilters = {
  tenant: "",
  level: "",
  service: "",
  q: "",
  start: "",
  end: "",
};

function renderPage(
  filters: LogsFilters,
  onFilterChange: (next: Partial<LogsFilters>) => void = vi.fn(),
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <LogsPage filters={filters} onFilterChange={onFilterChange} />
    </QueryClientProvider>,
  );
}

test("sends the filters as query params", async () => {
  const calls: URL[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: RequestInfo | URL) => {
      const url = new URL(
        request instanceof Request ? request.url : String(request),
      );
      calls.push(url);
      return new Response(
        JSON.stringify({ items: [], truncated: false, clipped: false }),
        { headers: { "Content-Type": "application/json" } },
      );
    }),
  );
  renderPage({
    tenant: "demo",
    level: "ERROR",
    service: "web",
    q: "fallo",
    start: "2026-11-04T09:00:00.000Z",
    end: "2026-11-04T10:00:00.000Z",
  });

  await screen.findByText("No hay logs en este rango.");
  const call = calls.at(-1);
  expect(call?.searchParams.get("tenant")).toBe("demo");
  expect(call?.searchParams.get("level")).toBe("ERROR");
  expect(call?.searchParams.get("service")).toBe("web");
  expect(call?.searchParams.get("q")).toBe("fallo");
  expect(call?.searchParams.get("start")).toBe("2026-11-04T09:00:00.000Z");
  expect(call?.searchParams.get("end")).toBe("2026-11-04T10:00:00.000Z");
});

test("expands a row to show the JSON, the exception and copies the event_id", async () => {
  const user = userEvent.setup();
  const writeText = vi.fn();
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            items: [
              {
                _time: "2026-11-04T10:00:00Z",
                level: "ERROR",
                service: "web",
                tenant: "demo",
                _msg: "fallo al enviar",
                event_id: "evt-1",
                exception: "Traceback (most recent call last): boom",
              },
            ],
            truncated: false,
            clipped: false,
          }),
          { headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  renderPage(baseFilters);

  const toggle = await screen.findByRole("button", {
    name: /fallo al enviar/,
  });
  expect(screen.queryByText(/boom/)).not.toBeInTheDocument();

  await user.click(toggle);
  expect(screen.getAllByText(/boom/).length).toBeGreaterThan(0);

  await user.click(screen.getByRole("button", { name: "Copiar event_id" }));
  expect(writeText).toHaveBeenCalledWith("evt-1");
});

test("shows '503 Logs no disponibles' when the service is unavailable", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            code: "logs_unavailable",
            message: "El servicio de logs no está disponible.",
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  renderPage(baseFilters);

  expect(
    await screen.findByText("El servicio de logs no está disponible."),
  ).toBeInTheDocument();
});

test("warns when the range was clipped to the current month", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ items: [], truncated: false, clipped: true }),
          { headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  renderPage(baseFilters);

  expect(await screen.findByRole("status")).toHaveTextContent(
    "El rango se ha recortado",
  );
});
