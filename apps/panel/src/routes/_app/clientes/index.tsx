import { createFileRoute } from "@tanstack/react-router";
import { TenantListPage } from "@/features/tenants/list-page";
export const Route = createFileRoute("/_app/clientes/")({
  component: TenantListPage,
});
