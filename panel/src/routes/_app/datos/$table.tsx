import { createFileRoute } from "@tanstack/react-router";
import { TableDetailPage } from "@/features/data/table-detail-page";

export const Route = createFileRoute("/_app/datos/$table")({
  component: TableRoute,
});

function TableRoute() {
  const { table } = Route.useParams();
  return <TableDetailPage table={table} />;
}
