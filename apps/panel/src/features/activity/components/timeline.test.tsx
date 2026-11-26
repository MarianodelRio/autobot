import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { renderWithRouter } from "@/lib/test-router";
import { Timeline } from "./timeline";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const item = {
  id: "1",
  at: "2026-11-04T10:00:00Z",
  kind: "outbound",
  tenant: "demo",
  channel: "telegram",
  label: "Respuesta",
  status: "sent",
};

const detail = {
  contact: "Ana",
  text: "Hola Ana",
  facts: ["Facturable"],
  tenant: "demo",
  contact_link: "/clientes/demo?tab=contactos",
};

async function renderTimeline() {
  const client = new QueryClient();
  await renderWithRouter(
    <QueryClientProvider client={client}>
      <Timeline tenant="demo" />
    </QueryClientProvider>,
  );
}

function stubFetch() {
  return vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(
      request instanceof Request ? request.url : String(request),
    );
    if (url.pathname.includes("/activity/outbound/1"))
      return new Response(JSON.stringify(detail), {
        headers: { "Content-Type": "application/json" },
      });
    return new Response(JSON.stringify({ items: [item], next_cursor: null }), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

test("expands and collapses an item to fetch and show its detail", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch());
  await renderTimeline();

  const toggle = await screen.findByRole("button", { name: /Respuesta/ });
  expect(screen.queryByText("Hola Ana")).not.toBeInTheDocument();

  await user.click(toggle);
  expect(await screen.findByText("Hola Ana")).toBeInTheDocument();
  expect(screen.getByText("Ver cliente")).toBeInTheDocument();

  await user.click(toggle);
  expect(screen.queryByText("Hola Ana")).not.toBeInTheDocument();
});

test("the feed never shows the message text or contact name", async () => {
  vi.stubGlobal("fetch", stubFetch());
  await renderTimeline();

  await screen.findByRole("button", { name: /Respuesta/ });
  expect(screen.queryByText("Hola Ana")).not.toBeInTheDocument();
  expect(screen.queryByText("Ana")).not.toBeInTheDocument();
});

test("refetches the first page every 15s while only one page is loaded", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  await renderTimeline();

  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  await vi.advanceTimersByTimeAsync(15_000);
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
});
