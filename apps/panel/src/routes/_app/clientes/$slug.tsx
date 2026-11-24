import {
  createFileRoute,
  useBlocker,
  useNavigate,
} from "@tanstack/react-router";
import { useState } from "react";
import { TenantDetailPage } from "@/features/tenants/detail-page";

const TABS = ["resumen", "configuracion", "actividad", "contactos", "avisos"];

interface TenantSearch {
  tab?: string;
  section?: "canal";
}

export const Route = createFileRoute("/_app/clientes/$slug")({
  component: TenantRoute,
  validateSearch: (search: Record<string, unknown>): TenantSearch => {
    const out: TenantSearch = {};
    // «Alta» was its own tab until ADR-027: old links open Configuración.
    if (search.tab === "alta") out.tab = "configuracion";
    else if (typeof search.tab === "string" && TABS.includes(search.tab))
      out.tab = search.tab;
    if (search.section === "canal") out.section = "canal";
    return out;
  },
});
function TenantRoute() {
  const { slug } = Route.useParams();
  const { tab, section } = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const [dirty, setDirty] = useState(false);
  useBlocker({
    shouldBlockFn: () =>
      !window.confirm("Hay cambios sin guardar. ¿Quieres salir?"),
    disabled: !dirty,
    enableBeforeUnload: dirty,
  });
  return (
    <TenantDetailPage
      slug={slug}
      dirty={dirty}
      onDirtyChange={setDirty}
      initialTab={tab}
      initialSection={section}
      onTabChange={(next) =>
        // The tab already asked about unsaved changes (and `dirty` is still true
        // in this render): the blocker would ask a second time.
        void navigate({
          search: { tab: next },
          replace: true,
          ignoreBlocker: true,
        })
      }
    />
  );
}
