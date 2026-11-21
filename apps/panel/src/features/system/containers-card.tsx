import type { components } from "@/api/schema";
import { EmptyState } from "@/components/empty-state";
import { StatusDot, toStatusDotLevel } from "@/components/status-dot";
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
import { formatNumber } from "@/lib/format";

const CONTAINER_STATUS_LABEL: Record<string, string> = {
  running: "En marcha",
  restarting: "Reiniciándose",
  exited: "Parado",
  dead: "Muerto",
  created: "Creado",
  paused: "Pausado",
  removing: "Eliminándose",
  missing: "No existe",
};

const CONTAINER_HEALTH_LABEL: Record<string, string> = {
  healthy: "Bien",
  unhealthy: "Fallando",
  starting: "Arrancando",
  none: "—",
};

export function ContainersCard({
  containers,
}: {
  containers: components["schemas"]["ContainersOut"];
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>Contenedores</CardTitle>
        {containers.generated_at && (
          <span className="text-sm text-muted-foreground">
            Actualizado <TimeAgo date={containers.generated_at} />
          </span>
        )}
      </CardHeader>
      <CardContent>
        {!containers.available ? (
          <EmptyState message="Sin datos de contenedores. En producción, revisa autobot-containers.timer." />
        ) : (
          <>
            {containers.stale && (
              <p className="mb-3 text-sm text-status-warning">
                Datos desactualizados: el timer de contenedores puede estar
                parado.
              </p>
            )}
            {containers.maintenance === "deploy" && (
              <p className="mb-3 text-sm text-status-warning">
                Despliegue en curso.
              </p>
            )}
            {containers.maintenance === "restore" && (
              <p className="mb-3 text-sm text-status-warning">
                Restauración a medias.
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Servicio</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Salud</TableHead>
                  <TableHead>Reinicios</TableHead>
                  <TableHead>En marcha desde</TableHead>
                  <TableHead>Imagen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {containers.items.map((item) => (
                  <TableRow key={item.name ?? item.service}>
                    <TableCell>{item.service}</TableCell>
                    <TableCell>
                      <StatusDot
                        level={toStatusDotLevel(item.level)}
                        label={
                          item.reason ??
                          CONTAINER_STATUS_LABEL[item.status] ??
                          item.status
                        }
                      />
                    </TableCell>
                    <TableCell>
                      {CONTAINER_HEALTH_LABEL[item.health] ?? item.health}
                    </TableCell>
                    <TableCell>{formatNumber(item.restart_count)}</TableCell>
                    <TableCell>
                      {item.status === "running" && item.started_at ? (
                        <TimeAgo date={item.started_at} />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell
                      className={
                        item.image_matches === false
                          ? "font-mono text-status-warning"
                          : "font-mono"
                      }
                    >
                      {item.image_tag ? item.image_tag.slice(0, 12) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </CardContent>
    </Card>
  );
}
