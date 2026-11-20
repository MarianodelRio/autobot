import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { CopyButton } from "@/components/copy-button";
import { ErrorState } from "@/components/error-state";
import { QrCode } from "@/components/qr-code";
import { StatusDot, type StatusDotLevel } from "@/components/status-dot";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorDetail, errorMessage } from "@/lib/errors";

type SetupStep = components["schemas"]["SetupStepOut"];
type SetupAction = components["schemas"]["SetupAction"];
type Detail = components["schemas"]["TenantDetail"];

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

const PIN = /^[0-9]{6}$/;

function StepActionButton({
  slug,
  step,
  action,
}: {
  slug: string;
  step: SetupStep;
  action: SetupAction;
}) {
  const [open, setOpen] = useState(false);
  const [pin, setPin] = useState("");
  const client = useQueryClient();
  const run = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/setup/action/{step}", {
          params: { path: { slug, step: step.key } },
          body: action.needs_pin ? { pin } : {},
        }),
      ),
    onSuccess: (result) => {
      setOpen(false);
      setPin("");
      client.setQueryData<SetupStep[]>(["tenant-setup", slug], (previous) =>
        previous?.map((item) => (item.key === step.key ? result : item)),
      );
      toast.success(result.detail);
    },
  });
  const error = run.isError && (
    <p role="alert" className="text-sm text-status-critical">
      {errorMessage(run.error, "No se pudo completar la acción.")}
    </p>
  );
  if (!action.needs_pin && !action.confirm)
    return (
      <>
        <Button size="sm" disabled={run.isPending} onClick={() => run.mutate()}>
          {action.label}
        </Button>
        {error}
      </>
    );
  const pinId = `setup-pin-${step.key}`;
  return (
    <>
      <Button
        size="sm"
        onClick={() => {
          run.reset();
          setOpen(true);
        }}
      >
        {action.label}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          setOpen(value);
          if (!value) setPin("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{action.label}</DialogTitle>
            <DialogDescription>
              {action.needs_pin
                ? "El PIN de verificación en dos pasos del número (6 dígitos). No se guarda en ningún sitio: apúntalo y guárdalo tú en un lugar seguro."
                : "Esto activa de verdad la recepción de mensajes del número real del negocio. ¿Seguro que quieres hacerlo ahora?"}
            </DialogDescription>
          </DialogHeader>
          {action.needs_pin && (
            <>
              <Label htmlFor={pinId}>PIN de 6 dígitos</Label>
              <Input
                id={pinId}
                inputMode="numeric"
                autoComplete="off"
                maxLength={6}
                value={pin}
                onChange={(event) => setPin(event.target.value)}
              />
            </>
          )}
          <Button
            disabled={run.isPending || (action.needs_pin && !PIN.test(pin))}
            onClick={() => run.mutate()}
          >
            {action.needs_pin ? action.label : "Sí, continuar"}
          </Button>
          {error}
        </DialogContent>
      </Dialog>
    </>
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
      // The forced health check also refreshes what «templates» and the activation
      // checklist read from the cache.
      if (step.key === "health")
        void client.invalidateQueries({
          queryKey: ["activation-checklist", slug],
        });
    },
  });
  return (
    <li className="space-y-1 border-b pb-3 last:border-b-0 last:pb-0">
      <div className="flex items-center gap-2">
        <StatusDot level={STEP_LEVEL[step.state] ?? "unknown"} />
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
        {step.action && (
          <StepActionButton slug={slug} step={step} action={step.action} />
        )}
      </div>
      <p className="text-sm text-muted-foreground">{step.why}</p>
      <p className="text-sm">{step.detail}</p>
      {check.isError && (
        <p role="alert" className="text-sm text-status-critical">
          {errorDetail(check.error, "No se pudo comprobar.")}
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

function QrCard({ detail }: { detail: Detail }) {
  if (detail.channel_type === null) return null;
  return (
    <li className="space-y-2 border-b pb-3 text-sm last:border-b-0 last:pb-0">
      <span className="font-medium">QR del canal</span>
      {detail.public_link ? (
        <QrCode
          value={detail.public_link}
          title="QR del canal público"
          fileName={`canal-${detail.slug}`}
        />
      ) : (
        <div className="flex items-center gap-2">
          <StatusDot level="warning" />
          <span className="text-status-warning">
            {detail.channel_type === "telegram"
              ? "Falta el usuario del bot (bot_username): sin él no hay enlace ni QR."
              : "Falta el teléfono público (display_phone): sin él no hay enlace ni QR."}
          </span>
        </div>
      )}
    </li>
  );
}

function ActivateCard({ slug, steps }: { slug: string; steps: SetupStep[] }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/tenants/{slug}/status", {
          params: { path: { slug } },
          body: { action: "activate", confirm_slug: typed },
        }),
      ),
    onSuccess: () => {
      setOpen(false);
      setTyped("");
      toast.success("Cliente activado.");
      void client.invalidateQueries({ queryKey: ["tenant", slug] });
      void client.invalidateQueries({ queryKey: ["tenants"] });
      void client.invalidateQueries({ queryKey: ["overview"] });
    },
  });
  const blocked = steps.some((step) => step.blocking && step.state !== "ok");
  return (
    <li className="space-y-2 pb-1 text-sm">
      <span className="font-medium">Activar</span>
      <p className="text-muted-foreground">
        Completa los pasos bloqueantes y escribe el slug para confirmar.
      </p>
      <Button
        onClick={() => {
          mutation.reset();
          setOpen(true);
        }}
      >
        Activar
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          setOpen(value);
          if (!value) setTyped("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Activar cliente</DialogTitle>
            <DialogDescription>
              Escribe {slug} para confirmar.
            </DialogDescription>
          </DialogHeader>
          <Label htmlFor="setup-activation-slug">Escribe {slug}</Label>
          <Input
            id="setup-activation-slug"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
          <Button
            disabled={typed !== slug || blocked || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            Activar
          </Button>
          {mutation.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(mutation.error, "No se pudo activar el cliente.")}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </li>
  );
}

export function SetupTab({ slug, detail }: { slug: string; detail: Detail }) {
  const q = useQuery({
    queryKey: ["tenant-setup", slug],
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/setup", { params: { path: { slug } } })),
    staleTime: 0,
    // Reading the steps never calls a provider, but a refetch on every window focus
    // would still overwrite results from «Comprobar» that are not cached.
    refetchOnWindowFocus: false,
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
      <QrCard detail={detail} />
      {detail.status === "onboarding" && (
        <ActivateCard slug={slug} steps={q.data} />
      )}
    </ul>
  );
}
