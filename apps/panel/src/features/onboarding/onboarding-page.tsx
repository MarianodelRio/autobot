import Form from "@rjsf/shadcn";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ComponentProps, useEffect, useMemo, useState } from "react";
import YAML from "yaml";
import { type ApiError, api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/error-state";
import { JsonDiff } from "@/components/json-diff";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { errorsToSchema } from "@/features/tenants/config/editor";
import { validator } from "@/lib/form-validator";

const STORAGE_KEY = "autobot.onboarding";
type Draft = {
  step: number;
  pack: string;
  name: string;
  slug: string;
  slugEdited: boolean;
  timezone: string;
  channel: "whatsapp" | "telegram";
  config: Record<string, unknown> | null;
  template: Record<string, unknown> | null;
  // C22: {dataset name -> chosen library entry name}; empty for a pack with none.
  datasetChoices: Record<string, string>;
};
const initial: Draft = {
  step: 1,
  pack: "",
  name: "",
  slug: "",
  slugEdited: false,
  timezone: "Europe/Madrid",
  channel: "whatsapp",
  config: null,
  template: null,
  datasetChoices: {},
};
export function slugFromName(name: string) {
  return name
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/g, "");
}
export function validSlug(slug: string) {
  return slug.length <= 64 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug);
}
function restore(): Draft {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return initial;
    const value = JSON.parse(raw);
    if (
      !value ||
      typeof value !== "object" ||
      typeof value.pack !== "string" ||
      typeof value.name !== "string" ||
      typeof value.slug !== "string" ||
      typeof value.timezone !== "string" ||
      ![1, 2, 3, 4, 5].includes(value.step) ||
      !["whatsapp", "telegram"].includes(value.channel)
    )
      return initial;
    return { ...initial, ...value };
  } catch {
    return initial;
  }
}
function configSchema(
  document: Record<string, unknown>,
): Record<string, unknown> | null {
  const props = document.properties;
  if (
    !props ||
    typeof props !== "object" ||
    !("config" in props) ||
    !props.config ||
    typeof props.config !== "object"
  )
    return null;
  return {
    ...(props.config as Record<string, unknown>),
    $defs: document.$defs,
  };
}
function configUi(
  value: Record<string, unknown>,
): ComponentProps<typeof Form>["uiSchema"] {
  const result: Record<string, unknown> = {};
  if (!value.widgets || typeof value.widgets !== "object") return result;
  for (const [path, widget] of Object.entries(value.widgets)) {
    if (!path.startsWith("config.")) continue;
    let node = result;
    for (const part of path.slice(7).split(".")) {
      if (!node[part]) node[part] = {};
      node = node[part] as Record<string, unknown>;
    }
    node["ui:widget"] = widget;
  }
  return result;
}

