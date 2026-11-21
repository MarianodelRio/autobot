import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { type ApiError, api, unwrap } from "@/api/client";
import { errorsToSchema } from "@/features/tenants/config/editor";
import { invalidateKeys, qk } from "@/lib/queries";
import { type Draft, stepForErrors } from "./draft";
import { clearStoredDraft } from "./use-onboarding-draft";

/** Sends the draft as a new tenant. A ref, not `pending` state, guards against a
 * double click: two clicks in the same tick both see `pending` false. */
export function useCreateTenant({
  draft,
  needsDatasets,
  update,
  setErrors,
  setValidationErrors,
  onCreated,
}: {
  draft: Draft;
  needsDatasets: boolean;
  update: (patch: Partial<Draft>) => void;
  setErrors: (errors: string[]) => void;
  setValidationErrors: (errors: ReturnType<typeof errorsToSchema>) => void;
  onCreated: (slug: string) => void;
}) {
  const client = useQueryClient();
  const [pending, setPending] = useState(false);
  const creating = useRef(false);
  async function create() {
    if (creating.current) return;
    creating.current = true;
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
      clearStoredDraft();
      invalidateKeys(client, [qk.tenants(), qk.overview()]);
      onCreated(draft.slug);
    } catch (error) {
      const e = error as ApiError;
      if (e.status === 422) {
        const details = e.details ?? [];
        setErrors(details.length ? details : [e.message]);
        setValidationErrors(
          errorsToSchema(details.map((d) => d.replace(/^config\./, ""))),
        );
        update({ step: stepForErrors(details) });
      } else if (e.status === 409) {
        setErrors([e.message || "El slug ya existe."]);
        update({ step: 2 });
        invalidateKeys(client, [qk.slugAvailability(draft.slug)]);
      } else setErrors([e.message || "No se pudo crear el cliente."]);
    } finally {
      creating.current = false;
      setPending(false);
    }
  }
  return { create, pending };
}
