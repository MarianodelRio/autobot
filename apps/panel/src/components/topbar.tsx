import { useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { NAV_SECTIONS } from "./nav-sections";

const RELOAD_HINT =
  "Recarga los datos de esta pantalla; los resultados de «Comprobar» se conservan mientras no cambie la configuración";

/** Refetches everything on screen. The results of «Comprobar» are kept apart from
 * the queries (lib/setup-checks.ts), so they survive while the configuration is the
 * same. Unsaved edits live in component state, never in the query cache: they
 * survive too. It spins only for a reload the person asked for, not for the 30 s
 * background refreshes. */
export function ReloadButton() {
  const client = useQueryClient();
  const [manual, setManual] = useState(false);
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="ml-auto"
        aria-describedby="reload-hint"
        aria-busy={manual}
        title={RELOAD_HINT}
        onClick={() => {
          setManual(true);
          void client
            .invalidateQueries({ refetchType: "active" })
            .finally(() => setManual(false));
        }}
      >
        <RefreshCw
          aria-hidden="true"
          data-fetching={manual}
          className={manual ? "animate-spin" : undefined}
        />
        Recargar
      </Button>
      <span id="reload-hint" className="sr-only">
        {RELOAD_HINT}
      </span>
    </>
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
