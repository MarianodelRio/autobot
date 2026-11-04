// The installed shadcn theme renders with the panel's existing components and styles.
import Form from "@rjsf/shadcn";
import DefaultObjectTemplate from "@rjsf/shadcn/lib/ObjectFieldTemplate/ObjectFieldTemplate.js";
import validator from "@rjsf/validator-ajv8";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ComponentProps, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import YAML from "yaml";
import { type ApiError, api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/error-state";
import { JsonDiff } from "@/components/json-diff";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

type Detail = components["schemas"]["TenantDetail"];
type ErrorSchema = NonNullable<ComponentProps<typeof Form>["extraErrors"]>;

const GroupedObjectTemplate = (
  props: Parameters<typeof DefaultObjectTemplate>[0],
) => {
  const groups = props.registry.formContext.groups;
  if (
    props.fieldPathId.$id !== "root" ||
    !Array.isArray(groups) ||
    !DefaultObjectTemplate
  ) {
    return <DefaultObjectTemplate {...props} />;
  }
  const used = new Set<string>();
  return (
    <div className="space-y-6">
      {groups.map((group: { key: string; label: string; fields: string[] }) => {
        const fields = props.properties.filter((property) =>
          group.fields.includes(property.name),
        );
        for (const field of fields) used.add(field.name);
        return fields.length ? (
          <section key={group.key} className="space-y-3">
            <h2 className="text-lg font-semibold">{group.label}</h2>
            {fields.map((field) => (
              <div key={field.name} className={field.hidden ? "hidden" : ""}>
                {field.content}
              </div>
            ))}
          </section>
        ) : null;
      })}
      {props.properties
        .filter((property) => !used.has(property.name))
        .map((field) => (
          <div key={field.name} className={field.hidden ? "hidden" : ""}>
            {field.content}
          </div>
        ))}
    </div>
  );
};

type Node = { __errors?: string[]; [key: string]: Node | string[] | undefined };
export function errorsToSchema(details: string[]): ErrorSchema {
  const root: Node = {};
  for (const detail of details) {
    const split = detail.indexOf(":");
    if (split < 0) continue;
    let path = detail
      .slice(0, split)
      .trim()
      .replace(/^document\./, "");
    const message = detail.slice(split + 1).trim();
    if (path === "document") path = "";
    let node = root;
    for (const part of path.split(".").filter(Boolean)) {
      const existing = node[part];
      if (!existing || Array.isArray(existing)) node[part] = {};
      node = node[part] as Node;
    }
    if (!node.__errors) node.__errors = [];
    node.__errors.push(message);
  }
  return root as ErrorSchema;
}
function uiSchema(
  value: Record<string, unknown>,
): ComponentProps<typeof Form>["uiSchema"] {
  const result: Record<string, unknown> = {};
  const assign = (path: string, key: string, v: unknown) => {
    let node = result;
    for (const part of path.split(".")) {
      const prev = node[part];
      if (!prev || typeof prev !== "object" || Array.isArray(prev))
        node[part] = {};
      node = node[part] as Record<string, unknown>;
    }
    node[key] = v;
  };
  if (Array.isArray(value.read_only))
    for (const field of value.read_only)
      if (typeof field === "string") assign(field, "ui:readonly", true);
  if (value.widgets && typeof value.widgets === "object")
    for (const [field, widget] of Object.entries(value.widgets))
      assign(field, "ui:widget", widget);
  if (Array.isArray(value.groups)) {
    const order = value.groups.flatMap((group: unknown) =>
      typeof group === "object" &&
      group !== null &&
      "fields" in group &&
      Array.isArray(group.fields)
        ? group.fields
        : [],
    );
    result["ui:order"] = [...order, "*"];
  }
  return result;
}
export function ConfigEditor({
  detail,
  onDirtyChange,
}: {
  detail: Detail;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const client = useQueryClient();
  const [baseline, setBaseline] = useState(detail.document);
  const [version, setVersion] = useState(detail.version);
  const [draft, setDraft] = useState(detail.document);
  const [yaml, setYaml] = useState(() => YAML.stringify(detail.document));
  const [yamlError, setYamlError] = useState("");
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [comment, setComment] = useState("");
  const [showDiff, setShowDiff] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [conflict, setConflict] = useState(false);
  const [latest, setLatest] = useState<Detail | null>(null);
  const schema = useQuery({
    queryKey: ["pack-schema", detail.pack],
    queryFn: () =>
      unwrap(
        api.GET("/packs/{pack}/schema", {
          params: { path: { pack: detail.pack } },
        }),
      ),
  });
  const dirty =
    yamlError !== "" || JSON.stringify(draft) !== JSON.stringify(baseline);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  const ui = useMemo(
    () => (schema.data ? uiSchema(schema.data.ui_schema) : {}),
    [schema.data],
  );
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/tenants/{slug}/document", {
          params: { path: { slug: detail.slug } },
          body: {
            document: draft,
            base_version: version ?? 0,
            comment: comment.trim(),
          },
        }),
      ),
    onSuccess: (result) => {
      setBaseline(draft);
      setVersion(result.version);
      setComment("");
      setErrors([]);
      setConflict(false);
      setLatest(null);
      toast.success(
        `Guardado: versión ${result.version}; se aplica en unos segundos`,
      );
      void client.invalidateQueries({ queryKey: ["tenant", detail.slug] });
      void client.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (error: ApiError) => {
      if (error.status === 422) setErrors(error.details);
      else if (error.status === 409) setConflict(true);
      else setErrors([error.message || "No se pudo guardar."]);
    },
  });
  async function loadLatest(replace: boolean) {
    try {
      const current = await unwrap(
        api.GET("/tenants/{slug}", { params: { path: { slug: detail.slug } } }),
      );
      if (replace) {
        setBaseline(current.document);
        setDraft(current.document);
        setVersion(current.version);
        setYaml(YAML.stringify(current.document));
        setYamlError("");
        setConflict(false);
        setLatest(null);
        setErrors([]);
      } else setLatest(current);
    } catch {
      setErrors(["No se pudo cargar la versión más reciente."]);
    }
  }
  function changeYaml(value: string) {
    setYaml(value);
    try {
      const parsed: unknown = YAML.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error();
      setDraft(parsed as Record<string, unknown>);
      setYamlError("");
    } catch {
      setYamlError("El YAML debe contener un documento válido.");
    }
  }
  if (schema.isPending) return <p>Cargando formulario…</p>;
  if (schema.isError)
    return (
      <ErrorState
        message="No se pudo cargar el esquema."
        onRetry={() => void schema.refetch()}
      />
    );
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Button
          variant={mode === "form" ? "default" : "outline"}
          onClick={() => setMode("form")}
          disabled={!!yamlError}
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
          schema={schema.data.document}
          uiSchema={ui}
          validator={validator}
          formData={draft}
          extraErrors={errorsToSchema(errors)}
          templates={{ ObjectFieldTemplate: GroupedObjectTemplate }}
          formContext={{ groups: schema.data.ui_schema.groups }}
          onChange={({ formData }) => {
            if (formData && typeof formData === "object") {
              setDraft(formData);
              setYaml(YAML.stringify(formData));
              setErrors([]);
            }
          }}
        >
          <div />
        </Form>
      ) : (
        <>
          <Label htmlFor="config-yaml">Documento YAML</Label>
          <Textarea
            id="config-yaml"
            className="min-h-96 font-mono"
            value={yaml}
            onChange={(event) => changeYaml(event.target.value)}
          />
          {yamlError && <p role="alert">{yamlError}</p>}
        </>
      )}
      {errors.length > 0 && (
        <ul role="alert">
          {errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      {conflict && (
        <div role="alert" className="space-y-2">
          <p>Hay una versión más reciente.</p>
          <Button variant="outline" onClick={() => void loadLatest(true)}>
            Recargar
          </Button>{" "}
          <Button variant="outline" onClick={() => void loadLatest(false)}>
            Ver diferencias
          </Button>
          {latest && <JsonDiff before={latest.document} after={draft} />}
        </div>
      )}
      <div>
        <Button variant="outline" onClick={() => setShowDiff(!showDiff)}>
          Ver cambios
        </Button>
        {showDiff && <JsonDiff before={baseline} after={draft} />}
      </div>
      <div>
        <Label htmlFor="config-comment">Comentario obligatorio</Label>
        <Input
          id="config-comment"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />
      </div>
      <Button
        disabled={
          !dirty ||
          !!yamlError ||
          !comment.trim() ||
          save.isPending ||
          version === null
        }
        onClick={() => save.mutate()}
      >
        Guardar
      </Button>
    </div>
  );
}
