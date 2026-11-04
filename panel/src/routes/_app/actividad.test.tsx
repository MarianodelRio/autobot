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

afterEach(() => vi.unstubAllGlobals());

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

function stubFetch() {
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
    if (url.pathname.endsWith("/tenants"))
      return new Response(JSON.stringify([]), {
        headers: { "Content-Type": "application/json" },
      });
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      headers: { "Content-Type": "application/json" },
    });
  });
}

test("reads filters from the URL on load", async () => {
  vi.stubGlobal("fetch", stubFetch());
  const router = renderAt("/actividad?kinds=alert&status=open");

  await screen.findByRole("heading", { name: "Actividad" }, { timeout: 8000 });
  expect(router.state.location.search).toEqual({
    kinds: "alert",
    status: "open",
  });
  expect(
    await screen.findByRole("button", { name: "Alertas" }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("toggling a kind filter updates the URL", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", stubFetch());
  const router = renderAt("/actividad");

  await user.click(
    await screen.findByRole(
      "button",
      { name: "Trabajos fallidos" },
      { timeout: 8000 },
    ),
  );

  expect(router.state.location.search).toEqual({ kinds: "job" });
});
