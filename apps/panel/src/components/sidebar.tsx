import { Link, useRouterState } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import {
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  Sidebar as SidebarRoot,
} from "@/components/ui/sidebar";
import { useLogout } from "@/features/auth/use-logout";
import { NAV_SECTIONS } from "./nav-sections";

export function AppSidebar({
  username,
  incidentsCount,
}: {
  username: string;
  incidentsCount?: number;
}) {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const logout = useLogout();

  return (
    <SidebarRoot>
      <SidebarHeader>
        <span className="px-2 text-sm font-semibold">Autobot</span>
      </SidebarHeader>
      <SidebarContent>
        <SidebarMenu>
          {NAV_SECTIONS.map((section) => (
            <SidebarMenuItem key={section.to}>
              <SidebarMenuButton asChild isActive={pathname === section.to}>
                <Link to={section.to}>
                  <section.icon />
                  <span>{section.title}</span>
                </Link>
              </SidebarMenuButton>
              {section.title === "Incidencias" && !!incidentsCount && (
                <SidebarMenuBadge>{incidentsCount}</SidebarMenuBadge>
              )}
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <span className="px-2 text-sm text-muted-foreground">
              {username}
            </span>
          </SidebarMenuItem>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={() => logout.mutate()}>
              <LogOut />
              <span>Salir</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </SidebarRoot>
  );
}
