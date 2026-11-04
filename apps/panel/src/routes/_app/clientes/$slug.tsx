import { createFileRoute, useBlocker } from "@tanstack/react-router";
import { useState } from "react";
import { TenantDetailPage } from "@/features/tenants/detail-page";
export const Route = createFileRoute("/_app/clientes/$slug")({
  component: TenantRoute,
  validateSearch: (search: Record<string, unknown>): { tab?: "canal" } =>
    search.tab === "canal" ? { tab: "canal" } : {},
});
function TenantRoute() {
  const { slug } = Route.useParams();
  const { tab } = Route.useSearch();
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
    />
  );
}
