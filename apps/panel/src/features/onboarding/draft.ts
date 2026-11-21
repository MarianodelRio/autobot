export const STORAGE_KEY = "autobot.onboarding";

export type Draft = {
  step: number;
  pack: string;
  name: string;
  slug: string;
  slugEdited: boolean;
  timezone: string;
  channel: "whatsapp" | "telegram";
  config: Record<string, unknown> | null;
  template: Record<string, unknown> | null;
  // {dataset name -> chosen library entry name}; empty for a pack with none.
  datasetChoices: Record<string, string>;
};

export const initialDraft: Draft = {
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

/** The wizard step that owns the field a 422 names: the basics (name, slug, zone,
 * channel) live on step 2, the pack on step 1, everything else is the config (4). */
export function stepForErrors(details: string[]): number {
  const fields = details.map(
    (detail) =>
      (detail.split(":")[0] ?? "")
        .replace(/^(body\.)?(payload\.)?/, "")
        .split(".")[0],
  );
  if (fields.includes("pack")) return 1;
  if (
    fields.some((f) =>
      ["slug", "name", "timezone", "channel_type"].includes(f ?? ""),
    )
  )
    return 2;
  return 4;
}

export function slugFromName(name: string) {
  return name
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64)
    .replace(/-+$/g, "");
}

export function validSlug(slug: string) {
  return slug.length <= 64 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug);
}

/** The draft kept in sessionStorage, or a fresh one when it is missing or malformed. */
export function restoreDraft(): Draft {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return initialDraft;
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
      return initialDraft;
    return { ...initialDraft, ...value };
  } catch {
    return initialDraft;
  }
}
