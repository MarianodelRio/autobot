import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { TimeAgo } from "@/components/time-ago";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatEur, formatNumber } from "@/lib/format";
import { errorMessage } from "./error-message";

export function TenantListPage() {
  const [search, setSearch] = useState("");
  const [pack, setPack] = useState("");
  const [status, setStatus] = useState("");
  const query = useQuery({
    queryKey: ["tenants"],
    queryFn: () => unwrap(api.GET("/tenants")),
  });
  const rows = query.data ?? [];
  const filtered = rows.filter(
    (row) =>
      `${row.name} ${row.slug}`
        .toLocaleLowerCase()
        .includes(search.toLocaleLowerCase()) &&
      (!pack || row.pack === pack) &&
      (!status || row.status === status),
  );
  return (
    <div>
      <PageHeader
        title="Clientes"
        actions={
          <a
            className="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground"
            href="/clientes/nuevo"
          >
            Nuevo cliente
          </a>
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <Input
          className="max-w-xs"
          aria-label="Buscar clientes"
          placeholder="Buscar clientes"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          className="rounded-md border bg-background px-3"
          aria-label="Pack"
          value={pack}
          onChange={(event) => setPack(event.target.value)}
        >
          <option value="">Todos los packs</option>
          {[...new Set(rows.map((row) => row.pack))].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <select
          className="rounded-md border bg-background px-3"
          aria-label="Estado"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">Todos los estados</option>
          {[...new Set(rows.map((row) => row.status))].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>
      {query.isPending ? (
        <p>Cargando clientes…</p>
      ) : query.isError ? (
        <ErrorState
          message={errorMessage(
            query.error,
            "No se pudieron cargar los clientes.",
          )}
          onRetry={() => void query.refetch()}
        />
      ) : filtered.length === 0 ? (
        <EmptyState message="No hay clientes que mostrar." />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              {[
                "Negocio",
                "Pack",
                "Canal",
                "Estado",
                "Salud",
                "Mensajes mes",
                "Coste",
                "Última actividad",
              ].map((label) => (
                <TableHead key={label}>{label}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((row) => (
              <TableRow key={row.slug}>
                <TableCell>
                  <a
                    className="underline"
                    href={`/clientes/${encodeURIComponent(row.slug)}`}
                  >
                    {row.name}
                  </a>
                </TableCell>
                <TableCell>{row.pack}</TableCell>
                <TableCell>{row.channel}</TableCell>
                <TableCell>{row.status}</TableCell>
                <TableCell>{row.health}</TableCell>
                <TableCell>
                  {formatNumber(row.inbound_month)} /{" "}
                  {formatNumber(row.outbound_month)}
                </TableCell>
                <TableCell>{formatEur(Number(row.cost_eur_month))}</TableCell>
                <TableCell>
                  {row.last_activity_at ? (
                    <TimeAgo date={row.last_activity_at} />
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
