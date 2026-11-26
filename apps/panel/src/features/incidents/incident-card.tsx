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
  newSinceReview,
} from "./shared";

function ReviewButton({ incident }: { incident: Incident }) {
  // One click: the review is cheap to undo (a new case reopens the incident). It
  // carries the last case the card displays, so a later case is not swallowed.
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/incidents/{id}/review", {
          params: { path: { id: incident.id } },
          body: { seen_through: incident.seen_through },
        }),
      ),
    success: "Incidencia revisada.",
    invalidate: incidentsChanged(),
    tenant: incident.tenant ?? undefined,
    appliesConfig: false,
  });
  return (
    <>
      <Button
        size="sm"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        Lo he revisado
      </Button>
      {mutation.isError && (
        <p role="alert" className="basis-full text-sm text-destructive">
          {errorMessage(mutation.error, "No se pudo marcar como revisada.")}
        </p>
      )}
    </>
  );
}

function DiscardAllButton({ incident }: { incident: Incident }) {
  const [open, setOpen] = useState(false);
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/incidents/{id}/discard-all", {
          params: { path: { id: incident.id } },
        }),
      ),
    success: "Envíos descartados.",
    invalidate: incidentsChanged(),
    tenant: incident.tenant ?? undefined,
    appliesConfig: false,
    onSuccess: () => setOpen(false),
    onError: () => setOpen(false),
  });
  return (
    <>
      <Button
        size="sm"
        variant="outline"
        disabled={mutation.isPending || mutation.isSuccess}
        onClick={() => setOpen(true)}
      >
        Descartar todos
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title="Descartar todos"
        description={`Se descartarán ${incident.case_count} envíos ambiguos: no se reenviarán.`}
        confirmLabel="Descartar todos"
        onConfirm={() => mutation.mutate()}
      />
      {mutation.isError && (
        <p role="alert" className="basis-full text-sm text-destructive">
          {errorMessage(mutation.error, "No se pudieron descartar los envíos.")}
        </p>
      )}
    </>
  );
}

const PAGE_SIZE = 20;

/** The embedded preview, or — after «Ver más» — the whole paginated list. The
 * query is seeded with the preview, so «Ver más» continues from its cursor. */
function Cases({ incident }: { incident: Incident }) {
  const query = useInfiniteQuery({
    // The cursor in the key: a refreshed preview seeds a fresh query.
    queryKey: [...qk.incidentCases(incident.id), incident.cases_next_cursor],
    initialPageParam: "",
    initialData: {
      pages: [
        { items: incident.cases, next_cursor: incident.cases_next_cursor },
      ],
      pageParams: [""],
    },
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/incidents/{id}/cases", {
          params: {
            path: { id: incident.id },
            query: { cursor: pageParam, limit: PAGE_SIZE },
          },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const paged = (query.data?.pages.length ?? 1) > 1;
  // Until paged, the live preview wins (the open list refreshes every 30 s).
  const cases: Case[] = paged
    ? (query.data?.pages.flatMap((page) => page.items) ?? [])
    : incident.cases;
  const more = paged ? query.hasNextPage : incident.cases_next_cursor != null;
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
          onClick={() => void query.fetchNextPage()}
        >
          Ver más
        </Button>
      )}
    </div>
  );
}

/** The figures of the incident (disk %, counts, restarts), when they add to the title. */
function showText(incident: Incident): boolean {
  const text = incident.text.trim();
  if (!text) return false;
  if (!incident.has_cases) return text !== incident.title;
  return !text.includes(incident.title) && !incident.title.includes(text);
}

export function IncidentCard({ incident }: { incident: Incident }) {
  // The only way to close an ambiguous-sends incident is acting on them.
  const [open, setOpen] = useState(incident.kind === "outbound_ambiguous");
  const delivery = DELIVERY_HINT[incident.delivery];
  const count = newSinceReview(incident.new_since_review);
  const withCases = incident.has_cases && incident.case_count > 0;
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
            {showText(incident) && (
              <p className="text-sm text-muted-foreground">{incident.text}</p>
            )}
            <p className="text-sm text-muted-foreground">
              Desde hace <TimeAgo date={incident.first_seen_at} /> · última vez{" "}
              <TimeAgo date={incident.last_seen_at} />
              {withCases &&
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
            {incident.kind === "owner_unlinked" && incident.tenant && (
              <Button size="sm" variant="outline" asChild>
                <Link
                  to="/clientes/$slug"
                  params={{ slug: incident.tenant }}
                  search={{ tab: "configuracion", section: "personas" }}
                >
                  Invitar al dueño
                </Link>
              </Button>
            )}
            {incident.kind === "outbound_ambiguous" &&
              incident.can_discard_all && (
                <DiscardAllButton incident={incident} />
              )}
            {incident.reviewable && <ReviewButton incident={incident} />}
          </div>
        </div>
        {incident.nature === "condition" && (
          <p className="text-sm text-muted-foreground">
            Se cierra sola cuando se arregle.
          </p>
        )}
        {withCases && (
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
