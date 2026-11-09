import type { ReactNode } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { useOverview } from "@/features/overview/use-overview";
import { AppSidebar } from "./sidebar";
import { Topbar } from "./topbar";

export function AppShell({
  username,
  children,
}: {
  username: string;
  children: ReactNode;
}) {
  const overview = useOverview();

  return (
    <SidebarProvider>
      <AppSidebar
        username={username}
        incidentsCount={overview.data?.incidents_open}
      />
      <SidebarInset className="min-w-0">
        <Topbar />
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  );
}
