import type Form from "@rjsf/shadcn";
import { useQuery } from "@tanstack/react-query";
import { type ComponentProps, useEffect, useMemo, useState } from "react";
import YAML from "yaml";
import { api, unwrap } from "@/api/client";
import { PageHeader } from "@/components/page-header";
import { validator } from "@/lib/form-validator";
import { packSchemaQueryOptions, packsQueryOptions, qk } from "@/lib/queries";
import { BasicsStep } from "./basics-step";
import { ConfigStep, configSchema, configUi } from "./config-step";
import { DatasetsStep } from "./datasets-step";
import { validSlug } from "./draft";
import { PackStep } from "./pack-step";
import { ReviewStep } from "./review-step";
import { useCreateTenant } from "./use-create-tenant";
import { useOnboardingDraft } from "./use-onboarding-draft";

export function OnboardingPage({
  onCreated,
}: {
  onCreated: (slug: string) => void;
}) {
  const { draft, setDraft, update, yaml, setYaml } = useOnboardingDraft();
  const [errors, setErrors] = useState<string[]>([]);
  const [validationErrors, setValidationErrors] = useState<
    ComponentProps<typeof Form>["extraErrors"]
  >({});
  const [yamlError, setYamlError] = useState("");
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [showDiff, setShowDiff] = useState(false);
  const packs = useQuery(packsQueryOptions());
  const selectedPack = packs.data?.find((p) => p.name === draft.pack);
  const datasetNames = selectedPack?.dataset_names ?? [];
  const needsDatasets = datasetNames.length > 0;
  const available = useQuery({
    queryKey: qk.slugAvailability(draft.slug),
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
    ...packSchemaQueryOptions(draft.pack),
    enabled: !!draft.pack && draft.step >= 3,
  });
  const template = useQuery({
    queryKey: qk.packTemplate(draft.pack),
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
  }, [draft.config, template.data, setDraft, setYaml]);
  const formSchema = useMemo(
    () => (schema.data ? configSchema(schema.data.document) : null),
    [schema.data],
  );
  const ui = useMemo(
    () => (schema.data ? configUi(schema.data.ui_schema) : {}),
    [schema.data],
  );
  const { create, pending } = useCreateTenant({
    draft,
    needsDatasets,
    update,
    setErrors,
    setValidationErrors,
    onCreated,
  });
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
  return (
    <div className="space-y-5">
      <PageHeader
        title="Nuevo cliente"
        description={`Paso ${draft.step} de ${needsDatasets ? 5 : 4}`}
      />
      {draft.step === 1 && (
        <PackStep
          pack={draft.pack}
          onSelect={(name) => {
            if (name !== draft.pack) {
              update({
                pack: name,
                config: null,
                template: null,
                datasetChoices: {},
              });
              setYaml("{}");
            }
            setErrors([]);
          }}
          onNext={() => update({ step: 2 })}
        />
      )}
      {draft.step === 2 && (
        <BasicsStep
          draft={draft}
          update={update}
          available={available}
          onBack={() => update({ step: 1 })}
          onNext={nextBasic}
        />
      )}
      {draft.step === 3 && needsDatasets && (
        <DatasetsStep
          draft={draft}
          datasetNames={datasetNames}
          update={update}
          onBack={() => update({ step: 2 })}
          onNext={() => update({ step: 4 })}
        />
      )}
      {draft.step === 4 && (
        <ConfigStep
          draft={draft}
          formSchema={formSchema}
          ui={ui}
          loading={
            schema.isPending || (draft.config === null && template.isPending)
          }
          failed={schema.isError || template.isError}
          onRetry={() => {
            void schema.refetch();
            if (draft.config === null) void template.refetch();
          }}
          mode={mode}
          onModeChange={setMode}
          yaml={yaml}
          yamlError={yamlError}
          onYamlChange={changeYaml}
          validationErrors={validationErrors}
          onFormChange={(formData) => {
            update({ config: formData });
            setYaml(YAML.stringify(formData));
            setValidationErrors({});
          }}
          showDiff={showDiff}
          onToggleDiff={() => setShowDiff(!showDiff)}
          onBack={() => update({ step: needsDatasets ? 3 : 2 })}
          onNext={nextConfig}
        />
      )}
      {draft.step === 5 && (
        <ReviewStep
          draft={draft}
          showDatasets={needsDatasets}
          pending={pending}
          onBack={() => update({ step: 4 })}
          onCreate={() => void create()}
        />
      )}
      {errors.length > 0 && (
        <ul role="alert" className="text-sm text-destructive">
          {errors.map((error, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: the same message can repeat
            <li key={`${index}:${error}`}>{error}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
