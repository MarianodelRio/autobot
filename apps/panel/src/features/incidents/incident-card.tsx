import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { StatusBadge } from "@/components/status-badge";
import { TimeAgo } from "@/components/time-ago";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";
import { CaseItem } from "./case-items";
import {
  type Case,
  DELIVERY_HINT,
  type Incident,
  incidentsChanged,
  logsWindow,
} from "./shared";

function ReviewButton({ incident }: { incident: Incident }) {
  const [open, setOpen] = useState(false);
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/incidents/{id}/review", {
          params: { path: { id: incident.id } },
        }),
      ),
    success: "Incidencia revisada.",
    invalidate: incidentsChanged(),
    tenant: incident.tenant ?? undefined,
    appliesConfig: false,
    onSuccess: () => setOpen(false),
  });
  return (
    <>
      <Button
        size="sm"
        disabled={mutation.isPending}
        onClick={() => setOpen(true)}
      >
        Lo he revisado
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Marcar como revisada"
        description="Dejará de aparecer aquí. Si ocurre algo nuevo del mismo tipo, volverá a abrirse."
        confirmLabel="Lo he revisado"
        onConfirm={() => mutation.mutate()}
      />
      {mutation.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(mutation.error, "No se pudo marcar como revisada.")}
        </p>
      )}
    </>
  );
}

/** The embedded cases, or — after «Ver más» — the whole paginated list. */
function Cases({ incident }: { incident: Incident }) {
  const [all, setAll] = useState(false);
  const query = useInfiniteQuery({
    queryKey: qk.incidentCases(incident.id),
    enabled: all,
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/incidents/{id}/cases", {
          params: { path: { id: incident.id }, query: { cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const loaded: Case[] | undefined = query.data?.pages.flatMap(
    (page) => page.items,
  );
  const cases = loaded ?? incident.cases;
  const more = all ? query.hasNextPage : cases.length < incident.case_count;
  const tenant = incident.tenant ?? undefined;
  return (
    <div className="space-y-2">
      <ul className="space-y-2">
        {cases.map((item) => (
          <CaseItem
            key={`${item.type}-${item.id}`}
            item={item}
            tenant={tenant}
          />
        ))}
      </ul>
      {query.isError && (
        <p role="alert" className="text-sm text-destructive">
          No se pudieron cargar más casos.
        </p>
      )}
      {more && (
        <Button
          size="sm"
          variant="outline"
          disabled={query.isFetching}
          onClick={() => {
            if (all) void query.fetchNextPage();
            else setAll(true);
          }}
        >
          Ver más
        </Button>
      )}
    </div>
  );
}

export function IncidentCard({ incident }: { incident: Incident }) {
  const [open, setOpen] = useState(false);
  const delivery = DELIVERY_HINT[incident.delivery];
  const count =
    incident.new_since_review != null
      ? `${incident.new_since_review} nuevos desde tu revisión`
      : null;
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={incident.severity} />
              {incident.tenant ? (
                <Link
                  className="text-sm underline"
                  to="/clientes/$slug"
                  params={{ slug: incident.tenant }}
                >
                  {incident.tenant}
                </Link>
              ) : (
                <span className="text-sm text-muted-foreground">
                  Plataforma
                </span>
              )}
              <h2 className="font-medium">{incident.title}</h2>
            </div>
            <p className="text-sm">{incident.advice}</p>
            <p className="text-sm text-muted-foreground">
              Desde hace <TimeAgo date={incident.first_seen_at} /> · última vez{" "}
              <TimeAgo date={incident.last_seen_at} />
              {incident.case_count > 0 &&
                ` · ${incident.case_count} ${incident.case_count === 1 ? "caso" : "casos"}`}
              {count && ` · ${count}`}
              {delivery && ` · ${delivery}`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" asChild>
              <Link
                to="/logs"
                search={{
                  tab: "technical",
                  tenant: incident.tenant ?? undefined,
                  ...logsWindow(incident.last_seen_at),
                }}
              >
                Ver logs
              </Link>
            </Button>
            {incident.runbook && (
              <Button size="sm" variant="outline" asChild>
                <a href={incident.runbook} target="_blank" rel="noopener">
                  Ver runbook
                </a>
              </Button>
            )}
            {incident.reviewable && <ReviewButton incident={incident} />}
          </div>
        </div>
        {incident.nature === "condition" && (
          <p className="text-sm text-muted-foreground">
            Se cierra sola cuando se arregle.
          </p>
        )}
        {incident.case_count > 0 && (
          <div className="space-y-2">
            <Button
              size="sm"
              variant="ghost"
              aria-expanded={open}
              onClick={() => setOpen(!open)}
            >
              {open
                ? "Ocultar casos"
                : `Ver ${incident.case_count} ${incident.case_count === 1 ? "caso" : "casos"}`}
            </Button>
            {open && <Cases incident={incident} />}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
