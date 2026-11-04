import { createFileRoute } from "@tanstack/react-router";
import { TenantDetailPage } from "@/features/tenants/detail-page";
export const Route = createFileRoute("/_app/clientes/$slug")({
  component: TenantRoute,
});
function TenantRoute() {
  const { slug } = Route.useParams();
  return <TenantDetailPage slug={slug} />;
}