function DatasetChoiceField({
  pack,
  dataset,
  value,
  onChange,
}: {
  pack: string;
  dataset: string;
  value: string;
  onChange: (name: string) => void;
}) {
  const entries = useQuery({
    queryKey: ["dataset-library", pack, dataset],
    queryFn: () =>
      unwrap(
        api.GET("/packs/{pack}/datasets/{dataset}/library", {
          params: { path: { pack, dataset } },
        }),
      ),
  });
  if (entries.isPending) return <p>Cargando biblioteca de {dataset}…</p>;
  if (entries.isError)
    return (
      <ErrorState
        message={`No se pudo cargar la biblioteca de ${dataset}.`}
        onRetry={() => void entries.refetch()}
      />
    );
  if (entries.data.length === 0)
    return (
      <p role="alert">
        No hay ninguna entrada subida para «{dataset}». Súbela primero con{" "}
        <code>make bus-subir</code>.
      </p>
    );
  return (
    <fieldset className="space-y-2 rounded-md border p-3">
      <legend className="px-1 font-medium">{dataset}</legend>
      {entries.data.map((entry) => {
        const towns = entry.summary.pueblos;
        return (
          <label key={entry.name} className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name={`dataset-${dataset}`}
              checked={value === entry.name}
              onChange={() => onChange(entry.name)}
            />
            <span>
              <strong>{entry.name}</strong> (v{entry.version})
              {Array.isArray(towns) && (
                <span className="text-muted-foreground">
                  {" "}
                  · {towns.join(", ")}
                </span>
              )}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}

export function OnboardingPage({
  onCreated,
}: {
  onCreated: (slug: string) => void;
}) {
  const [draft, setDraft] = useState<Draft>(restore);
  const [errors, setErrors] = useState<string[]>([]);
  const [validationErrors, setValidationErrors] = useState<
    ComponentProps<typeof Form>["extraErrors"]
  >({});
  const [yaml, setYaml] = useState(() =>
    YAML.stringify(restore().config ?? {}),
  );
  const [yamlError, setYamlError] = useState("");
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [showDiff, setShowDiff] = useState(false);
  const [pending, setPending] = useState(false);
  const client = useQueryClient();
  const update = (patch: Partial<Draft>) =>
    setDraft((old) => ({ ...old, ...patch }));
  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
    } catch {}
  }, [draft]);
  const packs = useQuery({
    queryKey: ["packs"],
    queryFn: () => unwrap(api.GET("/packs")),
  });
  const selectedPack = packs.data?.find((p) => p.name === draft.pack);
  const needsDatasets = (selectedPack?.dataset_names.length ?? 0) > 0;
  const datasetsChosen =
    !needsDatasets ||
    (selectedPack?.dataset_names.every((d) => draft.datasetChoices[d]) ??
      false);
  const available = useQuery({
    queryKey: ["slug-availability", draft.slug],
    queryFn: () =>
      unwrap(
        api.GET("/tenant-slug-availability", {
          params: { query: { slug: draft.slug } },
        }),
      ),
    enabled: draft.step === 2 && validSlug(draft.slug),
    staleTime: 0,
    retry: false,
  });
  const schema = useQuery({
    queryKey: ["pack-schema", draft.pack],
    queryFn: () =>
      unwrap(
        api.GET("/packs/{pack}/schema", {
          params: { path: { pack: draft.pack } },
        }),
      ),
    enabled: !!draft.pack && draft.step >= 3,
  });
  const template = useQuery({
    queryKey: ["pack-template", draft.pack],
    queryFn: () =>
      unwrap(
        api.GET("/packs/{pack}/template", {
          params: { path: { pack: draft.pack } },
        }),
      ),
    enabled: !!draft.pack && draft.step >= 3 && draft.config === null,
  });
  useEffect(() => {
    if (draft.config === null && template.data?.config) {
      setDraft((old) => ({
        ...old,
        config: template.data?.config ?? null,
        template: template.data?.config ?? null,
      }));
      setYaml(YAML.stringify(template.data.config));
    }
  }, [draft.config, template.data]);
  const formSchema = useMemo(
    () => (schema.data ? configSchema(schema.data.document) : null),
    [schema.data],
  );
  const ui = useMemo(
    () => (schema.data ? configUi(schema.data.ui_schema) : {}),
    [schema.data],
  );
  function nextBasic() {
    if (
      !draft.name.trim() ||
      !draft.timezone.trim() ||
      !validSlug(draft.slug) ||
      !available.data?.available ||
      available.isFetching
    )
      return;
    setErrors([]);
    update({ step: needsDatasets ? 3 : 4 });
  }
  function nextConfig() {
    if (!formSchema || !draft.config || yamlError) return;
    try {
      const result = validator.validateFormData(draft.config, formSchema);
      setValidationErrors(result.errorSchema);
      if (result.errors.length) {
        setErrors(
          result.errors.map(
            (e) => e.stack ?? e.message ?? "Configuración no válida",
          ),
        );
        return;
      }
      setErrors([]);
      update({ step: 5 });
    } catch {
      setErrors(["No se pudo validar la configuración."]);
    }
  }
  function changeYaml(value: string) {
    setYaml(value);
    try {
      const parsed: unknown = YAML.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error();
      update({ config: parsed as Record<string, unknown> });
      setYamlError("");
      setValidationErrors({});
    } catch {
      setYamlError("El YAML debe contener una configuración válida.");
    }
  }
  async function create() {
    setPending(true);
    setErrors([]);
    try {
      await unwrap(
        api.POST("/tenants", {
          body: {
            pack: draft.pack,
            slug: draft.slug,
            name: draft.name.trim(),
            timezone: draft.timezone.trim(),
            channel_type: draft.channel,
            config: draft.config ?? {},
            comment: "",
            dataset_choices: needsDatasets ? draft.datasetChoices : undefined,
          },
        }),
      );
      sessionStorage.removeItem(STORAGE_KEY);
      void client.invalidateQueries({ queryKey: ["tenants"] });
      void client.invalidateQueries({ queryKey: ["overview"] });
      onCreated(draft.slug);
    } catch (error) {
      const e = error as ApiError;
      if (e.status === 422) {
        const details = e.details ?? [];
        setErrors(details.length ? details : [e.message]);
        setValidationErrors(
          errorsToSchema(details.map((d) => d.replace(/^config\./, ""))),
        );
        update({ step: 4 });
      } else if (e.status === 409) {
        setErrors([e.message || "El slug ya existe."]);
        update({ step: 2 });
        void client.invalidateQueries({
          queryKey: ["slug-availability", draft.slug],
        });
      } else setErrors([e.message || "No se pudo crear el cliente."]);
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="space-y-5">
      <PageHeader
        title="Nuevo cliente"
        description={`Paso ${draft.step} de ${needsDatasets ? 5 : 4}`}
      />
      {draft.step === 1 && (
        <section className="space-y-4">
          <h2 className="font-semibold">Elige un pack</h2>
          {packs.isPending ? (
            <p>Cargando packs…</p>
          ) : packs.isError ? (
            <ErrorState
              message="No se pudieron cargar los packs."
              onRetry={() => void packs.refetch()}
            />
          ) : packs.data.length === 0 ? (
            <p>No hay packs disponibles.</p>
          ) : (
            <div className="flex flex-wrap gap-3">
              {packs.data.map((pack) => (
                <button
                  key={pack.name}
                  type="button"
                  aria-pressed={draft.pack === pack.name}
                  className="rounded-lg border p-4 aria-pressed:border-primary"
                  onClick={() => {
                    if (pack.name !== draft.pack) {
                      update({
                        pack: pack.name,
                        config: null,
                        template: null,
                        datasetChoices: {},
                      });
                      setYaml("{}");
                    }
                    setErrors([]);
                  }}
                >
                  {pack.name}
                </button>
              ))}
            </div>
          )}
          <Button disabled={!draft.pack} onClick={() => update({ step: 2 })}>
            Siguiente
          </Button>
        </section>
      )}
      {draft.step === 2 && (
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
              <p role="alert">
                Usa hasta 64 letras minúsculas, números y guiones.
              </p>
            )}
            {validSlug(draft.slug) &&
              (available.isFetching ? (
                <p>Comprobando disponibilidad…</p>
              ) : available.isError ? (
                <p role="alert">No se pudo comprobar el slug.</p>
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
            <Input
              id="new-timezone"
              value={draft.timezone}
              onChange={(event) => update({ timezone: event.target.value })}
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
            <Button variant="outline" onClick={() => update({ step: 1 })}>
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
              onClick={nextBasic}
            >
              Siguiente
            </Button>
          </div>
        </section>
      )}
      {draft.step === 3 && needsDatasets && (
        <section className="space-y-4">
          <h2 className="font-semibold">Horarios</h2>
          <p className="text-sm text-muted-foreground">
            Elige, para cada conjunto, la entrada de la biblioteca que usará
            este negocio. El alta no se completa sin elegir uno.
          </p>
          {selectedPack?.dataset_names.map((dataset) => (
            <DatasetChoiceField
              key={dataset}
              pack={draft.pack}
              dataset={dataset}
              value={draft.datasetChoices[dataset] ?? ""}
              onChange={(name) =>
                update({
                  datasetChoices: { ...draft.datasetChoices, [dataset]: name },
                })
              }
            />
          ))}
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => update({ step: 2 })}>
              Anterior
            </Button>
            <Button
              disabled={!datasetsChosen}
              onClick={() => update({ step: 4 })}
            >
              Siguiente
            </Button>
          </div>
        </section>
      )}
      {draft.step === 4 && (
        <section className="space-y-4">
          <h2 className="font-semibold">Configuración</h2>
          {schema.isPending || (draft.config === null && template.isPending) ? (
            <p>Cargando configuración…</p>
          ) : schema.isError || template.isError ? (
            <ErrorState
              message="No se pudo cargar la configuración del pack."
              onRetry={() => {
                void schema.refetch();
                if (draft.config === null) void template.refetch();
              }}
            />
          ) : !formSchema || !draft.config ? (
            <p role="alert">El pack no tiene una plantilla de configuración.</p>
          ) : (
            <>
              <div className="flex gap-2">
                <Button
                  variant={mode === "form" ? "default" : "outline"}
                  disabled={!!yamlError}
                  onClick={() => setMode("form")}
                >
                  Formulario
                </Button>
                <Button
                  variant={mode === "yaml" ? "default" : "outline"}
                  onClick={() => setMode("yaml")}
                >
                  YAML
                </Button>
              </div>
              {mode === "form" ? (
                <Form
                  schema={formSchema}
                  uiSchema={ui}
                  validator={validator}
                  formData={draft.config}
                  extraErrors={validationErrors}
                  onChange={({ formData }) => {
                    if (formData && typeof formData === "object") {
                      update({ config: formData });
                      setYaml(YAML.stringify(formData));
                      setValidationErrors({});
                    }
                  }}
                >
                  <div />
                </Form>
              ) : (
                <>
                  <Label htmlFor="onboarding-yaml">Configuración YAML</Label>
                  <Textarea
                    id="onboarding-yaml"
                    className="min-h-80 font-mono"
                    value={yaml}
                    onChange={(event) => changeYaml(event.target.value)}
                  />
                  {yamlError && <p role="alert">{yamlError}</p>}
                </>
              )}
              <Button variant="outline" onClick={() => setShowDiff(!showDiff)}>
                Ver cambios
              </Button>
              {showDiff && (
                <JsonDiff before={draft.template} after={draft.config} />
              )}
            </>
          )}
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => update({ step: needsDatasets ? 3 : 2 })}
            >
              Anterior
            </Button>
            <Button
              disabled={!formSchema || !draft.config || !!yamlError}
              onClick={nextConfig}
            >
              Siguiente
            </Button>
          </div>
        </section>
      )}
      {draft.step === 5 && (
        <section className="space-y-4">
          <h2 className="font-semibold">Revisión</h2>
          <p>
            Pack: {draft.pack} · Nombre: {draft.name} · Slug: {draft.slug}
          </p>
          <p>
            Zona horaria: {draft.timezone} · Canal: {draft.channel}
          </p>
          {needsDatasets && (
            <p>
              Horarios:{" "}
              {Object.entries(draft.datasetChoices)
                .map(([dataset, name]) => `${dataset} → ${name}`)
                .join(", ")}
            </p>
          )}
          <pre className="overflow-auto rounded-md border p-3">
            {YAML.stringify(draft.config)}
          </pre>
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={pending}
              onClick={() => update({ step: 4 })}
            >
              Anterior
            </Button>
            <Button disabled={pending} onClick={() => void create()}>
              Crear cliente
            </Button>
          </div>
        </section>
      )}
      {errors.length > 0 && (
        <ul role="alert">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
