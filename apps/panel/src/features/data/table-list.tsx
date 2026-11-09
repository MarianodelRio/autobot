import { useState } from "react";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Input } from "@/components/ui/input";
import { formatNumber } from "@/lib/format";
import { type TableSummary, useTables } from "./use-tables";

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

export function TableList({
  onSelect,
}: {
  onSelect: (table: TableSummary) => void;
}) {
  const [search, setSearch] = useState("");
  const query = useTables();
  const tables = (query.data ?? []).filter((table) => {
    const term = search.trim().toLowerCase();
    if (!term) return true;
    return (
      table.name.toLowerCase().includes(term) ||
      table.description.toLowerCase().includes(term)
    );
  });
  const groups = [...new Set(tables.map((t) => t.group))].sort(
    (a, b) => groupRank(a) - groupRank(b) || a.localeCompare(b),
  );
  return (
    <div className="flex h-full flex-col gap-3">
      <Input
        placeholder="Buscar tabla"
        aria-label="Buscar tabla"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {query.isPending ? (
        <p className="text-sm text-muted-foreground">Cargando tablas…</p>
      ) : query.isError ? (
        <ErrorState
          message="No se pudo cargar el catálogo."
          onRetry={() => void query.refetch()}
        />
      ) : tables.length === 0 ? (
        <EmptyState message="Sin tablas que coincidan." />
      ) : (
        <div className="max-h-[calc(100vh-10rem)] space-y-3 overflow-auto">
          {groups.map((group) => (
            <div key={group}>
              <p className="px-1 py-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {group}
              </p>
              <ul className="divide-y rounded-md border">
                {tables
                  .filter((t) => t.group === group)
                  .map((table) => (
                    <li key={table.name}>
                      <button
                        type="button"
                        onClick={() => onSelect(table)}
                        className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-accent"
                      >
                        <span className="truncate font-mono">{table.name}</span>
                        <span className="shrink-0 text-muted-foreground">
                          {table.approx ? "≈ " : ""}
                          {formatNumber(table.row_count)}
                        </span>
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
