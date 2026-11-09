import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useRef, useState } from "react";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { TenantSelect } from "@/components/tenant-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDebouncedCallback } from "@/hooks/use-debounced-callback";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { LogDetailSheet } from "./log-detail-sheet";

export interface TechnicalFilters {
  tenant: string;
  level: string;
  service: string;
  q: string;
  start: string;
  end: string;
}

const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

const QUICK_RANGES: { value: string; label: string; minutes: number }[] = [
  { value: "15m", label: "15 min", minutes: 15 },
  { value: "1h", label: "1 h", minutes: 60 },
  { value: "24h", label: "24 h", minutes: 24 * 60 },
  { value: "7d", label: "7 días", minutes: 7 * 24 * 60 },
  { value: "31d", label: "31 días", minutes: 31 * 24 * 60 },
];

const LEVEL_COLOR: Record<string, string> = {
  DEBUG: "text-muted-foreground",
  INFO: "text-foreground",
  WARNING: "text-status-warning",
  ERROR: "text-status-critical",
  CRITICAL: "text-status-critical",
};

function toLocalInput(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromLocalInput(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

function field(item: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value) return value;
  }
  return "";
}

export function TechnicalTab({
  filters,
  onFilterChange,
}: {
  filters: TechnicalFilters;
  onFilterChange: (next: Partial<TechnicalFilters>) => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [serviceText, setServiceText] = useState(filters.service);
  const [queryText, setQueryText] = useState(filters.q);
  const parentRef = useRef<HTMLDivElement>(null);
  const debouncedService = useDebouncedCallback(
    (value: string) => onFilterChange({ service: value }),
    300,
  );
  const debouncedQuery = useDebouncedCallback(
    (value: string) => onFilterChange({ q: value }),
    300,
  );
  const query = useQuery({
    queryKey: ["logs", filters],
    queryFn: () =>
      unwrap(
        api.GET("/logs", {
          params: {
            query: {
              tenant: filters.tenant,
              level: filters.level,
              service: filters.service,
              q: filters.q,
              start: filters.start || undefined,
              end: filters.end || undefined,
            },
          },
        }),
      ),
  });
  const items = query.data?.items ?? [];
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 40,
    overscan: 10,
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {QUICK_RANGES.map((range) => (
          <Button
            key={range.value}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              const now = new Date();
              const start = new Date(now.getTime() - range.minutes * 60_000);
              onFilterChange({
                start: start.toISOString(),
                end: now.toISOString(),
              });
            }}
          >
            {range.label}
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Input
          type="datetime-local"
          aria-label="Desde"
          value={toLocalInput(filters.start)}
          onChange={(event) =>
            onFilterChange({ start: fromLocalInput(event.target.value) })
          }
        />
        <Input
          type="datetime-local"
          aria-label="Hasta"
          value={toLocalInput(filters.end)}
          onChange={(event) =>
            onFilterChange({ end: fromLocalInput(event.target.value) })
          }
        />
        <select
          className="rounded-md border bg-background px-3 py-2 text-sm"
          aria-label="Nivel"
          value={filters.level}
          onChange={(event) => onFilterChange({ level: event.target.value })}
        >
          <option value="">Todos los niveles</option>
          {LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
        <Input
          className="max-w-xs"
          aria-label="Servicio"
          placeholder="Servicio (p. ej. web, worker)"
          value={serviceText}
          onChange={(event) => {
            setServiceText(event.target.value);
            debouncedService(event.target.value);
          }}
        />
        <TenantSelect
          value={filters.tenant}
          onChange={(value) => onFilterChange({ tenant: value })}
        />
        <Input
          className="max-w-xs"
          aria-label="Texto"
          placeholder="Buscar en el mensaje"
          value={queryText}
          onChange={(event) => {
            setQueryText(event.target.value);
            debouncedQuery(event.target.value);
          }}
        />
      </div>
      {query.isPending ? (
        <p>Cargando logs…</p>
      ) : query.isError ? (
        <ErrorState
          message={errorMessage(query.error, "Logs no disponibles.")}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <>
          {query.data.clipped && (
            <p role="status" className="text-sm text-status-notice">
              El rango se ha recortado a los últimos 31 días, los que se
              conservan.
            </p>
          )}
          {items.length === 0 ? (
            <EmptyState message="No hay logs en este rango." />
          ) : (
            <div
              ref={parentRef}
              className="h-[60vh] overflow-auto rounded-md border"
            >
              <div
                style={{
                  height: `${virtualizer.getTotalSize()}px`,
                  position: "relative",
                }}
              >
                {virtualizer.getVirtualItems().map((row) => {
                  const item = items[row.index];
                  if (!item) return null;
                  const level = field(item, "level");
                  return (
                    <button
                      type="button"
                      key={row.key}
                      aria-current={selected === row.index}
                      onClick={() => setSelected(row.index)}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        height: `${row.size}px`,
                        transform: `translateY(${row.start}px)`,
                      }}
                      className={cn(
                        "grid grid-cols-[140px_90px_90px_120px_minmax(0,1fr)] items-center gap-3 border-b px-2 text-left text-sm hover:bg-accent",
                        selected === row.index && "bg-accent",
                      )}
                    >
                      <span>
                        {formatDateTime(
                          field(item, "_time", "ts") ||
                            new Date().toISOString(),
                        )}
                      </span>
                      <span className={LEVEL_COLOR[level] ?? ""}>
                        {level || "—"}
                      </span>
                      <span>{field(item, "service") || "—"}</span>
                      <span>{field(item, "tenant") || "—"}</span>
                      <span className="truncate">
                        {field(item, "_msg", "msg")}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {query.data.truncated && (
            <p className="text-sm text-muted-foreground">
              Hay más resultados de los que se muestran: afina los filtros o
              reduce el rango.
            </p>
          )}
        </>
      )}
      <LogDetailSheet
        item={selected !== null ? (items[selected] ?? null) : null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      />
    </div>
  );
}
