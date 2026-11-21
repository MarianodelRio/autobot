import type { UseQueryResult } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TimezoneSelect } from "@/features/tenants/config/timezone-widget";
import { type Draft, slugFromName, validSlug } from "./draft";

export function BasicsStep({
  draft,
  update,
  available,
  onBack,
  onNext,
}: {
  draft: Draft;
  update: (patch: Partial<Draft>) => void;
  available: Pick<
    UseQueryResult<{ available: boolean }>,
    "data" | "isFetching" | "isError"
  >;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <section className="space-y-4">
      <h2 className="font-semibold">Datos básicos</h2>
      <div>
        <Label htmlFor="new-name">Nombre</Label>
        <Input
          id="new-name"
          value={draft.name}
          onChange={(event) =>
            update({
              name: event.target.value,
              ...(!draft.slugEdited
                ? { slug: slugFromName(event.target.value) }
                : {}),
            })
          }
        />
      </div>
      <div>
        <Label htmlFor="new-slug">Slug</Label>
        <Input
          id="new-slug"
          value={draft.slug}
          onChange={(event) =>
            update({ slug: event.target.value, slugEdited: true })
          }
        />
        {draft.slug && !validSlug(draft.slug) && (
          <p role="alert" className="text-sm text-destructive">
            Usa hasta 64 letras minúsculas, números y guiones.
          </p>
        )}
        {validSlug(draft.slug) &&
          (available.isFetching ? (
            <p>Comprobando disponibilidad…</p>
          ) : available.isError ? (
            <p role="alert" className="text-sm text-destructive">
              No se pudo comprobar el slug.
            </p>
          ) : (
            available.data && (
              <p>
                {available.data.available
                  ? "Slug disponible."
                  : "Este slug ya existe."}
              </p>
            )
          ))}
      </div>
      <div>
        <Label htmlFor="new-timezone">Zona horaria</Label>
        <TimezoneSelect
          id="new-timezone"
          value={draft.timezone}
          onChange={(timezone) => update({ timezone })}
        />
      </div>
      <div>
        <Label htmlFor="new-channel">Canal</Label>
        <select
          id="new-channel"
          className="block rounded-md border bg-background p-2"
          value={draft.channel}
          onChange={(event) =>
            update({ channel: event.target.value as Draft["channel"] })
          }
        >
          <option value="whatsapp">WhatsApp</option>
          <option value="telegram">Telegram</option>
        </select>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" onClick={onBack}>
          Anterior
        </Button>
        <Button
          disabled={
            !draft.name.trim() ||
            !draft.timezone.trim() ||
            !validSlug(draft.slug) ||
            !available.data?.available ||
            available.isFetching ||
            available.isError
          }
          onClick={onNext}
        >
          Siguiente
        </Button>
      </div>
    </section>
  );
}
