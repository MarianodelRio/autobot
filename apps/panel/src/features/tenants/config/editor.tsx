// The installed shadcn theme renders with the panel's existing components and styles.
import Form from "@rjsf/shadcn";
import DefaultObjectTemplate from "@rjsf/shadcn/lib/ObjectFieldTemplate/ObjectFieldTemplate.js";
import validator from "@rjsf/validator-ajv8";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ComponentProps,
  type ReactNode,
  useEffect,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";
import YAML from "yaml";
import { type ApiError, api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { ErrorState } from "@/components/error-state";
import { JsonDiff } from "@/components/json-diff";
import { type Status, StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { ChannelSection } from "./channel-section";
import { OwnerSection } from "./owner-section";

type Detail = components["schemas"]["TenantDetail"];
type ErrorSchema = NonNullable<ComponentProps<typeof Form>["extraErrors"]>;

interface FormContext {
  groups?: { key: string; label: string; fields: string[] }[];
  groupExtras?: Record<string, ReactNode>;
  collapsed?: string[];
}

const GroupedObjectTemplate = (
  props: Parameters<typeof DefaultObjectTemplate>[0],
) => {
  const { groups, groupExtras, collapsed } = (props.registry.formContext ??
    {}) as FormContext;
  const path = props.fieldPathId.path.join(".");
  if (collapsed?.includes(path)) {
    return (
      <details className="rounded-md border p-3">
        <summary className="cursor-pointer font-medium">{props.title}</summary>
        <div className="mt-3 space-y-3">
          {props.properties.map((field) => (
            <div key={field.name} className={field.hidden ? "hidden" : ""}>
              {field.content}
            </div>
          ))}
        </div>
      </details>
    );
  }
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
      {groups.map((group) => {
        const fields = props.properties.filter((property) =>
          group.fields.includes(property.name),
        );
        for (const field of fields) used.add(field.name);
        const extra = groupExtras?.[group.key];
        if (fields.length === 0 && !extra) return null;
        return (
          <Card key={group.key} id={`section-${group.key}`}>
            <CardHeader>
              <CardTitle>{group.label}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {fields.map((field) => (
                <div key={field.name} className={field.hidden ? "hidden" : ""}>
                  {field.content}
                </div>
              ))}
              {extra}
            </CardContent>
          </Card>
        );
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
  if (Array.isArray(value.hidden))
    for (const field of value.hidden)
      if (typeof field === "string") assign(field, "ui:widget", "hidden");
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

/** rjsf shows a type selector for the `channel` discriminated union by default;
 * since the type is fixed and read-only for an existing tenant, this resolves it
 * to the one real branch so the form never shows a selector. Generic: it works
 * off the schema's own `oneOf`/`discriminator`, not any pack-specific knowledge. */
function resolveChannelSchema(
  document: Record<string, unknown>,
  channelType: string | null,
): Record<string, unknown> {
  const properties = document.properties as Record<string, unknown> | undefined;
  const channelProp = properties?.channel as
    | Record<string, unknown>
    | undefined;
  if (!channelProp) return document;
  if (channelType === null) {
    const { channel, ...rest } = properties ?? {};
    return { ...document, properties: rest };
  }
  const defs = (document.$defs ?? {}) as Record<
    string,
    Record<string, unknown>
  >;
  const branches: unknown[] = Array.isArray(channelProp.oneOf)
    ? channelProp.oneOf
    : Array.isArray(channelProp.anyOf)
      ? channelProp.anyOf.flatMap((b) =>
          typeof b === "object" &&
          b &&
          Array.isArray((b as { oneOf?: unknown[] }).oneOf)
            ? ((b as { oneOf: unknown[] }).oneOf as unknown[])
            : [],
        )
      : [];
  const resolve = (branch: unknown): Record<string, unknown> | undefined => {
    if (typeof branch !== "object" || branch === null) return undefined;
    const ref = (branch as { $ref?: string }).$ref;
    return ref
      ? defs[ref.replace("#/$defs/", "")]
      : (branch as Record<string, unknown>);
  };
  const match = branches.map(resolve).find((s) => {
    const type = s?.properties as Record<string, unknown> | undefined;
    const field = type?.type as Record<string, unknown> | undefined;
    return field?.const === channelType;
  });
  if (!match) return document;
  return {
    ...document,
    properties: { ...properties, channel: match },
  };
}

export function ConfigEditor({
  detail,
  onDirtyChange,
  initialSection,
}: {
  detail: Detail;
  onDirtyChange: (dirty: boolean) => void;
  initialSection?: string;
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
  useEffect(() => {
    if (!initialSection) return;
    document
      .getElementById(`section-${initialSection}`)
      ?.scrollIntoView({ block: "start" });
  }, [initialSection]);
  const ui = useMemo(
    () => (schema.data ? uiSchema(schema.data.ui_schema) : {}),
    [schema.data],
  );
  const resolvedSchema = useMemo(
    () =>
      schema.data
        ? resolveChannelSchema(schema.data.document, detail.channel_type)
        : undefined,
    [schema.data, detail.channel_type],
  );
  const formContext = useMemo(
    (): FormContext => ({
      groups: schema.data?.ui_schema.groups as FormContext["groups"],
      collapsed: schema.data?.ui_schema.collapsed as FormContext["collapsed"],
      groupExtras: {
        channel: <ChannelSection detail={detail} />,
        people: <OwnerSection detail={detail} />,
      },
    }),
    [schema.data, detail],
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
  function discard() {
    setDraft(baseline);
    setYaml(YAML.stringify(baseline));
    setYamlError("");
    setComment("");
    setErrors([]);
  }
  if (schema.isPending) return <p>Cargando formulario…</p>;
  if (schema.isError || !resolvedSchema)
    return (
      <ErrorState
        message="No se pudo cargar el esquema."
        onRetry={() => void schema.refetch()}
      />
    );
  return (
    <div className="space-y-4 pb-20">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>Negocio</span>
          <span>·</span>
          <code>{detail.slug}</code>
          <span>·</span>
          <span>{detail.pack}</span>
          <span>·</span>
          <StatusBadge status={detail.status as Status} />
          <span>·</span>
          <code className="text-xs">{String(detail.document.id ?? "")}</code>
        </div>
        {mode === "form" ? (
          <Button variant="outline" size="sm" onClick={() => setMode("yaml")}>
            Editar YAML
          </Button>
        ) : (
          <Button
            variant="outline"
            size="sm"
            disabled={!!yamlError}
            onClick={() => setMode("form")}
          >
            Volver al formulario
          </Button>
        )}
      </div>
      {mode === "form" ? (
        <Form
          schema={resolvedSchema}
          uiSchema={ui}
          validator={validator}
          formData={draft}
          extraErrors={errorsToSchema(errors)}
          templates={{ ObjectFieldTemplate: GroupedObjectTemplate }}
          formContext={formContext}
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
      {dirty && (
        <div className="fixed inset-x-0 bottom-0 z-10 flex flex-wrap items-center gap-3 border-t bg-card p-3 shadow-lg">
          <span className="text-sm">Cambios sin guardar</span>
          <Button variant="outline" size="sm" onClick={() => setShowDiff(true)}>
            Ver cambios
          </Button>
          <Input
            aria-label="Comentario (opcional)"
            placeholder="Comentario (opcional)"
            className="max-w-xs"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
          />
          <div className="ml-auto flex gap-2">
            <Button variant="outline" onClick={discard}>
              Descartar
            </Button>
            <Button
              disabled={!!yamlError || save.isPending || version === null}
              onClick={() => save.mutate()}
            >
              Guardar
            </Button>
          </div>
        </div>
      )}
      <Sheet open={showDiff} onOpenChange={setShowDiff}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>Cambios sin guardar</SheetTitle>
          </SheetHeader>
          <div className="px-4">
            <JsonDiff before={baseline} after={draft} />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
