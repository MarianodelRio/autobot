import type { ReactNode } from "react";
import { useState } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { useOverview } from "@/features/overview/use-overview";
import { CommandMenu } from "./command-menu";
import { AppSidebar } from "./sidebar";
import { Topbar } from "./topbar";

export function AppShell({
  username,
  children,
}: {
  username: string;
  children: ReactNode;
}) {
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);
  const overview = useOverview();

  return (
    <SidebarProvider>
      <AppSidebar
        username={username}
        incidentsCount={overview.data?.incidents_open}
      />
      <SidebarInset>
        <Topbar onOpenCommandMenu={() => setCommandMenuOpen(true)} />
        <main className="flex-1 overflow-auto p-6">{children}</main>
      </SidebarInset>
      <CommandMenu open={commandMenuOpen} onOpenChange={setCommandMenuOpen} />
    </SidebarProvider>
  );
}
