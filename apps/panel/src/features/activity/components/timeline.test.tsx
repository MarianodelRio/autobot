import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { Timeline } from "./timeline";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const item = {
  id: "1",
  at: "2026-11-04T10:00:00Z",
  kind: "alert",
  tenant: "demo",
  channel: null,
  icon: "🚨",
  title: "Alerta",
  detail: "Algo falló",
  status: "open",
  link: "/clientes/demo",
};

function renderTimeline() {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <Timeline tenant="demo" />
    </QueryClientProvider>,
  );
}

test("expands and collapses an item's detail", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ items: [item], next_cursor: null }), {
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
  renderTimeline();

  const toggle = await screen.findByRole("button", { name: /Alerta/ });
  expect(screen.queryByText("Algo falló")).not.toBeInTheDocument();

  await user.click(toggle);
  expect(screen.getByText("Algo falló")).toBeInTheDocument();
  expect(screen.getByText("Ver cliente")).toBeInTheDocument();

  await user.click(toggle);
  expect(screen.queryByText("Algo falló")).not.toBeInTheDocument();
});

test("refetches the first page every 15s while only one page is loaded", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetcher = vi.fn(
    async () =>
      new Response(JSON.stringify({ items: [item], next_cursor: null }), {
        headers: { "Content-Type": "application/json" },
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  renderTimeline();

  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  await vi.advanceTimersByTimeAsync(15_000);
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
});
