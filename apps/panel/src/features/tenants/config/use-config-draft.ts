import { useEffect, useState } from "react";
import YAML from "yaml";
import type { components } from "@/api/schema";

type Detail = components["schemas"]["TenantDetail"];
type Document = Record<string, unknown>;

/** The editing state of a tenant's config: the saved baseline, the draft being
 * edited (as a form or as YAML), the server errors and the optimistic-lock
 * version. The editor component only wires it to the form and the requests. */
export function useConfigDraft(
  detail: Detail,
  onDirtyChange: (dirty: boolean) => void,
) {
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
  const dirty =
    yamlError !== "" || JSON.stringify(draft) !== JSON.stringify(baseline);
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
    setDraft(detail.document);
    setVersion(detail.version);
    setYaml(YAML.stringify(detail.document));
  }, [detail, dirty, version]);

  function changeForm(formData: Document) {
    setDraft(formData);
    setYaml(YAML.stringify(formData));
    setErrors([]);
  }
  function changeYaml(value: string) {
    setYaml(value);
    try {
      const parsed: unknown = YAML.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
        throw new Error();
      setDraft(parsed as Document);
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
  /** The server stored `sent` as `newVersion`. */
  function saved(sent: Document, newVersion: number) {
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
    setDraft(current.document);
    setVersion(current.version);
    setYaml(YAML.stringify(current.document));
    setYamlError("");
    setConflict(false);
    setLatest(null);
    setErrors([]);
  }

  return {
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
  };
}
