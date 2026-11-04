import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Timeline } from "./components/timeline";

export const ACTIVITY_KINDS: { value: string; label: string }[] = [
  { value: "inbound", label: "Mensajes recibidos" },
  { value: "outbound", label: "Respuestas" },
  { value: "notification", label: "Avisos al dueño" },
  { value: "alert", label: "Alertas" },
  { value: "job", label: "Trabajos fallidos" },
  { value: "audit", label: "Auditoría" },
];

export interface ActivityFilters {
  tenant: string;
  kinds: string;
  status: string;
}

export function ActivityPage({
  filters,
  onFilterChange,
}: {
  filters: ActivityFilters;
  onFilterChange: (next: Partial<ActivityFilters>) => void;
}) {
  const tenants = useQuery({
    queryKey: ["tenants"],
    queryFn: () => unwrap(api.GET("/tenants")),
  });
  const selectedKinds = new Set(filters.kinds ? filters.kinds.split(",") : []);
  return (
    <div>
      <PageHeader title="Actividad" />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          className="rounded-md border bg-background px-3 py-2 text-sm"
          aria-label="Cliente"
          value={filters.tenant}
          onChange={(event) => onFilterChange({ tenant: event.target.value })}
        >
          <option value="">Todos los clientes</option>
          {(tenants.data ?? []).map((row) => (
            <option key={row.slug} value={row.slug}>
              {row.name}
            </option>
          ))}
        </select>
        <Input
          className="max-w-xs"
          aria-label="Estado"
          placeholder="Estado (p. ej. sent, failed, open)"
          value={filters.status}
          onChange={(event) => onFilterChange({ status: event.target.value })}
        />
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        {ACTIVITY_KINDS.map((kind) => {
          const active = selectedKinds.has(kind.value);
          return (
            <Button
              key={kind.value}
              type="button"
              size="sm"
              variant={active ? "default" : "outline"}
              aria-pressed={active}
              onClick={() => {
                const next = new Set(selectedKinds);
                if (active) next.delete(kind.value);
                else next.add(kind.value);
                onFilterChange({ kinds: [...next].join(",") });
              }}
            >
              {kind.label}
            </Button>
          );
        })}
      </div>
      <Timeline
        tenant={filters.tenant}
        kinds={filters.kinds}
        status={filters.status}
      />
    </div>
  );
}
