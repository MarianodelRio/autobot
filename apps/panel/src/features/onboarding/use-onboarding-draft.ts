import { useEffect, useState } from "react";
import YAML from "yaml";
import { type Draft, restoreDraft, STORAGE_KEY } from "./draft";

/** The wizard's draft, persisted in sessionStorage so a reload keeps it, plus the
 * YAML text of its config (edited in the YAML mode of the config step). */
export function useOnboardingDraft() {
  const [draft, setDraft] = useState<Draft>(restoreDraft);
  const [yaml, setYaml] = useState(() =>
    YAML.stringify(restoreDraft().config ?? {}),
  );
  const update = (patch: Partial<Draft>) =>
    setDraft((old) => ({ ...old, ...patch }));
  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
    } catch {}
  }, [draft]);
  return { draft, setDraft, update, yaml, setYaml };
}

export function clearStoredDraft() {
  sessionStorage.removeItem(STORAGE_KEY);
}
