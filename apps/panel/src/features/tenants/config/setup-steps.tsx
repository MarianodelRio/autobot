import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { CopyButton } from "@/components/copy-button";
import { QrCode } from "@/components/qr-code";
import { StatusDot } from "@/components/status-dot";
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
import { qk } from "@/lib/queries";
import {
  overlaySteps,
  recordSetupResult,
  useSetupChecks,
} from "@/lib/setup-checks";
import { levelOf, STEP_LEVEL } from "@/lib/status-levels";
import { useApiMutation } from "@/lib/use-api-mutation";

type SetupStep = components["schemas"]["SetupStepOut"];
type SetupAction = components["schemas"]["SetupAction"];
type Detail = components["schemas"]["TenantDetail"];

function TesterCandidates({ slug, step }: { slug: string; step: SetupStep }) {
  const add = useApiMutation({
    fn: (id: string) =>
      unwrap(
        api.POST("/tenants/{slug}/setup/testers", {
          params: { path: { slug } },
          body: { id },
        }),
      ),
    success: "Tester añadido.",
    tenant: slug,
    error: "No se pudo añadir el tester.",
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
  version,
  step,
  action,
  locked,
}: {
  slug: string;
  version: number | null | undefined;
  step: SetupStep;
  action: SetupAction;
  locked: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pin, setPin] = useState("");
  const client = useQueryClient();
  const run = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/setup/action/{step}", {
          params: { path: { slug, step: step.key } },
          body: action.needs_pin ? { pin } : {},
        }),
      ),
    success: (result) => result.detail,
    tenant: slug,
    channel: true, // channel steps register things at Meta / Telegram
    appliesConfig: false,
    onSuccess: (result) => {
      setOpen(false);
      setPin("");
      recordSetupResult(client, slug, result, version);
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
        <Button
          type="button"
          size="sm"
          disabled={locked || run.isPending}
          onClick={() => run.mutate()}
        >
          {action.label}
        </Button>
        {error}
      </>
    );
  const pinId = `setup-pin-${step.key}`;
  return (
    <>
      <Button
        type="button"
        size="sm"
        disabled={locked}
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

/** One onboarding step inside its Configuración section. `locked` while that section
 * has unsaved edits: checks and actions run against what is saved. */
export function StepRow({
  slug,
  version,
  step,
  locked = false,
}: {
  slug: string;
  /** The tenant's configuration version on screen: tags the results of checks. */
  version: number | null | undefined;
  step: SetupStep;
  locked?: boolean;
}) {
  const client = useQueryClient();
  const check = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/setup/check/{step}", {
          params: { path: { slug, step: step.key } },
        }),
      ),
    // A check can change what the rest of the tenant shows (the forced health
    // check feeds the activation checklist). The step result is stored apart
    // (setup-checks), so the refetch this triggers cannot wipe it.
    tenant: slug,
    channel: true, // it may have just read the webhook from Telegram
    appliesConfig: false,
    onSuccess: (result) => recordSetupResult(client, slug, result, version),
  });
  return (
    <li className="space-y-1 border-b pb-3 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <StatusDot level={levelOf(STEP_LEVEL, step.state)} />
        <span className="font-medium">{step.label}</span>
        {step.blocking && (
          <span className="text-xs text-muted-foreground">(obligatorio)</span>
        )}
        <span className="ml-auto flex flex-wrap items-center gap-2">
          {step.checkable && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={locked || check.isPending}
              onClick={() => check.mutate()}
            >
              Comprobar
            </Button>
          )}
          {step.action && (
            <StepActionButton
              slug={slug}
              version={version}
              step={step}
              action={step.action}
              locked={locked}
            />
          )}
        </span>
      </div>
      <p className="text-sm">{step.detail}</p>
      <p className="text-xs text-muted-foreground">{step.why}</p>
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

/** The downloadable QR of the public link (the missing-link warning is shown by
 * `ChannelSection`, right above it). */
export function ChannelQr({ detail }: { detail: Detail }) {
  if (detail.channel_type === null || !detail.public_link) return null;
  return (
    <div className="space-y-2 text-sm">
      <span className="font-medium">QR del canal</span>
      <QrCode
        value={detail.public_link}
        title="QR del canal público"
        fileName={`canal-${detail.slug}`}
      />
    </div>
  );
}

/** The onboarding steps: what the backend reports (never a provider call) with the
 * stored «Comprobar» results of the tenant's current `version` laid over them. */
export function useSetupSteps(
  slug: string,
  version: number | null | undefined,
) {
  const checks = useSetupChecks(slug);
  const select = useCallback(
    (steps: SetupStep[]) => overlaySteps(steps, checks, version),
    [checks, version],
  );
  return useQuery({
    queryKey: qk.tenantSetup(slug),
    queryFn: () =>
      unwrap(api.GET("/tenants/{slug}/setup", { params: { path: { slug } } })),
    staleTime: 0,
    select,
  });
}

function ActivateButton({ slug, blocked }: { slug: string; blocked: boolean }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const mutation = useApiMutation({
    fn: () =>
      unwrap(
        api.POST("/tenants/{slug}/status", {
          params: { path: { slug } },
          body: { action: "activate", confirm_slug: typed },
        }),
      ),
    success: "Cliente activado.",
    tenant: slug,
    channel: true,
    onSuccess: () => {
      setOpen(false);
      setTyped("");
    },
  });
  return (
    <>
      <Button
        type="button"
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
          {blocked && (
            <p className="text-sm text-status-warning">
              Faltan pasos obligatorios: complétalos antes de activar.
            </p>
          )}
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
    </>
  );
}

/** Top of the Configuración tab while the tenant is in alta: how many mandatory
 * steps are done, a link to the section of each missing one, and «Activar». */
export function ActivationBanner({
  slug,
  steps,
  sectionLabel,
  onGo,
}: {
  slug: string;
  steps: SetupStep[];
  /** The label of a section key, or undefined if no section has that key. */
  sectionLabel: (key: string) => string | undefined;
  onGo: (section: string) => void;
}) {
  const mandatory = steps.filter((step) => step.blocking);
  const missing = mandatory.filter((step) => step.state !== "ok");
  return (
    <section
      aria-label="Progreso del alta"
      className="space-y-3 rounded-md border bg-card p-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        <StatusDot level={missing.length === 0 ? "ok" : "warning"} />
        <span className="font-medium">
          Alta: {mandatory.length - missing.length} de {mandatory.length} pasos
          obligatorios listos
        </span>
        <span className="ml-auto">
          <ActivateButton slug={slug} blocked={missing.length > 0} />
        </span>
      </div>
      {missing.length > 0 ? (
        <ul className="flex flex-wrap gap-2 text-sm">
          <li className="text-muted-foreground">Falta:</li>
          {missing.map((step) => {
            const label = sectionLabel(step.section);
            return (
              <li key={step.key}>
                {label ? (
                  <button
                    type="button"
                    className="underline underline-offset-2"
                    onClick={() => onGo(step.section)}
                  >
                    {step.label} ({label})
                  </button>
                ) : (
                  step.label
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          Todos los pasos obligatorios están listos: ya se puede activar.
        </p>
      )}
    </section>
  );
}
