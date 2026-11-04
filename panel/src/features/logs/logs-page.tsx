import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";

export interface LogsFilters {
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
  { value: "mes", label: "Mes", minutes: 31 * 24 * 60 },
];

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

function LogRow({
  item,
  open,
  onToggle,
}: {
  item: Record<string, unknown>;
  open: boolean;
  onToggle: () => void;
}) {
  const eventId = field(item, "event_id");
  return (
    <div className="border-b">
      <button
        type="button"
        className="grid w-full grid-cols-[140px_90px_90px_120px_1fr] items-start gap-3 py-2 text-left text-sm"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span>
          {formatDateTime(
            field(item, "_time", "ts") || new Date().toISOString(),
          )}
        </span>
        <span>{field(item, "level") || "—"}</span>
        <span>{field(item, "service") || "—"}</span>
        <span>{field(item, "tenant") || "—"}</span>
        <span className="truncate">{field(item, "_msg", "msg")}</span>
      </button>
      {open && (
        <div className="mb-2 space-y-2 pl-4 text-sm">
          {field(item, "exception") && (
            <pre className="overflow-auto whitespace-pre-wrap text-destructive">
              {field(item, "exception")}
            </pre>
          )}
          <pre className="overflow-auto">{JSON.stringify(item, null, 2)}</pre>
          {eventId && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void navigator.clipboard?.writeText(eventId);
                toast.success("event_id copiado.");
              }}
            >
              Copiar event_id
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export function LogsPage({
  filters,
  onFilterChange,
}: {
  filters: LogsFilters;
  onFilterChange: (next: Partial<LogsFilters>) => void;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const parentRef = useRef<HTMLDivElement>(null);
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
    <div>
      <PageHeader title="Logs" />
      <div className="mb-3 flex flex-wrap gap-2">
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
      <div className="mb-4 flex flex-wrap items-center gap-3">
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
          value={filters.service}
          onChange={(event) => onFilterChange({ service: event.target.value })}
        />
        <Input
          className="max-w-xs"
          aria-label="Cliente"
          placeholder="Cliente (slug)"
          value={filters.tenant}
          onChange={(event) => onFilterChange({ tenant: event.target.value })}
        />
        <Input
          className="max-w-xs"
          aria-label="Texto"
          placeholder="Buscar en el mensaje"
          value={filters.q}
          onChange={(event) => onFilterChange({ q: event.target.value })}
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
            <p role="status" className="mb-2 text-sm text-status-notice">
              El rango se ha recortado: solo se conserva el mes en curso.
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
                  return (
                    <div
                      key={row.key}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        transform: `translateY(${row.start}px)`,
                      }}
                    >
                      <LogRow
                        item={item}
                        open={expanded.has(row.index)}
                        onToggle={() =>
                          setExpanded((current) => {
                            const next = new Set(current);
                            if (next.has(row.index)) next.delete(row.index);
                            else next.add(row.index);
                            return next;
                          })
                        }
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {query.data.truncated && (
            <p className="mt-2 text-sm text-muted-foreground">
              Hay más resultados de los que se muestran: afina los filtros o
              reduce el rango.
            </p>
          )}
        </>
      )}
    </div>
  );
}
