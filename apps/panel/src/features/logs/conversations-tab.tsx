import { TenantSelect } from "@/components/tenant-select";
import { Button } from "@/components/ui/button";
import { Timeline } from "@/features/activity/components/timeline";

export interface ConversationsFilters {
  tenant: string;
  kinds: string;
  status: string;
}

const KIND_CHIPS: { value: string; label: string }[] = [
  { value: "inbound", label: "Recibidos" },
  { value: "outbound", label: "Respuestas" },
  { value: "notification", label: "Avisos" },
];

const STATUSES = ["pending", "done", "failed", "ignored", "sent", "unknown"];

export function ConversationsTab({
  filters,
  onFilterChange,
}: {
  filters: ConversationsFilters;
  onFilterChange: (next: Partial<ConversationsFilters>) => void;
}) {
  const selectedKinds = new Set(filters.kinds ? filters.kinds.split(",") : []);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <TenantSelect
          value={filters.tenant}
          onChange={(value) => onFilterChange({ tenant: value })}
        />
        <select
          className="rounded-md border bg-background px-3 py-2 text-sm"
          aria-label="Estado"
          value={filters.status}
          onChange={(event) => onFilterChange({ status: event.target.value })}
        >
          <option value="">Todos los estados</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap gap-2">
        {KIND_CHIPS.map((kind) => {
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
