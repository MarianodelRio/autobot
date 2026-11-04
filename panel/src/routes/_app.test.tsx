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

test("renders the section once there is a session", {
  timeout: 10_000,
}, async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: RequestInfo | URL) => {
      const url = String(request instanceof Request ? request.url : request);
      const body = url.includes("/overview")
        ? { status: { level: "ok" }, tenant_rows: [] }
        : url.includes("/system")
          ? {
              machine: {
                cpu_pct: null,
                mem_used_pct: null,
                disk_used_pct: null,
                load1: null,
                uptime_s: null,
              },
              samples: [],
              services: {
                web: true,
                worker: true,
                db: true,
                victorialogs: true,
              },
              database: { ok: true, bytes: 0, tables: [] },
              queues: [],
              backup: { stale: true },
              deploys: [],
              release: "",
              tls: { days_left: null },
            }
          : { username: "operator" };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  renderAt("/sistema");

  expect(
    await screen.findByRole("heading", { name: "Sistema" }, { timeout: 8000 }),
  ).toBeInTheDocument();
});
