import { useEffect, useMemo, useState } from "react";
import YAML from "yaml";
import type { components } from "@/api/schema";
import {
  type Json,
  mergePaths,
  sameValue,
  withoutUntouchedDefaults,
} from "@/lib/form-draft";

type Detail = components["schemas"]["TenantDetail"];

/** The editing state of a tenant's config: the saved baseline, the draft being
 * edited (as a form or as YAML), the server errors and the optimistic-lock
 * version. The editor component only wires it to the form and the requests.
 *
 * `normalize` applies the schema's defaults to a stored document. rjsf fills them in
 * as soon as a form mounts, so the draft starts already normalized and «dirty» means
 * "differs from the normalized baseline": opening the tab never counts as a change.
 * `toSave` leaves the untouched defaults out again. */
export function useConfigDraft(
  detail: Detail,
  onDirtyChange: (dirty: boolean) => void,
  normalize: (document: Json) => Json,
) {
  const [baseline, setBaseline] = useState<Json>(detail.document);
  const [version, setVersion] = useState(detail.version);
  const normalized = useMemo(() => normalize(baseline), [normalize, baseline]);
  const [draft, setDraft] = useState<Json>(() => normalize(detail.document));
  const [yaml, setYaml] = useState(() =>
    YAML.stringify(normalize(detail.document)),
  );
  const [yamlError, setYamlError] = useState("");
  const [mode, setMode] = useState<"form" | "yaml">("form");
  const [comment, setComment] = useState("");
  const [showDiff, setShowDiff] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const [conflict, setConflict] = useState(false);
  const [latest, setLatest] = useState<Detail | null>(null);
  const dirty = yamlError !== "" || !sameValue(draft, normalized);
  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);
  // `detail` is refetched elsewhere too (e.g. Activar/Pausar): without
  // unsaved changes, follow its version so the next save never carries a stale
  // `base_version` and 409s. Only ever move *forward*: `detail` is a prop that can
  // itself be a render behind a version this component already moved to on its own
  // (a save, or "Recargar" after a conflict).
  useEffect(() => {
    if (dirty || detail.version === null || detail.version <= (version ?? -1))
      return;
    setBaseline(detail.document);
    setDraft(normalize(detail.document));
    setVersion(detail.version);
    setYaml(YAML.stringify(normalize(detail.document)));
  }, [detail, dirty, version, normalize]);

  /** One section's form changed: take its `paths` from `part`. Functional, since
   * several section forms can report in the same render (each on mount). */
  function changeFields(part: Json, paths: string[]) {
    setDraft((previous) => {
      const next = mergePaths(previous, part, paths);
      return sameValue(next, previous) ? previous : next;
    });
  }
  function enterYaml() {
    setYaml(YAML.stringify(draft));
    setYamlError("");
    setMode("yaml");
  }
  function changeYaml(value: string) {
    setYaml(value);
    try {
      const parsed: unknown = YAML.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error();
      setDraft(parsed as Json);
      setYamlError("");
    } catch {
      setYamlError("El YAML debe contener un documento válido.");
    }
  }
  function discard() {
    setDraft(normalized);
    setYaml(YAML.stringify(normalized));
    setYamlError("");
    setComment("");
    setErrors([]);
  }
  /** The document to send: the draft without the defaults nobody touched. */
  function toSave(): Json {
    return withoutUntouchedDefaults(draft, normalized, baseline) as Json;
  }
  /** The server stored `sent` as `newVersion`. */
  function saved(sent: Json, newVersion: number) {
    setBaseline(sent);
    setVersion(newVersion);
    setComment("");
    setErrors([]);
    setConflict(false);
    setLatest(null);
  }
  /** Drop the draft for the server's current version (after a conflict). */
  function replaceWith(current: Detail) {
    setBaseline(current.document);
    setDraft(normalize(current.document));
    setVersion(current.version);
    setYaml(YAML.stringify(normalize(current.document)));
    setYamlError("");
    setConflict(false);
    setLatest(null);
    setErrors([]);
  }

  return {
    baseline,
    normalized,
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
    changeFields,
    enterYaml,
    changeYaml,
    discard,
    toSave,
    saved,
    replaceWith,
  };
}
