import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { AuditPage } from "./audit-page";

afterEach(() => vi.unstubAllGlobals());

const event = {
  id: "e1",
  at: "2026-11-04T10:00:00Z",
  actor: "operator",
  action: "alert.resolve",
  tenant_id: "t1",
  tenant: "demo",
  target_type: "ops_alert",
  target_id: "a1",
  summary: "Operador resuelve alerta.",
  details: { note: "manual" },
};

function stubFetch(onAuditUrl: (url: URL) => void) {
  return vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    if (url.pathname.endsWith("/tenants"))
      return new Response(JSON.stringify([{ slug: "demo", name: "Demo" }]), {
        headers: { "Content-Type": "application/json" },
      });
    onAuditUrl(url);
    return new Response(JSON.stringify({ items: [event], next_cursor: null }), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

function renderPage(
  filters: { tenant: string; action: string },
  onFilterChange: (next: Partial<typeof filters>) => void,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AuditPage filters={filters} onFilterChange={onFilterChange} />
    </QueryClientProvider>,
  );
}

test("filters by tenant and action calls onFilterChange", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch(() => {}),
  );
  const onFilterChange = vi.fn();
  renderPage({ tenant: "", action: "" }, onFilterChange);

  await screen.findByText("alert.resolve");
  await user.selectOptions(screen.getByLabelText("Cliente"), "demo");
  expect(onFilterChange).toHaveBeenCalledWith({ tenant: "demo" });

  await user.type(screen.getByLabelText("Acción"), "x");
  expect(onFilterChange).toHaveBeenCalledWith({ action: "x" });
});

test("sends the tenant and action filters to the API", async () => {
  const calls: URL[] = [];
  vi.stubGlobal(
    "fetch",
    stubFetch((url) => calls.push(url)),
  );
  renderPage({ tenant: "demo", action: "alert.resolve" }, vi.fn());

  await screen.findByText("alert.resolve");
  const call = calls.at(-1);
  expect(call?.searchParams.get("tenant")).toBe("demo");
  expect(call?.searchParams.get("action")).toBe("alert.resolve");
});

test("expands an event to show its JSON details", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch(() => {}),
  );
  renderPage({ tenant: "", action: "" }, vi.fn());

  const toggle = await screen.findByRole("button", { name: /alert.resolve/ });
  expect(screen.queryByText(/"note"/)).not.toBeInTheDocument();

  await user.click(toggle);
  expect(screen.getByText(/"note"/)).toBeInTheDocument();
});
