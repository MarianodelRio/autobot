import { Link, useRouterState } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { AUDIT_SECTION, NAV_SECTIONS } from "./nav-sections";

export function Topbar({
  onOpenCommandMenu,
}: {
  onOpenCommandMenu: () => void;
}) {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const current = [...NAV_SECTIONS, AUDIT_SECTION].find(
    (section) => section.to === pathname,
  );

  return (
    <header className="flex h-14 items-center justify-between gap-4 border-b border-border px-4">
      <div className="flex items-center gap-2">
        <SidebarTrigger />
        <span className="text-sm text-muted-foreground">
          {current?.title ?? ""}
        </span>
      </div>
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={onOpenCommandMenu}
          className="flex items-center gap-2 rounded-md border border-border px-2 py-1 text-sm text-muted-foreground hover:bg-accent"
        >
          <Search className="size-3.5" aria-hidden="true" />
          <span>Buscar</span>
          <kbd className="font-mono text-xs">⌘K</kbd>
        </button>
        {/* Gray until T25 wires GET overview's status.level. */}
        <Link to="/incidencias" aria-label="Estado global: desconocido">
          <span className="size-2.5 rounded-full bg-status-unknown" />
        </Link>
      </div>
    </header>
  );
}
