import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { routeTree } from "@/routeTree.gen";

afterEach(() => vi.unstubAllGlobals());

const activeInvite = {
  id: "i1",
  code: "ABCD1234",
  note: "peluquero Juan",
  max_uses: 1,
  uses: 0,
  grants: 0,
  expires_at: "2027-01-01T00:00:00Z",
  revoked_at: null,
  created_by: "operator",
  created_at: "2026-11-16T09:00:00Z",
  telegram_link: "https://t.me/AutobotDemoBot?start=ABCD1234",
  qr_svg: "<svg><rect/></svg>",
};

function stubFetch(invites: unknown[] = [activeInvite]) {
  return vi.fn(async (request: RequestInfo | URL) => {
    const req = request instanceof Request ? request : new Request(request);
    const url = new URL(req.url);
    if (url.pathname.endsWith("/me"))
      return new Response(JSON.stringify({ username: "operator" }), {
        headers: { "Content-Type": "application/json" },
      });
    if (req.method === "GET" && url.pathname.endsWith("/demo/invites"))
      return new Response(JSON.stringify(invites), {
        headers: { "Content-Type": "application/json" },
      });
    if (req.method === "POST" && url.pathname.endsWith("/demo/invites")) {
      const body = (await req.json()) as { note: string };
      return new Response(
        JSON.stringify({
          ...activeInvite,
          id: "i2",
          note: body.note,
          telegram_link: null,
          qr_svg: null,
        }),
        { headers: { "Content-Type": "application/json" } },
      );
    }
    if (req.method === "POST" && url.pathname.endsWith("/revoke"))
      return new Response(
        JSON.stringify({ ...activeInvite, revoked_at: "2026-11-16T10:00:00Z" }),
        { headers: { "Content-Type": "application/json" } },
      );
    return new Response(JSON.stringify({}), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

function renderPage(invites?: unknown[]) {
  const fetcher = stubFetch(invites);
  vi.stubGlobal("fetch", fetcher);
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: ["/demo"] }),
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return fetcher;
}

test("lists existing invites with their status and QR link", async () => {
  renderPage();

  expect(
    await screen.findByText("peluquero Juan", {}, { timeout: 8000 }),
  ).toBeInTheDocument();
  expect(screen.getByText("Activa")).toBeInTheDocument();
  expect(screen.getByText("0/1")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Ver código" }));
  expect(screen.getByText("ABCD1234")).toBeInTheDocument();
  expect(
    screen.getByText("https://t.me/AutobotDemoBot?start=ABCD1234"),
  ).toBeInTheDocument();
}, 10_000);

test("an invite without DEMO_TELEGRAM_BOT_USERNAME shows the code with no QR", async () => {
  renderPage([{ ...activeInvite, telegram_link: null, qr_svg: null }]);

  await userEvent.click(
    await screen.findByRole(
      "button",
      { name: "Ver código" },
      { timeout: 8000 },
    ),
  );
  expect(screen.getByText("ABCD1234")).toBeInTheDocument();
  expect(screen.getByText(/DEMO_TELEGRAM_BOT_USERNAME/)).toBeInTheDocument();
}, 10_000);

test("creating an invite posts the form and refreshes the list", async () => {
  const user = userEvent.setup();
  const fetcher = renderPage();

  await user.type(
    await screen.findByLabelText(/Nota/, {}, { timeout: 8000 }),
    "nuevo peluquero",
  );
  await user.click(screen.getByRole("button", { name: "Crear invitación" }));

  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        (call) =>
          (call[0] as Request).method === "POST" &&
          String((call[0] as Request).url).endsWith("/demo/invites"),
      ),
    ).toBe(true),
  );
}, 10_000);

test("revoking an invite asks for confirmation before posting", async () => {
  const user = userEvent.setup();
  const fetcher = renderPage();

  await user.click(
    await screen.findByRole("button", { name: "Revocar" }, { timeout: 8000 }),
  );
  expect(screen.getByText(/conserva su acceso/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Revocar" }));

  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(
        (call) =>
          (call[0] as Request).method === "POST" &&
          String((call[0] as Request).url).endsWith("/demo/invites/i1/revoke"),
      ),
    ).toBe(true),
  );
}, 10_000);
