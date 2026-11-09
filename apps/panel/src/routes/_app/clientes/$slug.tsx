import { createFileRoute, useBlocker } from "@tanstack/react-router";
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
    if (typeof search.tab === "string" && TABS.includes(search.tab))
      out.tab = search.tab;
    if (search.section === "canal") out.section = "canal";
    return out;
  },
});
function TenantRoute() {
  const { slug } = Route.useParams();
  const { tab, section } = Route.useSearch();
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
    />
  );
}
