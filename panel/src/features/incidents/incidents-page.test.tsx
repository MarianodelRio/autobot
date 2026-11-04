import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { IncidentsPage } from "./incidents-page";

afterEach(() => vi.unstubAllGlobals());

const alert = {
  id: "a1",
  kind: "manual",
  tenant_id: "t1",
  tenant: "demo",
  severity: "warning",
  text: "Algo va mal",
  first_seen_at: "2026-11-04T09:00:00Z",
  last_seen_at: "2026-11-04T10:00:00Z",
  occurrences: 2,
  sent_count: 1,
  last_sent_at: "2026-11-04T10:00:00Z",
  last_delivery: "sent",
  auto_resolves: false,
  resolved_at: null,
  resolved_by: null,
};

const outbound = {
  id: "o1",
  tenant_id: "t1",
  tenant: "demo",
  channel: "telegram",
  status: "unknown",
  created_at: "2026-11-04T09:00:00Z",
  last_error: null,
  can_mark_sent: true,
  mark_sent_reason: null,
  can_resend: true,
  resend_reason: null,
};

const job = {
  id: 1,
  at: "2026-11-04T09:00:00Z",
  task_name: "send_message",
  queue: "default",
  status: "failed",
  attempts: 3,
  ids: {},
  last_event: { type: "failed", at: "2026-11-04T09:00:00Z" },
  can_retry: true,
  retry_reason: null,
};

function stubFetch() {
  return vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    if (url.pathname.endsWith("/incidents"))
      return new Response(
        JSON.stringify({ alerts: [alert], outbound: [outbound], jobs: [job] }),
        { headers: { "Content-Type": "application/json" } },
      );
    if (url.pathname.endsWith("/alerts"))
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/resolve"))
      return new Response(JSON.stringify({ message: "Alerta resuelta." }), {
        headers: { "Content-Type": "application/json" },
      });
    if (url.pathname.endsWith("/mark-sent"))
      return new Response(
        JSON.stringify({ message: "Envío marcado como enviado." }),
        { headers: { "Content-Type": "application/json" } },
      );
    if (url.pathname.endsWith("/resend")) {
      const body = req.body ? await req.json() : null;
      if (body?.confirm_duplicate_risk !== true)
        return new Response(
          JSON.stringify({
            code: "bad_request",
            message: "Confirme el riesgo.",
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        );
      return new Response(JSON.stringify({ message: "Mensaje reenviado." }), {
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.pathname.endsWith("/retry"))
      return new Response(JSON.stringify({ message: "Trabajo reencolado." }), {
        headers: { "Content-Type": "application/json" },
      });
    return new Response(JSON.stringify({}), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

function renderPage() {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <IncidentsPage />
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

test("resolves an alert that does not auto-resolve", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(await screen.findByRole("button", { name: "Resolver" }));
  await user.click(await screen.findByRole("button", { name: "Resolver" }));

  await waitFor(() => expect(posted(fetcher, "/alerts/a1/resolve")).toBe(true));
});

test("marking a send as sent posts without confirmation", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Marcar enviado" }),
  );

  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/mark-sent")).toBe(true),
  );
});

test("resending a message requires confirming the duplicate risk", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(await screen.findByRole("button", { name: "Reenviar" }));
  expect(
    screen.getByText(/reenviar puede crear un duplicado/),
  ).toBeInTheDocument();
  expect(posted(fetcher, "/outbound/o1/resend")).toBe(false);

  const buttons = screen.getAllByRole("button", { name: "Reenviar" });
  const confirmButton = buttons.at(-1);
  if (!confirmButton) throw new Error("confirm button not found");
  await user.click(confirmButton);

  await waitFor(() =>
    expect(posted(fetcher, "/outbound/o1/resend")).toBe(true),
  );
});

test("retries a failed job", async () => {
  const user = userEvent.setup();
  const fetcher = stubFetch();
  vi.stubGlobal("fetch", fetcher);
  renderPage();

  await user.click(await screen.findByRole("button", { name: "Reintentar" }));

  await waitFor(() => expect(posted(fetcher, "/jobs/1/retry")).toBe(true));
});
