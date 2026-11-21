import type { components } from "@/api/schema";
import { StatusDot } from "@/components/status-dot";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { INTEGRATION_LEVEL, levelOf } from "@/lib/status-levels";

const SERVICE_LABEL: Record<string, string> = {
  worker: "worker",
  db: "db",
  victorialogs: "logs",
};

export function StatusCard({
  services,
  integrations,
}: {
  services: Record<string, boolean>;
  integrations: components["schemas"]["IntegrationOut"][];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Estado</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Plataforma
          </p>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(services).map(([name, ok]) => (
              <StatusDot
                key={name}
                level={ok ? "ok" : "critical"}
                label={SERVICE_LABEL[name] ?? name}
              />
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Integraciones
          </p>
          <div className="space-y-1.5">
            {integrations.map((integration) => (
              <div
                key={integration.key}
                className="flex items-center justify-between text-sm"
              >
                <StatusDot
                  level={levelOf(INTEGRATION_LEVEL, integration.state)}
                  label={integration.label}
                />
                <span className="text-muted-foreground">
                  {integration.state === "off" ? "apagada" : integration.detail}
                </span>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
