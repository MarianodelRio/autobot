import { Link, useRouterState } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useOverview } from "@/features/overview/use-overview";
import { AUDIT_SECTION, NAV_SECTIONS } from "./nav-sections";

export function Topbar({
  onOpenCommandMenu,
}: {
  onOpenCommandMenu: () => void;
}) {
  const { data, isError } = useOverview();
  const level = isError ? "unknown" : (data?.status.level ?? "unknown");
  const colors = {
    ok: "bg-status-ok",
    warning: "bg-status-warning",
    critical: "bg-status-critical",
    unknown: "bg-status-unknown",
  };
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
        <Link to="/incidencias" aria-label={`Estado global: ${level}`}>
          <span className={`block size-2.5 rounded-full ${colors[level]}`} />
        </Link>
      </div>
    </header>
  );
}
