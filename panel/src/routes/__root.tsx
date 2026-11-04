import { createRootRoute, Outlet } from "@tanstack/react-router";

// Placeholder root route so the TanStack Router plugin has something to
// generate against; T23b builds the real route tree (login, _app, …) on it.
export const Route = createRootRoute({
  component: Outlet,
});
