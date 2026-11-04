import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { routeTree } from "@/routeTree.gen";

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

afterEach(() => {
  vi.unstubAllGlobals();
});

test("redirects to /login?redirect=<path> when there is no session", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 401 })),
  );

  const router = renderAt("/sistema");

  await waitFor(() => {
    expect(router.state.location.pathname).toBe("/login");
  });
  expect(router.state.location.search).toEqual({ redirect: "/sistema" });
});

test("renders the section once there is a session", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (request: RequestInfo | URL) =>
        new Response(
          JSON.stringify(
            String(request instanceof Request ? request.url : request).includes(
              "/overview",
            )
              ? { status: { level: "ok" }, tenant_rows: [] }
              : { username: "operator" },
          ),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          },
        ),
    ),
  );

  renderAt("/sistema");

  expect(
    await screen.findByRole("heading", { name: "Sistema" }),
  ).toBeInTheDocument();
});
