import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { CopyButton } from "@/components/copy-button";
import { ErrorState } from "@/components/error-state";
import { StatusDot, type StatusDotLevel } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";

type SetupStep = components["schemas"]["SetupStepOut"];

const STEP_LEVEL: Record<SetupStep["state"], StatusDotLevel> = {
  ok: "ok",
  pending: "notice",
  error: "critical",
  "n/a": "unknown",
};

function TesterCandidates({ slug, step }: { slug: string; step: SetupStep }) {
  const client = useQueryClient();
  const add = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/tenants/{slug}/setup/testers", {
          params: { path: { slug } },
          body: { id },
        }),
      ),
    onSuccess: (result) => {
      client.setQueryData<SetupStep[]>(["tenant-setup", slug], (previous) =>
        previous?.map((item) => (item.key === step.key ? result : item)),
      );
      toast.success("Tester añadido.");
    },
    onError: (error) =>
      toast.error(errorMessage(error, "No se pudo añadir el tester.")),
  });
  if (step.tester_candidates.length === 0) return null;
  return (
    <div className="space-y-1 text-sm">
      <p className="text-muted-foreground">
        Últimos que escribieron sin ser testers:
      </p>
      <ul className="space-y-1">
        {step.tester_candidates.map((candidate) => (
          <li key={candidate.id} className="flex items-center gap-2">
            <code>{candidate.display}</code>
            <Button
              size="sm"
              variant="outline"
              disabled={add.isPending}
              onClick={() => add.mutate(candidate.id)}
            >
              Añadir
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StepCard({ slug, step }: { slug: string; step: SetupStep }) {
  const client = useQueryClient();
  const check = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/setup/check/{step}", {
          params: { path: { slug, step: step.key } },
        }),
      ),
    onSuccess: (result) => {
      client.setQueryData<SetupStep[]>(["tenant-setup", slug], (previous) =>
        previous?.map((item) => (item.key === step.key ? result : item)),
      );
    },
  });
  return (
    <li className="space-y-1 border-b pb-3 last:border-b-0 last:pb-0">
      <div className="flex items-center gap-2">
        <StatusDot level={STEP_LEVEL[step.state]} />
        <span className="font-medium">{step.label}</span>
        {step.blocking && (
          <span className="text-xs text-muted-foreground">(bloqueante)</span>
        )}
        {step.checkable && (
          <Button
            size="sm"
            variant="outline"
            disabled={check.isPending}
            onClick={() => check.mutate()}
          >
            Comprobar
          </Button>
        )}
      </div>
      <p className="text-sm text-muted-foreground">{step.why}</p>
      <p className="text-sm">{step.detail}</p>
      {check.isError && (
        <p role="alert" className="text-sm text-status-critical">
          No se pudo comprobar.
        </p>
      )}
      {step.values.length > 0 && (
        <dl className="space-y-1 text-sm">
          {step.values.map((value) => (
            <div key={value.label} className="flex items-center gap-2">
              <dt className="text-muted-foreground">{value.label}</dt>
              <dd className="flex items-center gap-1">
                <code>{value.value}</code>
                {value.copiable && <CopyButton value={value.value} />}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {step.key === "tester" && <TesterCandidates slug={slug} step={step} />}
    </li>
  );
}

export function SetupTab({ slug }: { slug: string }) {
  const q = useQuery({
    queryKey: ["tenant-setup", slug],
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/setup", { params: { path: { slug } } })),
    staleTime: 0,
  });
  if (q.isPending) return <p>Cargando pasos del alta…</p>;
  if (q.isError)
    return (
      <ErrorState
        message="No se pudieron cargar los pasos del alta."
        onRetry={() => void q.refetch()}
      />
    );
  return (
    <ul className="space-y-3">
      {q.data.map((step) => (
        <StepCard key={step.key} slug={slug} step={step} />
      ))}
    </ul>
  );
}
