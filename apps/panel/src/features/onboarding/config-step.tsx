import Form from "@rjsf/shadcn";
import type { ComponentProps } from "react";
import { ErrorState } from "@/components/error-state";
import { JsonDiff } from "@/components/json-diff";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { validator } from "@/lib/form-validator";
import type { Draft } from "./draft";

export function configSchema(
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
export function configUi(
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

export function ConfigStep({
  draft,
  formSchema,
  ui,
  loading,
  failed,
  onRetry,
  mode,
  onModeChange,
  yaml,
  yamlError,
  onYamlChange,
  validationErrors,
  onFormChange,
  showDiff,
  onToggleDiff,
  onBack,
  onNext,
}: {
  draft: Draft;
  formSchema: Record<string, unknown> | null;
  ui: ComponentProps<typeof Form>["uiSchema"];
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
  mode: "form" | "yaml";
  onModeChange: (mode: "form" | "yaml") => void;
  yaml: string;
  yamlError: string;
  onYamlChange: (value: string) => void;
  validationErrors: ComponentProps<typeof Form>["extraErrors"];
  onFormChange: (formData: Record<string, unknown>) => void;
  showDiff: boolean;
  onToggleDiff: () => void;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <section className="space-y-4">
      <h2 className="font-semibold">Configuración</h2>
      {loading ? (
        <p>Cargando configuración…</p>
      ) : failed ? (
        <ErrorState
          message="No se pudo cargar la configuración del pack."
          onRetry={onRetry}
        />
      ) : !formSchema || !draft.config ? (
        <p role="alert" className="text-sm text-destructive">
          El pack no tiene una plantilla de configuración.
        </p>
      ) : (
        <>
          <div className="flex gap-2">
            <Button
              variant={mode === "form" ? "default" : "outline"}
              disabled={!!yamlError}
              onClick={() => onModeChange("form")}
            >
              Formulario
            </Button>
            <Button
              variant={mode === "yaml" ? "default" : "outline"}
              onClick={() => onModeChange("yaml")}
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
                if (formData && typeof formData === "object")
                  onFormChange(formData);
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
                onChange={(event) => onYamlChange(event.target.value)}
              />
              {yamlError && (
                <p role="alert" className="text-sm text-destructive">
                  {yamlError}
                </p>
              )}
            </>
          )}
          <Button variant="outline" onClick={onToggleDiff}>
            Ver cambios
          </Button>
          {showDiff && (
            <JsonDiff before={draft.template} after={draft.config} />
          )}
        </>
      )}
      <div className="flex gap-2">
        <Button variant="outline" onClick={onBack}>
          Anterior
        </Button>
        <Button
          disabled={!formSchema || !draft.config || !!yamlError}
          onClick={onNext}
        >
          Siguiente
        </Button>
      </div>
    </section>
  );
}
