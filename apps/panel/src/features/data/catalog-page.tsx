import { Link } from "@tanstack/react-router";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { formatBytes, formatNumber } from "@/lib/format";
import { useTables } from "./use-tables";

// Matches the display order of the groups in catalog.py; anything uncatalogued
// (or a future group not listed here) sorts after these, alphabetically.
const GROUP_ORDER = [
  "Negocios y config",
  "Conversaciones y mensajes",
  "Avisos y métricas",
  "Demo y dueños",
  "Cola de trabajos",
  "Operación del panel",
  "Django interno",
];

function groupRank(group: string): number {
  const index = GROUP_ORDER.indexOf(group);
  return index === -1 ? GROUP_ORDER.length : index;
}

export function CatalogPage() {
  const query = useTables();
  const tables = query.data ?? [];
  const groups = [...new Set(tables.map((t) => t.group))].sort(
    (a, b) => groupRank(a) - groupRank(b) || a.localeCompare(b),
  );
  return (
    <div>
      <PageHeader title="Datos" />
      {query.isPending ? (
        <p>Cargando catálogo…</p>
      ) : query.isError ? (
        <ErrorState
          message="No se pudo cargar el catálogo."
          onRetry={() => void query.refetch()}
        />
      ) : tables.length === 0 ? (
        <EmptyState message="No hay tablas en el catálogo." />
      ) : (
        <div className="space-y-3">
          {groups.map((group) => (
            <details key={group} className="rounded-md border" open>
              <summary className="cursor-pointer px-4 py-2 font-medium">
                {group}
              </summary>
              <ul className="divide-y">
                {tables
                  .filter((t) => t.group === group)
                  .map((table) => (
                    <li key={table.name}>
                      <Link
                        to="/datos/$table"
                        params={{ table: table.name }}
                        className="flex items-center justify-between px-4 py-2 text-sm hover:bg-accent"
                      >
                        <span className="font-mono">{table.name}</span>
                        <span className="text-muted-foreground">
                          {table.approx ? "≈ " : ""}
                          {formatNumber(table.row_count)} filas ·{" "}
                          {formatBytes(table.bytes)}
                        </span>
                      </Link>
                    </li>
                  ))}
              </ul>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
