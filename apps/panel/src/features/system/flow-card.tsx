import type { components } from "@/api/schema";
import { StatusDot } from "@/components/status-dot";
import { TimeAgo } from "@/components/time-ago";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import { FLOW_LEVEL, levelOf } from "@/lib/status-levels";

const FLOW_LABEL: Record<string, string> = {
  ok: "Funcionando",
  idle: "Sin tráfico reciente",
  critical: "Con problemas",
};

export function FlowCard({ flow }: { flow: components["schemas"]["FlowOut"] }) {
  // ISO timestamps sort lexicographically: the latest of the two, if any.
  const lastAt = [flow.last_inbound_at, flow.last_outbound_at]
    .filter((at) => at != null)
    .sort()
    .at(-1);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Flujo de mensajes</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <StatusDot
            level={levelOf(FLOW_LEVEL, flow.state)}
            label={
              flow.state === "critical" && flow.reason
                ? flow.reason
                : FLOW_LABEL[flow.state]
            }
          />
          <p className="mt-1 text-sm text-muted-foreground">
            {lastAt ? (
              <>
                Último mensaje <TimeAgo date={lastAt} />
              </>
            ) : (
              "Sin mensajes todavía"
            )}
          </p>
        </div>
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="font-mono text-2xl tabular-nums">
              {formatNumber(flow.received_1h)}
            </p>
            <p className="text-sm text-muted-foreground">recibidos</p>
          </div>
          <div>
            <p className="font-mono text-2xl tabular-nums">
              {formatNumber(flow.answered_1h)}
            </p>
            <p className="text-sm text-muted-foreground">respondidos</p>
          </div>
          <div>
            <p className="font-mono text-2xl tabular-nums">
              {formatNumber(flow.failed_1h)}
            </p>
            <p className="text-sm text-muted-foreground">fallos</p>
          </div>
        </div>
        <p className="text-center text-xs text-muted-foreground">última hora</p>
      </CardContent>
    </Card>
  );
}
