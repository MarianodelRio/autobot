import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

/** Render `ui` inside a minimal router (tests only): components that use `<Link>` or
 * `useRouter` need one. Returns the router, to check where a click navigated. */
export async function renderWithRouter(ui: ReactNode, path = "/") {
  const rootRoute = createRootRoute({ component: () => ui });
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  await router.load();
  render(<RouterProvider router={router} />);
  return router;
}
