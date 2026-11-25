import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { StatusDot } from "@/components/status-dot";
import { TimeAgo } from "@/components/time-ago";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorMessage } from "@/lib/errors";
import { formatNumber } from "@/lib/format";
import { LIVE, qk } from "@/lib/queries";

/** The configuration revision in the database and the one each alive backend process
 * has loaded (ADR-030); a process behind it is marked. */
export function ConfigCard() {
  const query = useQuery({
    queryKey: qk.systemConfig(),
    ...LIVE,
    queryFn: () => unwrap(api.GET("/system/config")),
  });
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Configuración cargada</CardTitle>
        {query.data && (
          <span className="text-sm text-muted-foreground">
            Revisión {formatNumber(query.data.revision)}
            {query.data.updated_at && (
              <>
                {" "}
                · cambió <TimeAgo date={query.data.updated_at} />
              </>
            )}
          </span>
        )}
      </CardHeader>
      <CardContent>
        {query.isPending ? (
          <p>Cargando…</p>
        ) : query.isError ? (
          <ErrorState
            message={errorMessage(
              query.error,
              "No se pudo cargar la configuración cargada.",
            )}
            onRetry={() => void query.refetch()}
          />
        ) : query.data.processes.length === 0 ? (
          <EmptyState message="Ningún proceso ha informado todavía de su configuración." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Servicio</TableHead>
                <TableHead>Contenedor</TableHead>
                <TableHead>Revisión</TableHead>
                <TableHead>Último latido</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.processes.map((process) => (
                <TableRow key={`${process.host}-${process.pid}`}>
                  <TableCell className="font-mono">{process.service}</TableCell>
                  <TableCell className="font-mono text-sm">
                    {process.host}:{process.pid}
                  </TableCell>
                  <TableCell>
                    <StatusDot
                      level={process.behind ? "warning" : "ok"}
                      label={
                        process.behind
                          ? `${formatNumber(process.revision)} (atrasado)`
                          : formatNumber(process.revision)
                      }
                    />
                  </TableCell>
                  <TableCell>
                    <TimeAgo date={process.seen_at} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
