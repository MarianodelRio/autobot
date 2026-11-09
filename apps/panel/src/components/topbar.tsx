import { useRouterState } from "@tanstack/react-router";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { NAV_SECTIONS } from "./nav-sections";

export function Topbar() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const current = NAV_SECTIONS.find((section) => section.to === pathname);

  return (
    <header className="flex h-14 items-center gap-2 border-b border-border px-4">
      <SidebarTrigger />
      <span className="text-sm text-muted-foreground">
        {current?.title ?? ""}
      </span>
    </header>
  );
}
