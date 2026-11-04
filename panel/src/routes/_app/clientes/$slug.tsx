import { createFileRoute, useBlocker } from "@tanstack/react-router";
import { useState } from "react";
import { TenantDetailPage } from "@/features/tenants/detail-page";
export const Route = createFileRoute("/_app/clientes/$slug")({
  component: TenantRoute,
});
function TenantRoute() {
  const { slug } = Route.useParams();
  const [dirty, setDirty] = useState(false);
  useBlocker({
    shouldBlockFn: () =>
      !window.confirm("Hay cambios sin guardar. ¿Quieres salir?"),
    disabled: !dirty,
    enableBeforeUnload: dirty,
  });
  return (
    <TenantDetailPage slug={slug} dirty={dirty} onDirtyChange={setDirty} />
  );
}
