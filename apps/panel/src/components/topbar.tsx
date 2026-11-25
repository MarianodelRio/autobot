import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { NAV_SECTIONS } from "./nav-sections";

/** Refetches everything on screen. It is an explicit request, so it also refreshes
 * the setup steps (their «Comprobar» results are then dropped, as the label says).
 * Unsaved edits live in component state, never in the query cache: they survive. */
export function ReloadButton() {
  const client = useQueryClient();
  const fetching = useIsFetching() > 0;
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className="ml-auto"
      aria-label="Recargar"
      title="Recargar los datos de esta pantalla (descarta los resultados de «Comprobar»)"
      onClick={() => void client.invalidateQueries({ refetchType: "active" })}
    >
      <RefreshCw
        aria-hidden="true"
        data-fetching={fetching}
        className={fetching ? "animate-spin" : undefined}
      />
      Recargar
    </Button>
  );
}

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
      <ReloadButton />
    </header>
  );
}
