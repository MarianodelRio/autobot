import { createFileRoute, Outlet, redirect } from "@tanstack/react-router";
import { AppShell } from "@/components/app-shell";
import { meQueryOptions } from "@/features/auth/use-me";

export const Route = createFileRoute("/_app")({
  beforeLoad: async ({ context, location }) => {
    try {
      return { me: await context.queryClient.ensureQueryData(meQueryOptions) };
    } catch {
      throw redirect({ to: "/login", search: { redirect: location.pathname } });
    }
  },
  component: AppLayout,
});

function AppLayout() {
  // beforeLoad always sets `me` or redirects away before this renders.
  const { me } = Route.useRouteContext() as { me: { username: string } };
  return (
    <AppShell username={me.username}>
      <Outlet />
    </AppShell>
  );
}
