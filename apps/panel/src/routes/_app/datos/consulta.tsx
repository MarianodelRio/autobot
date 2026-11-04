import { createFileRoute } from "@tanstack/react-router";
import { QueryPage } from "@/features/data/query-page";

export const Route = createFileRoute("/_app/datos/consulta")({
  component: ConsultaRoute,
  validateSearch: (search: Record<string, unknown>): { sql?: string } =>
    typeof search.sql === "string" && search.sql ? { sql: search.sql } : {},
});

function ConsultaRoute() {
  const { sql } = Route.useSearch();
  return <QueryPage initialSql={sql} />;
}
