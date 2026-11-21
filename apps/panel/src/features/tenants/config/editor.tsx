// The installed shadcn theme renders with the panel's existing components and styles.
import Form from "@rjsf/shadcn";
import DefaultObjectTemplate from "@rjsf/shadcn/lib/ObjectFieldTemplate/ObjectFieldTemplate.js";
import { useQuery } from "@tanstack/react-query";
import { type ComponentProps, type ReactNode, useEffect, useMemo } from "react";
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
import { validator } from "@/lib/form-validator";
import { packSchemaQueryOptions, tenantChanged } from "@/lib/queries";
import { useApiMutation } from "@/lib/use-api-mutation";
import { CalendarSection } from "./calendar-section";
import { ChannelSection } from "./channel-section";
import { DatasetSection } from "./dataset-section";
import { HistorySection } from "./history-section";
import { OpeningHoursField } from "./opening-hours-field";
import { OwnerSection } from "./owner-section";
import { ServicesField } from "./services-field";
import { TimezoneWidget } from "./timezone-widget";
import { useConfigDraft } from "./use-config-draft";

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
  if (value.fields && typeof value.fields === "object")
    for (const [field, name] of Object.entries(value.fields))
      assign(field, "ui:field", name);
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
  const {
    baseline,
    version,
    draft,
    yaml,
    yamlError,
    mode,
    setMode,
    comment,
    setComment,
    showDiff,
    setShowDiff,
    errors,
    setErrors,
    conflict,
    setConflict,
    latest,
    setLatest,
    dirty,
    changeForm,
    changeYaml,
    discard,
    saved,
    replaceWith,
  } = useConfigDraft(detail, onDirtyChange);
  const schema = useQuery(packSchemaQueryOptions(detail.pack));
  useEffect(() => {
    if (!initialSection) return;
    document
      .getElementById(`section-${initialSection}`)
      ?.scrollIntoView({ block: "start" });
  }, [initialSection]);
  // "demo" only makes sense for the platform's own demo tenants; hiding it
  // keeps a real client's form from offering to turn it into one.
  const isDemo = Boolean(detail.document.demo);
  const ui = useMemo(
    () =>
      schema.data
        ? uiSchema(
            isDemo
              ? schema.data.ui_schema
              : {
                  ...schema.data.ui_schema,
                  hidden: [
                    ...((schema.data.ui_schema.hidden as string[]) ?? []),
                    "demo",
                  ],
                },
          )
        : {},
    [schema.data, isDemo],
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
        ...(detail.pack === "salon"
          ? { config: <CalendarSection detail={detail} /> }
          : {}),
        ...(detail.pack === "bus"
          ? { config: <DatasetSection detail={detail} dataset="timetable" /> }
          : {}),
      },
    }),
    [schema.data, detail],
  );
  const save = useApiMutation({
    // The document sent is passed in, so on success the baseline is exactly what the
    // server stored, even if the person kept typing while the request was in flight.
    fn: (sent: Record<string, unknown>) =>
      unwrap(
        api.PUT("/tenants/{slug}/document", {
          params: { path: { slug: detail.slug } },
          body: {
            document: sent,
            base_version: version ?? 0,
            comment: comment.trim(),
          },
        }),
      ),
    success: (result) =>
      `Guardado: versión ${result.version}; se aplica en unos segundos`,
    invalidate: tenantChanged(detail.slug),
    onSuccess: (result, sent) => saved(sent, result.version),
    onError: (caught) => {
      const error = caught as ApiError;
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
      if (replace) replaceWith(current);
      else setLatest(current);
    } catch {
      setErrors(["No se pudo cargar la versión más reciente."]);
    }
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
        <div className="flex items-center gap-2">
          <HistorySection
            slug={detail.slug}
            current={draft}
            dirty={dirty}
            onRolledBack={() => {
              discard();
              void loadLatest(true);
            }}
          />
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
      </div>
      {mode === "form" ? (
        <Form
          schema={resolvedSchema}
          uiSchema={ui}
          validator={validator}
          formData={draft}
          extraErrors={errorsToSchema(errors)}
          templates={{ ObjectFieldTemplate: GroupedObjectTemplate }}
          widgets={{ timezone: TimezoneWidget }}
          fields={{ OpeningHours: OpeningHoursField, Services: ServicesField }}
          formContext={formContext}
          onChange={({ formData }) => {
            if (formData && typeof formData === "object") changeForm(formData);
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
          {yamlError && (
            <p role="alert" className="text-sm text-destructive">
              {yamlError}
            </p>
          )}
        </>
      )}
      {errors.length > 0 && (
        <ul role="alert" className="text-sm text-destructive">
          {errors.map((error, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: the same message can repeat
            <li key={`${index}:${error}`}>{error}</li>
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
              onClick={() => save.mutate(draft)}
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
