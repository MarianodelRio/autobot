import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { ActivityPage } from "./activity-page";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(onActivityUrl: (url: URL) => void) {
  return vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    if (url.pathname.endsWith("/tenants"))
      return new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      });
    onActivityUrl(url);
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

function renderPage(
  filters: { tenant: string; kinds: string; status: string },
  onFilterChange: (next: Partial<typeof filters>) => void,
) {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <ActivityPage filters={filters} onFilterChange={onFilterChange} />
    </QueryClientProvider>,
  );
}

test("toggling a kind calls onFilterChange with the updated kinds list", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch(() => {}),
  );
  const onFilterChange = vi.fn();
  renderPage({ tenant: "", kinds: "", status: "" }, onFilterChange);

  await user.click(await screen.findByRole("button", { name: "Alertas" }));

  expect(onFilterChange).toHaveBeenCalledWith({ kinds: "alert" });
});

test("deselecting an active kind removes it from the list", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch(() => {}),
  );
  const onFilterChange = vi.fn();
  renderPage({ tenant: "", kinds: "alert,job", status: "" }, onFilterChange);

  await user.click(await screen.findByRole("button", { name: "Alertas" }));

  expect(onFilterChange).toHaveBeenCalledWith({ kinds: "job" });
});

test("changing the status filter calls onFilterChange", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    stubFetch(() => {}),
  );
  const onFilterChange = vi.fn();
  renderPage({ tenant: "", kinds: "", status: "" }, onFilterChange);

  await user.type(screen.getByLabelText("Estado"), "f");

  expect(onFilterChange).toHaveBeenCalledWith({ status: "f" });
});

test("passes the current filters to the activity request", async () => {
  vi.stubGlobal(
    "fetch",
    stubFetch(() => {}),
  );
  const calls: URL[] = [];
  vi.stubGlobal(
    "fetch",
    stubFetch((url) => calls.push(url)),
  );
  renderPage({ tenant: "demo", kinds: "alert", status: "open" }, vi.fn());

  await screen.findByText("No hay actividad.");
  const call = calls.at(-1);
  expect(call?.searchParams.get("tenant")).toBe("demo");
  expect(call?.searchParams.get("kinds")).toBe("alert");
  expect(call?.searchParams.get("status")).toBe("open");
});
